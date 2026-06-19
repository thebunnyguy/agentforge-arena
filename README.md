# AgentForge Arena

Offline-first mathematical benchmarking and observability for code-modifying
agents. The core value is the **evaluation system** — deterministic, statistically
honest, explainable scoring — not the agents. No paid LLM APIs, no LLM-as-judge
in the core path, runs fully offline.

## Status — v0.2 in progress (offline, executable, 341 tests)

```
docs/EVALUATION_FRAMEWORK.md   # the complete mathematical framework (design)
kernel/afa_kernel/             # the math: scoring, aggregation, confidence, domains, ranking
runner/afa_runner/             # tasks, agents, sandbox, clean-room grader, store, report
tasks/                         # 24 benchmark tasks across 5 domains (+ manifest.json)
db/schema.sql                  # production PostgreSQL raw-layer schema
examples/                      # run_demo, eval_pack, eval_persist, report_combined, ...
reports/leaderboard.html       # generated visual report (gitignored)
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

Every task passes the §8 benchmark CI (`validate_task`): the reference fix scores
1.0 three times identically; the unmodified snapshot fails hidden but passes
regression. Difficulty spans 2–5.

## Agents

- `MockAgent` / `SequenceAgent` / `ScriptAgent` — deterministic, for tests/demos.
- `OllamaAgent` — a real local-LLM coding agent over Ollama (offline, open weights).
- `OpenAICompatAgent` — talks to any OpenAI-compatible server (LM Studio, llama.cpp,
  vLLM, Ollama's `/v1`). No lock-in to one backend.

## Latest evaluation (5 local models, 24 tasks, n=5 each → 120 runs/model)

```
rank  agent                 p_hat   Wilson LCB
  1   oracle (reference)    1.000     0.969
  2   qwen2.5-coder:7b      0.567     0.477
 3-4  deepseek-coder:6.7b   0.317     0.240
 3-5  qwen2.5-coder:3b      0.267     0.196
 4-5  llama3.2:3b           0.217     0.152
  6   gemma2:2b             0.050     0.023
```

Honest behaviors on display: ranks 3–5 cluster (overlapping intervals — the math
won't fake a separation); `deepseek-coder` is strong on security/performance but
weak on api/backend (domain scoring surfaces what one number hides); a stronger,
newer model can beat a larger older one. Infrastructure failures (model server
unreachable) are voided, never counted against an agent.

## Quickstart

```bash
python -m pytest                                         # full suite (kernel + runner)
PYTHONPATH="kernel:runner" python examples/run_demo.py   # deterministic end-to-end demo

# Real-agent evaluation (needs a local Ollama with the model pulled):
PYTHONPATH="kernel:runner" python examples/eval_persist.py <model> 5   # one model, resumable
python examples/report_combined.py                       # build reports/leaderboard.html
open reports/leaderboard.html                            # the visual report
```

## How it works (one run)

```
agent edits a fresh copy of the task snapshot
  -> capture diff (scope-checked against protected + always-protected paths)
  -> CLEAN ROOM: apply ONLY the diff to a pristine snapshot, run regression then
     hidden tests (pytest JUnit XML), build gates + hidden results
  -> kernel.score_run:  S = G · T_hidden · (0.85 + 0.15·Q),  X = functional pass
  -> persist (SQLite raw layer) ; aggregate n runs ; rank by Wilson lower bound
```

The clean room is security-critical: the agent's environment never touches
grading, and auto-executed files (`conftest.py`, `sitecustomize.py`, `*.pth`, …)
are always-protected so an agent cannot run code inside the grader.

## Not done yet (the road ahead)

Docker sandbox (the `Sandbox` interface has a `LocalSandbox`; Docker is a drop-in),
live Postgres wiring (DDL is provided), a web dashboard (beyond the static HTML
report), and the later-version math (Jeffreys/bootstrap, IRT/Bayesian difficulty,
Pareto/multi-objective). See `docs/EVALUATION_FRAMEWORK.md` §11 and `DEVLOG.md`.
