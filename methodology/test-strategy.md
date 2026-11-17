# Test Strategy — Ammeter QA Exam

Goal: one API for three ammeters → configurable sampling → statistics → archived results with unique
IDs → comparison. Bonus: error simulation, visualization, config-driven setup. Deliver: code, usage
docs, sample results, design notes. Graded on structure, flexibility, error handling, reporting, reuse.

**Change scope (frozen supplied files):** `Ammeters/` (all emulators and client), `main.py`,
`config/config.yaml`, root `README.md` — read-only. Its inaccurate ports/commands are recorded as
deviations in `docs/test_framework_README.md`, not fixed.

**Ours:** `src/testing/*`, `src/utils/logger.py`, new files under `tests/`, and `requirements.txt` —
every dependency change must be documented in `docs/test_framework_README.md`. `src/utils/config.py`
is also left alone: validation and sampling resolution go in new `src/testing/` modules.

Detail (oracle derivations, full 18 config cases, risks): `methodology/test-strategy-appendix.md`.

## Plan — tick one task at a time

| # | Task / files | Done when |
|---|---|---|
| [ ] T-01 | Freeze the decisions below. No code. | Decisions accepted. |
| [x] T-02 | Unblock skeleton: `test_framework.py`, `logger.py`, `requirements.txt`. Add missing `Dict` import, logger handler/level/file, trim unused heavy deps (keep PyYAML). | Imports on 3.13 + 3.14; log line written; fresh venv installs. |
| [x] T-03 | Document usage in `docs/test_framework_README.md` (do **not** touch root `README.md`): how to run, installed libs, real ports/commands, root-README deviations. `.gitignore`: add `!results/sample/` exception. | Stranger can follow the docs verbatim; samples can be committed; root README unchanged in `git diff`. |
| [x] T-04 | Config validation + `resolve_sampling()` in new `src/testing/sampling.py`; framework-owned defaults in `src/testing/defaults.yaml` are merged over read-only `config.yaml` (its sampling values are `null`). Do not edit `config.py` or `config.yaml`. | 18 config cases green (appendix §4.2); errors before any socket opens; `git diff` shows no supplied file changed. |
| [x] T-05 | Adapters: new `adapters/`. Three + fake, one shared contract suite; `open`/`read_current`/`close`, timeouts. | All four pass; no socket/thread left open. |
| [ ] T-06 | Sampler: new `sampler.py`. Count/frequency/duration precedence, injected clock, timeout, retry. | Timing tests deterministic, no `sleep()`; exact count. |
| [ ] T-07 | Statistics: new `analysis.py`. Mean, median, stddev, min, max, CV, drift; n=1 and constant values. | Seeded/metamorphic tests exact; no `ZeroDivisionError`. |
| [ ] T-08 | Storage: new `storage.py`. Frozen `RunResult` JSON, unique ID, metadata, list/compare. | Two runs in one second differ; retrieval works; no partial artifacts. |
| [ ] T-09 | Wire it in `src/testing/`: real `run_test()`, new CLI entry point, typed errors, continue-on-failure. `main.py` stays frozen. | `python -m src.testing` runs YAML → artifact; one broken ammeter doesn't erase the other two. |
| [ ] T-10 | E2E + ~10 new L0 tests: `tests/`. L2/L3, clean-clone run. | All levels green twice; no unclassified tracebacks. |
| [ ] T-11 | **BONUS** Visualization: CSV + text table; guarded matplotlib. | CSV written; missing plot package skips cleanly. |
| [ ] T-12 | **BONUS** Error simulation: faulty-adapter corpus. | Detection score x/7; false positives measured. |
| [ ] T-13 | **BONUS** Comparison report: precision/stability from CV and drift. | No trueness claim; limitation stated. |
| [ ] T-14 | Sample results + final docs: `docs/test_framework_README.md` (fix log + design decisions), spec → evidence map. | Deliverables 1–4 have committed artifacts. |

Bonus rows can be dropped without breaking the core deliverable. T-01…T-10 are sequential; T-11…T-13
can start after T-09; T-14 is last.

## Decisions (frozen)

| Topic | Decision |
|---|---|
| API | `AmmeterAdapter`: `open(timeout)`, `read_current() -> float`, `close()`, context manager; never prints. Same contract test for all devices + fake. |
| Config | Ports/commands from `config.yaml`; `build_emulators()` guards drift. Count + frequency win, duration derived; >1 % conflict → `ConfigError`; 1000 Hz ceiling (configurable). |
| Timing | Injected clock in our code; no wall-clock assertions. |
| Errors | Typed: `ConfigError`, `TransportError`/`SampleTimeout`, `ProtocolError`/`ParseError`, `StorageError`, `AnalysisError`; message names ammeter, port, cause. Report, keep other results, exit non-zero. |
| Results | Frozen `RunResult` JSON: ID, UTC time, config snapshot, stats, samples, errors. |
| Accuracy | No reference → compare precision/stability only. CIRCUTOR outputs V·s, so raw values aren't comparable as amperes. |
| Dependencies | PyYAML + stdlib; matplotlib optional behind a guarded import. |

Tests may name only symbols that exist (appendix §5.1), or be labelled *planned*. `MeasurementAlgorithm`,
`AmmeterClient`, `ConfigManager`, `MeasurementServer`, `InputHandler`, `OutputHandler` do not exist.

## How we test

| Level | Scope |
|---|---|
| L0 — SUT | Real sockets: correct command → number, unknown → `ERR_UNKNOWN_COMMAND`, empty → `b""`, second client answered, port reuse, wire round-trip. 16 tests already green + ~10 new. |
| L1 — Unit | 18 config cases, statistics, sampler with fake clock, run ID, error taxonomy. |
| L2 — Integration | Adapter ↔ live emulator: one sample/batch, timeout, no leaks. |
| L3 — E2E | YAML → JSON artifact; Ctrl-C; two runs → distinct IDs; clean clone. |
| L5 — Meta | Faulty adapters (scale, constant, empty, wrong command, never close, slow, off-by-one) must be flagged; score x/7. |

### All tests we plan to add, by category

Categories: **Contract** (L0, real sockets) · **Unit** (L1, no I/O) · **Integration** (L2, framework ↔ emulator)
· **System** (L3, YAML → artifact) · **Meta** (L5, test-the-tester) · **Non-functional** (perf).
F-IDs are from appendix §5.1. "existing" = already in `tests/test_fixes.py` (16 tests, green).

| Test | Category | Exam ask | Task |
|---|---|---|---|
| Adapter contract: `open`/`read_current`/`close`, context manager, on 3 emulators | Contract + Integration | Unified API | T-05 |
| Fake adapter passes the same contract suite | Unit | Reuse / extension criterion | T-05 |
| 4th ammeter added via adapter + config only | Integration | Flexibility + config-driven bonus | T-05 |
| `run_test()` returns a typed result for each ammeter | Integration | Unified API + reporting | T-09 |
| Client success path F-26 | Contract | Unified API | T-10 |
| C-01…C-18 precedence and validation | Unit | Sampling + config-driven bonus | T-04 |
| Fake clock: exact count from count/frequency/duration | Unit | Sampling | T-06 |
| Per-sample timeout → `SampleTimeout` | Integration | Sampling + error handling | T-06 |
| Retry after transient failure | Integration | Sampling + error handling | T-06 |
| No socket/thread leak across a batch | Integration | Sampling + code quality | T-05/T-10 |
| Mean, median, stddev, min, max on injected data | Unit | Result analysis | T-07 |
| Metamorphic: duplicate → unchanged; ×k → mean ×k, CV same | Unit | Result analysis | T-07 |
| n=1 and constant data → stddev 0, no exception | Unit | Analysis + error handling | T-07 |
| `RunResult` schema + config snapshot metadata | Unit | Result management + reporting | T-08 |
| Two runs in one second → distinct IDs | Unit | Result management | T-08 |
| Save → list → compare historical runs | Integration | Result management | T-08 |
| Write failure leaves no partial artifact | Integration | Results + error handling | T-08 |
| Bounds F-14…F-16 (Greenlee 0.01–100, ENTES 5–200, CIRCUTOR 0.001–0.1) | Contract | Accuracy | T-10 |
| Formula oracles F-17…F-19 + injected golden F-20 | Unit | Accuracy | T-10 |
| Seeded distribution reference for the generator | Unit | Accuracy | T-13 bonus |
| CV/drift comparison report, no trueness claim | System | Accuracy bonus | T-13 bonus |
| Repeated-run dispersion / performance consistency | Non-functional | Performance-consistency bonus | T-13 bonus |
| Unknown / empty command: `ERR_UNKNOWN_COMMAND` (F-07 existing, F-23 new) | Contract | Error handling | existing + T-10 |
| Non-numeric or `NaN` reply → `ParseError` | Integration | Error handling | T-09 |
| Occupied port / refused connect → `TransportError` (F-24) | Contract | Error handling | T-10 |
| Invalid config → `ConfigError` before any socket opens | Unit | Error handling | T-04 |
| Typed error names ammeter + port + cause | Unit | Error handling + reporting | T-09 |
| Continue on failure, aggregate errors, exit non-zero | System | Error handling | T-09 |
| Ctrl-C exits cleanly (existing) | System | Error handling | existing |
| Golden-shape check of the result artifact | System | Clear reporting | T-08/T-10 |
| Logger actually writes a line F-28 | Unit | Reporting + code quality | T-02 |
| Sample results committed | System | Deliverable 3 | T-14 |
| 7 faulty adapters detected, score x/7 | Meta | Error-simulation bonus | T-12 bonus |
| Correct run passes — measured false positives | Meta | Error-simulation bonus | T-12 bonus |
| CSV + text-table artifact present | System | Visualization bonus | T-11 bonus |
| matplotlib absent → clean skip | Unit | Visualization bonus | T-11 bonus |

**Sequencing:** core first (T-01…T-10) covers all five required capabilities and all five evaluation
criteria. Bonus rows are T-11…T-13 and can be added afterwards or dropped; only they are labelled
bonus above. Every exam ask has at least one core test except the explicitly bonus features
(error simulation, visualization, performance consistency, cross-ammeter comparison report).

Determinism depends on the setup, not the SUT:

- Injected `side_effect=[...]` → operands known → assert the **exact** value.
- Recording `side_effect` around the real generator → exact draws → assert the **exact** formula.
- `wraps=` records bounds only → use for call count/order, never for the value.
- Unmocked sockets → bounds only: Greenlee `0.01–100`, ENTES `5–200`, CIRCUTOR `0.001–0.1`. One real-draw test per ammeter.

## Done

- [ ] `python main.py` still works unchanged, and the framework CLI (`python -m src.testing`) works from a clean clone, twice.
- [ ] All spec capabilities have a test and a committed sample artifact.
- [ ] Error paths raise typed errors; no silent "No data received".
- [ ] `git diff` on `Ammeters/` contains only fixes already logged — no test-only edits.
- [ ] No push without explicit approval.

Document, don't fix: global RNG reseed; server blocking `recv` / no shutdown / daemon threads; emulator
`print` output; CIRCUTOR V·s units; Python 3.14 deferring annotations (CI needs 3.13). None fails a
normal run. Run everything from the repo root (`CONFIG_PATH` is relative).
