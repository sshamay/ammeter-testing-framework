"""T-04: the 18 config cases from the plan (appendix §4.2).

Run from the repository root:

    python -m unittest discover -s tests -v
"""

import os
import tempfile
import unittest
from unittest.mock import patch

from src.testing.errors import ConfigError
from src.testing.sampling import SamplingPlan, load_sampling_plan, resolve_sampling
from src.utils.config import load_config

CONFIG_PATH = "config/config.yaml"


def sampling(count=None, duration=None, frequency=None, ceiling=None):
    data = {
        "measurements_count": count,
        "total_duration_seconds": duration,
        "sampling_frequency_hz": frequency,
    }
    if ceiling is not None:
        data["max_sampling_frequency_hz"] = ceiling
    return data


# Expected plan is (count, frequency_hz, duration_seconds); expected error is a message fragment.
CASES = [
    ("C-01", sampling(100, None, 10), (100, 10.0, 10.0), None),
    ("C-02", sampling(100, 10, None), (100, 10.0, 10.0), None),
    ("C-03", sampling(None, 10, 10), (100, 10.0, 10.0), None),
    ("C-04", sampling(100, 10.0, 10), (100, 10.0, 10.0), None),
    ("C-05", sampling(100, 10.1, 10), (100, 10.0, 10.0), None),
    ("C-06", sampling(100, 10.11, 10), None, "disagrees"),
    ("C-07", sampling(None, None, 10), None, "count or duration"),
    ("C-08", sampling(None, None, None), None, "count or duration"),
    ("C-09", sampling(0, None, 10), None, ">= 1"),
    ("C-10", sampling(-5, None, 10), None, ">= 1"),
    ("C-11", sampling(100, 0, None), None, "greater than 0"),
    ("C-12", sampling(100, -1, None), None, "greater than 0"),
    ("C-13", sampling(100, None, 0), None, "greater than 0"),
    ("C-14", sampling(None, 10, 5000), None, "1000"),
    ("C-15", sampling(None, 10, 1000), (10000, 1000.0, 10.0), None),
    ("C-16", sampling(100.5, None, 10), None, "integer"),
    ("C-17", sampling("100", None, 10), None, "integer"),
    ("C-18", sampling(float("nan"), None, 10), None, "finite"),
]


class TestResolveSampling(unittest.TestCase):
    def test_all_18_config_cases(self):
        for case_id, data, expected, error_message in CASES:
            with self.subTest(case=case_id):
                if error_message is not None:
                    with self.assertRaises(ConfigError) as context:
                        resolve_sampling(data)
                    self.assertIn(error_message, str(context.exception))
                else:
                    plan = resolve_sampling(data)
                    self.assertIsInstance(plan, SamplingPlan)
                    self.assertEqual(plan.count, expected[0])
                    self.assertAlmostEqual(plan.frequency_hz, expected[1])
                    self.assertAlmostEqual(plan.duration_seconds, expected[2])

    def test_count_only_reports_missing_duration(self):
        """A lone count must fail with a typed, specific error — never a bare assert."""
        with self.assertRaises(ConfigError) as context:
            resolve_sampling(sampling(100, None, None))
        self.assertIn("total_duration_seconds is required when only count is set", str(context.exception))

    def test_duration_only_reports_missing_frequency(self):
        """A lone duration must fail with a typed, specific error — never a bare assert."""
        with self.assertRaises(ConfigError) as context:
            resolve_sampling(sampling(None, 10, None))
        self.assertIn("sampling_frequency_hz is required when only duration is set", str(context.exception))

    def test_invalid_config_opens_no_socket(self):
        with patch("socket.socket", side_effect=AssertionError("socket opened")):
            with self.assertRaises(ConfigError):
                resolve_sampling(sampling(None, None, None))

    def test_frozen_config_is_not_edited_but_is_runnable(self):
        config = load_config("config/config.yaml")
        self.assertIsNone(config["testing"]["sampling"]["measurements_count"])
        self.assertIsNone(config["testing"]["sampling"]["sampling_frequency_hz"])

        plan = load_sampling_plan()
        self.assertEqual(plan.count, 20)
        self.assertAlmostEqual(plan.frequency_hz, 10.0)
        self.assertAlmostEqual(plan.duration_seconds, 2.0)


class TestLoadConfigErrors(unittest.TestCase):
    """load_config explains bad input instead of raising raw tracebacks."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)

    def path(self, name: str) -> str:
        return os.path.join(self.temp_dir.name, name)

    def write(self, name: str, content: str) -> str:
        path = self.path(name)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return path

    def test_missing_file(self):
        with self.assertRaises(FileNotFoundError):
            load_config(self.path("missing.yaml"))

    def test_invalid_yaml(self):
        path = self.write("broken.yaml", "ammeters:\n  greenlee: {port: 5001\n")
        with self.assertRaises(ValueError):
            load_config(path)

    def test_empty_file(self):
        path = self.write("empty.yaml", "")
        with self.assertRaises(ValueError):
            load_config(path)

    def test_non_mapping_file(self):
        path = self.write("list.yaml", "- greenlee\n- entes\n")
        with self.assertRaises(ValueError):
            load_config(path)

    def test_valid_file_returns_mapping(self):
        config = load_config(CONFIG_PATH)
        self.assertIsInstance(config, dict)
        self.assertEqual(set(config["ammeters"]), {"greenlee", "entes", "circutor"})


if __name__ == "__main__":
    unittest.main(verbosity=2)
