"""Top-level orchestration: configuration → sampling → statistics → archived result.

``run_test`` never prints and never calls ``sys.exit``: it returns a typed :class:`RunResult` so the
same API can be driven by tests, scripts, and any future caller. Per-ammeter failures are
recorded and the remaining ammeters are still measured — one broken device must not erase the other
results.
"""

from typing import Mapping, Optional, Type

from ..utils.config import load_config
from .adapters import SocketAmmeterAdapter, build_adapters
from .adapters.base import AmmeterAdapter
from .errors import ConfigError, MeasurementError, describe
from .sampler import Clock, Sampler, SamplingSettings, load_sampler_settings
from .sampling import load_sampling_plan
from .storage import DEFAULT_RESULTS_DIR, RunResult, build_run_result, save_run

ALL_AMMETERS = "all"


def _load_config_typed(path: str) -> dict:
    """Translate the frozen loader's raw OSError/ValueError into our ConfigError."""
    try:
        return load_config(path)
    except (OSError, ValueError) as error:
        raise ConfigError(f"cannot load config {path}: {error}") from error


def format_failure(name: str, adapter: AmmeterAdapter, error: BaseException) -> str:
    """One grep-friendly error line naming the ammeter, port and cause.

    Adapter errors already include ``ammeter@host:port:`` via :func:`describe`; keep that text as-is
    instead of nesting the endpoint twice. Raw exceptions (e.g. a misbehaving test double) are
    wrapped here so every recorded error carries the endpoint.
    """
    text = str(error)
    if text.startswith(f"{name}@"):
        return text
    cause = f"{type(error).__name__}: {text}" if text else type(error).__name__
    return describe(name, adapter.port, adapter.host, cause)


class AmmeterTestFramework:
    """Runs a sampling campaign over the configured ammeters and archives the result.

    Constructor injection keeps the real path deterministic in tests: pass fake adapters and a fake
    clock, and no socket or wall-clock sleep is involved. Production uses the defaults — real socket
    adapters and the system clock.
    """

    def __init__(
        self,
        config_path: str = "config/config.yaml",
        *,
        adapter_class: Type[AmmeterAdapter] = SocketAmmeterAdapter,
        adapters: Optional[Mapping[str, AmmeterAdapter]] = None,
        clock: Optional[Clock] = None,
        settings: Optional[SamplingSettings] = None,
        results_dir: str = DEFAULT_RESULTS_DIR,
    ):
        self.config_path = config_path
        self.config = _load_config_typed(config_path)
        self.results_dir = results_dir
        self.clock = clock
        self.settings = (
            settings if settings is not None else load_sampler_settings(config_path)
        )
        self.adapters: Mapping[str, AmmeterAdapter] = (
            dict(adapters)
            if adapters is not None
            else build_adapters(self.config, adapter_class)
        )

    def run_test(
        self, ammeter_type: str = ALL_AMMETERS, *, save: bool = True
    ) -> RunResult:
        """Measure one ammeter or all of them; return the typed result.

        ``ammeter_type`` is a name from the config's ``ammeters`` section, or ``"all"`` (the default).
        A per-ammeter failure is added to ``result.errors`` and the loop continues, so a broken device
        cannot delete the other measurements. Errors from untyped exceptions are prefixed
        ``UNEXPECTED:`` to make adapter or framework bugs visible in the report. Configuration,
        analysis and storage failures propagate as typed errors — they are not per-ammeter faults.
        """
        selected = self._select(ammeter_type)
        try:
            plan = load_sampling_plan(self.config_path)
        except (OSError, ValueError) as error:
            raise ConfigError(f"cannot load sampling config {self.config_path}: {error}") from error

        samples: dict = {}
        errors = []
        for name, adapter in selected.items():
            try:
                series = Sampler(adapter, plan, self.settings, self.clock).run()
            except Exception as error:
                # One dead ammeter must not stop the others. A typed measurement error already
                # describes the fault; a raw exception points at an adapter or framework bug, so
                # mark it as UNEXPECTED instead of letting it masquerade as a device failure.
                text = format_failure(name, adapter, error)
                if not isinstance(error, (MeasurementError, OSError)):
                    text = f"UNEXPECTED: {text}"
                errors.append(text)
                continue
            samples[name] = series.values

        result = build_run_result(samples, self.config, errors)
        if save:
            save_run(result, self.results_dir)
        return result

    def _select(self, ammeter_type: str) -> Mapping[str, AmmeterAdapter]:
        if ammeter_type == ALL_AMMETERS:
            return self.adapters
        if ammeter_type not in self.adapters:
            available = ", ".join(sorted(self.adapters)) or "(none)"
            raise ConfigError(
                f"unknown ammeter {ammeter_type!r}; configured ammeters: {available}"
            )
        return {ammeter_type: self.adapters[ammeter_type]}
