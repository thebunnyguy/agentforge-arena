# AgentForge Arena — Local Product App Implementation Plan

## Purpose

This document defines the practical implementation plan for turning **AgentForge Arena** from a CLI + static report benchmark into a **local browser-based application**.

The goal is not merely to build a frontend. The goal is:

> User opens a local app → selects a local model and task set → starts a benchmark → watches progress → inspects results → exports reports — without manually using terminal commands for the core workflow.

This plan is intentionally incremental. Each phase must be independently shippable, testable, and reviewable before moving to the next.

---

## Current Repo Reality

The current repository already has a strong backend foundation:

```txt
kernel/      scoring, aggregation, Wilson intervals, ranking, domain statistics
runner/      agents, sandbox, task loading, grading, diff capture, SQLite persistence, reports
tasks/       benchmark task pack
reports/     persisted runs.sqlite and leaderboard.html
examples/    CLI evaluation/report scripts
```

The existing system already supports:

- Running model evaluations from CLI.
- Persisting runs into SQLite.
- Storing per-run scores, diff stats, patch text, and per-test results.
- Generating a static HTML leaderboard.
- Reusing the frozen scoring/statistics kernel.
- Running local models through Ollama or OpenAI-compatible local endpoints.

The missing product layer is:

```txt
api/ or afa_api/      local FastAPI app
web/                  browser UI
worker                background evaluation runner
docker-compose.yml    one-command local launch
```

---

## Non-Negotiable Rules

These rules apply across every phase.

### Do not touch benchmark truth casually

```txt
Do not modify kernel scoring math.
Do not silently change leaderboard formulas.
Do not change task semantics.
Do not edit hidden tests or task contracts unless explicitly doing a task-pack repair.
Do not rerun model evaluations unless explicitly requested.
```

### Keep the app honest

The app must always describe itself as:

```txt
trusted-local benchmark / local product app
```

not:

```txt
secure untrusted-agent platform
```

The current `LocalSandbox` is not a security boundary. The UI and README must not imply that arbitrary hostile agents are safely isolated.

### Keep local-first constraints

```txt
No paid APIs.
No hosted OpenAI API support in v1.
No LLM-as-judge.
No cloud-first architecture.
No multi-user auth.
No Postgres in the first product version.
```

### Avoid overbuilding

Do not start with:

```txt
Celery
Redis
Postgres
WebSockets
Next.js/Vercel static site
DockerSandbox
multi-user auth
parallel jobs
cloud deployment
```

Those are future concerns, not the next implementation step.

---

# Phase 0 — Implementation Freeze and Safety Baseline

## Goal

Lock the boundaries before coding the app layer.

## Scope

This phase does not add product functionality. It confirms what is frozen and what is allowed to change.

## Deliverables

Create or update a short implementation note, for example:

```txt
docs/APP_IMPLEMENTATION_RULES.md
```

It should state:

- `kernel/` math is frozen.
- `tasks/` semantics are frozen unless explicitly repairing task contracts.
- `runner/` can be reused but should not be rewritten.
- New app code should live in new directories first.
- Current `reports/runs.sqlite` is a source-of-truth artifact, not a playground.
- The app is trusted-local only.

## Files allowed

```txt
docs/APP_IMPLEMENTATION_RULES.md
```

## Files not allowed

```txt
kernel/**
tasks/**
reports/runs.sqlite
```

## Verification

Run:

```bash
python3 -m pytest
```

Expected:

```txt
All existing tests pass.
No benchmark data changed.
No report numbers changed.
```

## Stop condition

Stop if any tests fail or any benchmark/result artifact changes unexpectedly.

---

# Phase 1 — Read-Only FastAPI API

## Goal

Expose the existing benchmark results through a local HTTP API without changing any data.

This phase creates the backend read layer for the future app.

## Why this comes first

The repo already has persisted data and report functions. Before building a UI or live runner, we need an API that proves it can expose the same truth as the existing report.

## New directory

```txt
afa_api/
```

Suggested structure:

```txt
afa_api/
  __init__.py
  main.py
  serialize.py
  db.py
  errors.py
```

## Endpoints

Minimum endpoints:

```txt
GET /api/health
GET /api/meta
GET /api/leaderboard
GET /api/leaderboard?task_id=<task_id>
GET /api/domains/<agent>
GET /api/cell/<agent>/<task_id>
GET /api/run/<agent>/<task_id>/<idx>
```

## API behavior

### `GET /api/health`

Returns:

```json
{
  "status": "ok",
  "db_ok": true,
  "total_runs": 600,
  "agents": 5,
  "tasks": 24
}
```

### `GET /api/meta`

Returns:

- task list
- agent list
- run counts
- task version distribution
- patch/test artifact coverage
- formula version
- trusted-local caveat
- DB/report provenance if available

### `GET /api/leaderboard`

Uses existing report functions.

Must not compute leaderboard math in the API manually.

### `GET /api/domains/<agent>`

Uses existing domain profile function.

### `GET /api/cell/<agent>/<task_id>`

Returns:

- aggregate result for the agent × task cell
- ordered run rows
- captured/not-captured flags
- score primitives for each run

### `GET /api/run/<agent>/<task_id>/<idx>`

Returns:

- run score
- diff stats
- patch text if captured
- per-test results if captured
- clear not-captured state if legacy row
- synthetic state if synthetic baseline is later included

## Implementation constraints

Use existing backend functions wherever possible:

```txt
leaderboard()
domain_profile()
task_aggregate()
SqliteRunStore.load_runs()
SqliteRunStore.summary()
```

Direct SQL is allowed only for details not returned by `load_runs`, such as:

```txt
patch_text
test_results
created_at
touched_protected
```

## Important design choice

For this phase, do not add synthetic baselines unless already required by the existing report path.

If synthetic baselines are included, they must be explicitly marked:

```json
{
  "synthetic": true
}
```

## Tests

Add:

```txt
runner/tests/test_api_readonly.py
```

Suggested tests:

```txt
test_health_returns_db_counts
test_leaderboard_matches_report_function
test_meta_reports_artifact_coverage
test_cell_returns_aggregate_and_runs
test_run_returns_patch_when_captured
test_run_returns_not_captured_for_legacy_rows
test_unknown_agent_returns_404
test_unknown_task_returns_404
test_no_endpoint_mutates_database
```

## Verification commands

```bash
python3 -m pytest
```

Optional manual checks:

```bash
uvicorn afa_api.main:app --reload
curl http://127.0.0.1:8000/api/health
curl http://127.0.0.1:8000/api/leaderboard
```

## Acceptance gate

Phase 1 is complete only if:

```txt
Existing tests pass.
New API tests pass.
Leaderboard API numbers match existing report functions.
No DB rows are added.
No report artifacts are modified.
No scoring math is duplicated.
```

---

# Phase 2 — Basic Vite React Dashboard

## Goal

Build the first browser UI over the read-only API.

The app should now let a user inspect existing benchmark results without opening terminal reports manually.

## New directory

```txt
web/
```

Suggested structure:

```txt
web/
  package.json
  vite.config.ts
  index.html
  src/
    main.tsx
    App.tsx
    api/
      client.ts
      types.ts
    components/
      Layout.tsx
      WilsonBar.tsx
      ScoreBadge.tsx
      CaveatBanner.tsx
      LoadingState.tsx
      ErrorState.tsx
    pages/
      Overview.tsx
      CellPage.tsx
      RunPage.tsx
```

## Pages in this phase

Only build three pages first:

```txt
/
  Overview

/cell/:agent/:taskId
  Cell drilldown

/cell/:agent/:taskId/run/:idx
  Run detail
```

Do not build the full app shell yet.

## Overview page

Must show:

- trusted-local warning
- DB/run summary
- leaderboard table
- Wilson interval bars
- domain matrix or domain summary
- task/version/capture coverage summary

## Cell page

Must show:

- agent
- task id
- aggregate pass rate
- Wilson interval
- n_valid / n_pass
- mean/median/min/max/std score if provided
- run table
- score primitives per run:
  - `G`
  - `T_hidden`
  - `S`
  - `X`
  - status
  - captured/not captured

## Run page

Must show:

- run identity
- task version
- status
- score breakdown
- patch text if captured
- test results if captured
- not-captured state if missing
- Q caveat if `q_components` is unavailable

## Frontend rule

The frontend must not compute benchmark statistics.

Allowed frontend math:

```txt
format percentages
scale an already-returned value onto a pixel bar
sort/filter rows for display only
```

Forbidden frontend math:

```txt
Wilson interval computation
pass@k computation
ranking computation
mean/std recomputation
domain pooling
Kish effective n
```

## Verification

```bash
cd web
npm install
npm run build
```

Also run backend tests:

```bash
python3 -m pytest
```

## Acceptance gate

Phase 2 is complete only if:

```txt
Frontend builds.
Overview numbers match API.
API numbers match backend report functions.
No browser-side benchmark math exists.
No job/run mutation exists.
```

---

# Phase 3 — Polished Read-Only App Shell

## Goal

Turn the basic dashboard into an app-like read-only explorer.

This is still read-only. It prepares the UX foundation for future live evaluation.

## Pages to add

```txt
/leaderboard
/agents
/agent/:agent
/tasks
/task/:taskId
/runs
/methodology
```

## Layout

Add:

```txt
sidebar
topbar
global trusted-local badge
DB snapshot/provenance footer
navigation breadcrumbs
```

## Required UI honesty elements

Every relevant page should surface:

```txt
trusted-local only
no untrusted-agent isolation
synthetic baselines if present
task versions
captured vs not captured
Q components unavailable/default Q behavior
domain imbalance
small-n/provisional status
```

## Runs page

A simple filterable table is enough.

Filters:

```txt
agent
task
status
functional_pass
captured/not captured
```

Do not over-engineer with heavy virtualization unless the table becomes slow.

Current data is small.

## Methodology page

Explain:

- `G`
- `T_hidden`
- `Q`
- `S`
- `X`
- Wilson intervals
- provisional ranks
- voided infra failures
- domain profile displayability
- why the app is trusted-local only

## Verification

```bash
npm run build
python3 -m pytest
```

Manual checks:

```txt
All routes load.
Deep links work.
Unknown agent/task/run shows clean error.
No route triggers DB writes.
```

## Acceptance gate

Phase 3 is complete only if:

```txt
The read-only app feels usable.
All result pages are navigable.
The app honestly explains limitations.
No live evaluation controls exist yet.
```

---

# Phase 4 — Job Schema and Job API, No Worker Yet

## Goal

Introduce product-job state without executing evaluations yet.

This phase creates the app's control-plane data model.

## Tables

Add app-owned tables beside the existing raw benchmark tables.

Recommended schema:

```sql
CREATE TABLE IF NOT EXISTS evaluation_jobs (
    id TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    cancel_requested INTEGER NOT NULL DEFAULT 0,
    params_json TEXT NOT NULL,
    total_runs INTEGER NOT NULL DEFAULT 0,
    completed_runs INTEGER NOT NULL DEFAULT 0,
    passed_runs INTEGER NOT NULL DEFAULT 0,
    voided_runs INTEGER NOT NULL DEFAULT 0,
    failed_runs INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT,
    error_message TEXT
);

CREATE TABLE IF NOT EXISTS job_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT NOT NULL,
    seq INTEGER NOT NULL,
    ts TEXT NOT NULL,
    type TEXT NOT NULL,
    payload_json TEXT,
    UNIQUE(job_id, seq)
);

CREATE INDEX IF NOT EXISTS ix_job_events_job_seq
ON job_events(job_id, seq);

CREATE TABLE IF NOT EXISTS app_settings (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    settings_json TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS job_runs (
    job_id TEXT NOT NULL,
    run_id INTEGER NOT NULL,
    PRIMARY KEY (job_id, run_id)
);
```

## Why `job_runs` instead of modifying `runs`

Use `job_runs(job_id, run_id)` first.

Reason:

```txt
It preserves the raw runs table as an append-only benchmark artifact.
It avoids post-insert UPDATE runs SET job_id.
It keeps product metadata separate from benchmark data.
```

If later the team chooses to add `runs.job_id`, that can be done as a product optimization, not required now.

## New endpoints

```txt
GET  /api/jobs
GET  /api/jobs/<job_id>
POST /api/jobs
POST /api/jobs/<job_id>/cancel
POST /api/jobs/<job_id>/retry
GET  /api/settings
PUT  /api/settings
POST /api/backends/verify
```

## Behavior

### `POST /api/jobs`

Creates a queued job only.

It should not start the worker and should not create run rows.

Job params:

```json
{
  "backend": {
    "kind": "mock",
    "base_url": null
  },
  "model": "mock",
  "name": "mock",
  "tasks": ["fix-binary-search"],
  "repeats": 1,
  "base_seed": 42,
  "temperature": 0.8,
  "request_timeout_s": 180
}
```

Start with `mock` backend support only.

## Frontend pages

Add:

```txt
/jobs
/jobs/:jobId
/settings
/new
```

But `/new` should only create queued jobs. It should not run them yet.

## Verification

Tests:

```txt
test_create_job
test_list_jobs
test_cancel_queued_job
test_retry_terminal_job_creates_new_job
test_job_tables_do_not_modify_raw_runs
test_settings_redacts_secret_fields
```

## Acceptance gate

Phase 4 is complete only if:

```txt
Jobs can be created and listed.
No evaluations run.
No new rows appear in runs.
No scoring/reporting changes occur.
```

---

# Phase 5 — Worker With Mock Jobs Only

## Goal

Introduce the background worker safely using mock/deterministic jobs before connecting real local models.

## New file

```txt
afa_api/worker.py
```

## Worker behavior

```txt
poll queued jobs
claim one job atomically
load task selection
construct mock agent
run existing pipeline
save run via SqliteRunStore.save_run()
insert job_runs link
emit job_events
update job counters
mark job succeeded/failed/canceled
```

## Reuse existing code

The worker should mirror `examples/eval_persist.py`.

The existing CLI already does the important things correctly:

```txt
loads manifest
constructs agent once
constructs LocalSandbox
loads tasks
skips already completed indices
calls run_once()
calls store.save_run()
prints PASS/fail/VOID(infra)
```

Do not rewrite the runner pipeline.

## Job claiming

Use conditional update:

```sql
UPDATE evaluation_jobs
SET status='running', started_at=:now
WHERE id=:id AND status='queued';
```

Claim succeeds only if affected rows = 1.

## Job events

Minimum event types:

```txt
job_started
run_started
run_persisted
progress
job_done
job_failed
job_canceled
log
error
```

Avoid too many micro-events at first.

You can add `run_diffed` and `run_graded` later if useful.

## Run identity issue

Before worker writes real repeated runs, define this clearly.

Recommended:

```txt
Inside a job, idx is the repeat index for that job.
Globally, product job detail uses job_id + task_id + idx.
Explorer global cell/run routes remain for existing report-style views.
```

Product-specific run detail route:

```txt
/jobs/:jobId/runs/:taskId/:idx
```

Explorer route remains:

```txt
/cell/:agent/:taskId/run/:idx
```

This avoids collisions when the same model/task is evaluated multiple times.

## Verification

Start with a tiny mock job:

```txt
1 task
1 repeat
```

Then:

```txt
2 tasks
2 repeats
```

Tests:

```txt
test_worker_claims_job
test_worker_persists_mock_run
test_worker_links_run_to_job
test_worker_emits_progress_events
test_worker_marks_job_succeeded
test_cancel_between_runs
```

## Acceptance gate

Phase 5 is complete only if:

```txt
Mock jobs run end-to-end.
New runs are persisted.
job_runs links are correct.
Read-only dashboard sees new data after refresh.
No real model execution exists yet.
```

---

# Phase 6 — SSE Live Monitor

## Goal

Stream live progress from the worker to the browser.

## New endpoint

```txt
GET /api/jobs/<job_id>/events
```

Use Server-Sent Events.

## SSE behavior

Each event should include:

```txt
id: <seq>
event: <type>
data: <payload_json>
```

Support resume:

```txt
Last-Event-ID
```

If the browser reconnects, replay events after the last seen `seq`.

## Frontend page

```txt
/jobs/:jobId
```

Add live monitor behavior:

```txt
overall progress bar
current run
event log
PASS / fail / VOID(infra)
cancel button
terminal state
```

## Poll fallback

Also support:

```txt
GET /api/jobs/<job_id>/events?since=<seq>
```

Returning JSON array.

This helps testing and fallback if SSE has issues.

## Verification

Tests:

```txt
test_sse_replays_from_start
test_sse_resumes_after_last_event_id
test_poll_fallback_returns_events_since_seq
test_terminal_event_closes_stream
```

Manual:

```txt
start mock job
open live monitor
refresh page mid-job
events replay correctly
```

## Acceptance gate

Phase 6 is complete only if:

```txt
Live progress works for mock jobs.
Reconnect does not duplicate displayed runs.
Cancel updates UI correctly.
No real model execution yet.
```

---

# Phase 7 — Real Local Model Runner

## Goal

Connect the product job system to actual local models.

Only start this after mock worker + SSE are reliable.

## Supported backends

### Ollama

Default backend:

```txt
http://host.docker.internal:11434
```

Verify endpoint:

```txt
GET /api/tags
```

### OpenAI-compatible local server

Examples:

```txt
LM Studio
llama.cpp server
vLLM
Ollama /v1 endpoint
```

Important caveat:

The current OpenAI-compatible agent does not send an Authorization header.

So in v1:

```txt
Do not expose a working API key field.
Hide it or mark it unsupported for generation.
```

## New Evaluation wizard

Now fully enable:

```txt
backend verification
model selection
task selection
repeats
base seed
temperature
request timeout
review
launch
```

## Start small

Manual smoke progression:

```txt
1 model × 1 task × 1 repeat
1 model × 3 tasks × 1 repeat
1 model × 24 tasks × 1 repeat
1 model × 24 tasks × 5 repeats
```

Do not jump directly to full benchmark.

## Acceptance gate

Phase 7 is complete only if:

```txt
Ollama job runs from browser.
Results persist.
Live monitor shows progress.
Dashboard reflects new runs.
OpenAI-compatible local mode is either working honestly or hidden.
No hosted paid API support exists.
```

---

# Phase 8 — Docker Compose Local App

## Goal

Package the product as a local app launched through Docker Compose.

## Services

```txt
web
api
worker
```

Optional later:

```txt
ollama
```

Default should connect to host Ollama, not run Ollama inside Docker.

## Files

```txt
docker-compose.yml
docker/api.Dockerfile
docker/web.Dockerfile
docker/worker.Dockerfile
.env.example
.dockerignore
```

## Ports

Expose one main app port:

```txt
http://localhost:8080
```

## Volumes

Persist:

```txt
reports/runs.sqlite
reports/leaderboard.html
```

Suggested volume strategy:

```txt
./reports:/app/reports
```

This keeps results visible in the repo while developing.

For more product-like mode later, use a named volume.

## Environment variables

```txt
AFA_DB_PATH=/app/reports/runs.sqlite
AFA_TASKS_DIR=/app/tasks
AFA_OLLAMA_BASE_URL=http://host.docker.internal:11434
AFA_API_BASE_URL=http://api:8000
```

## Verification

From fresh clone:

```bash
docker compose up --build
```

Then open:

```txt
http://localhost:8080
```

Acceptance checks:

```txt
dashboard loads
API health ok
jobs page loads
settings page loads
mock job can run
Ollama verify works if host Ollama is running
```

## Acceptance gate

Phase 8 is complete only if:

```txt
A user can launch the app with Docker Compose.
They can inspect existing results.
They can run a mock job.
They can run a small Ollama job if Ollama is available.
No terminal is needed after startup.
```

---

# Phase 9 — Report Regeneration and Export

## Goal

Let users regenerate and export reports from the browser.

## Endpoints

```txt
POST /api/reports/regenerate
GET  /api/reports/latest
GET  /api/export/json
GET  /api/export/csv
GET  /api/export/html
```

## Behavior

Use existing report code.

Report regeneration should:

```txt
read current reports/runs.sqlite
generate reports/leaderboard.html
return status/path
```

Do not generate inside a long blocking request if it becomes slow.

Use job/background task if needed.

## Frontend

Add:

```txt
/reports
```

Shows:

```txt
last generated time
DB snapshot info
regenerate button
download HTML
download JSON/CSV
warning that report is a snapshot
```

## Acceptance gate

Phase 9 is complete only if:

```txt
Report regeneration matches existing report_combined output.
Exports are clearly labeled.
No export changes benchmark data.
```

---

# Phase 10 — Product Polish

## Goal

Make the app feel stable and demo-ready.

## Add

```txt
friendly empty states
loading skeletons
error cards
backend unreachable page
Ollama not running guidance
copyable command snippets
persistent settings
dark/light mode only if easy
README quickstart
screenshots or GIFs
```

## Update README

Add a product section:

```txt
## Local App Quickstart

1. Install Docker.
2. Install and start Ollama.
3. Pull a local model.
4. Run docker compose up.
5. Open http://localhost:8080.
```

## Acceptance gate

```txt
Fresh user can follow README.
App starts.
Existing results visible.
Small job can run.
Report can export.
Limitations are clearly stated.
```

---

# Future Phases — Not Now

These are future roadmap items, not part of the immediate implementation.

## Future A — DockerSandbox

Goal:

```txt
real process/container isolation for untrusted agents
```

Until this exists, do not claim secure untrusted execution.

## Future B — Postgres backend

Use only if:

```txt
multi-user/team deployment
large-scale hosted service
many concurrent writers
```

SQLite is enough for local v1.

## Future C — Static public evidence site

Optional:

```txt
Vercel/GitHub Pages static benchmark explorer
read-only
no job controls
```

This should reuse the serializer from the local app but remain a separate artifact.

## Future D — Multi-model batch jobs

Once single-model jobs are stable, allow:

```txt
run multiple models in one job
```

Not needed for v1.

## Future E — Auth / multi-user

Only if converting from local app to hosted service.

---

# Recommended Codex/Sonnet Execution Instruction

Use this instruction when asking an agent to implement.

```txt
Implement AgentForge Arena as a local browser app in strict phases.

Start with Phase 1 only.

Phase 1 scope:
- Add afa_api/ with FastAPI read-only endpoints.
- Reuse existing SqliteRunStore and report functions.
- Add serializer functions for overview, leaderboard, domains, cell, run, and meta.
- Add tests for all endpoints.
- Do not modify kernel/, tasks/, scoring math, or task semantics.
- Do not add job tables.
- Do not add worker.
- Do not add Docker.
- Do not rerun model evaluations.
- Do not mutate reports/runs.sqlite.

After Phase 1, stop and report:
1. files changed
2. endpoints added
3. tests added
4. exact test command run
5. whether API numbers match the existing report/store
```

---

# Final Phase Order

```txt
0. Freeze backend/math rules
1. Read-only FastAPI API
2. Basic Vite React dashboard
3. Polished read-only app shell
4. Job schema + job API, no worker
5. Worker with mock jobs only
6. SSE live monitor
7. Real local model runner
8. Docker Compose local app
9. Report regenerate/export
10. Product polish
```

This is the safest path from the current repo to a proper local application.
