"""Turn a validated :class:`SamplingPlan` into a finite series of readings.

Timing is injected so tests never wait on wall-clock time. The schedule is: take the first reading
immediately, then sleep ``1 / frequency_hz`` between subsequent readings. A transient failure is
retried within the same sample; a sample that fails every attempt raises its last typed error so the
caller can report that ammeter and continue with the others.
"""

import time
from dataclasses import dataclass
from typing import Any, Mapping, Optional, Protocol, Tuple

from .adapters.base import AmmeterAdapter
from .errors import ConfigError, MeasurementError
from .sampling import SamplingPlan, load_sampling_config


class Clock(Protocol):
    """Minimal timing interface; a fake is injected in tests."""

    def now(self) -> float: ...

    def sleep(self, seconds: float) -> None: ...


class SystemClock:
    """Production clock — the only place that is allowed to block."""

    def now(self) -> float:
        return time.monotonic()

    def sleep(self, seconds: float) -> None:
        time.sleep(seconds)


@dataclass(frozen=True)
class SamplingSettings:
    timeout: float = 0.5
    max_attempts: int = 2
    backoff_seconds: float = 0.05

    @classmethod
    def from_config(cls, sampling: Mapping[str, Any]) -> "SamplingSettings":
        retry = sampling.get("retry") or {}
        settings = cls(
            timeout=float(sampling.get("timeout_per_sample_seconds", cls.timeout)),
            max_attempts=int(retry.get("max_attempts", cls.max_attempts)),
            backoff_seconds=float(retry.get("backoff_seconds", cls.backoff_seconds)),
        )
        if settings.timeout <= 0:
            raise ConfigError(f"sampling.timeout_per_sample_seconds must be > 0, got {settings.timeout}")
        if settings.max_attempts < 1:
            raise ConfigError(f"retry.max_attempts must be >= 1, got {settings.max_attempts}")
        if settings.backoff_seconds < 0:
            raise ConfigError(f"retry.backoff_seconds must be >= 0, got {settings.backoff_seconds}")
        return settings


def load_sampler_settings(config_path: str = "config/config.yaml") -> SamplingSettings:
    """Read timeout/retry defaults merged over the frozen config."""
    return SamplingSettings.from_config(load_sampling_config(config_path))


@dataclass(frozen=True)
class SampleSeries:
    """One ammeter's campaign: the good readings plus any recovered failures."""

    ammeter: str
    values: Tuple[float, ...]
    errors: Tuple[MeasurementError, ...] = ()
    attempts: int = 0

    @property
    def count(self) -> int:
        return len(self.values)


class Sampler:
    """Drives one adapter according to one plan."""

    def __init__(
        self,
        adapter: AmmeterAdapter,
        plan: SamplingPlan,
        settings: Optional[SamplingSettings] = None,
        clock: Optional[Clock] = None,
    ):
        self.adapter = adapter
        self.plan = plan
        self.settings = settings or SamplingSettings()
        self.clock = clock or SystemClock()

    def run(self) -> SampleSeries:
        interval = 1.0 / self.plan.frequency_hz
        values = []
        errors = []
        attempts = 0

        self.adapter.open(timeout=self.settings.timeout)
        try:
            for index in range(self.plan.count):
                if index:
                    self.clock.sleep(interval)
                value, used = self._read_with_retry(errors)
                attempts += used
                values.append(value)
        finally:
            self.adapter.close()

        return SampleSeries(
            ammeter=self.adapter.name,
            values=tuple(values),
            errors=tuple(errors),
            attempts=attempts,
        )

    def _read_with_retry(self, errors: list) -> Tuple[float, int]:
        used = 0
        for attempt in range(self.settings.max_attempts):
            used += 1
            try:
                return self.adapter.read_current(), used
            except MeasurementError as error:
                errors.append(error)
                if attempt + 1 == self.settings.max_attempts:
                    raise
                self.clock.sleep(self.settings.backoff_seconds)
        raise AssertionError("unreachable: max_attempts >= 1")
