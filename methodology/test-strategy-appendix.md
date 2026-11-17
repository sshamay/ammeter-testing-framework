> **Historical reference only — not the active plan.** Active plan: `methodology/test-strategy.md`.
> Kept for the oracle derivations, risk analysis and design rationale behind the short plan.

# Test Strategy & Plan — Ammeter Measurement System

Status: **draft v0.4 — for review**
Source requirements: `Exam/ammeter-test-specification.md`, `README.md`, `config/config.yaml`,
existing code in `Ammeters/`, `src/`.
Related: `docs/test_framework_README.md` (fix log), `methodology/00-preflight-checklist.md` (gates).

## Changelog

**v0.6** — config cases enumerated; determinism scoped correctly

- §4.1's closing sentence ("every row above is one test case … this table is the test plan; §4.1 is the
  design answer") was circular — the table *is* §4.1 — and hid five equivalence classes behind one row.
  Replaced with §4.2: 18 executable cases C-01…C-18 with concrete inputs and expected outputs, plus the
  inclusive-boundary pairs (1 % delta, 1000 Hz) that distinguish `<` from `≤`.
- Defined the "feasible ceiling" that §4.1 previously left as a placeholder:
  `max_sampling_frequency_hz` (default 1000), stated as a chosen constant to be justified later.
- §6.2 said "no test may assert a measurement's value", which contradicted §6.2.3 and the new F-20/F-21.
  Rewritten: determinism belongs to the *setup*. Injected operands → exact assertion is mandatory;
  unmocked over-the-socket readings → bounds and distribution. Added a setup→oracle table and made
  each rung state where it applies.

**v0.5** — symbol audit: the functional test inventory is checked against the code

- Added §5.1: the verified symbol inventory, the 16 tests that actually exist, and the planned rows
  kept visibly separate from the real ones. The phantom names an earlier draft cited
  (`MeasurementAlgorithm`, `AmmeterClient`, `ConfigManager`, `MeasurementServer`, `InputHandler`,
  `OutputHandler`) are listed as non-existent so they cannot reappear.
- Corrected §6.2.2: the `patch(wraps=)` example read `c.args[0]`, which is the *bound* passed in
  (`1.0`, `0.1`), not the value drawn — it would have asserted `I == 10.0` and failed on every run.
  Replaced with a recording `side_effect`, and stated what `wraps=` can and cannot observe.
- Added planned rows for the unasserted behaviours that the current suite skips: wire round-trip,
  empty payload, occupied port, second sequential client, and the successful-client path.

**v0.4** — change authority: what we are allowed to change in the SUT

- Added §0.1 "Change authority" and the §18 SUT policy, derived from the spec's wording
  ("use existing ammeter emulation infrastructure — if you get an error in the code, please fix it")
  and from the contract the README documents.
- §6.2.2 and §6.2.3 rewritten: the formula oracle and golden values now use `patch(..., wraps=)` and
  `side_effect` in-process. No constructor seam, no `Measurement` return type in the emulator, no
  log parsing.
- §9: a stalled client is handled with client-side timeouts; the server's blocking `recv` is recorded as
  a limitation of the provided infrastructure rather than fixed.
- §13 reclassified into allowed fixes, framework-side workarounds, and withdrawn items.
- §19 Q1 updated: a reference mode would be a SUT change and conflicts with §18.

**v0.3** — added §6.2 "Testing nondeterministic output":

- The oracle ladder for random devices: provable bounds, formula oracle, golden values,
  distribution tests, metamorphic statistics, mutation controls.
- Derived (not guessed) figures: provable output ranges per ammeter, analytic means, coefficients of
  variation, and the sample size each oracle needs to be stable.
- Records that seeded testing is **blocked today** by the global RNG reseed (reclassified in §13.2), and
  which planted defect each technique does and does not catch.
- Notes the CIRCUTOR unit-scale inconsistency as independent evidence for the §6.1 precision-only framing.

**v0.2** — added the parts the spec grades as *design*, not just testing:

- §3 Framework contract: unified API, lifecycle, data types, error taxonomy (was missing entirely).
- §4 Config schema and the sampling precedence decision table (the `NULL` blocks in `config.yaml`).
- §6.1 Accuracy vs precision framing for the bonus requirement.
- §7 additions: performance consistency, historical comparison runs.
- §11 Dependency policy and visualization approach.
- §12 Deliverables traceability (4 deliverables + 3 bonus → phase → evidence).
- §13 Known defects the framework branch must fix, with reproduction evidence.
- §14 cross-platform and Python-version specifics (incl. the PEP 649 landmine).
- §19 open decisions with proposed defaults.

**v0.1** — first draft: nested SUTs, levels L0–L5, oracles, determinism policy, fault matrix,
test-the-tester, entry/exit criteria, risks, metrics, sequencing.

---

## 0. What is actually under test

There are **two nested systems**, and conflating them is the most common way this exercise goes wrong:

| | System | Quality question |
|---|---|---|
| **SUT-A** | The three emulators + socket protocol (`Ammeters/`) | Does the device behave per contract? |
| **SUT-B** | The framework we are building (`src/testing/`, sampling, analysis, storage) | Does the tool measure *and* characterise SUT-A correctly? |

That forces a second question most candidates skip: **does the framework actually detect a broken
ammeter?** A tool that reports "all good" for every input is worthless.

**Strategy in one line:** prove the device contract at the bottom, prove the framework's *decisions* in
the middle, prove the framework's *judgement* with deliberately faulty emulators at the top.

### 0.1 Change authority

The spec (line 119) says: *"Use existing ammeter emulation infrastructure - if you get an error in the
code, please fix it. and explain the fix in the documentation."* That grants **one** permission — fixing
errors — and no licence to reshape the device. The README additionally documents each ammeter's port,
command and measurement logic, so changing observable SUT behaviour would also contradict deliverable 2.

Therefore:

- `Ammeters/` may change **only** to fix a defect that manifests in normal operation, and each change is
  logged as a fix with its reproduction.
- Test ergonomics — injection seams, richer return types, reference modes, logging in place of `print` —
  are **not** grounds to modify the SUT. They are solved inside `tests/` (patching, fakes) or inside
  `src/testing/` (our adapters).
- Latent defects that cannot be reproduced in a normal run are **documented as limitations** and worked
  around, not fixed.
- `src/testing/`, `examples/`, `config/` are our deliverable area and may be designed freely.

---

## 1. Scope

**In scope**

- Protocol contract of all three emulators (commands, replies, errors, lifecycle).
- The framework contract itself: API, lifecycle, data types, error taxonomy (§3).
- Config → run behaviour (schema, validation, precedence, defaults).
- Sampling accuracy (count, duration, frequency) under a controlled clock.
- Statistics correctness against independent oracles.
- Result artifacts: schema, uniqueness, retrieval, comparison.
- Failure paths: transport, protocol, config, timing, storage.
- Cross-platform and cross-Python-version sanity.

**Out of scope (stated, not silently skipped)**

- Electrical truth in amperes. The emulators are stimulus; we test contract and model consistency.
- UI/dashboard (none exists).
- Load beyond a small number of concurrent clients (not a requirement; listed as a risk).
- Rewriting the emulators. `Ammeters/` changes only for logged defect fixes (§0.1, §13.1).

---

## 2. Quality model — evaluation criteria as testable properties

| Spec criterion | How it is *tested*, not asserted in prose |
|---|---|
| Code quality & structure | Static checks + review checklist; no dead code (logger is currently dead → flagged) |
| Flexibility | Add a 4th ammeter in a test fixture; require **zero** changes to sampling/analysis/storage |
| Comprehensive error handling | Fault-injection matrix (§9); every branch raises a typed, message-bearing error (§3.4) |
| Clear reporting | Artifact schema validation + golden-file comparison of one run's report |
| Extension/reuse | The same framework drives a fake in-memory ammeter — proves the extension point is real |

The extension test is the sharpest: if the framework can only measure three hard-coded classes, the
"flexibility" criterion is unmet — and the test proves it either way.

---

## 3. Framework contract (design, frozen before code)

The spec's first requirement is a *unified measurement API*. This is the contract tests will pin.

### 3.1 Adapter interface

One protocol every ammeter type implements — the emulators, a fake, and any future device:

```python
class AmmeterAdapter(Protocol):
    name: str                      # "greenlee" | "entes" | "circutor" | ...
    command: bytes                 # exact command accepted by the device

    def open(self, timeout: float) -> None: ...      # connect + handshake
    def read_current(self) -> float: ...             # one measurement, raises on failure
    def close(self) -> None: ...                     # idempotent
    # context-manager support: __enter__ → open, __exit__ → close
```

Rules the tests enforce:

- `read_current()` **returns** a `float`; it never prints. Output formatting belongs to reporting.
- `read_current()` before `open()` raises a typed error, not an `AttributeError`.
- `close()` is idempotent and safe after a failed `open()`.
- No adapter leaves a socket open or a thread alive after `close()` (verified against
  `threading.enumerate()` baseline and file-descriptor count).
- Adding a fourth adapter requires no change outside the adapter module and config.

### 3.2 Data types

```python
@dataclass(frozen=True)
class Measurement:
    value: float
    inputs: dict[str, float]     # what the protocol carried; today {} (value only)

@dataclass(frozen=True)
class Sample:
    ammeter: str
    sequence: int
    value: float
    requested_at: float      # monotonic
    received_at: float
    latency: float

@dataclass(frozen=True)
class AmmeterStats:
    count: int
    mean: float
    median: float
    stddev: float
    minimum: float
    maximum: float
    coefficient_of_variation: float
    drift_per_unit_time: float

@dataclass(frozen=True)
class RunResult:
    run_id: str
    started_utc: str
    config_snapshot: dict
    per_ammeter: dict[str, AmmeterStats]
    samples: dict[str, list[Sample]]
    errors: list[str]
```

Frozen (`frozen=True`) is deliberate: results are artifacts, and a mutable result object invites
accidental post-analysis mutation. Tests assert immutability.

`Measurement` belongs to the **framework adapter layer**, not to `Ammeters/`. The wire protocol carries
only the current, so `inputs` is empty today, and the emulator is deliberately **not** modified to expose
its random draws (§0.1, §18).

### 3.3 Run lifecycle

`load config → validate → build adapters → open all → sample → close all → analyse → persist`

- Any phase failure produces a typed error and a non-zero exit; partial artifacts are either complete
  or absent, never half-written.
- `close()` runs in a `finally` block; Ctrl-C ends the run with a summary of what was collected.
- A run records the config snapshot it used, so a historical result is reproducible after config edits.

### 3.4 Error taxonomy

Criterion #3 is "comprehensive error handling", so the taxonomy is a deliverable, not an implementation
detail:

```
MeasurementError                  # base; every framework error inherits from this
├── ConfigError                   # missing/invalid config, precedence conflict, bad range
├── TransportError                # connect refused, reset, bind conflict
│   └── SampleTimeout             # per-sample deadline exceeded
├── ProtocolError                 # ERR_UNKNOWN_COMMAND, unexpected/misaligned reply
│   └── ParseError                # empty, non-numeric, NaN, inf
├── StorageError                  # unwritable directory, partial write, corrupt artifact
└── AnalysisError                 # insufficient samples, non-finite statistics
```

Message rule: **always names the ammeter, the port and the cause.** Compare the bug this replaces:

```
No data received.                                          # old: no context, no cause
ProtocolError: greenlee:5001 rejected command 'MEASURE_GREENLEE'
  (expected 'MEASURE_GREENLEE -get_measurement')           # new: actionable
```

Per-ammeter failure policy (must be decided, then tested): **continue on ammeter failure, aggregate
errors, exit non-zero** — a broken device should not delete the other two measurements.

---

## 4. Config schema and precedence

`config/config.yaml` currently has `testing.*`, `analysis.*`, `result_management.*` set to `NULL`.
Proposed shape (v0.2 — needs sign-off, §19 Q4):

```yaml
testing:
  ammeters: [greenlee, entes, circutor]     # default: every entry under ammeters
  sampling:
    measurements_count: 100
    total_duration_seconds: null
    sampling_frequency_hz: 10
    max_sampling_frequency_hz: 1000         # hard ceiling; above this, reject
    on_conflict: reject                      # reject | warn_adjust
    timeout_per_sample_seconds: 0.5
    retry: {max_attempts: 2, backoff_seconds: 0.05}

analysis:
  statistical_metrics: [mean, median, stddev, min, max, cv, drift]
  compare_across_ammeters: true
  visualization: {enabled: false, backend: csv, plot_types: []}

result_management:
  results_dir: results/runs
  keep_samples: true
  format: json
  schema_version: 1
  metadata: [run_id, timestamp_utc, config_snapshot, python_version, platform, hostname]
```

### 4.1 Precedence decision table

The spec allows count, duration **and** frequency to be configured, but only two are independent.
Ambiguity here is the single biggest source of "it ran, but the wrong number of samples".

**Proposed rule:** `measurements_count` + `sampling_frequency_hz` are authoritative;
`total_duration_seconds` is derived and, if supplied, must agree within tolerance.

| count | duration | frequency | Result |
|---|---|---|---|
| set | — | set | duration = count / frequency |
| set | set | — | frequency = count / duration |
| — | set | set | count = floor(duration × frequency) |
| set | set | set, consistent (≤1% delta) | accept |
| set | set | set, inconsistent | `ConfigError` |
| — | — | set | `ConfigError`: count or duration required |
| none | none | none | `ConfigError` |
| 0 / negative | any | any | `ConfigError` (boundary test) |
| any | 0 | any | `ConfigError` |
| any | any | 0 | `ConfigError` |
| any | any | > `max_sampling_frequency_hz` | `ConfigError` with the ceiling stated |

### 4.2 Config test cases — the rows above, made executable

The table says what the rule is; these are the cases. All run against a planned pure function
`resolve_sampling(sampling) -> SamplingPlan(count, frequency_hz, duration_seconds)` that raises
`ConfigError` (§3.4). **Planned, P2** — it does not exist yet, so these rows belong to §5.1 group C.

Canonical values: `count=100`, `freq=10`, `duration=10`. `—` means the key is absent/`null`.

| ID | count | duration | freq | Expected |
|---|---|---|---|---|
| C-01 | 100 | — | 10 | plan = (100, 10.0, 10.0); duration derived |
| C-02 | 100 | 10 | — | plan = (100, 10.0, 10.0); frequency derived |
| C-03 | — | 10 | 10 | plan = (100, 10.0, 10.0); count derived |
| C-04 | 100 | 10.0 | 10 | accepted, delta = 0 % |
| C-05 | 100 | 10.1 | 10 | accepted, delta = **exactly 1 %** → the bound is inclusive |
| C-06 | 100 | 10.11 | 10 | `ConfigError`, delta = 1.1 % → first value outside the bound |
| C-07 | — | — | 10 | `ConfigError`, message says count or duration is required |
| C-08 | — | — | — | `ConfigError` (nothing to sample with) |
| C-09 | 0 | — | 10 | `ConfigError`, count must be ≥ 1 |
| C-10 | -5 | — | 10 | `ConfigError` |
| C-11 | 100 | 0 | — | `ConfigError`, duration must be > 0 |
| C-12 | 100 | -1 | — | `ConfigError` |
| C-13 | 100 | — | 0 | `ConfigError`, frequency must be > 0 |
| C-14 | — | 10 | 5000 | `ConfigError`, message names the 1000 Hz ceiling |
| C-15 | — | 10 | 1000 | accepted — the ceiling itself is legal; count = 10 000 |
| C-16 | 100.5 | — | 10 | `ConfigError`, count must be an integer |
| C-17 | `"100"` | — | 10 | `ConfigError`, wrong type (YAML quoted string) |
| C-18 | `.nan` | — | 10 | `ConfigError`, value must be finite |

Rows C-09…C-18 are the ones the one-line "0/negative" and "> ceiling" rows hide: zero, negative,
non-integer, wrong-type and non-finite are **five** equivalence classes, not one. C-05 and C-15 are the
inclusive-boundary twins of C-06 and C-14; a validator that uses `<` instead of `≤` fails one of each
pair and nothing else.

The 1000 Hz default is a **chosen, configurable constant**, not a measurement: every sample costs a
socket round-trip plus one pass of the single-threaded accept loop, so a "5 kHz" config would silently
stretch the run instead of sampling at 5 kHz. The constant must be justified with a measured
round-trip distribution once the sampler exists (§16, tolerance provenance).

---

## 5. Test levels

| Level | What | Count | Speed | Purpose |
|---|---|---|---|---|
| **L0 Contract** | Emulator ⇄ client over real sockets, per ammeter | ~15 | ms | Correct command → number; unknown → typed error; partial/oversized/no payload; connect/close churn |
| **L1 Unit** | Pure logic: stats, config validation, precedence resolver, run-ID, clock/scheduler | ~40 | ms | Deterministic, no I/O, no sleeps |
| **L2 Integration** | Framework × running emulator: one sample, one batch, lifecycle | ~12 | 100 ms | Wiring, timeouts, retries, teardown, no port/thread leak |
| **L3 System/E2E** | Full run from YAML → artifacts on disk | ~5 | seconds | Deliverable works end to end and is reproducible |
| **L4 Non-functional** | Timing accuracy, leak checks, cross-platform, runtime budget | ~8 | varies | Usable, not just correct |
| **L5 Meta** | Seeded-defect (mutation) runs: framework **must** fail | ~10 | seconds | Proves detection power |

Volume concentrates in L0/L1; L3 stays tiny and slow. The current suite is 16 tests in
`tests/test_fixes.py` — mostly L0 plus config (L1) and one process-level Ctrl-C check (L3).
L2, L4 and L5 are the real gaps.

### 5.1 Functional test inventory

**Symbol audit (2026-11-17).** Every name below was read from the working tree
(`grep -rn "^\s*\(class\|def\) " Ammeters/ src/ main.py`). The suite is green in ~1.5 s.

> **Non-existent, never cite in a test row:** `MeasurementAlgorithm`, `MeasurementServer`,
> `AmmeterClient`, `ConfigManager`, `InputHandler`, `OutputHandler`, `Emulator.parseInput`,
> `save_config`, `get_default_config`, `MeasurementAlgorithm.measure`. None of these exist; an
> earlier draft of this plan was built on them and was therefore untestable.

**What actually exists**

| Module | Verified symbols |
|---|---|
| `Ammeters/base_ammeter.py` | `AmmeterEmulatorBase` (ABC), `__init__(port)`, `start_server()`, `get_current_command` (abstract property → `bytes`), `measure_current()` (abstract → `float`) |
| `Ammeters/Greenlee_Ammeter.py` | `GreenleeAmmeter`; command `b"MEASURE_GREENLEE -get_measurement"`; `I = V/R`, `V∈[1,10)`, `R∈[0.1,100)` |
| `Ammeters/Entes_Ammeter.py` | `EntesAmmeter`; command `b"MEASURE_ENTES -get_data"`; `I = B·K`, `B∈[0.01,0.1)`, `K∈[500,2000)` |
| `Ammeters/Circutor_Ammeter.py` | `CircutorAmmeter`; command `b"MEASURE_CIRCUTOR -get_measurement -current"`; `I = dt·ΣV`, 10 samples |
| `Ammeters/client.py` | `request_current_from_ammeter(port, command)` — prints, returns `None` |
| `src/utils/config.py` | `load_config(config_path) -> dict` |
| `src/utils/Utils.py` | `generate_random_float(min_value, max_value)` |
| `src/utils/logger.py` | `TestLogger(test_name)` + `info/error/debug/warning` (dead: no handler, level or file) |
| `src/testing/test_framework.py` | `AmmeterTestFramework(config_path)`, `run_test(ammeter_type)` — stub, returns `None` |
| `main.py` | `AMMETERS`, `build_emulators(config)`, `main()` |

#### A. Tests that already exist (`tests/test_fixes.py`, green)

| ID | Test | Target | Asserts |
|---|---|---|---|
| F-01 | `test_emulator_starts_on_port_left_in_time_wait` | `AmmeterEmulatorBase.start_server()` | binds a port in TIME_WAIT (`SO_REUSEADDR`) and still answers; skipped if the OS allows the rebind anyway |
| F-02 | `test_configured_command_is_accepted_by_each_emulator` | `build_emulators`, `get_current_command` | config command `==` each emulator's property, all three |
| F-03 | `test_truncated_command_is_rejected_by_each_emulator` | same | first word alone `!=` the property (the old client bug) |
| F-04 | `test_ports_come_from_config` | `build_emulators` | `emulators["greenlee"].port ==` configured port |
| F-05 | `test_config_command_drift_stops_startup` | `build_emulators` | drifted command raises `SystemExit` |
| F-06 | `test_every_emulator_class_is_covered` | `AMMETERS` | keys are exactly `{greenlee, entes, circutor}` |
| F-07 | `test_unknown_command_returns_error_marker` | `start_server()` over a socket | reply `== b"ERR_UNKNOWN_COMMAND"` |
| F-08 | `test_known_command_returns_a_number` | same | reply parses as `float` |
| F-09 | `test_client_prints_error_instead_of_measurement` | `request_current_from_ammeter` | stdout has `"Error from port"`, not `"Received current measurement"` |
| F-10 | `test_missing_file` / `test_invalid_yaml` / `test_empty_file` / `test_non_mapping_file` | `load_config` | `FileNotFoundError`; `ValueError` ×3 |
| F-11 | `test_valid_file_returns_mapping` | `load_config` | `dict` with the three ammeter keys |
| F-12 | `test_ctrl_c_exits_without_traceback` | `main()` as a subprocess | no `Traceback`/`KeyboardInterrupt`; prints `"Stopped by user."`; exit 0 |
| F-13 | `test_each_emulator_returns_a_measurement` | all three `measure_current` paths over sockets | each reply parses as `float` |

#### B. Functional tests to add — all address existing symbols, no SUT change (§0.1)

| ID | Test | Target | Asserts |
|---|---|---|---|
| F-14 | Greenlee bounds | `GreenleeAmmeter.measure_current()` | `0.01 ≤ I ≤ 100` (§6.2.1) |
| F-15 | ENTES bounds | `EntesAmmeter.measure_current()` | `5 ≤ I ≤ 200` |
| F-16 | CIRCUTOR bounds | `CircutorAmmeter.measure_current()` | `0.001 ≤ I ≤ 0.1` |
| F-17 | Greenlee formula oracle | `patch("Ammeters.Greenlee_Ammeter.generate_random_float", side_effect=record)` | `I == v/r` from the **returned** draws; exactly 2 draws (§6.2.2) |
| F-18 | ENTES formula oracle | same target in `Entes_Ammeter` | `I == b·k`; 2 draws |
| F-19 | CIRCUTOR formula oracle | same target in `Circutor_Ammeter` | `I == dt·Σ(v₁..v₁₀)`; exactly 11 draws |
| F-20 | Injected golden values | `side_effect=[10.0, 0.1]` | `I == 100.0` exactly; `assert_has_calls([call(1.0,10.0), call(0.1,100.0)])` pins order and constants (§6.2.3) |
| F-21 | Wire round-trip | `start_server()` + patched `measure_current` returning `0.1+0.2` | `float(recv) == 0.1+0.2` — `str()` serialisation is lossless |
| F-22 | Two sequential clients | `start_server()` | second connection also gets a numeric reply (accept loop survives a completed request) |
| F-23 | Empty payload | `start_server()` | client half-closes without sending → `recv` returns `b""` (server `continue`s on `if not data`) — pins current behaviour, no reply |
| F-24 | Occupied port | `AmmeterEmulatorBase.start_server()` | binding an already-bound port raises `OSError` |
| F-25 | RNG helper bounds | `generate_random_float(min, max)` | `min ≤ x < max` for N draws (half-open, matches `random.uniform`) |
| F-26 | Successful client path | `request_current_from_ammeter` against a live emulator | stdout has `"Received current measurement"` and no `"Error from port"` (the positive twin of F-09) |
| F-27 | Config robustness gap | `build_emulators` with a missing ammeter key | currently `KeyError`, not a typed error — pin it now, convert to `ConfigError` in P2 (§3.4) |
| F-28 | Dead logger | `TestLogger("x").info("y")` | **fails today** (no handler/level/file) — red test that drives §13.3, then green once wired |

#### C. Planned framework tests — nothing to point at yet (§3 is design, not code)

These stay in §4–§10 and are **not** functional tests of today's code. They become rows only when
the corresponding module exists: `AmmeterAdapter` contract (§3.1), `resolve_sampling()` against the
18 config cases C-01…C-18 (§4.2), sampling scheduler with injected clock (§8), statistics vs
metamorphic oracles (§6.2.5), `RunResult` schema and retrieval (§3.2), error taxonomy (§3.4), fault
matrix (§9), faulty-adapter corpus (§10).

**Rule:** a test row names a symbol that `grep` finds, or it is labelled *planned* and blocked on a
phase gate from §17. There is no third category.

---

## 6. Oracles

`assert result == expected` is always wrong in measurement software. Three labelled oracle types:

1. **Invariant oracle** — relations that must hold: `I ≈ V/R` (Greenlee), `I ≈ B·K` (ENTES),
   integrated samples (CIRCUTOR), computed from the emulator's *own reported inputs*.
2. **Statistical oracle** — properties, not values: bounded range, mean near distribution midpoint,
   non-degenerate variance over N samples, monotonic response under a narrowed input range.
3. **Golden oracle** — artifact/report shape against a committed golden file, volatile fields
   (run ID, timestamp, duration, hostname) masked.

Rules:

- **No exact float equality against a computed or measured value.** Every numeric assertion carries an
  explicit tolerance and a stated reason for it. The one exception is an **injected-input identity**
  (F-20, F-21): when the test supplies the operands, or asserts a serialisation round-trip, the
  expected value is produced by the same IEEE operations, so `==` is exact by construction, not a
  judgement about physical accuracy.
- A negative test asserts that a *failure is reported*, not merely that nothing crashed.

### 6.1 Accuracy vs precision (spec §5 bonus)

The spec asks to "compare measurements across different ammeter types, determine relative accuracy,
identify the most reliable measurement method". Three emulators simulate **different physics**
(Ohm's law, Hall effect, Rogowski integration) and draw random inputs — there is **no shared ground
truth**, so *trueness* (distance from truth) is not measurable and any claim to it would be unsupported.

What **is** measurable, and what the analysis will report:

| Property | Definition | Comparable across ammeters? |
|---|---|---|
| **Precision / repeatability** | coefficient of variation of N samples | yes |
| **Stability** | drift slope over the run, normalized by mean | yes |
| **Resolution** | distinct values / N samples | yes |
| **Latency** | requested_at → received_at, p50/p95 | yes |
| **Trueness (error vs reference)** | mean − reference | **no reference exists** |

So the deliverable is framed as **relative measurement precision and stability**, with the limitation
stated in the report. If a trueness number is wanted, the only honest route is an **optional reference
mode** (env flag or config) that pins an emulator's internal inputs and exposes the expected current —
an additive extension, explicitly out of the current scope and pending approval (§19 Q1).

A second, independent reason the absolute comparison fails: the three models do not share a unit scale.
`CircutorAmmeter.measure_current()` returns `dt · ΣV`, i.e. **voltage × time**, not current — a Rogowski
coil requires `I = (1/M) · ∫V dt` with mutual inductance `M`, which the emulator omits. So CIRCUTOR
outputs 0.001–0.1 while ENTES outputs 5–200. Comparing those as "amperes" would be meaningless; the
model inconsistency is recorded as an observation, not fixed (it is a modelling choice, not a crash).

---

### 6.2 Testing nondeterministic output

Determinacy is a property of the **test setup**, not of the SUT. The emulator draws at random, but the
draw goes through a module-level name we can patch, so whether the test knows the value is our choice:

| Setup | What the test knows | Oracle |
|---|---|---|
| `patch(..., side_effect=[...])` | the operands exactly — chosen by the test | **exact** value (§6.2.3) |
| `patch(..., side_effect=record)` wrapping the real generator | the operands exactly — recorded after the fact | **exact** formula (§6.2.2) |
| `patch(..., wraps=...)` | the bounds passed in, **not** the draw | call shape only |
| no patch, over a socket | nothing | bounds (§6.2.1), distribution (§6.2.4) |

So the correct rule is not "never assert a value" — it is **assert exactly whenever the input is
injected, and never assert a value when it is not.** A mocked `measure_current()` is a pure function
of known operands; asserting `== 100.0` there is exact, not fragile. The nondeterminism only survives
in the unmocked path: the over-the-socket tests and the one real-draw smoke test per ammeter (§8).

The ladder below is ordered by determinism, not by preference. Which rung a test stands on is decided
by the table above, not by taste:

| # | Technique | Where it applies | Asserts | Flake risk |
|---|---|---|---|---|
| 1 | Injected golden values (§6.2.3) | mocked, unit | exact value + model constants + draw order | none |
| 2 | Formula oracle (§6.2.2) | mocked, real draws recorded | `I == f(draws)`; draw count and order | none |
| 3 | Provable bounds (§6.2.1) | unmocked, and as a cheap invariant everywhere | output inside the analytic range | none |
| 4 | Distribution tests (§6.2.4) | unmocked repetition; generator/model validation | moments match the stated model | low, if tolerance is derived |
| 5 | Metamorphic statistics (§6.2.5) | framework analysis, seeded | maths invariant under known transforms | none |
| 6 | Mutation controls (§6.2.6) | the tests themselves | the oracles detect planted defects | n/a (meta) |

Rungs 1–2 are sufficient to verify the model; 3–4 exist for the unmocked path; 6 proves 1–5 are
actually watching. No unit test of `measure_current()` is allowed to stand on rung 3 alone — if it can
inject, it injects.

#### 6.2.1 Provable bounds

The ranges are constants, so the output range is arithmetic, not a guess:

| Ammeter | Formula | Inputs | Provable output range |
|---|---|---|---|
| Greenlee | `I = V / R` | V ∈ [1, 10), R ∈ [0.1, 100) | **0.01 ≤ I ≤ 100** |
| ENTES | `I = B · K` | B ∈ [0.01, 0.1), K ∈ [500, 2000) | **5 ≤ I ≤ 200** |
| CIRCUTOR | `I = dt · ΣV` (10 samples) | dt ∈ [0.001, 0.01), V ∈ [0.1, 1.0) | **0.001 ≤ I ≤ 0.1** |

```python
self.assertGreaterEqual(current, 0.01)   # Greenlee
self.assertLessEqual(current, 100.0)
```

Deterministic, seed-free, tolerance-free, and a ×10 scale error leaves the range immediately.
`random.uniform` yields `[a, b)`, so assert `≤`, never `<`.

**Misses:** a generator stuck on one legal value.

#### 6.2.2 Formula oracle — in-process, no log parsing

The invariant `I = V/R` is checked at unit level, where the real draws can be **observed** without
changing the SUT. `wraps=` calls the real function, but it only records each call's *arguments* — for
this SUT those are the bounds (`1.0, 10.0` and `0.1, 100.0`), **not** the value drawn. Reading
`call_args[0]` therefore yields the constants and an oracle that asserts `I == 10.0` would fail
every time. The draw has to be recorded on the way back:

```python
draws = []

def record(min_value, max_value):
    value = generate_random_float(min_value, max_value)   # the real generator
    draws.append((min_value, max_value, value))
    return value

with patch("Ammeters.Greenlee_Ammeter.generate_random_float", side_effect=record):
    current = GreenleeAmmeter(port).measure_current()

self.assertEqual(len(draws), 2)              # fails loudly if the patch target is wrong
self.assertEqual([(d[0], d[1]) for d in draws], [(1.0, 10.0), (0.1, 100.0)])  # order + bounds
voltage, resistance = draws[0][2], draws[1][2]
self.assertAlmostEqual(current, voltage / resistance, places=12)
```

Three properties matter: the values are **real** (nothing injected), the relationship holds for what
the code actually drew, and the bounds/order are pinned separately. `draws` must be non-empty — if the
patch target is wrong, the length assertion fails loudly instead of the test passing vacuously.

The same recorder works for ENTES (`B·K`) and CIRCUTOR (11 draws: `dt` + ten voltages), so one helper
covers all three.

**Not** using the printed log. `print` output is debug text, not a contract: it can be reworded freely,
it round-trips floats lossily, and a test that passes because the text matched proves nothing about the
value the client received. Logs are read only to prove that *logging* happened (§13.3, logger).

The invariant is therefore unavailable over the socket — the wire carries only the current — and that is
acceptable: over the socket we assert bounds and distribution (§6.2.1, §6.2.4).

#### 6.2.3 Golden values — injected, not seeded

Exact expected values come from `side_effect`, which is test-side and requires no constructor parameter:

```python
with patch("Ammeters.Greenlee_Ammeter.generate_random_float", side_effect=[10.0, 0.1]):
    self.assertEqual(GreenleeAmmeter(port).measure_current(), 100.0)
```

This tests three things at once: the arithmetic, the **boundary** (probability zero under real draws),
and — with `assert_has_calls([call(1.0, 10.0), call(0.1, 100.0)])` — that the model constants and the
draw order did not change.

Seeding the global RNG would be the alternative, but it is unavailable here without editing the SUT:
`random.seed(time.time())` in `base_ammeter.py.__init__` reseeds the **global** generator, so any test
that seeds first is silently undone by constructing an emulator. Under §0.1 that line is a documented
limitation, not a fix: nothing in a normal run reproduces a failure from it. Injection sidesteps it
entirely.

#### 6.2.4 Distribution tests

Because the input distributions are known, the output moments are analytic:

| Ammeter | Analytic mean | SD | CV | Mean usable as an oracle? |
|---|---|---|---|---|
| ENTES | **68.75** exactly | 41.8 | 0.61 | Yes — SE ≈ 1.32 (1.9 % of mean) at N = 1000 |
| CIRCUTOR | **0.0303** exactly | 0.0151 | 0.50 | Yes — SE ≈ 1.6 % at N = 1000 |
| Greenlee | **0.380** | 1.885 | **≈ 5.0** | **No** — heavy tail; SE ≈ 16 % of mean at N = 1000 |

Greenlee is the trap: `R` can approach 0.1, producing values up to 100 while the mean sits at 0.38. A
mean-based assertion there looks "flaky" when it is simply the wrong statistic. Use **median and
quantiles** for Greenlee.

**Scope:** this rung validates `generate_random_float` and the model constants on the *unmocked* path.
It is not how the framework's own statistics are tested — those run on seeded or injected data and are
exact (§6.2.5). Sampling the SUT 1000 times to check a `mean()` implementation would be slow, flaky and
beside the point.

Tolerance rule — derive it, never guess it:

```
tolerance = z · sd / √N        # z = 1.96 for 95 %
```

For quantities without closed form (Greenlee's median, quantiles, tail shape) generate a **reference
sample in the test** from the same model using its own `random.Random(seed)` and compare, or use a
bucketed χ² / KS check. The seed lives in the test; the SUT is untouched, and the comparison stays
deterministic.

#### 6.2.5 Metamorphic and aggregate controls

At framework level, randomness is the point, so oracles are relational:

- duplicate every sample → mean, median and stddev unchanged
- multiply every sample by k → mean × k, stddev × k, CV unchanged
- N samples in → `stats.count == N` exactly
- constant-valued adapter → stddev = 0, not `ZeroDivisionError`

#### 6.2.6 Mutation controls — which technique catches what

A corpus of faulty adapters proves the oracles above are actually watching:

| Planted defect | Bounds | Formula | Distribution | Injected golden |
|---|---|---|---|---|
| ×10 scale factor | ✅ | ❌ | ✅ | ✅ |
| constant 0.05 (legal for Greenlee) | ❌ | ❌ | ✅ | ✅ |
| `R / V` instead of `V / R` | ⚠️ sometimes | ✅ | ✅ | ✅ |
| draw order changed (voltage second) | ❌ | ❌ | ❌ | ✅ |
| off-by-one sample count | ❌ | ❌ | ✅ | ✅ |
| `NaN` / empty reply | ❌ | ❌ | ❌ | ❌ → needs the protocol oracle (§9) |

No single technique is sufficient — that table is the argument for using all of them.

#### 6.2.7 Which oracle answers which question

| Question | Oracle |
|---|---|
| Is the value physically plausible? | Provable bounds (§6.2.1) |
| Is the arithmetic right? | Formula oracle (§6.2.2) |
| Did the model change? | Injected golden values (§6.2.3) |
| Does the generator match its distribution? | Analytic moments / reference sample (§6.2.4) |
| Does the framework analyse correctly? | Metamorphic statistics (§6.2.5) |
| Are these tests real? | Mutation corpus (§6.2.6) |

**CI policy:** deterministic tests (bounds, injection, formula) form the gate; one real-draw,
no-patching smoke run per ammeter keeps the genuine path covered, so no injected test can hide a wiring
defect. Nothing here depends on changing the SUT.

---


---

## 7. Test design techniques by area

| Area | Technique | Example cases |
|---|---|---|
| Sampling parameters | Equivalence partitioning + boundaries | every row of §4.1; count = 0, 1, 2, N, N+1; frequency above ceiling |
| Protocol | State transition + error guessing from the fix log | before listen, connected-not-sent, unknown, truncated, extra args, closed mid-reply (RST), second client while first is stalled |
| Config | Boundary + negative | missing, empty, malformed, non-mapping, missing key, wrong type, port out of range, duplicate port, command drift |
| Adapter contract | Contract test reused per implementation | the same suite runs against all three emulators **and** a fake adapter |
| Cross-ammeter comparison | Pairwise / combinatorial | 3 ammeters × 3 parameter combos × success/failure = 18, cheap to enumerate |
| Statistics | **Metamorphic** | duplicate dataset → mean/median/stddev unchanged; scale by k → mean × k, stddev × k |
| Nondeterministic output | Bounds + formula + injection + distribution (§6.2) | every draw inside the provable range; `I == V/R` from observed calls; injected exact value; mean within SE-derived tolerance |
| Result management | Idempotency + uniqueness | two runs in the same second get distinct IDs; rerun finds priors; compare 1 vs N runs; empty history |
| **Performance consistency** | Repeated runs, dispersion | same config k = 5 times → spread of means; CV per ammeter; drift per run must be bounded |
| **Historical comparison** | Pairwise across runs | same ammeter across configs; across ammeters in one run; non-comparable configs must be labelled, not silently compared |

Metamorphic testing is the highest-value idea here: it verifies statistics without a known-correct
expected value. Performance consistency and comparison runs are the bonus-requirement test surface.

---

## 8. Determinism policy (anti-flake charter)

- **Inject the clock.** Sampling tests use a fake clock. No test asserts wall-clock timing by sleeping.
  The clock seam lives in the framework (`src/testing/`), not in the SUT.
- **Control randomness from the test side.** `patch(..., side_effect=...)` for chosen values,
  `patch(..., wraps=...)` for observed real draws. No constructor seam in `Ammeters/` (§0.1).
- **One real-draw test per ammeter.** Never mocked, never injected — it proves the genuine path works
  and that the other tests are not passing vacuously.
- **Ports are never hard-coded** in tests: allocate, retry on collision, assert behaviour against a
  closed port rather than assuming one is free. (macOS: port 5000 is held by ControlCenter.)
- **Timing assertions use tolerance bands** derived from the requirement, plus a separate drift test.
- **Flake budget = 0.** A 95%-green test is a defect; quarantine it, do not retry blindly.
- Each test declares itself deterministic, injected, or tolerance-based.

---

## 9. Fault-injection matrix (negative testing)

Every fault must produce a typed, actionable error — never a traceback, never silence.

| Layer | Injected fault | Expected framework behaviour |
|---|---|---|
| Transport | port occupied | `TransportError`, fail fast, names ammeter + port |
| Transport | server slow to start | bounded wait then `SampleTimeout` (no fixed sleep) |
| Transport | connection reset mid-reply | retry policy or typed failure; no thread death |
| Transport | connect but never send | client must not hang: connect/read timeouts on **our** side; the server's blocking `recv` is a documented limitation (§13) |
| Protocol | unknown / truncated / empty / extra-args command | `ProtocolError`; `ERR_UNKNOWN_COMMAND` classified, not swallowed |
| Protocol | non-numeric reply (`NaN`, garbage, empty) | `ParseError`, not a zero measurement |
| Config | invalid sampling combination | `ConfigError` before any socket opens |
| Timing | run overruns duration | documented policy (stop at N, or extend) — tested |
| Storage | unwritable results dir / disk full | `StorageError`; no partial artifact left behind |
| Analysis | n=1 / all-identical values | statistics defined (stddev = 0), not `ZeroDivisionError` |

`NaN` is the case reviewers miss: `float("nan")` parses fine and then poisons every downstream statistic.

---

## 10. Test-the-tester (L5)

A corpus of **deliberately wrong adapters**, each violating one contract; the framework must flag each:

1. off-by-one sample count (returns N−1)
2. wrong scale factor (×10 current)
3. silent `None` / empty reply
4. correct value but never closes the connection
5. constant value (zero variance detected)
6. replies to the wrong command
7. correct protocol but slower than the sampling deadline

Pass condition is inverted: the framework must **report failure** for each. Paired with the opposite
check — a correct run must pass — so false positives are measured too. Report a **detection score
(x/7)**; it is a stronger claim than "N tests pass".

This also satisfies the spec bonus "implement error simulation" without polluting the production
emulators: faulty devices live in the test corpus.

---

## 11. Dependency policy and visualization

Current state violates the "minimize external library dependencies" constraint:
`requirements.txt` declares `numpy`, `scipy`, `matplotlib`, `seaborn`, `pandas`, `pyyaml` — **only
`pyyaml` is imported anywhere**. Proposal:

| Tier | Contents | Rule |
|---|---|---|
| Runtime | `pyyaml` | must stay minimal; `statistics`, `json`, `socket`, `threading`, `csv` from stdlib cover the rest |
| Optional extra | `matplotlib` | visualization only, behind a guarded import |
| Dev | `pytest`, `pytest-xdist` (maybe) | never imported by production code |

**Visualization approach (proposed):** default is stdlib — CSV export per ammeter plus a text/ASCII
summary table; a committed sample artifact proves it. `matplotlib` rendering is a guarded feature: if
the package is missing, the run warns and skips the plot instead of failing. Test: one case with the
extra absent (must skip cleanly), one with it present (file appears, non-empty). This satisfies the
bonus while keeping "minimize dependencies" literally true for the core.

---

## 12. Deliverables traceability

| Spec deliverable | Phase | Evidence artifact |
|---|---|---|
| 1. Complete Python implementation | P1–P4 | code + this contract §3 |
| 2. README with usage instructions | P6 | README "How to run", installed libraries, known deviations (§19 Q3) |
| 3. Sample test results | P5 | generated locally under git-ignored `results/sample/` by `tests/test_sample_results.py`; never committed |
| 4. Brief doc of design decisions | P0/P6 | `docs/test_framework_README.md` + decisions section of this file |
| Bonus: error simulation | P5 | §10 faulty-adapter corpus + detection score |
| Bonus: advanced visualization | P4 | §11 CSV/text default, optional matplotlib |
| Bonus: configuration-driven approach | P0–P3 | §4 schema; a fourth ammeter requires config only |

---

## 13. Defects, workarounds and change classification

The spec (line 119) permits fixing errors in the provided infrastructure and requires the fix to be
documented. §0.1 restricts SUT changes to that permission. This section therefore classifies every
candidate by what it actually is — **observed error fix**, **enhancement**, **framework-side workaround**,
or **our own code**. Each entry in the fix log should carry that label.

### 13.1 Already fixed in PR #1 — and how each is honestly classified

| # | Change | Reproduction | Classification |
|---|---|---|---|
| 1 | `SO_REUSEADDR` before `bind()` | second run → `OSError [Errno 48]` | **error fix** |
| 2 | Client sends the full command | all three → `No data received.` | **error fix** |
| 3 | Server replies `ERR_UNKNOWN_COMMAND` | none — silence is the old behaviour | **enhancement** (observability; the error itself was #2) |
| 4 | Ports/commands read from config + drift guard | none — no mismatch ever occurred | **enhancement** (serves the config-driven bonus) |
| 5 | `load_config` raises clear errors | none — the shipped config is valid | **robustness** (serves the error-handling criterion) |
| 6 | `KeyboardInterrupt` guard | Ctrl-C → raw traceback | **error fix** |

Three of six are error fixes; three are justified enhancements. The fix log should say so rather than
presenting all six as bugs, which is both more accurate and more defensible under review.

### 13.2 Framework-side workarounds — no SUT change

| Issue | Why not fixed in the SUT | What the framework does |
|---|---|---|
| Stalled client blocks the server (`conn.recv` has no timeout) | Only reproducible by an artificially stalled client; a normal run never triggers it | Sets connect/read timeouts on its own sockets and fails that ammeter with `SampleTimeout`; limitation documented |
| `random.seed(time.time())` reseeds the global RNG in `__init__` | Latent; not reproducible in a normal run | Controls randomness with `patch(side_effect=...)` / `patch(wraps=...)`; limitation documented |
| Server threads never stop (daemon threads, infinite `accept` loop) | No shutdown API exists; adding one is a design change | Framework owns its adapters' lifecycle and does not rely on server shutdown; documented |
| Emulators print to stdout from server threads | Changing it alters documented behaviour and is unnecessary | Framework logs separately; the SUT keeps printing |

### 13.3 Withdrawn, or our own code

| Item | Status |
|---|---|
| `examples/run_tests.py` → `ModuleNotFoundError: No module named 'src'` | **Withdrawn** — the README says *"don't use it"*. Fix only if the example is kept, and then in `examples/`, not the SUT |
| Example passes no argument to `run_test()` → `TypeError` | Same as above; resolves when the API is implemented |
| `run_test()` body is `pass` → returns `None` | **Our deliverable** — implement it |
| `Dict` used without import in `src/testing/test_framework.py` → `NameError` on ≤3.13 | **Our code** — fix when implementing; §14 explains why the dev venv hides it |
| `src/utils/logger.py` — dead and broken: never imported, no handler, no level, no file written | **Our code** — fix, wire it into the framework, then test that a line lands in the file |

### 13.4 Remaining SUT fixes

None currently identified: no reproducible error remains in `Ammeters/`. Any future candidate must
supply a reproduction, a root cause, before/after evidence and the classification above — otherwise it
is worked around (§13.2) or documented as a limitation.

---

## 14. Environments, entry and exit criteria

**Python:** dev venv is **3.14.6**. CI matrix minimum: **3.13 + 3.14** (the eager→deferred annotation
boundary; 3.11 if a lower bound is wanted). Any test relying on annotation evaluation must run on both.
This is how a missing `Dict` import — invisible on 3.14 because PEP 649 defers annotations — surfaces as
a `NameError` on 3.13.

**Operating systems:** macOS (dev), Linux, Windows. Known differences that must be designed for, not
discovered:

| Concern | Windows | Unix |
|---|---|---|
| Port reuse | `SO_REUSEADDR` is *not* reuse; needs `SO_EXCLUSIVEADDRUSE` | `SO_REUSEADDR` as used today |
| Abrupt close / RST | differs with `SO_LINGER` availability | supported |
| Ctrl-C | `SIGINT` semantics differ from Unix; `KeyboardInterrupt` still raised | as today |
| Timer resolution | ~15.6 ms floor → timing tolerances must not be tighter | ~1 ms |
| Test process model | no `fork` | `fork` available (we do not rely on it) |

**Entry criteria (Definition of Ready):** §3 contract signed off; §4 schema and precedence signed off;
the framework's clock seam identified — no SUT seam is required or permitted (§0.1); ports allocated
dynamically.

**Exit criteria (Definition of Done):**

- L0–L3 green, deterministic, twice consecutively, from a clean clone.
- L5 detection score = 7/7, false positives = 0.
- Suite runtime within a stated budget (target < 30 s; slow/E2E separable).
- Zero unclassified tracebacks in any error-path test.
- Every row of §4.1 covered by a test; every spec bullet in §12 has evidence.
- One end-to-end run artifact generated locally under ignored `results/` (never committed).
- **SUT change audit:** `git diff` against the supplied `Ammeters/` contains only fixes logged in §13.1
  with a reproduction — no test-only edits.

---

## 15. Risks & mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Sampling-parameter ambiguity unresolved | Framework "correct" by accident; untestable | §4.1 signed off before code |
| Statistical assertions too tight | Chronic flake; suite loses trust | Injected values, reference samples, and tolerances derived per §6.2.4 |
| Ports/threads leak between runs | Fails only on CI | L2 lifecycle + leak assertions |
| Framework tuned to three emulators | "Flexibility" criterion fails | 4th-ammeter extension test |
| Real-clock timing in tests | Flake under CI load | Virtual clock seam |
| Silent-failure class returns (`No data received.`) | Wrong results, no exception | Negative oracles: failure must be *reported* |
| `results/` gitignore blocks sample deliverable | Deliverable 3 unmet at submission | `!results/sample/` exception, verified in a clean clone |
| Trueness claimed without a reference | Technically indefensible | §6.1 framing, limitation stated |
| Asserting a mean on a heavy-tailed signal (Greenlee) | "Flaky" tests that are mis-specified, not flaky | §6.2.4: median/quantiles where CV > 1; tolerance = z·sd/√N |

---

## 16. Metrics reported

- **Requirement traceability:** spec bullets covered / total (§12).
- **Detection score:** planted defects caught / planted (§10).
- **False positives:** correct runs flagged / total correct runs.
- **Flake rate:** target 0.
- **Runtime budget:** per level, slow tests separated.
- **Error-path coverage:** every branch that must raise is checked to raise a *typed* error.
- **Tolerance provenance:** every numeric tolerance cites either `z · sd / √N` or a seeded reference
  sample generated inside the test — no hand-waved ±5 % (§6.2.4).
- **SUT change audit:** lines changed in `Ammeters/`, each traceable to a logged defect fix; the target
  for the framework branch is **zero new SUT changes**.
- Coverage %, if reported at all, only as branch coverage on decision code — line coverage is inflated
  by the E2E path.

---

## 17. Sequencing

| Phase | Focus | Gate |
|---|---|---|
| **P0** | Sign off §0.1 change authority, §3 contract, §4 schema + precedence, §3.4 taxonomy, artifact contract | No code before this |
| **P1** | Clear §13.3 (our own code); L0 contract tests for all three emulators; client returns a value | Device + API contract locked |
| **P2** | L1 units: stats, config validation, precedence table (§4.1), run ID, clock | Pure logic green |
| **P3** | L2/L3: adapters, sampling with injected clock, storage, E2E from YAML | Deliverable works |
| **P4** | L4: timing/drift, leaks, cross-platform matrix, dependency trim, visualization | Usable, not just working |
| **P5** | L5: faulty-adapter corpus, detection score, comparison runs, sample artifacts | Framework proven able to find faults |
| **P6** | README usage + installed libraries, decisions doc, traceability matrix | Submission-ready |

---

## 18. Deliberate non-goals

- No mocking of the socket layer (real ports are cheap and strictly better evidence).
- No assertions on exact float values or exact elapsed times.
- No test whose only purpose is raising a coverage number.
- No retry-until-green in CI.
- No electrical-trueness claims without a reference (§6.1).
- **No SUT changes for testability.** `Ammeters/` is modified only for a defect that reproduces in
  normal operation, with the fix logged (§0.1, §13.1). Injection seams, richer return types, reference
  modes and logging-from-the-device are rejected on principle — control, observation and formatting are
  the framework's job.
- **No log parsing as an oracle.** A measurement is asserted from returned data or observed calls; logs
  are read only to prove that logging happened.

---

## 19. Open decisions (proposed defaults pending your sign-off)

| # | Decision | Proposed default | Alternative |
|---|---|---|---|
| **Q1** | Accuracy framing (§6.1) | Precision/stability comparison, limitation stated | Trueness measurement — would require a reference mode, which is a SUT change and conflicts with §18, so it would need an explicit exception |
| **Q2** | Visualization (§11) | stdlib CSV + text table; matplotlib optional behind a guarded import | matplotlib required for the bonus |
| **Q3** | README (deliverable 2) | Add "How to run" + installed libraries **and** correct the wrong ports/CIRCUTOR command | Leave README untouched, document usage elsewhere |
| **Q4** | Precedence rule (§4.1) | count + frequency authoritative, duration derived, conflict = `ConfigError` | duration + frequency authoritative, or "last one wins" |
| **Q5** | Per-ammeter failure policy (§3.4) | Continue, aggregate errors, exit non-zero | Abort the whole run on first failure |
| **Q6** | Python matrix (§14) | 3.13 + 3.14 | 3.11 + 3.14, or dev version only |
