# Ammeter Test Framework

**Status:** complete. `main.py` starts the three emulators and receives one current reading from each; the framework adds config-driven sampling, statistics, atomic JSON archiving, visualization and faulty-adapter detection without editing that supplied file.

Per the assignment: use the existing ammeter emulation infrastructure; fix code errors and explain the fixes in this document. The root `README.md` is unchanged; its discrepancies are listed under "Deviations from the original README".

## Quick start

Run everything **from the repository root** — `CONFIG_PATH` is relative to it.

```sh
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

| Command | Purpose | Trigger |
|---|---|---|
| `python -m unittest discover -s tests` | Full regression suite (159 tests, ~9 s) | Manual — after every commit |
| `python -m unittest tests.system.test_sample_results` | One campaign into a temp directory (read-only default) | Manual, or as part of discovery |
| `AMMETER_WRITE_SAMPLE=1 python -m unittest tests.system.test_sample_results` | The same campaign twice: temp + `results/sample/` | Manual, env-var gated (`WRITE_SAMPLE` in `tests/system/test_sample_results.py`) |
| `python -m unittest tests.test_fault_corpus -v` | Meta-test: 7/7 detection, 0/7 false positives | Manual, also part of discovery |
| `python main.py` | Frozen demo: starts the emulators and takes one reading from each — **not** the test runner (Ctrl-C to stop) | Manual; also the target of the Ctrl-C test |

Every run is human-invoked: there is no CI workflow, Makefile, tox or pytest configuration (`pyproject.toml` declares packaging metadata only). Each `test_*.py` also ends in `if __name__ == "__main__": unittest.main(...)`, but direct `python tests/.../test_x.py` is unreliable because tests import helpers as `from tests.support import ...`; use `python -m unittest <module>` from the repository root.

The deliverable is the QA suite, not a command-line client: emulator startup lives in test fixtures, campaigns run in-process through `AmmeterTestFramework.run_test()`, and failures are returned as typed entries in `RunResult.errors` (with ammeter, port and cause) while the other ammeters are still archived.

## Environment and installed libraries

| Item | Value |
|---|---|
| Interpreter used | Python 3.14.6 (dev virtualenv `.venv/`) |
| Install command | `pip install -r requirements.txt` |
| Optional editable install | `pip install -e .` uses `pyproject.toml`; it keeps every `src.*` import path and includes `src/testing/defaults.yaml` as package data. |
| Libraries installed | **PyYAML 6.0.3** in a fresh venv — needed by `src/utils/config.py` for `config/config.yaml` |
| Everything else | Python standard library: `socket`, `threading`, `statistics`, `json`, `logging`, `csv`, `unittest` |
| Removed from `requirements.txt` | `numpy`, `scipy`, `seaborn`, `pandas`, `matplotlib` — none was imported anywhere; dependencies are kept minimal. |
| Optional, not required | `matplotlib` stays commented in `requirements.txt` for the guarded visualization import. It is present in this dev venv but not installed by `pip install -r requirements.txt`; if it is absent, plotting is skipped cleanly and CSV/text output still works. Both cases are tested. |

Verified: a fresh virtualenv created from `requirements.txt` alone can import `yaml` and `AmmeterTestFramework`.

## Scope, configuration and deviations

| Frozen supplied files (read-only) | Editable files |
|---|---|
| `Ammeters/*` (emulators and client), `main.py`, `config/config.yaml`, root `README.md`, `src/utils/config.py` | Everything under `src/testing/` and `tests/` (including supplied test files), plus `src/utils/logger.py`, `requirements.txt` and the new `pyproject.toml` |

The supplied `config/config.yaml` has `null` sampling values. We do not edit it: the framework merges its own defaults (in `src/testing/defaults.yaml`) over it before validating. Any change to `requirements.txt` is recorded in the environment table above.

### Sampling settings: where the numbers live

| Meaning | Where it is defined | Effective value |
|---|---|---|
| Measurements per campaign (the readings behind CV/drift) | `src/testing/defaults.yaml` → `measurements_count` | **20 per ammeter** |
| Sampling frequency | `src/testing/defaults.yaml` → `sampling_frequency_hz` | 10 Hz → derived duration 2 s |
| Retries per reading | `src/testing/defaults.yaml` → `retry.max_attempts` | 2 attempts |
| Retry backoff | `src/testing/defaults.yaml` → `retry.backoff_seconds`, `retry.backoff_multiplier` | 0.05 s × 2^retry index → 0.05, 0.10, 0.20, … s |

`measurements_count`, `total_duration_seconds` and `sampling_frequency_hz` are `null` in the frozen config; `sampling.py:load_sampling_config()` merges our defaults over it (null = unset), `resolve_sampling()` validates and derives duration/count when one is missing, and `sampler.py` loops `range(plan.count)` to take the readings. `tests/system/test_sample_results.py` pins the default at 20 — change `src/testing/defaults.yaml` and that assertion together, never the frozen config.

One `run_test()` call is one run: a `RunResult` with a fresh UUID `run_id` (`storage.py:new_run_id()`). There is no global run-count setting; the committed sample is a single campaign, and with `AMMETER_WRITE_SAMPLE=1` the sample test executes two (one temp, one committed).

### Deviations from the original README

The root `README.md` is supplied by the exercise and is not modified. Its values differ from the code:

| Topic | Root README says | Actual code / config |
|---|---|---|
| Greenlee port | 5000 | 5001 (5000 is occupied by macOS ControlCenter) |
| ENTES port | 5001 | 5002 |
| CIRCUTOR port | 5002 | 5003 |
| CIRCUTOR command | `MEASURE_CIRCUTOR -get_measurement` | `MEASURE_CIRCUTOR -get_measurement -current` |
| `examples/run_tests.py` | present | documented as unusable ("don't use it"); not part of the solution |

## What the suite covers

The regression suite has 159 tests (~9 s): 5 skeleton, 10 config/sampling, 43 adapter, 17 sampler, 23 analysis/storage, 19 framework wiring, 16 SUT contract, 4 system, 19 visualization, 1 sample-result and 2 fault-corpus tests. The fix regressions formerly in `tests/test_fixes.py` were redistributed to the modules that own them.

Adapter tests run one shared contract suite against real emulators and the fake. Sampler tests use an injected clock, so timing tests finish in milliseconds. Storage tests write to temp directories and prove atomic writes leave no partial artifact. Framework tests inject fake adapters and one-shot connection doubles. The SUT contract tests cover documented value bounds, exact formula oracles from injected draws, the wire round-trip and the client success path. System tests check the artifact's golden key shape, prove no connection/thread leak across a batch, and run `run_test()` twice from a clean `git archive HEAD` export with stderr asserted empty — no unclassified tracebacks.

### Coverage matrix (happy / boundary / error / failure)

Each behaviour gets a row, each applicable category a cell with a representative test id (`module::test`). `—` means the category does not apply to that layer. The retry column is where transient faults must be scripted, never random.

| Behaviour | Happy | Boundary | Error | Failure / retry |
|---|---|---|---|---|
| Sampling plan | `tests/unit/test_sampler.py::test_exact_count_from_count_and_frequency` | `tests/unit/test_config_sampling.py::test_all_18_config_cases` | `tests/unit/test_config_sampling.py::test_invalid_config_opens_no_socket` | — |
| Sampler loop | `tests/unit/test_sampler.py::test_single_reading_does_not_sleep` | `tests/unit/test_sampler.py::test_count_derived_from_duration_and_frequency` | `tests/unit/test_sampler.py::test_permanent_error_fails_fast_without_backoff` | `tests/unit/test_sampler.py::test_retry_backoff_follows_exponential_schedule`, `test_connect_failure_is_retried_with_the_same_schedule` |
| Adapter ↔ emulator | `tests/integration/test_adapters.py::test_open_read_close_returns_float` | `tests/integration/test_adapters.py::test_truncated_command_is_rejected_by_each_emulator` | `tests/integration/test_adapters.py::test_dead_port_raises_transport_error_naming_endpoint` | `tests/integration/test_adapters.py::test_reopen_yields_another_reading` |
| Campaign orchestration | `tests/unit/test_framework.py::test_run_test_returns_typed_result_per_ammeter` | `tests/unit/test_framework.py::test_single_ammeter_selection` | `tests/unit/test_framework.py::test_broken_ammeter_does_not_erase_the_other_two` | `tests/unit/test_framework.py::test_recovered_transient_does_not_fail_the_run`, `tests/system/test_end_to_end.py::test_no_connection_or_thread_leak_across_a_batch` |
| Storage | `tests/unit/test_storage.py::test_save_list_load_round_trip` | `tests/unit/test_storage.py::test_two_runs_in_one_second_have_different_ids` | `tests/unit/test_storage.py::test_corrupt_artifact_raises_storage_error` | `tests/unit/test_storage.py::test_write_failure_leaves_no_partial_artifact`, `tests/system/test_end_to_end.py::test_run_test_runs_twice_from_a_clean_git_export` |
| Visualization | `tests/unit/test_visualization.py::test_enabled_writes_all_outputs` | `tests/unit/test_visualization.py::test_empty_plot_types_render_nothing` | `tests/unit/test_visualization.py::test_invalid_settings_raise_config_error` | `tests/unit/test_visualization.py::test_absent_matplotlib_skips_cleanly`, `test_plot_render_failure_is_a_note_not_a_crash` |

The classifier decision point is pinned separately by `tests/unit/test_sampler.py::test_transient_errors_are_retryable_permanent_ones_are_not`: transport, timeout, protocol and parse errors retry; config, analysis and storage errors fail fast. Only transient faults retry, with exponential backoff — connection errors and bad replies can recover, configuration/analysis/storage errors cannot — and the injected clock pins the exact 0.05 → 0.10 → 0.20 s schedule.

### Test data sources

| Source | Defined in | Used by | Shape / assertions |
|---|---|---|---|
| Frozen config | `config/config.yaml` | Sample test, framework wiring | Ports 5001–5003 and the exact commands; sampling values are `null` |
| Framework defaults | `src/testing/defaults.yaml` | All framework tests | 20 readings at 10 Hz, retry 2, backoff `0.05 × 2^i`, visualization settings |
| Temp generated configs | `write_config()` in `tests/support.py` and inline in the system tests | Unit, system | Small counts (1–5) and fake ports, so tests stay exact and fast |
| Scripted fake adapters | `FakeAmmeterAdapter`, the `GOOD` tuples, `tests/faulty_adapters.py` | Unit, fault corpus | Floats **or exception instances**, replayed in order |
| Boundary doubles | `patch("socket.socket", side_effect=...)`, `patch(CREATE_CONNECTION, ...)`, `os.replace` failure, fake pyplot, `time.sleep` guard | Unit, integration | Injected faults and exact call assertions; no real socket, sleep or disk write |
| Recorded RNG draws | `record_draws()` in `tests/integration/test_sut_contract.py` | Formula oracles | Keeps the real `random.uniform` draw but records it → exact `V/R`, `B×F`, `Σv·Δt` |
| Live emulator output | Frozen `Ammeters/` + `src/utils/Utils.py` (`random.uniform`) | Contract tests, adapters, sample | Unseeded random floats → **bounds only**: Greenlee 0.01–100, ENTES 5–200, CIRCUTOR 0.001–0.1 |
| Committed evidence | `results/sample/20261118T103405Z-197ff68345e6/` | Deliverable, not an input | One JSON, three CSVs, `summary.txt`, two PNGs; 20 samples per ammeter, `errors: []` |

The assertion policy follows `test-strategy.md`: injected `side_effect=[...]` gives known operands so the value is asserted **exactly**; a recording `side_effect` around the real generator gives exact draws so the **formula** is asserted exactly; `wraps=` supports call count/order, never the value; unmocked sockets are checked against their documented bounds only.

No reference meter exists, so reports never claim trueness: accuracy reporting is limited to precision/stability (CV/drift), and CIRCUTOR's raw values are V·s, not amperes.

### Result archive

Each `<run_id>.json` under `results/runs/` holds `run_id`, `created_utc`, `schema_version`, the raw `config_snapshot`, `effective_settings` (the resolved sampling plan and retry values actually used), `environment` (Python, platform and framework version), per-ammeter `statistics`, raw `samples` and `errors`. `list_runs()` returns IDs oldest-first, `load_run()` returns the validated dict and `load_run_result()` rebuilds a `RunResult`. `compare_runs_by_id(first, second)` reports CV/drift deltas between two archived runs — precision/stability only, never trueness:

```py
from src.testing.storage import compare_runs_by_id, list_runs

first, second = list_runs("results/runs")[-2:]
deltas = compare_runs_by_id(first, second, "results/runs")
```

Artifacts written before `effective_settings` and `environment` were added (including the committed sample) still load; both keys are optional at schema version 1.

### Visualization

A default run writes under `<results-dir>/visualizations/<run_id>/`: `<ammeter>.csv` (`index,current` rows of the raw series), `summary.txt` (the eight precision/stability metrics per ammeter, errors, skip notes and the "no trueness" disclaimer), and `series.png` / `comparison.png` **only if the optional `matplotlib` extra is importable**. A missing or failing plot becomes a `Note:` in `summary.txt`, never a failed run.

Settings live under `analysis.visualization` in `src/testing/defaults.yaml` (`enabled: true`, `backend: csv`, `plot_types: [series, comparison]`, `directory: visualizations`). The frozen `config/config.yaml` keeps `enabled: true` and `plot_types: null`; nulls are treated as "unset", so our defaults apply. `enabled: false` in the config disables all output. `requirements.txt` is unchanged.

### Faulty-adapter corpus

`tests/faulty_adapters.py` defines seven test-only adapters, each breaking one contract from appendix §10 (off-by-one count, ×10 scale, empty reply, leaked connection, constant value, wrong command, late reply), plus a healthy control. `tests/test_fault_corpus.py` injects one faulty adapter as `greenlee` while healthy fakes keep the other two ammeters online; an oracle must fire on the framework's typed `RunResult` (errors, samples, statistics) or on the adapter's connection counters. The pass condition is inverted — a fault passes only when it is surfaced — and the healthy control runs all seven oracles to measure false positives. It prints `Detection score: 7/7` and `False positives: 0/7`. No production emulator or `src/testing/` module is changed: faulty devices live only in the test corpus, which covers the requested error simulation without polluting the SUT. The score measures whether our oracles are watching, not whether the devices are broken.

### Sample results from a regular test run

`tests/system/test_sample_results.py` starts the frozen emulators in threads (by importing `build_emulators` from `main.py` — the file is never edited) and calls `AmmeterTestFramework.run_test()` directly, so a **normal unittest run** produces the JSON artifact and the visualization files. With `AMMETER_WRITE_SAMPLE=1` a second campaign is written to `results/sample/`; exactly one committed campaign there is the deliverable for "Sample test results". All other `results/` output (e.g. `results/runs/`) stays git-ignored, and further sample runs get new `run_id`s and are left untracked rather than committed. The test starts its own emulator servers, so no externally running client or server is needed.

## Fixes and environment notes

The bugs below were fixed during initial bring-up, before the supplied files were frozen. The remaining notes cover platform and version behaviour that is tested around rather than changed in those files.

| # | Bug | Explanation of the fix |
|---|---|---|
| 1 | Second run fails with `Address already in use` (`Errno 48`). | The emulator closes each connection it serves, so the OS keeps that port reserved for about 30 seconds (`TIME_WAIT`). The next run's `bind()` refuses it. Fixed by setting `SO_REUSEADDR` before `bind()`, which lets a new server start right away; a program that is really listening on the port still gets `Errno 48`, so real conflicts are not hidden. On Windows `SO_REUSEADDR` has different semantics and a second server may bind where Unix would refuse, so tests allocate free ports dynamically and start one server per port. |
| 2 | All three ammeters answered `No data received.` | `main.py` sent only the beginning of each command (`b'MEASURE_GREENLEE'`, `b'MEASURE_ENTES'`, `b'MEASURE_CIRCUTOR'`). The emulator compares the request byte-for-byte with its own command and closes the connection without replying when it does not match. Fixed by sending the complete command for each ammeter: `MEASURE_GREENLEE -get_measurement`, `MEASURE_ENTES -get_data`, `MEASURE_CIRCUTOR -get_measurement -current`. |
| 3 | An unrecognised command was ignored: the server closed the connection without a word, so the client could not tell a wrong request from a missing reply. | The server had no branch for a non-matching request. Added one: it now answers `ERR_UNKNOWN_COMMAND` and logs the received bytes, and the client prints that error instead of treating it as a measurement. An empty request is skipped instead of being answered. A wrong command is now reported as an error rather than as silence. |
| 4 | Ports and commands were hard-coded in `main.py` while `config/config.yaml` sat unused with its ammeter block commented out. | The config file is now the single source of truth: `main.py` reads each ammeter's port and command from it instead of repeating the values. At start-up each configured command is compared with the command the emulator actually accepts, so a mismatch stops the run immediately instead of quietly producing `ERR_UNKNOWN_COMMAND` later. |
| 5 | `load_config()` gave a raw traceback for a missing, empty or malformed config file. | It now raises a clear error for each case: `FileNotFoundError` with the path, `ValueError` with the YAML parsing problem, and `ValueError` when the file is empty or is not a mapping. A valid file still returns the parsed mapping. |
| 6 | Ctrl-C ended the run with a raw `KeyboardInterrupt` traceback, which looks the same as a crash and gives no way to tell "stopped by the user" from "failed". | `main()` is now wrapped in a `KeyboardInterrupt` guard that prints `Stopped by user.` and exits with status 0. Covered by a test that sends a real `SIGINT` to a subprocess running `main.py` and checks the output contains no traceback. POSIX `SIGINT` is not a graceful interrupt for a Windows child process, so `tests/system/test_end_to_end.py` uses `CREATE_NEW_PROCESS_GROUP` + `CTRL_BREAK_EVENT` on Windows and `SIGINT` elsewhere. |
| 7 | An integrated run took the first reading from each ammeter and then failed every subsequent one with `Broken pipe`. | The sampler held one connection open for the whole batch, but the frozen emulators answer exactly one request and then close. The sampler now opens a fresh connection for each reading and each retry, and always closes it in a `finally`. A one-shot connection double in the unit tests and the live-emulator adapter tests both pin this behaviour. |

### Version and platform notes

| Concern | Handling |
|---|---|
| `tarfile` extraction filter | `extractall(filter="data")` needs Python 3.12+ (or a backported patch release); `tests/system/test_end_to_end.py` validates archive members itself and uses plain `extractall`, so older interpreters work too. |
| Timer resolution | Windows has a ~15.6 ms timer floor, so tight timing assertions would flake; unit tests inject a fake clock and the two live timing checks use loose tolerances. |
| Paths and encodings | Separators and default encodings differ between platforms; framework paths use `pathlib`, text I/O passes `encoding="utf-8"` and CSV uses `newline=""`. |
| Dependencies | PyYAML is the only required third-party package; matplotlib is imported behind a guard and skips cleanly. |
| Python version | Newer built-in generic or union syntax would break older interpreters, so type hints use `typing.Tuple`/`Mapping` and the package imports on Python 3.10 through 3.14 (the dev interpreter is 3.14.6). |
