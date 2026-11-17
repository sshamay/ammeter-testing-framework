"""Typed errors for the framework. Supplied modules are not modified."""


class MeasurementError(Exception):
    """Base class for every framework error."""


class ConfigError(MeasurementError):
    """Missing, invalid or inconsistent configuration."""
