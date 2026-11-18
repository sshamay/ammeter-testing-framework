"""Stdlib-first visualization: one CSV per ammeter, an ASCII metrics table, optional PNG plots.

CSV and text output are always available and need no extra packages. PNG rendering is a *guarded*
feature: if ``matplotlib`` is missing, the run records a skip note and continues instead of failing.
Nothing here prints or raises for a missing extra: skip notes live in the summary artifact, and
callers own any presentation or status handling.
"""

import csv
from collections.abc import Mapping as MappingABC
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence, Tuple

import yaml

from .errors import ConfigError, StorageError
from .storage import RunResult
from .test_framework import _load_config_typed

DEFAULTS_PATH = Path(__file__).with_name("defaults.yaml")
DEFAULT_VISUALIZATIONS_DIR = "visualizations"
PLOT_SERIES = "series"
PLOT_COMPARISON = "comparison"
KNOWN_PLOTS = (PLOT_SERIES, PLOT_COMPARISON)
SUPPORTED_BACKENDS = ("csv",)


@dataclass(frozen=True)
class VisualizationSettings:
    enabled: bool = True
    backend: str = "csv"
    plot_types: Tuple[str, ...] = KNOWN_PLOTS
    directory: str = DEFAULT_VISUALIZATIONS_DIR

    @classmethod
    def from_config(cls, config: Mapping[str, Any]) -> "VisualizationSettings":
        enabled = config.get("enabled", True)
        if not isinstance(enabled, bool):
            raise ConfigError(f"analysis.visualization.enabled must be a bool, got {enabled!r}")
        backend = config.get("backend", "csv")
        if backend not in SUPPORTED_BACKENDS:
            raise ConfigError(
                f"analysis.visualization.backend must be one of {SUPPORTED_BACKENDS}, got {backend!r}"
            )
        raw_plots = config.get("plot_types", KNOWN_PLOTS)
        if not isinstance(raw_plots, (list, tuple)):
            raise ConfigError(f"analysis.visualization.plot_types must be a list, got {raw_plots!r}")
        plots = tuple(raw_plots)
        unknown = [plot for plot in plots if plot not in KNOWN_PLOTS]
        if unknown:
            raise ConfigError(f"analysis.visualization.plot_types contains unknown plots: {unknown}")
        directory = config.get("directory", DEFAULT_VISUALIZATIONS_DIR)
        if not isinstance(directory, str) or not directory:
            raise ConfigError(f"analysis.visualization.directory must be a non-empty string, got {directory!r}")
        return cls(enabled=enabled, backend=backend, plot_types=plots, directory=directory)


def _load_defaults() -> Mapping[str, Any]:
    with DEFAULTS_PATH.open(encoding="utf-8") as default_file:
        return yaml.safe_load(default_file)["analysis"]["visualization"]


def merge_visualization_config(config: Mapping[str, Any]) -> Mapping[str, Any]:
    """Our defaults over a loaded config; null values in the latter mean 'unset'."""
    analysis = config.get("analysis") or {}
    if not isinstance(analysis, MappingABC):
        raise ConfigError(f"analysis must be a mapping, got {analysis!r}")
    user = analysis.get("visualization") or {}
    if not isinstance(user, MappingABC):
        raise ConfigError(f"analysis.visualization must be a mapping, got {user!r}")
    merged = dict(_load_defaults())
    for key, value in user.items():
        if value is not None:
            merged[key] = value
    return merged


def settings_from_config(config: Mapping[str, Any]) -> VisualizationSettings:
    """Build settings from the config the framework already loaded (no second file read)."""
    return VisualizationSettings.from_config(merge_visualization_config(config))


def load_visualization_config(config_path: str = "config/config.yaml") -> Mapping[str, Any]:
    return merge_visualization_config(_load_config_typed(config_path))


def load_visualization_settings(config_path: str = "config/config.yaml") -> VisualizationSettings:
    return settings_from_config(_load_config_typed(config_path))


@dataclass(frozen=True)
class VisualizationArtifacts:
    directory: Optional[Path] = None
    csv_paths: Tuple[Path, ...] = ()
    table_path: Optional[Path] = None
    plot_paths: Tuple[Path, ...] = ()
    skipped: Tuple[str, ...] = ()


DISCLAIMER = "Precision/stability only (no reference meter); CIRCUTOR values are V*s, not amperes."


def format_table(result: RunResult) -> str:
    """All eight metrics per ammeter, aligned with stdlib string formatting only."""
    if not result.statistics:
        return "  (no ammeter produced readings)"
    header = (
        f"{'ammeter':<12} {'n':>4} {'mean':>10} {'median':>10} {'stddev':>10} "
        f"{'min':>10} {'max':>10} {'CV':>9} {'drift':>10}"
    )
    rows = [header]
    for name in sorted(result.statistics):
        stats = result.statistics[name]
        rows.append(
            f"{name:<12} {stats.count:>4} {stats.mean:>10.4f} {stats.median:>10.4f} "
            f"{stats.stddev:>10.4f} {stats.min:>10.4f} {stats.max:>10.4f} "
            f"{stats.cv:>9.4f} {stats.drift:>+10.4f}"
        )
    return "\n".join(rows)


def write_csv(result: RunResult, directory: Path) -> Tuple[Path, ...]:
    """One ``index,current`` file per ammeter — the raw series, exactly as measured."""
    paths = []
    for name in sorted(result.samples):
        path = directory / f"{name}.csv"
        try:
            with path.open("w", encoding="utf-8", newline="") as output:
                writer = csv.writer(output)
                writer.writerow(["index", "current"])
                for index, value in enumerate(result.samples[name], start=1):
                    writer.writerow([index, value])
        except OSError as error:
            raise StorageError(f"cannot write CSV {path}: {error}") from error
        paths.append(path)
    return tuple(paths)


def write_text_table(result: RunResult, directory: Path, notes: Sequence[str] = ()) -> Path:
    path = directory / "summary.txt"
    lines = [format_table(result)]
    if result.errors:
        lines.append(f"Errors ({len(result.errors)}):")
        lines.extend(f"  - {error}" for error in result.errors)
    if result.recovered:
        lines.append(f"Recovered ({len(result.recovered)}):")
        lines.extend(f"  - {error}" for error in result.recovered)
    lines.extend(f"Note: {note}" for note in notes)
    lines.append(DISCLAIMER)
    try:
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    except OSError as error:
        raise StorageError(f"cannot write text table {path}: {error}") from error
    return path


def _load_pyplot():
    """Return pyplot, or ``None`` when the optional matplotlib extra is absent."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return None
    return plt


def _plot_series(plt, result: RunResult, directory: Path) -> Path:
    figure, axis = plt.subplots()
    for name in sorted(result.samples):
        values = result.samples[name]
        axis.plot(range(1, len(values) + 1), values, marker="o", label=name)
    axis.set_xlabel("sample index")
    axis.set_ylabel("reading")
    axis.set_title("Series (precision/stability only, no reference meter)")
    if result.samples:  # matplotlib warns on a legend with no labelled artists
        axis.legend()
    axis.grid(True)
    path = directory / "series.png"
    figure.savefig(path)
    plt.close(figure)
    return path


def _plot_comparison(plt, result: RunResult, directory: Path) -> Path:
    names = sorted(result.statistics)
    figure, axes = plt.subplots(1, 2)
    axes[0].bar(names, [result.statistics[name].cv for name in names])
    axes[0].set_ylabel("CV")
    axes[1].bar(names, [result.statistics[name].drift for name in names])
    axes[1].set_ylabel("drift")
    figure.suptitle("CV and drift (precision/stability only)")
    path = directory / "comparison.png"
    figure.savefig(path)
    plt.close(figure)
    return path


_PLOTTERS = {PLOT_SERIES: _plot_series, PLOT_COMPARISON: _plot_comparison}


def render_plots(
    result: RunResult, directory: Path, settings: VisualizationSettings
) -> Tuple[Tuple[Path, ...], Tuple[str, ...]]:
    """Never raises because the optional extra is missing; records why it skipped."""
    plt = _load_pyplot()
    if plt is None:
        return (), ("matplotlib not installed - PNG plots skipped",)
    paths, skipped = [], []
    for plot_type in settings.plot_types:
        try:
            paths.append(_PLOTTERS[plot_type](plt, result, directory))
        except (OSError, RuntimeError) as error:
            skipped.append(f"{plot_type} plot failed: {error}")
    return tuple(paths), tuple(skipped)


def visualize(
    result: RunResult,
    results_dir: str,
    settings: Optional[VisualizationSettings] = None,
) -> VisualizationArtifacts:
    """Write CSV + text table, then best-effort plots, under ``<results_dir>/<dir>/<run_id>``."""
    settings = settings or VisualizationSettings()
    if not settings.enabled:
        return VisualizationArtifacts()
    directory = Path(results_dir) / settings.directory / result.run_id
    directory.mkdir(parents=True, exist_ok=True)
    csv_paths = write_csv(result, directory)
    plot_paths, skipped = render_plots(result, directory, settings)
    table_path = write_text_table(result, directory, skipped)
    return VisualizationArtifacts(
        directory=directory,
        csv_paths=csv_paths,
        table_path=table_path,
        plot_paths=plot_paths,
        skipped=skipped,
    )
