"""Sampling configuration resolution.

The supplied ``config/config.yaml`` is read-only and leaves its sampling values empty, so the
framework's own defaults are merged over it before validation. ``resolve_sampling`` is pure: it opens
no sockets and raises ``ConfigError`` instead of returning a half-valid plan.
"""

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Optional

import yaml

from src.utils.config import load_config

from .errors import ConfigError

DEFAULT_CEILING_HZ = 1000.0
CONFLICT_TOLERANCE = 0.01
DEFAULTS_PATH = Path(__file__).with_name("defaults.yaml")


@dataclass(frozen=True)
class SamplingPlan:
    count: int
    frequency_hz: float
    duration_seconds: float


def _positive_number(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigError(f"sampling.{field} must be a number, got {value!r}")
    number = float(value)
    if not math.isfinite(number):
        raise ConfigError(f"sampling.{field} must be finite, got {value!r}")
    if number <= 0:
        raise ConfigError(f"sampling.{field} must be greater than 0, got {value!r}")
    return number


def _positive_count(value: Any) -> int:
    if isinstance(value, bool):
        raise ConfigError(f"sampling.measurements_count must be an integer >= 1, got {value!r}")
    if isinstance(value, (int, float)) and not math.isfinite(value):
        raise ConfigError(f"sampling.measurements_count must be finite, got {value!r}")
    if not isinstance(value, int):
        raise ConfigError(f"sampling.measurements_count must be an integer >= 1, got {value!r}")
    if value < 1:
        raise ConfigError(f"sampling.measurements_count must be >= 1, got {value!r}")
    return value


def _check_ceiling(frequency: float, ceiling: float) -> None:
    if frequency > ceiling:
        raise ConfigError(
            f"sampling.sampling_frequency_hz must be <= {ceiling:g} Hz, got {frequency:g}"
        )


def resolve_sampling(sampling: Mapping[str, Any]) -> SamplingPlan:
    """Resolve count, duration and frequency into one validated plan."""
    raw_count = sampling.get("measurements_count")
    raw_duration = sampling.get("total_duration_seconds")
    raw_frequency = sampling.get("sampling_frequency_hz")
    raw_ceiling = sampling.get("max_sampling_frequency_hz", DEFAULT_CEILING_HZ)

    ceiling = _positive_number(raw_ceiling, "max_sampling_frequency_hz")
    count: Optional[int] = _positive_count(raw_count) if raw_count is not None else None
    duration = (
        _positive_number(raw_duration, "total_duration_seconds")
        if raw_duration is not None
        else None
    )
    frequency = (
        _positive_number(raw_frequency, "sampling_frequency_hz")
        if raw_frequency is not None
        else None
    )

    if frequency is not None:
        _check_ceiling(frequency, ceiling)

    if count is None and duration is None:
        raise ConfigError(
            "sampling: count or duration required "
            "(measurements_count or total_duration_seconds)"
        )
    if count is None and frequency is None:
        raise ConfigError("sampling: sampling_frequency_hz is required when only duration is set")
    if frequency is None and duration is None:
        raise ConfigError("sampling: total_duration_seconds is required when only count is set")

    if count is None:
        assert duration is not None and frequency is not None
        count = math.floor(duration * frequency)
        if count < 1:
            raise ConfigError("sampling: derived measurements_count must be >= 1")

    if frequency is None:
        assert duration is not None
        frequency = count / duration

    if duration is None:
        duration = count / frequency
    else:
        derived_duration = count / frequency
        delta = abs(duration - derived_duration) / derived_duration
        if delta > CONFLICT_TOLERANCE + 1e-12:
            raise ConfigError(
                f"sampling: total_duration_seconds {duration:g} disagrees with "
                f"count/frequency ({derived_duration:g}) by {delta:.1%}"
            )
        duration = derived_duration

    _check_ceiling(frequency, ceiling)
    return SamplingPlan(count=count, frequency_hz=frequency, duration_seconds=duration)


def _load_defaults() -> Mapping[str, Any]:
    with DEFAULTS_PATH.open(encoding="utf-8") as default_file:
        defaults = yaml.safe_load(default_file)
    return defaults["testing"]["sampling"]


def load_sampling_plan(config_path: str = "config/config.yaml") -> SamplingPlan:
    """Merge framework defaults over the supplied config, then resolve the plan."""
    config = load_config(config_path)
    user_sampling = (config.get("testing") or {}).get("sampling") or {}
    merged = dict(_load_defaults())
    for key, value in user_sampling.items():
        if value is not None:
            merged[key] = value
    return resolve_sampling(merged)
