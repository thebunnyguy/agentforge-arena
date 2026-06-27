# AgentForge Arena — Observability Frontend Design

A single specification for the **read-only observability data explorer** over the AgentForge Arena evaluation results: a Vite React single-page app (overview → domain matrix → cell → run drill-down) talking to a live local FastAPI, both backed by one pure serializer over the frozen kernel and the persisted SQLite store.

This document covers the **read-only data explorer only**. It is **Phase 1 + Phase 2** of the shared implementation roadmap (read-only API + dashboard; cell/run drill-down). The job/evaluation backend, the worker, the New-Evaluation wizard, the live monitor, and Docker Compose packaging are out of scope here and live in the roadmap's later phases (§10). A static/Vercel "evidence site" is explicitly deferred to **Appendix A** (roadmap Phase 6, optional).

This spec supersedes earlier working notes on the API contract, the information architecture, the client controls, the verification plan, and the build order. Where those notes conflicted (route shape, response envelope, pagination, run identity in URLs), the conflict is resolved inline in favour of the design that keeps the frontend a **thin projection** with **no statistics in the browser** — the binding HARD CONSTRAINTS.

---

## 1. Overview & goals

The frontend is a **thin, read-only projection** over the FROZEN kernel (`afa_kernel`) and the persisted `reports/runs.sqlite` (600 runs = 5 models × 120; 24 tasks; 3 task versions). It computes **no statistics**. Every number it shows is either:

- a verbatim field from a frozen kernel dataclass produced by one of four report functions — `leaderboard()`, `domain_profile()`, `task_aggregate()`, `format_leaderboard()` — or
- a raw column read directly from the persisted DB rows (`runs`, `run_scores`, `diffs`, `test_results`).

A **live local FastAPI is always present** in this delivery: the React SPA is served from and fetches from a FastAPI process on the same machine, reading the same SQLite file. There is no "the API might be missing" mode to degrade to. (The optional baked-bundle evidence site in Appendix A is a separate, deferred artifact, not a runtime mode the SPA branches on.)

Goals, in priority order:

1. **Honesty is the product.** Foreground Wilson confidence intervals, provenance, gate breakdowns, provisional/deterministic/bimodal flags, synthetic baselines as explicit anchors, and the captured-vs-"not captured" data gap. A small sample must *look* uncertain; a suppressed domain must *look* suppressed, not low.
2. **One source of truth for math.** All scoring/aggregation/confidence/ranking lives only in the Python kernel. The web layer never re-implements it — not in TypeScript, not "as an approximation," not for any view.
3. **One serializer.** A single pure Python module turns the kernel/report layer into JSON; the live FastAPI is its only consumer in this doc. The frontend is a thin projection of that one shape.
4. **Offline-first.** Zero external network calls, no paid LLM APIs, no LLM-as-judge anywhere in the stack or its tests. The API and SPA run entirely on the local host.
5. **Three-way verifiable.** Every served value is checkable against raw SQL and against the in-process report functions, on the same live snapshot.

### Non-goals (this doc)

- **No writes through this surface.** The explorer is GET-only. Launching/re-grading evaluations is a separate worker concern (roadmap Phase 3–4), not a data-explorer control.
- **No authentication/authorization** (see Open risks). Single-user, trusted, local tool.
- **No per-component quality breakdown** — `q_components` is not persisted in v0.1 (reconstructed as `{}`), and the UI renders it as unavailable rather than fabricating.
- **No static/SSG delivery in this doc.** A baked read-only bundle for public hosting is deferred to Appendix A (roadmap Phase 6, optional).
- **No frontend statistics.** No re-derivation of Wilson bounds, pass@k, Kish `n_eff`, `conservative_continuous`, `stability`, `pooled_pass_rate`, or LCB ranking in JS.

### Trust model (scope boundary)

This is a **trusted, single-user, local** tool. The clean-room grader runs agent-generated code with host privileges via `LocalSandbox`; the explorer only *reads the results of those runs*. No untrusted-agent or malicious-agent isolation is claimed anywhere; do not run untrusted models/tasks. A hardened `DockerSandbox` is out of scope and unclaimed. The explorer itself touches no sandbox and executes no agent code — it is a pure read path over already-persisted rows.

---

## 2. Architecture — one serializer, a React SPA over a live FastAPI

### 2.1 The invariant: ONE serializer

There is exactly one piece of code that turns the kernel/report layer into JSON: a pure Python module **`afa_api/serialize.py`** exposing functions that take a `RunStore` (+ the parsed `manifest.json`) and return JSON-ready `dict`s. It owns the wire shape; nothing else shapes JSON. It does **field-by-field projection only** — no math, no derived values.

```
                    afa_api/serialize.py          ← THE serializer (pure projection)
                    ├─ build_overview(store, manifest)       → leaderboard() + summary() + subtitle
                    ├─ build_leaderboard(store, task_id?)    → leaderboard(store, task_id=...)
                    ├─ build_domains(store, agent)           → domain_profile(store, agent, task_domains)
                    ├─ build_cell(store, agent, task_id)     → task_aggregate() + per-run rows
                    ├─ build_run(store, agent, task_id, idx) → RunRecord + raw SQL for patch/tests
                    └─ build_meta(store, manifest)           → task pack, versions, observability
                          │
                    afa_api/main.py  (FastAPI, LIVE local)
                    imports serialize.py from route handlers,
                    runs it per request over the live SQLite DB,
                    returns the dicts as HTTP responses
                          │
                    web/  (Vite React SPA — fetch() over /api/v1/...)
```

The FastAPI route handlers import `serialize.py` and run it per request over the live DB. Every served value is a pure function of `(DB content, path params)`, so identical inputs yield byte-identical output — which is exactly what makes the three-way verification (§9) meaningful: there is exactly one projection to verify.

> The serializer is the load-bearing reuse. (Appendix A reuses this *same* module to bake a static bundle, with no second projection. That second consumer is deferred; the serializer is not.)

`build_domains` is named for its single-agent scope: it returns **one agent's** `list[DomainScore]`. The overview's full model × domain *matrix* is assembled **client-side** from N such single-agent calls (§4.3/§6.2) — the serializer never returns a matrix.

### 2.2 The two stores (load / refusal / baseline sequence)

`afa_api/main.py` reuses the load logic of `examples/report_combined.py` at startup, in this exact order:

1. Open the on-disk store; for each of the 5 `MODELS` call `disk.load_runs(agent=...)`; accumulate `evaluated_versions[task_id]` and `cell_versions[(agent, task_id)]`; re-save each record into an in-memory store. Capture `disk.summary()` for the observability header.
2. **Mixed-version refusal first.** Build `mixed_cells = {cell: sorted(vs) for cell, vs in cell_versions.items() if len(vs) > 1}`. If non-empty, raise `ValueError("refusing to pool multiple task versions: ...")` **before any aggregation or emission**. Dormant on the current DB (0 mixed cells; the 3 versions split *across* cells, never within one); surfaced as a hard error if a future DB violates it (§4.8 error model).
3. **Add synthetic baselines only after the refusal passes.** `oracle (synthetic baseline)` (always pass: `gate_product=1, t_hidden=1.0, q=1.0, final_score=1.0, functional_pass=True`, `+6/-0` lines) and `noop (synthetic baseline)` (always fail: all-zero, `files_changed=0`, true no-edit so `diff_exists` fails), `N=5` per task at each task's **current** version. They cannot create a mixed cell. The live leaderboard shows oracle n=120 p̂=1.000 (top anchor) and noop n=120 p̂=0.000 (bottom anchor) as the honest **deterministic bookends**.

**Two stores, bound to consumers explicitly.** The sequence yields two stores with different contents, and the design binds each endpoint to one:

- **Disk store** (`reports/runs.sqlite`): the **600 real runs only**, zero synthetic rows. It is the source for the §4.5 `/run` direct-SQL read (real agents) and for `disk.summary()` (the observability header, `total_runs=600`, counting real rows only). The synthetic `save_run` calls in step 3 target the in-memory store *after* the disk store's read is done.
- **In-memory store** (post-baseline): **600 real + 240 synthetic = 840 runs** (oracle n=120, noop n=120). All **aggregation** endpoints run here: `/overview`, `/leaderboard`, `/domains/<agent>`, and both the `aggregate` and `runs` blocks of `/cell` — i.e. `leaderboard()`, `domain_profile()`, `task_aggregate()`, plus the per-run list via `load_runs`. Synthetic cells therefore resolve and stay clickable.

The synthetic `save_run` rows carry score primitives (the all-pass / all-fail constants above) but **no GradeReport** — `patch_text` is `NULL` and there are zero `test_results`. To keep them distinct from a legacy "not captured" real row, every synthetic `RunRecord` the serializer emits carries `synthetic: true` (see §4.4/§4.5); the UI renders a third, explicit **"synthetic baseline — deterministic bookend, no real patch/tests"** state, never conflated with either "captured" or legacy "not captured."

This load-time work happens once at process boot; the running SPA simply fetches the resulting projections live from the local API.

### 2.3 Connection lifetime, journal mode, and read-only opens

The current `SqliteRunStore` (`runner/afa_runner/store.py`) is a **writer** built for the worker: its constructor does `sqlite3.connect(str(path))` (read-write, default `check_same_thread=True`) and runs `executescript(SQLITE_SCHEMA)` + `commit()` (CREATE TABLE/INDEX IF NOT EXISTS) on every open. There is no read-only open path, and the connection has thread affinity. The API cannot reuse this as-is; this section pins how the API opens the DB. (`report_combined.py` constructs the same writer store, so its load helper is **not** itself a read-only open — the API must add the read-only path below.)

**Journal mode is `delete`, not WAL — and the API will not flip it.** Verified against the live DB: `PRAGMA journal_mode` reports `delete`, and nothing in the store or the design ever issues `PRAGMA journal_mode=WAL`. WAL is a persistent per-DB property that must be set **once on a writable connection**; a read-only connection cannot change it. This design therefore does **not** assume WAL anywhere. Two consequences are stated honestly rather than papered over:

- **Reader/writer contention is real in delete-journal mode.** While the worker holds its (brief, per-record) write transaction, it takes an EXCLUSIVE lock that blocks **all** readers — including the API — for the duration of that transaction. The API's reads therefore *do* block during the worker's writes; they are not concurrent. The mitigation is a `PRAGMA busy_timeout` (e.g. 5000 ms) on every API connection so a read **waits out** the writer's short transaction instead of failing with `SQLITE_BUSY`. This is acceptable because writes are tiny append-only inserts and the explorer is a single-user local tool.
- **If WAL is wanted later, it is an explicit, owned, one-time step.** Enabling WAL is a roadmap Phase 3 concern (the worker, the only writer), not this read-only surface: the **worker** would issue `PRAGMA journal_mode=WAL` once on its writable connection at first open, it persists in the DB file thereafter, and a ship-gate would verify `PRAGMA journal_mode == 'wal'` on the live DB. Until that lands, the concurrency story is exactly the "reads block briefly during the worker's write transactions; `busy_timeout` absorbs the wait" model above. This doc claims no WAL guarantee.

**The API opens a fresh, short-lived, read-only connection per request — never the worker's connection.** Because `sqlite3` connections have thread affinity (`check_same_thread=True` by default) and FastAPI/uvicorn dispatches sync route handlers and SSE tails across a threadpool, a single boot-time connection reused across request threads raises `sqlite3.ProgrammingError: SQLite objects created in a thread can only be used in that same thread`. The design avoids this entirely: it does **not** share a long-lived store connection across handlers. Instead:

- A small **new** read-only open capability is added (a thin helper, not a change to the writer store): `sqlite3.connect("file:" + path + "?mode=ro", uri=True)`, which opens read-only and **skips** `executescript`/`commit`, so the API never runs DDL and never creates tables on a fresh/empty file. On every such connection the helper sets `busy_timeout`.
- Each request handler (and each SSE tail, if any) opens its **own** read-only connection on its own thread, projects, and closes it. Connection lifetime = request lifetime. There is no boot-time shared connection.
- What *is* loaded once at boot is the cheap, immutable, in-memory scaffolding: the parsed `manifest.json` (`task_domains`) and the synthetic-baseline rows assembled per §2.2 into an in-memory store used only by the aggregation endpoints. The per-request read-only disk connection is what touches `reports/runs.sqlite`.

So "load once at boot, project per request over the live DB" is reconciled precisely: the *projection logic and manifest* are loaded once; the *DB connection* is per-request, read-only, and thread-local. The aggregation endpoints read the boot-time in-memory store (which holds the 600 real + 240 synthetic rows already loaded in step 1–3, so they need no per-request disk connection); only `/run`'s real-agent SQL (§4.5) opens a per-request read-only disk connection.

---

## 3. Scope (read-only) & non-goals

### 3.1 What this surface is

A **read-only data explorer** over the persisted snapshot. It serves projections of already-persisted rows and of the report functions computed in Python at request time over the live DB. Concretely:

- the all-pooled leaderboard and per-`task_id` leaderboard scopes;
- the model × domain matrix;
- per-cell aggregates (Wilson bounds, pass@k, stability, `conservative_continuous`, the S-distribution);
- per-run detail (patch diff + per-test results, or the honest "not captured" / synthetic states);
- the synthetic oracle/noop bookends;
- the provenance/observability header and the (dormant) mixed-version notice.

Every one of these is a pure projection of the snapshot through the frozen kernel and the one serializer.

### 3.2 What is out of scope here (covered by other phases)

What is **not** part of this read-only explorer:

1. **A new eval run / new model / new repeats** — executing an agent and grading it is a live pipeline action driven by the worker (roadmap Phase 3–4), not a projection. It reuses `examples/eval_persist.py` + `afa_runner.pipeline` + the clean-room grader and adds **no scoring math**; it is not a data-explorer control.
2. **Re-scoring under a new `formula_version`** — the kernel recomputes and appends new `run_scores` rows (append-only). New scores appear in the explorer simply because they are in the DB; the explorer never triggers the recompute.
3. **`q_components` detail** — not persisted in v0.1; the API serves `q_components: {}` faithfully and the UI shows per-component q as unavailable.
4. **Writes of any kind** — the explorer is GET-only; the only mutating capability in the product (launching/monitoring evaluations) is a later-phase concern. The WAL enablement noted in §2.3 is likewise a worker concern, not this surface.
5. **A static/SSG public site** — deferred to Appendix A.

The explorer answers as of the live DB at request time; because the local API reads the same `reports/runs.sqlite` that the worker appends to, new runs become visible after an API restart (or a future explicit reload hook) without any rebuild step (§11.5).

---

## 4. API contract (read-only endpoints + JSON shapes)

All shapes below are verbatim projections of the frozen dataclasses; field names are the dataclass attribute names exactly, no field invented, no value recomputed.

**Conventions.** Base path `/api/v1`. All responses `application/json; charset=utf-8`. **GET only** — no mutating verbs on this surface. CORS read-only. **No `{data, page}` envelope, no pagination** — single-resource objects are returned directly. Aggregation surfaces are tiny by construction (5 agents + 2 synthetic, 24 tasks, ≤~30 runs/cell); the kernel returns complete, ordered lists and the frontend **must not slice or re-order them**. Run identity is `(agent, task_id, idx)` — **never `runs.id`** (an internal SQL lookup detail only). Agent path segments are percent-encoded (`:`, `.`, spaces): `qwen2.5-coder%3A7b`, `oracle%20(synthetic%20baseline)`. Agent and task lists are not hardcoded in the frontend — they come from `/overview` / `/meta`.

**Shared serializer rules:**

- Enums serialize to their `.value` string (`RunStatus` → `"valid" | "timeout" | "agent_error" | "infra_failure"`).
- `rank_low`/`rank_high` serialize to JSON `null` when the agent is provisional.
- `patch_text` serializes to JSON `null` when the DB column is `NULL`.
- `pass_at_k` keys are stringified ints (`"1"`, `"2"`, …).
- `q_components` is a JSON object, always `{}` from the SQLite store in v0.1.
- Floats carry full kernel precision on the wire; any rounding for display happens only in the browser.

### Endpoints (exact paths)

| Live route | Serializer call |
|------------|-----------------|
| `GET /api/v1/overview` | `build_overview` |
| `GET /api/v1/leaderboard[?task_id=<id>]` | `build_leaderboard` |
| `GET /api/v1/domains/<agent>` | `build_domains` |
| `GET /api/v1/cell/<agent>/<task_id>` | `build_cell` |
| `GET /api/v1/run/<agent>/<task_id>/<idx>` | `build_run` |
| `GET /api/v1/meta` | `build_meta` |
| `GET /api/v1/manifest.json` | snapshot descriptor (§4.6) |

`build_domains` returns a **single agent's** `list[DomainScore]`; the model × domain matrix is the client's assembly of one such call per agent (§4.3/§6.2), so the serializer never returns a matrix.

`format_leaderboard()` is intentionally **not** exposed as JSON — it is pure CLI text formatting; the web layer renders the structured `/leaderboard` rows itself. It may optionally back a `GET /api/v1/leaderboard.txt` returning `text/plain` (`format_leaderboard(leaderboard(store))`) — flagged optional, not core.

### 4.1 `GET /api/v1/overview`

Landing payload: the all-tasks-pooled leaderboard plus the provenance header. Wraps `leaderboard(in-mem)` + `disk.summary()` + the `report_combined` subtitle.

```jsonc
{
  "leaderboard": [ /* list[LeaderboardEntry], kernel ranking order */ ],
  "meta": { "subtitle": "Persisted DB data only: ...", "formula_version": "v0.1",
            "snapshot_id": "...", "version_notice": "" },
  "observability": { "total_runs": 600, "runs_with_patch": 520,
                     "runs_with_test_results": 519, "test_result_rows": 6322,
                     "first_created_at": "2026-06-18 ...", "last_created_at": "2026-06-22 ..." }
}
```

`observability` field names are exactly `RunStoreSummary`'s and come from `disk.summary()` (real rows only; `total_runs=600`).

### 4.2 `GET /api/v1/leaderboard[?task_id=<id>]`

Wraps `leaderboard(store, task_id=...)` (keyword-only `task_id` mirrored as the query param). `task_id` absent → all tasks pooled; present → single-task scope; the kernel re-ranks. Unknown `task_id` → 404 `task_not_found`. Returns the bare `list[LeaderboardEntry]` in kernel ranking order — **no envelope**, no echoed scope (the scope *is* the request's own `task_id` query param). The list is already ordered by `wilson_low`; provisional agents present with `null` ranks; synthetic baselines appear as ordinary rows.

```jsonc
[
  { "agent": "qwen2.5-coder:7b", "pass_rate": 0.633, "wilson_low": 0.544,
    "wilson_high": 0.714, "n": 120, "provisional": false,
    "rank_low": 1, "rank_high": 2 },
  { "agent": "some-sparse-agent", "pass_rate": 0.0, "wilson_low": 0.0,
    "wilson_high": 0.0, "n": 0, "provisional": true,
    "rank_low": null, "rank_high": null }
]
```

Each element's fields are exactly `LeaderboardEntry`'s: `agent, pass_rate, wilson_low, wilson_high, n, provisional, rank_low, rank_high` — no wrapper keys. The frontend renders in returned order and **never re-sorts by `pass_rate`**. (The `pass_rate 0.633` shown for `qwen2.5-coder:7b` is its **all-tasks-pooled** value; per-cell pass rates for the same agent differ — e.g. its `escape-html` cell is a perfect 5/5, §9.1 — and that is expected, not a contradiction.)

### 4.3 `GET /api/v1/domains/<agent>`

Wraps `domain_profile(store, agent, task_domains)`, where `task_domains` is built from `manifest.json` (`task_id -> [(domain, weight), ...]`, e.g. `escape-html -> [("security",1.0),("backend",0.5)]`). Unknown `agent` → 404 `agent_not_found`. Returns the agent's `list[DomainScore]`, sorted by domain name (per the report function). This is a **single-agent** serializer (`build_domains`); the matrix is assembled client-side.

```jsonc
{ "agent": "qwen2.5-coder:7b",
  "domains": [
    { "domain": "async-concurrency", "pooled_pass_rate": 0.42, "n_eff": 18.7,
      "wilson_low": 0.27, "wilson_high": 0.59, "stability": 0.71,
      "n_tasks": 2, "n_runs": 20, "displayable": false },
    { "domain": "backend", "pooled_pass_rate": 0.68, "n_eff": 41.2,
      "wilson_low": 0.55, "wilson_high": 0.79, "stability": 0.80,
      "n_tasks": 7, "n_runs": 70, "displayable": true }
  ] }
```

Fields are exactly `DomainScore`'s: `domain, pooled_pass_rate, n_eff, wilson_low, wilson_high, stability, n_tasks, n_runs, displayable`. The overview's model × domain matrix is assembled client-side by fetching one `domains/<agent>` per agent.

### 4.4 `GET /api/v1/cell/<agent>/<task_id>`

The single-cell drill-down: the cell aggregate plus the ordered per-run list. 404 `agent_not_found` / `task_not_found`; 404 `cell_empty` if the pair has zero rows. **Both** the `aggregate` block and the `runs` block read the **in-memory store** (post-baseline, §2.2), so synthetic cells (oracle/noop) resolve identically to real cells. The `aggregate` block wraps `task_aggregate(store, agent, task_id)` (the honest whole-cell number) and projects **every `AggregateResult` field** (all 19 fields of the frozen dataclass). The `runs` block comes from `store.load_runs(task_id, agent)` (ordered by `idx`), projecting per-run `RunRecord` + nested `RunScore`. Because `load_runs` does **not** select `patch_text`/`test_results`, each run row carries a `captured` boolean (`true` iff `diffs.patch_text IS NOT NULL`) so the UI knows whether the run drill-down will have patch/tests before the user clicks. Synthetic rows additionally carry `synthetic: true`.

```jsonc
{ "agent": "qwen2.5-coder:7b", "task_id": "fix-binary-search",
  "aggregate": {            // every AggregateResult field (all 19)
    "n_valid": 5, "n_pass": 4, "pass_rate": 0.8, "wilson_low": 0.376, "wilson_high": 0.964,
    "mean_s": 0.79, "median_s": 0.85, "min_s": 0.0, "max_s": 0.95, "std_s": 0.34,
    "stability": 0.32, "conservative_continuous": 0.41, "timeout_rate": 0.0,
    "infra_void_rate": 0.0, "reliability": 1.0,
    "pass_at_k": { "1": 0.8, "2": 0.9, "3": 0.95, "4": 0.99, "5": 1.0 },
    "deterministic": false, "bimodal": true, "provisional": false },
  "runs": [
    { "idx": 0, "task_version": "1.0.1", "status": "valid", "duration_ms": 18342,
      "transcript_hash": "sha256:9f...", "files_changed": 1, "lines_added": 6,
      "lines_removed": 2, "captured": true, "synthetic": false,
      "score": { "status": "valid", "gate_product": 1, "t_hidden": 1.0, "q": 1.0,
                 "q_components": {}, "final_score": 1.0, "functional_pass": true,
                 "voided": false } }
  ] }
```

The `aggregate` block's 19 keys are exactly the `AggregateResult` field names: `n_valid, n_pass, pass_rate, wilson_low, wilson_high, mean_s, median_s, min_s, max_s, std_s, stability, conservative_continuous, timeout_rate, infra_void_rate, reliability, pass_at_k, deterministic, bimodal, provisional`. Run-row field names are the `RunRecord` fields `idx, task_version, status, duration_ms, transcript_hash, files_changed, lines_added, lines_removed`; nested `score` is the full `RunScore`. `captured` and `synthetic` are the only API-added fields (named distinctly so they can't be mistaken for kernel fields): `synthetic` is `true` only for oracle/noop rows.

### 4.5 `GET /api/v1/run/<agent>/<task_id>/<idx>`

Single-run detail including patch and per-test results. This is the **one endpoint that wraps no report function**, and its source depends on whether the agent is real or synthetic:

- **Real agents (5 models):** `load_runs` carries neither `patch_text` nor `test_results`, so the serializer reads them by a **direct, read-only, parameterized SQL select** against `reports/runs.sqlite` (the **disk store**) across `runs ⋈ run_scores ⋈ diffs ⟕ test_results`, located by `(agent, task_id, idx)`. This select runs on a **fresh per-request read-only connection** (`mode=ro`, with `busy_timeout`; §2.3) opened on the handler's own thread — never a shared boot-time connection. It does no statistics; the `RunScore` columns it shows are the persisted kernel facts. `runs.id` is resolved at lookup time (`SELECT id FROM runs WHERE agent/task_id/idx`) and used only as the internal join key — never returned as a wire field.
- **Synthetic agents (`oracle`/`noop`):** there is **no disk row** — the baselines exist only in the in-memory store (§2.2). The serializer reads the synthetic `RunRecord` + `RunScore` from the **in-memory store** (not disk SQL) and renders the explicit "synthetic baseline" state: `synthetic: true`, `captured: false`, `patch_text: null`, `test_results: "synthetic baseline — no patch/tests"` (distinct from both "captured" and the legacy "not captured" string). The deterministic score primitives are shown.

404 `run_not_found` if the `(agent, task_id, idx)` triple has no row in the store that backs it (disk for real agents, in-memory for synthetic). This is why synthetic baselines are **fully linkable** (§6.1) even though they have no disk-SQL witness.

> **Resolved contradiction (run identity).** One working note keyed run detail on the raw `runs.id` autoincrement and exposed `run_id` on the wire; the IA forbids `runs.id` in URLs and mandates the `(agent, task_id, idx)` triple (the only identity `RunRecord` exposes). **This spec keys the run endpoint and URLs on `(agent, task_id, idx)`.** `runs.id` is an internal SQL lookup detail used to fetch `diffs`/`test_results` for that triple; it is never a URL segment and never a required wire field.

```jsonc
{ "agent": "qwen2.5-coder:7b", "task_id": "fix-binary-search", "idx": 0,
  "task_version": "1.0.1", "status": "valid", "duration_ms": 18342,
  "created_at": "2026-06-21 14:03:11", "transcript_hash": "sha256:9f...",
  "files_changed": 1, "lines_added": 6, "lines_removed": 2, "touched_protected": false,
  "captured": true, "synthetic": false,
  "score": { "status": "valid", "gate_product": 1, "t_hidden": 1.0, "q": 1.0,
             "q_components": {}, "final_score": 1.0, "functional_pass": true,
             "voided": false, "formula_version": "v0.1" },
  "patch_text": "--- a/bsearch.py\n+++ b/bsearch.py\n@@ ...",
  "test_results": [
    { "suite": "hidden",     "test_name": "test_midpoint", "passed": true, "weight": 1.0 },
    { "suite": "regression", "test_name": "test_smoke",    "passed": true, "weight": 1.0 }
  ] }
```

Legacy variant: `"captured": false`, `"synthetic": false`, `"patch_text": null`, `"test_results": "not captured"`, score primitives still present. Synthetic variant (oracle/noop, from the in-memory store): `"synthetic": true`, `"captured": false`, `"patch_text": null`, `"test_results": "synthetic baseline — no patch/tests"`, with the deterministic baseline score primitives. Field names for real agents come straight from the raw tables: `runs`/`diffs` columns at top level; `score` = `run_scores` columns including the SQLite-named `q` (not Postgres `q_score`) and `formula_version`; `test_results[]` rows use SQLite `passed` (0/1 → JSON bool), `suite`, `test_name`, `weight`.

### 4.6 `GET /api/v1/meta`

Provenance for the report header — task pack, versions, capture coverage. Observability counts come from `store.summary()` (a stored-fact projection, not the kernel). Per-task version data is read from distinct `runs.task_version` and compared against the current version resolved from `manifest.json` (`version` key, else `tasks/<dir>/task.json`, fallback `1.0.0`) — the `_current_task_version` logic from `report_combined.py`. The `version_notice` is reproduced verbatim and is dormant (empty) on the current DB.

```jsonc
{ "task_pack": {
    "n_tasks": 24,
    "tasks": [ { "task_id": "escape-html", "dir": "tasks/escape-html",
                 "domains": [["security",1.0],["backend",0.5]],
                 "activity": "debugging-bugfix", "scale": "S", "manual_difficulty": 2,
                 "current_version": "1.0.1", "evaluated_versions": ["1.0.1"],
                 "version_mismatch": false } ] },
  "agents": ["deepseek-coder:6.7b","gemma2:2b","llama3.2:latest",
             "noop (synthetic baseline)","oracle (synthetic baseline)",
             "qwen2.5-coder:3b","qwen2.5-coder:7b"],
  "task_versions": { "distinct": ["1.0.0","1.0.1","1.0.2"],
                     "distribution": { "1.0.0": 100, "1.0.1": 425, "1.0.2": 75 } },
  "observability": { "total_runs": 600, "first_created_at": "2026-06-18 ...",
                     "last_created_at": "2026-06-22 ...", "runs_with_patch": 520,
                     "runs_with_test_results": 519, "test_result_rows": 6322 },
  "provenance": { "formula_version": "v0.1", "version_notice": "",
                  "subtitle": "Persisted DB data only: qwen2.5-coder:7b 120 runs/24 tasks; ... gemma2:2b 120 runs/24 tasks. Oracle and noop are explicitly synthetic baselines.",
                  "synthetic_baselines": ["oracle (synthetic baseline)","noop (synthetic baseline)"] } }
```

`observability` field names are exactly `RunStoreSummary`'s. `subtitle`/`version_notice` are reproduced from `report_combined.py` verbatim. `GET /api/v1/manifest.json` returns the same snapshot descriptor used to pin the DB content (`schema_version`, `formula_version`, `snapshot_id`, `db_sha256`, run/patch/test counts) — `db_sha256` computed at startup, `snapshot_id` = process boot time + hash.

### 4.7 Endpoint → source map (summary)

| Endpoint | Wraps | Recompute (frozen-fn args) | Patch/tests? |
|----------|-------|----------------------------|--------------|
| `GET /overview` | `leaderboard(in-mem)` + `disk.summary()` | none (fixed scope) | no |
| `GET /leaderboard[?task_id=]` | `leaderboard(in-mem, task_id=)` | `task_id` (scope) | no |
| `GET /domains/<agent>` | `domain_profile(in-mem, agent, task_domains)` | `agent`; `task_domains` (manifest) | no |
| `GET /cell/<agent>/<task_id>` | `task_aggregate(...)` (all 19 fields) + `load_runs(...)` (in-memory store) | (fixed scope from path) | no (flags `captured`/`synthetic`) |
| `GET /run/<agent>/<task_id>/<idx>` | **none** — per-request read-only disk SQL (real) / in-memory read (synthetic) | — | **yes** (or `"not captured"` / synthetic state) |
| `GET /meta` | `disk.summary()` + `task_ids()`/`agents()` + manifest | — | summary counts only |

**Store binding (§2.2):** "in-mem" = the in-memory store post-baseline (600 real + 240 synthetic), the only place oracle/noop appear, so all aggregation runs there; "disk" = `reports/runs.sqlite` (600 real only), used for `/run` real-agent SQL (via a per-request read-only connection, §2.3) and for `summary()` (`total_runs=600`, counting real rows only — synthetic rows are not observability facts).

### 4.8 Error model

One shape for every non-2xx (FastAPI exception handler), no stack traces, offline-safe:

```jsonc
{ "error": { "code": "task_not_found",
             "message": "No runs found for task_id 'fix-foo' in the store.",
             "detail": { "task_id": "fix-foo" } } }
```

| HTTP | `code` | When |
|------|--------|------|
| 400 | `invalid_parameter` | Bad query param (unknown `task_id` filter form, malformed value). |
| 404 | `task_not_found` | `task_id` not in `store.task_ids()`. |
| 404 | `agent_not_found` | `agent` not in `store.agents()`. |
| 404 | `cell_empty` | Valid `(agent, task_id)` pair but zero rows (distinct from not-found). |
| 404 | `run_not_found` | `(agent, task_id, idx)` triple has no row. |
| 409 | `mixed_version_pool` | A scope would pool >1 `task_version` within a cell — mirrors `report_combined.py`'s refusal; `detail` carries `{cell: [versions]}`. Dormant on the current DB. |
| 422 | (FastAPI validation) | Path/query type coercion failures, re-mapped to the envelope above. |

---

## 5. Data model & capture gaps

The frontend projects the SQLite raw layer (`runner/afa_runner/store.py`, the `SQLITE_SCHEMA` inside `SqliteRunStore`) and the frozen kernel output types (`kernel/afa_kernel/types.py`). The relevant raw tables:

- **`runs`** — `id` (autoincrement, internal lookup only), `task_id`, `task_version`, `agent`, `idx`, `status` (all 600 live rows `valid`), `transcript_hash`, `duration_ms`, `created_at`. Index `ix_runs_task_agent (task_id, agent)`.
- **`run_scores`** — PK `(run_id, formula_version)`; `gate_product`, `t_hidden`, `q` (SQLite name; Postgres calls it `q_score`), `final_score`, `functional_pass`, `voided`, `formula_version='v0.1'`. `load_runs` reconstructs `RunScore.q_components = {}` (not persisted in v0.1). No per-gate booleans in SQLite (`gates_jsonb` is Postgres-only).
- **`diffs`** — PK `run_id`; `files_changed`, `lines_added`, `lines_removed`, `touched_protected`, and the **nullable** `patch_text` (the capture flag).
- **`test_results`** — PK `id`; `suite` (`'hidden' | 'regression'`), `test_name`, `passed` (0/1; Postgres uses `status` text), `weight`. Index `ix_test_results_run (run_id)`.

`load_runs` selects from `runs ⋈ run_scores ⋈ diffs` only — it does **not** select `patch_text` or `test_results` — which is why `/cell` adds the `captured` flag and `/run` does the direct §4.5 read.

**Journal mode.** The live DB's `PRAGMA journal_mode` is `delete` (rollback journal), not WAL; the store never sets WAL. The API opens read-only and does not change it (§2.3). Concurrency with the worker's writes is handled by `busy_timeout`, not WAL.

### Capture matrix (live DB)

600 runs = 5 agents × 120. 520 have `patch_text`; 80 legacy rows do not. 519 distinct runs carry `test_results` (6322 rows total).

| column / table | 80 legacy runs | 520 captured runs |
|----------------|----------------|-------------------|
| `runs.*`, `run_scores.*`, `diffs` diffstat columns | populated | populated |
| `diffs.touched_protected` | populated (written `0`) | populated (real value) |
| `diffs.patch_text` | **NULL — not captured** | **populated** |
| `test_results` rows | **none (0 rows)** | **present** |

Per-agent legacy (no-patch) split: deepseek-coder:6.7b 20, gemma2:2b 20, qwen2.5-coder:3b 20, llama3.2:latest 10, qwen2.5-coder:7b 10 (= 80). The legacy rows are older (`created_at` Jun 18–19) than captured rows (Jun 20–22).

### The captured-vs-"not captured" honesty contract

Captured vs not-captured is decided **per artifact**, not by a single flag: `captured = (diffs.patch_text IS NOT NULL)`.

- **Legacy (80 rows, `patch_text IS NULL`):** `patch_text: null`, `captured: false`, and `test_results` is the literal string `"not captured"` (not `[]`, to distinguish "no artifact persisted" from "captured but empty"). Aggregate score primitives (`gate_product`, `t_hidden`, `final_score`, `functional_pass`, line counts) are still present for all 600 runs.
- **Captured (520 rows):** the patch string and a `test_results` array.
- **Captured-but-empty edge case** (`fix-binary-search`, `llama3.2:latest`, idx of `runs.id=554`): `patch_text` present, `test_results: []` (empty array = captured, zero rows). The UI renders the patch and says "per-test results not captured" — distinct from the legacy "not captured" string. This is why `runs_with_patch=520` but `runs_with_test_results=519`.
- **Synthetic (oracle/noop):** `synthetic: true`, `captured: false`, `patch_text: null`, `test_results: "synthetic baseline — no patch/tests"`. The deterministic bookend state, never conflated with captured or legacy.

**Capture gaps the UI must surface honestly (not fabricate):**

1. **`q_components` = `{}`** in v0.1 — show Q = 1.0 (offline) and per-component q as unavailable.
2. **Per-gate booleans absent** in SQLite — show the gate **product** `G` (`gate_product`) reliably; mark `setup_ok`/`diff_exists`/`scope_ok`/`regression_pass`/`no_timeout` as "not captured" for runs lacking them.
3. **80 legacy runs lack patch + per-test** — render "not captured" for both; aggregates still shown. Permanent property of historical rows, not a bug.
4. **`runs.id=554` edge case** — patch present, zero test rows; the two not-captured states are independent.

`docs/FAILURE_INSPECTION.md` is a stale 500-run snapshot inference. It must **never** be an oracle for any count or verdict; counts come only from live SQL or the store/report functions.

---

## 6. Views

One shell, deep-linkable; the URL **is** the state. The SPA resolves these routes client-side (React Router or equivalent), fetching the matching `/api/v1/...` resource on navigation.

### 6.1 Routes

```
/                                  Overview: leaderboard + domain matrix (all tasks pooled)
/?task=<task_id>                   Overview re-scoped to one task (leaderboard(store, task_id=...))
/methodology                       How scoring works (static, no DB)
/agent/<agent>                     Agent profile: that agent's domain_profile() + its row across tasks
/cell/<agent>/<task_id>            Cell drill-down: the (agent, task) per-run table
/cell/<agent>/<task_id>/run/<idx>  Run detail: patch diff + per-test results, or "not captured"
```

`idx` (the `RunRecord.idx` repeat index) is the canonical run key in URLs — never the SQLite `runs.id`. Agent segments are percent-encoded; synthetic baselines are **fully linkable** (their cell and run pages resolve from the in-memory store, §4.4/§4.5, and the run page renders the explicit "synthetic baseline — no real patch/tests" state rather than 404-ing). Every drill-down shows a breadcrumb `Overview › <agent> › <task_id> › run #<idx>` and a persistent scope chip ("All tasks" or "Task: <task_id>") so the user always knows what `n` counts.

### 6.2 View 1 — Overview (leaderboard + domain matrix)

**Leaderboard table** (from `/overview` or `/leaderboard?task_id=`, rendered in kernel order, **never re-sorted by `pass_rate`**):

| Column | Field | Honesty treatment |
|--------|-------|-------------------|
| Rank | `rank_low` / `rank_high` | Single value when equal; range `low–high` when they differ; literal **"provisional"** badge when `provisional` or either bound is `null`. Mirrors `format_leaderboard`'s `_rank_cell`. Rows sharing a band get a left-rail grouping (a tie is one cluster, not 3 false positions). |
| Agent | `agent` | Synthetic baselines get a "synthetic baseline" tag and muted treatment — bookends, not competitors. |
| p̂ | `pass_rate` | The point inside the interval bar, 3 dp — never standalone. |
| Wilson interval | `wilson_low … wilson_high` | **The hero element.** Horizontal bar on a shared 0–1 axis; tick at `pass_rate`. Overlapping brackets *are* the "can't separate these two" story, drawn. |
| n | `n` | Valid (non-voided) runs in scope. |
| Status | `provisional` | `n < 5` → amber "provisional — excluded from ranking" pill. |

Caption verbatim from the kernel rule: "Ranked by Wilson lower bound. Agent a out-ranks b only when LCB(a) > p̂(b); otherwise they share a rank range."

**Domain matrix** (model rows × domain columns; each row from one `domains/<agent>` call — `build_domains` — fetched one per agent and assembled into the matrix client-side):

| Element | Field | Honesty treatment |
|---------|-------|-------------------|
| Cell value | `pooled_pass_rate` | Shown **only when** `displayable` (`n_tasks ≥ 5 AND n_runs ≥ 25`). |
| Suppressed cell | `displayable == false` | Renders literal **`--`** (grey hatch), never a number. Tooltip: "not displayable: n_tasks=…, n_runs=… (need ≥5 tasks and ≥25 runs)". |
| Cell uncertainty | `wilson_low/high`, `n_eff` | On hover: Wilson interval on `n_eff` (Kish), plus `n_eff`, `n_tasks`, `n_runs`. |
| Cell shading | `pooled_pass_rate` | Intensity encodes the rate; `--` cells are unshaded so **suppression ≠ low score**. |

### 6.3 View 2 — Cell drill-down

From `/cell/<agent>/<task_id>`. **Aggregate header** projects all 19 `AggregateResult` fields: headline `n_pass`/`n_valid` → `pass_rate` with the reused Wilson bar; an S-distribution strip (`mean_s, median_s, min_s, max_s, std_s`) where `max_s` is labeled **"max (cherry-pick hazard — diagnostic only)"**; conservative readings (`conservative_continuous`, `stability`); a `pass_at_k` k→value table; a reliability strip (`reliability, timeout_rate, infra_void_rate`); and honesty badges shown only when true: `provisional`, `deterministic` ("variance 0 by construction"), `bimodal` ("the mean is a fiction").

**Per-run table**, one row per `RunRecord` in `idx` order — columns present for all 600 runs: `# (idx, links to run)`, `Status` (enum string; `infra_failure` struck-through + "VOIDED — excluded from n"), `G` (`gate_product`, 0 in red), `T_hidden`, `X / functional_pass`, `S` (`final_score`, tooltip `S = G·T_hidden·(0.85+0.15·Q)`), `Files`, `+/−`, `Duration`, and a **capture chip** with three states driven by the serializer: `synthetic` → "synthetic baseline"; else `captured` → "captured"; else "not captured (legacy run)". Footer states the cell's capture split honestly (synthetic cells are labeled as deterministic bookends, not a capture gap).

### 6.4 View 3 — Run detail

From `/cell/<agent>/<task_id>/run/<idx>` → `/api/v1/run/...`.

- **Header:** `status`, `idx`, `transcript_hash` (truncated + copy; equal hashes ⇒ identical runs), `duration_ms`, `task_version` (so the reader knows which version was graded; cells never pool versions).
- **Gate breakdown:** the five gates as a checklist when captured; otherwise show only `gate_product` (the value that *is* stored) with "per-gate breakdown not captured for this run." `gate_product == 0` highlights the failing side: "any single failed gate forces G = 0 and S = 0."
- **How S was computed:** a derivation panel, values verbatim: `S = gate_product · t_hidden · (0.85 + 0.15·q) = <final_score>`, with the note "quality modifier Q = 1.0 (offline; per-component q not persisted in v0.1)".
- **Patch diff:** captured → rendered unified diff + diffstat (+ `touched_protected` flag if true). Legacy → full-width "Patch not captured (legacy run)." with the diffstat still shown (those columns exist for all 600).
- **Per-test results:** captured → table of `test_results` grouped by `suite` (`hidden`/`regression`), pass/fail from `passed`, `weight`. Legacy → "Per-test results not captured (legacy run)." Edge case `runs.id=554` → patch shown, per-test reads "Patch captured, but the grade report recorded no per-test rows" — distinct from legacy. Synthetic (oracle/noop, `synthetic: true`) → a fourth state: "Synthetic baseline — deterministic bookend; no real patch or per-test results," with the all-pass / all-fail score primitives shown — never conflated with captured or legacy "not captured."

### 6.5 View 4 — Methodology

Static (no DB), quoting `types.py` docstrings to stay in lockstep with the kernel: the four `RunStatus` values and their effect on `n`; `S = G·T_hidden·(0.85+0.15·Q)`; what `functional_pass` (X) means; `pass_rate = n_pass/n_valid` and the provisional/deterministic/bimodal flags; Wilson LCB/UCB ranking and the strict-domination rule; domain pooling, Kish `n_eff`, the `displayable` threshold; and the standing statement: "All scoring, aggregation, confidence, and ranking math is computed by the frozen Python kernel (`afa_kernel`). This explorer only projects those results; it never recomputes them."

### 6.6 Cross-cutting honesty posture

Uncertainty is the hero (wide bars for small `n`); provisional is loud everywhere; suppression is a labeled grey hatch; captured-vs-not-captured is per-row truth from real `patch_text`/`test_results` presence; cherry-pick hazards (`max_s`, `bimodal`) are named; synthetic anchors sit outside the competitive field; provenance (`transcript_hash`, `task_version`, the mixed-version refusal) is one click away. Every rendered value has a checkable origin, and the explorer shows that origin rather than softening it.

---

## 7. Client-side controls

The SPA offers a small set of **presentation-only** controls. The single rule: a control may only **select, hide, reorder, or text-match rows/columns that already exist verbatim in the response** — its output is a subset or permutation of values the kernel already emitted. The only arithmetic allowed on kernel fields is comparison for filter/sort (`<`, `>`, `==`, `localeCompare`, `includes`). No control re-invokes a kernel function, changes `n`/`c`/the pooled set, or produces a number the API did not already serve.

| Control | Operates on | Mechanism (client-only) |
|---------|-------------|-------------------------|
| Filter rows | leaderboard / cell / run tables | predicate over served fields (`agent`, `status`, `provisional`, `functional_pass`, `deterministic`, `bimodal`, `voided`) |
| Sort rows | any table | comparator over a served column (`wilson_low`, `pass_rate`, `n`, `mean_s`, `stability`, `duration_ms`, …) — a local view sort; the canonical kernel order is always restorable |
| Search | agent / task / test names | substring match |
| Show / hide columns | any table | visibility toggle (URL / `localStorage`) |
| Choose a domain to view | domain matrix | select which served `DomainScore.domain` renders |
| Leaderboard scope by `task_id` | leaderboard | navigate to `/leaderboard?task_id=<id>` — the **kernel re-ranks server-side**; the client does not re-rank |

**Two things the controls must not do.** (1) **Re-rank.** The leaderboard renders in kernel order by default; a user-applied local sort is a view convenience, but ranks/intervals shown are always the exact served values and never shift to "close a gap." Re-ranking under a different inclusion set (e.g. a minimum-n cutoff) would change the `RankInput` set fed to the kernel — that is a server-side recompute via `/leaderboard?task_id=`, not a client control. (2) **Re-compute any statistic.** A display-only min-n control may *hide* rows below a served `n`/`n_eff`/`n_runs` from the DOM, with the persistent caption **"Display filter only — hides rows below n; ranks and intervals are unchanged from the full-pool computation."** It never deletes rows from the pool or re-derives a bound.

### The forbidden path (enforceable rule)

Never re-implement scoring, Wilson bounds, pooling, Kish `n_eff`, `pass@k`, `conservative_continuous`, `stability`, `pooled_pass_rate`, or LCB ranking in TS/JS — not even as an approximation, not for any control. The answer to "I can't show that without computing it" is **the server computes it** (the kernel ran in Python and the API served the result), never "the browser computes it."

**Two distinct kinds of arithmetic — only one is forbidden:**

- **Kernel statistical math (FORBIDDEN, anywhere in `web/`):** producing or reconstructing any *statistic* — Wilson bounds, `pass@k`, Kish `n_eff`, `conservative_continuous`, `stability`, `mean_s`/`median_s`/`std_s`, `pooled_pass_rate`, LCB/UCB ranking, or any re-derivation of them from primitives (`n`, `c`, per-run scores). This emits a *new number the kernel did not*.
- **Display-coordinate arithmetic (PERMITTED, in display/SVG helpers only):** mapping an *already-served* kernel value in a *known range* to a pixel/axis position — e.g. `x = wilson_low * axisWidth` to place a bar end, a tick at `pass_rate`, the S-distribution strip, the `pass_at_k` k→value bars. This produces **no new statistic** — it is pure projection of a frozen value onto screen geometry. A wide bar for small `n` is the kernel's interval drawn to scale, not a recomputation.

Enforce it mechanically: the web package contains zero numeric kernel logic. A lint/CI guard bans the forbidden tokens (`wilson`, a `pass_at_k` *computation*, `Math.sqrt`, `_continuous`, a `pooled` reducer) in **logic modules** (`web/src/lib/**` excluding geometry, hooks, data transforms). It does **not** scan clearly-named display/SVG-geometry helpers (e.g. `web/src/components/**/*.svg.tsx`, `web/src/lib/geometry/**`), which are exempt because their only arithmetic is range-to-pixel projection. (The exemption is scoped to geometry that takes a kernel value as input and returns a coordinate; it does not license computing a new field. Field *names* like `wilson_low` may of course be read everywhere.) Without this carve-out the guard and the honesty visuals could not both ship; with it, both are enforceable.

---

## 8. (reserved)

---

## 9. Verification plan

Verification proves **one thing**: that no number, flag, or provenance bit is altered, recomputed, or dropped as data flows `SQLite row → report function (kernel types) → serializer → wire (API JSON)`. The single source of truth is the live triplet, agreed pairwise:

1. **API JSON** — what FastAPI serves for a target.
2. **Raw SQL** — `sqlite3` against `reports/runs.sqlite` for the per-run *primitives* (`gate_product`, `t_hidden`, `q`, `final_score`, `functional_pass`, `voided`, `transcript_hash`, `task_version`, `diffs.patch_text` nullability) and set membership.
3. **Report-function output** — `task_aggregate`, `leaderboard`, `domain_profile`, `format_leaderboard` called in-process against a read-only `SqliteRunStore`-equivalent connection on the same file.

**Forbidden oracle:** `docs/FAILURE_INSPECTION.md` prose (stale 500-run snapshot; it says "500" where the live DB has 600 with an 80-row legacy gap). Any test hardcoding a number traceable to it is a defect. SQL never re-derives kernel math (the kernel is frozen and is the only place Wilson/pass@k/etc. are computed); SQL only reconciles primitives and set membership.

**What "three-way" honestly means per field type.** The check is not uniformly three-way, and this doc states it plainly rather than overselling it:

- **Primitives, set membership, and ordering** (`n_valid`, `n_pass`, `gate_product`, `t_hidden`, `q`, `final_score`, `functional_pass`, `voided`, `transcript_hash` ordering, `task_version` count, `patch_text` nullability) get a **genuine three-way** check: raw SQL (leg A) is an *independent* witness alongside the report function (leg C) and the API (leg B).
- **Kernel-computed statistics** (`wilson_low/high`, `pass_at_k`, `stability`, `conservative_continuous`, `mean_s`/`median_s`/`std_s`, `n_eff`, `rank_low/high`, `pooled_pass_rate`) are verified **two-way by construction** — report function (leg C) ↔ API (leg B) — because the kernel is the *sole* math authority and both legs derive from the same kernel call; raw SQL cannot independently re-derive a Wilson bound without re-implementing the kernel (forbidden). To avoid pure report-fn-as-oracle for the numbers that matter most, **one frozen golden anchor** supplies a true third witness (§9.1): a hand-derived Wilson bound for an anchor cell's `(n_valid, n_pass)`, committed once and diffed, so "three-way" is literally true for at least that computed field.

### 9.1 Core three-way equality (a known captured cell)

Anchor: `agent = "qwen2.5-coder:7b"`, `task_id = "escape-html"` — fully captured, single-version (`1.0.1`), all 5 runs carry `patch_text`. This cell is verified live as `n_valid=5, n_pass=5` (a **perfect 5/5** cell), so its golden Wilson bounds are `wilson_low < 1` and `wilson_high = 1` — a valid closed-form Wilson check on the `c = n` boundary. (This per-cell 5/5 is fully consistent with the agent's *pooled* leaderboard `pass_rate 0.633` in §4.2: pooling across all 24 tasks lowers the rate; a single strong cell does not.) The run-detail anchor inside it is identified canonically as `(qwen2.5-coder:7b, escape-html, idx 0)` — **not** by a hardcoded `runs.id`. The test resolves `runs.id` at runtime (`SELECT id FROM runs WHERE agent=:a AND task_id=:t AND idx=:i`) and uses it only as the internal lookup §4.5 mandates, so a re-ingest that reassigns the AUTOINCREMENT cannot silently invalidate the anchor.

To exercise a **non-degenerate** (interior, `c < n`) Wilson computation as well, the suite parametrizes a second anchor — a partial-pass cell (`n_valid=5, n_pass=4`, e.g. the `fix-binary-search` example) — whose two-way A↔C check covers the `0 < c < n` case; the hand-derived golden third witness (leg D) is computed on the **perfect 5/5 escape-html cell** as the committed boundary anchor and, optionally, on the interior partial-pass cell for a non-boundary golden.

- **Leg A — report function (math authority):** `task_aggregate(store, agent, task_id)` → the expected `AggregateResult` (never recomputed by the test).
- **Leg B — API:** the `/cell/...` JSON; assert field-by-field equality with A across all 19 `AggregateResult` fields. Floats with `abs(a−b) ≤ 1e-9` (guards only IEEE-754 JSON round-trip; the serializer must not round). `pass_at_k` keys stringified ints, values float-equal. Booleans identity-equal.
- **Leg C — raw SQL (independent primitive/membership witness):**
  ```sql
  SELECT r.idx, s.gate_product, s.t_hidden, s.q, s.final_score,
         s.functional_pass, s.voided, r.transcript_hash, r.task_version
  FROM runs r JOIN run_scores s ON s.run_id = r.id
  WHERE r.agent = :agent AND r.task_id = :task_id ORDER BY r.idx;
  ```
  Assert: `COUNT(voided=0) == n_valid`; `SUM(functional_pass) == n_pass`; the ordered `transcript_hash` list (idx order, `INFRA_FAILURE` excluded) == the list `task_aggregate` feeds to `aggregate_runs`; `COUNT(DISTINCT task_version) == 1`. **Leg C is an independent third witness only for these primitives / membership / ordering** — it deliberately does *not* re-derive Wilson/pass@k/etc. (that would re-implement the frozen kernel).

`A == B` field-by-field, with `A`'s primitives reconciled against `C`, is the equality for this cell. For the computed statistics on this cell, `A == B` is two-way by construction — **except** the one frozen golden witness below.

- **Leg D — frozen golden Wilson witness (the literal third witness for a computed field):** the anchor cell's `(n_valid, n_pass)` and its `wilson_low`/`wilson_high` are computed **once** by hand (closed-form Wilson score interval at the kernel's confidence level, independent of `afa_kernel`), committed as a golden constant, and diffed against both `A.wilson_low/high` and `B.wilson_low/high` at `1e-9`. For the perfect-5/5 escape-html anchor this golden is the boundary case `wilson_high == 1.0` (exactly) and `wilson_low < 1.0`; the optional interior partial-pass golden exercises a non-degenerate `0 < wilson_low < wilson_high < 1` computation. This makes the three-way claim **literally true for at least one computed field** at the anchor, instead of relying on the report function as its own oracle. The golden is recomputed by hand (not by importing the kernel) and only if the anchor cell's `(n_valid, n_pass)` changes.

### 9.2 Run-detail paths

All anchors are expressed as `(agent, task_id, idx)` triples — the design's canonical identity (§4.5) — and the test resolves `runs.id` at runtime purely as the internal SQL lookup. No AUTOINCREMENT id is hardcoded in the suite. (For reference on the current DB these triples resolve to ids 601, 11, 554; the suite must never depend on those values.)

- **Captured (`qwen2.5-coder:7b, escape-html, idx 0`):** per-run scalars three-way equal; served `patch_text` byte-equals `SELECT patch_text FROM diffs WHERE run_id = <resolved>`; the served `(suite, test_name, passed, weight)` rows equal the raw `test_results` set (`passed` mapped from 0/1).
- **Legacy (`gemma2:2b, fix-binary-search, idx 0` — v1.0.0, NULL patch, 0 tests):** the run detail renders "not captured" for patch and per-test (an explicit `null` / `"not captured"` marker — never an empty string masquerading as captured, never a fabricated diff); score primitives still served and SQL-equal.
- **Edge (`llama3.2:latest, fix-binary-search, idx 3`):** patch renders (captured) while per-test renders "not captured" **independently** — proving patch-presence and test-presence are decided separately.
- **Synthetic (`oracle (synthetic baseline)`, any task, any idx):** the run detail resolves from the **in-memory store** (no disk row exists), renders `synthetic: true` with the "synthetic baseline — no patch/tests" state, and its primitives equal `report_combined`'s deterministic baseline constants — **exempt from the raw-SQL leg** (there is nothing in `runs.sqlite` to join against). Same for `noop`.

### 9.3 Synthetic-baseline constants (the deterministic bookend check)

Synthetic rows have no disk witness, so instead of leg C they are checked against `report_combined`'s deterministic baseline constants: every served `oracle` run has `gate_product=1, t_hidden=1.0, q=1.0, final_score=1.0, functional_pass=true` and every `noop` run is all-zero with `files_changed=0`; the leaderboard shows oracle n=120 p̂=1.000 (top anchor) and noop n=120 p̂=0.000 (bottom anchor) exactly. This is the verification path for the 240 synthetic runs and the 48 synthetic cells.

### 9.4 Mixed-version refusal through the API

- **Dormant (live DB):** the API builds and serves; assert every served cell has `COUNT(DISTINCT task_version) == 1` and the subtitle contains no "awaiting reevaluation" string.
- **Injected violation (synthetic temp / `:memory:` store, never the live file):** insert two runs into one `(agent, task_id)` cell with different `task_version`; drive the API's build/aggregate entry point; assert it raises/returns the refusal (the `"refusing to pool multiple task versions"` stem) and never serves a pooled aggregate.
- **Synthetic-baseline non-interference:** assert each synthetic cell is single-version in the built store (baselines added only after the refusal passes).

### 9.5 Read-path opening (connection + journal-mode guards)

Two small guards keep §2.3's connection model honest:

- **Read-only open does not write.** Point the API's read-only open helper at a **fresh temp DB file**; assert that after a full set of GET requests the file's schema is unchanged (no tables created) and its mtime did not advance — i.e. the API never ran `executescript`/`commit`. Distinguishes the read path from the writer store.
- **Thread-affinity does not crash.** Drive two concurrent GETs on different threadpool workers (e.g. a `/cell` and a `/run`) through the `TestClient`; assert neither raises `sqlite3.ProgrammingError` — proving handlers use per-request connections, not a shared boot-time one.
- **(Worker-side, Phase 3 only — not gated here)** if/when the worker enables WAL, a separate ship-gate asserts `PRAGMA journal_mode == 'wal'` on the live DB. This read-only surface asserts nothing about WAL; it only sets `busy_timeout` and tolerates `delete`-journal contention.

### 9.6 Pytest suite (FastAPI `TestClient`, in-process, zero network, no LLM)

| Test | Asserts |
|------|---------|
| `test_cell_threeway_equality` | §9.1 — A == B field-by-field across all 19 `AggregateResult` fields at 1e-9; C reconciles `n_valid`, `n_pass`, ordered hashes (primitives only). Parametrized over `escape-html` (perfect 5/5) + a partial-pass interior cell. |
| `test_golden_wilson_anchor` | §9.1 leg D — `escape-html` anchor `wilson_low/high` (A and B) equal the hand-derived golden Wilson bound at 1e-9 (literal third witness; boundary case `wilson_high == 1.0`, `wilson_low < 1.0`). Optional interior golden on the partial-pass cell. |
| `test_pass_at_k_serialization` | `pass_at_k` keys stringified ints; values float-equal; `k ≤ n_valid`. |
| `test_run_detail_captured` | §9.2 — `(qwen2.5-coder:7b, escape-html, idx 0)`, id resolved at runtime: scalars + byte-equal patch + per-test rows three-way. |
| `test_run_detail_legacy` | §9.2 — `(gemma2:2b, fix-binary-search, idx 0)`, id resolved at runtime: "not captured" for patch + per-test; primitives still SQL-equal. |
| `test_run_detail_captured_no_tests` | §9.2 — `(llama3.2:latest, fix-binary-search, idx 3)`, id resolved at runtime: patch renders; per-test "not captured" independently. |
| `test_run_detail_synthetic` | §9.2/§9.3 — `oracle`/`noop` run detail resolves from the in-memory store (no disk row); `synthetic: true`; primitives equal the baseline constants; exempt from the raw-SQL leg. |
| `test_leaderboard_projection` | API leaderboard == `leaderboard(store)` element-for-element in order; `null` ranks iff `provisional`; oracle p̂=1.000 / noop p̂=0.000 present. |
| `test_format_leaderboard_parity` | If the optional `.txt` is exposed, byte-equals `format_leaderboard(leaderboard(store))`. |
| `test_mixed_version_refusal_dormant` | §9.4 — every served cell single-version; no "awaiting reevaluation". |
| `test_mixed_version_refusal_enforced` | §9.4 — injected two-version cell raises/refuses with the refusal stem. |
| `test_readonly_open_no_write` | §9.5 — read-only open against a temp DB creates no tables and does not advance mtime (the API never runs DDL/commit). |
| `test_concurrent_requests_thread_safe` | §9.5 — two concurrent GETs on different threadpool threads raise no `sqlite3.ProgrammingError` (per-request connections, not a shared one). |
| `test_db_invariants_live` | Live guard (NOT from prose): `COUNT(*)=600`, all `status='valid'`, `runs_with_patch=520`, `runs_with_test_results=519`, `versions_per_cell_gt1=0`, and `PRAGMA journal_mode == 'delete'` (until the worker enables WAL). Drift fails with a clear message so other anchors aren't silently stale. |

Shared fixtures: `live_store` (session-scoped read-only connection on the live DB), `api_client` (`TestClient`), a `sql` helper, `deep_equal(a, b, tol=1e-9)` (stringified-int + null-aware), `temp_store` (per-test `:memory:` / temp DB for injected fixtures). Float policy: full precision on the wire; tests compare at `1e-9` for JSON round-trip only; display rounding is a browser concern, out of scope for wire-equality.

---

## 10. Build phases

This document delivers **Phase 1 + Phase 2** of the shared implementation roadmap. The full roadmap (referenced, not redefined here) is:

- **Phase 1** — read-only FastAPI API + React dashboard over the current SQLite. *(this doc)*
- **Phase 2** — cell / run drill-down. *(this doc)*
- **Phase 3** — job/evaluation backend + worker.
- **Phase 4** — UI evaluation wizard + live monitor.
- **Phase 5** — Docker Compose local app (one command).
- **Phase 6 (or later)** — static / Vercel evidence site (baked read-only bundle) — explicitly deferred (Appendix A).

Each phase below has one binary **ship-gate** that must hold before the next starts. No phase re-implements kernel math.

### Phase 1 — read-only FastAPI + React dashboard (overview)

Build `afa_api/` (FastAPI) beside `runner/` and `kernel/`, depending on `afa_runner.report` and a **new read-only open path** over `reports/runs.sqlite` (`mode=ro` URI connection that skips DDL/commit, with `busy_timeout`; §2.3) — *not* the writer `SqliteRunStore` constructor, which opens read-write and runs DDL. Build `afa_api/serialize.py` (the single serializer) and the read-only endpoints of §4, each a thin wrapper over one report function plus the §4.5 direct read for run detail. `task_domains` loaded from `manifest.json`. The load/refusal/baseline sequence (§2.2) runs at startup; the per-request connection model (§2.3) governs all DB access. Path bootstrap mirrors `eval_persist.py` (prepend `<root>/kernel` and `<root>/runner` to `sys.path`).

Then the Vite React SPA under `web/`: a typed `fetcher` over `/api/v1/...`, the app shell, the leaderboard view (Wilson interval as the foreground bar; rank ranges; provisional badges; synthetic bookends) and the domain matrix (colored by `pooled_pass_rate`; `displayable`-gated; `--` for suppressed; assembled client-side from one `build_domains` call per agent). Subtitle/observability banner from `/meta`. The set of controls is presentation-only (§7): filter / sort / search / show-hide columns / scope-by-`task_id` (server re-ranks).

*Tech:* FastAPI (async, typed, auto-OpenAPI; the contract is the product; endpoints mirror report functions 1:1 so "no new math" is enforceable by inspection). Vite React SPA (fast dev server, single build artifact, served by the local API or a dev proxy). Wilson intervals and the matrix are hand-rolled inline SVG (no chart lib) — pixel control over the honesty visuals, zero dependency that could recompute anything.

**Ship-gate 1:** the §9 three-way verification passes for the overview/leaderboard/domain endpoints against the live DB (leaderboard ordering + Wilson bounds, per-domain scores); oracle p̂=1.000 n=120, noop p̂=0.000 n=120; `/meta` reports `runs_with_patch=520`, `runs_with_test_results=519`; mixed-version refusal path covered; the read-only-open and thread-safety guards (§9.5) pass; the overview renders against the live API with order and Wilson bounds pixel-faithful to `format_leaderboard(leaderboard(store))` (ranks, p̂/LCB to 3 dp); domain matrix gates on `displayable`; no client-side arithmetic on scores; provisional agents excluded from rank numbering exactly as the kernel reports; pytest green. Never verify against `docs/FAILURE_INSPECTION.md`.

### Phase 2 — drill-down (cell + run, captured vs "not captured")

Cell view from `/cell/...` (all 19 `AggregateResult` fields; `pass_at_k` series; honesty badges; per-run list by `idx`). Run detail from `/run/...` (gate breakdown via `gate_product`, `t_hidden`, `q` + `q_components`, `final_score`, `functional_pass`, diffstat, `transcript_hash`). The captured-vs-not-captured UI is driven **solely** by the serializer's `captured`/`synthetic` flags (never UI inference): 520 captured render patch + `test_results`; the 80 legacy render "not captured" for both while still showing aggregates; `runs.id=554` renders patch + "tests not captured"; synthetic renders the deterministic-bookend state. The presentation-only cell/run filters slot in here.

*Tech:* dependency-light diff *display* over `patch_text` (no diff generation). `captured` drives the UI so the "not captured" story can't drift from the DB.

**Ship-gate 2:** for a sample spanning all 5 models, cell + run pages match raw SQL row-for-row; all 80 legacy runs render "not captured" for patch and per-test with aggregates shown; `id=554` shows patch-present / tests-not-captured; the per-agent legacy split (20/20/20/10/10 = 80) matches the UI's `captured` flag; synthetic cells/runs render the bookend state and resolve from the in-memory store; `pass_at_k` keys round-trip as ints; the §9 run-detail tests (`test_run_detail_captured/legacy/captured_no_tests/synthetic`) are green.

---

## 11. Open risks & caveats

1. **Thin per-run provenance.** SQLite reconstructs `RunScore.q_components={}` and has no `gates_jsonb`; per-gate booleans and per-component q are not in the dev DB. Run detail shows `G` (`gate_product`) honestly and marks sub-gates / q-components as unavailable rather than fabricating them.
2. **80 legacy runs lack artifacts** (no `patch_text`, no `test_results`) — a permanent property of historical rows; drill-down renders "not captured" for all 80 plus the `id=554` edge (patch present, tests absent). Not a bug to fix.
3. **Single-user / no-auth / trusted local host.** No authn/authz in scope. The explorer is read-only over a local SQLite file; it executes no agent code and touches no sandbox. The product as a whole is a trusted, single-user, local tool — the clean-room grader (a separate worker concern) runs agent code with host privileges via `LocalSandbox`, so the host must run only trusted models/tasks and must not be exposed to an untrusted network. No untrusted-agent isolation is claimed; a hardened `DockerSandbox` is out of scope and unclaimed.
4. **Mixed-version control is dormant but enforced.** No scope pools across versions; any scope that would pool >1 `task_version` in a cell returns 409 `mixed_version_pool` (mirroring `report_combined.py`'s refusal). The contract is enforced even though the current DB has zero mixed cells; a future DB that introduces a mixed cell will make the API raise rather than mis-pool.
5. **Snapshot freshness.** Because the local API reads the same `reports/runs.sqlite` the worker appends to, new runs appear on the next fetch with no rebuild — but aggregations are computed at process startup (§2.2 load sequence), so newly-appended runs become visible after an API restart (or a future explicit reload hook). The deferred static bundle (Appendix A) is strictly point-in-time and would need a re-bake; that asymmetry only matters if Phase 6 ships.
6. **Reader/writer contention (delete-journal mode).** The live DB is in `delete` (rollback-journal) mode, not WAL, and this read-only surface does not change that (§2.3). While the worker holds a write transaction it takes an EXCLUSIVE lock that briefly blocks the API's reads; a `busy_timeout` on each per-request read-only connection makes the read wait out the short write rather than failing. This is acceptable for a single-user local tool with tiny append-only writes. True reader/writer concurrency would require the **worker** to enable WAL once (a Phase 3 concern), which would persist in the DB file; this doc claims no WAL guarantee.

---

## 12. Tech choices

| Layer | Choice | Why |
|-------|--------|-----|
| Serializer | One pure Python module (`afa_api/serialize.py`) | Single wire contract; field-by-field projection only, provably no math. |
| API | FastAPI | Async, typed, auto-OpenAPI, trivially containerized; endpoints mirror report functions 1:1. Opens SQLite **read-only per request** (`mode=ro`, `busy_timeout`); never runs DDL; not WAL (DB is `delete`-journal — §2.3). |
| DB connection | Fresh read-only connection per request/SSE tail, thread-local | `sqlite3` connections have thread affinity; FastAPI dispatches handlers across a threadpool, so a shared boot-time connection raises `ProgrammingError`. Per-request `mode=ro` opens avoid that and never write. |
| Run identity | `(agent, task_id, idx)` | The only identity `RunRecord` exposes; `runs.id` is an internal SQL detail, never a URL/wire field. |
| Response shape | Single-resource objects, no envelope, no pagination | Surfaces are tiny; kernel lists must stay complete/ordered; the frontend must not slice or re-order. |
| Web framework | Vite + React + TypeScript (SPA) | Fast dev loop, single build artifact, no SSR/SSG machinery needed for a live local API. (Next.js/SSG is reserved for the optional Phase 6 evidence site, Appendix A.) |
| Routing | Client-side SPA router; URL is state | Deep-linkable overview → cell → run; `idx`-keyed run URLs. |
| Charts | Hand-rolled inline SVG | Wilson bars and the matrix are simple marks; pixel control over honesty visuals; zero dependency that could "recompute." |
| Controls | Client-side filter / sort / search / show-hide columns | Presentation-only; touch no number; never re-rank or re-derive a statistic (§7). |
| CI guard | Lint rule banning kernel-math tokens in `web/` logic modules (display/SVG-geometry helpers exempt) | Enforces "no kernel statistical math in JS" mechanically while permitting range-to-pixel display projection (§7). |

### Files this design adds / touches (all absolute)

- `/Users/manuk/Downloads/projects/agentforge arena/afa_api/serialize.py` — **new**, the single serializer (pure projection).
- `/Users/manuk/Downloads/projects/agentforge arena/afa_api/main.py` — **new**, FastAPI live local server (reuses the load/refusal/baseline logic of `examples/report_combined.py`; adds the read-only per-request open path of §2.3).
- `/Users/manuk/Downloads/projects/agentforge arena/web/` — **new**, the Vite React SPA (`web/src/lib/` fetcher + types, `web/src/components/`, `web/src/lib/geometry/` SVG helpers).
- Reused unchanged: `runner/afa_runner/report.py`, `runner/afa_runner/pipeline.py` (`RunRecord`), `kernel/afa_kernel/types.py` (FROZEN), `tasks/manifest.json`, `reports/runs.sqlite`, `examples/report_combined.py`.
- `runner/afa_runner/store.py` (`SqliteRunStore` + `SQLITE_SCHEMA`) — reused for **types/schema reference**; its writer constructor (read-write, runs DDL, single thread-affine connection) is **not** the API's open path. The API adds its own read-only `mode=ro` connection helper (§2.3) rather than reusing the writer store.

---

## Appendix A — deferred static / Vercel evidence site (Phase 6, optional)

**Status: deferred and optional.** Not part of the Phase 1 + Phase 2 read-only explorer above. This appendix records the shape of an optional, public, read-only "evidence site" so the idea is captured without making it a co-equal delivery mode. The v1 product is the Vite React SPA over the live local FastAPI; the static bundle is a *later, optional* artifact and the SPA never branches on its existence.

**What it would be.** A second consumer of the *same* `afa_api/serialize.py` — a build-time baker (`afa_api/export_bundle.py`) that runs the serializer once over `reports/runs.sqlite` and writes the resulting dicts to `.json` files on disk, which a static-site generator reads at build time (SSG). Because it calls the identical serializer, the baked files carry byte-identical semantics to the live API responses — no second projection, no re-implemented math.

**Sketch of the layout** (each live route maps 1:1 to one baked file; the agent path-segment encoding is identical to the live router):

| Live route | Baked file |
|------------|-----------|
| `GET /api/v1/overview` | `bundle/v1/overview.json` |
| `GET /api/v1/leaderboard` | `bundle/v1/leaderboard/index.json` |
| `GET /api/v1/leaderboard?task_id=<id>` | `bundle/v1/leaderboard/<task_id>.json` (24 files) |
| `GET /api/v1/domains/<agent>` | `bundle/v1/domains/<agent>.json` |
| `GET /api/v1/cell/<agent>/<task_id>` | `bundle/v1/cell/<agent>/<task_id>.json` |
| `GET /api/v1/run/<agent>/<task_id>/<idx>` | `bundle/v1/run/<agent>/<task_id>/<idx>.json` |
| `GET /api/v1/meta` | `bundle/v1/meta.json` |
| `GET /api/v1/manifest.json` | `bundle/v1/manifest.json` |

Cardinality on the current DB: 1 overview + 1 meta + 1 manifest + (1 + 24) leaderboard + 7 domain files (5 models + oracle + noop) + 7×24 = 168 cell files (120 real + 48 synthetic) + 840 run files (600 real + 240 synthetic). A `manifest.json` pins the bundle to a content snapshot (`schema_version`, `formula_version`, `snapshot_id`, `db_sha256`, run/patch/test counts, per-file hashes). The mixed-version refusal (§2.2) runs **first** at bake time, so a bad DB aborts the build and ships nothing.

**Why it is deferred.** The live local API already serves every view; a static bundle adds value only for *public, server-less hosting of a frozen snapshot*, which is not a v1 requirement. Deferring it avoids the heavyweight static-vs-live two-mode framing (mode switches, capability probes, disabled-control degradation tables) that a single always-present local API makes unnecessary.

**If/when it ships (Phase 6).** It would: (1) reuse `serialize.py` unchanged; (2) add only the baker and a static host config; (3) extend the verification suite with a `test_static_bundle_matches_api` check — build the bundle and start the API against the same `reports/runs.sqlite`, assert snapshot identity (DB content hash), then compare every target via canonical order-independent deep equality at `1e-9` (identical leaderboard ordering, `null` ranks for provisional agents in both, identical "not captured"/synthetic markers). Disagreement on the same snapshot would break the single-serializer guarantee and fail the build loudly. Synthetic targets (no disk-SQL witness) would be checked against the baseline constants of §9.3 rather than a raw-SQL leg. None of this is in scope for the Phase 1 + Phase 2 deliverable.
