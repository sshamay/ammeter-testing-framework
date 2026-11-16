# Pre-Flight Checklist — Ammeter QA Exercise

> **Status:** draft, not yet executed.
> **Purpose:** everything that must be true *before* any framework, sampling or analysis code is written. Fixing the provided infrastructure is part of the exam, so it belongs here, not in the solution.
> **Reusability:** sections marked `[generic]` are project-independent and can be copied into any new test-automation repo. Sections marked `[ammeter]` are specific to this exercise.

---

## 0. How to use this document

1. Work top to bottom. Every gate must be **closed** before the next one opens.
2. A gate is closed only when its **Exit criteria** are met and evidenced (command output, screenshot, or a committed file).
3. Never start Gate N+1 to "save time" while Gate N is open — that is exactly how infrastructure bugs get baked into the framework.
4. Anything discovered during a gate that is not a blocker goes into the **Parking lot** at the end, not into the current gate.
5. Record every command you run that changes the machine (installs, versions) directly in `README.md` — the spec requires reporting which libraries were installed.

---

## Gate 1 — Understand the assignment `[ammeter]`

- [ ] Read `Exam/ammeter-test-specification.md` **in full** (the spec explicitly demands this before starting).
- [ ] Read `README.md` in full; note it is partly inaccurate (see Gate 3).
- [ ] Extract the five required capabilities into a single backlog:
  - [ ] Unified measurement API across Greenlee / ENTES / CIRCUTOR
  - [ ] Configurable sampling: measurement count, total duration, sampling frequency
  - [ ] Result analysis: mean, median, std-dev, min, max
  - [ ] Result management: unique run ID, metadata, retrieval and comparison of history
  - [ ] Accuracy assessment across ammeter types (bonus)
- [ ] Extract the evaluation criteria and keep them visible while designing: code quality, framework flexibility, error handling, result reporting, extensibility.
- [ ] Extract the constraints: reuse the existing emulator infrastructure, fix errors and document the fixes, minimise dependencies, stay cross-platform, keep code readable.
- [ ] Write the deliverables list into `README.md` as a checklist so the repo itself tracks completion:
  - [ ] Complete Python implementation
  - [ ] README with usage instructions
  - [ ] Sample test results
  - [ ] Documentation of design decisions
  - [ ] Fix log for pre-existing bugs

**Exit criteria:** a one-page requirements summary exists in the repo (this file plus `README.md` checklists) and every spec bullet maps to a planned artefact.

---

## Gate 2 — Environment and dependency baseline `[generic]`

- [ ] Record interpreter: `python3 --version` (target 3.9+; note the exact version used).
- [ ] Create and activate a virtual environment (`.venv/`, already git-ignored).
- [ ] Decide the **minimum** dependency set. The spec says minimise dependencies, but `requirements.txt` currently pins `numpy`, `scipy`, `matplotlib`, `seaborn`, `pyyaml`, `pandas` while the code only needs `PyYAML` and the stdlib.
  - [ ] Keep `PyYAML` (config loading is already written against it).
  - [ ] Decide explicitly whether plotting (`matplotlib`) is in scope for the bonus; if not, drop `seaborn`/`scipy`/`pandas` from `requirements.txt`.
  - [ ] Do not leave unused heavy pins in the file "just in case".
- [ ] Install, then capture the resolved versions (`pip freeze`) for the README.
- [ ] Verify cross-platform assumptions: `localhost` binding, no POSIX-only paths, no shell-outs, `socket.AF_INET`/`SOCK_STREAM` only.
- [ ] Document in `README.md`: Python version, venv command, install command, exact package list, and any platform caveats.

**Exit criteria:** fresh venv can be created from `requirements.txt` alone and `python -c "import yaml"` succeeds; installed packages are written down.

---

## Gate 3 — Run `main.py`, find the bugs, fix them, document them `[ammeter]`

This gate is a **workflow, not a list of known fixes**. The goal is to make `python main.py` work end to end, and to arrive at that state by observing real behaviour rather than by editing until it stops complaining. Each sub-step produces evidence that survives into the final documentation.

### 3.1 Run it as-is (do not edit anything yet)

- [ ] Create the venv and install `requirements.txt` **before** the first run, so failures are the code's, not the environment's.
- [ ] Run `python main.py` verbatim and capture the full terminal output (exit code, tracebacks, prints, silence).
- [ ] Run it **twice in a row** — the second run is where port-binding and shutdown problems surface.
- [ ] Probe the emulators independently of `main.py`: `nc -zv localhost <port>` / a five-line `socket` script, so "server never started" is separated from "client sent the wrong thing".
- [ ] Write down the **observed** behaviour, without interpretation: what printed, what hung, what returned nothing.

### 3.2 Triage: turn observations into a bug log

- [ ] Open `docs/fix-log.md` and record one row per symptom: **symptom → reproduction → root cause → affected file → severity**.
- [ ] Distinguish *blocking* bugs (the script cannot produce a reading) from *latent* bugs (the script works but the code is unsafe or undocumented). Only blockers must be fixed in this gate; latent ones go to the parking lot with a decision.
- [ ] Confirm each root cause by reading the code at the point of failure — a fix without a named root cause is a guess.
- [ ] Classify each bug as `pre-existing` or `introduced by me`; the spec requires explaining pre-existing fixes, and mixing the two destroys that explanation.

Likely candidates to test for (hypotheses, not conclusions — verify each before touching code):

| Area | Symptom to look for | Where to look |
|---|---|---|
| Ports | Client connects to a port nobody listens on; README/config/`main.py` disagree | `main.py`, `README.md`, `config/config.yaml` |
| Lifecycle | Emulators print "running" then everything dies instantly | `main.py` daemon threads + trailing `pass` |
| Startup race | First request fails, later ones succeed | fixed `time.sleep(5)` instead of a readiness probe |
| Command match | Server accepts the connection, replies with nothing | exact `data == get_current_command` comparison vs truncated client commands |
| Docs drift | README command for CIRCUTOR never matches the implementation | command flag `-current` |
| Rebinding | Second run fails with "Address already in use" | missing `SO_REUSEADDR` |
| Hangs | A request blocks forever with no error | no `settimeout` on accept/recv/connect |
| Import error | `NameError: Dict` before any server starts | `src/testing/test_framework.py` |
| Logging | `results/logs/` exists but is always empty | logger never attaches a handler or level |
| Measurement | Values are implausible or units are wrong | RNG reseeding, CIRCUTOR `Σ V·Δt` |

### 3.3 Fix, one root cause per change

- [ ] Fix blocking bugs in dependency order: **config source of truth → ports → server lifecycle → readiness probe → client command → process keep-alive**.
- [ ] Make the smallest change that removes the root cause; no opportunistic refactors in the same commit.
- [ ] Re-run `python main.py` after each fix and paste the new output into the fix-log row — a fix is only closed when its row has "after" evidence.
- [ ] Prefer a single source of truth: ports and commands belong in `config/config.yaml`, and `main.py`, README and client all read from it.
- [ ] Keep the public shape of the emulator API stable (base class contract: command bytes + `measure_current()`), so the later framework is not built on a moving target.
- [ ] Leave the "make it nice" items (timeout strategy, concurrency, RNG isolation, unit normalisation) for Gate 5 or the parking lot unless they block the run.

### 3.4 Document what was fixed and why

- [ ] `docs/fix-log.md` is complete: every pre-existing bug has symptom, root cause, fix, and proof.
- [ ] Add a short "Fixes applied to the provided infrastructure" section to `README.md` that links to the fix log and states the final run command.
- [ ] Update `README.md` so ports, commands and behaviour match the code exactly — the README is currently the biggest source of false information in the repo.
- [ ] State any accepted-but-unfixed defect explicitly, with the reason it was left alone.

**Exit criteria:**
1. `python main.py` exits cleanly with `Ctrl-C` and returns **one valid reading from each of the three emulators** on a cold start and on an immediate second run.
2. `docs/fix-log.md` has a row per bug, each with reproduction and post-fix evidence.
3. `README.md` matches observed behaviour.
4. No fix was applied without a recorded root cause.

---

## Gate 4 — Repository and workflow hygiene `[generic]`

- [ ] `.gitignore` covers `__pycache__/`, `.venv/`, `.idea/`, `.DS_Store`, `results/`, `*.log` (done).
- [ ] Decide what sample artefacts are committed vs generated: `results/` is ignored, so commit curated samples under `docs/results/` (or similar) if the deliverable requires them.
- [ ] Confirm repo visibility, default branch `main`, and remote `origin` (already pushed once).
- [ ] **Approval gate:** no `git push` without the user's explicit approval in that turn (see `AGENTS.md`). Prepare commits locally and show the exact push command first.
- [ ] Commit message convention: `gate-3: fix port config and readiness probe` style, one logical change per commit.
- [ ] Confirm git identity matches the account that should own the commits.
- [ ] Decide the Python packaging story: keep flat imports (`from Ammeters...`, `from src...`) or add `pyproject.toml`; the spec values readability over packaging, so document the choice.

**Exit criteria:** a clean `git status`, a documented branch/commit policy, and no generated files tracked by accident.

---

## Gate 5 — Define "done" for the solution `[ammeter]`

- [ ] Freeze the **unified API** before implementing it: one entry point that takes an ammeter type and a sampling plan and returns a typed result object.
- [ ] Freeze the **result schema** (run ID, timestamp, ammeter type, command, sample count, frequency, duration, samples, statistics, metadata) and write it down; every later module depends on it.
- [ ] Freeze the **config schema** (`testing.sampling`, `ammeters.<type>.{port,command}`, `analysis.*`, `result_management.*`) and remove `NULL` placeholders.
- [ ] Define the **sampling contract**: what wins when `measurements_count`, `total_duration_seconds` and `sampling_frequency_hz` are all set or all `NULL`? Document precedence and validation rules.
- [ ] Define the **timing strategy** (`time.perf_counter`, drift compensation, what happens when a sample is late).
- [ ] Define the **error taxonomy**: connection refused, timeout, malformed response, unknown command, partial read — and how the framework reports each.
- [ ] Define the **acceptance test** for the exercise itself: three ammeters sampled successfully, statistics produced, results archived and retrievable, README reproducible by a stranger.

**Exit criteria:** API, result schema, config schema, sampling precedence and error taxonomy are written down and reviewed before code is written against them.

---

## Definition of Ready for implementation

Implementation may start only when all of the following are true:

1. `python main.py` returns one valid reading per ammeter, reproducibly.
2. Every **blocking** defect found in Gate 3 is fixed and recorded in `docs/fix-log.md`; non-blocking ones are documented in the parking lot with a decision.
3. `requirements.txt` is minimal and reflects a working venv; installed packages are in `README.md`.
4. Config, result and sampling schemas are frozen.
5. Git policy (approval before push) is acknowledged.

---

## Parking lot

Non-blocking items discovered along the way. Each entry: what, why it matters, decision (fix / accept / defer).

| Item | Why it matters | Decision |
|---|---|---|
| Concurrency in emulator servers | Single-threaded accept loop | |
| RNG seeding per instance | Correlated measurement streams | |
| CIRCUTOR unit (V·s vs A) | Results may not be comparable | |
| Log rotation / retention | Unbounded `results/logs` growth | |
| `pyproject.toml` vs flat imports | Reproducibility for reviewers | |

---

## Changelog

| Date | Change |
|---|---|
| 2026-11-16 | Initial pre-flight checklist created from `Exam/ammeter-test-specification.md`. |
| 2026-11-16 | Gate 3 rewritten as a workflow (run → triage → fix → document) instead of a list of known fixes; suspected defects demoted to verify-me hypotheses. |
