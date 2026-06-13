## 11. Implementation roadmap

Each stage is shippable on its own, uses only the data already being collected, and never invalidates earlier data (raw runs are append-only; derived scores are recomputable under a new `formula_version`).

### v0.1 — Honest foundations (buildable by one person in weeks)

**Math shipped:**
- Gated deterministic run score `S = G · T_hidden · (0.85 + 0.15·Q)`; functional pass `X`.
- Repeated runs: n = 5 per (agent, task); deterministic agents detected by transcript hash (n = 2).
- Aggregates: p̂, Wilson 95% interval, mean/median/min/max/s of S, stability = max(0, 1 − 2s), timeout rate, pass@k (unbiased).
- Domain scores: pooled weighted pass rate per domain + Wilson via Kish n_eff; overall = macro-average over domains with ≥ 5 tasks.
- Leaderboard: rank by Wilson LCB; ties when intervals make ordering unjustified; "provisional" badge below n = 5.
- Manual task difficulty (rubric 1–5), displayed but not weighted into scores.

**Systems shipped:** Docker sandbox with pinned digests, clean-room grader (apply diff to pristine snapshot), Postgres-backed job queue (`FOR UPDATE SKIP LOCKED`), run manifests + env_hash, append-only raw tables + `formula_version`-stamped derived tables, golden-solution CI for every task.

**Dependencies:** Python stdlib + scipy (Beta quantiles for later; Wilson is closed-form). No ML libraries. Everything offline.

### v0.2 — Reliability and task quality (after ~3–5 agents × ~30+ tasks of data)

- Jeffreys/Beta-Binomial shrinkage: posterior Beta(c+0.5, n−c+0.5); shrunk point estimate (c+0.5)/(n+1); equal-tailed 95% credible intervals.
- Bootstrap percentile CIs (B = 2000) for continuous scores, labeled approximate below n = 10.
- Empirical difficulty with Laplace shrinkage: `d_t = 1 − (c_pool+1)/(n_pool+2)`.
- Discrimination: corrected point-biserial item-rest correlation; task-health flags (too easy > 0.9, too hard < 0.1, non-discriminative |r_pb| < 0.2, negative discrimination r_pb < −0.1 → auto-quarantine, flaky-grader quarantine, overfittable via metamorphic delta > 0.3).
- Task lifecycle: candidate → calibrating → active → quarantined → retired.
- Difficulty-weighted domain scores (w_t = 0.5 + d_t) with leave-one-agent-out difficulty to break circularity.
- Pareto dashboard + ε-constraint queries; metamorphic variants and contamination scores.

### v1.0 — Serious leaderboard math (after ~8–10 distinct agent versions with broad coverage)

- Hierarchical Bayesian Rasch, fit offline nightly in PyMC (NUTS):
  `logit P(X_ait = 1) = θ_a + γ_{a,dom(t)} − b_t`, with θ_a ~ N(0,1), b_t ~ N(0,1.5²), γ ~ N(0,τ²), τ ~ HalfNormal(0.5).
- Outputs: posterior credible intervals for abilities and difficulties, per-domain offsets, pairwise P(θ_a > θ_b) matrix, rank clusters (tie unless P(θ_a > θ_b) > 0.75), rank ranges shown as "1–3" not fake total orders.
- IRT-calibrated difficulty replaces empirical difficulty in weighting; 2PL discrimination parameters where data supports them.
- Multi-objective presets with published weights and fixed-anchor normalization; per-domain Pareto frontiers.
- Private eval pack split; cross-version overfit deltas on the dashboard.

### v2.0 — Optional learned components (only after a large run corpus exists)

- Trace-quality classifier trained on accumulated traces (predicting functional pass from process signals) — used for *diagnostics and early-stopping hints*, never for the score.
- Adaptive run allocation: spend the run budget where posterior uncertainty is highest (largest credible-interval width), a bandit-style scheduler on top of the same math.
- Both are additive; the deterministic core remains the score of record.

---

## 12. Final recommendation

### The MVP algorithm stack (build exactly this first)

1. **Run score:** `S = G · T_hidden · (0.85 + 0.15·Q)`; binary `X` for pass.
2. **Repetition:** n = 5 (n = 2 for verified-deterministic agents; n = 10 when 0.2 < p̂ < 0.8).
3. **Confidence:** Wilson 95% interval on p̂:
   `p_L, p_U = [ p̂ + z²/2n ∓ z·√(p̂(1−p̂)/n + z²/4n²) ] / (1 + z²/n)`, z = 1.96.
4. **Ranking:** sort by Wilson lower bound. Conservative by construction; small samples penalize themselves.
5. **Stability:** max(0, 1 − 2s). **Retry value:** pass@k = 1 − C(n−c,k)/C(n,k).
6. **Domains:** pooled weighted pass rates + Kish-n_eff Wilson intervals; macro-average overall.

### The advanced stack (the destination)

Jeffreys shrinkage (v0.2) → empirical difficulty + discrimination filters (v0.2) → hierarchical Bayesian Rasch with credible-interval rank clusters and P(a ≻ b) matrix (v1.0) → Pareto + preset scalarizations for use-case views (v0.2–v1.0). No Elo, no Glicko, no TrueSkill, no LLM judge.

### Minimums (decision, not guidance)

- **Runs per (agent, task):** 5 minimum to appear in rankings; 10 in the high-variance region; 2 for verified-deterministic agents.
- **Tasks per domain:** 5 minimum to display a domain score; 8–10 before treating domain comparisons as meaningful; ~30 tasks overall before the overall leaderboard is worth publishing.
- **Agents for difficulty estimation:** 3 diverse agents before task-health flags activate; 8–10 agent versions before IRT.

### Dashboard: show / don't show

**Show:** pass rate with its interval and n; conservative score (LCB); stability; per-domain radar with CI bands and "insufficient data" cells; Pareto scatter (LCB vs median runtime); task-health flags; run-score distributions (dot plots, not just means); pass@k curves; determinism badges.

**Don't show:** single-run scores as headline numbers; best-case score outside a clearly-labeled diagnostic; mean S without n and interval; a strict total-order leaderboard when intervals overlap (cluster ranks instead); overall scores for agents evaluated on different domain coverage without an incomparability warning; IRT abilities before the agent count supports identification; stability values at n < 10 without a wide-uncertainty marker.

### Biggest mathematical risks (and the built-in mitigations)

1. **Correlated runs.** Runs share the same model and prompt; failures are not independent coin flips. Wilson assumes i.i.d.; intervals can be optimistic. Mitigation: clean sandbox per run (removes environmental correlation), determinism detection (removes the degenerate case), and honest labeling of pass@k extrapolation.
2. **Small-n overconfidence.** Mitigated structurally: LCB ranking, provisional badges, shrinkage estimators, no continuous CIs below n = 10.
3. **Difficulty circularity.** Empirical difficulty comes from the same agents being ranked. Mitigation: leave-one-agent-out weighting in v0.2; joint estimation in v1.0.
4. **Benchmark overfitting over time.** Agents (and their authors) adapt to the pack. Mitigation: private eval pack, metamorphic variants, cross-version overfit deltas, pack versioning that forks score time series.
5. **Quarantine survivor bias.** Quarantining tasks that strong agents fail can drift the pool easier. Mitigation: quarantine requires a *diagnosed defect* (negative discrimination, grader flakiness, ambiguity), never difficulty alone; quarantine log is public.
6. **Aggregation hiding bimodality.** A mean of 0.5 from {0,0,1,1,1} is a different animal than five 0.5s. Mitigation: bimodality flag + distribution dot plots are first-class dashboard citizens.
7. **Goodhart on Q.** Bounded by design: Q moves at most 15% of an already-earned correctness score.

### How to validate that the evaluator itself is trustworthy

1. **Golden solutions:** every task's reference solution must score S = 1.0, three consecutive times, byte-identical — the benchmark's own CI.
2. **Known-bad solutions:** empty diff, revert diff, and a deliberately-wrong patch must score 0 (and fail the right gates).
3. **Synthetic-agent coverage simulation:** simulate agents with known true pass probability p (seeded Bernoulli), run the real aggregation code, and verify Wilson/Jeffreys intervals achieve ~95% empirical coverage and LCB ranking orders the true p values correctly on average. This is a unit test of the statistics.
4. **Sanity orderings:** a ScriptAgent that replays the reference solution must outrank MockAgent everywhere; a known-degraded agent (e.g., the same Ollama model heavily quantized) should rank below its full-precision sibling more often than not.
5. **Grader determinism audits:** weekly sentinel runs (deterministic ScriptAgent on fixed tasks) must reproduce byte-identical scores; deviation = environment drift alarm, results quarantined until resolved.
6. **Recompute reproducibility:** derived scores are recomputable from raw data under a pinned `formula_version`; a recompute that changes any number without a formula change is a release-blocking bug.

### Limitations

This framework measures *benchmark-relative* competence under *this* harness, task pool, and sandbox policy. It cannot certify real-world ability beyond the tasks' coverage, cannot fully escape difficulty/pool circularity at small agent counts, and its intervals lean on conditional-independence assumptions that correlated model failures can violate. Every dashboard number is honest only together with its uncertainty and its n — the framework's job is to make showing them inseparable.
