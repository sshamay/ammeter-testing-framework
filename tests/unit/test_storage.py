"""T-08: frozen result schema, unique IDs, atomic writes and retrieval."""

import json
import os
import tempfile
import unittest
from unittest.mock import patch

from src.testing.analysis import Statistics
from src.testing.errors import StorageError
from src.testing.storage import (
    build_run_result,
    compare_runs,
    compare_runs_by_id,
    list_runs,
    load_run,
    load_run_result,
    new_run_id,
    save_run,
)


class TestRunResult(unittest.TestCase):
    def test_schema_metadata_and_config_snapshot(self):
        samples = {"greenlee": (1.0, 2.0)}
        result = build_run_result(samples, {"ammeters": {"greenlee": {"port": 5001}}})

        self.assertEqual(result.schema_version, 1)
        self.assertTrue(result.run_id)
        self.assertTrue(result.created_utc)
        self.assertEqual(result.config_snapshot["ammeters"]["greenlee"]["port"], 5001)
        self.assertIsInstance(result.statistics["greenlee"], Statistics)
        self.assertEqual(result.samples["greenlee"], (1.0, 2.0))
        self.assertIn("python_version", result.environment)
        self.assertIn("platform", result.environment)
        self.assertIn("framework_version", result.environment)

    def test_two_runs_in_one_second_have_different_ids(self):
        self.assertNotEqual(new_run_id(), new_run_id())
        self.assertNotEqual(
            build_run_result({"x": (1.0,)}, {}).run_id,
            build_run_result({"x": (1.0,)}, {}).run_id,
        )


class TestStorage(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.results_dir = os.path.join(self.temp_dir.name, "runs")

    def test_save_list_load_round_trip(self):
        result = build_run_result(
            {"greenlee": (1.0, 2.0)},
            {"ammeters": {"greenlee": {"port": 5001}}},
            errors=["entes@5002: connect failed"],
        )
        path = save_run(result, self.results_dir)

        self.assertTrue(path.exists())
        self.assertEqual(list_runs(self.results_dir), (result.run_id,))
        data = load_run(result.run_id, self.results_dir)
        self.assertEqual(data["run_id"], result.run_id)
        self.assertEqual(data["schema_version"], 1)
        self.assertEqual(data["errors"], ["entes@5002: connect failed"])
        self.assertAlmostEqual(data["statistics"]["greenlee"]["mean"], 1.5)
        self.assertEqual(data["config_snapshot"]["ammeters"]["greenlee"]["port"], 5001)

    def test_write_failure_leaves_no_partial_artifact(self):
        result = build_run_result({"greenlee": (1.0,)}, {})
        with patch("src.testing.storage.os.replace", side_effect=OSError("disk full")):
            with self.assertRaises(StorageError):
                save_run(result, self.results_dir)
        self.assertEqual(os.listdir(self.results_dir), [])

    def test_missing_artifact_raises_storage_error(self):
        with self.assertRaises(StorageError):
            load_run("does-not-exist", self.results_dir)

    def test_corrupt_artifact_raises_storage_error(self):
        result = build_run_result({"greenlee": (1.0,)}, {})
        os.makedirs(self.results_dir, exist_ok=True)
        with open(os.path.join(self.results_dir, f"{result.run_id}.json"), "w") as output:
            output.write("not json")
        with self.assertRaises(StorageError):
            load_run(result.run_id, self.results_dir)

    def test_compare_runs_reports_cv_and_drift_deltas(self):
        stable = build_run_result({"greenlee": (1.0, 1.0, 1.0)}, {})
        varying = build_run_result({"greenlee": (1.0, 2.0, 3.0)}, {})
        comparison = compare_runs(stable, varying)

        self.assertIn("greenlee", comparison)
        self.assertGreater(comparison["greenlee"]["cv_delta"], 0)
        self.assertGreater(comparison["greenlee"]["drift_delta"], 0)

    def test_effective_settings_and_environment_are_persisted(self):
        result = build_run_result(
            {"greenlee": (1.0, 2.0)},
            {},
            effective_settings={"sampling": {"count": 2, "frequency_hz": 10}},
            environment={"python_version": "3.14.6"},
        )
        save_run(result, self.results_dir)

        data = load_run(result.run_id, self.results_dir)
        self.assertEqual(
            data["effective_settings"]["sampling"], {"count": 2, "frequency_hz": 10}
        )
        self.assertEqual(data["environment"]["python_version"], "3.14.6")

    def test_load_run_result_rebuilds_the_original_result(self):
        result = build_run_result(
            {"greenlee": (1.0, 2.0)},
            {"ammeters": {"greenlee": {"port": 5001}}},
            ["greenlee@fake:5001: connect failed"],
            effective_settings={"sampling": {"count": 2}},
            environment={"python_version": "3.14.6"},
        )
        save_run(result, self.results_dir)

        self.assertEqual(load_run_result(result.run_id, self.results_dir), result)

    def test_compare_runs_by_id_uses_archived_artifacts(self):
        stable = build_run_result({"greenlee": (1.0, 1.0, 1.0)}, {})
        varying = build_run_result({"greenlee": (1.0, 2.0, 3.0)}, {})
        save_run(stable, self.results_dir)
        save_run(varying, self.results_dir)

        comparison = compare_runs_by_id(
            stable.run_id, varying.run_id, self.results_dir
        )
        self.assertGreater(comparison["greenlee"]["cv_delta"], 0)
        self.assertGreater(comparison["greenlee"]["drift_delta"], 0)

    def test_legacy_artifact_without_new_metadata_still_loads(self):
        result = build_run_result({"greenlee": (1.0, 2.0)}, {})
        path = save_run(result, self.results_dir)
        data = json.loads(path.read_text(encoding="utf-8"))
        data.pop("effective_settings")
        data.pop("environment")
        path.write_text(json.dumps(data), encoding="utf-8")

        loaded = load_run_result(result.run_id, self.results_dir)
        self.assertEqual(loaded.effective_settings, {})
        self.assertEqual(loaded.environment, {})
        self.assertEqual(loaded.samples["greenlee"], (1.0, 2.0))

    def test_artifact_is_valid_json_with_sorted_keys(self):
        result = build_run_result({"x": (2.0,)}, {})
        path = save_run(result, self.results_dir)
        with path.open(encoding="utf-8") as source:
            text = source.read()
        json.loads(text)
        self.assertEqual(list(json.loads(text).keys()), sorted(json.loads(text).keys()))


if __name__ == "__main__":
    unittest.main(verbosity=2)
