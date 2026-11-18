"""T-12: test-the-tester — detection score over the faulty-adapter corpus (appendix §10).

Every case injects one faulty adapter as ``greenlee`` while healthy fakes keep ``entes`` and
``circutor`` online. The pass condition is inverted: a fault is only a pass when an oracle fires on
the framework's typed output. The healthy control runs all seven detectors and none may fire, which
measures false positives. No sockets and no wall-clock sleeps are involved.
"""

import tempfile
import unittest
from pathlib import Path

from src.testing.adapters.fake import FakeAmmeterAdapter
from src.testing.sampler import SamplingSettings
from src.testing.test_framework import AmmeterTestFramework

from tests.faulty_adapters import FAULT_CASES, new_adapter
from tests.support import COMMANDS, GOOD, NAMES, FakeClock, write_config

PEERS = ("entes", "circutor")


def healthy_adapter(name):
    """A contract-obeying fake for the two ammeters that are not under test."""
    return FakeAmmeterAdapter(
        name=name,
        values=GOOD[name],
        port=5001 + NAMES.index(name),
        command=COMMANDS[name].encode(),
    )


class FaultCorpusCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.config_path = write_config(self.temp.name)
        self.results_dir = str(Path(self.temp.name) / "runs")
        self.settings = SamplingSettings(max_attempts=2, backoff_seconds=0.0)

    def run_campaign(self, target):
        adapters = {"greenlee": target}
        adapters.update({name: healthy_adapter(name) for name in PEERS})
        framework = AmmeterTestFramework(
            self.config_path,
            adapters=adapters,
            clock=FakeClock(),
            settings=self.settings,
            results_dir=self.results_dir,
        )
        return framework.run_test(save=False)


class TestFaultDetectionScore(FaultCorpusCase):
    def test_detection_score(self):
        detected = []
        for case in FAULT_CASES:
            with self.subTest(fault=case.name):
                target = new_adapter(case)
                result = self.run_campaign(target)
                fired = case.detector(result, target)
                detected.append(fired)
                self.assertTrue(fired, f"fault not surfaced: {case.name}")
                for name in PEERS:
                    self.assertIn(name, result.samples, f"{name} lost when {case.name} failed")
                    self.assertEqual(len(result.samples[name]), 3)
        score = sum(detected)
        print(f"Detection score: {score}/{len(FAULT_CASES)}")
        self.assertEqual(score, len(FAULT_CASES))

    def test_healthy_control_no_false_positives(self):
        target = new_adapter()          # no fault case → healthy CorpusAdapter
        result = self.run_campaign(target)

        self.assertEqual(result.errors, ())
        self.assertEqual(set(result.samples), set(NAMES))
        for name in NAMES:
            self.assertEqual(len(result.samples[name]), 3)
        self.assertEqual(target.opens, 3)
        self.assertEqual(target.closes, 3)
        self.assertFalse(target.is_open)

        for case in FAULT_CASES:
            with self.subTest(detector=case.name):
                self.assertFalse(case.detector(result, target), f"false positive: {case.name}")
        print(f"False positives: 0/{len(FAULT_CASES)}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
