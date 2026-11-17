"""Pure statistics over a sample series.

No I/O, no printing, no external dependencies. ``stddev`` is the population standard deviation so
that a single reading and a constant series both produce 0.0 instead of an exception.
"""

import math
import statistics
from dataclasses import asdict, dataclass
from typing import Iterable, Tuple

from .errors import AnalysisError

FIELDS = ("mean", "median", "stddev", "min", "max", "cv", "drift")


@dataclass(frozen=True)
class Statistics:
    count: int
    mean: float
    median: float
    stddev: float
    min: float
    max: float
    cv: float
    drift: float

    def as_dict(self) -> dict:
        return asdict(self)


def _finite_values(values: Iterable[float]) -> Tuple[float, ...]:
    series = tuple(values)
    if not series:
        raise AnalysisError("cannot compute statistics of an empty series")
    for value in series:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise AnalysisError(f"sample must be a number, got {value!r}")
        if not math.isfinite(value):
            raise AnalysisError(f"sample must be finite, got {value!r}")
    return tuple(float(value) for value in series)


def _drift(series: Tuple[float, ...]) -> float:
    """Mean of the second half minus mean of the first half; 0 for fewer than two readings."""
    if len(series) < 2:
        return 0.0
    middle = len(series) // 2
    first, second = series[:middle], series[middle:]
    return statistics.fmean(second) - statistics.fmean(first)


def compute_statistics(values: Iterable[float]) -> Statistics:
    """All metrics for one ammeter's series, with safe n=1 and constant-data behaviour."""
    series = _finite_values(values)
    mean = statistics.fmean(series)
    stddev = statistics.pstdev(series) if len(series) > 1 else 0.0
    cv = stddev / abs(mean) if mean != 0 else 0.0
    return Statistics(
        count=len(series),
        mean=mean,
        median=statistics.median(series),
        stddev=stddev,
        min=min(series),
        max=max(series),
        cv=cv,
        drift=_drift(series),
    )
