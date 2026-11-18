"""Regular unittest run that produces sample results and visualizations (T-14, part A).

No separate process and no change to the frozen ``main.py``: this file imports ``build_emulators``
from it, starts the three emulators in threads, and drives ``AmmeterTestFramework`` directly.

By default the campaign runs into a temp directory, so the regression suite stays read-only. Set
``AMMETER_WRITE_SAMPLE=1`` to write the same artifacts under ``results/sample/``. One such campaign
is the committed "Sample test results" deliverable; further runs are left untracked:

    AMMETER_WRITE_SAMPLE=1 python -m unittest tests.system.test_sample_results
"""

import importlib.util
import io
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from main import build_emulators, load_config

from src.testing.storage import load_run
from src.testing.test_framework import AmmeterTestFramework
from src.testing.visualization import visualize
from tests.emulator_helpers import start_emulator, wait_until_listening

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = REPO_ROOT / "config" / "config.yaml"
SAMPLE_DIR = REPO_ROOT / "results" / "sample"
AMMETERS = ("circutor", "entes", "greenlee")
WRITE_SAMPLE = os.environ.get("AMMETER_WRITE_SAMPLE") == "1"


class TestSampleResults(unittest.TestCase):
    """A normal test-file run that measures, archives and visualizes a full campaign."""

    @classmethod
    def setUpClass(cls):
        # Import, never edit, the frozen main.py: its builder also checks the configured commands.
        config = load_config(str(CONFIG_PATH))
        emulators = build_emulators(config)
        for emulator in emulators.values():
            start_emulator(emulator)
        for emulator in emulators.values():
            if not wait_until_listening(emulator.port):
                raise AssertionError(f"emulator did not start on port {emulator.port}")

    def run_campaign(self, results_dir: Path):
        framework = AmmeterTestFramework(
            config_path=str(CONFIG_PATH), results_dir=str(results_dir)
        )
        with redirect_stdout(io.StringIO()):  # the frozen emulators are chatty
            result = framework.run_test()
            artifacts = visualize(result, str(results_dir))
        return result, artifacts

    def assert_outputs(self, results_dir: Path):
        result, artifacts = self.run_campaign(results_dir)

        data = load_run(result.run_id, str(results_dir))
        self.assertEqual(data["errors"], [])
        self.assertEqual(set(data["statistics"]), set(AMMETERS))
        for name in AMMETERS:
            with self.subTest(ammeter=name):
                self.assertEqual(len(data["samples"][name]), 20)  # our config-driven default

        self.assertEqual(artifacts.directory, results_dir / "visualizations" / result.run_id)
        self.assertEqual({path.name for path in artifacts.csv_paths}, {f"{name}.csv" for name in AMMETERS})
        self.assertTrue(artifacts.table_path.is_file())
        table = artifacts.table_path.read_text(encoding="utf-8")
        self.assertIn("CV", table)
        self.assertIn("Precision/stability only", table)
        if importlib.util.find_spec("matplotlib") is not None:
            self.assertEqual({path.name for path in artifacts.plot_paths}, {"series.png", "comparison.png"})
            self.assertTrue(all(path.stat().st_size > 0 for path in artifacts.plot_paths))
        else:
            self.assertTrue(any("matplotlib" in note for note in artifacts.skipped))
        return result

    def test_campaign_writes_json_and_visualization(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            self.assert_outputs(Path(temp_dir))
        if WRITE_SAMPLE:
            SAMPLE_DIR.mkdir(parents=True, exist_ok=True)
            self.assert_outputs(SAMPLE_DIR)


if __name__ == "__main__":
    unittest.main(verbosity=2)
