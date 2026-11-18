"""T-10: system-level evidence — artifact shape, batch hygiene, clean-export run twice."""

import io
import os
import signal
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

from Ammeters.Circutor_Ammeter import CircutorAmmeter
from Ammeters.Entes_Ammeter import EntesAmmeter
from Ammeters.Greenlee_Ammeter import GreenleeAmmeter

from src.testing.adapters.fake import FakeAmmeterAdapter
from src.testing.errors import TransportError, describe
from src.testing.sampler import SamplingSettings
from src.testing.storage import list_runs, load_run
from src.testing.test_framework import AmmeterTestFramework
from src.testing.visualization import visualize
from tests.emulator_helpers import free_port, start_emulator, wait_until_listening
from tests.support import (
    COMMANDS,
    GOOD,
    NAMES,
    FakeClock,
    scripted_adapter_class,
    write_config,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
ARTIFACT_KEYS = {
    "run_id", "created_utc", "config_snapshot", "statistics",
    "samples", "errors", "recovered", "schema_version", "effective_settings", "environment",
}
STAT_KEYS = {"count", "mean", "median", "stddev", "min", "max", "cv", "drift"}

# Executed with ``python -c`` and cwd=<clean git export>, so its imports resolve from the export
# tree rather than from the repository running the suite. No CLI module exists any more.
CLEAN_EXPORT_RUNNER = """
import sys

from src.testing.test_framework import AmmeterTestFramework
from src.testing.visualization import settings_from_config, visualize

config_path, results_dir = sys.argv[1], sys.argv[2]
framework = AmmeterTestFramework(config_path=config_path, results_dir=results_dir)
result = framework.run_test()
visualize(result, results_dir, settings_from_config(framework.config))
print(f"MEASURED {len(result.statistics)}")
for error in result.errors:
    print(error, file=sys.stderr)
sys.exit(1 if result.errors else 0)
"""


def safe_extract(archive, destination):
    """Extract our own ``git archive`` without tarfile's version-specific ``filter`` argument.

    Python < 3.12 has no ``filter=``, and older patch releases of 3.10/3.11 lack its backport.
    Validate the members ourselves (paths stay inside the destination, no links or devices) so
    plain ``extractall`` is safe on every supported interpreter.
    """
    root = destination.resolve()
    for member in archive.getmembers():
        target = (destination / member.name).resolve()
        if not target.is_relative_to(root):
            raise ValueError(f"unsafe archive path: {member.name}")
        if member.issym() or member.islnk() or member.isdev() or member.isfifo():
            raise ValueError(f"unsupported archive entry: {member.name}")
    archive.extractall(destination)


def build_framework(config_path, results_dir, *, adapters=None, adapter_class=None):
    return AmmeterTestFramework(
        config_path,
        adapters=adapters,
        adapter_class=adapter_class or scripted_adapter_class(GOOD),
        clock=FakeClock(),
        settings=SamplingSettings(max_attempts=2, backoff_seconds=0.01),
        results_dir=results_dir,
    )


class TestArtifactShape(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.config_path = write_config(self.temp.name)
        self.results_dir = str(Path(self.temp.name) / "runs")

    def test_artifact_matches_golden_shape(self):
        result = build_framework(self.config_path, self.results_dir).run_test()
        data = load_run(result.run_id, self.results_dir)

        self.assertEqual(set(data), ARTIFACT_KEYS)
        self.assertEqual(data["schema_version"], 1)
        self.assertEqual(data["errors"], [])
        self.assertEqual(data["recovered"], [])
        self.assertEqual(set(data["statistics"]), set(NAMES))
        self.assertEqual(set(data["samples"]), set(NAMES))
        for name in NAMES:
            with self.subTest(ammeter=name):
                self.assertEqual(set(data["statistics"][name]), STAT_KEYS)
                self.assertEqual(data["samples"][name], list(GOOD[name]))
        self.assertEqual(data["config_snapshot"]["ammeters"]["greenlee"]["port"], 5001)


class TestRecoveredEvidence(unittest.TestCase):
    """A recovered fault must survive from sampling through the artifact to summary.txt."""

    def test_transient_recovery_reaches_artifact_and_summary(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = write_config(temp_dir)
            results_dir = str(Path(temp_dir) / "runs")
            scripts = dict(GOOD)
            scripts["entes"] = (
                TransportError(describe("entes", 5002, "fake", "transient")),
                5.0,
                5.1,
                4.9,
            )
            framework = build_framework(
                config_path, results_dir, adapter_class=scripted_adapter_class(scripts)
            )
            result = framework.run_test()
            with patch("src.testing.visualization._load_pyplot", return_value=None):
                artifacts = visualize(result, results_dir)

            data = load_run(result.run_id, results_dir)
            self.assertEqual(data["errors"], [])
            self.assertEqual(len(data["recovered"]), 1)
            self.assertIn("entes@fake:5002: transient", data["recovered"][0])
            self.assertEqual(result.samples["entes"], (5.0, 5.1, 4.9))
            summary = artifacts.table_path.read_text(encoding="utf-8")
            self.assertIn("Recovered (1):", summary)
            self.assertIn(data["recovered"][0], summary)


class TestBatchHygiene(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.config_path = write_config(self.temp.name)
        self.results_dir = str(Path(self.temp.name) / "runs")

    def test_no_connection_or_thread_leak_across_a_batch(self):
        config = yaml.safe_load(Path(self.config_path).read_text(encoding="utf-8"))
        adapters = {}
        instances = []
        for name, settings in config["ammeters"].items():
            adapter = FakeAmmeterAdapter(
                name=name, values=GOOD[name], port=settings["port"],
                command=settings["command"].encode("utf-8"),
            )
            adapter.opens = 0
            adapter.closes = 0
            original_open, original_close = adapter.open, adapter.close

            def counted_open(timeout=None, _adapter=adapter, _open=original_open):
                _adapter.opens += 1
                _open(timeout)

            def counted_close(_adapter=adapter, _close=original_close):
                _adapter.closes += 1
                _close()

            adapter.open, adapter.close = counted_open, counted_close
            adapters[name] = adapter
            instances.append(adapter)

        before = threading.active_count()
        build_framework(self.config_path, self.results_dir, adapters=adapters).run_test()
        self.assertEqual(threading.active_count(), before)
        for adapter in instances:
            with self.subTest(ammeter=adapter.name):
                self.assertEqual(adapter.opens, 3)
                self.assertEqual(adapter.closes, adapter.opens)
                self.assertFalse(adapter.is_open)
                self.assertEqual(adapter.reads, 3)


class TestCleanExport(unittest.TestCase):
    def test_run_test_runs_twice_from_a_clean_git_export(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            archive = subprocess.run(
                ["git", "archive", "HEAD"], cwd=REPO_ROOT, capture_output=True, check=True
            ).stdout
            export = Path(temp_dir) / "export"
            export.mkdir()
            with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
                safe_extract(tar, export)

            ports = {name: free_port() for name in COMMANDS}
            config = {
                "testing": {
                    "sampling": {
                        "measurements_count": 2,
                        "total_duration_seconds": None,
                        "sampling_frequency_hz": 100,
                    }
                },
                "ammeters": {
                    name: {"port": port, "command": COMMANDS[name]}
                    for name, port in ports.items()
                },
            }
            config_path = Path(temp_dir) / "config.yaml"
            config_path.write_text(yaml.safe_dump(config), encoding="utf-8")

            for server_class, name in (
                (GreenleeAmmeter, "greenlee"),
                (EntesAmmeter, "entes"),
                (CircutorAmmeter, "circutor"),
            ):
                start_emulator(server_class(ports[name]))
            for port in ports.values():
                self.assertTrue(wait_until_listening(port))

            results_dir = Path(temp_dir) / "runs"
            command = [
                sys.executable, "-c", CLEAN_EXPORT_RUNNER,
                str(config_path), str(results_dir),
            ]
            for attempt in range(2):
                completed = subprocess.run(
                    command, cwd=export, capture_output=True, text=True, timeout=60
                )
                self.assertEqual(completed.returncode, 0, completed.stderr + completed.stdout)
                self.assertEqual(completed.stderr, "", "unclassified traceback on stderr")
                self.assertIn("MEASURED 3", completed.stdout)

            identifiers = list_runs(str(results_dir))
            self.assertEqual(len(identifiers), 2)
            self.assertEqual(len(set(identifiers)), 2)
            for run_id in identifiers:
                data = load_run(run_id, str(results_dir))
                self.assertEqual(set(data["statistics"]), set(COMMANDS))
                self.assertEqual(data["errors"], [])


class TestFrozenMainScript(unittest.TestCase):
    """The supplied main.py must return one reading from every configured ammeter."""

    def test_main_returns_one_reading_per_ammeter(self):
        # Run from a temp cwd with free ports so lingering daemon emulators from other tests
        # cannot collide with the fixed ports in the frozen config.
        with tempfile.TemporaryDirectory() as temp_dir:
            ports = {name: free_port() for name in COMMANDS}
            config = {
                "ammeters": {
                    name: {"port": port, "command": COMMANDS[name]}
                    for name, port in ports.items()
                }
            }
            config_dir = Path(temp_dir) / "config"
            config_dir.mkdir()
            (config_dir / "config.yaml").write_text(
                yaml.safe_dump(config), encoding="utf-8"
            )
            env = dict(os.environ, PYTHONPATH=str(REPO_ROOT))
            completed = subprocess.run(
                [sys.executable, str(REPO_ROOT / "main.py")],
                cwd=temp_dir,
                env=env,
                capture_output=True,
                text=True,
                timeout=30,
            )

        self.assertEqual(completed.returncode, 0, completed.stderr + completed.stdout)
        self.assertEqual(completed.stderr, "")
        self.assertEqual(
            completed.stdout.count("Received current measurement from port"),
            len(COMMANDS),
        )
        for name, port in ports.items():
            with self.subTest(ammeter=name):
                self.assertRegex(
                    completed.stdout,
                    rf"Received current measurement from port {port}: [-+0-9.eE]+ A",
                )
        self.assertNotIn("Error from port", completed.stdout)
        self.assertNotIn("No data received", completed.stdout)


class TestInterruptedRun(unittest.TestCase):
    """Ctrl-C stops the frozen main.py with a message instead of a traceback."""

    def test_ctrl_c_exits_without_traceback(self):
        # Windows has no POSIX SIGINT for a child: use a new process group and CTRL_BREAK_EVENT,
        # which Python still turns into KeyboardInterrupt. POSIX keeps the ordinary SIGINT path.
        if os.name == "nt":
            process = subprocess.Popen(
                [sys.executable, "main.py"],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
            )
            interrupt = signal.CTRL_BREAK_EVENT
        else:
            process = subprocess.Popen(
                [sys.executable, "main.py"],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
            interrupt = signal.SIGINT
        try:
            time.sleep(1.5)
            if process.poll() is not None:
                self.skipTest("main.py finished before the interrupt could be sent")
            process.send_signal(interrupt)
            output, _ = process.communicate(timeout=20)
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()

        self.assertNotIn("Traceback", output)
        self.assertNotIn("KeyboardInterrupt", output)
        self.assertIn("Stopped by user.", output)
        self.assertEqual(process.returncode, 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
