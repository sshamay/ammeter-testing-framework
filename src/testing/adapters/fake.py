"""In-memory adapter with the same contract as the socket-backed one.

Values may be floats or exception instances; an exception is raised in its turn, which lets later
sampler and fault-injection tests reuse this adapter without touching the emulators.
"""

from typing import Iterable, Optional, Union

from ..errors import TransportError, describe
from .base import AmmeterAdapter

Reading = Union[float, BaseException]


class FakeAmmeterAdapter(AmmeterAdapter):
    """Deterministic adapter: no sockets, no threads, no prints."""

    def __init__(
        self,
        name: str = "fake",
        values: Iterable[Reading] = (1.0,),
        port: int = 0,
        command: bytes = b"FAKE",
        host: str = "fake",
    ):
        super().__init__(name=name, port=port, command=command, host=host)
        self.values = tuple(values)
        if not self.values:
            raise ValueError("FakeAmmeterAdapter needs at least one value")
        self._open = False
        self._index = 0
        self.reads = 0
        self.last_timeout: Optional[float] = None

    def open(self, timeout: Optional[float] = None) -> None:
        self.last_timeout = self.timeout if timeout is None else timeout
        self._open = True

    def read_current(self) -> float:
        if not self._open:
            raise TransportError(describe(self.name, self.port, self.host, "adapter is not open"))
        reading = self.values[self._index % len(self.values)]
        self._index += 1
        self.reads += 1
        if isinstance(reading, BaseException):
            raise reading
        return float(reading)

    def close(self) -> None:
        self._open = False

    @property
    def is_open(self) -> bool:
        return self._open
