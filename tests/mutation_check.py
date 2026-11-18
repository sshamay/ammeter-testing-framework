"""Dependency-free mutation check for the framework's regression tests.

Nine single-line source mutants are applied one at a time to an isolated temp copy of the
repository, and a targeted slice of the unit suite runs against each. A mutant is *killed* when
at least one test fails; a survivor is a test gap (or an equivalent mutant). The working tree is
never modified and no third-party package is needed.

Run from the repository root: ``python -m tests.mutation_check``. Exit status is 0 only when the
untouched baseline passes and every mutant is killed; a skipped mutant (changed source anchor)
also fails the check, so test or source drift cannot silently weaken it.
"""

import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Tuple

REPO_ROOT = Path(__file__).resolve().parents[1]
IGNORE = shutil.ignore_patterns(
    ".git", ".venv", "__pycache__", "results", "*.pyc", "*.egg-info", ".mutmut-cache"
)

FRAMEWORK = "tests.unit.test_framework"
STORAGE = "tests.unit.test_storage"
VISUALIZATION = "tests.unit.test_visualization"
SAMPLER = "tests.unit.test_sampler"
BASELINE = (FRAMEWORK, STORAGE, VISUALIZATION)


@dataclass(frozen=True)
class Mutant:
    """One source edit, the exact text it replaces, and the tests that should notice it."""

    source: str
    old: str
    new: str
    description: str
    modules: Tuple[str, ...]


MUTANTS: Tuple[Mutant, ...] = (
    Mutant(
        "src/testing/visualization.py",
        "    if result.recovered:\n",
        "    if False:\n",
        "drop the Recovered section from summary.txt",
        (VISUALIZATION,),
    ),
    Mutant(
        "src/testing/visualization.py",
        'f"Recovered ({len(result.recovered)}):"',
        'f"Recovered (0):"',
        "hardcode the recovered count in summary.txt",
        (VISUALIZATION,),
    ),
    Mutant(
        "src/testing/storage.py",
        "        recovered=tuple(recovered),\n",
        "        recovered=(),\n",
        "build_run_result discards recovered faults",
        (STORAGE, FRAMEWORK),
    ),
    Mutant(
        "src/testing/storage.py",
        '            recovered=tuple(data.get("recovered", ())),\n',
        "            recovered=(),\n",
        "load_run_result discards archived recovered faults",
        (STORAGE,),
    ),
    Mutant(
        "src/testing/test_framework.py",
        "            recovered.extend(\n"
        "                format_failure(name, adapter, error) for error in series.errors\n"
        "            )\n",
        "",
        "run_test stops collecting recovered faults",
        (FRAMEWORK,),
    ),
    Mutant(
        "src/testing/test_framework.py",
        "else build_adapters(self.config, adapter_class)",
        "else build_adapters({}, adapter_class)",
        "ignore the config's ammeters when building adapters",
        (FRAMEWORK,),
    ),
    Mutant(
        "src/testing/adapters/base.py",
        "    for name, settings in ammeters.items():",
        "    for name, settings in list(ammeters.items())[:3]:",
        "build_adapters drops devices beyond the first three",
        (FRAMEWORK,),
    ),
    Mutant(
        "src/testing/sampler.py",
        "    return isinstance(error, (TransportError, ProtocolError))",
        "    return False",
        "no fault is retryable any more",
        (SAMPLER, FRAMEWORK),
    ),
    Mutant(
        "src/testing/storage.py",
        "uuid.uuid4().hex[:12]",
        "uuid.uuid4().hex[:0]",
        "remove the unique tail of every run ID",
        (STORAGE,),
    ),
)


def run_tests(root: Path, modules: Tuple[str, ...]) -> Tuple[int, str]:
    """Run the named unittest modules against ``root`` instead of the working tree."""
    env = dict(os.environ, PYTHONPATH=str(root), PYTHONDONTWRITEBYTECODE="1")
    try:
        completed = subprocess.run(
            [sys.executable, "-m", "unittest", *modules],
            cwd=root,
            env=env,
            capture_output=True,
            text=True,
            timeout=180,
        )
    except subprocess.TimeoutExpired:
        return 124, "timed out after 180 s"
    return completed.returncode, completed.stderr


def count_tests(output: str) -> int:
    match = re.search(r"Ran (\d+) tests?", output)
    return int(match.group(1)) if match else 0


def failing_tests(output: str) -> Tuple[str, ...]:
    names = set()
    for line in output.splitlines():
        if line.startswith(("FAIL: ", "ERROR: ")):
            label = line.split(" (", 1)[0].strip()
            names.add(label.removeprefix("FAIL: ").removeprefix("ERROR: "))
    return tuple(sorted(names))


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="ammeter-mutation-") as temporary:
        base = Path(temporary) / "base"
        shutil.copytree(REPO_ROOT, base, ignore=IGNORE)

        code, output = run_tests(base, BASELINE)
        executions = count_tests(output)
        print(f"Baseline: {'OK' if code == 0 else 'FAILED'} ({executions} unit tests)")
        if code != 0:
            print(output[-2000:])
            return 1

        killed = survived = skipped = 0
        for index, mutant in enumerate(MUTANTS, start=1):
            path = base / mutant.source
            original = path.read_text(encoding="utf-8")
            if original.count(mutant.old) != 1:
                print(
                    f"M{index:02d} SKIPPED  {mutant.description} "
                    f"(expected one {mutant.old!r}, found {original.count(mutant.old)})"
                )
                skipped += 1
                continue

            run_root = Path(temporary) / f"mutant-{index:02d}"
            shutil.copytree(base, run_root, ignore=IGNORE)
            target = run_root / mutant.source
            target.write_text(original.replace(mutant.old, mutant.new, 1), encoding="utf-8")
            code, output = run_tests(run_root, mutant.modules)
            executions += count_tests(output)

            if code != 0:
                killed += 1
                names = failing_tests(output)
                print(f"M{index:02d} KILLED   {mutant.description}")
                for name in names[:5]:
                    print(f"           by {name}")
                if len(names) > 5:
                    print(f"           ... and {len(names) - 5} more")
            else:
                survived += 1
                print(f"M{index:02d} SURVIVED {mutant.description}")

        print(
            f"\nRESULT: {killed} killed, {survived} survived, {skipped} skipped "
            f"of {len(MUTANTS)} mutants; {executions} test executions"
        )
        return 0 if killed == len(MUTANTS) and survived == 0 and skipped == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
