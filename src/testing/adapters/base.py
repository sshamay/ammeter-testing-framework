"""The one contract every ammeter adapter implements.

The emulators themselves are frozen. This module only defines our side of the wire: a small,
uniform API that hides sockets from the rest of the framework and can be satisfied by a fake.
"""

from abc import ABC, abstractmethod
from typing import Any, Mapping, Optional, Type

from ..errors import ConfigError


DEFAULT_TIMEOUT = 3.0


class AmmeterAdapter(ABC):
    """Common interface for real and fake ammeters. Never prints; returns values or raises."""

    def __init__(self, name: str, port: int = 0, command: bytes = b"", host: str = "localhost"):
        self.name = name
        self.port = port
        self.command = command
        self.host = host
        self.timeout = DEFAULT_TIMEOUT

    @abstractmethod
    def open(self, timeout: Optional[float] = None) -> None:
        """Acquire the connection; ``None`` uses the adapter's configured timeout."""

    @abstractmethod
    def read_current(self) -> float:
        """Return one finite measurement; raise a typed error on any failure."""

    @abstractmethod
    def close(self) -> None:
        """Release the connection. Must be safe to call repeatedly."""

    @property
    @abstractmethod
    def is_open(self) -> bool:
        """Whether a live connection is currently held."""

    def __enter__(self) -> "AmmeterAdapter":
        self.open(self.timeout)
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        self.close()
        return False


def build_adapters(
    config: Mapping[str, Any],
    adapter_class: Type[AmmeterAdapter],
    **kwargs: Any,
) -> dict:
    """Build one adapter per entry in the frozen config's ``ammeters`` section.

    Ports and commands come only from the supplied config; no emulator code is changed. Passing a
    different ``adapter_class`` (e.g. the fake) is how the same configuration drives tests.
    """
    ammeters = config.get("ammeters")
    if not isinstance(ammeters, Mapping) or not ammeters:
        raise ConfigError("ammeters: a non-empty mapping of devices is required")

    adapters = {}
    for name, settings in ammeters.items():
        if not isinstance(settings, Mapping):
            raise ConfigError(f"ammeters.{name}: expected a mapping, got {settings!r}")
        port = settings.get("port")
        command = settings.get("command")
        if not isinstance(port, int) or isinstance(port, bool) or port < 1:
            raise ConfigError(f"ammeters.{name}.port must be a positive integer, got {port!r}")
        if not isinstance(command, str) or not command:
            raise ConfigError(f"ammeters.{name}.command must be a non-empty string, got {command!r}")
        adapters[name] = adapter_class(
            name=name,
            port=port,
            command=command.encode("utf-8"),
            **kwargs,
        )
    return adapters
