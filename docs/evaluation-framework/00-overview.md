# AgentForge Arena — Mathematical Evaluation Framework

**Status:** founding design document
**Scope:** the complete scoring, aggregation, confidence, difficulty, ranking, and validity math for evaluating code-modifying agents offline.

---

## 0. Overview and design principles

AgentForge Arena evaluates code-modifying agents (MockAgent, ScriptAgent, local CLI agents, Ollama-served LLM agents, optional external API agents later) on software-engineering tasks executed in controlled sandboxes. This document defines the mathematics of that evaluation. Five principles govern every choice:

1. **Deterministic core.** Every score is computed by an explainable formula from observable artifacts (test results, diffs, traces). No LLM-as-judge anywhere in the core path. A score can always be decomposed back into the signals that produced it.
2. **Honesty over precision.** A number shown without its uncertainty is a lie of omission. Every displayed estimate carries an interval, a sample size, or an "insufficient data" badge. The framework prefers admitting ignorance to fabricating confidence.
3. **Small-data first, more accurate with scale.** v0.1 methods (Wilson intervals, conservative lower-bound ranking, macro-averaged domains) are valid at n = 5 runs. As run counts and agent counts grow, the same data feeds progressively stronger machinery (Beta-Binomial shrinkage → hierarchical Bayesian Rasch) without changing what is collected.
4. **Offline and reproducible.** Everything runs without internet or paid APIs: pinned Docker images, local package mirrors, PyMC for Bayesian fits as offline batch jobs, content-addressed artifacts, environment hashes.
5. **The grader is also under test.** The framework includes machinery for validating itself: golden-solution suites, grader-determinism checks, synthetic-agent coverage simulations, and append-only raw data with versioned, recomputable derived scores.

### The score architecture in one page

A single run is scored as:

```
S = G · T_hidden · (0.85 + 0.15·Q)
```

- `G ∈ {0,1}` — product of hard **gates**: setup succeeded (agent-attributable), a diff exists, no protected paths touched, the regression suite still passes, no timeout. Any gate failure → S = 0.
- `T_hidden ∈ [0,1]` — weighted fraction of **hidden tests** passed, graded in a clean room (the captured diff is applied to a pristine snapshot in a separate grader sandbox; the agent never sees hidden tests).
- `Q ∈ [0,1]` — bounded **quality** modifier (lint, typecheck, static-analysis delta, security-scan delta, diff parsimony). Quality scales correctness between 85% and 100% of itself; it can never substitute for correctness.
- **Functional pass** `X = 1` iff all gates pass AND all hidden tests pass. Runtime, cost, and memory are never inside S — they are separate axes for multi-objective comparison.

Across `n` repeated runs (default 5, escalated to 10 in the high-variance region 0.2 < p̂ < 0.8):

- **Headline:** pass rate `p̂ = c/n` with its **Wilson 95% interval**; leaderboards rank by the **Wilson lower bound**.
- **Stability** = max(0, 1 − 2s), where s is the sample standard deviation of S (max possible std of a [0,1] variable is 0.5).
- Mean, median, min, max, pass@k (unbiased estimator) are diagnostics, never the headline.

Domain capability is a **skill vector**, not a single number: tasks carry weighted domain tags (1.0 / 0.5 / 0.25), per-domain pooled pass rates get Wilson intervals via Kish effective sample size, and the "overall" score is a macro-average across domains with ≥ 5 tasks — always labeled as a benchmark-relative convenience, never a universal ability.

Task difficulty starts manual (1–5 rubric), becomes empirical (shrunk pooled failure rates + discrimination flags) in v0.2, and is jointly estimated with agent ability in v1.0 via a hierarchical Bayesian Rasch model:

```
logit P(X_ait = 1) = θ_a + γ_{a,dom(t)} − b_t
```

fit offline with PyMC, producing credible intervals and a pairwise P(θ_a > θ_b) matrix. Elo/Glicko/TrueSkill are deliberately rejected (wrong fit for a static agent-by-task grid); Bradley-Terry applied to agent-vs-task outcomes *is* the Rasch model, so v1.0 subsumes it.

### Notation used throughout

| Symbol | Meaning |
|---|---|
| `a`, `t`, `i` | agent, task, run index |
| `n` | number of VALID runs of agent a on task t |
| `c` | number of functionally passing runs among them |
| `X_i ∈ {0,1}` | functional pass of run i |
| `S_i ∈ [0,1]` | continuous score of run i |
| `p̂ = c/n` | empirical pass rate |
| `G`, `T_hidden`, `Q` | gates product, hidden-test fraction, quality score |
| `s` | sample standard deviation (Bessel-corrected, n−1) |
| `z` | 1.96 (95% two-sided normal quantile) |
| `b_t`, `θ_a` | task difficulty, agent ability (IRT) |
| `k` | domain index (also: attempt count in pass@k — context disambiguates) |

### Run status taxonomy

| Status | Counted in n? | Score |
|---|---|---|
| VALID | yes | computed |
| TIMEOUT | yes | failure (0), tracked separately |
| AGENT_ERROR | yes | failure (0) |
| INFRA_FAILURE | **no** — voided, auto-retried ≤ 2×, alert after | none |

Infrastructure failures are the platform's fault, not the agent's; mixing them into agent scores is dishonest and is structurally prevented.

### Document map

| § | File | Covers |
|---|---|---|
| 1 | 01-run-scoring.md | Scoring one run: gates, T_hidden, Q, rejected signals, gameability |
| 2 | 02-repeated-runs.md | Aggregating n runs: pass rate, stability, pass@k, conservative score |
| 3 | 03-confidence.md | Wilson, Jeffreys/Beta-Binomial, bootstrap, LCB ranking, coverage validation |
| 4 | 04-domains.md | Domain × activity taxonomy, skill vectors, per-domain confidence |
| 5 | 05-difficulty.md | Difficulty estimation, discrimination, task-health flags, lifecycle |
| 6 | 06-ranking.md | Ranking algorithm comparison and the staged recommendation |
| 7 | 07-multi-objective.md | Pareto frontiers, ε-constraint queries, use-case presets |
| 8 | 08-benchmark-design.md | Task template, quality gates, anti-gaming defenses |
| 9 | 09-pipeline-reproducibility.md | End-to-end pipeline, sandboxing, manifests, drift detection |
| 10 | 10-data-model.md | PostgreSQL schema, append-only raw / recomputable derived layers |
| 11 | 11-roadmap-and-recommendation.md | v0.1 → v2.0 build plan and the final algorithm stack |
