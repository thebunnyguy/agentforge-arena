# Pre-Integration ATLAS Baseline

> Recorded **before** any ATLAS content was merged into `integration/phase0-benchmark-integrity`.
> Purpose: after ORACLE and ATLAS are combined, any behavioural difference can be attributed to
> integration rather than guessed at. Nothing in this document describes the merged system.

## 1. Subject

| | |
|---|---|
| Branch | `codex/phase-0-evaluation-integrity` |
| Frozen HEAD | `1e1a788cadd5ed35fed9fe37d8e8ebbba922bf07` |
| Commits over master (`fd423ab`) | `9c77e6f` canonical DB binding + live target discovery; `f74918e` durable evaluation identity + trial recovery; `1e1a788` evaluation-scoped reports + acceptance canary |
| Observed as | an isolated detached `git worktree` at the frozen SHA (never the ATLAS branch itself; ATLAS was not modified) |
| Merge base with master and with ORACLE | `fd423ab` (master has not moved) |

**Method.** Not inferred from commit messages. (a) A full-suite test run on the frozen tree with the historical-DB hash
bracketed around it; (b) seven independent read-only auditors, one per subsystem plus a cross-cutting task-version
auditor, each reading the implementation and reporting `file:line` evidence; (c) a completeness critic that
spot-checked the auditors' claims against the code and corrected five of them; (d) my own direct reading of the
highest-stakes code (`_task_digest`, `create_job` reuse predicate, `pipeline.py`, the mixed-version guard, Docker env).
Full unedited auditor output: [`atlas-baseline-evidence/subsystem-audits.md`](atlas-baseline-evidence/subsystem-audits.md).
Test logs and canary receipt: [`atlas-baseline-evidence/test-run/`](atlas-baseline-evidence/test-run/).

## 2. What ATLAS changed relative to master

27 files, +7213 / −823.

| Subsystem | Files |
|---|---|
| Runtime DB / migration / projection | `afa_api/db.py` (+392), `afa_api/main.py`, `afa_app.py`, `afa_api/projection.py` (new), `afa_api/store_load.py`, `afa_api/routes_readonly.py`, `afa_api/serialize.py`, `afa_api/schemas.py` |
| Evaluation lifecycle / identity / recovery | `afa_api/jobs.py` (rewritten, ~970 lines changed), `afa_api/routes_jobs.py`, `afa_api/worker.py` (~540 lines changed) |
| Evaluation reporting | `afa_api/evaluation_report.py` (new, 450), `examples/report_combined.py` |
| Runner / raw persistence / provider | `runner/afa_runner/store.py` (+135), `runner/afa_runner/pipeline.py` (+3: `RunRecord.run_id`), `runner/afa_runner/agents_ollama.py` (+10: `set_run_seed`) |
| Tests | `tests/test_evaluation_identity.py`, `test_evaluation_reports.py`, `test_phase0_live_projection.py`, `test_phase0_acceptance_canary.py`, `test_a2_boundaries.py`, `test_a3_boundaries.py`, `test_jobs_api.py`, `afa_api/tests/test_jobs.py`, `runner/tests/test_store.py`, `runner/tests/test_report_combined.py`, `runner/tests/test_agents_openai.py` |

No `web/` files, no task files, no `reports/runs.sqlite` change.

## 3. Architecture summary

* **Two DBs, never confused.** `reports/runs.sqlite` (`db.EVIDENCE_DB_PATH`) is committed immutable evidence and is
  *never* a default or a writable target. The writable **runtime DB** is chosen by `resolve_db_path`
  (`afa_api/db.py:39-50`): explicit `app.state.db_path` / worker argument → `AFA_DB_PATH` → `reports/app.sqlite`.
* **Seeding.** `ensure_working_db` (`db.py:198-247`) copies evidence into a runtime DB using the SQLite **backup API**
  from a `mode=ro` handle into a `mkstemp` file, then publishes it with a no-clobber `os.link`. It never re-seeds an
  existing target.
* **Live projections.** Overview / leaderboard / cell / domains / meta / export are rebuilt **per request** from the bound
  DB (`projection.open_projection`, `store_load.load_stores`), with no cache and no hard-coded roster. The model roster is
  `SELECT DISTINCT agent FROM runs`. A brand-new model appears without restart.
* **Control plane.** `evaluation_jobs` → `evaluation_trials` → raw `runs`, driven by a per-evaluation worker thread
  (`afa_api/worker.py`) fenced by an OS `flock` plus DB owner/claim tokens.
* **Reporting.** `GET /jobs/{id}/report.json|report.md` are built strictly from the evaluation's own persisted trials.

## 4. Schema and migration summary

* `db.migrate` (`db.py:391-453`) is **additive and idempotent when run sequentially**: `CREATE IF NOT EXISTS`, nine guarded
  `ALTER TABLE evaluation_jobs ADD COLUMN`, a guarded `ALTER TABLE runs ADD COLUMN job_id`, and an `INSERT OR IGNORE` settings
  row. There is no schema-version counter; shape is detected with `PRAGMA table_info` / `index_list`.
* It **fails closed** (`RuntimeError` → `migrate_error` → HTTP 503 on control-plane routes, raw reads still work) on missing
  required columns or non-unconditional identity keys. Master's destructive drop-and-recreate is gone.
* The committed evidence DB already contains *old-shape, empty* `evaluation_jobs`/`job_events`/`app_settings`, so **every**
  seeded copy takes the ALTER path.
* **Not concurrency-safe.** `migrate` is check-then-ALTER with no lock; a forced 4-way concurrent run produced 77 of 160
  `duplicate column name` errors. `afa_app.py` starts the worker before uvicorn and both migrate the same seeded DB, so the
  overlap is real in principle (not observed in `afa_app.py` itself).
* Tables (identity-relevant): `evaluation_jobs(id, status, cancel_requested, params_json, counters…, mode, source_evaluation_id,
  snapshot_json, owner_token, owner_started_at)`, `evaluation_trials PK(evaluation_id, task_id, idx)` with
  `task_version NOT NULL`, `task_digest NOT NULL`, `trial_state`, `evidence_state`, `run_id`, `source_evaluation_id`,
  `source_run_id`, `origin_evaluation_id`; `job_runs PK(job_id, run_id)`; `job_events UNIQUE(job_id, seq)`; `runs.job_id`
  (nullable, added). `runs` has **no** uniqueness on `(agent, task_id, idx)` and **no** provider/backend column.
* Historical DB facts (verified on a copy): 720 runs = 6 agents × 120 over 24 tasks; task versions `1.0.0`×120 (4 tasks),
  `1.0.1`×510 (17 tasks), `1.0.2`×90 (3 tasks); 0 evaluation_jobs, 0 job_runs, 0 runs with `job_id`; header is **WAL** (bytes
  18–19 = `02 02`).

## 5. Evaluation identity model

```
evaluation_jobs.id  (uuid4 hex — one explicit evaluation request)
        └── evaluation_trials (evaluation_id, task_id, idx)   — one requested position
                └── runs.id                                    — one persisted raw execution
```

Three distinct identities. The legacy `(agent, task_id, idx)` tuple is retained only for the old lookup route; it is
**not** an identity (duplicates are accepted by design). `runs.agent` is the model-name string.

**Snapshot** (`jobs.build_snapshot`, immutable, stored as `snapshot_json` at creation): `model`, `backend{kind, base_url}`,
`generation{base_seed, temperature, request_timeout_s, seed_provenance, timeout_provenance}`, `tasks[{task_id,
task_version, task_digest}]`, `repeats`.

* `task_version` = `str(tasks/<id>/task.json["version"])`, read strictly; `id` must equal the directory name.
* `task_digest` = `"sha256:" + sha256` over **sorted relative paths + raw bytes of every regular file under `tasks/<id>/`**
  (`jobs.py:185-194`, `rglob("*")`, **no exclusion list**; verified by direct reading).

## 6. Fresh / resume / reuse semantics

| Mode | Behaviour (verified in code and tests) |
|---|---|
| **fresh** (default) | New `uuid4` evaluation, all trials inserted `pending / missing`. Nothing consults prior runs, so an identical request re-executes and yields new, disjoint raw run ids (canary A vs B: `[1221,1222]` vs `[1223,1224]`). |
| **resume** | Same evaluation id. `resume_job` first calls `validate_snapshot_tasks` (409 on drift), then reopens only `blocked` trials. In the worker a `completed` trial keeps its original `run_id` and is skipped (`run_skipped` event, agent never invoked); only pending positions execute (canary: `resumed_attempts == [{idx:1, seed:1001}]`). |
| **reuse** | Opt-in (`mode="reuse"` + `source_evaluation_id`). Requires a non-legacy source evaluation with a stored snapshot. Compatibility predicate is exact equality of `_snapshot_identity` = `{model, backend, generation, tasks (ordered, incl. task_version and task_digest), repeats}` between the source's **stored** snapshot and a snapshot **recomputed from current disk** (`jobs.py:288-295, 323`). Every source trial must be `completed`, `fresh`/`reused`, with a run that has `job_id`, a patch and ≥1 test result, and a non-legacy origin. No new raw rows are created; trials carry `evidence_state='reused'`, `source_evaluation_id`, `source_run_id`, `origin_evaluation_id` (origin preserved across chains), and report `comparability='provisional'`. Refusal is atomic (409). |

Legacy (pre-ATLAS) runs have `job_id NULL`, belong to no evaluation and can **never** be reuse sources.
`runs.task_version` is **not** compared during reuse (only the trial/snapshot copy is).

## 7. Persistence and transaction model

* One raw run, its `run_scores` / `diffs` / `test_results`, the `job_runs` link and the trial completion commit in **one
  transaction** on a borrowed connection (`save_run(commit=False)` issues an explicit `BEGIN` + `SAVEPOINT`;
  `complete_trial` is guarded by `trial_state='claimed' AND claim_token AND EXISTS(job running AND owner_token)` and raises
  `TrialClaimError` if `rowcount != 1`). Injected failures roll everything back and release the claim. The fence is evaluated
  after the first raw INSERT holds the write lock, so it is atomic.
* `job_events` are **not** transactional with evidence: `run_diff/run_graded/run_scored` are committed *before* the raw save
  and `append_event` is unfenced (`MAX(seq)+1` then INSERT). Events are a projection, not proof; `evaluation_trials` is truth.
* `RunRecord.run_id: int | None = None` is populated on load, `None` before save. It was inserted **before**
  `grade_report` (`pipeline.py`), a positional-binding hazard for a 12th positional argument. No in-repo caller does this.

## 8. Recovery and concurrency model

* Ownership: `owner_token` on the job, `claim_token` per trial, an OS `fcntl.flock` per evaluation under
  `tempfile.gettempdir()/agentforge-arena-evaluation-locks/…` plus an in-process set. A live owner (lock held) is never
  reclaimed even with an aged lease.
* Startup / `serve` call `reclaim_stale_running(recover_unlocked=True)`: an owner whose lock is free (process died) is
  requeued, its `claimed` trials return to `pending`, and the lifespan re-dispatches it. A stale owner's `complete_trial` and
  `mark_terminal` are rejected (fencing). `resume_job` does **not** pass `recover_unlocked`, so an explicit resume of a
  dead-owner job is refused until the lease ages (≥300 s or timeout+60).
* Cancel is a flag honoured at the next trial boundary; auto-recovery of an interrupted job with `cancel_requested=1`
  terminalizes it as `canceled` without executing anything.
* Duplicate prevention: `evaluation_trials` PK, claim guards, `UNIQUE(job_id, seq)`.
* Known gaps: liveness is same-host / same-`TMPDIR` only; `append_event` is unfenced; any single-trial exception fails the whole
  evaluation; infra failures persist as `completed / fresh` and the job ends `succeeded`.

## 9. Reporting model

* `GET /api/v1/runs/{run_id}` — exact forensic identity (bypasses the projection, so it works while aggregates refuse).
* Legacy `GET /api/v1/run/{model}/{task}/{idx}` — returns **409 `ambiguous` + `candidate_run_ids`** when more than one row
  matches (never silently picks one), except that a mixed-version refusal (503) pre-empts it.
* `GET /api/v1/jobs/{id}/results` and `/trials` — evaluation-scoped trial projections.
* `GET /api/v1/jobs/{id}/report.json` (versioned schema) and `report.md` — deterministic, built from persisted
  evidence via read-only connections, byte-identical after an app re-creation. They carry evaluation identity, model,
  backend, generation parameters, `task_snapshots` (id/version/digest), counters, per-trial `run_id`, outcome,
  `evidence_state`, reuse provenance, `artifact_state`, `comparability` and a limitations section. Missing artifacts are
  reported explicitly, not defaulted.
* **Comparability** = `comparable` (fresh + patch + test results), `provisional` (reused), omitted otherwise. It ignores
  version currency and minimum repetitions; there is no `official` state. Nothing hides observed results.
* Reports and trials trust `evaluation_trials`/`snapshot_json`; they never consult `runs.task_version` or the current on-disk
  version. A report stays `comparable` at its original version forever.

## 10. Provider model

* `backend.kind ∈ {mock, ollama, openai_compat}` (closed set in `schemas.py`, `evaluation_report.py`, `worker.factory_for`).
* `mock` overlays the task's `reference/` files (perfect score), labelled `agent=<model>` in `runs`; `ollama` uses the
  Ollama agent; `openai_compat` uses `OpenAICompatAgent`, which POSTs `{base_url}/v1/chat/completions` (no Authorization
  header). On master `factory_for` sent **both** `ollama` and `openai_compat` to the Ollama factory; ATLAS fixes that, and
  `agents_openai.py` itself is unchanged vs master (`agents_ollama.py` only gains `set_run_seed`).
* Provenance is "requested" only: the seed is ignored by Ollama, and `runs` has no provider column, so mock and real runs are
  indistinguishable in raw rows. Every HTTP error (an `HTTPError` is a `URLError`) is voided as `INFRA_FAILURE`.
  `openai_compat` base URLs must not include `/v1`.

## 11. Tests executed on the frozen ATLAS tree (isolated worktree)

Command form: `python3 -m pytest -p no:cacheprovider -ra <files>` from the worktree root. Sequential groups.

| # | Group | Files | Result | Time |
|---|---|---|---|---|
| 01 | evaluation identity | `tests/test_evaluation_identity.py` | **14 passed** | 16.1 s |
| 02 | jobs / API | `tests/test_jobs_api.py` (11) + `afa_api/tests/test_jobs.py` (13) | **24 passed** | 32.0 s |
| 03 | reports | `tests/test_evaluation_reports.py` (8) + `runner/tests/test_report_combined.py` | **12 passed** | 16.3 s |
| 04 | live projection | `tests/test_phase0_live_projection.py` | **8 passed** | 2.7 s |
| 05 | store / persistence | `runner/tests/test_store.py` | **15 passed** | 0.2 s |
| 06 | providers | `runner/tests/test_agents_openai.py` + `test_agents_ollama.py` | **18 passed** | 0.3 s |
| 07 | boundaries A2 | `tests/test_a2_boundaries.py` | **14 passed** | 7.9 s |
| 08 | boundaries A3 | `tests/test_a3_boundaries.py` (22 defs, 34 with parametrization) | **34 passed** | 36.0 s |
| 09 | Phase-0 canary | `tests/test_phase0_acceptance_canary.py` | **1 passed** | 9.2 s |
| 10 | **FULL suite** | `kernel/tests runner/tests afa_api/tests tests` | **493 passed, 0 failed, 0 skipped, 1 warning** | 363.5 s (6:03) |

The single warning is Starlette's `httpx`-TestClient deprecation. No `skip`/`xfail` markers and no `conftest` exist in the ATLAS tests.

## 12. Phase-0 acceptance canary — receipt (frozen ATLAS)

Captured with `pytest -s`; full JSON in `atlas-baseline-evidence/test-run/canary-receipt.json`.

| Stage | Observed |
|---|---|
| A fresh (`fa53718f…`) | raw runs `[1221, 1222]` |
| B fresh, same request (`769c6ab5…`) | raw runs `[1223, 1224]` — **disjoint** from A |
| C explicit reuse of A (`11300b14…`) | raw runs `[1221, 1222]` — the same rows, **no new raw evidence** |
| D interrupted then resumed (`f661c99b…`) | `interrupted_attempts` idx 0 then idx 1 (raised); after recovery/resume `resumed_attempts == [{idx:1, seed:1001}]`; raw runs `[1225, 1226]`, both on D |
| Restart / regeneration | `restart_native_matches`, `restart_result_matches`, `restart_report_matches` all `true` for every run and evaluation |
| Threads | 1 intentional interruption, 0 unexpected thread errors |
| Historical DB | `historical_before == historical_after == 42b6dad8…838ced` |

What is real in the canary: a sqlite copy of the evidence DB, the real FastAPI app on an in-process ASGI `TestClient` (no
socket), real dispatch threads, a real `fcntl` owner lock, real subprocess grading. What is faked: the mock agent, the
interruption (a `BaseException` from `act()`), and "restart" (`create_app()` + a new `TestClient` in the same process).
Real SIGKILL/process tests live in `test_a3_boundaries.py`. The canary task is hard-coded `fix-binary-search`
(version and digest are read dynamically from the report, not hard-coded).

## 13. Historical database SHA-256

```
before ATLAS-only tests : 42b6dad85ee662d6d5d7f75ffbda5a3b95d50837837f81c875730a8987838ced
after  ATLAS-only tests : 42b6dad85ee662d6d5d7f75ffbda5a3b95d50837837f81c875730a8987838ced   (identical)
git blob at 1e1a788     : 42b6dad85ee662d6d5d7f75ffbda5a3b95d50837837f81c875730a8987838ced
main checkout (master)  : 42b6dad85ee662d6d5d7f75ffbda5a3b95d50837837f81c875730a8987838ced
```

The hash was computed independently, not assumed. Reading the WAL-mode evidence DB read-only creates gitignored
`runs.sqlite-shm` / `-wal` sidecars; the main file is unchanged. The frozen worktree had no tracked modifications after the run.

## 14. Known limitations of ATLAS on its own

**High**
1. `migrate()` is not concurrency-safe (check-then-ALTER, no lock).
2. The mixed-version guard is **global and per-(agent, task)**: one cell with two `task_version`s takes down overview,
   leaderboard, domains, cell, run, meta, export (503), `healthz` (200 `degraded`) and `POST /reports/regenerate` (409).
   Different agents on different versions of the same task are pooled **silently**.
3. Worker execution reads `params_json`, not the snapshot; invalid `params_json` silently falls back to `JobParams()`
   (mock backend, model `mock`) and would persist perfect-score "fresh" evidence under a snapshot claiming another model.
   No test covers this.

**Medium**
4. `_task_digest` has no exclusion list (`__pycache__`, `.DS_Store`, caches, anything added to the task dir change it).
5. Drift is checked at creation/resume/before each non-completed trial, not during or after a trial (small TOCTOU window).
6. `runs.task_version`, `evaluation_trials.task_version` and `snapshot_json` are independent copies that are never cross-checked.
7. `comparability` ignores version currency; `provisional` (reuse) is unrelated to the kernel's `provisional` (n < 5).
8. `run_scores` PK is `(run_id, formula_version)` but forensic/trial lookups do not filter on it (arbitrary pick if two rows).
9. Duplicate `(agent, task, idx)` rows (repeat evaluations at the same version) are pooled and double-count in aggregates.
10. `job_events` are unfenced and can describe a run that was never persisted.
11. Infra failures persist as `completed / fresh`; jobs end `succeeded`; every HTTP error is voided as infra.
12. The evidence-DB guard lives only at `afa_api.db`; offline tools (`examples/eval_persist.py`) can write `runs.sqlite`.
13. `main.py` calls `ensure_working_db` outside its try/except, so an evidence-bound `AFA_DB_PATH` aborts startup; both
    Dockerfiles bake `AFA_DB_PATH=/app/reports/runs.sqlite` (docker-compose overrides it to `app.sqlite`).
14. Liveness uses a same-host `flock` under `TMPDIR`; multi-host or multi-`TMPDIR` deployments can double-run a trial (fencing
    still prevents a loser from publishing).
15. Provenance is thin (`requested` only; no served-model digest; no provider column on `runs`).

**Low / informational.** Stale docstrings (`db.py` says the runner is untouched and the DB is `journal_mode=delete`; the
evidence DB is WAL); `_completed_indices` is dead code; cancel during the last trial cancels a fully-completed job;
Markdown output is unescaped; `RunStore` Protocol was not updated for `commit`/`job_id`; `SqliteRunStore(path)` never adds
`runs.job_id` to an older DB; `/runs/{id}` returns 404 (not "partial") for a run lacking a score or diff row.

## 15. Suspicious behaviour and assumptions requiring integration attention

Corrections from the critic (claims the auditors got wrong or overstated, now fixed here): (i) the mixed-version guard is
**not** the only version mechanism — a duplicate guard lives in `examples/report_combined.py:159-169` and the evaluation side
enforces version+digest on snapshots; (ii) an evidence-bound `AFA_DB_PATH` **aborts app start-up**, it does not degrade to 503;
(iii) UNVERIFIABLE has **no distinct job status** — drift yields `trial_state='blocked'` + `evidence_state='unverifiable'`
per task and the job ends `failed`; (iv) the canary's SHA literal is asserted *after* every behavioural assertion, so a benign
rebuild of `runs.sqlite` fails only the literal; (v) seed provenance is `verified` on the snapshot side but only ever
"requested".

### Pre-registered predictions for the merge (checked in `docs/integration/PHASE0_INTEGRATION_REPORT.md`)

| # | Prediction if the merge is faithful | Basis |
|---|---|---|
| P1 | `git merge` of ATLAS onto the ORACLE tree is **textually clean**; `pipeline.py` auto-merges (disjoint hunks: `run_id` near L43, `overlay_diff` near L310); no other file is touched by both | file lists of both branches |
| P2 | Merged `pipeline.py` has `RunRecord.run_id` (before `grade_report`), `overlay_diff`, and `_reference_diff` delegating to it; ORACLE never constructs `RunRecord` positionally | grep of both trees |
| P3 | All **493** ATLAS tests still pass unchanged: the hard-coded literals (`fix-binary-search @ 1.0.0`, 24 tasks, 720 runs, the DB SHA) stay valid because ORACLE did **not** bump `fix-binary-search` and did not touch `runs.sqlite` | canary auditor's fragility list |
| P4 | All **61** ORACLE integrity tests still pass; the FULL audit still reads 15/2/7/0 | ORACLE-only integration check (done) |
| P5 | Task digests now include `tasks/*/integrity/**` (157 tracked files) and change when any of them, `task.json`, or any grading file changes; execution and grading never read `integrity/` | `_task_digest` + runner/grader read paths |
| P6 | A new evaluation of a bumped task snapshots the **current** version/digest (e.g. `sanitize-filename` 1.0.2), never the historical one | `task_snapshot` reads `task.json` |
| P7 | Historical rows keep their true `runs.task_version` (1.0.1); the cell payload shows `current_version 1.0.2` vs `task_versions ['1.0.1']` with **no stale flag**; evaluation reports contain none of them | `store_load`, `serialize`, `evaluation_report` |
| P8 | A **new** model name evaluated on a bumped task: 200 everywhere, but ranked next to old-version agents with no marking | guard is per (agent, task) |
| P9 | An **existing historical** model name evaluated on a bumped task → aggregate routes 503 as soon as the first run persists; `/runs/{id}`, `/jobs/*`, `report.json/md` keep working; `POST /reports/regenerate` → 409 | `store_load.py:168-178` |
| P10 | Reuse where source `task_version`/`task_digest` ≠ current → 409 `reuse source snapshot is incompatible`, zero new rows; reuse of a legacy/absent evaluation → 409 `unavailable or legacy` | `create_job` |
| P11 | Resume after a task file/version change → 409 drift; worker marks the trial `blocked`/`unverifiable` | `validate_snapshot_tasks`, `_load_snapshot_task` |
| P12 | ORACLE controls run through the merged runner; a mock evaluation of a remediated task still scores 1.0 (mock overlay ≡ `overlay_diff` on `reference/`) | ATLAS mock factory vs ORACLE overlay |
| P13 | `reports/runs.sqlite` SHA is byte-identical at every stage | design |
| P14 | The remediation manifest still reads 18 tasks / 540 runs / 51 prior-pass cells (18 × 30 = 540 rows in the untouched historical DB) | manifest + DB |

Design decisions taken up front (so they cannot be rationalised after the fact): scoring math is not touched; the
fail-closed global 503 is **preserved** (not weakened) even though it will bite the re-evaluation campaign; the digest's
over-inclusiveness is documented, not "fixed", unless it is shown to cause a concrete integration defect.
