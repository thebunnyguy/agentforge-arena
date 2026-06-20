# AgentForge Arena — v0.1 Evaluation Kernel

The executable mathematical core of AgentForge Arena. Pure Python standard
library (no third-party runtime dependencies, fully offline). This is **only**
the math: scoring a run, aggregating repeated runs, confidence intervals,
domain profiling, and leaderboard ranking. No dashboard, no Docker, no agents.

Specification: [`../docs/EVALUATION_FRAMEWORK.md`](../docs/EVALUATION_FRAMEWORK.md).

## Layout

```
kernel/
  afa_kernel/
    types.py        # shared dataclasses + enums (the interface contract)
    confidence.py   # §3  Wilson interval, LCB, pass@k, t-critical, stability
    scoring.py      # §1  score one run -> S, X, status
    aggregate.py    # §2  aggregate n repeated runs of one (agent, task)
    domains.py      # §4  per-domain pooled scores + macro overall
    ranking.py      # §6  rank agents by Wilson lower bound (with tie clusters)
  tests/            # pytest suite, including the canonical numeric anchors
```

## Run the tests

```bash
cd kernel
python3 -m pip install pytest      # dev-only dependency
python3 -m pytest
```

## Canonical anchors (must always hold)

- Wilson 95% interval, n=5, c=3  ->  [0.2307, 0.8824]
- Unbiased pass@k, n=5, c=2, k=3 ->  0.9
- Run score  S = G · T_hidden · (0.85 + 0.15·Q)
- Stability  = max(0, 1 − 2s)   (max std of a [0,1] variable is 0.5)

## Scope (v0.1 only)

Implemented: gated deterministic run score, repeated-run aggregation, Wilson
intervals, LCB ranking with tie clustering, macro-averaged domain scores.

Deferred (later versions, NOT here): Jeffreys/Beta-Binomial shrinkage, bootstrap
CIs, empirical/IRT difficulty, hierarchical Bayesian models, Pareto/multi-objective.
