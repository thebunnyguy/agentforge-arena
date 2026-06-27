# AgentForge Arena

Offline-first mathematical benchmarking and observability for code-modifying
agents. The core value is the **evaluation system** — deterministic, statistically
honest, explainable scoring — not the agents. No paid LLM APIs, no LLM-as-judge
in the core path, runs fully offline.

## Status — v0.2.0 (offline and executable)

```
docs/EVALUATION_FRAMEWORK.md   # the complete mathematical framework (design)
docs/FAILURE_INSPECTION.md     # forensic write-up of the most suspicious result cells
docs/OBSERVABILITY_FRONTEND_DESIGN.md  # read-only results-explorer design
docs/PRODUCT_APP_DESIGN.md     # local eval-running app design
kernel/afa_kernel/             # the math: scoring, aggregation, confidence, domains, ranking
runner/afa_runner/             # tasks, agents, sandbox, clean-room grader, store, report
afa_api/                       # FastAPI app: read-only results API + jobs/worker/SSE
web/                           # Vite + React single-page app (the dashboard UI)
afa_app.py, start.command      # one-command local app launcher (UI + API + worker)
tasks/                         # 24 benchmark tasks across 5 domains (+ manifest.json)
db/schema.sql                  # production PostgreSQL raw-layer schema
examples/                      # run_demo, eval_pack, eval_persist, report_combined, ...
reports/runs.sqlite            # read-only evidence DB (raw rows + grading artifacts)
reports/leaderboard.html       # reproducible HTML projection of runs.sqlite
docker-compose.yml             # containerized local app (alternative to the launcher)
DEVLOG.md                      # full phase-by-phase development log
```

Pure Python standard library (plus `pytest` for tests, and a local model server
for real-agent evaluation). Tested on Python 3.13.

## The task pack (24 tasks, every domain displayable)

| domain | tasks |
|---|---|
| backend | 17 |
| security | 5 (path-traversal, sanitize-filename, redirect, mask-secrets, escape-html) |
| async-concurrency | 5 (gather-bounded, retry, timeout, batched, first-success) |
| performance | 5 (merge-intervals, two-sum, grid-paths, top-k, async-batched) — graded by large-input timeout, not wall-clock |
| api-design | 5 (lru-cache, refactor, result-type, query-builder, paginator) |

**Coverage caveat:** this pack is intentionally usable but backend-heavy:
backend tags touch 17/24 tasks (8 primary), while api-design and performance
have only 3 primary tasks each and reach five via weighted secondary tags.
Domain profiles use tag weights 1.0/0.5/0.25; their evidence mass is therefore
not balanced even though every domain clears the display threshold. **TODO:**
the next task-bank expansion should add primary api-design/performance tasks
before adding more backend tasks.

Every task passes the §8 benchmark CI (`validate_task`): the reference fix scores
1.0 three times identically; the unmodified snapshot fails hidden but passes
regression. Difficulty spans 2–5.

## Agents

- `MockAgent` / `SequenceAgent` / `ScriptAgent` — deterministic, for tests/demos.
- `OllamaAgent` — a real local-LLM coding agent over Ollama (offline, open weights).
- `OpenAICompatAgent` — talks to any OpenAI-compatible server (LM Studio, llama.cpp,
  vLLM, Ollama's `/v1`). No lock-in to one backend.

## Latest evaluation

The DB contains 600 real model runs: all five local models have exactly 5 runs
on each of 24 tasks (120 persisted rows/model). Oracle and noop are generated
only as explicitly labeled synthetic comparison baselines; no model cells are
gap-filled or reconstructed.

```
rank  agent                          n  p_hat    LCB
   1  oracle (synthetic baseline)  120  1.000  0.969
   2  qwen2.5-coder:7b             120  0.558  0.469
 3-4  deepseek-coder:6.7b          120  0.233  0.167
 3-5  llama3.2:latest              120  0.183  0.124
 4-5  qwen2.5-coder:3b             120  0.150  0.097
   6  gemma2:2b                    120  0.033  0.013
   7  noop (synthetic baseline)    120  0.000  0.000
```

Honest behaviors on display: ranks 3–5 cluster (overlapping Wilson intervals —
the math won't fake a separation; the re-grade reshuffled their order without
truly separating them — `llama3.2` now edges `qwen2.5-coder:3b`);
`deepseek-coder` is strongest on performance/security and weakest on async/api
(domain scoring surfaces what one number hides). Infrastructure failures (model
server unreachable) are voided, never counted against an agent.

Evaluation provenance (per-run config is not yet uniformly captured — see the
roadmap): the P0 completion runs used Ollama 0.17.4, temperature 0.8, base seed
42, `qwen2.5-coder:7b` digest `dae161e27b0e`, and `llama3.2:latest` digest
`a80c4f17acd5`.

These numbers reflect the full re-grade across all 24 tasks, each at its current
task version. The report generator refuses to pool runs from different task
versions within a cell, so no superseded-version rows leak into the leaderboard;
every task's runs (including the strengthened `async-batched`, `top-k-frequent`,
and `refactor-order-validation` oracles) are at that task's current version. The
table is regenerated from `reports/runs.sqlite` by `examples/report_combined.py`.

## Quickstart

```bash
python3 -m pytest                                         # full suite (kernel + runner)
PYTHONPATH="kernel:runner" python3 examples/run_demo.py   # deterministic end-to-end demo

# Real-agent evaluation (needs a local Ollama with the model pulled):
ollama pull qwen2.5-coder:7b
ollama pull llama3.2:latest
PYTHONPATH="kernel:runner" python3 examples/eval_persist.py <model> 5  # resumable
python3 examples/report_combined.py                       # build reports/leaderboard.html
open reports/leaderboard.html                            # the visual report
```

## Run the local app (one command)

A browser app to **explore** the results and **run new evaluations** against a
local model — no juggling separate terminals.

```bash
# Double-click start.command (macOS), or from any shell:
python3 afa_app.py
```

It builds the UI on first run, starts the API + background worker, serves
everything on **one port**, and opens your browser at **http://localhost:8000**.
Press Ctrl-C to stop.

- **Browse** the leaderboard, domain matrix, and per-run drill-downs over the
  existing 600 runs — no model needed.
- **Run a new evaluation** from the wizard: pick a local backend (Ollama, or any
  local OpenAI-compatible server), choose models / tasks / repeats, and watch
  live progress; results land on the leaderboard.

The app works on a **copy** of the evidence DB (`reports/app.sqlite`,
git-ignored); the committed `reports/runs.sqlite` is never mutated. Running new
evaluations needs a local model backend, e.g. `ollama serve` with a model pulled
(`ollama pull qwen2.5-coder:7b`). It is a trusted, single-user, local tool: it
runs agent code with host privileges and makes no untrusted-agent isolation
claims — don't point it at untrusted models or tasks.

## …or with Docker Compose

The local app packages the SPA (`web/`), the FastAPI app (`afa_api/`), and the
background evaluation worker behind one port. Ollama runs on the **host** by
default; nothing is sandbox-isolated — this is a trusted, single-user, local
tool that runs agent code with host privileges.

```bash
# 1. Install Docker. (Optional) install + start Ollama and pull a model:
ollama pull qwen2.5-coder:7b

# 2. From a fresh clone, launch the app:
docker compose up --build

# 3. Open the app:
#    http://localhost:8080
```

Services: `web` (nginx serving the built SPA + proxying `/api`), `api`
(`uvicorn afa_api.main:app`), `worker` (`python -m afa_api.worker`). The shared
WAL DB and report projection live under `./reports` (bind-mounted, so results
stay visible in the repo). All published ports bind to `127.0.0.1` only.

```text
http://localhost:8080            # the app (web)
http://localhost:8000/api/v1/healthz   # api health (direct/debug)
```

Model backend (LOCAL servers only — no hosted/paid APIs). Defaults to host
Ollama at `http://host.docker.internal:11434`. Override via `.env` (copy from
`.env.example`) or inline:

```bash
OLLAMA_BASE_URL=http://host.docker.internal:11434 docker compose up --build
```

Optional: run Ollama in a container instead of on the host:

```bash
docker compose --profile ollama up --build
# then point the app at it:
OLLAMA_BASE_URL=http://ollama:11434 docker compose --profile ollama up
```

Without Ollama you can still launch the app, browse existing results, and run a
mock job.

## How it works (one run)

```
agent edits a fresh copy of the task snapshot
  -> capture diff (scope-checked against protected + always-protected paths)
  -> CLEAN ROOM: apply ONLY the diff to a pristine snapshot, run regression then
     hidden tests (pytest JUnit XML), build gates + hidden results
  -> kernel.score_run:  S = G · T_hidden · (0.85 + 0.15·Q),  X = functional pass
  -> persist score + patch + per-test outcomes (SQLite raw layer)
  -> aggregate n runs ; rank by Wilson lower bound
```

The clean room is security-critical: the agent's environment never touches
grading, and auto-executed files (`conftest.py`, `sitecustomize.py`, `*.pth`, …)
are always-protected so an agent cannot run code inside the grader.

## Not done yet (the road ahead)

A hardened Docker sandbox for **untrusted** agents (the `Sandbox` interface has a
`LocalSandbox`; a `DockerSandbox` is a drop-in — out of scope for the trusted
local tool), live Postgres wiring (DDL is provided), and the later-version math
(Jeffreys/bootstrap, IRT/Bayesian difficulty, Pareto/multi-objective). The web
dashboard and the eval-running app now ship (`afa_api/` + `web/`). See
`docs/EVALUATION_FRAMEWORK.md` §11 and `DEVLOG.md`.
