"""Turn a validated :class:`SamplingPlan` into a finite series of readings.

Timing is injected so tests never wait on wall-clock time. The schedule is: take the first reading
immediately, then sleep ``1 / frequency_hz`` between subsequent readings.

Each reading owns its own connection: the emulators answer exactly one request and then close, so a
batch cannot reuse one open socket. Only *transient* faults are retried, with a fresh connection and
an exponential backoff (``backoff_seconds * multiplier ** retry_index``). Permanent framework faults
fail fast. A sample that exhausts its attempts raises its last typed error so the caller can report
that ammeter and continue with the others.
"""

import time
from dataclasses import dataclass
from typing import Any, Mapping, Optional, Protocol, Tuple

from .adapters.base import AmmeterAdapter
from .errors import ConfigError, MeasurementError, ProtocolError, TransportError
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
    backoff_multiplier: float = 2.0

    @classmethod
    def from_config(cls, sampling: Mapping[str, Any]) -> "SamplingSettings":
        retry = sampling.get("retry") or {}
        settings = cls(
            timeout=float(sampling.get("timeout_per_sample_seconds", cls.timeout)),
            max_attempts=int(retry.get("max_attempts", cls.max_attempts)),
            backoff_seconds=float(retry.get("backoff_seconds", cls.backoff_seconds)),
            backoff_multiplier=float(
                retry.get("backoff_multiplier", cls.backoff_multiplier)
            ),
        )
        if settings.timeout <= 0:
            raise ConfigError(f"sampling.timeout_per_sample_seconds must be > 0, got {settings.timeout}")
        if settings.max_attempts < 1:
            raise ConfigError(f"retry.max_attempts must be >= 1, got {settings.max_attempts}")
        if settings.backoff_seconds < 0:
            raise ConfigError(f"retry.backoff_seconds must be >= 0, got {settings.backoff_seconds}")
        if settings.backoff_multiplier < 1:
            raise ConfigError(
                f"retry.backoff_multiplier must be >= 1, got {settings.backoff_multiplier}"
            )
        return settings


def load_sampler_settings(config_path: str = "config/config.yaml") -> SamplingSettings:
    """Read timeout/retry defaults merged over the frozen config."""
    return SamplingSettings.from_config(load_sampling_config(config_path))


def _is_retryable(error: BaseException) -> bool:
    """Device/wire faults may recover; framework faults cannot be retried away.

    ``TransportError`` covers connect failures and I/O timeouts (``SampleTimeout`` is a subclass);
    ``ProtocolError`` covers empty, unexpected and unparseable replies. Config, analysis and storage
    errors are deterministic framework faults, so they fail fast instead of burning attempts.
    """
    return isinstance(error, (TransportError, ProtocolError))


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

        for index in range(self.plan.count):
            if index:
                self.clock.sleep(interval)
            value, used = self._read_with_retry(errors)
            attempts += used
            values.append(value)

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
                self.adapter.open(timeout=self.settings.timeout)
                return self.adapter.read_current(), used
            except MeasurementError as error:
                errors.append(error)
                if attempt + 1 == self.settings.max_attempts or not _is_retryable(error):
                    raise
                backoff = self.settings.backoff_seconds * self.settings.backoff_multiplier ** attempt
                self.clock.sleep(backoff)
            finally:
                self.adapter.close()
        raise AssertionError("unreachable: max_attempts >= 1")
