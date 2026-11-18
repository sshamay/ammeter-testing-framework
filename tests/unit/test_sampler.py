"""T-06: deterministic sampler tests — no wall-clock waits, exact counts.

Run from the repository root:

    python -m unittest discover -s tests -v
"""

import io
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from src.testing.adapters import FakeAmmeterAdapter
from src.testing.errors import (
    AnalysisError,
    ConfigError,
    ParseError,
    ProtocolError,
    SampleTimeout,
    StorageError,
    TransportError,
    describe,
)
from src.testing.sampler import (
    Sampler,
    SamplingSettings,
    _is_retryable,
    load_sampler_settings,
)
from src.testing.sampling import resolve_sampling
from tests.support import FakeClock


class FlakyConnectAdapter(FakeAmmeterAdapter):
    """Fails the first connect with a transient timeout, then obeys the contract."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.connects = 0

    def open(self, timeout=None):
        self.connects += 1
        if self.connects == 1:
            raise SampleTimeout(describe(self.name, self.port, self.host, "connect timed out"))
        super().open(timeout)


def plan(count=None, duration=None, frequency=None):
    return resolve_sampling(
        {
            "measurements_count": count,
            "total_duration_seconds": duration,
            "sampling_frequency_hz": frequency,
        }
    )


class TestSamplerCounts(unittest.TestCase):
    def test_exact_count_from_count_and_frequency(self):
        adapter = FakeAmmeterAdapter("fake", values=(1.0,))
        clock = FakeClock()
        series = Sampler(adapter, plan(count=5, frequency=10), clock=clock).run()

        self.assertEqual(series.ammeter, "fake")
        self.assertEqual(series.count, 5)
        self.assertEqual(len(series.values), 5)
        self.assertEqual(series.attempts, 5)
        self.assertEqual(adapter.reads, 5)
        self.assertFalse(adapter.is_open)

    def test_sleeps_between_readings_only(self):
        clock = FakeClock()
        Sampler(FakeAmmeterAdapter(values=(1.0,)), plan(count=5, frequency=10), clock=clock).run()
        self.assertEqual(len(clock.sleeps), 4)
        for seconds in clock.sleeps:
            self.assertAlmostEqual(seconds, 0.1)

    def test_single_reading_does_not_sleep(self):
        clock = FakeClock()
        series = Sampler(FakeAmmeterAdapter(values=(7.0,)), plan(count=1, frequency=10), clock=clock).run()
        self.assertEqual(series.values, (7.0,))
        self.assertEqual(clock.sleeps, [])

    def test_count_derived_from_duration_and_frequency(self):
        adapter = FakeAmmeterAdapter(values=(2.0,))
        clock = FakeClock()
        series = Sampler(adapter, plan(duration=1, frequency=10), clock=clock).run()

        self.assertEqual(series.count, 10)
        self.assertEqual(len(clock.sleeps), 9)
        for seconds in clock.sleeps:
            self.assertAlmostEqual(seconds, 0.1)

    def test_never_calls_real_time_sleep(self):
        with patch("src.testing.sampler.time.sleep", side_effect=AssertionError("real sleep")):
            Sampler(FakeAmmeterAdapter(values=(1.0,)), plan(count=3, frequency=10), clock=FakeClock()).run()


class TestSamplerSettings(unittest.TestCase):
    def test_defaults_come_from_framework_defaults_file(self):
        settings = load_sampler_settings()
        self.assertEqual(settings.timeout, 0.5)
        self.assertEqual(settings.max_attempts, 2)
        self.assertAlmostEqual(settings.backoff_seconds, 0.05)
        self.assertAlmostEqual(settings.backoff_multiplier, 2.0)

    def test_settings_can_be_overridden_from_config_mapping(self):
        settings = SamplingSettings.from_config(
            {
                "timeout_per_sample_seconds": 2,
                "retry": {
                    "max_attempts": 3,
                    "backoff_seconds": 0.2,
                    "backoff_multiplier": 3.0,
                },
            }
        )
        self.assertEqual(settings.timeout, 2.0)
        self.assertEqual(settings.max_attempts, 3)
        self.assertAlmostEqual(settings.backoff_seconds, 0.2)
        self.assertAlmostEqual(settings.backoff_multiplier, 3.0)

    def test_invalid_settings_raise_config_error(self):
        for config in (
            {"retry": {"max_attempts": 0}},
            {"timeout_per_sample_seconds": 0},
            {"retry": {"backoff_seconds": -1}},
            {"retry": {"backoff_multiplier": 0.5}},
        ):
            with self.subTest(config=config), self.assertRaises(ConfigError):
                SamplingSettings.from_config(config)

    def test_transient_errors_are_retryable_permanent_ones_are_not(self):
        cases = (
            (SampleTimeout("timeout"), True),
            (TransportError("connect failed"), True),
            (ParseError("non-numeric reply"), True),
            (ProtocolError("empty reply"), True),
            (ConfigError("bad config"), False),
            (AnalysisError("no statistics"), False),
            (StorageError("disk full"), False),
            (ValueError("raw adapter bug"), False),
        )
        for error, expected in cases:
            with self.subTest(error=type(error).__name__):
                self.assertIs(_is_retryable(error), expected)

    def test_open_uses_the_configured_timeout(self):
        adapter = FakeAmmeterAdapter(values=(1.0,))
        Sampler(
            adapter,
            plan(count=1, frequency=10),
            settings=SamplingSettings(timeout=0.25),
            clock=FakeClock(),
        ).run()
        self.assertEqual(adapter.last_timeout, 0.25)


class TestSamplerFailures(unittest.TestCase):
    def test_timeout_aborts_the_series_and_closes_adapter(self):
        failure = SampleTimeout("stalled")
        adapter = FakeAmmeterAdapter("fake", values=(failure,))
        with self.assertRaises(SampleTimeout) as context:
            Sampler(
                adapter,
                plan(count=3, frequency=10),
                settings=SamplingSettings(max_attempts=1),
                clock=FakeClock(),
            ).run()
        self.assertIs(context.exception, failure)
        self.assertFalse(adapter.is_open)

    def test_retry_recovers_and_records_transient_error(self):
        failure = SampleTimeout("first attempt")
        adapter = FakeAmmeterAdapter("fake", values=(failure, 2.5))
        clock = FakeClock()
        settings = SamplingSettings(max_attempts=2, backoff_seconds=0.05)
        series = Sampler(adapter, plan(count=1, frequency=10), settings, clock).run()

        self.assertEqual(series.values, (2.5,))
        self.assertEqual(len(series.errors), 1)
        self.assertIs(series.errors[0], failure)
        self.assertEqual(series.attempts, 2)
        self.assertEqual(clock.sleeps, [0.05])

    def test_retry_backoff_follows_exponential_schedule(self):
        failures = tuple(SampleTimeout(f"failure {index}") for index in range(3))
        adapter = FakeAmmeterAdapter("fake", values=failures + (9.0,))
        clock = FakeClock()
        settings = SamplingSettings(
            max_attempts=4, backoff_seconds=0.1, backoff_multiplier=2.0
        )

        series = Sampler(adapter, plan(count=1, frequency=10), settings, clock).run()

        self.assertEqual(series.values, (9.0,))
        self.assertEqual(len(series.errors), 3)
        self.assertEqual(series.attempts, 4)
        self.assertEqual(adapter.reads, 4)
        self.assertEqual(clock.sleeps, [0.1, 0.2, 0.4])
        self.assertAlmostEqual(clock.now(), 0.7)
        self.assertFalse(adapter.is_open)

    def test_permanent_error_fails_fast_without_backoff(self):
        permanent = ConfigError("device config rejected")
        adapter = FakeAmmeterAdapter("fake", values=(permanent,))
        clock = FakeClock()

        with self.assertRaises(ConfigError) as context:
            Sampler(
                adapter,
                plan(count=1, frequency=10),
                SamplingSettings(max_attempts=3, backoff_seconds=0.1),
                clock,
            ).run()

        self.assertIs(context.exception, permanent)
        self.assertEqual(adapter.reads, 1)
        self.assertEqual(clock.sleeps, [])
        self.assertFalse(adapter.is_open)

    def test_connect_failure_is_retried_with_the_same_schedule(self):
        adapter = FlakyConnectAdapter("fake", values=(7.0,))
        clock = FakeClock()

        series = Sampler(adapter, plan(count=1, frequency=10), clock=clock).run()

        self.assertEqual(series.values, (7.0,))
        self.assertEqual(series.attempts, 2)
        self.assertEqual(adapter.connects, 2)
        self.assertEqual(adapter.reads, 1)
        self.assertEqual(clock.sleeps, [0.05])
        self.assertFalse(adapter.is_open)

    def test_exhausted_retries_raise_last_error(self):
        first = TransportError("first")
        last = TransportError("last")
        adapter = FakeAmmeterAdapter("fake", values=(first, last))
        with self.assertRaises(TransportError) as context:
            Sampler(
                adapter,
                plan(count=1, frequency=10),
                settings=SamplingSettings(max_attempts=2),
                clock=FakeClock(),
            ).run()
        self.assertIs(context.exception, last)
        self.assertEqual(adapter.reads, 2)
        self.assertFalse(adapter.is_open)

    def test_sampler_never_prints(self):
        output = io.StringIO()
        with redirect_stdout(output):
            Sampler(FakeAmmeterAdapter(values=(1.0,)), plan(count=2, frequency=10), clock=FakeClock()).run()
        self.assertEqual(output.getvalue(), "")


if __name__ == "__main__":
    unittest.main(verbosity=2)
