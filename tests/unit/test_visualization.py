"""T-11: stdlib visualization writers, guarded matplotlib, and CLI wiring.

CSV/text output must work with no optional packages. PNG rendering is a guarded feature: absent
matplotlib, missing/failed plots become notes instead of exceptions or a non-zero exit status.
"""

import csv
import io
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import MagicMock, patch

import yaml

from src.testing.cli import EXIT_FATAL, EXIT_OK, main
from src.testing.errors import ConfigError, StorageError
from src.testing.storage import RunResult, build_run_result
from src.testing.visualization import (
    DISCLAIMER,
    KNOWN_PLOTS,
    VisualizationArtifacts,
    VisualizationSettings,
    format_table,
    load_visualization_config,
    load_visualization_settings,
    render_plots,
    settings_from_config,
    visualize,
    write_csv,
    write_text_table,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
FROZEN_CONFIG = str(REPO_ROOT / "config" / "config.yaml")


def sample_result(errors=()):
    return build_run_result(
        {"greenlee": (1.0, 2.0, 3.0), "entes": (4.0, 5.0, 6.0)}, {}, errors
    )


def write_config(directory, visualization):
    path = Path(directory) / "config.yaml"
    path.write_text(
        yaml.safe_dump({"analysis": {"visualization": visualization}}), encoding="utf-8"
    )
    return str(path)


def fake_pyplot(save_error=None):
    """A minimal pyplot double whose 'PNG' files are real, non-empty files."""

    def savefig(path, *_args, **_kwargs):
        if save_error is not None:
            raise save_error
        Path(path).write_bytes(b"PNG")

    series_figure, series_axis = MagicMock(), MagicMock()
    series_figure.savefig.side_effect = savefig
    comparison_figure, axes = MagicMock(), (MagicMock(), MagicMock())
    comparison_figure.savefig.side_effect = savefig

    plt = MagicMock()
    plt.subplots.side_effect = [
        (series_figure, series_axis),
        (comparison_figure, axes),
    ]
    return plt, (series_figure, comparison_figure)


class TestSettings(unittest.TestCase):
    def test_frozen_config_merges_under_our_defaults(self):
        settings = load_visualization_settings(FROZEN_CONFIG)
        self.assertTrue(settings.enabled)                     # frozen config says true
        self.assertEqual(settings.backend, "csv")
        self.assertEqual(settings.plot_types, KNOWN_PLOTS)    # frozen plot_types: null -> defaults
        self.assertEqual(settings.directory, "visualizations")

    def test_null_overrides_fall_back_to_defaults(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = write_config(
                temp_dir,
                {"enabled": None, "backend": None, "plot_types": None, "directory": None},
            )
            self.assertEqual(load_visualization_settings(path), VisualizationSettings())

    def test_explicit_values_win_over_defaults(self):
        config = {"enabled": False, "plot_types": ["series"], "directory": "charts"}
        self.assertEqual(
            settings_from_config({"analysis": {"visualization": config}}),
            VisualizationSettings(enabled=False, plot_types=("series",), directory="charts"),
        )

    def test_invalid_settings_raise_config_error(self):
        cases = (
            {"enabled": "yes"},
            {"backend": "png"},
            {"plot_types": "series"},
            {"plot_types": ["bogus"]},
            {"directory": ""},
            42,  # visualization must be a mapping
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            for index, value in enumerate(cases):
                with self.subTest(value=value):
                    path = write_config(temp_dir, value)
                    with self.assertRaises(ConfigError):
                        load_visualization_settings(path)

    def test_invalid_analysis_section_raises_config_error(self):
        with self.assertRaises(ConfigError):
            settings_from_config({"analysis": 42})

    def test_unreadable_config_raises_config_error(self):
        with self.assertRaises(ConfigError):
            load_visualization_config(str(REPO_ROOT / "config" / "does-not-exist.yaml"))


class TestFormatTable(unittest.TestCase):
    def test_every_metric_is_rendered_for_every_ammeter(self):
        text = format_table(sample_result())
        for expected in (
            "ammeter", "mean", "median", "stddev", "min", "max", "CV", "drift",
            "greenlee", "entes",
            "0.8165",  # population stddev of (1, 2, 3)
            "0.4082",  # CV = stddev / mean
            "+1.5000",  # drift = 3 - mean(1, 2)
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, text)
        self.assertLess(text.index("entes"), text.index("greenlee"))  # deterministic order

    def test_empty_statistics_get_an_explanatory_line(self):
        self.assertIn("(no ammeter produced readings)", format_table(RunResult("id", "now", {}, {}, {})))


class TestCSVWriter(unittest.TestCase):
    def test_exact_rows_one_file_per_ammeter(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            paths = write_csv(sample_result(), directory)
            self.assertEqual([path.name for path in paths], ["entes.csv", "greenlee.csv"])
            with paths[0].open(encoding="utf-8", newline="") as source:
                self.assertEqual(
                    list(csv.reader(source)),
                    [["index", "current"], ["1", "4.0"], ["2", "5.0"], ["3", "6.0"]],
                )

    def test_write_failure_becomes_storage_error(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            (directory / "entes.csv").mkdir()  # a directory where the file should go
            with self.assertRaises(StorageError):
                write_csv(sample_result(), directory)


class TestTextTableWriter(unittest.TestCase):
    def test_includes_metrics_errors_notes_and_disclaimer(self):
        result = sample_result(["entes@fake:5002: timeout"])
        with tempfile.TemporaryDirectory() as temp_dir:
            path = write_text_table(result, Path(temp_dir), ["matplotlib not installed - PNG plots skipped"])
            text = path.read_text(encoding="utf-8")
        for expected in ("ammeter", "CV", "drift", "Errors (1)", "timeout", "Note: matplotlib", DISCLAIMER):
            with self.subTest(expected=expected):
                self.assertIn(expected, text)

    def test_write_failure_becomes_storage_error(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            (Path(temp_dir) / "summary.txt").mkdir()
            with self.assertRaises(StorageError):
                write_text_table(sample_result(), Path(temp_dir))


class TestGuardedPlotting(unittest.TestCase):
    def test_absent_matplotlib_skips_cleanly(self):
        with patch("src.testing.visualization._load_pyplot", return_value=None):
            paths, skipped = render_plots(sample_result(), Path("unused"), VisualizationSettings())
        self.assertEqual(paths, ())
        self.assertEqual(skipped, ("matplotlib not installed - PNG plots skipped",))

    def test_present_matplotlib_writes_nonempty_pngs(self):
        plt, figures = fake_pyplot()
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            with patch("src.testing.visualization._load_pyplot", return_value=plt):
                paths, skipped = render_plots(sample_result(), directory, VisualizationSettings())
            self.assertEqual([path.name for path in paths], ["series.png", "comparison.png"])
            self.assertEqual(skipped, ())
            for path in paths:
                with self.subTest(path=path):
                    self.assertGreater(path.stat().st_size, 0)
            self.assertEqual(plt.close.call_count, len(figures))

    def test_plot_render_failure_is_a_note_not_a_crash(self):
        plt, _ = fake_pyplot(save_error=OSError("disk full"))
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch("src.testing.visualization._load_pyplot", return_value=plt):
                paths, skipped = render_plots(sample_result(), Path(temp_dir), VisualizationSettings())
        self.assertEqual(paths, ())
        self.assertEqual(len(skipped), 2)
        self.assertTrue(all("disk full" in note for note in skipped))

    def test_empty_plot_types_render_nothing(self):
        plt, _ = fake_pyplot()
        with patch("src.testing.visualization._load_pyplot", return_value=plt):
            paths, skipped = render_plots(
                sample_result(), Path("unused"), VisualizationSettings(plot_types=())
            )
        self.assertEqual((paths, skipped), ((), ()))
        plt.subplots.assert_not_called()


class TestVisualizeOrchestrator(unittest.TestCase):
    def test_disabled_writes_nothing(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            artifacts = visualize(sample_result(), temp_dir, VisualizationSettings(enabled=False))
        self.assertEqual(artifacts, VisualizationArtifacts())
        self.assertFalse((Path(temp_dir) / "visualizations").exists())

    def test_enabled_writes_all_outputs(self):
        result = sample_result()
        plt, _ = fake_pyplot()
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch("src.testing.visualization._load_pyplot", return_value=plt):
                artifacts = visualize(result, temp_dir)
            self.assertEqual(artifacts.directory, Path(temp_dir) / "visualizations" / result.run_id)
            self.assertEqual([path.name for path in artifacts.csv_paths], ["entes.csv", "greenlee.csv"])
            self.assertEqual(artifacts.table_path.name, "summary.txt")
            self.assertEqual([path.name for path in artifacts.plot_paths], ["series.png", "comparison.png"])
            self.assertEqual(artifacts.skipped, ())
            self.assertTrue(artifacts.table_path.exists())

    def test_skip_note_reaches_the_summary_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch("src.testing.visualization._load_pyplot", return_value=None):
                artifacts = visualize(sample_result(), temp_dir)
            self.assertTrue(artifacts.skipped)
            self.assertIn("matplotlib not installed", artifacts.table_path.read_text(encoding="utf-8"))


class TestCLIVisualization(unittest.TestCase):
    def run_cli(self, args, config, results_dir):
        result = sample_result()
        with patch("src.testing.cli.AmmeterTestFramework") as framework:
            framework.return_value.config = config
            framework.return_value.run_test.return_value = result
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["--results-dir", str(results_dir)] + args)
        return code, output.getvalue(), result

    def test_default_run_writes_csv_and_text_and_reports_skip(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            results_dir = Path(temp_dir) / "runs"
            with patch("src.testing.visualization._load_pyplot", return_value=None):
                code, output, result = self.run_cli([], {}, results_dir)
            directory = results_dir / "visualizations" / result.run_id
            self.assertEqual(code, EXIT_OK)
            self.assertEqual(
                sorted(path.name for path in directory.iterdir()),
                ["entes.csv", "greenlee.csv", "summary.txt"],
            )
            self.assertIn("Note: matplotlib not installed", output)

    def test_no_visualize_flag_skips_all_output(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            results_dir = Path(temp_dir) / "runs"
            code, output, _ = self.run_cli(["--no-visualize"], {}, results_dir)
            self.assertEqual(code, EXIT_OK)
            self.assertFalse((results_dir / "visualizations").exists())
            self.assertNotIn("Note:", output)

    def test_config_can_disable_visualization(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            results_dir = Path(temp_dir) / "runs"
            config = {"analysis": {"visualization": {"enabled": False}}}
            code, _, _ = self.run_cli([], config, results_dir)
            self.assertEqual(code, EXIT_OK)
            self.assertFalse((results_dir / "visualizations").exists())

    def test_invalid_visualization_config_is_fatal(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config = {"analysis": {"visualization": {"backend": "png"}}}
            with patch("src.testing.cli.AmmeterTestFramework") as framework:
                framework.return_value.config = config
                errors = io.StringIO()
                with redirect_stderr(errors):
                    code = main(["--results-dir", temp_dir])
            self.assertEqual(code, EXIT_FATAL)
            self.assertIn("ConfigError", errors.getvalue())


if __name__ == "__main__":
    unittest.main(verbosity=2)
