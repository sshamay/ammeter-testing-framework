"""Typed errors for the framework. Supplied modules are not modified."""

from typing import Optional


class MeasurementError(Exception):
    """Base class for every framework error."""


class ConfigError(MeasurementError):
    """Missing, invalid or inconsistent configuration."""


class TransportError(MeasurementError):
    """Cannot reach an ammeter, or the adapter is in the wrong state."""


class SampleTimeout(TransportError):
    """A connect or read exceeded its deadline."""


class ProtocolError(MeasurementError):
    """The ammeter replied with something that is not a measurement."""


class ParseError(ProtocolError):
    """The reply could not be interpreted as a finite float."""


def describe(ammeter: str, port: Optional[int], host: str, cause: str) -> str:
    """Consistent, grep-friendly error text: ammeter, endpoint and cause."""
    return f"{ammeter}@{host}:{port}: {cause}"
