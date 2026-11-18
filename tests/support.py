"""Shared, stateless helpers and constants for the regression suite.

No ``test*`` prefix, so unittest discovery does not collect this module.
"""

from pathlib import Path

import yaml

from src.testing.adapters.fake import FakeAmmeterAdapter

COMMANDS = {
    "greenlee": "MEASURE_GREENLEE -get_measurement",
    "entes": "MEASURE_ENTES -get_data",
    "circutor": "MEASURE_CIRCUTOR -get_measurement -current",
}
NAMES = ("greenlee", "entes", "circutor")

GOOD = {
    "greenlee": (4.0, 4.1, 3.9),
    "entes": (5.0, 5.1, 4.9),
    "circutor": (0.02, 0.021, 0.019),
}


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


def write_config(directory, count=3, frequency=10, *, extra_ammeters=()):
    """Write a small test config with fake ports and a fixed reading count.

    ``extra_ammeters`` is an iterable of ``(name, command)`` pairs appended after the three standard
    devices, so a test can prove config-driven extension without hard-coding production code.
    """
    ammeters = {
        name: {"port": 5001 + index, "command": COMMANDS[name]}
        for index, name in enumerate(NAMES)
    }
    for index, (name, command) in enumerate(extra_ammeters, start=len(NAMES)):
        ammeters[name] = {"port": 5001 + index, "command": command}
    config = {
        "testing": {
            "sampling": {
                "measurements_count": count,
                "total_duration_seconds": None,
                "sampling_frequency_hz": frequency,
            }
        },
        "ammeters": ammeters,
        "analysis": {"statistical_metrics": None},
        "result_management": {"storage": None},
    }
    path = Path(directory) / "config.yaml"
    path.write_text(yaml.safe_dump(config), encoding="utf-8")
    return str(path)


def scripted_adapter_class(scripts):
    """An adapter class whose per-ammeter readings come from ``scripts``."""

    class ScriptedAdapter(FakeAmmeterAdapter):
        def __init__(self, name, port, command, host="fake", **kwargs):
            super().__init__(
                name=name, values=scripts[name], port=port, command=command, host=host
            )

    return ScriptedAdapter
