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
    return parser


def format_summary(
    result: RunResult, results_dir: str = DEFAULT_RESULTS_DIR, *, saved: bool = True
) -> str:
    """Plain-text precision/stability table — no trueness claim, no external dependency."""
    lines = [f"Run {result.run_id}: {len(result.statistics)} of {len(result.statistics) + len(result.errors)} ammeters measured"]
    if result.statistics:
        lines.append(f"{'ammeter':<12} {'n':>4} {'mean':>10} {'stddev':>10} {'CV':>9} {'drift':>10}")
        for name in sorted(result.statistics):
            stats = result.statistics[name]
            lines.append(
                f"{name:<12} {stats.count:>4} {stats.mean:>10.4f} {stats.stddev:>10.4f} "
                f"{stats.cv:>9.4f} {stats.drift:>+10.4f}"
            )
    else:
        lines.append("  (no ammeter produced readings)")
    if result.errors:
        lines.append(f"Errors ({len(result.errors)}):")
        lines.extend(f"  - {error}" for error in result.errors)
    if saved:
        lines.append(f"Artifact: {Path(results_dir) / (result.run_id + '.json')}")
    else:
        lines.append("Artifact: not saved (--no-save)")
    lines.append("Precision/stability only (no reference meter); CIRCUTOR values are V*s, not amperes.")
    return "\n".join(lines)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        framework = AmmeterTestFramework(config_path=args.config, results_dir=args.results_dir)
        result = framework.run_test(args.ammeter, save=not args.no_save)
    except MeasurementError as error:
        print(f"ERROR: {type(error).__name__}: {error}", file=sys.stderr)
        return EXIT_FATAL
    print(format_summary(result, args.results_dir, saved=not args.no_save))
    return EXIT_PARTIAL if result.errors else EXIT_OK
