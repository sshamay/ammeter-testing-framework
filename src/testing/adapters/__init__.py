"""Unified ammeter adapter layer.

All devices, real or fake, satisfy the same ``AmmeterAdapter`` contract. Nothing here prints and
nothing here modifies the frozen emulator package.
"""

from .base import DEFAULT_TIMEOUT, AmmeterAdapter, build_adapters
from .fake import FakeAmmeterAdapter
from .socket_adapter import SocketAmmeterAdapter

__all__ = [
    "DEFAULT_TIMEOUT",
    "AmmeterAdapter",
    "SocketAmmeterAdapter",
    "FakeAmmeterAdapter",
    "build_adapters",
]
