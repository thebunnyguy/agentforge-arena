# Phase-0 Release Hardening — the current-benchmark contract

> Purpose: make the integrated ORACLE + ATLAS system safe to use as the execution environment for a fresh real-model
> benchmark campaign, **without** changing the benchmark itself (scoring math, tasks, hidden suites, mutation engine,
> controls) and **without** running that campaign.
>
> Read §12 (campaign operator notes) and §13 (verdict) before starting a campaign.

## 1. Subject

| | |
|---|---|
| Frozen source | `integration/phase0-benchmark-integrity @ af040b750df188a961eb084f1c0b99d262ba272a` (runtime code state `2ee57c8`, beneath doc/evidence commits) |
| Release branch | `release/phase0-current-benchmark`, created from exactly that commit. The source branch, `master`, the ORACLE branch and the ATLAS branch were never modified |
| Immutable evidence DB | `reports/runs.sqlite`, sha256 `42b6dad85ee662d6d5d7f75ffbda5a3b95d50837837f81c875730a8987838ced`. 720 runs = 6 models × 24 tasks × 5 repeats, all *legacy*: `job_id` NULL and — the committed file predates provenance, it has **no** `backend_kind` column at all (the column exists only in a migrated working copy, where every historical row is NULL). Only 6 of the 24 tasks are still at the version those runs were made at, so **180 runs are CURRENT and 540 HISTORICAL**; 18 tasks were version-bumped by ORACLE remediation |
| Not changed | `kernel/` (scoring math), `tasks/`, hidden suites, the ORACLE mutation/control engine (`integrity/`), benchmark definitions |
| Changed outside `afa_api/`, `web/`, `tests/` | `runner/afa_runner/store.py` (additive `runs.backend_kind`, `save_run(backend_kind=)`, score-formula pin, read snapshot, row-naming errors), `runner/afa_runner/report_html.py` (one label), `examples/report_combined.py` (current-only, scope-aware report), `examples/eval_persist.py`, `runner/tests/test_report_combined.py` |

Everything below was verified against the committed evidence DB (only ever copied) and, for the UI, a real built app
serving a seeded scratch copy.

## 2. Vocabulary (the contract every surface follows)

**Task version.** `tasks/<id>/task.json → version` is the *current version* of a task (the manifest has no `version`
key for any task today; a manifest `version` would override it — see §11).

| Term | Definition |
|---|---|
| **CURRENT run** | `runs.task_version == current version of runs.task_id` |
| **HISTORICAL run** | any other row — an older version, a newer-than-known or unknown version, or a task outside the pack. Preserved byte-for-byte, queryable, **never pooled with current rows, never restamped, never deleted** |
| **CURRENT benchmark evidence** | the CURRENT runs in the selected evidence scope. This is what every default aggregate uses |
| **MISSING CURRENT** | a model (or agent × task cell) that has historical evidence but **no current-version evidence**. It is listed, labelled `MISSING CURRENT`, has `state: historical_only`, is **never ranked** and never described as having completed the current benchmark |
| **Evidence class** | provenance of the *producer*: `real` (ollama / openai_compat), `synthetic` (mock), `legacy` (no provider recorded and no evaluation: the 720 committed rows — and, by construction, **any** later job-less write that omits `backend_kind`), `conflict` (provenance cannot be established consistently) |
| **Evidence scope** | `?evidence=benchmark` (default: real + legacy), `real`, `synthetic`, `all`; anything else is HTTP 400 |

Three questions are answered separately and never conflated: *which version* the evidence is at, whether that version is
*current*, and *who produced it*. "Never hidden" is a statement about **versions**: a scope deliberately filters by
producer (e.g. `?evidence=real` hides every legacy row; the runs are then counted in `excluded.out_of_scope_runs`, and
a model with only legacy evidence disappears from that scope's model list rather than being listed as MISSING CURRENT).

## 3. Area 1 — version-aware projections

### Previous behaviour and risk
Every projection fed *all* persisted rows into the kernel's in-memory store, which is version-blind and keyed by
`(agent, task)`. The frozen source guarded this in the API layer (`afa_api/store_load.load_stores` and
`examples/report_combined.py`, never in `kernel/`) with `refusing to pool multiple task versions`. Consequences:

* the moment a run at a task's *current* version was persisted next to a historical row of the same `(agent, task)` —
  exactly what the first real-model campaign does for 18 of 24 tasks — **every aggregate route answered 503 and report
  regeneration 409** (reproduced on the frozen source: overview / leaderboard / meta / cell / domains / export / run
  all 503 after one such run);
* the alternative, silently removing that guard, would have pooled 1.0.1 and 1.0.2 evidence into one pass rate — the
  most damaging possible error for a benchmark, because the tasks were bumped precisely because the old evidence was
  invalid for the new definition;
* a model with only historical evidence would have appeared to have "completed" the benchmark.

### Design
Filter **before** the kernel, never inside it. `afa_api/store_load.load_stores` reads runs and their provenance in one
read snapshot, classifies each run (current/historical × evidence class), and builds:

* a `real` store containing only CURRENT, in-scope runs — what every default aggregate uses;
* a `full` store = the `real` store plus the synthetic oracle/noop bookends (report_combined parity);
* per-run records (`LoadedStores.runs`, in-scope runs of any version) and the versions *stored* per cell/task across all
  classes (`stored_cell_versions`, `stored_task_versions`) for history and forensics.

Kernel math is untouched. Per-version history (`?version=`) is computed with a throwaway `scratch_store` that refuses to
hold more than one version of a task, so the mixed-version `ValueError` is retained as a *structural invariant* that
stored data can no longer trigger. No global 503/409 remains for version coexistence.

### Alternatives rejected
* **Remove the guard / pool versions** — invalidates the benchmark (above).
* **Restamp or delete historical rows, or backfill a version column** — destroys audited evidence; the evidence DB is immutable.
* **Refuse to serve until historical rows are archived** — makes the product unusable exactly when the campaign starts.
* **Filter in SQL only** — would leave the kernel store able to receive mixed versions from any other code path.

### Implementation (API surface)
`overview`, `leaderboard`, `domains/{agent}`, `cell/{agent}/{task}`, `meta`, `export` and `reports/regenerate` answer over
CURRENT evidence in the selected scope. `/runs/{id}` (exact raw lookup: any version, any class, no scope parameter) and
`/run/{agent}/{task}/{idx}` (forensic: resolves within one version, never class-filtered) label each run with its
`version_status` / `evidence_class`. Key payload decisions:

* `real_counts` keeps its exact legacy shape `{n_runs, n_tasks}` but counts CURRENT in-scope runs; every roster model is
  present (0/0 if historical-only). The breakdown lives in `evidence_counts`, `current_benchmark`, `excluded`.
* Only models with current rows get a leaderboard entry; the rest are in `historical_only_models`. Entries carry
  `coverage {tasks_with_current_evidence, tasks_total, complete}`. **Ranks compare pooled pass rates over whatever tasks
  each model has evidence for**; they are not comparable across models until every ranked model has `coverage.complete`.
* Domain aggregates are current-only.
* Cell state is `captured | historical_only | not_captured | synthetic`, about *current* evidence and independent of
  `?version=`; `?version=<old>` returns that version's runs and aggregate labelled `evidence_status: historical`.
  `cell.task_versions` and `meta.evaluated_versions` report versions *stored* across all classes.
* `excluded {synthetic_runs, synthetic_models, provenance_conflict_runs, out_of_scope_runs, unaccounted_runs}` accounts
  for every raw run: in-scope current + in-scope historical + those five counters = the raw row count in **every**
  scope (a per-cell view carries `synthetic_runs`, `provenance_conflict_runs` and `out_of_scope_runs`). `unaccounted_runs` are rows with no
  `run_scores` row of the pinned formula or no `diffs` row: counted, never aggregated, not reachable through `/runs/{id}`.
* The tuple route returns 409 with `candidates` when still ambiguous; UI links use the exact `/runs/{run_id}`.

### Tests
`tests/test_phase0_release_hardening.py` §A–E; `tests/test_phase0_campaign_readiness.py` (§10.4); the rewritten
`test_reevaluating_a_historical_model_on_a_bumped_task_no_longer_collapses_the_projections` in
`tests/test_integration_oracle_atlas.py`; the real-data gate (§10.3).

### Limitations
Currency is decided by the version **string** only (exact equality). Task *content* drift at an unchanged version is not
detected at projection time (it is caught at evaluation time by the task digest snapshot). In the default scope a fresh
real run for a model that already has legacy runs at a still-current task pools with them (§11, §12).

## 4. Area 2 — UI semantics

Every place that shows evidence states, separately: **Evidence version**, **Current task version**,
**Status `CURRENT` | `HISTORICAL`**, and for a cell with no current evidence: `Current benchmark evidence: NONE` /
`Historical evidence: AVAILABLE (versions …; N runs)` with a version selector. Overview, leaderboard, agents, domain
matrix, agent profile, cell, task and runs pages are labelled *current benchmark evidence*, show coverage
(`8/24 tasks with current evidence`) and carry an evidence-scope selector (the Reports page does not: its
*Regenerate* and *Export JSON* always use the default benchmark scope; other scopes are API-only). A historical-only model
appears as `MISSING CURRENT … not ranked`. Mock evaluations are labelled
`SYNTHETIC · mock — excluded from benchmark results`. Jobs whose persisted parameters cannot be verified render as
`Evaluation parameters unavailable` (never dereferencing null params), with retry/resume disabled; the **UI** shows their
evidence class as *unknown* (the API still reports the class recorded in the creation snapshot).

32 files under `web/`. Verified by 58 Playwright cases (27 with the API mocked — job view, job events, validation,
version evidence including a check that no evaluation-card child clips or overlaps at 1440/1280/1100/900/390px — and 31
route/width cases in `routes.spec.ts` that run against a live app), the axe (serious/critical) checks inside them, and the
manual smoke in §10.6. The manual smoke found two real defects the automated suite missed (clipped card actions; an
unverifiable job asserting an evidence class) which were fixed and are now covered by a test.

## 5. Area 3 — fail-closed persisted parameters

### Previous behaviour and risk
The persisted `params_json` was projected by `_job_params_from_row`, which dropped unknown keys, coerced values, and on
*any* failure returned `JobParams()` — the schema defaults: **model `"mock"`, backend `mock`, no tasks, repeats 1,
temperature 0.6**. The worker executed `job.params` from that projection. A corrupt row (malformed JSON, non-object,
missing model, invalid backend kind, wrong-typed `repeats`) that was resumed or recovered at startup therefore ran as a
*default mock evaluation* — a different evaluation than the one recorded — and its runs were stored under agent `mock`
linked to the recorded job id (reproduced). Retry of a fully corrupt row failed (empty task list); retry of a partially
corrupt one (model dropped, tasks intact) cloned a mock job over the same tasks.

### Design
One verification, `jobs.verify_persisted_params`, used for **execution, recovery, retry, resume and listing alike**:

1. strict parse (`model_validate(strict=True)`): the seven top-level keys `model, backend, tasks, repeats, base_seed,
   temperature, request_timeout_s` must be present, unknown top-level keys are rejected, types are strict (no `"2"→2`),
   non-empty unique tasks, non-blank model, finite temperature, no credential-bearing backend URL;
2. agreement with the job row's own `mode` / `source_evaluation_id` columns;
3. agreement with the **creation snapshot** (model, backend kind/URL, seed, temperature, timeout, repeats, task list) — the
   real guard: a defaulted or coerced value can never diverge from what was recorded;
4. **only `InvalidPersistedParams` can escape** — non-list snapshot `tasks`, absurdly nested JSON (`RecursionError`),
   non-finite numbers (NaN, Infinity, `1e999`) and any other surprise become "unverifiable".

Effects: the worker builds no agent and calls no factory; the job goes `failed` with
`invalid persisted evaluation parameters: <field names only>` (values and attacker-chosen key names are never echoed);
non-completed trials become `blocked`/`unverifiable`; `resume_job`/`retry_job` return HTTP 409 before mutating anything;
startup recovery fails such a running job closed instead of requeueing it; listings keep working with
`params: null, params_status: "unverifiable", params_error`. A row whose control columns cannot form a job at all
(unknown status/mode literal, non-numeric counters) is listed as an explicit `failed`/`unverifiable` placeholder rather than
500ing the list. Evaluation reports state when parameters could not be verified. Job creation refuses a blank model, a
non-finite temperature, `repeats > 10 000`, `request_timeout_s > 86 400`, out-of-range seeds and task ids the filesystem
cannot stat up front; reuse is refused from a source whose own parameters do not verify; and a request-validation error
never echoes (or chokes on) the submitted value.

**Consequence worth knowing:** every job created before snapshots existed (`mode='legacy'`, e.g. old mock jobs in an
existing `reports/app.sqlite`) is listed as `unverifiable` by construction and can be neither resumed nor retried.

### Tests
`tests/test_phase0_release_hardening.py` §F (malformed JSON, wrong types, missing model, bad backend kind, malformed
backend, bad repeats, bad generation, credential-bearing backend, plus a valid control that *does* run) and §G (recovery
through the app lifespan and `reclaim_stale_running`): in every case **zero raw runs, zero fresh evidence, factory never
invoked**; `tests/test_phase0_redteam_params_migration.py`; `tests/test_phase0_hardening_round2.py` §1–3.

### Limitations
The guard trusts the injected agent factory (`app.state.agent_factory`) — a trusted-local extension point.

## 6. Area 4 — raw run provenance

### Design
Additive nullable column `runs.backend_kind TEXT CHECK (backend_kind IS NULL OR backend_kind IN ('mock','ollama','openai_compat'))`.
It is written from the backend the **factory declares** (`factory.backend_kind`; the three production factories declare
theirs), never from the merely *requested* kind: an undeclared factory stores NULL. Historical rows are never rewritten or
backfilled — NULL means *no provider recorded*, displayed as "LEGACY · unknown provider", never as Ollama.

Resolution for one run: a run persisted under a reserved baseline name → **conflict**; else its own `backend_kind`; else
its evaluation's snapshot backend kind; else the evaluation's `params_json` backend kind (master-era jobs); else a run
that names a job with nothing attestable → **conflict**; else (no job, no provider) → **legacy**. A run's own value
disagreeing with its evaluation's is a **conflict**, surfaced as `provenance: mismatch` in reports (comparability withheld)
and counted in `excluded.provenance_conflict_runs`, never resolved silently.

| Provider | `runs.backend_kind` | Class | Default (benchmark) ranking | `real` scope | `synthetic` scope | Inspectable |
|---|---|---|---|---|---|---|
| mock | `mock` | synthetic | **no** (excluded and counted) | no | yes | `?evidence=synthetic`, `/runs/{id}`, tuple route |
| ollama | `ollama` | real | yes | yes | no | yes |
| openai_compat | `openai_compat` | real | yes | yes | no | yes |
| legacy (no provider, no job) | NULL | legacy | yes | no | no | yes, labelled "unknown provider" |
| conflict (disagreement, unknown kind, unattestable job run) | any | conflict | **no** | no | no | `?evidence=all`, `/runs/{id}` |
| reserved baseline name | any | conflict | **no** | no | no | **`/runs/{id}` only** (never aggregated in any scope, not even `all`; cell/tuple routes serve the synthetic bookend) |

Names reserved for the two synthetic reference baselines (`oracle (synthetic baseline)`, `noop (synthetic baseline)`)
cannot be used as a model name: creation is rejected, and injected rows are conflicts.

### Tests
§H (raw provenance persisted per factory), §I (mock exclusion from default views, availability in synthetic/all,
forensic routes unfiltered), §J (snapshot ↔ raw run consistency), `tests/test_phase0_redteam_provenance.py`.

### Limitations
* Provenance attests the **configured backend kind**, not the model identity behind a URL: a real-kind factory pointed at
  a server that replays reference solutions is recorded as real. The system does not record a served-model digest.
* `legacy` is defined by shape (no provider, no job), not by the 720 committed rows: **any writer that omits both
  `job_id` and `backend_kind` (e.g. a bare `SqliteRunStore.save_run`) produces benchmark evidence**, including a mock run.
  The app worker and `examples/eval_persist.py` stamp provenance; other writers must.
* An injected agent factory that declares no backend is recorded NULL and classed from its evaluation's *requested*
  backend (`provider_source: evaluation`, `provenance: unknown`).

## 7. Area 5 — concurrent migration safety

### Previous behaviour and risk
`db.migrate` is called from the API startup (and its lazy retry), the worker (`claim_and_run`, `dispatch_job`, `serve`),
`jobs.create_job` and `examples/eval_persist.py`, from several threads and processes. On the frozen source it ran
check-then-`ALTER TABLE ADD COLUMN` in autocommit with no lock (`executescript` commits per statement). In an ad-hoc
stress harness (real threads and subprocesses, copies of the evidence DB; not committed) **168 of 800 concurrent
initialisers failed** with `duplicate column name` (the loser's `ALTER` after the winner's) and, for a delete-mode
file, `database is locked` raised from the `journal_mode=WAL` switch (SQLite skips the busy handler for that switch, so
moving `busy_timeout` earlier did not help). A failed startup migration was then remembered forever
(`app.state.migrate_error`), so **every read projection answered 503 until the process was restarted**.

### Design
* **Read-only fast path** (`_schema_is_current`): a handful of `SELECT`/`PRAGMA` reads, no lock, returns immediately when
  every table, index, column *name*, identity key and the settings row already exist. Any missing piece → slow path.
* **Serialised slow path**: `BEGIN IMMEDIATE`, then *re-inspect under the lock* (a loser finds the work done), run the
  additive migration, commit. Any failure `ROLLBACK`s (SQLite DDL is transactional) and re-raises — errors are **not
  swallowed**; a busy timeout surfaces as `sqlite3.OperationalError`. Re-inspection compares names, so it neither detects
  nor repairs a column whose *definition* drifted.
* WAL is enabled with a bounded retry; `executescript` implicitly commits, so scripts are split into statements and run
  inside the transaction.
* Historical rows are only ever read; `runs.job_id` / `runs.backend_kind` are added as NULLable columns without a rewrite.
* **Startup is two recorded steps** (`afa_api/startup.py`): migration (`app.state.migrate_error`; job/settings/regenerate
  routes answer 503 while set) and same-host recovery of orphaned `running` evaluations (`app.state.recovery_error`,
  surfaced by `/healthz` as `degraded`). Both are retried lazily — at most once per second, under a lock, **in a worker
  thread from the app middleware for every `/api/v1` request, never from projection code on the event loop** — so a
  transient lock at startup no longer pins the app until restart, and recovery that was skipped is performed after a
  successful retry.
* Recovery isolates rows: one bad orphan is failed closed (or, on an unexpected error, left `running` and reported) while
  the others are still recovered; what was requeued is still dispatched (`RecoveryIncomplete`); a dying dispatch thread
  fails its job instead of leaving it `running`; `resume_job` reclaims only its own evaluation.

### Tests
`tests/test_phase0_migration_concurrency.py` (44 tests): with n=8 initialisers, real threads and real subprocesses,
WAL and delete-mode copies of the evidence DB plus brand-new empty files, asserts 0 errors, complete schema, `integrity_check`
ok, historical rows byte-identical (checksums over the original columns), and a deterministic test that no rival can
interleave between the column check and the `ALTER` (mutation-tested: removing `BEGIN IMMEDIATE` fails it).
`tests/test_phase0_hardening_round2.py` covers the retry, recovery isolation and evidence-DB alias refusal (`..`, `.`,
symlink, hard link and case-variant spellings). A 10-process matrix over master-era / ATLAS-era / committed-evidence
copies was run ad hoc during review (0 errors) but is not a repo test.

## 8. Adversarial review and dispositions

Three independent rounds attacked the result after implementation (a test author per area; a red team; then code reviewers,
black-box attackers and a fact-checker of this document), always against *copies* of the evidence DB.

**Attacks that failed** (worth stating): no version-string variant (whitespace, leading zero, `v` prefix, extra component,
`-rc1`, newer-than-current), task-id case variant or out-of-manifest task entered a current aggregate; mixed-version
pooling was structurally impossible across 266 randomised rows × 12 provenance combinations × 4 scopes; 40+ corrupt
`params_json` variants never executed; symlink, hard-link, upper-case and `..` aliases of the evidence DB were refused; the
tracked `reports/leaderboard.html` was never modified by a non-default scope; the evidence DB hash never changed.

Round 1 (red team, F1–F19), fixed unless noted:

| # | Sev | Finding | Disposition |
|---|---|---|---|
| F1 | high | A second `run_scores` row (new `formula_version`) double-counted a run everywhere | **Fixed.** Every projection/evaluation join pins `SCORE_FORMULA_VERSION = "v0.1"` (tolerating pre-`formula_version` schemas); constants guarded by a test. Runs scored under another formula are invisible until the constant changes (counted in `unaccounted_runs`) |
| F2 | med | Provenance read separately from runs (TOCTOU) | **Fixed.** One read snapshot; a run id absent from the provenance map is a conflict |
| F3 | med | Master-era mock runs counted as benchmark evidence | **Fixed.** Fallback to the evaluation's `params_json` |
| F4 | med | One NaN/Infinity temperature 500'd `GET /jobs` | **Fixed** (also `1e999`, in round 2) |
| F5 | med | Non-default `regenerate` overwrote the canonical report | **Fixed.** Only the benchmark scope writes `leaderboard.html`; others write `leaderboard-<scope>.html`; every report states its scope and what it left out |
| F6 | med | Undeclared factories laundered the requested backend into `runs.backend_kind` | **Fixed.** Only a declared kind is stored |
| F7 | med | Transient startup lock made `migrate_error` permanent | **Fixed** (lazy retry; extended in round 2) |
| F8 | med | Independent evaluations of one model pool into one cell (duplicate `idx`, no per-evaluation breakdown) | **Not fixed — §11/§12.** It is the existing aggregation model; rows stay distinguishable (`job_id`, `/runs/{id}`) |
| F9 | med | One unrecognised `runs.status` 503s every aggregate, unnamed | **Fixed (diagnosability):** the error names run, agent and task (also for corrupt numeric columns). Routes still fail closed |
| F10 | med | Reserved baseline names blended into the bookends | **Fixed** (creation rejects; rows are never aggregated in any scope) |
| F11 | low | Listing showed defaults/coercions as `available` | **Fixed** |
| F12 | low | Guard ignored `mode`/`source_evaluation_id`/extra keys; echoed key names | **Fixed** (extra keys rejected in round 2) |
| F13 | low | Runs lacking scores/diffs invisible and unreconciled | **Fixed (visibility):** `unaccounted_runs` |
| F14 | low | Manifest `version` would override `task.json` | **Not fixed — documented.** No manifest entry has a `version` today, so the path is dormant and untested |
| F15 | low | Migration fast path (and slow-path re-inspection) check names, not definitions | **Not fixed — documented** |
| F16 | low | Job-level `evidence_class` comes from the snapshot | **Not fixed — documented.** Per-trial provenance carries the truth; the UI shows *unknown* for unverifiable jobs |
| F17 | info | `eval_persist.py` wrote into the evidence DB by default | **Fixed** and now tested (refuses the evidence DB; resume ignores mock/conflict runs) |
| F18 | info | Currency is the version string; same-version content drift unseen | **Not fixed — documented** |
| F19 | info | `classify()` raised on an unknown kind | **Fixed** |

Round 2 (regression authors + code review + black-box attack + fact-check) — every item below was **reproduced, fixed and
covered by `tests/test_phase0_hardening_round2.py`** unless marked:

* *high* — evaluations crashed on a `run_scores` table that predates `formula_version` (the F1 pin was unguarded on the write
  side); a snapshot with a scalar `tasks`, absurdly nested JSON (`RecursionError`) or `1e999` escaped the verification
  boundary: the job list 500'd, startup recovery aborted mid-loop (valid orphans stranded `queued`, never dispatched),
  `worker.serve()` crashed, and one deeply nested snapshot on a run-owning job 503'd the entire benchmark read side.
* *medium* — recovery was all-or-nothing and never retried; the migration retry ran synchronously on the event loop; corrupt
  control columns / event payloads 500'd job routes; reserved-name runs still entered `evidence=all`; the accounting
  did not reconcile under the `real`/`synthetic` scopes; the listing said `available` for parameters execution refused;
  unknown top-level params keys were accepted; a dying dispatch thread left its job `running`; `resume` silently
  requeued unrelated orphans; a `NaN` in a request body turned a 422 into a 500.
* *low* — doomed job creations (blank model, non-finite temperature, huge repeats) were accepted; out-of-range integers
  500'd; crafted version strings (`1.²`, 5000 digits) crashed every projection; evaluation reports gave no hint that
  parameters were unverifiable; the HTML provenance panel did not say it counts every persisted run.
* *documented, not changed* — the owner lock lives in `tempfile.gettempdir()` (§11); rows without score/diff rows are
  counted but not inspectable (§3); a persisted row under a reserved name is reachable only by exact id (§6).

Round 3 (fresh reviewers on the newest diff — code review and black-box attack): across rounds 2 and 3 **no attack made a
historical row enter a current aggregate, made a mock or conflicting run enter the default results, made an unverifiable
evaluation execute (zero runs, factory never called), fabricated a provenance value, or changed the evidence DB.** What
they found was **hostile persisted state and recovery bookkeeping** — availability and honesty of the control plane — all
fixed and covered by `tests/test_phase0_hardening_round3.py`:

* recovery's counter/event bookkeeping was not isolated (a failure there lost already-requeued jobs, let `/healthz`
  heal itself to `ok`, and made `worker.serve()` crash-loop);
* invalid UTF-8 in one `evaluation_jobs` column, or JSON parseable but nested ~1000 deep, still 500'd the job list and
  aborted recovery; corrupt event rows 500'd the events route; `PUT /settings` with `NaN`/`1e999`/deep/unencodable
  values persisted a blob that made every later `GET /settings` answer 500;
* the unreadable-job placeholder made a claimed row a phantom `running` job; junk items in `snapshot.tasks` were silently
  dropped by verification; reuse was allowed from a source whose parameters do not verify;
* `dispatch_job` swallowed failures that happen before a claim; the lazy retry could queue requests behind a slow attempt;
  concurrent resume could 500 on an event-sequence collision; task ids longer than the filesystem allows, absurd
  `request_timeout_s`/`base_seed`, infinite or out-of-range stored score/integer columns and an unbounded SSE
  `Last-Event-ID` each produced a 500 or an unnamed 503;
* a **pre-existing** path traversal in the SPA fallback route (`AFA_SERVE_WEB=1`, bound to 127.0.0.1 by default):
  `GET /%2e%2e/<file>` served files outside `web/dist`. Fixed with a containment check; not a benchmark-integrity issue
  but worth stating.

Not fixed (documented, §11): a corrupt *raw* row (`runs`, `run_scores`, `diffs`, `test_results`, `evaluation_trials`) can
still make exact-id and evaluation-scoped routes answer 500 — aggregate routes fail closed with a **named** 503.

## 9. What changed

18 commits on `release/phase0-current-benchmark` over the frozen source (64 files, +12,354 / −993 at `81f9265`, before this
document):

| Theme | Commits |
|---|---|
| Migration serialisation + `runs.backend_kind` | `827805b` |
| Fail-closed parameters; raw provenance recording | `a678b80` |
| Version-aware, provenance-aware projections | `4b96668`, `a9c22fb` (tests that pinned the superseded behaviour) |
| Campaign simulation; independent release suite and its fixes | `1ee4b30`, `e99dc30`, `f589e3e` |
| UI semantics | `508268a`, `4b3c719` (defects found by the manual smoke) |
| Round 1 (red team) | `3ef58a4`, `8095cd7` (web `test:real` revived) |
| Round 1 regression tests; round 2 | `8e3ddce`, `d223356`, `a0de10d`; `37e865f`, `6c4eb2c`, `515e093` |
| Round 3 | `81f9265` |

## 10. Verification

All runs below bracket `reports/runs.sqlite` with its sha256. **It was `42b6dad85ee662d6d5d7f75ffbda5a3b95d50837837f81c875730a8987838ced`
before and after every one** (see §10.2).

### 10.1 Tests (final code, `81f9265`)

| | Result |
|---|---|
| **Full suite** — clean detached worktree, `python3 -m pytest -p no:cacheprovider -ra` | **1202 passed, 0 failed, 0 skipped, 4 warnings in 599.73 s** (the frozen source's reference run was 612 passed; the 4 warnings are the FastAPI/`TestClient` httpx deprecation notice and three `PytestCollectionWarning`s for the runner dataclass `TestSuiteSpec`). 0 `*.pyc` under `tasks/`; the worktree had no tracked change afterwards |
| Cross-system ORACLE+ATLAS integration (`tests/test_integration_oracle_atlas.py`) | 58 passed (the same count as before this work) |
| Acceptance canary (`tests/test_phase0_acceptance_canary.py`) | 1 passed. Receipt: 4 evaluations (fresh, reuse, interrupted→resumed), every native-run / report / result match after an app restart `true`, `unexpected_thread_errors: 0`, historical DB hash before = after. Updated only to request the synthetic view explicitly and to assert the default view excludes the mock evidence |
| Migration concurrency | 44 passed |
| Release-hardening suite (independent author) | 235 passed |
| Red-team regression suites (3 independent authors) | 53 + 67 + 81 = 201 passed |
| Round-2 / round-3 hardening regressions | 64 + 44 = 108 passed |
| Campaign-readiness simulation | 1 passed (§10.4) |
| Web: `npm run typecheck`, `npm run build` | pass |
| Web: Playwright — routes (live app), job view, job events, validation, version evidence | 58 passed (27 with the API mocked, 31 against a running app) |
| Web: real-app end-to-end (`npm run test:real`, real built app + worker, mock backend) | 3 passed, 1 skipped (the optional local-Ollama smoke skips when no server is reachable; §10.7 covers that path) |

The tests that necessarily changed were changed deliberately and explained in their commits (`a9c22fb`, `f589e3e`,
`3ef58a4`, `37e865f`): they had pinned the mixed-version 503, the lenient default-params behaviour, or the pre-hardening
report/regenerate shape.

### 10.2 `reports/runs.sqlite` hashes

| Stage | sha256 before | sha256 after |
|---|---|---|
| Mission start (source frozen) | `42b6dad8…838ced` | — |
| Every intermediate stage: migration, provenance, projections, campaign simulation, UI build, red team, rounds 2–3 (checked at each stage boundary and around each long run) | `42b6dad8…838ced` | `42b6dad8…838ced` |
| Final full suite | `42b6dad8…838ced` | `42b6dad8…838ced` |
| Final ORACLE audit (detached worktree **and** main checkout) | `42b6dad8…838ced` | `42b6dad8…838ced` |
| Ollama provider smoke (scratch copy) | `42b6dad8…838ced` | `42b6dad8…838ced` |
| UI smoke, Playwright suites, canary, scale probe | `42b6dad8…838ced` | `42b6dad8…838ced` |

Full digest: `42b6dad85ee662d6d5d7f75ffbda5a3b95d50837837f81c875730a8987838ced` throughout.

### 10.3 Real historical data gate (committed evidence copy, no synthetic rows)
For `qwen3.5:9b` × `sanitize-filename` (1.0.1 → 1.0.2): overview 200; `real_counts` 30 runs / 6 tasks; the bumped cell is
`historical_only` with `evidence_status: none`, 0 current runs, 5 historical runs; `?version=1.0.1` reproduces the original
40% pass rate over its 5 runs with `evidence_status: historical`; the unbumped cell `fix-binary-search` is `captured`; the
task leaderboard for the bumped task is empty with all 6 models listed as historical-only, and `?version=1.0.1` ranks the 6 by
their old evidence; `version` without `task_id` and an unknown scope are 400; `meta` reports `evaluated_versions
['1.0.1']`, 0 current / 30 historical runs; a mock re-evaluation of a historical model **no longer collapses anything** (all
routes 200, the mock run counted in `excluded.synthetic_runs`, `evidence=all` shows it). No route answered 503 or 409 for
version coexistence. Every model has 30 current runs on 6 tasks and 90 historical runs on 18 tasks; coverage `6/24`.

### 10.4 Campaign-readiness simulation
`tests/test_phase0_campaign_readiness.py`: two existing historical model names × two ORACLE-bumped tasks
(`sanitize-filename`, `toposort`: 1.0.1 → 1.0.2) × 2 repetitions, through the real API, worker, grader and persistence
path, on a copy of the evidence DB, with a factory that declares the `ollama` backend. After **every** evaluation the whole
product stays usable (overview, leaderboard, meta, export, jobs, domains, cells, runs, health: no 503/409); current
evidence is added beside the historical evidence (cells report `current` 2 runs + `historical` 5 runs, aggregated
independently, `real_counts` 30 → 34, coverage 6 → 8 tasks, `excluded.synthetic_runs` 0); the report and JSON export
regenerate; the 10 historical rows on those cells are **not** pooled in; every historical row and its dependent rows are
byte-identical afterwards and none was backfilled; new rows carry `backend_kind='ollama'` and versions 1.0.2.

### 10.5 ORACLE audit (fresh, `--all --full`, clean worktree at `81f9265`)
`PYTHONPATH=integrity:runner:kernel python3 -m afa_integrity audit --all --full --workers 4`, 724,457 ms:
**15 HEALTHY / 2 NEEDS_REVIEW / 7 PROVISIONAL / 0 INVALID** — the same as the integrated baseline. Compared **per task, per
check, per control, per mutation account and per provenance hash** with `compare_audits.py`: *identical for all 24 tasks*;
a recursive diff of the summary JSON differs only in `created_at` and `duration_ms`. 157 checks pass, 2 warn, 9 skipped, 24
unverifiable (hidden-test isolation); 73 controls all matched their expectation (45 known-bad rejected, 13 semantic mutants
rejected, 15 alternatives accepted). Evidence per `docs/AUDIT_EVIDENCE_POLICY.md`:
`integrity/pack-audit/release-full-summary.md`, `release-full-tasks/` (the two NEEDS_REVIEW tasks) and
`release-audit-comparison.md`.

### 10.6 Manual UI smoke (real built app, seeded scratch copy of the evidence DB)
Seeded with: a **historical-only** model (`smoke-historical-only`: legacy runs at old versions only), a **current-only**
model (`smoke-current-only`: `ollama`-attested runs at current versions), a model with **both** (`qwen3.5:9b`: 5 real 1.0.2
runs beside its 5 legacy 1.0.1 runs), a job whose persisted parameters are corrupt, plus two mock evaluations run through
the API. Driven with headless Chrome/Playwright at 1440px and 390px; every page loaded with 0 console errors, 0 bad
responses and no horizontal overflow: overview, leaderboard, agents, the three agent profiles, tasks, task detail, the
historical cell, the current cell, the both-versions cell (default and `?version=1.0.1`), evaluations list, mock monitor and
results, the corrupt job, a current-real raw run, a historical-legacy raw run, a mock raw run, runs explorer, reports,
methodology, new evaluation; JSON and Markdown evaluation reports and the JSON export were fetched; the app was **stopped and
restarted** on the same DB and the overview payload was identical (compared as parsed JSON). Screenshots were read, not just asserted. It found
**two defects** the automated suite had missed — the "Recent evaluations" rows clipped their *Results/Retry* actions and let a
badge overlap the counters at desktop width, and an unverifiable job's detail page asserted an evidence class — plus a stale
"may require an API reload" sentence. All fixed; the first is now covered by a Playwright layout check. The Reports page's
*Regenerate* button was deliberately **not** clicked in the smoke (it rewrites the git-tracked `reports/leaderboard.html`);
regeneration is covered by tests with the output redirected and by `test:real` in a temp copy.

### 10.7 Provider smoke (real local model)
Ollama 0.31.1 with `qwen3.5:9b`, through the app on a scratch copy: `POST /jobs {backend: ollama, tasks:
[sanitize-filename, fix-binary-search], repeats: 1, temperature 0.2}` → succeeded in 70 s, 2/2 passed. Both raw runs
(1221, 1222) carry `runs.backend_kind = 'ollama'` (evaluation snapshot agrees: trial `provenance: consistent`), class
`real`, versions 1.0.0 / 1.0.2 (`version_status: current`); overview `current_runs` 180 → 182, `historical_runs` 540
unchanged, `excluded` all zero; the bumped cell shows `1.0.2 current (1 run)` beside `1.0.1 historical (5 runs)`; all 720
historical rows still have NULL `backend_kind`. (Run twice: once mid-work and once on the final code.) This proves the
persistence and provenance path with a real local model; it is **not** an evaluation of the model.

### 10.8 Scale check (synthetic fixture, scratch DB — not evidence)
1,440 persisted runs (720 committed + 720 added: 6 more models × 24 tasks × 5 at current versions), 12 models: every
projection route (`overview`, `leaderboard`, `meta`, `export`, `domains`, `cell`, `healthz`) answers in **43–48 ms** median
(the projection is rebuilt per request; `/jobs` 1–3 ms). A full 540-run campaign is well inside that.


## 11. Remaining limitations

Benchmark-side (ORACLE; unchanged by this work and out of its scope):

1. **Hidden-test isolation is UNVERIFIABLE** for all 24 tasks (`isolation.hidden_test_readability`): the engine cannot
   prove the sandbox hides the hidden tests from the agent. The execution model is trusted-local, with no isolation claim.
2. **7 tasks are PROVISIONAL** (no declared known-bad / mutant / alternative solutions) and **2 are NEEDS_REVIEW**
   (`fix-list-dedup`: no relevant mutants generated; `refactor-order-validation`: hidden/regression suites import two
   reachable local files). Their discrimination evidence is thinner.
3. The task digest still includes untracked non-bytecode files in a task directory; content drift between the snapshot and
   the run (TOCTOU) is detected at evaluation time, not continuously; content drift at an unchanged **version string** is not
   seen by the projections.

Control-plane / projection side:

4. **Pooling.** Cells are keyed by `runs.agent` (the model name). In the default scope, fresh real runs for a model that
   already has *legacy* runs at a still-current task **pool with them** (cell `n_valid` 5 → 10, duplicate `idx`, classes
   `{legacy, real}`, the tuple route answers 409). This is correct for evidence at the same version but pools different
   producers/settings. Independent evaluations of one model with different generation settings pool the same way (F8), and
   one model name run through two backends pools into one cell. Only `?evidence=real` isolates campaign evidence — and it
   hides the legacy models entirely.
5. **`legacy` is defined by row shape** (§6): any writer that omits both `job_id` and `backend_kind` produces benchmark
   evidence. Provenance attests the configured backend kind, not the model identity; no served-model digest is recorded.
6. **Same-host liveness.** The evaluation owner lock lives in `tempfile.gettempdir()`, so the API and the worker must share a
   host **and** `TMPDIR` (the single-process launcher `afa_app.py` does). With the compose split (`docker-compose.yml`
   runs `api` and `worker` in separate containers sharing only `./reports`), the API's startup recovery
   (`recover_unlocked=True`) cannot see the worker's lock and can requeue — and re-execute — a job the worker is running.
   Pre-existing; **do not use the compose split for a campaign**.
7. Events (`job_events`) are projections of the control plane, not audited evidence.
8. Rows the projection cannot see (no `run_scores` row of formula `v0.1`, or no `diffs` row) are counted in
   `excluded.unaccounted_runs` but not reachable via `/runs/{id}`; runs scored under another formula are invisible until
   the pinned constant changes. One row with an unrecognised `runs.status` or an unreadable numeric column makes every
   aggregate route answer a **named 503** until repaired (fail closed).
9. A corrupt *raw* row (`run_scores`, `diffs`, `test_results`, `evaluation_trials`) can still make exact-id and
   evaluation-scoped routes answer 500; aggregate routes fail closed with a named 503.
10. A run persisted under a reserved baseline name is reachable only by exact id; `?evidence=all` never aggregates it.
11. The migration fast path and slow-path re-inspection check column *names*, not definitions or CHECK text (F15).
12. A manifest `version` would override `task.json` (F14): dormant today (no manifest entry has one) and untested.
13. Job-level `evidence_class`/`backend_kind` come from the creation snapshot (F16); the API reports them even for a job
    whose parameters are unverifiable (the UI shows *unknown*). Every job created before snapshots existed
    (`mode='legacy'`) lists as `unverifiable` and can be neither resumed nor retried. A persisted evaluation with
    `repeats > 10 000` (now refused at creation) is likewise unverifiable.
14. The Reports page has no evidence-scope selector: *Regenerate* and *Export JSON* use the default scope (other scopes are
    API-only). The default-scope *Regenerate* rewrites the **git-tracked** `reports/leaderboard.html`.
15. Ranks over unequal task coverage are not comparable (§3); coverage is shown, not corrected.

## 12. Campaign operator notes (what a reader deciding to run a real-model campaign must know)

* **Where evidence lands.** New runs go to the working DB `reports/app.sqlite` (gitignored), seeded once from
  `reports/runs.sqlite` by the SQLite backup API; the evidence DB itself is refused as a writable target (including its
  aliases). Set `AFA_DB_PATH` identically for the API and the worker.
* **Choose the backend explicitly.** `POST /jobs` defaults to backend `mock` and model `"mock"`: without
  `backend: {kind: ollama | openai_compat}` the job is synthetic and excluded from default results.
* **Two entry points record different things.** The app (jobs API / worker) stores a creation snapshot, a `job_id` and the
  factory's declared backend, and honours `temperature`/`base_seed`/`request_timeout_s` you set.
  `examples/eval_persist.py` always drives `OllamaAgent` (temperature 0.8, base_seed 42), writes job-less runs stamped
  `ollama` with no snapshot, and treats *legacy runs at the current version as already saved* — re-running an existing
  model never re-evaluates the 6 unbumped tasks. Both pool in the default views; do not mix them without meaning to.
* **Pooling decision.** Re-running a model that already has legacy evidence will pool with its 5 legacy runs on the 6
  unbumped tasks. If a separate campaign cohort is wanted, give it a distinct model name (the model name is the cell key)
  or read `?evidence=real`.
* **Expect `MISSING CURRENT`** for every model until it has evidence on the 18 bumped tasks; a partial-coverage rank is not
  a full-benchmark rank. Full coverage needs 18 tasks × 5 repeats × N models of fresh runs.
* Read campaign results from the default views (current benchmark) and use `?version=` / `?evidence=` only to *inspect*.
* Do not run the API and worker in separate containers with separate `TMPDIR`s (§11.6).
* Pre-existing mock jobs in an old `reports/app.sqlite` list as *unverifiable*: that is by design, not corruption.

## 13. Campaign-readiness verdict

**Question: is the system now safe to use as the execution environment for a fresh real-model benchmark campaign?**

**Yes — for the evidence pipeline, under the conditions in §12 — and explicitly not as a statement about the benchmark's
own discriminating power.**

What is demonstrated (not asserted):

* **Current vs historical.** Historical evidence is preserved and never pooled, hidden or restamped; current evidence lands
  beside it; a model with only historical evidence is `MISSING CURRENT` and unranked; no route 503s or 409s for version
  coexistence — on the committed evidence, in the campaign simulation, in the real-model smoke and in the UI smoke.
* **Fail-closed parameters.** Corrupt persisted parameters (and, after three adversarial rounds, corrupt or hostile persisted
  state of many kinds) never execute, resume, retry or recover with defaults: zero runs, factory never called.
* **Provenance.** `runs.backend_kind` is written from what the factory declares, never backfilled, never invented; mock
  evidence is excluded from default results but inspectable; a contradiction is surfaced as an integrity error.
* **Migration.** Serialised, loud, retried lazily, race-tested with real threads and processes; historical rows untouched.
* **Nothing about the benchmark changed**: the fresh full ORACLE audit is identical to the baseline check by check.
* The immutable evidence DB never changed, through 1202 tests, a full audit, a real-model run and a UI smoke.

What is **not** demonstrated or not guaranteed, and why the answer is conditional:

1. The **540-run (or 720-run) campaign itself was deliberately not run** (out of scope); behaviour at that volume is
   supported by the 1,440-row scale check and the 2×2×2 simulation, not by a real campaign.
2. **Hidden-test isolation is UNVERIFIABLE**, 7 tasks are PROVISIONAL and 2 NEEDS_REVIEW (§11.1–2): the projections are
   trustworthy about *what was recorded*, not about whether every task discriminates well.
3. The pooling behaviour in §11.4 / §12 is a **decision the campaign operator must make on purpose** (distinct model name
   or `?evidence=real` for an isolated cohort); the system does not make it for them and the default view will pool
   legacy and fresh real runs at the six unbumped tasks.
4. Provenance attests the configured backend kind, not the model identity; no model digest is recorded.
5. The API and worker must run on one host with one `TMPDIR` (§11.6); the compose split is unsafe for a campaign.
6. Hostile or corrupt *raw* rows can still make some forensic routes answer 500 (aggregates fail closed with a named 503).

If those conditions are met, results produced by the app path (jobs API + worker, explicit backend) are attributable — by
version, by provider and by the exact parameters that ran — and cannot silently contaminate, or be contaminated by, the
committed historical evidence. That is the claim, and it stops there.

