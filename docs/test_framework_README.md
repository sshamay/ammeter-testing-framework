# Test Framework — Fixes & Design Considerations

**Status:** step 1 complete (make `main.py` work), framework skeleton unblocked. `main.py` starts the three emulators and receives one current reading from each.

Per the assignment: use the existing ammeter emulation infrastructure; if there is an error in the code, fix it and explain the fix in the documentation. The original `README.md` is intentionally left unchanged; the deviations are recorded below.

## Environment and installed libraries

| Item | Value |
|---|---|
| Interpreter used | Python 3.14.6 (dev virtualenv `.venv/`) |
| Install command | `pip install -r requirements.txt` |
| Libraries installed | **PyYAML 6.0.3 only** — needed by `src/utils/config.py` for `config/config.yaml` |
| Everything else | Python standard library: `socket`, `threading`, `statistics`, `json`, `logging`, `csv`, `unittest` |
| Removed from `requirements.txt` | `numpy`, `scipy`, `seaborn`, `pandas`, `matplotlib` — none was imported anywhere. The spec asks to minimise dependencies. |
| Optional, not installed | `matplotlib` is kept as a commented line for the guarded visualization import (task T-11). If it is absent, plotting is skipped cleanly. |

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
`feature/end-to-end-regression`). T-07 and T-08 share a branch because `RunResult` stores the statistics. Every increment is
regression-tested before the next begins, and nothing is pushed without approval.

## How to run

Run everything **from the repository root** — `CONFIG_PATH` is relative to it.

```sh
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python main.py                     # frozen demo: one reading from each ammeter; Ctrl-C to stop
python -m src.testing              # framework CLI: measure all ammeters and save a JSON run
python -m src.testing --ammeter entes --no-save
python -m unittest discover -s tests -v   # regression suite, run after every commit
```

The framework CLI accepts `--config PATH`, `--ammeter NAME|all`, `--results-dir DIR` and `--no-save`.
It prints a precision/stability table and returns exit status **0** (all measured), **1** (some
ammeters failed; the rest were archived) or **2** (configuration/analysis/storage failure). It never
edits `main.py`. A broken ammeter is reported with its name, port and cause and does not erase the
other measurements. No reference meter exists, so the report never claims trueness; CIRCUTOR's raw
values are V·s, not amperes.

The regression suite currently has 143 tests (~2.1 s): 16 original fix tests, 5 skeleton tests,
5 config/sampling tests, 39 adapter tests, 13 sampler tests, 19 analysis/storage tests, 18 framework
wiring tests, 12 CLI tests, 13 SUT contract tests and 3 system tests. The adapter tests run one shared
contract suite against real emulators and the fake. Sampler tests use an injected clock, so timing
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
