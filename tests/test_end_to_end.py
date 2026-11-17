"""T-10: system-level evidence — artifact shape, batch hygiene, clean-export run twice."""

import io
import subprocess
import sys
import tarfile
import tempfile
import threading
import unittest
from contextlib import redirect_stdout
from pathlib import Path

import yaml

from Ammeters.Circutor_Ammeter import CircutorAmmeter
from Ammeters.Entes_Ammeter import EntesAmmeter
from Ammeters.Greenlee_Ammeter import GreenleeAmmeter

from src.testing.adapters.fake import FakeAmmeterAdapter
from src.testing.sampler import SamplingSettings
from src.testing.storage import list_runs, load_run
from src.testing.test_framework import AmmeterTestFramework
from tests.emulator_helpers import free_port, start_emulator, wait_until_listening
from tests.test_framework import (
    GOOD, NAMES, FakeClock, scripted_adapter_class, write_config,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
COMMANDS = {
    "greenlee": "MEASURE_GREENLEE -get_measurement",
    "entes": "MEASURE_ENTES -get_data",
    "circutor": "MEASURE_CIRCUTOR -get_measurement -current",
}
ARTIFACT_KEYS = {
    "run_id", "created_utc", "config_snapshot", "statistics",
    "samples", "errors", "schema_version",
}
STAT_KEYS = {"count", "mean", "median", "stddev", "min", "max", "cv", "drift"}


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
        self.assertEqual(set(data["statistics"]), set(NAMES))
        self.assertEqual(set(data["samples"]), set(NAMES))
        for name in NAMES:
            with self.subTest(ammeter=name):
                self.assertEqual(set(data["statistics"][name]), STAT_KEYS)
                self.assertEqual(data["samples"][name], list(GOOD[name]))
        self.assertEqual(data["config_snapshot"]["ammeters"]["greenlee"]["port"], 5001)


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
    def test_cli_runs_twice_from_a_clean_git_export(self):
        with tempfile.TemporaryDirectory() as temp_dir, redirect_stdout(io.StringIO()):
            archive = subprocess.run(
                ["git", "archive", "HEAD"], cwd=REPO_ROOT, capture_output=True, check=True
            ).stdout
            export = Path(temp_dir) / "export"
            export.mkdir()
            with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
                tar.extractall(export, filter="data")

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
                sys.executable, "-m", "src.testing",
                "--config", str(config_path),
                "--results-dir", str(results_dir),
            ]
            for attempt in range(2):
                completed = subprocess.run(
                    command, cwd=export, capture_output=True, text=True, timeout=60
                )
                self.assertEqual(completed.returncode, 0, completed.stderr + completed.stdout)
                self.assertEqual(completed.stderr, "", "unclassified traceback on stderr")
                self.assertIn("3 of 3 ammeters measured", completed.stdout)

            identifiers = list_runs(str(results_dir))
            self.assertEqual(len(identifiers), 2)
            self.assertEqual(len(set(identifiers)), 2)
            for run_id in identifiers:
                self.assertEqual(set(load_run(run_id, str(results_dir))["statistics"]), set(COMMANDS))


if __name__ == "__main__":
    unittest.main(verbosity=2)
