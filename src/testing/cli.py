"""Command-line entry point: ``python -m src.testing``.

The CLI is the only layer allowed to print and to choose an exit status. ``run_test`` stays pure of
presentation concerns, so the same framework can be embedded elsewhere.
"""

import argparse
import sys
from pathlib import Path
from typing import Optional, Sequence

from .errors import MeasurementError
from .storage import DEFAULT_RESULTS_DIR, RunResult
from .test_framework import ALL_AMMETERS, AmmeterTestFramework
from .visualization import (
    DISCLAIMER,
    VisualizationSettings,
    format_table,
    settings_from_config,
    visualize,
)


EXIT_OK = 0
EXIT_PARTIAL = 1   # some ammeters failed; the others were measured and archived
EXIT_FATAL = 2     # configuration, analysis or storage failure — no result produced


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m src.testing",
        description="Measure the configured ammeters and archive a JSON run result.",
    )
    parser.add_argument(
        "--config", default="config/config.yaml", help="YAML config path (default: config/config.yaml)"
    )
    parser.add_argument(
        "--ammeter",
        default=ALL_AMMETERS,
        help=f"one configured ammeter name, or '{ALL_AMMETERS}' for every ammeter (default)",
    )
    parser.add_argument(
        "--results-dir", default=DEFAULT_RESULTS_DIR, help=f"artifact directory (default: {DEFAULT_RESULTS_DIR})"
    )
    parser.add_argument(
        "--no-save", action="store_true", help="print the summary without writing an artifact"
    )
    parser.add_argument(
        "--no-visualize", action="store_true",
        help="skip CSV/text/PNG output (overrides analysis.visualization.enabled)",
    )
    return parser


def format_summary(
    result: RunResult,
    results_dir: str = DEFAULT_RESULTS_DIR,
    *,
    saved: bool = True,
    notes: Sequence[str] = (),
) -> str:
    """Plain-text precision/stability table — no trueness claim, no external dependency."""
    lines = [f"Run {result.run_id}: {len(result.statistics)} of {len(result.statistics) + len(result.errors)} ammeters measured"]
    lines.append(format_table(result))
    if result.errors:
        lines.append(f"Errors ({len(result.errors)}):")
        lines.extend(f"  - {error}" for error in result.errors)
    if saved:
        lines.append(f"Artifact: {Path(results_dir) / (result.run_id + '.json')}")
    else:
        lines.append("Artifact: not saved (--no-save)")
    lines.extend(f"Note: {note}" for note in notes)
    lines.append(DISCLAIMER)
    return "\n".join(lines)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        framework = AmmeterTestFramework(config_path=args.config, results_dir=args.results_dir)
        settings = (
            VisualizationSettings(enabled=False)
            if args.no_visualize
            else settings_from_config(framework.config)
        )
        result = framework.run_test(args.ammeter, save=not args.no_save)
        notes = ()
        if settings.enabled:
            notes = visualize(result, args.results_dir, settings).skipped
    except MeasurementError as error:
        print(f"ERROR: {type(error).__name__}: {error}", file=sys.stderr)
        return EXIT_FATAL
    print(format_summary(result, args.results_dir, saved=not args.no_save, notes=notes))
    return EXIT_PARTIAL if result.errors else EXIT_OK
