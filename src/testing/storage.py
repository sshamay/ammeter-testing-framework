"""Archived run results with unique IDs and atomic writes.

The JSON artifact is the framework's reporting evidence: it carries the config snapshot, the applied
sampling/retry settings, the runtime environment, the stats, the raw samples, terminal errors and
recovered transient faults. Writes go to a temp file in the same directory and are renamed into place,
so a failure can never leave a half-written result.
"""

import json
import os
import platform
import tempfile
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from importlib import metadata
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional, Tuple

from .analysis import Statistics, compute_statistics
from .errors import StorageError

SCHEMA_VERSION = 1
DEFAULT_RESULTS_DIR = "results/runs"


@dataclass(frozen=True)
class RunResult:
    run_id: str
    created_utc: str
    config_snapshot: Mapping[str, Any]
    statistics: Mapping[str, Statistics]
    samples: Mapping[str, Tuple[float, ...]]
    errors: Tuple[str, ...] = ()
    recovered: Tuple[str, ...] = ()
    schema_version: int = SCHEMA_VERSION
    effective_settings: Mapping[str, Any] = field(default_factory=dict)
    environment: Mapping[str, Any] = field(default_factory=dict)


def new_run_id() -> str:
    """Unique even for two runs started in the same second."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{stamp}-{uuid.uuid4().hex[:12]}"


def _default_environment() -> dict:
    """Runtime context needed to interpret an archived run later."""
    try:
        framework_version = metadata.version("ammeter-testing-framework")
    except metadata.PackageNotFoundError:
        framework_version = "unknown"
    return {
        "python_version": platform.python_version(),
        "platform": platform.platform(),
        "framework_version": framework_version,
    }


def build_run_result(
    samples: Mapping[str, Tuple[float, ...]],
    config_snapshot: Mapping[str, Any],
    errors: Iterable[str] = (),
    *,
    recovered: Iterable[str] = (),
    effective_settings: Optional[Mapping[str, Any]] = None,
    environment: Optional[Mapping[str, Any]] = None,
) -> RunResult:
    """Compute every ammeter's stats and wrap them with metadata into a frozen result."""
    return RunResult(
        run_id=new_run_id(),
        created_utc=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        config_snapshot=dict(config_snapshot),
        statistics={name: compute_statistics(values) for name, values in samples.items()},
        samples=dict(samples),
        errors=tuple(errors),
        recovered=tuple(recovered),
        effective_settings=dict(effective_settings or {}),
        environment=dict(
            environment if environment is not None else _default_environment()
        ),
    )


def save_run(result: RunResult, results_dir: str = DEFAULT_RESULTS_DIR) -> Path:
    """Write ``<run_id>.json`` atomically and return its path."""
    directory = Path(results_dir)
    temp_path: Optional[str] = None
    try:
        directory.mkdir(parents=True, exist_ok=True)
        handle, temp_path = tempfile.mkstemp(prefix=".run-", suffix=".tmp", dir=directory)
        with os.fdopen(handle, "w", encoding="utf-8") as output:
            json.dump(asdict(result), output, indent=2, sort_keys=True)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        target = directory / f"{result.run_id}.json"
        os.replace(temp_path, target)
        temp_path = None
    except (OSError, TypeError, ValueError) as error:
        raise StorageError(f"cannot save run {result.run_id} in {directory}: {error}") from error
    finally:
        if temp_path is not None and os.path.exists(temp_path):
            os.unlink(temp_path)
    return target


def list_runs(results_dir: str = DEFAULT_RESULTS_DIR) -> Tuple[str, ...]:
    """Run IDs on disk, oldest first (the ID starts with a sortable UTC stamp)."""
    directory = Path(results_dir)
    if not directory.exists():
        return ()
    return tuple(path.stem for path in sorted(directory.glob("*.json")))


def load_run(run_id: str, results_dir: str = DEFAULT_RESULTS_DIR) -> dict:
    """Read one artifact back as a plain dict."""
    path = Path(results_dir) / f"{run_id}.json"
    try:
        with path.open(encoding="utf-8") as source:
            data = json.load(source)
    except (OSError, ValueError) as error:
        raise StorageError(f"cannot read run {run_id} from {path}: {error}") from error
    if data.get("schema_version") != SCHEMA_VERSION or data.get("run_id") != run_id:
        raise StorageError(f"artifact {path} is not a valid run result")
    return data


def load_run_result(run_id: str, results_dir: str = DEFAULT_RESULTS_DIR) -> RunResult:
    """Rebuild a ``RunResult`` from an artifact; older artifacts omit the new metadata keys."""
    data = load_run(run_id, results_dir)
    try:
        return RunResult(
            run_id=data["run_id"],
            created_utc=data["created_utc"],
            config_snapshot=data["config_snapshot"],
            statistics={
                name: Statistics(**entry) for name, entry in data["statistics"].items()
            },
            samples={name: tuple(values) for name, values in data["samples"].items()},
            errors=tuple(data.get("errors", ())),
            recovered=tuple(data.get("recovered", ())),
            schema_version=data["schema_version"],
            effective_settings=data.get("effective_settings", {}),
            environment=data.get("environment", {}),
        )
    except (AttributeError, KeyError, TypeError, ValueError) as error:
        raise StorageError(f"artifact {run_id} has an invalid run shape: {error}") from error


def compare_runs(first: RunResult, second: RunResult) -> Mapping[str, Mapping[str, float]]:
    """Deltas in precision/stability metrics — never a trueness claim."""
    comparison = {}
    for name in sorted(set(first.statistics) & set(second.statistics)):
        before, after = first.statistics[name], second.statistics[name]
        comparison[name] = {
            "cv_delta": after.cv - before.cv,
            "drift_delta": after.drift - before.drift,
        }
    return comparison


def compare_runs_by_id(
    first: str, second: str, results_dir: str = DEFAULT_RESULTS_DIR
) -> Mapping[str, Mapping[str, float]]:
    """Compare two archived runs by ID, using their CV/drift deltas only."""
    return compare_runs(
        load_run_result(first, results_dir), load_run_result(second, results_dir)
    )
