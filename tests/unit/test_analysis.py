"""T-07: deterministic, pure statistics tests. No I/O and no randomness."""

import math
import unittest

from src.testing.analysis import Statistics, compute_statistics
from src.testing.errors import AnalysisError


class TestStatistics(unittest.TestCase):
    def test_exact_metrics_on_injected_data(self):
        stats = compute_statistics([1, 2, 3, 4])
        self.assertIsInstance(stats, Statistics)
        self.assertEqual(stats.count, 4)
        self.assertAlmostEqual(stats.mean, 2.5)
        self.assertAlmostEqual(stats.median, 2.5)
        self.assertAlmostEqual(stats.stddev, math.sqrt(1.25))
        self.assertEqual(stats.min, 1.0)
        self.assertEqual(stats.max, 4.0)

    def test_duplicate_series_leaves_mean_and_cv_unchanged(self):
        base = compute_statistics([1, 2, 3, 4, 5])
        doubled = compute_statistics([1, 2, 3, 4, 5, 1, 2, 3, 4, 5])
        self.assertAlmostEqual(doubled.mean, base.mean)
        self.assertAlmostEqual(doubled.cv, base.cv)

    def test_scaling_multiplies_mean_and_stddev_but_not_cv(self):
        base = compute_statistics([1, 2, 3, 4])
        scaled = compute_statistics([2, 4, 6, 8])
        self.assertAlmostEqual(scaled.mean, 2 * base.mean)
        self.assertAlmostEqual(scaled.stddev, 2 * base.stddev)
        self.assertAlmostEqual(scaled.cv, base.cv)

    def test_single_reading_is_safe(self):
        stats = compute_statistics([7.0])
        self.assertEqual(stats.count, 1)
        self.assertEqual(stats.stddev, 0.0)
        self.assertEqual(stats.cv, 0.0)
        self.assertEqual(stats.drift, 0.0)

    def test_constant_series_has_zero_spread(self):
        stats = compute_statistics([3.0, 3.0, 3.0])
        self.assertEqual(stats.mean, 3.0)
        self.assertEqual(stats.stddev, 0.0)
        self.assertEqual(stats.cv, 0.0)
        self.assertEqual(stats.drift, 0.0)

    def test_zero_mean_does_not_divide_by_zero(self):
        stats = compute_statistics([-1.0, 1.0])
        self.assertEqual(stats.mean, 0.0)
        self.assertEqual(stats.cv, 0.0)

    def test_drift_tracks_direction(self):
        self.assertGreater(compute_statistics([1, 2, 3, 4, 5]).drift, 0)
        self.assertLess(compute_statistics([5, 4, 3, 2, 1]).drift, 0)

    def test_empty_series_raises_analysis_error(self):
        with self.assertRaises(AnalysisError):
            compute_statistics([])

    def test_non_finite_samples_raise_analysis_error(self):
        for value in (float("nan"), float("inf")):
            with self.subTest(value=value), self.assertRaises(AnalysisError):
                compute_statistics([1.0, value])

    def test_non_numeric_samples_raise_analysis_error(self):
        with self.assertRaises(AnalysisError):
            compute_statistics([1.0, "2.0"])

    def test_as_dict_contains_every_metric(self):
        data = compute_statistics([1, 2, 3]).as_dict()
        self.assertEqual(
            set(data),
            {"count", "mean", "median", "stddev", "min", "max", "cv", "drift"},
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
