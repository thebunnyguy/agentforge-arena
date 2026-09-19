# Phase-0 Integration Report — ORACLE x ATLAS

Integration branch: **`integration/phase0-benchmark-integrity`**. Verified code state: **`2ee57c845420c541ed879999fbd394e8bd16b57d`**
(everything after that commit is documentation and evidence only, including one test docstring). `master` is untouched; the frozen `oracle` and
`codex/phase-0-evaluation-integrity` branches are untouched; **no model re-evaluation was run**.

The two questions the integrated product can now answer:

1. *Did this evaluation happen freshly, traceably, durably, under the right identity?* — **ATLAS**.
2. *Can we trust the benchmark, hidden tests, controls and task version that judged the agent?* — **ORACLE**.

## 1. Result at a glance

| | Result |
|---|---|
| Merge | Both merges textually clean; merged tree = ORACLE ∪ ATLAS exactly (verified file-by-file). Only `pipeline.py` was touched by both sides (disjoint hunks). |
| Full repository suite (clean worktree, final code) | **612 passed, 0 failed, 0 skipped** (9:00) |
| Phase-0 acceptance canary | **passes**; receipt identical to the isolated-ATLAS receipt (evaluation ids normalized) |
| ORACLE integrity suite | **61 / 61** |
| FULL benchmark audit (fresh, integrated) | **HEALTHY 15 · NEEDS_REVIEW 2 · PROVISIONAL 7 · INVALID 0** — identical to the frozen ORACLE baseline on every check, control, mutation count, finding and provenance hash |
| Remediation manifest | 18 tasks / 540 runs / 51 prior-pass cells — re-derived from the untouched historical DB, all per-task values match |
| `reports/runs.sqlite` SHA-256 | `42b6dad8…838ced` before, after every test group, after the audits, after the smoke test — **byte-identical** |
| Defects found by integration | **2** (one ORACLE-side stale test pin, one ATLAS-latent digest instability) — both reproduced, attributed, fixed minimally, regression-tested |
| ATLAS behaviour modified | **one** computation: `jobs._task_digest` plus a 2-line bytecode helper (+15/−1 lines in `afa_api/jobs.py`); everything else in ATLAS is byte-identical to frozen |

## 2. Branch and merge history

| SHA | Commit | Role |
|---|---|---|
| `fd423abfcc6bb883b513c2b967fb5a2683b8b710` | master | parent of the integration branch (had not moved) |
| `d0efbc431d3687588074d1690d0c61ffdf4f01ef` | frozen ORACLE | merged source |
| `1e1a788cadd5ed35fed9fe37d8e8ebbba922bf07` | frozen ATLAS | merged source |
| `cee935465545288cf422a9615a4e9473380e6f9b` | **ORACLE merge** (`--no-ff`) | tree hash `7ecccf90…` == `oracle`'s tree |
| `3c7162b87ce18dd971943d13a24acf1b62a3deec` | pre-integration ATLAS baseline | recorded *before* ATLAS was merged |
| `1c15d0cfa9dfe66c77fa515c17abe682dd10ac5b` | **ATLAS merge** (`--no-ff`) | |
| `1142d39a7e23547b1b531db78673a6821a86d906` | integration fix 1 (ORACLE-side defect) | stale test pin |
| `4b7d712e35933b5b4ae181a33756a65bcc06e146` | cross-system integration tests | 33 tests (58 after fix 2) |
| `2ee57c845420c541ed879999fbd394e8bd16b57d` | integration fix 2 (ATLAS-latent defect) | digest ignores bytecode |
| *final docs commit* | this report + evidence | documentation only |

Order followed the plan: baseline of ATLAS in isolation (own worktree, own test run, DB hash bracketed) → ORACLE merge and
focused sanity → study ATLAS against the ORACLE tree and predict conflicts (`git merge-tree` dry run) → ATLAS merge →
verification → cross-system tests → fresh audit → smoke test.

## 3. Conflict resolution

**There were no textual conflicts.** `git merge-tree --write-tree` predicted this and the merge confirmed it. The complete
list of paths modified by both sides relative to the merge base is a single file:

### `runner/afa_runner/pipeline.py`

| | Behaviour |
|---|---|
| ORACLE (~L310) | adds `overlay_diff(task, overlay_root)` — the one shared overlay-then-grade primitive used by references, known-bad controls, semantic mutants and alternatives — and rewrites `_reference_diff` to delegate to it |
| ATLAS (~L43) | adds `RunRecord.run_id: int | None = None` (native persistence identity; absent before save, populated on load) |
| Integrated | **both**, verified by diffing the merged file against each side: merged − ORACLE = exactly ATLAS's 3-line `run_id` hunk; merged − ATLAS = exactly ORACLE's `overlay_diff` hunks |
| Why both survive | the hunks are disjoint (a dataclass field vs. a function). `run_id` sits *before* `grade_report`, which is a positional-binding hazard for a 12th positional argument, but ORACLE never constructs `RunRecord` (it goes through `score_run`) and no in-repo caller is positional, so nothing mis-binds |

Semantic retention is also proven by a test (`test_runrecord_and_overlay_primitives_coexist_in_the_merged_pipeline`):
`run_id` is a defaulted field ordered before `grade_report`; `pipeline.overlay_diff is afa.overlay_diff`;
`_reference_diff(task) == overlay_diff(task, task.reference_dir)`; and ATLAS's mock agent produces a run whose file/line
counts equal ORACLE's overlay diff of the reference and scores 1.0.

## 4. ATLAS architecture review (independent; full baseline in `ATLAS_PRE_INTEGRATION_BASELINE.md`)

* **Identity hierarchy.** `evaluation_jobs.id` (uuid, one request) → `evaluation_trials (evaluation_id, task_id, idx)` (one
  requested position) → `runs.id` (one raw execution). Never collapsed to `model + task + idx`; `runs` deliberately has no
  uniqueness on that tuple.
* **Fresh / resume / reuse.** Fresh is the default and always re-executes (canary A vs B: disjoint runs). Resume keeps the
  evaluation id and completed run ids and executes only pending positions. Reuse is explicit, requires exact equality of the
  source's *stored* snapshot with a snapshot *recomputed from current disk* (model, backend, generation, ordered
  `task_id/task_version/task_digest`, repeats), creates no raw rows, and labels evidence `reused`/`provisional` with source and
  origin ids.
* **Persistence.** One raw run, its scores/diff/test results, the `job_runs` link and the trial completion commit in one
  transaction; the owner/claim fence is evaluated after the first raw INSERT holds the write lock.
* **Recovery.** OS `flock` + owner/claim tokens; a stale worker cannot publish over a successor; startup requeues dead owners.
* **DB ownership.** Evidence DB is never a default or a writable target (alias/symlink guarded); working DB is seeded by the
  SQLite backup API and published no-clobber; migrations are additive/idempotent and fail closed.
* **Reports.** `report.json` (versioned) and `report.md` come from the same persisted evidence via read-only connections and are
  byte-identical after a restart. **Provider.** `mock` / `ollama` / `openai_compat` are distinct; `openai_compat` really calls
  `/v1/chat/completions`.

Integration-relevant assumptions the review recorded (pre-registered as P1–P14, outcomes in §12): ATLAS assumes
`tasks/<id>/task.json` carries `id` and a string `version`; it hashes the task directory; its mixed-version guard is global and
per-(agent, task); `runs.task_version` and the trial/snapshot version are independent copies.

## 5. ORACLE preservation

Everything below is present in the merged tree and byte-identical to frozen `oracle` (the merged tree equals ORACLE's tree
outside ATLAS's files, the baseline docs, and the changes in §6).

* **Benchmark Integrity Engine** — `integrity/afa_integrity` (core, all checks, CLI, provenance, reports, pack audit), its
  fixtures and 61 tests.
* **Checks** — reference validation, no-op, hidden-import closure, protected-path probes (with the corrected, non-overstated
  `_pytest` finding), declared controls, mutation testing, determinism, isolation (UNVERIFIABLE, excluded from status), health
  precedence `INVALID > NEEDS_REVIEW > UNVERIFIABLE > PROVISIONAL > HEALTHY`.
* **Controls** — 157 tracked files under `tasks/*/integrity/` (known-bad, semantic mutants, alternatives, declared equivalents).
* **Mutation system** — generic AST mutation plus the accounting (generated / unsupported / declared-equivalent / intercepted /
  relevant / killed / survived); no single mutation score.
* **Remediation** — hardened hidden suites (19 files), 18 `task.json` version bumps and contract clarifications, the
  `runner/afa_runner/diffing.py` protected-file addition (`pytest.py`), `overlay_diff`.
* **Manifests and policy** — `integrity/pack-audit/remediation-manifest.{json,md}` (unchanged), the frozen audit summaries and
  `docs/AUDIT_EVIDENCE_POLICY.md`.
* **Residual limitations remain visible**: 2 NEEDS_REVIEW, 7 PROVISIONAL, isolation UNVERIFIABLE.

## 6. Defects found by integration, and how each was handled

Both followed reproduce → classify → attribute → regression → smallest fix → rerun focused → rerun full.

### 6.1 Stale test pin on the frozen ORACLE branch (ORACLE-side; not an integration effect)

The first clean post-merge full-suite run gave **552 passed, 2 failed**. Both failures were
`runner/tests/test_grader.py` assertions `len(report.run_input.hidden) == 6` for `fix-list-dedup`. ORACLE's remediation
(`e2e4513`) added two hidden tests (6 → 8) and did not update the pin.

* **Attribution (checked, not assumed):** fails on the ORACLE-only tree `cee9354` (== frozen `oracle`); passes on frozen ATLAS.
  So **frozen `oracle@d0efbc4` itself fails the full repository suite** — its mission-2 verification ran the integrity suite and
  audits but not `runner/tests`. Disclosed in the ORACLE journal (erratum appended).
* **Fix (`1142d39`):** assert that the graded test *names* equal the test functions the hidden suite defines (read from its
  source). Stricter than the count and stable under future hardening; not a weakening.

### 6.2 `task_digest` depended on the checkout (ATLAS-latent, exposed by integration)

ATLAS hashes **every file** under `tasks/<id>/`, including untracked `__pycache__/*.pyc`. Identical committed content therefore
produced different digests depending on the checkout. Measured on the integrated tree: **22 of 24 tasks** had a different
digest in a developer checkout than in a pristine worktree of the same commit (e.g. `toposort` `995b1dc0…` vs `00858816…`).
That breaks the invariant "`task_digest` == current task contents" (my own first test of it was tautological and could not see
this) and would spuriously trip fail-closed drift refusals — or make a campaign's digests irreproducible across machines.

* **Why the grader's definition is the right one:** `afa_runner.grader` strips `__pycache__`, `*.pyc`, `*.pyo` from every clean
  room (framework §9), so bytecode can never influence a grade. Excluding exactly that set aligns two existing definitions.
* **Cost check before changing:** the committed evidence DB has **0** evaluation jobs and **0** runs with a `job_id`, so no
  persisted snapshot can be orphaned; on a pristine tree the new digest is **byte-identical to the old one for all 24 tasks**;
  with bytecode excluded, developer checkout == pristine == digest over `git ls-files` for all 24 tasks.
* **Fix (`2ee57c8`):** single edit point `jobs._task_digest` (+15/−1). Everything else — ORACLE's `integrity/` subtree,
  `task.json`, grading and snapshot files — is still hashed. `.DS_Store` and other non-bytecode junk are deliberately *not*
  excluded (the grader does not exclude them; a `snapshot/.DS_Store` would reach the clean room), so they still fail closed.
* **Tests (written first; they failed on the unfixed code):** digest equals the digest of git-tracked files for all 24 tasks
  (an independent reference), bytecode never causes drift, and real content changes still do.

## 7. Verification results

**ORACLE-only integration state (before ATLAS)** — tree identical to `oracle`; `integrity/tests` **61 passed** (audit_fixtures 8,
controls 13, health 15, hidden_import_closure 5, mutation_engine 7, overlay 9, pack 1, protected_paths 3; 164 s); FULL audit
on a clean worktree **15/2/7/0**, all 24 tasks identical to the frozen audit.

**ATLAS-focused, after merge (clean worktree, before any addition)** — 14 / 24 / 12 / 8 / 15 / 18 / 14 / 34 / 1 passed for
identity / jobs-API / reports / live projection / store / providers / A2 / A3 / canary — **identical counts to the isolated
ATLAS baseline**.

**Final, on the verified code (`2ee57c8`, clean worktree, sequential groups)**

| Group | Passed | Time |
|---|---|---|
| evaluation identity | 14 | 18.0 s |
| jobs / API | 24 | 35.8 s |
| reports | 12 | 20.5 s |
| live projection | 8 | 3.3 s |
| store / persistence | 15 | 0.2 s |
| providers | 18 | 0.3 s |
| boundaries A2 / A3 | 14 / 34 | 9.7 s / 39.6 s |
| **Phase-0 acceptance canary** | **1** | 10.4 s |
| **cross-system integration tests** | **58** | 37.7 s |
| **ORACLE integrity suite** | **61** | 184.7 s |
| **FULL repository suite** | **612 passed, 0 failed, 0 skipped, 4 warnings** | **540.8 s (9:00)** |

`612 = 493 (ATLAS suite) + 61 (integrity) + 58 (new)`. Warnings are Starlette's `httpx` TestClient deprecation and pytest's
non-collectable `TestSuiteSpec` dataclass notices. Logs: `evidence/final-test-run/`; the first (2-failure) run:
`evidence/post-merge-first-run-2-failures/`.

**Cross-system tests** (`tests/test_integration_oracle_atlas.py`, 58): snapshot version/digest for all 18 remediated tasks
(18); version lineage raw run → trial → `/results` → `report.json` → `report.md` for the three formerly-INVALID tasks (3);
API version signal flags exactly the 18 tasks (1); historical evidence never restamped or pooled into a new evaluation (1);
global guard preserved (1); reuse control + incompatible-snapshot reuse fails closed, two variants (3); legacy evidence cannot
be reused (1); digest scope characterization (1); digest == committed content for all 24 tasks (24) and bytecode-ignored (1);
`RunRecord`/`overlay_diff` coexistence (1); ORACLE controls through the merged runner (2); manifest matches the DB (1).
They were **mutation-checked**: bypassing the reuse compatibility check, removing the mixed-version guard, and making the digest
ignore `integrity/` each made the corresponding tests fail (ATLAS files restored afterwards; `git status` clean).

**Phase-0 canary receipt (merged + fixed)**: A `[1221,1222]`, B `[1223,1224]` (disjoint), C reuse `[1221,1222]` (no new
evidence), D interrupted → resumed executing only `{idx:1, seed:1001}` → `[1225,1226]`; restart/result/report matches all
`true`; 0 unexpected thread errors; historical SHA unchanged. Identical to the isolated-ATLAS receipt once the random
evaluation ids are normalized. `evidence/canary/canary-receipt-integrated.json`.

## 8. FULL benchmark audit (fresh, integrated)

Run on a clean worktree of `2ee57c8` (772.8 s): **HEALTHY 15 · NEEDS_REVIEW 2 · PROVISIONAL 7 · INVALID 0**, matching the frozen
ORACLE baseline (15/2/7/0). It was not just the counts: `evidence/audit/compare_audits.py` compares, per task, the status,
every check result, every control verdict, all mutation accounting, findings and provenance hashes (task.json, snapshot,
reference, grading, controls) and reports **identical** for all 24 tasks vs the ORACLE-only audit and for all 20 tasks retained
in the frozen committed evidence. So the difference attributable to integration is **none**, and nothing was manufactured
toward "24 HEALTHY".

* NEEDS_REVIEW (2, unchanged): `fix-list-dedup` (mutation adequacy could not be assessed — every generated mutant was
  unsupported / declared-equivalent / intercepted), `refactor-order-validation` (benign gate-7 import closure).
* PROVISIONAL (7, unchanged): `async-batched`, `async-first-success`, `async-gather-bounded`, `grid-paths`,
  `merge-intervals`, `top-k-frequent`, `two-sum-indices` — no controls declared.
* Evidence stored per the evidence policy: `integrity/pack-audit/integrated-full-summary.{json,md}` plus per-task detail for the
  two NEEDS_REVIEW tasks only (`integrated-full-tasks/`).
* The audit writes nothing into `tasks/` (0 `.pyc` after QUICK and FULL) and never touches the historical DB.

## 9. Cross-version evidence (historical ≠ current)

* **Snapshots use the current ORACLE version and digest** for all 18 remediated tasks (e.g. `sanitize-filename 1.0.2`,
  digest equal to the digest of its git-tracked files).
* **Historical rows keep their true version.** `sanitize-filename`: all 30 historical rows are `1.0.1`; current is `1.0.2`. The
  API's own signal (`meta.tasks[].evaluated_versions != [current_version]`) flags **exactly the 18 remediated tasks** and no
  others. A historical cell reads `task_versions ['1.0.1']` against `current_version '1.0.2'`; a new model's cell reads
  `['1.0.2']`; an exact historical run is still `task_version 1.0.1` after new evaluations.
* **Evaluation-scoped views contain only their own evidence.** A new evaluation's report/results contain none of the 30
  historical run ids and carry `1.0.2` in the snapshot, every trial, the raw run, `report.json` and `report.md`.
* **Aggregates keep the guard.** A model that already has old-version rows, re-evaluated on a bumped task, makes overview,
  leaderboard, meta, cell, domains and export return **503** with `refusing to pool multiple task versions:
  qwen3.5:9b/sanitize-filename: 1.0.1,1.0.2` and `healthz` `degraded`; `POST /reports/regenerate` → 409 (test); while
  `/jobs/*`, `report.json/md` and `/runs/{id}` keep working (verified live and in a test). **The guard was preserved, not
  weakened.**

## 10. Reuse safety

* Same snapshot → reuse allowed, `reused / provisional`, source and origin recorded, **zero new raw rows** (positive control).
* Source evaluation created at the **pre-remediation version** (`1.0.1`) → 409 `reuse source snapshot is incompatible`, no
  evaluation row, no raw evidence.
* Source at the **same version but a changed oracle** (a hidden-test byte differs) → 409 by digest alone — version equality is
  not enough.
* Nonexistent/legacy source → 409 `unavailable or legacy`; all 720 historical runs have `job_id IS NULL` and can never be sourced.
* No evidence laundering across benchmark versions is possible.

## 11. Historical database safety

```
SHA-256(reports/runs.sqlite)
  master checkout                                   42b6dad85ee662d6d5d7f75ffbda5a3b95d50837837f81c875730a8987838ced
  isolated frozen-ATLAS tests (before / after)      42b6dad8…838ced / 42b6dad8…838ced
  ORACLE-only integration state                     42b6dad8…838ced
  post-merge test groups (all 11, after each)       42b6dad8…838ced
  final test groups (all 12, after each)            42b6dad8…838ced
  FULL audits (before / after)                      42b6dad8…838ced / 42b6dad8…838ced
  manual smoke test (before / after)                42b6dad8…838ced / 42b6dad8…838ced
  git blob at 1e1a788                               42b6dad8…838ced
```

Reading a WAL-mode DB read-only leaves gitignored `runs.sqlite-shm` / `-wal` sidecars; the main file is unchanged. The default
runtime DB `reports/app.sqlite` was never touched (mtime unchanged); the smoke test used an explicit scratch DB.

## 12. Pre-registered predictions (from the baseline) vs outcome

| # | Outcome |
|---|---|
| P1 textually clean merge, only `pipeline.py` shared | **Confirmed** (dry run and merge) |
| P2 `run_id` + `overlay_diff` + delegation coexist | **Confirmed** (diff of merged vs each side; test) |
| P3 all 493 ATLAS tests pass unchanged | **Confirmed** (identical group counts) |
| P4 61 ORACLE tests; audit 15/2/7/0 | **Confirmed** |
| P5 digest covers `integrity/**`; execution never reads it | **Confirmed**, plus a new finding: it also covered bytecode → §6.2 |
| P6 new evaluation snapshots current version/digest | **Confirmed** (18 tasks) |
| P7 historical rows keep old version, no stale flag | **Confirmed** (API + UI; see §13 L2) |
| P8 new model pooled next to old-version agents unmarked | **Confirmed** (a mock "model" ranked on the live leaderboard) |
| P9 same-name re-evaluation trips the global guard | **Confirmed live and in a test** |
| P10 incompatible reuse → 409, zero rows | **Confirmed** (3 variants) |
| P11 drift → refuse/block | **Confirmed at unit level** (`validate_snapshot_tasks` raises after an `integrity/` edit; HTTP 409 and blocked-trial paths are ATLAS's own passing tests) |
| P12 controls run via merged runner; mock ≡ overlay | **Confirmed** |
| P13 DB SHA identical at every stage | **Confirmed** |
| P14 manifest 18 / 540 / 51 | **Confirmed** (re-derived) |

## 13. Manual application smoke test

Real launcher: `AFA_DB_PATH=<scratch> AFA_PORT=8765 AFA_NO_BROWSER=1 python3 afa_app.py` from the main checkout (API + separate
worker + built SPA). The Chrome extension was **not connected**, so the SPA was driven with **headless Chromium via the repo's
own Playwright** (13 pages, text + screenshots + console/network capture). Backend: `mock` only (no live model server).
A first smoke run on the pre-fix code was discarded and repeated on the fixed code.

| Step | Observed |
|---|---|
| Start | seeded working DB from evidence into the explicit path; UI served (200); default `reports/app.sqlite` untouched |
| Unseen model | `smoke-unseen-060701`, 3 remediated tasks × 2, absent from the 6-model roster before |
| Progression | `queued → running 0/6 … → succeeded 6/6`, 6 passed, 0 voided |
| Snapshot | `sanitize-filename 1.0.2`, `toposort 1.0.2`, `validate-redirect-url 1.0.2`, digests equal to a pristine checkout's |
| Results / trials | 6 trials `fresh / comparable / complete`, runs 1221–1226 |
| Exact runs | `/runs/1221…` `found`, `@1.0.2`, `job_id` = the evaluation, patch + 17 test results |
| Reports | `report.json` schema 1, `limitations: []`; `report.md` shows the snapshot list with digests |
| Live discovery | model in overview/leaderboard/domains immediately, no restart |
| Restart | **`report.json`, `report.md`, `results` byte-identical** (sha256 in `evidence/smoke/api/SHA256SUMS.txt`); job JSON equal; runs 1221–1226 still inspectable; UI pages identical text; 0 console errors |
| Fresh again (B) | new runs 1227–1232, disjoint from A |
| Explicit reuse (C) | runs 1221–1226, `reused / provisional`, source = origin = A, `counters.reused 6`, no new raw evidence; **UI shows PASSED 0, VOIDED / REUSED 0 / 6 and ↺ markers, not ✓** |
| Guard (historical model, bumped task) | aggregates 503 with the explicit message; SPA shows a "Could not load this view … refusing to pool multiple task versions" card; evaluation pages still work |
| Empty campaign DB (no code change) | same model name evaluated twice on a bumped task → all aggregates 200 at a single version `1.0.2`; historical DB unchanged |

Looked for and **not found**: blank evidence panels, reused evidence shown as fresh, restamped historical versions, missing
evidence shown as complete, suppressed observed results, console errors, failed requests (13 pages × 2 runs = 0 / 0).
Looked for and **found** (presentation, not correctness): see L2/L3 below.

`POST /reports/regenerate` was deliberately **not** sent to the main checkout during the smoke test: it rewrites the tracked
`reports/leaderboard.html`. It is covered by ATLAS's own tests (200) and by mine (409 under the guard, output redirected).

## 14. Integrated diff review (master → `2ee57c8`)

377 files, +58,913 / −879. **Every file is attributed; there are no unexplained edits.**

| Category | Source | Files | + | − |
|---|---|---|---|---|
| runtime DB / canonical DB / projections (`db`, `main`, `projection`, `store_load`, `afa_app`) | ATLAS | 5 | 523 | 198 |
| evaluation lifecycle + identity + recovery (`jobs`, `worker`, `routes_jobs`, `schemas`) | ATLAS (+ integration fix in `jobs.py`: +15/−1) | 4 | 1395 | 406 |
| evaluation reporting / forensics / serialization | ATLAS | 4 | 708 | 164 |
| runner: raw persistence (`store.py`) / providers (`agents_ollama.py`) | ATLAS | 2 | 112 | 33 |
| runner: `pipeline.py` | ATLAS + ORACLE | 1 | 26 | 10 |
| runner: `__init__.py` exports, `diffing.py` (`pytest.py` protected), `pyproject.toml` (test paths), `examples/benchmark_audit.py` | ORACLE | 4 | 39 | 3 |
| ATLAS tests | ATLAS | 11 | 4486 | 22 |
| benchmark integrity engine: core + checks / mutation / tests + fixtures | ORACLE | 19 / 3 / 66 | 2685 / 706 / 1372 | 0 |
| benchmark controls (known-bad / mutants / alternatives / equivalences) | ORACLE | 157 | 3154 | 0 |
| hidden + regression tests (remediated grading) | ORACLE | 19 | 667 | 15 |
| task versions + contract clarifications (`task.json`) | ORACLE | 18 | 35 | 26 |
| integrity manifests + audit evidence | ORACLE | 44 | 39722 | 0 |
| documentation (`ORACLE.md`, `BENCHMARK_INTEGRITY.md`, `AUDIT_EVIDENCE_POLICY.md`) | ORACLE | 3 | 1078 | 0 |
| **integration-specific**: baseline + evidence | integration | 15 | 1543 | 0 |
| **integration-specific**: cross-system tests | integration | 1 | 646 | 0 |
| **integration-specific**: stale-pin test fix (`runner/tests/test_grader.py`) | integration (ORACLE defect) | 1 | 16 | 2 |

(As of `2ee57c8`; the final commit adds this report, `docs/integration/evidence/`, the integrated audit summary and an erratum
in the ORACLE journal — documentation/evidence only.) Not committed, pre-existing and untracked: `.freeflow/`,
`docs/PAPER.md`, `summary.md`.

## 15. Remaining limitations (none hidden)

**ORACLE (unchanged, visible):** 2 NEEDS_REVIEW and 7 PROVISIONAL tasks; hidden tests are readable by graded code during the
hidden-suite run (isolation UNVERIFIABLE, excluded from status); no hardcoding detector, and `expression-evaluator`'s `eval()`
route cannot be caught by a behavioural suite; the `_pytest` directory-name gap is inert today (allow-lists block root writes);
the other 15 remediated tasks got no patch-by-patch historical exploitation audit.

**Integration-level (new, from this work):**
* **L1 — global 503 on same-name re-evaluation.** By design (preserved), but it will hit the campaign: the first persisted
  new-version run for a model that already has old-version rows makes every aggregate view refuse. Mitigation tested with no
  code change: run the campaign in a **fresh, empty runtime DB**; a version-aware projection is the proper follow-up.
* **L2 — silent cross-agent pooling.** The guard is per-(agent, task): different agents on different versions of one task are
  pooled unmarked (a new model ranks beside old-version agents), and there is no API stale flag; the version lives only in
  `current_version` vs `task_versions`/`evaluated_versions`. **L3 — UI headline.** A historical cell reads "task version
  **1.0.2**" in its header while its evidence tile says `1.0.1` (rows are 1.0.1). Not blank, not restamped, but easy to misread.
* **L4 — digest residuals.** After fix 2, `integrity/` edits, `.DS_Store` and any other non-bytecode file still change the
  digest; that makes older evaluations refuse resume/reuse (fail-closed, spurious for grading). Recommendation: keep, or later
  narrow to runner-read subtrees with a digest-schema bump. The 24 `test_task_digest_is_a_function_of_committed_content_only`
  tests are **intentionally** checkout-sensitive to this: an untracked non-bytecode file under `tasks/<id>/` (e.g. a Finder
  `.DS_Store`) makes them fail on purpose — clean the checkout, do not weaken the test.
* **L5 — the mock backend is indistinguishable in `runs`.** Mock runs are stored under the model name and become "real models" in
  leaderboards; **never use the mock backend for campaign evidence.** Repeat evaluations of one model at one version double-count
  in aggregates.
* **L6 — the UI health header** says "Connecting" (not "degraded") when the guard trips; **L7 —** the Chrome extension was
  unavailable, so UI checks used headless Chromium, and only the mock backend was exercised (no live Ollama/OpenAI-compatible
  server).

**ATLAS (pre-existing, unchanged; full list in the baseline §14):** `migrate()` is not concurrency-safe (not observed in three
launcher starts, which is not proof); invalid `params_json` silently degrades to mock parameters; drift is not re-checked
during/after a trial; `runs.task_version` and the trial/snapshot copy are never cross-checked; `comparability` ignores version
currency; duplicate `(agent, task, idx)` rows are pooled; events are unfenced; infra failures persist as `completed / fresh`;
the evidence-DB guard lives only in `afa_api.db`; both Dockerfiles default `AFA_DB_PATH` to the evidence DB (compose overrides
it); liveness is same-host/same-`TMPDIR`; the canary asserts the SHA literal last. Also: `test_grade_ignores_stale_snapshot_bytecode`
briefly writes a `.pyc` into the committed `fix-list-dedup` fixture (removed in `finally`) — harmless since fix 2.

## 16. Implications for the (not yet started) re-evaluation

No re-evaluation was run. When it starts: (1) only after this branch is accepted and merged; (2) real backends only (L5);
(3) a fresh runtime DB per benchmark version, or a version-aware projection first (L1/L2); (4) start from a tree free of
non-bytecode junk under `tasks/` (L4); (5) the exact cells are in `integrity/pack-audit/remediation-manifest.json`
(18 tasks × 6 models × 5 reps = 540 runs; 51 prior-pass cells first); (6) use ATLAS evaluations so each trial carries
`task_version` + `task_digest`; never reuse across versions (it is refused).

## 17. Completion gate

| Gate | Status |
|---|---|
| ORACLE preserved (engine, controls, mutations, remediated hidden tests, versions, manifest, policy, visible limitations, explainable audit) | ✅ §5, §8 |
| ATLAS preserved (canonical DB, discovery, identities, fresh default, same-id resume, reuse, fencing, reports, providers, restart, canary) | ✅ §7 (493 ATLAS tests + canary), §13 |
| Current ORACLE version and digest captured by ATLAS evaluations | ✅ §9 (18 tasks; fix 2 makes the digest reproducible) |
| Old-version evidence never silently current | ✅ never restamped/pooled/reused, machine-distinguishable; ⚠ presentation gaps L2/L3 disclosed |
| Incompatible reuse fails | ✅ §10 |
| ORACLE tooling works through the merged runner | ✅ §7 |
| ATLAS reports describe ORACLE-versioned evaluations | ✅ §9, §13 |
| Historical DB byte-identical | ✅ §11 |

## 18. Reproduce

```bash
git checkout integration/phase0-benchmark-integrity
python3 -m pytest -q                                                    # 612 passed
python3 -m pytest -q tests/test_phase0_acceptance_canary.py -s          # receipt
PYTHONPATH=integrity:runner:kernel python3 -m afa_integrity audit --all --full --workers 4   # 15/2/7/0 (exit 1 = worst status NEEDS_REVIEW)
python3 docs/integration/evidence/audit/compare_audits.py <auditA> <auditB>                   # per-task identity check
shasum -a 256 reports/runs.sqlite                                       # 42b6dad8…838ced
```
