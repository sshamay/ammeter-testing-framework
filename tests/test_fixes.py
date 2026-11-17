"""Regression tests for the bugs fixed in Ammeters/, main.py and src/utils/config.py.

Run from the repository root:

    python -m unittest discover -s tests -v

Each class maps to one row of the fix log in docs/test_framework_README.md.
"""

import io
import os
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from contextlib import redirect_stdout

from Ammeters.Circutor_Ammeter import CircutorAmmeter
from Ammeters.Entes_Ammeter import EntesAmmeter
from Ammeters.Greenlee_Ammeter import GreenleeAmmeter
from Ammeters.client import request_current_from_ammeter
from main import AMMETERS, build_emulators
from src.utils.config import load_config

CONFIG_PATH = "config/config.yaml"

GREENLEE_COMMAND = b"MEASURE_GREENLEE -get_measurement"


def free_port() -> int:
    """Return a port that is free right now."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("localhost", 0))
        return s.getsockname()[1]


def wait_until_listening(port: int, timeout: float = 5.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection(("localhost", port), timeout=0.2):
                return True
        except OSError:
            time.sleep(0.02)
    return False


def start_emulator(emulator) -> None:
    """Run an emulator server in a daemon thread (it never stops on its own)."""
    with redirect_stdout(io.StringIO()):
        threading.Thread(target=emulator.start_server, daemon=True).start()


def ask(port: int, command: bytes, timeout: float = 3.0) -> bytes:
    with socket.create_connection(("localhost", port), timeout=timeout) as connection:
        connection.sendall(command)
        return connection.recv(1024)


def leave_port_in_time_wait(port: int) -> None:
    """Serve one connection and close it server-side, leaving the port in TIME_WAIT."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("localhost", port))
        listener.listen()
        client = socket.create_connection(("localhost", port))
        served, _ = listener.accept()
        served.close()
        client.close()


class TestPortStaysReusable(unittest.TestCase):
    """Fix 1: bind() must work while the previous connection is in TIME_WAIT."""

    def test_emulator_starts_on_port_left_in_time_wait(self):
        port = free_port()
        leave_port_in_time_wait(port)

        # Precondition: without SO_REUSEADDR this environment refuses the bind.
        # If it does not, the platform cannot reproduce the bug and the test is skipped.
        probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            probe.bind(("localhost", port))
        except OSError:
            blocked = True
        else:
            blocked = False
        finally:
            probe.close()
        if not blocked:
            self.skipTest("this platform does not block rebinding after TIME_WAIT")

        start_emulator(GreenleeAmmeter(port))
        self.assertTrue(
            wait_until_listening(port),
            "emulator failed to bind a port still in TIME_WAIT",
        )
        self.assertIsInstance(float(ask(port, GREENLEE_COMMAND)), float)


class TestCommandsMatchEmulators(unittest.TestCase):
    """Fix 2 and 4: the commands the client sends are the ones the emulators accept."""

    def setUp(self):
        self.config = load_config(CONFIG_PATH)

    def test_configured_command_is_accepted_by_each_emulator(self):
        emulators = build_emulators(self.config)
        for name, emulator in emulators.items():
            configured = self.config["ammeters"][name]["command"].encode("utf-8")
            self.assertEqual(configured, emulator.get_current_command)

    def test_truncated_command_is_rejected_by_each_emulator(self):
        """The old client sent only the first word of the command; that must not match."""
        emulators = build_emulators(self.config)
        for name, emulator in emulators.items():
            truncated = self.config["ammeters"][name]["command"].split()[0].encode("utf-8")
            self.assertNotEqual(truncated, emulator.get_current_command, name)

    def test_ports_come_from_config(self):
        port = free_port()
        self.config["ammeters"]["greenlee"]["port"] = port
        emulators = build_emulators(self.config)
        self.assertEqual(emulators["greenlee"].port, port)

    def test_config_command_drift_stops_startup(self):
        self.config["ammeters"]["circutor"]["command"] = "MEASURE_CIRCUTOR -get_measurement"
        with self.assertRaises(SystemExit):
            build_emulators(self.config)

    def test_every_emulator_class_is_covered(self):
        self.assertEqual(set(AMMETERS), {"greenlee", "entes", "circutor"})


class TestUnknownCommandIsReported(unittest.TestCase):
    """Fix 3: an unrecognised command gets an explicit error, not silence."""

    def setUp(self):
        self.port = free_port()
        start_emulator(GreenleeAmmeter(self.port))
        self.assertTrue(wait_until_listening(self.port))

    def test_unknown_command_returns_error_marker(self):
        self.assertEqual(ask(self.port, b"MEASURE_GREENLEE"), b"ERR_UNKNOWN_COMMAND")

    def test_known_command_returns_a_number(self):
        reply = ask(self.port, GREENLEE_COMMAND)
        self.assertTrue(reply)
        self.assertIsInstance(float(reply), float)

    def test_client_prints_error_instead_of_measurement(self):
        output = io.StringIO()
        with redirect_stdout(output):
            request_current_from_ammeter(self.port, b"MEASURE_GREENLEE")
        self.assertIn("Error from port", output.getvalue())
        self.assertNotIn("Received current measurement", output.getvalue())


class TestLoadConfigErrors(unittest.TestCase):
    """Fix 5: load_config explains bad input instead of raising raw tracebacks."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)

    def path(self, name: str) -> str:
        return os.path.join(self.temp_dir.name, name)

    def write(self, name: str, content: str) -> str:
        path = self.path(name)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return path

    def test_missing_file(self):
        with self.assertRaises(FileNotFoundError):
            load_config(self.path("missing.yaml"))

    def test_invalid_yaml(self):
        path = self.write("broken.yaml", "ammeters:\n  greenlee: {port: 5001\n")
        with self.assertRaises(ValueError):
            load_config(path)

    def test_empty_file(self):
        path = self.write("empty.yaml", "")
        with self.assertRaises(ValueError):
            load_config(path)

    def test_non_mapping_file(self):
        path = self.write("list.yaml", "- greenlee\n- entes\n")
        with self.assertRaises(ValueError):
            load_config(path)

    def test_valid_file_returns_mapping(self):
        config = load_config(CONFIG_PATH)
        self.assertIsInstance(config, dict)
        self.assertEqual(set(config["ammeters"]), {"greenlee", "entes", "circutor"})


class TestInterruptedRun(unittest.TestCase):
    """Fix 6: Ctrl-C stops the run with a message instead of a traceback."""

    def test_ctrl_c_exits_without_traceback(self):
        # Windows has no POSIX SIGINT for a child: use a new process group and CTRL_BREAK_EVENT,
        # which Python still turns into KeyboardInterrupt. POSIX keeps the ordinary SIGINT path.
        if os.name == "nt":
            process = subprocess.Popen(
                [sys.executable, "main.py"],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
            )
            interrupt = signal.CTRL_BREAK_EVENT
        else:
            process = subprocess.Popen(
                [sys.executable, "main.py"],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
            interrupt = signal.SIGINT
        try:
            time.sleep(1.5)
            if process.poll() is not None:
                self.skipTest("main.py finished before the interrupt could be sent")
            process.send_signal(interrupt)
            output, _ = process.communicate(timeout=20)
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()

        self.assertNotIn("Traceback", output)
        self.assertNotIn("KeyboardInterrupt", output)
        self.assertIn("Stopped by user.", output)
        self.assertEqual(process.returncode, 0)


class TestEmulatorMeasurements(unittest.TestCase):
    """The three emulators answer their own commands with a number."""

    def test_each_emulator_returns_a_measurement(self):
        for name, emulator_class in AMMETERS.items():
            with self.subTest(ammeter=name):
                port = free_port()
                start_emulator(emulator_class(port))
                self.assertTrue(wait_until_listening(port), f"{name} did not start")
                command = load_config(CONFIG_PATH)["ammeters"][name]["command"].encode("utf-8")
                self.assertIsInstance(float(ask(port, command)), float)


if __name__ == "__main__":
    unittest.main(verbosity=2)
