# Test Strategy & Plan — Ammeter Measurement System

Status: **draft v0.1 — for review**
Source requirements: `Exam/ammeter-test-specification.md`, `README.md`, `config/config.yaml`,
existing code in `Ammeters/`, `src/`.
Related: `docs/test_framework_README.md` (fix log), `methodology/00-preflight-checklist.md` (gates).

---

## 0. What is actually under test

There are **two nested systems**, and conflating them is the most common way this exercise goes wrong:

| | System | Quality question |
|---|---|---|
| **SUT-A** | The three emulators + socket protocol (`Ammeters/`) | Does the device behave per contract? |
| **SUT-B** | The framework we are building (`src/testing/`, sampling, analysis, storage) | Does the tool measure *and* characterise SUT-A correctly? |

That forces a second question most candidates skip: **does the framework actually detect a broken ammeter?**
A tool that reports "all good" for every input is worthless.

**Strategy in one line:** prove the device contract at the bottom, prove the framework's *decisions* in the
middle, prove the framework's *judgement* with deliberately faulty emulators at the top.

---

## 1. Scope

**In scope**

- Protocol contract of all three emulators (commands, replies, errors, lifecycle).
- Config → run behaviour (precedence, validation, defaults).
- Sampling accuracy (count, duration, frequency) under a controlled clock.
- Statistics correctness against independent oracles.
- Result artifacts: schema, uniqueness, retrieval, comparison.
- Failure paths: transport, protocol, config, timing, storage.
- Cross-platform sanity (macOS / Linux / Windows) and port collisions.

**Out of scope (stated, not silently skipped)**

- Physical/electrical realism in amperes — the emulators are stimulus, not the subject.
  We test the *contract* and the *model's internal consistency*, not electrical truth.
- UI/dashboard (none exists).
- Load beyond N concurrent clients (not a requirement; noted as a risk only).
- Fixing pre-existing bugs beyond what blocks running (governed by the fix log).

---

## 2. Quality model — evaluation criteria as testable properties

| Spec criterion | How it is *tested*, not asserted in prose |
|---|---|
| Code quality & structure | Static checks + review checklist; no dead code (logger is currently dead → flagged) |
| Flexibility | Add a 4th ammeter in a test fixture; require **zero** changes to sampling/analysis/storage |
| Comprehensive error handling | Fault-injection matrix (§7); every branch raises a typed, message-bearing error |
| Clear reporting | Artifact schema validation + golden-file comparison of one run's report |
| Extension/reuse | The same framework drives a fake in-memory ammeter — proves the extension point is real |

The extension test is the sharpest: if the framework can only measure three hard-coded classes, the
"flexibility" criterion is unmet — and the test proves it either way.

---

## 3. Test levels

| Level | What | Count | Speed | Purpose |
|---|---|---|---|---|
| **L0 Contract** | Emulator ⇄ client over real sockets, per ammeter | ~15 | ms | Correct command → number; unknown → typed error; partial/oversized/no payload; connect/close churn |
| **L1 Unit** | Pure logic: stats, config parsing, precedence resolver, run-ID generator, clock/scheduler | ~40 | ms | Deterministic, no I/O, no sleeps |
| **L2 Integration** | Framework × running emulator: one sample, one batch | ~10 | 100 ms | Wiring, timeouts, retries, teardown, no port/thread leaks |
| **L3 System/E2E** | Full run from YAML → artifacts on disk | ~5 | seconds | The deliverable works end to end and is reproducible |
| **L4 Non-functional** | Timing accuracy, leak checks, cross-platform, runtime budget | ~8 | varies | Makes it usable, not just correct |
| **L5 Meta** | Seeded-defect (mutation) runs: framework **must** fail | ~10 | seconds | Proves detection power; catches false-negative drift |

Volume concentrates in L0/L1; L3 stays tiny and slow. Today's suite is almost entirely L0 —
L1, L4 and L5 are the real gaps.

---

## 4. The hard part: oracles

In measurement software, `assert result == expected` is always wrong. Three oracle types, each labelled:

1. **Invariant oracle** — relations that must hold: `I ≈ V/R` (Greenlee), `I ≈ B·K` (ENTES),
   integrated samples (CIRCUTOR). Computed from the emulator's *own reported inputs*, so it tests the
   model rather than the transport.
2. **Statistical oracle** — properties, not values: bounded range, mean within tolerance of the
   distribution midpoint, non-degenerate variance over N samples, monotonic response under narrowed input.
3. **Golden oracle** — artifact/report shape and formatting against a committed golden file, with
   volatile fields (run ID, timestamp, duration) masked.

Rules:

- **No exact float equality anywhere.** Every numeric assertion carries an explicit tolerance and a
  stated reason for that tolerance.
- A negative test must assert that a *failure is reported*, not merely that nothing crashed.

---

## 5. Test design techniques by area

| Area | Technique | Example cases |
|---|---|---|
| Sampling parameters | Equivalence partitioning + boundaries | count = 0, 1, 2, N, N+1; duration = 0, 0.001, very long; frequency = 0, 1, 1000, infeasible |
| **Parameter precedence** | Decision table | `count`+`frequency` given, duration omitted; all three given *and inconsistent*; none given. The spec allows all three but only two are independent — the rule must be explicit, then tested |
| Protocol | State transition + error guessing from the fix log | before listen, connected-not-sent, unknown, truncated, extra args, closed mid-reply (RST), second client while first is stalled |
| Config | Boundary + negative | missing, empty, malformed, non-mapping, missing key, wrong type, port out of range, duplicate port, command drift |
| Cross-ammeter comparison | Pairwise / combinatorial | 3 ammeters × 3 parameter combos × success/failure = 18, cheap enough to enumerate |
| Statistics | **Metamorphic** | duplicate dataset → mean/median/stddev unchanged; scale by k → mean × k, stddev × k |
| Result management | Idempotency + uniqueness | two runs in the same second get distinct IDs; rerun finds priors; compare 1 vs N runs; empty history |

Metamorphic testing is the highest-value idea here: it verifies the statistics without needing a
known-correct expected value.

---

## 6. Determinism policy (anti-flake charter)

- **Inject the clock.** Sampling tests use a fake clock. No test asserts wall-clock timing by sleeping.
- **Inject the RNG.** Per-emulator seeded generators, not the global `random` module (currently reseeded
  per instance — a real defect, to be fixed and then tested).
- **Ports are never hard-coded** in tests: allocate, retry on collision, assert behaviour to a closed port
  rather than assuming one is free. (macOS: port 5000 is occupied by ControlCenter — an environment fact.)
- **Timing assertions use tolerance bands** derived from the requirement, plus a separate drift test.
- **Flake budget = 0.** A 95%-green test is a defect; quarantine it, do not retry blindly.
- Each test declares itself deterministic, seeded, or tolerance-based.

---

## 7. Fault-injection matrix (negative testing)

Every fault must produce a **typed, actionable error** — never a traceback, never silence.

| Layer | Injected fault | Expected framework behaviour |
|---|---|---|
| Transport | port occupied | fail fast, name the ammeter, actionable message |
| Transport | server slow to start | bounded wait, then timeout error (no fixed sleep) |
| Transport | connection reset mid-reply | retry policy or typed failure; no thread death |
| Transport | connect but never send | server must not block forever (timeout) |
| Protocol | unknown / truncated / empty / extra-args command | `ERR_UNKNOWN_COMMAND` → classified as protocol error |
| Protocol | non-numeric reply (`NaN`, garbage, empty) | parse error, not a zero measurement |
| Config | invalid sampling combination | rejected before any socket opens |
| Timing | run overruns duration | documented policy (stop at N, or extend) — tested |
| Storage | unwritable results dir / disk full | typed error; no partial artifact left behind |
| Analysis | n=1 / all-identical values | statistics defined (stddev = 0), not `ZeroDivisionError` |

`NaN` is the case reviewers miss: `float("nan")` parses fine and then poisons every downstream statistic.

---

## 8. Test-the-tester (L5)

Build a corpus of **deliberately wrong ammeters**, each violating one contract, and require the framework
to flag each:

1. off-by-one sample count (returns N−1)
2. wrong scale factor (×10 current)
3. silent `None` / empty reply
4. correct value but never closes the connection
5. always returns a constant (zero variance detected)
6. replies to the wrong command
7. correct protocol but slower than the sampling deadline

Pass condition is inverted: the framework must **report failure** for each. Paired with the opposite
check — a correct run must pass — so false positives are measured too. Report a **detection score (x/7)**;
it is a stronger claim than "N tests pass".

---

## 9. Environment & entry/exit criteria

**Environments:** pinned Python version + one secondary for the portability constraint; macOS for dev,
Linux and Windows in CI.

**Entry criteria (Definition of Ready):** config schema frozen; sampling precedence rule written;
clock/RNG seams identified; ports allocated dynamically.

**Exit criteria (Definition of Done):**

- L0–L3 green, deterministic, twice consecutively, from a clean clone.
- L5 detection score = 7/7, false positives = 0.
- Suite runtime within a stated budget (target < 30 s; slow/E2E separable).
- Zero unclassified tracebacks in any error-path test.
- Traceability matrix: every spec bullet has ≥1 covering test.
- One end-to-end run artifact committed as a sample.

---

## 10. Risks & mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Sampling-parameter ambiguity unresolved | Framework "correct" by accident; untestable | Freeze precedence rule before coding |
| Statistical assertions too tight | Chronic flake; suite loses trust | Seeded RNG + tolerance justified per assertion |
| Ports/threads leak between runs | Fails only on CI | Leak-check level + dynamic ports |
| Framework tuned to three emulators | Flexibility criterion fails | 4th-ammeter extension test |
| Real-clock timing in tests | Flake under CI load | Virtual clock seam |
| Silent-failure class returns (like `No data received.`) | Wrong results, no exception | Negative oracle tests: assert failure is *reported* |

---

## 11. Metrics reported

- **Requirement traceability:** spec bullets covered / total.
- **Detection score:** seeded defects caught / planted.
- **False positives:** correct runs flagged / total correct runs.
- **Flake rate:** target 0.
- **Runtime budget:** per level, slow tests separated.
- **Error-path coverage:** every branch that must raise is checked to raise a *typed* error.
- Coverage %, if reported at all, only as branch coverage on decision code — line coverage is inflated
  by the E2E path.

---

## 12. Sequencing

| Phase | Focus | Gate |
|---|---|---|
| **P0** | Freeze schema, precedence rule, error taxonomy, artifact contract | No code before this |
| **P1** | L0 contract tests for all three emulators + client return-value refactor | Device contract locked |
| **P2** | L1 units: stats, config validation, precedence resolver, run ID | Pure logic green |
| **P3** | L2/L3: sampling loop with injected clock, storage, E2E from YAML | Deliverable works |
| **P4** | L4: timing/drift, leaks, cross-platform, runtime budget | Usable, not just working |
| **P5** | L5: seeded-defect corpus, detection score, sample artifacts | Framework proven able to find faults |
| **P6** | Traceability matrix + design-decision doc folded into README / fix log | Submission-ready |

---

## 13. Deliberate non-goals

- No mocking of the socket layer (real ports are cheap and strictly better evidence).
- No assertions on exact float values or exact elapsed times.
- No test whose only purpose is raising a coverage number.
- No retry-until-green in CI.
- No expanding scope into electrical simulation accuracy.

---

## 14. Open questions for review

1. **Accuracy assessment (spec §5, bonus).** With three emulators simulating *different* physics there is
   no shared ground truth, so only *precision* (repeatability, stability) is comparable, not *trueness*.
   Confirm this framing, or add an instrumented reference mode to the emulators.
2. **Visualization dependency.** "Minimize external library dependencies" vs matplotlib — optional extra
   behind a guarded import, or stdlib-only text output?
3. **Sampling precedence.** Which two of the three parameters are authoritative, and what happens when the
   third contradicts them?
