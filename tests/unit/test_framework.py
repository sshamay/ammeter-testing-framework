"""T-09: framework wiring — typed results, continue-on-failure, error aggregation.

All adapters here are injected fakes and all waits use a fake clock, so the whole suite runs without
sockets or wall-clock sleeps.
"""

import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from src.testing.adapters.fake import FakeAmmeterAdapter
from src.testing.analysis import Statistics
from src.testing.errors import ConfigError, ParseError, TransportError, describe
from src.testing.sampler import SamplingSettings
from src.testing.storage import RunResult, list_runs, load_run
from src.testing.test_framework import AmmeterTestFramework, format_failure
from tests.support import (
    GOOD,
    NAMES,
    FakeClock,
    scripted_adapter_class,
    write_config,
)


def one_shot_adapter_class(scripts):
    """A double for the frozen wire protocol: one connection answers exactly one request."""

    class OneShotAdapter(FakeAmmeterAdapter):
        def __init__(self, name, port, command, host="fake", **kwargs):
            super().__init__(
                name=name, values=scripts[name], port=port, command=command, host=host
            )
            self._answered = False

        def open(self, timeout=None):
            self._answered = False
            super().open(timeout)

        def read_current(self):
            if self._answered:
                raise TransportError(
                    describe(self.name, self.port, self.host, "connection closed by server")
                )
            self._answered = True
            return super().read_current()

    return OneShotAdapter


class FrameworkCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.config_path = write_config(self.temp.name)
        self.results_dir = str(Path(self.temp.name) / "runs")
        self.clock = FakeClock()
        self.settings = SamplingSettings(max_attempts=2, backoff_seconds=0.01)

    def framework(self, scripts, **kwargs):
        return AmmeterTestFramework(
            self.config_path,
            adapter_class=scripted_adapter_class(scripts),
            clock=self.clock,
            settings=self.settings,
            results_dir=self.results_dir,
            **kwargs,
        )


class TestFrameworkWiring(FrameworkCase):
    def test_run_test_returns_typed_result_per_ammeter(self):
        result = self.framework(GOOD).run_test(save=False)

        self.assertIsInstance(result, RunResult)
        self.assertEqual(set(result.statistics), set(NAMES))
        for stats in result.statistics.values():
            self.assertIsInstance(stats, Statistics)
        self.assertEqual(result.samples["greenlee"], GOOD["greenlee"])
        self.assertEqual(result.errors, ())

    def test_every_configured_ammeter_measured_with_exact_count(self):
        result = self.framework(GOOD).run_test(save=False)
        for name in NAMES:
            self.assertEqual(result.statistics[name].count, 3)
            self.assertEqual(result.samples[name], GOOD[name])

    def test_artifact_written_with_config_snapshot(self):
        result = self.framework(GOOD).run_test()

        self.assertEqual(list_runs(self.results_dir), (result.run_id,))
        data = load_run(result.run_id, self.results_dir)
        self.assertEqual(data["config_snapshot"]["ammeters"]["entes"]["port"], 5002)
        self.assertEqual(len(data["samples"]), 3)
        self.assertAlmostEqual(data["statistics"]["greenlee"]["mean"], 4.0)
        self.assertEqual(data["effective_settings"]["sampling"]["count"], 3)
        self.assertEqual(data["effective_settings"]["retry"]["max_attempts"], 2)

    def test_no_save_skips_artifact(self):
        result = self.framework(GOOD).run_test(save=False)
        self.assertFalse(Path(self.results_dir).exists())
        self.assertTrue(result.run_id)

    def test_single_ammeter_selection(self):
        result = self.framework(GOOD).run_test("greenlee", save=False)
        self.assertEqual(set(result.statistics), {"greenlee"})
        self.assertEqual(result.samples["greenlee"], GOOD["greenlee"])

    def test_unknown_ammeter_raises_typed_config_error(self):
        with self.assertRaises(ConfigError) as context:
            self.framework(GOOD).run_test("nope", save=False)
        message = str(context.exception)
        self.assertIn("nope", message)
        self.assertIn("greenlee", message)

    def test_missing_config_raises_typed_config_error(self):
        missing = str(Path(self.temp.name) / "missing.yaml")
        with self.assertRaises(ConfigError):
            AmmeterTestFramework(missing)

    def test_two_runs_have_distinct_ids_and_artifacts(self):
        first = self.framework(GOOD).run_test()
        second = self.framework(GOOD).run_test()

        self.assertNotEqual(first.run_id, second.run_id)
        self.assertEqual(len(list_runs(self.results_dir)), 2)

    def test_framework_never_prints(self):
        output = io.StringIO()
        with redirect_stdout(output):
            self.framework(GOOD).run_test(save=False)
        self.assertEqual(output.getvalue(), "")

    def test_uses_injected_clock_not_wall_clock(self):
        self.framework(GOOD).run_test(save=False)
        self.assertEqual(len(self.clock.sleeps), 6)  # 2 inter-reading waits per ammeter

    def test_sampler_reopens_connection_for_each_reading(self):
        framework = AmmeterTestFramework(
            self.config_path,
            adapter_class=one_shot_adapter_class(GOOD),
            clock=self.clock,
            settings=self.settings,
            results_dir=self.results_dir,
        )
        result = framework.run_test(save=False)
        self.assertEqual(result.errors, ())
        for name in NAMES:
            self.assertEqual(result.samples[name], GOOD[name])


class TestContinueOnFailure(FrameworkCase):
    def test_broken_ammeter_does_not_erase_the_other_two(self):
        scripts = dict(GOOD)
        scripts["entes"] = (
            TransportError(describe("entes", 5002, "fake", "connect failed")),
        )
        result = self.framework(scripts).run_test()

        self.assertEqual(set(result.statistics), {"greenlee", "circutor"})
        self.assertEqual(result.samples["greenlee"], GOOD["greenlee"])
        self.assertEqual(result.samples["circutor"], GOOD["circutor"])
        self.assertEqual(len(result.errors), 1)
        self.assertIn("entes@fake:5002", result.errors[0])
        self.assertIn("connect failed", result.errors[0])

    def test_non_numeric_and_nan_replies_are_reported_as_parse_errors(self):
        for reply in ("non-numeric reply b'abc'", "non-finite reply b'nan'"):
            with self.subTest(reply=reply):
                scripts = dict(GOOD)
                scripts["greenlee"] = (ParseError(describe("greenlee", 5001, "fake", reply)),)
                result = self.framework(scripts).run_test(save=False)
                self.assertIn(reply, result.errors[0])
                self.assertEqual(set(result.statistics), {"entes", "circutor"})

    def test_multiple_failures_are_aggregated(self):
        scripts = dict(GOOD)
        scripts["greenlee"] = (TransportError("greenlee down"),)
        scripts["circutor"] = (ValueError("circutor broke"),)
        result = self.framework(scripts).run_test(save=False)

        self.assertEqual(len(result.errors), 2)
        self.assertEqual(set(result.statistics), {"entes"})

    def test_unexpected_adapter_exception_is_flagged_in_the_report(self):
        scripts = dict(GOOD)
        scripts["circutor"] = (ValueError("circutor broke"),)
        result = self.framework(scripts).run_test(save=False)

        self.assertEqual(len(result.errors), 1)
        self.assertTrue(result.errors[0].startswith("UNEXPECTED: "))
        self.assertIn("ValueError: circutor broke", result.errors[0])

    def test_recovered_transient_does_not_fail_the_run(self):
        scripts = dict(GOOD)
        scripts["entes"] = (TransportError("transient"), 5.0, 5.1, 4.9)
        result = self.framework(scripts).run_test(save=False)

        self.assertEqual(result.errors, ())
        self.assertEqual(set(result.statistics), set(NAMES))
        self.assertEqual(result.samples["entes"], (5.0, 5.1, 4.9))
        self.assertEqual(len(result.recovered), 1)
        self.assertIn("entes@fake:5002", result.recovered[0])
        self.assertIn("TransportError: transient", result.recovered[0])

    def test_recovered_errors_are_persisted_in_the_artifact(self):
        scripts = dict(GOOD)
        scripts["greenlee"] = (TransportError("transient"), 4.0, 4.1, 3.9)
        result = self.framework(scripts).run_test()

        data = load_run(result.run_id, self.results_dir)
        self.assertEqual(data["errors"], [])
        self.assertEqual(len(data["recovered"]), 1)
        self.assertEqual(tuple(data["recovered"]), result.recovered)
        self.assertIn("greenlee@fake:5001: TransportError: transient", data["recovered"][0])


class TestExtension(FrameworkCase):
    """A new device needs only a config entry and an adapter with the shared contract."""

    def test_fourth_ammeter_via_config_and_adapter_only(self):
        path = write_config(
            self.temp.name, extra_ammeters=(("bench", "MEASURE_BENCH -get_current"),)
        )
        scripts = dict(GOOD)
        scripts["bench"] = (7.0, 7.1, 6.9)
        framework = AmmeterTestFramework(
            path,
            adapter_class=scripted_adapter_class(scripts),
            clock=self.clock,
            settings=self.settings,
            results_dir=self.results_dir,
        )

        result = framework.run_test()
        expected = set(NAMES) | {"bench"}

        self.assertEqual(set(result.statistics), expected)
        self.assertEqual(result.samples["bench"], (7.0, 7.1, 6.9))
        self.assertEqual(result.statistics["bench"].count, 3)
        self.assertEqual(result.errors, ())
        data = load_run(result.run_id, self.results_dir)
        self.assertEqual(set(data["samples"]), expected)
        self.assertEqual(data["config_snapshot"]["ammeters"]["bench"]["port"], 5004)
        self.assertEqual(
            data["config_snapshot"]["ammeters"]["bench"]["command"],
            "MEASURE_BENCH -get_current",
        )


class TestFailureFormatting(unittest.TestCase):
    def test_raw_exception_gets_ammeter_port_and_type(self):
        adapter = FakeAmmeterAdapter(name="circutor", port=5003)
        text = format_failure("circutor", adapter, ValueError("boom"))
        self.assertEqual(text, "circutor@fake:5003: ValueError: boom")

    def test_already_described_adapter_error_is_not_nested(self):
        adapter = FakeAmmeterAdapter(name="entes", port=5002)
        error = ParseError(describe("entes", 5002, "fake", "non-numeric reply"))
        text = format_failure("entes", adapter, error)
        self.assertEqual(text, "entes@fake:5002: non-numeric reply")

    def test_error_without_message_still_names_endpoint_and_type(self):
        adapter = FakeAmmeterAdapter(name="greenlee", port=5001)
        self.assertEqual(
            format_failure("greenlee", adapter, TransportError()),
            "greenlee@fake:5001: TransportError",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
