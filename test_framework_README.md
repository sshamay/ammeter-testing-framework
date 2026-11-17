# Test Framework — Fixes & Design Considerations

**Status:** core deliverable complete (T-01…T-10), with the visualization (T-11) and faulty-adapter corpus (T-12) bonuses merged. `main.py` starts the three emulators and receives one current reading from each; the framework adds config-driven sampling, statistics, atomic JSON archiving, visualization and fault detection without editing that supplied file.

Per the assignment: use the existing ammeter emulation infrastructure; if there is an error in the code, fix it and explain the fix in the documentation. The original `README.md` is intentionally left unchanged; the deviations are recorded below.

## Environment and installed libraries

| Item | Value |
|---|---|
| Interpreter used | Python 3.14.6 (dev virtualenv `.venv/`) |
| Install command | `pip install -r requirements.txt` |
| Libraries installed | **PyYAML 6.0.3** in a fresh venv — needed by `src/utils/config.py` for `config/config.yaml` |
| Everything else | Python standard library: `socket`, `threading`, `statistics`, `json`, `logging`, `csv`, `unittest` |
| Removed from `requirements.txt` | `numpy`, `scipy`, `seaborn`, `pandas`, `matplotlib` — none was imported anywhere. The spec asks to minimise dependencies. |
| Optional, not required | `matplotlib` stays commented in `requirements.txt` for the guarded visualization import (T-11). It is present in this dev venv but not installed by `pip install -r requirements.txt`; if it is absent, plotting is skipped cleanly and CSV/text output still works. Both cases are tested. |

Verified: a fresh virtualenv created from `requirements.txt` alone can import `yaml` and `AmmeterTestFramework`.

## Scope of changes

| Frozen supplied files (read-only) | Editable files |
|---|---|
| `Ammeters/*` (emulators and client), `main.py`, `config/config.yaml`, root `README.md`, `src/utils/config.py` | Everything under `src/testing/` and `tests/` (including supplied test files), plus `src/utils/logger.py` and `requirements.txt` |

The supplied `config/config.yaml` has `null` sampling values. We do not edit it: the framework merges
its own defaults (in `src/testing/defaults.yaml`) over it before validating. Any change to
`requirements.txt` is recorded in the "Environment and installed libraries" table above.

Work is delivered as a progressive rollout, one branch per increment. `foundation/skeleton-and-docs`
holds only the foundation/skeleton/docs tasks (T-01…T-03); each later increment is stacked on the
previous one (`feature/config-driven-sampling` → `feature/ammeter-adapter-layer` →
`feature/measurement-sampler` → `feature/result-analysis-and-storage` → `feature/framework-wiring` →
`feature/end-to-end-regression` → `feature/visualization` → `test/sample-results-run` →
`feature/faulty-adapter-corpus`). T-07 and T-08 share a branch because `RunResult` stores the
statistics. Every increment is
regression-tested before the next begins, and nothing is pushed without approval.

## How to run

Run everything **from the repository root** — `CONFIG_PATH` is relative to it.

```sh
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python main.py
python -m src.testing
python -m src.testing --ammeter entes --no-save
python -m src.testing --no-visualize
python -m unittest discover -s tests -v
AMMETER_WRITE_SAMPLE=1 python -m unittest tests.test_sample_results
```

On Windows activate with `.venv\Scripts\activate`. `python main.py` is the frozen one-reading demo
(Ctrl-C to stop); `python -m src.testing` is the framework CLI that measures all ammeters and saves a
JSON run; `--no-visualize` skips CSV/text/PNG output; `python -m unittest discover -s tests -v` is the
regression suite run after every commit; the last command writes a local sample run under
`results/sample/` (git-ignored).

The framework CLI accepts `--config PATH`, `--ammeter NAME|all`, `--results-dir DIR`, `--no-save` and
`--no-visualize`. It prints a precision/stability table and returns exit status **0** (all measured),
**1** (some ammeters failed; the rest were archived) or **2** (configuration/analysis/storage failure).
It never edits `main.py`. A broken ammeter is reported with its name, port and cause and does not erase
the other measurements. No reference meter exists, so the report never claims trueness; CIRCUTOR's raw
values are V·s, not amperes.

### Visualization (T-11)

A default run writes, under `<results-dir>/visualizations/<run_id>/`:

- `<ammeter>.csv` — `index,current` rows of the raw series, one file per ammeter (stdlib `csv`);
- `summary.txt` — the eight precision/stability metrics per ammeter, errors, skip notes and the
  "no trueness" disclaimer; the same table is printed to stdout;
- `series.png` and `comparison.png` — **only if the optional `matplotlib` extra is importable**.
  A missing or failing plot becomes a `Note:` in stdout and `summary.txt`, never a failed run.

Settings live under `analysis.visualization` in our `src/testing/defaults.yaml` (`enabled: true`,
`backend: csv`, `plot_types: [series, comparison]`, `directory: visualizations`). The frozen
`config/config.yaml` keeps `enabled: true` and `plot_types: null`; nulls are treated as "unset", so
our defaults apply. `enabled: false` in the config or `--no-visualize` on the CLI disables all output.
`requirements.txt` is unchanged by this increment.

### Faulty-adapter corpus (T-12)

`tests/faulty_adapters.py` defines seven test-only adapters, each breaking one contract from appendix
§10 (off-by-one count, ×10 scale, empty reply, leaked connection, constant value, wrong command, late
reply), plus a healthy control. `tests/test_fault_corpus.py` injects one faulty adapter as `greenlee`
while healthy fakes keep the other two ammeters online; an oracle must fire on the framework's typed
`RunResult` (errors, samples, statistics) or on the adapter's connection counters. The pass condition
is inverted — a fault passes only when it is surfaced — and the healthy control runs all seven
oracles to measure false positives:

```sh
python -m unittest tests.test_fault_corpus -v
```

It prints `Detection score: 7/7` and `False positives: 0/7`. No production emulator or `src/testing/`
module is changed: the faulty devices live only in the test corpus, which is how the spec's "error
simulation" bonus is met without polluting the SUT.

### Sample results from a regular test run

`tests/test_sample_results.py` starts the frozen emulators in threads (by importing `build_emulators`
from `main.py` — the file is never edited) and calls `AmmeterTestFramework.run_test()` directly, so a
**normal unittest run** produces the JSON artifact and the visualization files under `results/sample/`:

```sh
AMMETER_WRITE_SAMPLE=1 python -m unittest tests.test_sample_results
```

Without the env var the same test runs into a temp directory, keeping the regression suite
read-only. All of `results/` is git-ignored, so generated artifacts are never committed.
Note that `python -m src.testing` is a client: it needs emulator servers already listening on the
configured ports; the test file starts them itself.

The regression suite currently has 167 tests (~9 s): 5 skeleton tests, 10 config/sampling tests,
43 adapter tests, 13 sampler tests, 19 analysis/storage tests, 19 framework wiring tests,
12 CLI tests, 16 SUT contract tests, 4 system tests, 23 visualization tests, 1 sample-result test
and 2 fault-corpus tests. The fix regressions formerly in `tests/test_fixes.py` were redistributed
to the modules that own them when that file was removed.
The adapter tests run one shared contract suite against real emulators and the fake. Sampler tests use an injected clock, so timing
tests finish in milliseconds. Storage tests write to temp directories and prove atomic writes leave
no partial artifact. The framework tests inject fake adapters and one-shot connection doubles. The
SUT contract tests cover documented value bounds, exact formula oracles from injected draws, the wire
round-trip and the client success path. System tests check the artifact's golden key shape, prove no
connection/thread leak across a batch, and run `python -m src.testing` twice from a clean `git
archive HEAD` export with stderr asserted empty — no unclassified tracebacks.

## Deviations from the original README

The root `README.md` is supplied by the exercise and is not modified. Its values differ from the code:

| Topic | Root README says | Actual code / config |
|---|---|---|
| Greenlee port | 5000 | 5001 (5000 is occupied by macOS ControlCenter) |
| ENTES port | 5001 | 5002 |
| CIRCUTOR port | 5002 | 5003 |
| CIRCUTOR command | `MEASURE_CIRCUTOR -get_measurement` | `MEASURE_CIRCUTOR -get_measurement -current` |
| `examples/run_tests.py` | present | documented as unusable ("don't use it"); not part of the solution |

## Fixes

| # | Bug | Explanation of the fix |
|---|---|---|
| 1 | Second run fails with `Address already in use` (`Errno 48`). | The emulator closes each connection it serves, so the OS keeps that port reserved for about 30 seconds (`TIME_WAIT`). The next run's `bind()` refuses it. Fixed by setting `SO_REUSEADDR` before `bind()`, which lets a new server start right away; a program that is really listening on the port still gets `Errno 48`, so real conflicts are not hidden. |
| 2 | All three ammeters answered `No data received.` | `main.py` sent only the beginning of each command (`b'MEASURE_GREENLEE'`, `b'MEASURE_ENTES'`, `b'MEASURE_CIRCUTOR'`). The emulator compares the request byte-for-byte with its own command and closes the connection without replying when it does not match. Fixed by sending the complete command for each ammeter: `MEASURE_GREENLEE -get_measurement`, `MEASURE_ENTES -get_data`, `MEASURE_CIRCUTOR -get_measurement -current`. |
| 3 | An unrecognised command was ignored: the server closed the connection without a word, so the client could not tell a wrong request from a missing reply. | The server had no branch for a non-matching request. Added one: it now answers `ERR_UNKNOWN_COMMAND` and logs the received bytes, and the client prints that error instead of treating it as a measurement. An empty request is skipped instead of being answered. A wrong command is now reported as an error rather than as silence. |
| 4 | Ports and commands were hard-coded in `main.py` while `config/config.yaml` sat unused with its ammeter block commented out. | The config file is now the single source of truth: `main.py` reads each ammeter's port and command from it instead of repeating the values. At start-up each configured command is compared with the command the emulator actually accepts, so a mismatch stops the run immediately instead of quietly producing `ERR_UNKNOWN_COMMAND` later. |
| 5 | `load_config()` gave a raw traceback for a missing, empty or malformed config file. | It now raises a clear error for each case: `FileNotFoundError` with the path, `ValueError` with the YAML parsing problem, and `ValueError` when the file is empty or is not a mapping. A valid file still returns the parsed mapping. |
| 6 | Ctrl-C ended the run with a raw `KeyboardInterrupt` traceback, which looks the same as a crash and gives no way to tell "stopped by the user" from "failed". | `main()` is now wrapped in a `KeyboardInterrupt` guard that prints `Stopped by user.` and exits with status 0. Covered by a test that sends a real `SIGINT` to a subprocess running `main.py` and checks the output contains no traceback. |
| 7 | An integrated run took the first reading from each ammeter and then failed every subsequent one with `Broken pipe`. | The sampler held one connection open for the whole batch, but the frozen emulators answer exactly one request and then close. The sampler now opens a fresh connection for each reading and each retry, and always closes it in a `finally`. A one-shot connection double in the unit tests and the live-emulator CLI test both pin this behaviour. |

## Design considerations

| # | Decision | Rationale |
|---|---|---|
| 1 | Fault injection lives only in `tests/`. | Each faulty adapter violates one adapter contract; the production adapters and the frozen emulators never hear about them. The SUT stays untouched and the detection score measures whether our oracles are watching, not whether the devices are broken. |

## Platform and version caveats

The supplied emulators are frozen, so differences that originate there are documented and tested
around rather than "fixed" by editing them.

| Concern | Impact | Handling |
|---|---|---|
| Windows port reuse | `Ammeters/base_ammeter.py` sets `SO_REUSEADDR`, which does not mean the same thing on Windows as on Unix; a second server may bind where Unix would refuse. | Tests allocate free ports dynamically and start one server per port; the frozen emulator is unchanged. |
| Ctrl-C | POSIX `SIGINT` is not a graceful interrupt for a Windows child process. | `tests/test_fixes.py` uses `CREATE_NEW_PROCESS_GROUP` + `CTRL_BREAK_EVENT` on Windows and `SIGINT` elsewhere. |
| `tarfile` extraction filter | `extractall(filter="data")` needs Python 3.12+ (or a backported patch release). | `tests/test_end_to_end.py` validates archive members itself and uses plain `extractall`, so older interpreters work too. |
| Timer resolution | Windows has a ~15.6 ms timer floor; tight timing assertions would flake. | Unit tests inject a fake clock; the two live timing checks use loose tolerances. |
| Paths and encodings | Separators and default encodings differ between platforms. | Framework paths use `pathlib`, text I/O passes `encoding="utf-8"` and CSV uses `newline=""`. |
| Dependencies | Plot extras must not be required. | PyYAML is the only required third-party package; matplotlib is imported behind a guard and skips cleanly. |

Type hints deliberately use `typing.Tuple`/`Mapping` rather than newer built-in generic or union
syntax, so the package imports on Python 3.10 through 3.14 (the dev interpreter is 3.14.6).
