"""Socket-backed adapter for the frozen TCP emulators.

Wire protocol (as implemented in ``Ammeters/base_ammeter.py``): connect to ``host:port``, send the
exact configured command bytes, read one reply, close. A reply is either a float as ASCII or
``ERR_UNKNOWN_COMMAND``. The server closes after every request, so one connection per reading.
"""

import math
import socket
from typing import Optional

from ..errors import ParseError, ProtocolError, SampleTimeout, TransportError, describe
from .base import DEFAULT_TIMEOUT, AmmeterAdapter


class SocketAmmeterAdapter(AmmeterAdapter):
    """Real adapter. One open/read/close cycle owns at most one socket."""

    def __init__(
        self,
        name: str,
        port: int,
        command: bytes,
        host: str = "localhost",
        timeout: float = DEFAULT_TIMEOUT,
    ):
        super().__init__(name=name, port=port, command=command, host=host)
        self.timeout = timeout
        self._connection: Optional[socket.socket] = None

    def open(self, timeout: Optional[float] = None) -> None:
        if self._connection is not None:
            self.close()
        effective = self.timeout if timeout is None else timeout
        try:
            connection = socket.create_connection((self.host, self.port), timeout=effective)
            connection.settimeout(effective)
        except OSError as error:
            raise TransportError(
                describe(self.name, self.port, self.host, f"connect failed: {error}")
            ) from error
        self._connection = connection

    def read_current(self) -> float:
        if self._connection is None:
            raise TransportError(describe(self.name, self.port, self.host, "adapter is not open"))
        try:
            self._connection.sendall(self.command)
            data = self._connection.recv(1024)
        except socket.timeout as error:
            raise SampleTimeout(
                describe(self.name, self.port, self.host, f"timed out after {self.timeout}s")
            ) from error
        except OSError as error:
            raise TransportError(
                describe(self.name, self.port, self.host, f"I/O failed: {error}")
            ) from error

        if not data:
            raise ProtocolError(describe(self.name, self.port, self.host, "empty reply"))
        if data.startswith(b"ERR"):
            raise ProtocolError(
                describe(
                    self.name,
                    self.port,
                    self.host,
                    data.decode("utf-8", errors="replace"),
                )
            )
        try:
            value = float(data.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as error:
            raise ParseError(
                describe(self.name, self.port, self.host, f"non-numeric reply {data!r}")
            ) from error
        if not math.isfinite(value):
            raise ParseError(
                describe(self.name, self.port, self.host, f"non-finite reply {data!r}")
            )
        return value

    def close(self) -> None:
        connection, self._connection = self._connection, None
        if connection is not None:
            try:
                connection.close()
            except OSError:
                pass

    @property
    def is_open(self) -> bool:
        return self._connection is not None
