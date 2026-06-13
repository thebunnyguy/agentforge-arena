# AgentForge Arena

Offline-first mathematical benchmarking and observability for code-modifying
agents. The core value is the **evaluation system** — deterministic, statistically
honest, explainable scoring — not the agents. No paid LLM APIs, no LLM-as-judge
in the core path, runs fully offline.

## Status — v0.1 (executable, unit-tested)

```
docs/EVALUATION_FRAMEWORK.md   # the complete mathematical framework (design)
kernel/afa_kernel/             # the math: scoring, aggregation, confidence, domains, ranking
runner/afa_runner/             # orchestration: tasks, agents, sandbox, clean-room grader, store, report
tasks/fix-list-dedup/          # a real benchmark task (buggy dedup)
db/schema.sql                  # production PostgreSQL raw-layer schema
examples/run_demo.py           # end-to-end demonstration
```

Pure Python standard library (plus `pytest` for tests). Tested on Python 3.13.

## Quickstart

```bash
# Run the whole test suite (kernel + runner)
python -m pytest

# Run the end-to-end demo: three agents on the dedup task, leaderboard out
PYTHONPATH="kernel:runner" python examples/run_demo.py
```

Demo output (note the honest small-sample tie — at n=5 a perfect 5/5's lower
bound 0.566 sits below a 3/5's point estimate 0.6, so they share rank 1-2):

```
rank  agent  n  p_hat    LCB
----  -----  -  -----  -----
 1-2  good   5  1.000  0.566
 1-2  seq    5  0.600  0.231
   3  bad    5  0.000  0.000
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
are always-protected so an agent cannot run code inside the grader. Tasks ship a
benchmark CI (`validate_task`): the reference fix must score 1.0 three times
identically; the unmodified snapshot must fail hidden but pass regression.

## What's intentionally NOT in v0.1

Dashboard, Docker sandbox (the `Sandbox` interface has a `LocalSandbox`; Docker
is a drop-in later), live Postgres wiring (DDL is provided), and all later-version
math (Jeffreys/bootstrap, IRT/Bayesian difficulty, Pareto/multi-objective). See
`docs/EVALUATION_FRAMEWORK.md` §11 for the staged roadmap.
