"""Regression tests for T-02: framework skeleton, logger and dependencies.

Run from the repository root:

    python -m unittest discover -s tests -v
"""

import glob
import logging
import os
import typing
import unittest
import uuid

from src.testing.storage import RunResult
from src.testing.test_framework import AmmeterTestFramework
from src.utils.logger import TestLogger


class TestFrameworkSkeleton(unittest.TestCase):
    def test_run_test_annotation_resolves(self):
        """Deferred annotations must resolve: the stub's Dict is now a typed RunResult."""
        hints = typing.get_type_hints(AmmeterTestFramework.run_test)
        self.assertIs(hints["return"], RunResult)

    def test_framework_can_be_constructed(self):
        framework = AmmeterTestFramework()
        self.assertIn("ammeters", framework.config)


class TestLoggerWritesFile(unittest.TestCase):
    def test_info_line_lands_in_log_file(self):
        name = f"regression_{uuid.uuid4().hex}"
        test_logger = TestLogger(name)

        self.assertEqual(test_logger.logger.level, logging.INFO)
        self.assertEqual(len(test_logger.logger.handlers), 1)

        test_logger.info("skeleton-regression-line")

        paths = glob.glob(os.path.join("results", "logs", f"*_{name}.log"))
        self.assertEqual(len(paths), 1, "logger did not create exactly one log file")
        self.addCleanup(os.remove, paths[0])
        with open(paths[0], encoding="utf-8") as log_file:
            self.assertIn("skeleton-regression-line", log_file.read())

    def test_reusing_a_name_does_not_stack_handlers(self):
        name = f"regression_{uuid.uuid4().hex}"
        first = TestLogger(name)
        second = TestLogger(name)
        self.assertEqual(len(first.logger.handlers), 1)
        self.assertEqual(len(second.logger.handlers), 1)
        for handler in second.logger.handlers:
            self.addCleanup(handler.close)
            self.addCleanup(second.logger.removeHandler, handler)
        paths = glob.glob(os.path.join("results", "logs", f"*_{name}.log"))
        for path in paths:
            self.addCleanup(os.remove, path)


class TestDependenciesAreMinimal(unittest.TestCase):
    def test_requirements_have_no_unused_heavy_pins(self):
        with open("requirements.txt", encoding="utf-8") as requirements:
            lines = [
                line.strip().lower()
                for line in requirements
                if line.strip() and not line.lstrip().startswith("#")
            ]
        self.assertEqual(len(lines), 1, lines)
        self.assertTrue(lines[0].startswith("pyyaml"))
        for heavy in ("numpy", "scipy", "pandas", "seaborn", "matplotlib"):
            self.assertNotIn(heavy, lines[0])
