"""Shared helpers for starting the frozen emulators in integration tests.

Not named ``test*.py`` so unittest discovery does not collect this module.
"""

import io
import socket
import threading
import time
from contextlib import redirect_stdout


def free_port() -> int:
    """Return a port that is free right now."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("localhost", 0))
        return sock.getsockname()[1]


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
    """Run an emulator server in a daemon thread; it never stops on its own."""
    with redirect_stdout(io.StringIO()):
        threading.Thread(target=emulator.start_server, daemon=True).start()


def ask(port: int, command: bytes, timeout: float = 3.0) -> bytes:
    """Send one command to a live emulator and return its raw reply."""
    with socket.create_connection(("localhost", port), timeout=timeout) as connection:
        connection.sendall(command)
        return connection.recv(1024)
