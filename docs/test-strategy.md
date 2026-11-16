# Test Strategy & Plan — Ammeter Measurement System

Status: **draft v0.2 — for review**
Source requirements: `Exam/ammeter-test-specification.md`, `README.md`, `config/config.yaml`,
existing code in `Ammeters/`, `src/`.
Related: `docs/test_framework_README.md` (fix log), `methodology/00-preflight-checklist.md` (gates).

## Changelog

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
- Rewriting the emulators for elegance. Only defects and additive, justified extensions.

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
| any | any | > feasible ceiling | `ConfigError` with the ceiling stated |

Every row above is one test case. This table is the test plan for config; §4.1 is the design answer.

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

Volume concentrates in L0/L1; L3 stays tiny and slow. Today's suite is almost entirely L0 —
L1, L4 and L5 are the real gaps.

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

- **No exact float equality anywhere.** Every numeric assertion carries an explicit tolerance and a
  stated reason for it.
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
| Result management | Idempotency + uniqueness | two runs in the same second get distinct IDs; rerun finds priors; compare 1 vs N runs; empty history |
| **Performance consistency** | Repeated runs, dispersion | same config k = 5 times → spread of means; CV per ammeter; drift per run must be bounded |
| **Historical comparison** | Pairwise across runs | same ammeter across configs; across ammeters in one run; non-comparable configs must be labelled, not silently compared |

Metamorphic testing is the highest-value idea here: it verifies statistics without a known-correct
expected value. Performance consistency and comparison runs are the bonus-requirement test surface.

---

## 8. Determinism policy (anti-flake charter)

- **Inject the clock.** Sampling tests use a fake clock. No test asserts wall-clock timing by sleeping.
- **Inject the RNG.** Per-adapter seeded generators, not the global `random` module (currently reseeded
  per instance — a real defect, to be fixed and then tested).
- **Ports are never hard-coded** in tests: allocate, retry on collision, assert behaviour against a
  closed port rather than assuming one is free. (macOS: port 5000 is held by ControlCenter.)
- **Timing assertions use tolerance bands** derived from the requirement, plus a separate drift test.
- **Flake budget = 0.** A 95%-green test is a defect; quarantine it, do not retry blindly.
- Each test declares itself deterministic, seeded, or tolerance-based.

---

## 9. Fault-injection matrix (negative testing)

Every fault must produce a typed, actionable error — never a traceback, never silence.

| Layer | Injected fault | Expected framework behaviour |
|---|---|---|
| Transport | port occupied | `TransportError`, fail fast, names ammeter + port |
| Transport | server slow to start | bounded wait then `SampleTimeout` (no fixed sleep) |
| Transport | connection reset mid-reply | retry policy or typed failure; no thread death |
| Transport | connect but never send | server must not block forever (timeout server-side) |
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
| 3. Sample test results | P5 | `results/sample/` committed (needs a `.gitignore` exception — `results/` and `*.log` are ignored today) |
| 4. Brief doc of design decisions | P0/P6 | `docs/test_framework_README.md` + decisions section of this file |
| Bonus: error simulation | P5 | §10 faulty-adapter corpus + detection score |
| Bonus: advanced visualization | P4 | §11 CSV/text default, optional matplotlib |
| Bonus: configuration-driven approach | P0–P3 | §4 schema; a fourth ammeter requires config only |

---

## 13. Known defects the framework branch must fix

The spec (line 119) says: use the existing infrastructure, and if you hit an error, fix it and explain
the fix. These are reproduced, not hypothetical:

| # | Defect | Reproduction | Fix |
|---|---|---|---|
| F1 | Example cannot import the package | `python examples/run_tests.py` → `ModuleNotFoundError: No module named 'src'` | runnable entry point (`python -m examples.run_tests`) or path bootstrap |
| F2 | Example calls the API wrongly | `python -m examples.run_tests` → `TypeError: run_test() missing 1 required positional argument: 'ammeter_type'` | align signature with usage |
| F3 | `run_test()` is a stub | body is `pass` → returns `None`; comparison prints nothing, silently | implement, or fail loudly while unimplemented |
| F4 | `Dict` never imported | `def run_test(...) -> Dict` in `src/testing/test_framework.py`; imports fine on 3.14 (PEP 649 defers annotations), **`NameError` on 3.13 and below** | import or use `dict[str, Any]` |
| F5 | No server-side timeout | a client that connects and never sends blocks every later request | deadline on `recv` (§9) |
| F6 | Global RNG reseeded per emulator | `random.seed(time.time())` in `base_ammeter.py` distorts cross-ammeter statistics | per-instance generator |
| F7 | Logger is dead and broken | never imported; no handler, no level, no file written | fix and wire it, then test that a line lands in the file |

F4 is the clearest argument for the version matrix in §14 — the dev venv is Python 3.14.6, where the
bug is invisible.

---

## 14. Environments, entry and exit criteria

**Python:** dev venv is **3.14.6**. CI matrix minimum: **3.13 + 3.14** (the eager→deferred annotation
boundary; 3.11 if a lower bound is wanted). Any test relying on annotation evaluation must run on both.

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
clock/RNG seams identified; ports allocated dynamically.

**Exit criteria (Definition of Done):**

- L0–L3 green, deterministic, twice consecutively, from a clean clone.
- L5 detection score = 7/7, false positives = 0.
- Suite runtime within a stated budget (target < 30 s; slow/E2E separable).
- Zero unclassified tracebacks in any error-path test.
- Every row of §4.1 covered by a test; every spec bullet in §12 has evidence.
- One end-to-end run artifact committed as a sample.

---

## 15. Risks & mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Sampling-parameter ambiguity unresolved | Framework "correct" by accident; untestable | §4.1 signed off before code |
| Statistical assertions too tight | Chronic flake; suite loses trust | Seeded RNG + justified tolerances |
| Ports/threads leak between runs | Fails only on CI | L2 lifecycle + leak assertions |
| Framework tuned to three emulators | "Flexibility" criterion fails | 4th-ammeter extension test |
| Real-clock timing in tests | Flake under CI load | Virtual clock seam |
| Silent-failure class returns (`No data received.`) | Wrong results, no exception | Negative oracles: failure must be *reported* |
| `results/` gitignore blocks sample deliverable | Deliverable 3 unmet at submission | `!results/sample/` exception, verified in a clean clone |
| Trueness claimed without a reference | Technically indefensible | §6.1 framing, limitation stated |

---

## 16. Metrics reported

- **Requirement traceability:** spec bullets covered / total (§12).
- **Detection score:** seeded defects caught / planted (§10).
- **False positives:** correct runs flagged / total correct runs.
- **Flake rate:** target 0.
- **Runtime budget:** per level, slow tests separated.
- **Error-path coverage:** every branch that must raise is checked to raise a *typed* error.
- Coverage %, if reported at all, only as branch coverage on decision code — line coverage is inflated
  by the E2E path.

---

## 17. Sequencing

| Phase | Focus | Gate |
|---|---|---|
| **P0** | Sign off §3 contract, §4 schema + precedence, §3.4 taxonomy, artifact contract | No code before this |
| **P1** | Fix F1–F4 (§13); L0 contract tests for all three emulators; client returns a value | Device + API contract locked |
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
- No rewriting the emulators for style — only F5–F7 and additive, approved extensions.

---

## 19. Open decisions (proposed defaults pending your sign-off)

| # | Decision | Proposed default | Alternative |
|---|---|---|---|
| **Q1** | Accuracy framing (§6.1) | Precision/stability comparison, limitation stated; reference mode deferred | Add an instrumented reference mode to emulators for trueness |
| **Q2** | Visualization (§11) | stdlib CSV + text table; matplotlib optional behind a guarded import | matplotlib required for the bonus |
| **Q3** | README (deliverable 2) | Add "How to run" + installed libraries **and** correct the wrong ports/CIRCUTOR command | Leave README untouched, document usage elsewhere |
| **Q4** | Precedence rule (§4.1) | count + frequency authoritative, duration derived, conflict = `ConfigError` | duration + frequency authoritative, or "last one wins" |
| **Q5** | Per-ammeter failure policy (§3.4) | Continue, aggregate errors, exit non-zero | Abort the whole run on first failure |
| **Q6** | Python matrix (§14) | 3.13 + 3.14 | 3.11 + 3.14, or dev version only |
