"""Test-only corpus of deliberately wrong adapters (T-12, appendix §10).

Each adapter breaks exactly one adapter contract. No supplied emulator is modified: the corpus lives
here so production code never learns about faulty devices. Detectors interpret a :class:`RunResult`
plus adapter instrumentation and answer one question — did the framework surface the fault?
"""

from dataclasses import dataclass
from typing import Callable

from src.testing.adapters.fake import FakeAmmeterAdapter
from src.testing.errors import ParseError, ProtocolError, SampleTimeout, describe
from src.testing.storage import RunResult

TRUTH = (4.0, 4.1, 3.9)          # the values a healthy ammeter should return
LOWER, UPPER = 3.5, 4.5          # bounds for the wrong-scale detector
EXPECTED_COMMAND = b"MEASURE_GREENLEE -get_measurement"

Detector = Callable[[RunResult, "CorpusAdapter"], bool]


class CorpusAdapter(FakeAmmeterAdapter):
    """Healthy control: obeys the whole contract and records connection hygiene."""

    def __init__(self, name="greenlee", port=5001, command=EXPECTED_COMMAND, values=TRUTH):
        super().__init__(name=name, values=values, port=port, command=command, host="fake")
        self.opens = 0
        self.closes = 0

    def open(self, timeout=None):
        self.opens += 1
        super().open(timeout)

    def close(self):
        self.closes += 1
        super().close()           # healthy: actually releases the connection


class OffByOneAdapter(CorpusAdapter):
    """1. Drops the final reading of the batch."""

    def read_current(self):
        if self.reads == len(TRUTH) - 1:
            raise SampleTimeout(describe(self.name, self.port, self.host, "final sample missing"))
        return super().read_current()


class WrongScaleAdapter(CorpusAdapter):
    """2. Reports ten times the real current."""

    def __init__(self, **kwargs):
        super().__init__(values=tuple(value * 10 for value in TRUTH), **kwargs)


class SilentReplyAdapter(CorpusAdapter):
    """3. Returns nothing instead of a numeric reply."""

    def read_current(self):
        raise ParseError(describe(self.name, self.port, self.host, "empty reply"))


class NeverClosesAdapter(CorpusAdapter):
    """4. Returns correct values but never releases the connection."""

    def close(self):
        self.closes += 1          # deliberately no super().close(): the socket stays open


class ConstantValueAdapter(CorpusAdapter):
    """5. Returns one constant, hiding all variance."""

    def __init__(self, **kwargs):
        super().__init__(values=(TRUTH[0],) * len(TRUTH), **kwargs)


class WrongCommandAdapter(CorpusAdapter):
    """6. Sends a command the ammeter does not understand."""

    def __init__(self, **kwargs):
        kwargs.pop("command", None)   # the fault is the command; ignore any injected value
        super().__init__(command=b"WRONG_COMMAND", **kwargs)

    def read_current(self):
        if self.command != EXPECTED_COMMAND:
            raise ProtocolError(
                describe(self.name, self.port, self.host, f"wrong command {self.command!r}")
            )
        return super().read_current()


class SlowAdapter(CorpusAdapter):
    """7. Answers after the sampling deadline."""

    def read_current(self):
        raise SampleTimeout(describe(self.name, self.port, self.host, "reply after deadline"))


def errors_for(result: RunResult, name: str):
    return [error for error in result.errors if name in error]


def detect_off_by_one(result: RunResult, adapter: CorpusAdapter) -> bool:
    return bool(errors_for(result, adapter.name)) and adapter.reads < len(TRUTH)


def detect_wrong_scale(result: RunResult, adapter: CorpusAdapter) -> bool:
    values = result.samples.get(adapter.name, ())
    return bool(values) and any(not LOWER <= value <= UPPER for value in values)


def detect_silent_reply(result: RunResult, adapter: CorpusAdapter) -> bool:
    return any("empty reply" in error for error in errors_for(result, adapter.name))


def detect_never_closes(result: RunResult, adapter: CorpusAdapter) -> bool:
    return adapter.opens > 0 and adapter.is_open


def detect_constant(result: RunResult, adapter: CorpusAdapter) -> bool:
    values = result.samples.get(adapter.name, ())
    stats = result.statistics.get(adapter.name)
    return (
        bool(values)
        and stats is not None
        and stats.cv == 0.0
        and all(value == TRUTH[0] for value in values)
    )


def detect_wrong_command(result: RunResult, adapter: CorpusAdapter) -> bool:
    return any("wrong command" in error for error in errors_for(result, adapter.name))


def detect_slow(result: RunResult, adapter: CorpusAdapter) -> bool:
    return any("deadline" in error for error in errors_for(result, adapter.name))


@dataclass(frozen=True)
class FaultCase:
    name: str
    adapter_class: type
    detector: Detector


FAULT_CASES = (
    FaultCase("off-by-one sample count", OffByOneAdapter, detect_off_by_one),
    FaultCase("wrong scale factor (x10)", WrongScaleAdapter, detect_wrong_scale),
    FaultCase("silent None/empty reply", SilentReplyAdapter, detect_silent_reply),
    FaultCase("correct value, never closes", NeverClosesAdapter, detect_never_closes),
    FaultCase("constant value (zero variance)", ConstantValueAdapter, detect_constant),
    FaultCase("replies to the wrong command", WrongCommandAdapter, detect_wrong_command),
    FaultCase("slower than the deadline", SlowAdapter, detect_slow),
)


def new_adapter(fault_case=None):
    """Build a fresh target adapter; ``None`` means the healthy control."""
    cls = fault_case.adapter_class if fault_case is not None else CorpusAdapter
    return cls(name="greenlee", port=5001, command=EXPECTED_COMMAND)
