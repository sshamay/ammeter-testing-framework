"""Shared, stateless helpers and constants for the regression suite.

No ``test*`` prefix, so unittest discovery does not collect this module.
"""

COMMANDS = {
    "greenlee": "MEASURE_GREENLEE -get_measurement",
    "entes": "MEASURE_ENTES -get_data",
    "circutor": "MEASURE_CIRCUTOR -get_measurement -current",
}
NAMES = ("greenlee", "entes", "circutor")


class FakeClock:
    """Records waits instead of performing them, advancing a logical clock."""

    def __init__(self):
        self.now_value = 0.0
        self.sleeps = []

    def now(self) -> float:
        return self.now_value

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now_value += seconds
