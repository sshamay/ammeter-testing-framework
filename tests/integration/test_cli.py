"""T-09: CLI presentation, exit codes, and the real ``python -m src.testing`` entry point."""

import importlib.util
import io
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

import yaml

from Ammeters.Circutor_Ammeter import CircutorAmmeter
from Ammeters.Entes_Ammeter import EntesAmmeter
from Ammeters.Greenlee_Ammeter import GreenleeAmmeter

from src.testing.analysis import compute_statistics
from src.testing.cli import EXIT_FATAL, EXIT_OK, EXIT_PARTIAL, build_parser, format_summary, main
from src.testing.errors import ConfigError
from src.testing.storage import RunResult, list_runs, load_run
from src.testing.visualization import VisualizationSettings
from tests.emulator_helpers import free_port, start_emulator, wait_until_listening
from tests.support import COMMANDS

REPO_ROOT = Path(__file__).resolve().parents[2]


def canned_result(errors=()):
    return RunResult(
        run_id="20260101T000000Z-test00000001",
        created_utc="2026-01-01T00:00:00+00:00",
        config_snapshot={},
        statistics={"greenlee": compute_statistics([1.0, 2.0])},
        samples={"greenlee": (1.0, 2.0)},
        errors=tuple(errors),
    )


class TestCLIParser(unittest.TestCase):
    def test_defaults(self):
        args = build_parser().parse_args([])
        self.assertEqual(args.config, "config/config.yaml")
        self.assertEqual(args.ammeter, "all")
        self.assertEqual(args.results_dir, "results/runs")
        self.assertFalse(args.no_save)

    def test_custom_arguments(self):
        args = build_parser().parse_args(
            ["--config", "x.yaml", "--ammeter", "entes", "--results-dir", "tmp/runs", "--no-save"]
        )
        self.assertEqual(args.config, "x.yaml")
        self.assertEqual(args.ammeter, "entes")
        self.assertEqual(args.results_dir, "tmp/runs")
        self.assertTrue(args.no_save)


class TestCLIMain(unittest.TestCase):
    def setUp(self):
        # These tests mock the framework, so there is no real config to derive visualization
        # settings from. Disabling them keeps presentation unit tests off disk.
        patcher = patch(
            "src.testing.cli.settings_from_config",
            return_value=VisualizationSettings(enabled=False),
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_exit_zero_when_every_ammeter_is_measured(self):
        with patch("src.testing.cli.AmmeterTestFramework") as framework:
            framework.return_value.run_test.return_value = canned_result()
            output = io.StringIO()
            with redirect_stdout(output):
                code = main([])

        self.assertEqual(code, EXIT_OK)
        self.assertIn("Run 20260101T000000Z", output.getvalue())
        framework.return_value.run_test.assert_called_once_with("all", save=True)

    def test_exit_partial_and_error_shown_when_one_ammeter_fails(self):
        error = "entes@fake:5002: ParseError: non-numeric reply"
        with patch("src.testing.cli.AmmeterTestFramework") as framework:
            framework.return_value.run_test.return_value = canned_result([error])
            output = io.StringIO()
            with redirect_stdout(output):
                code = main([])

        self.assertEqual(code, EXIT_PARTIAL)
        self.assertIn(error, output.getvalue())
        self.assertIn("Errors (1)", output.getvalue())

    def test_exit_fatal_on_typed_config_error(self):
        with patch("src.testing.cli.AmmeterTestFramework", side_effect=ConfigError("bad config")):
            errors = io.StringIO()
            with redirect_stderr(errors):
                code = main([])

        self.assertEqual(code, EXIT_FATAL)
        self.assertIn("ConfigError: bad config", errors.getvalue())

    def test_no_save_flag_reaches_run_test(self):
        with patch("src.testing.cli.AmmeterTestFramework") as framework:
            framework.return_value.run_test.return_value = canned_result()
            with redirect_stdout(io.StringIO()):
                main(["--no-save"])
        framework.return_value.run_test.assert_called_once_with("all", save=False)

    def test_selected_ammeter_reaches_run_test(self):
        with patch("src.testing.cli.AmmeterTestFramework") as framework:
            framework.return_value.run_test.return_value = canned_result()
            with redirect_stdout(io.StringIO()):
                main(["--config", "x.yaml", "--ammeter", "entes", "--results-dir", "tmp/runs"])
        framework.assert_called_once_with(config_path="x.yaml", results_dir="tmp/runs")
        framework.return_value.run_test.assert_called_once_with("entes", save=True)


class TestSummary(unittest.TestCase):
    def test_table_shows_precision_metrics_and_limits_the_accuracy_claim(self):
        text = format_summary(canned_result(), "tmp/runs")
        for expected in (
            "ammeter", "mean", "stddev", "CV", "drift",
            "Precision/stability only", "V*s, not amperes",
            "tmp/runs/20260101T000000Z-test00000001.json",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, text)

    def test_no_save_summary_does_not_claim_an_artifact(self):
        text = format_summary(canned_result(), "tmp/runs", saved=False)
        self.assertIn("not saved (--no-save)", text)
        self.assertNotIn("tmp/runs/", text)

    def test_summary_handles_a_run_with_no_data(self):
        result = RunResult("id", "now", {}, {}, {}, errors=("entes down",))
        text = format_summary(result)
        self.assertIn("(no ammeter produced readings)", text)
        self.assertIn("entes down", text)


class TestModuleEntryPoint(unittest.TestCase):
    def test_python_m_src_testing_help(self):
        completed = subprocess.run(
            [sys.executable, "-m", "src.testing", "--help"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("usage: python -m src.testing", completed.stdout)

    def test_yaml_to_artifact_against_live_emulators(self):
        """The T-09 system test: one CLI invocation measures all three and archives a result."""
        with tempfile.TemporaryDirectory() as temp_dir, redirect_stdout(io.StringIO()):
            ports = {name: free_port() for name in COMMANDS}
            config = {
                "testing": {
                    "sampling": {
                        "measurements_count": 3,
                        "total_duration_seconds": None,
                        "sampling_frequency_hz": 100,
                    }
                },
                "ammeters": {
                    name: {"port": port, "command": COMMANDS[name]}
                    for name, port in ports.items()
                },
                "analysis": {"statistical_metrics": None},
                "result_management": {"storage": None},
            }
            config_path = Path(temp_dir) / "config.yaml"
            config_path.write_text(yaml.safe_dump(config), encoding="utf-8")

            servers = [
                (GreenleeAmmeter, ports["greenlee"]),
                (EntesAmmeter, ports["entes"]),
                (CircutorAmmeter, ports["circutor"]),
            ]
            for server_class, port in servers:
                start_emulator(server_class(port))
            for port in ports.values():
                self.assertTrue(wait_until_listening(port), f"emulator on {port} did not start")

            results_dir = Path(temp_dir) / "runs"
            command = [
                sys.executable, "-m", "src.testing",
                "--config", str(config_path),
                "--results-dir", str(results_dir),
            ]
            first = subprocess.run(
                command, cwd=REPO_ROOT, capture_output=True, text=True, timeout=60
            )
            self.assertEqual(first.returncode, 0, first.stderr + first.stdout)
            self.assertEqual(first.stderr, "", "unclassified traceback on stderr")
            self.assertIn("3 of 3 ammeters measured", first.stdout)

            identifiers = list_runs(str(results_dir))
            self.assertEqual(len(identifiers), 1)
            data = load_run(identifiers[0], str(results_dir))
            self.assertEqual(set(data["statistics"]), set(COMMANDS))
            self.assertEqual(data["errors"], [])
            self.assertEqual(data["config_snapshot"]["ammeters"]["entes"]["port"], ports["entes"])
            for name in COMMANDS:
                self.assertEqual(len(data["samples"][name]), 3)

            # The default CLI run also produces stdlib visualization artifacts in the same tree.
            visual_dir = results_dir / "visualizations" / identifiers[0]
            expected_files = {f"{name}.csv" for name in COMMANDS} | {"summary.txt"}
            if importlib.util.find_spec("matplotlib") is not None:
                expected_files |= {"series.png", "comparison.png"}
            self.assertTrue(expected_files.issubset({path.name for path in visual_dir.iterdir()}))

            second = subprocess.run(
                command, cwd=REPO_ROOT, capture_output=True, text=True, timeout=60
            )
            self.assertEqual(second.returncode, 0, second.stderr + second.stdout)
            self.assertEqual(second.stderr, "", "unclassified traceback on stderr")
            self.assertEqual(len(list_runs(str(results_dir))), 2)
            self.assertEqual(len(set(identifiers + tuple(list_runs(str(results_dir))))), 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
