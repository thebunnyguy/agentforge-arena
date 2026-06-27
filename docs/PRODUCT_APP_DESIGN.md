# AgentForge Arena — Product App Design

A local browser application for **running** evaluations, not just viewing them. It wraps
the existing offline evaluation pipeline in a single-user web app: a New-Evaluation
wizard, a live progress monitor, job history, and report export — all on the local host,
all offline.

This document is the **product app**. The read-only results explorer it embeds is
specified separately in [OBSERVABILITY_FRONTEND_DESIGN.md](OBSERVABILITY_FRONTEND_DESIGN.md);
this doc reuses that explorer verbatim as its "results" surface and adds everything needed
to *launch and monitor* evaluations. It maps to **roadmap Phases 3–5** (the explorer is
Phases 1–2; the static evidence site is Phase 6, optional).

---

## 1. Overview & goals

The product app turns AgentForge Arena from a CLI + static report into a one-command local
tool that a single user runs on their own machine to:

1. Configure a local model backend (Ollama, or an OpenAI-compatible **local** server).
2. Launch an evaluation job (model × tasks × repeats) through a guided wizard.
3. Watch it run live (per-run progress, pass/fail, gate outcomes) and cancel/retry it.
4. Browse the results in the embedded read-only explorer, regenerate the report, and
   export the data.

Design priorities, in order:

1. **Reuse, don't reinvent.** The worker drives the **existing** pipeline
   (`examples/eval_persist.py`, `afa_runner.pipeline`, the clean-room grader,
   `SqliteRunStore`). The frozen kernel (`afa_kernel`) is the sole authority for
   scoring/aggregation/confidence/ranking. The product app introduces **no new scoring
   math** — it orchestrates, persists job state, and projects results.
2. **Offline-first.** Zero external network calls, no paid LLM APIs, no LLM-as-judge.
   Models are local (Ollama / LM Studio / llama.cpp / vLLM). Any "API key" field is for a
   *local* OpenAI-compatible server, never a hosted paid endpoint.
3. **Honest about what it is.** A trusted, single-user, local tool. It makes **no claim**
   of isolating untrusted or adversarial agents (§10).
4. **One serializer, one app.** The same FastAPI process serves the read-only explorer
   endpoints (via `afa_api/serialize.py`) and the new job/SSE/settings endpoints. The
   frontend is one Vite React SPA.

---

## 2. Scope & non-goals

### In scope (this doc)

- `evaluation_jobs` + `job_events` + `app_settings` tables (§4).
- A worker process that claims and runs jobs, emitting events (§5).
- Job/SSE/settings/report API on top of the read-only explorer API (§6).
- React wizard, live monitor, jobs history, settings, and the embedded results explorer (§7).
- Report regeneration and export (§8).
- One-command Docker Compose local app (§9).

### Non-goals

- **No untrusted-agent isolation / sandboxing claims.** See §10. A hardened
  `DockerSandbox` is explicitly out of scope and unclaimed.
- **No authentication / multi-tenancy.** Single user, bound to localhost.
- **No new statistics.** All numbers come from the frozen kernel via the report functions
  or are raw DB columns — same constraint as the explorer.
- **No paid/cloud model providers.** Local backends only.
- **No static/Vercel delivery.** Deferred to the explorer doc's Appendix A (Phase 6).

---

## 3. Architecture

```
            ┌──────────────────────────────────────────────────────────┐
            │  Vite React SPA  (web/)                                    │
            │  wizard · live monitor · jobs history · settings ·         │
            │  results = embedded read-only explorer                     │
            └───────────────┬───────────────────────┬──────────────────┘
                            │ fetch /api/v1/...      │ EventSource (SSE)
            ┌───────────────▼───────────────────────▼──────────────────┐
            │  FastAPI  (afa_api/main.py)  — ONE process                 │
            │  • read-only explorer routes  → afa_api/serialize.py       │
            │  • job routes (create/list/get/cancel/retry)               │
            │  • SSE + poll routes (job_events)                          │
            │  • settings + backend-verify + report/export routes        │
            └───────────────┬───────────────────────┬──────────────────┘
                            │ writes job rows         │ reads
                            ▼                         ▼
            ┌──────────────────────────────────────────────────────────┐
            │  SQLite  reports/runs.sqlite  (WAL)                        │
            │  existing: runs · run_scores · diffs · test_results        │
            │  new:      evaluation_jobs · job_events · app_settings     │
            └───────────────▲──────────────────────────────────────────┘
                            │ writes runs + job_events + progress
            ┌───────────────┴──────────────────────────────────────────┐
            │  Worker  (afa_api/worker.py)  — separate process           │
            │  claims a queued job → runs eval_persist/pipeline per      │
            │  (task, repeat) → grades in clean room → persists run →    │
            │  emits job_events → updates progress                       │
            └────────────────────────┬─────────────────────────────────┘
                                     │ local HTTP
                            ┌────────▼─────────┐
                            │  Ollama / OpenAI- │   (host or compose service;
                            │  compatible local │    model must be pulled once)
                            └───────────────────┘
```

Three processes (api, worker, web) share one SQLite file. The split between API and worker
matters: the API is request/response and must stay responsive; running a model takes
seconds-to-minutes per run, so it lives in the worker, never in a request handler.

### Relationship to the explorer

The explorer doc owns `afa_api/serialize.py`, the two-store startup load (disk store = 600
real runs; in-memory store = real + synthetic baselines), and the read-only routes. This
doc **adds to the same `afa_api` package and the same FastAPI app** — it does not fork it.
The "results" view in the product UI is the explorer's overview/cell/run views, scoped to a
job's runs (§7.5). Run identity on the wire is `(agent, task_id, idx)`, never `runs.id` —
matching the explorer, so the results view deep-links into explorer routes without
translation.

---

## 4. Data model

New tables sit **alongside** the existing raw layer and never alter the meaning of
`runs` / `run_scores` / `diffs` / `test_results`. They are created idempotently at startup
(`CREATE TABLE IF NOT EXISTS`), the same pattern the existing store uses.

### 4.1 `evaluation_jobs`

```sql
CREATE TABLE IF NOT EXISTS evaluation_jobs (
  id              TEXT PRIMARY KEY,                 -- uuid4 hex, generated by the API
  status          TEXT NOT NULL DEFAULT 'queued'
                  CHECK (status IN ('queued','running','succeeded','failed','canceled')),
  cancel_requested INTEGER NOT NULL DEFAULT 0,      -- 0/1; set by API, observed by worker
  params_json     TEXT NOT NULL,                    -- full wizard payload (§6.2)
  total_runs      INTEGER NOT NULL DEFAULT 0,       -- planned = tasks × repeats (one model/job)
  completed_runs  INTEGER NOT NULL DEFAULT 0,
  passed_runs     INTEGER NOT NULL DEFAULT 0,       -- functional_pass == true
  voided_runs     INTEGER NOT NULL DEFAULT 0,       -- infra_failure (excluded from n)
  failed_runs     INTEGER NOT NULL DEFAULT 0,       -- valid runs that did not functionally pass
  created_at      TEXT NOT NULL,
  started_at      TEXT,
  finished_at     TEXT,
  worker_id       TEXT,
  error_message   TEXT
);
```

### 4.2 `job_events`

Append-only event log per job. The monotonic `seq` is what makes the stream replayable for
SSE resume (§6.3).

```sql
CREATE TABLE IF NOT EXISTS job_events (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  job_id      TEXT NOT NULL REFERENCES evaluation_jobs(id),
  seq         INTEGER NOT NULL,                     -- 1,2,3… per job, assigned by the worker
  ts          TEXT NOT NULL,
  type        TEXT NOT NULL
              CHECK (type IN ('job_started','run_started','run_diffed','run_graded',
                              'run_persisted','progress','log',
                              'job_done','job_failed','job_canceled','error')),
  payload_json TEXT,
  UNIQUE (job_id, seq)
);
CREATE INDEX IF NOT EXISTS idx_job_events_job_seq ON job_events(job_id, seq);
```

Payload examples: `run_started` → `{agent, task_id, idx}`; `run_graded` → `{agent, task_id,
idx, gate_product, t_hidden, final_score, functional_pass, status}`; `progress` →
`{completed, total, passed, voided, failed}`; `log` → `{level, message}`.

### 4.3 `app_settings`

A single-row table holding persisted defaults (backend connection + run defaults).

```sql
CREATE TABLE IF NOT EXISTS app_settings (
  id            INTEGER PRIMARY KEY CHECK (id = 1),
  settings_json TEXT NOT NULL,
  updated_at    TEXT NOT NULL
);
```

`settings_json`: `{ backend: {kind, base_url, api_key_present}, defaults:
{repeats, base_seed, temperature, request_timeout_s} }`. A raw `api_key` (for a local
OpenAI-compatible server) is stored server-side only and never returned to the SPA — the
API returns `api_key_present: true|false`. (See §6.2 for the current wiring caveat.)

### 4.4 Run ↔ job linkage

Add a nullable column to `runs` via an **idempotent migration** (guarded by
`PRAGMA table_info(runs)` so it runs at most once):

```sql
ALTER TABLE runs ADD COLUMN job_id TEXT;            -- NULL for the 600 pre-job-era runs
CREATE INDEX IF NOT EXISTS idx_runs_job ON runs(job_id);
```

Chosen over a separate link table because "show me this job's runs" becomes a plain
`WHERE job_id = ?`, and it leaves the existing insert path untouched: the **worker stamps
`job_id`** on the rows it writes (it knows the job id), rather than changing
`SqliteRunStore.save_run`'s signature. Existing runs stay `NULL` (they predate the job
system); the explorer treats `job_id IS NULL` as "ad-hoc / pre-job," never an error.

### 4.5 Job state machine

```
            ┌─────────┐  worker claims   ┌─────────┐
   create ─▶│ queued  │ ───────────────▶ │ running │
            └────┬────┘                  └────┬────┘
                 │ cancel (pre-claim)         │ all runs done ─▶ succeeded
                 ▼                            │ cancel observed ─▶ canceled
            ┌─────────┐                       │ fatal error     ─▶ failed
            │canceled │◀──────────────────────┘
            └─────────┘
```

`succeeded` / `failed` / `canceled` are terminal. "Retry" (§6.1) creates a **new** job; it
never mutates a terminal one.

---

## 5. Worker process

A single long-lived Python process (`afa_api/worker.py`), one Compose service. It is the
only component that runs models and writes run rows.

### 5.1 Claiming a job (atomic)

Poll for the oldest `queued` job, then claim with a conditional UPDATE so a double-start can
never grab the same job:

```sql
UPDATE evaluation_jobs
   SET status='running', worker_id=:wid, started_at=:now
 WHERE id=:id AND status='queued';
-- claim succeeded iff rowcount == 1
```

v1 runs **one worker, one job at a time** (predictable on a single-GPU/CPU local box); the
claim is written to stay safe if that ever changes.

### 5.2 Execution loop

For the claimed job, expand `params_json` into the planned run list (tasks × repeats), set
`total_runs`, emit `job_started`, then for each unit:

1. Emit `run_started`.
2. Drive the **existing** pipeline — the same code `examples/eval_persist.py` uses
   (`OllamaAgent`/`OpenAICompatAgent` → `run_once` → clean-room `grade` → `score_run` →
   `SqliteRunStore.save_run`): apply the edit in a fresh snapshot → capture diff
   (`run_diffed`) → regression + hidden tests → score → persist (`run_graded`,
   `run_persisted`).
3. Stamp `runs.job_id` for the row just written (looked up by the unique
   `(agent, task_id, idx, task_version)`).
4. Update progress counters and emit `progress`.

**Task-dir resolution (verified caveat).** `eval_persist.py` loads tasks with
`load_task(_ROOT / "tasks" / task_id)`, assuming the directory name equals the task id. The
manifest carries an explicit `dir`, so when the wizard lets the user pick arbitrary tasks
the worker must resolve each path from `manifest[i].dir` (falling back to `tasks/<id>`) —
the UI passes task **ids**, the worker owns dir resolution.

**Resumability is inherited, not rebuilt.** `eval_persist` already skips
`(agent, task_id, idx)` units already persisted at the current task version, so a worker
restart (or a retry job, §6.1) continues instead of duplicating runs.

### 5.3 Cancel (between runs only)

The API sets `cancel_requested = 1`. The worker checks it **between runs** — never
mid-grade, so a clean-room evaluation always finishes and persists coherently. On observing
it, the worker sets `status='canceled'`, `finished_at`, emits `job_canceled`, and stops.
In-flight model generation is not force-killed; cancel takes effect at the next run boundary
(seconds-to-one-run of latency, surfaced in the UI).

### 5.4 Failure handling

- A per-run **infra failure** (model server unreachable, etc.) is recorded as the existing
  `infra_failure` status → counted in `voided_runs`, **excluded from `n`** (existing
  behavior), does **not** fail the job. Emits a `log`/`error` event and continues.
- A **fatal** error (bad params, DB unwritable, backend gone for the whole job) sets
  `status='failed'`, `error_message`, emits `job_failed`, and stops.
- A job with no fatal error transitions to `succeeded` once all planned runs are done (some
  may be voided); `finished_at` set, `job_done` emitted.

### 5.5 SQLite concurrency discipline

The current store opens `journal_mode=delete` and runs `executescript` (idempotent DDL) on
every open — so opening the DB is itself a small write. For the product app:

- **Enable WAL once** (`PRAGMA journal_mode=WAL`) and set `PRAGMA busy_timeout=5000` on
  every connection. WAL lets the explorer/API read while the worker writes.
- **Write ownership (documented, not magic):**
  - `runs` / `run_scores` / `diffs` / `test_results` — **worker-only writes**; API reads.
  - `job_events` — **worker-only writes**; API reads (SSE/poll).
  - `evaluation_jobs` — created by the API, status transitions by the worker, the
    `cancel_requested` flag by the API. Shared, but writes are tiny and touch distinct rows.
  - `app_settings` — API-only writes.
- This is **not** a strict single-writer model; it is WAL + short serialized writes, which
  suffices for a single-user local tool. The API should ensure the schema exists once at
  startup, then serve reads on read-only connections (`file:reports/runs.sqlite?mode=ro`) so
  the read path never triggers the store's DDL-on-open write.

---

## 6. API & SSE contract

The same FastAPI app as the explorer. All routes under `/api/v1`. Errors are JSON:
`{ "error": { "code": "...", "message": "...", "detail": {...}? } }`.

### 6.1 Job routes

| Method · path | Purpose | Notes / errors |
|---|---|---|
| `POST /jobs` | Create a job | Validates params (§6.2); inserts `queued`; returns `{id, status, created_at, total_runs}`. `422 validation_error`. |
| `GET /jobs` | List jobs | `?status=` filter; newest first; job summaries + progress. |
| `GET /jobs/{id}` | Job detail | Full row + progress + params. `404 job_not_found`. |
| `POST /jobs/{id}/cancel` | Request cancel | Sets `cancel_requested=1` if `queued`/`running`. `409 job_terminal` otherwise. |
| `POST /jobs/{id}/retry` | Retry a terminal job | `201` with a **new** job cloning `params_json`; resumes remaining work via `eval_persist` skip logic (§5.2). `409 job_not_terminal` if still active. |

### 6.2 Job params (POST /jobs body)

```jsonc
{
  "backend": { "kind": "ollama" | "openai_compat",
               "base_url": "http://host.docker.internal:11434",
               "api_key": "…optional, local server only — see caveat…" },
  "model":   "qwen2.5-coder:7b",            // one pulled local model per job (v1)
  "name":    "qwen2.5-coder:7b",            // agent label (defaults to model id)
  "tasks":   "all",                          // or ["fix-binary-search", "toposort", …]
  "repeats": 5,
  "base_seed": 42,
  "temperature": 0.8,
  "request_timeout_s": 180
}
```

Defaults match `eval_persist.py` (`temperature=0.8`, `base_seed=42`). Validation: `model`
present on the backend (cross-checked via `/backends/verify`); `tasks` is `"all"` or a
subset of the 24 manifest ids; numeric ranges sane. `total_runs = n_tasks × repeats`.
`repeats < 5` is allowed but the explorer will flag those cells **provisional** (the UI
surfaces that consequence; it computes nothing).

> **Verified wiring caveat — OpenAI-compat `api_key`.** The current OpenAI-compatible
> client (`runner/afa_runner/agents_openai.py`) sends **no `Authorization`/`Bearer`
> header** (none exists anywhere in `runner/`). So a key field is non-functional today. In
> v1 the field is **disabled with a note** ("local servers that require a token aren't
> supported until the OpenAI-compat client adds an auth header"); wiring it is a small,
> separate change (add `Authorization: Bearer …`). Ollama needs no key.

### 6.3 SSE — `GET /jobs/{id}/events`

`Content-Type: text/event-stream`. Streams `job_events` for the job from a cursor, oldest
first, then tails new events until a terminal event closes the stream:

```
id: 12
event: run_graded
data: {"agent":"qwen2.5-coder:7b","task_id":"toposort","idx":3,"final_score":0.0,"functional_pass":false,"status":"valid"}

: keepalive
```

- **Resume:** the client's `Last-Event-ID` (the last `seq`/`id` it saw) makes the server
  replay from there — a dropped connection loses nothing. Replay is `WHERE id > ?` and is
  idempotent on the client (it ignores ids ≤ what it already applied).
- **Heartbeat:** a `:` comment every ~15s keeps intermediaries from closing an idle stream.
- **Terminal:** after `job_done` / `job_failed` / `job_canceled`, the server sends that
  event and closes.
- **Poll fallback:** `GET /jobs/{id}/events?since=<id>` returns the same events as a JSON
  array, applied through the **same client reducer**, so SSE and polling render identically.

### 6.4 Settings & backend verification

| Method · path | Purpose |
|---|---|
| `GET /settings` | Persisted defaults; `api_key` redacted to `api_key_present`. |
| `PUT /settings` | Upserts `app_settings` (id=1). Validates types/ranges; does **not** check reachability (that's Verify), so saving never blocks on a server being up. |
| `POST /backends/verify` | Net-new **read-only** probe: Ollama → `GET {base_url}/api/tags`; OpenAI-compat → `GET {base_url}/v1/models`. Returns reachability + locally available models + latency. A connection check only — never constructs an agent or runs a task. `502 backend_unreachable` on failure. |

### 6.5 Reports & export

| Method · path | Purpose |
|---|---|
| `POST /reports/regenerate` | Reuses `examples/report_combined.build_report` to rewrite `reports/leaderboard.html` from the current DB; returns the path + summary. No new math. |
| `GET /export?format=json\|csv\|html[&job_id=…]` | Downloads leaderboard/runs data (all, or scoped to one job). `html` = the regenerated report; `json`/`csv` = rows. Read-only dumps of persisted data. |

---

## 7. UI (Vite React SPA)

One SPA, React Router, single API base URL (same origin in Compose; `VITE_API_BASE` in
dev). One API client module owns the base URL and the `{error:{code,message,detail}}`
envelope; the URL is the state; the product routes **extend** the explorer's route table
rather than replacing it.

### 7.1 New-Evaluation wizard (`/new`, step in `?step=`)

A five-step stepper; forward progress is gated on validity. It collects only the runner's
constructor knobs — never task-owned grading parameters (timeout, protected/editable paths,
suites, weights, `version`), which come from `task.json` and are shown **read-only**.

1. **Backend** — Ollama or OpenAI-compat local; base URL; **Verify & list models**
   (`/backends/verify`) — the only way to advance. (The api-key field is disabled-with-note
   per §6.2.)
2. **Model** — chosen from the verified list (never free-text). Agent `name` defaults to the
   model id; warns (doesn't block) on a label collision since the leaderboard pools by `agent`.
3. **Tasks** — full 24-task pack or a subset, from `tasks/manifest.json`, with
   activity/scale/difficulty/domains shown; per-task expand shows the read-only task-owned
   values. Selecting zero blocks Next.
4. **Run params** — repeats `N`, base seed, temperature, request timeout (prefilled from
   settings); a note clarifies request timeout ≠ the task's wall-clock `timeout_s`.
5. **Review & launch** — summary + computed `total_runs = n_tasks × N`; `POST /jobs` →
   navigate to `/jobs/{id}` (the live monitor). A resume info-chip shows how many matching
   runs already exist and will be skipped.

### 7.2 Settings (`/settings`)

Edit and persist the defaults the wizard prefills (`PUT /settings`), and re-verify backends
(same `/backends/verify`, same Connected/failed chip). Defaults only — editing never alters
past jobs or persisted runs.

### 7.3 Live monitor (`/jobs/:jobId`)

Subscribes to the SSE stream via a reducer-backed hook:

- Overall progress (`completed/total`) with passed / failed / **voided (infra, excluded from
  n)** broken out and labeled.
- A virtualized, append-only per-run log keyed by `(task_id, idx)` (so replay on reconnect
  updates rows, never duplicates), each row showing `PASS` / `fail` / `VOID(infra)`.
- Current-run card with an optimistic sub-stage indicator (see caveat below).
- **Cancel** (disables after one click → "Cancelling…") and, once terminal, **Retry**.
- Disconnect → reconnect with `Last-Event-ID` and capped backoff; on exhaustion, polling
  fallback (`?since=`) through the same reducer. Counters are recomputed from the keyed map
  on every apply, so duplicates can't inflate them.

> **Honest sub-stage timing.** `run_once` is one atomic call; the worker observes the
> diff/graded/scored fields only *after* it returns. The recommended worker emits those as
> one post-return burst, so the sub-stage indicator animates optimistically but the
> substantive stages land together. The UI must not imply live mid-`run_once` streaming.

### 7.4 Jobs history (`/jobs`)

A table of all jobs (newest first) with status chips, scope (`tasks × repeats`), progress,
duration, and actions: **Monitor** (always), **Results** (when runs persisted), **Retry**
(when terminal/failed/has-voids). Client-side sort/filter only; no re-ordering of server
order beyond the user's chosen sort.

### 7.5 Results (`/jobs/:jobId/results`) — embedded explorer

Reuses the read-only explorer views (overview → domain matrix → cell → run drill-down),
**scoped to this job's runs** via `runs.job_id`, plus a top job-summary strip (the worker's
`p_hat = c/nv` headline, labeled as the worker's summary). All explorer honesty rules carry
through unchanged: kernel ranking order (never re-sorted), Wilson bars, the three-state
capture chip (synthetic / captured / not captured), `q_components={}` (Q=1.0 offline),
per-gate "not captured," and the mixed-version refusal (a multi-version cell returns
`409 mixed_version_pool` and the UI shows the refusal, never a blended number). Implemented
by reusing the explorer view components with a `scope={agent, task_ids}` prop — not a fork.

---

## 8. Report regeneration & export

Thin wrappers over existing code, never new computation:

- **Regenerate** → `report_combined.build_report()` rewrites `reports/leaderboard.html` from
  the live DB (useful after a Retry fills in voided runs). Same version-pooling refusal
  applies. The app relays the kernel's policy; it does not average around it.
- **Export** → `json`/`csv` of the runs (optionally `?job_id=`), or the regenerated `html`
  report, as a download. Read-only dumps; no re-grade, no re-score.

---

## 9. Docker Compose & run model

One command — `docker compose up` — brings up the local app.

```
services:
  api:     uvicorn afa_api.main:app   → :8000   (explorer + job/SSE/settings API)
  worker:  python -m afa_api.worker             (claims & runs jobs)
  web:     built React SPA, served statically (or behind api) → :8080
  ollama:  (OPTIONAL) ollama/ollama   → :11434  — opt-in Compose profile
volumes:
  - ./reports:/app/reports            # shared runs.sqlite (WAL) across api + worker
env:
  - OLLAMA_BASE_URL=http://host.docker.internal:11434   # default: use HOST Ollama
healthchecks: api /healthz; worker heartbeat row; ollama /api/tags
```

- **Model backend, two ways:** by default talk to a **host** Ollama
  (`host.docker.internal`) using models you've already pulled; an **optional** bundled
  `ollama` service is available behind a Compose profile.
- **Offline caveat (honest):** "offline-first" holds *after* a model is pulled at least
  once; the first pull needs network. Surfaced in the wizard's verify step.
- **Dev story:** Vite dev server (:5173) + `uvicorn --reload` + the worker, all pointed at a
  local `reports/runs.sqlite`. No container needed for development.
- Bind to localhost; no public ports by default.

---

## 10. Security scope & honesty boundaries

Stated plainly so nothing is over-claimed:

- A **trusted, single-user, local** tool. **No authentication**; binds to localhost.
- The clean-room grader runs **agent-generated code with host privileges** via
  `LocalSandbox`. We make **no claim** of isolation or safety against untrusted or
  adversarial agents/tasks. **Do not run untrusted models or untrusted tasks.**
- A hardened `DockerSandbox` (real isolation for untrusted agents) is **out of scope and
  explicitly unclaimed**. The clean room's protections (only the diff is applied to a
  pristine snapshot; auto-executed files like `conftest.py` are always-protected) are about
  **grading integrity for trusted runs**, not a security boundary against a malicious agent.
- Running Compose does not change this: containerization here is **packaging**, not a
  security sandbox for agent code.

---

## 11. Build roadmap (Phases 1–6)

Phases 1–2 are delivered by [OBSERVABILITY_FRONTEND_DESIGN.md](OBSERVABILITY_FRONTEND_DESIGN.md);
this doc delivers 3–5; 6 is optional.

| Phase | Scope | Ship-gate (done = verified) |
|---|---|---|
| **1** | Read-only `afa_api/serialize.py` + FastAPI read endpoints + React dashboard (leaderboard + domain matrix) over the current `runs.sqlite`. | Three-way check passes (API == raw SQL == report functions) for an anchor cell; dashboard renders the 600-run leaderboard + matrix. |
| **2** | Cell + run drill-down (captured vs "not captured"). | A captured cell shows diff + per-test rows; a legacy cell shows "not captured"; synthetic baselines show the bookend state. |
| **3** | `evaluation_jobs` / `job_events` / `app_settings` tables + worker + job/SSE API (no UI yet — drive via curl/tests). | A job created via `POST /jobs` runs to completion, persists real runs (stamped `job_id`), streams events over SSE, survives a worker restart (resume); cancel works between runs. |
| **4** | React New-Evaluation wizard + live monitor + settings. | A user launches a job from the wizard, watches live progress, cancels/retries; SSE reconnect works. |
| **5** | Docker Compose one-command local app. | `docker compose up` then a full wizard → run → results flow works against a host Ollama, offline after the model is pulled. |
| **6** | *(optional)* Static / Vercel evidence site (baked read-only bundle). | Deferred — see the explorer doc's Appendix A. |

---

## 12. Open risks & caveats

- **SQLite write contention edges.** WAL + `busy_timeout` covers a single-user app, but a
  long worker write overlapping an API write can still hit a transient `SQLITE_BUSY`; writes
  must be short and retried.
- **Store DDL-on-open is a write.** The existing store runs `executescript` on open; the
  read path must use a read-only connection after first-time schema setup, or "API only
  reads" is false.
- **Cancel granularity.** Cancel takes effect only at a run boundary; an in-flight model
  generation finishes first. Intentional (coherent persistence), but a latency, not an
  instant stop.
- **Retry / resume granularity.** Resume relies on `eval_persist` skipping already-persisted
  `(agent, task_id, idx)` units. If a *voided* (`infra_failure`) run was persisted, a retry
  may skip it rather than re-attempt it; forcing a true re-run would require deleting those
  rows first. Confirm `eval_persist`'s skip predicate before relying on this.
- **OpenAI-compat key unwired** (§6.2) — verified: no auth header is sent today; the key
  field is disabled-with-note until the client is extended.
- **Host-Ollama dependency + first pull.** "Offline" holds only after the first pull, which
  needs network.
- **Thin per-run provenance.** Seeds/transcripts aren't uniformly captured across the
  existing 600 runs; new job runs should capture richer provenance going forward.
- **No auth.** Anyone with local access can launch jobs and read results — fine for a
  trusted single-user tool, not for shared hosting.
- **80 legacy runs lack patch/test artifacts.** Inherited from the explorer doc; the results
  view shows "not captured" for them.
