"""Small file logger retained from the supplied skeleton.

The framework itself never logs — it returns typed results and leaves presentation to the CLI — so
this utility is not on the measurement path. It is kept for callers that want an append-only log and
for its skeleton regression tests. Paths use :mod:`pathlib` so behaviour is identical on Windows,
Linux and macOS.
"""

import logging
from datetime import datetime
from pathlib import Path
from typing import Union

DEFAULT_LOG_DIR = Path("results") / "logs"


class TestLogger:
    """One dedicated log file per named test, with no duplicate handlers on reuse."""

    def __init__(self, test_name: str, log_dir: Union[str, Path] = DEFAULT_LOG_DIR):
        self._test_name = test_name
        self._log_dir = Path(log_dir)
        self.logger = self._setup_logger()

    def _setup_logger(self) -> logging.Logger:
        """Create the log directory, a timestamped file and a single INFO-level handler."""
        self._log_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_file = self._log_dir / f"{timestamp}_{self._test_name}.log"

        logger = logging.getLogger(f"test_{self._test_name}")
        for handler in logger.handlers[:]:
            logger.removeHandler(handler)
            handler.close()
        logger.setLevel(logging.INFO)
        logger.propagate = False

        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setLevel(logging.INFO)
        file_handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
        )
        logger.addHandler(file_handler)
        return logger

    def info(self, message: str) -> None:
        self.logger.info(message)

    def error(self, message: str) -> None:
        self.logger.error(message)

    def debug(self, message: str) -> None:
        self.logger.debug(message)

    def warning(self, message: str) -> None:
        self.logger.warning(message)
