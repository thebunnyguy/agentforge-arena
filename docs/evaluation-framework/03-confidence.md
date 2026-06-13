## 3. Confidence and uncertainty

Every number AgentForge Arena displays is an estimate from a small sample, and the platform treats it that way: no point estimate is ever rendered without its interval, and the leaderboard ranks by the interval's lower bound, not the point estimate. This section fixes the interval machinery for v0.1 and v0.2, the display rules, and the self-test that guards the interval implementation — and is explicit about what that test does and does not certify.

### 3.1 Wilson score interval (v0.1 workhorse)

For an agent a on task t with n valid runs and c functional passes (p-hat = c/n), the 95% Wilson score interval is:

```
center = (p-hat + z^2/(2n)) / (1 + z^2/n)

halfwidth = z * sqrt( p-hat*(1 - p-hat)/n + z^2/(4n^2) ) / (1 + z^2/n)

interval = [center - halfwidth, center + halfwidth]
```

Symbols: p-hat = c/n is the observed pass rate; n is the number of VALID runs (INFRA_FAILURE runs are voided and excluded; TIMEOUT and AGENT_ERROR count in n with X = 0); z = 1.96 is the standard-normal 97.5% quantile for a 95% interval.

Why Wilson and not the textbook Wald interval `p-hat +/- z*sqrt(p-hat(1-p-hat)/n)`:

- **Wald collapses at the extremes.** At p-hat = 0 or 1, `p-hat(1-p-hat) = 0`, so Wald reports a zero-width interval — absolute certainty from, say, 3 runs. Wilson at c = n = 3 reports [0.4385, 1.0]: honestly wide.
- **Wald escapes [0,1].** For n = 5, c = 3: Wald gives 0.6 +/- 1.96*sqrt(0.048) = [0.1706, 1.0294] — an upper bound above 1 for a probability.
- **Wald undercovers badly at small n.** Its empirical coverage at n <= 10 routinely drops to 80–90% against the nominal 95%. Wilson stays near nominal across the whole (n, p) grid (verified in 3.7).
- Wilson is a closed-form inversion of the score test — explainable, dependency-free, and trivially implementable in SQL or Python. Clopper–Pearson ("exact") was considered and **rejected**: it is conservative by construction (often 98–99% actual coverage), so its extra width costs ranking resolution without buying honesty.

**Contract anchor, step by step (n = 5, c = 3, p-hat = 0.6, z = 1.96):**

```
z^2          = 3.8416
z^2/(2n)     = 3.8416/10  = 0.38416
z^2/n        = 3.8416/5   = 0.76832

center       = (0.6 + 0.38416) / (1 + 0.76832)
             = 0.98416 / 1.76832 = 0.55655

inside sqrt  = 0.6*0.4/5 + 3.8416/(4*25)
             = 0.048 + 0.038416 = 0.086416
sqrt         = 0.29397
halfwidth    = 1.96 * 0.29397 / 1.76832 = 0.32583

interval     = [0.55655 - 0.32583, 0.55655 + 0.32583]
             = [0.2307, 0.8824]
```

This matches the contract anchor exactly. Note the center 0.5566 is pulled toward 0.5 relative to p-hat = 0.6 — Wilson has mild shrinkage built in, a preview of the explicitly Bayesian treatment below.

### 3.2 Jeffreys posterior and shrunk point estimates (v0.2)

v0.2 adds the Bayesian companion. With the Jeffreys prior Beta(0.5, 0.5), the posterior after observing c passes in n runs is:

```
p | data  ~  Beta(c + 0.5, n - c + 0.5)

posterior mean (shrunk point estimate):  p-tilde = (c + 0.5) / (n + 1)

95% equal-tailed credible interval: [Beta.ppf(0.025, c+0.5, n-c+0.5),
                                     Beta.ppf(0.975, c+0.5, n-c+0.5)]
```

Symbols: Beta(alpha, beta) is the Beta distribution; Beta.ppf(q, alpha, beta) is its q-quantile (scipy.stats.beta.ppf, computed offline — no network needed).

**Anchor (n = 5, c = 3):** posterior is Beta(3.5, 2.5); posterior mean = 3.5/6 = **0.5833** (contract anchor); equal-tailed 95% credible interval = [0.2094, 0.9056] — numerically close to Wilson's [0.2307, 0.8824], which is reassuring rather than redundant: two derivations agreeing is a cross-check.

Why shrinkage toward 0.5 is the honest small-n behavior: a 5/5 record yields p-hat = 1.0, but reporting 1.0 claims the agent *never* fails, which 5 observations cannot support. Jeffreys reports p-tilde = 5.5/6 = 0.9167 with credible interval [0.6206, 0.9999] — "probably very good, possibly merely good." The prior contributes exactly one pseudo-observation (0.5 pass + 0.5 fail), so its influence decays as 1/(n+1): at n = 5 it moves the estimate visibly; at n = 100 it is negligible. This is precisely the "useful with small data, more accurate as data grows" requirement, in one formula.

**Decision:** in v0.2 the UI shows p-tilde as the point estimate with the Jeffreys credible interval, but **the leaderboard continues to rank by the Wilson LCB**. Rationale: rankings stay directly comparable across v0.1 and v0.2, and the two lower bounds agree to within ~0.06 at every (n, c) we display (the worst gaps are at perfect records, e.g. Wilson 0.5655 vs Jeffreys 0.6206 at 5/5), so little is gained by switching the sort key.

### 3.3 Bootstrap percentile CI for continuous scores (v0.2)

The continuous score S in [0,1] (Section 1: S = G * T_hidden * (0.85 + 0.15*Q)) is not Bernoulli, so binomial intervals do not apply. v0.2 uses the bootstrap percentile method on the mean of S:

```
Given valid run scores S_1..S_n:
  seed = first 8 bytes (big-endian, unsigned) of
         sha256(f"{agent_version_id}|{task_version_id}|{dataset_version}")
  rng  = numpy.random.default_rng(seed)     # PCG64 — the generator is part of the spec
  idx  = rng.integers(0, n, size=(B, n))    # B = 2000 resample rows, one draw call
  m_b  = mean(S[idx[b]]) for b in 1..B
  sort m_1..m_B
  CI = [m_(50), m_(1950)]      # 2.5th and 97.5th percentiles of the 2000 means
```

The generator (PCG64 via `numpy.random.default_rng`), the single `rng.integers(0, n, size=(B, n))` call, and the seed derivation are all pinned because "bootstrap with seed s" does not otherwise name a unique procedure: a different RNG algorithm or draw ordering produces a different CI from the same seed, and the worked numbers below are only reproducible against this exact recipe.

**Worked example.** n = 10 scores: {0.91, 0.88, 0.00, 0.85, 0.93, 0.00, 0.89, 0.90, 0.87, 0.86} (two gate failures zeroed by G). Mean = 0.709, s = 0.3744. Under the pinned procedure with seed 42 (illustrative; production seeds come from the hash derivation above) and B = 2000, the percentile CI is **[0.447, 0.891]**. The asymmetry (wider downward) is correct behavior: resamples that draw the 0.0 outcomes three or four times drag the mean far down, and the percentile method captures that skew where a symmetric mean +/- z*s/sqrt(n) interval would not.

**Honest caveat and decision:** bootstrap percentile CIs undercover at small n — with n = 5 the resampling distribution has only 126 distinct multisets and actual coverage can fall below 90%. Therefore: **bootstrap CIs on mean S are not displayed for n < 10 at all** (the UI shows mean and s as unadorned diagnostics); at n >= 10 the CI is displayed and permanently labeled "approximate (bootstrap)". One deliberate carve-out below n = 10: the one-sided Student-t lower bound conservative_S of Section 2.5 remains displayed at 5 <= n < 10 — it is a labeled v0.1 approximation serving the deployment-floor question, not a coverage-calibrated two-sided interval, and the bootstrap supersedes it once n >= 10. Wilson/Jeffreys pass-rate intervals remain the only coverage-calibrated intervals shown at n < 10.

### 3.4 Uncertainty penalties for free: ranking by the Wilson LCB

The architecture contract (decision 5) ranks leaderboards by the Wilson lower confidence bound. This is the platform's entire small-sample penalty mechanism — no ad-hoc deductions, no minimum-n fudge factors. The LCB *is* the penalty, and it self-removes as evidence accumulates.

**Worked comparison.** Agent A: 3 passes in 3 runs (p-hat = 1.0). Agent B: 18 passes in 20 runs (p-hat = 0.9).

Agent A (n = 3, c = 3):

```
z^2/n  = 3.8416/3 = 1.28053          z^2/(2n) = 0.64027
center = (1.0 + 0.64027)/(1 + 1.28053) = 1.64027/2.28053 = 0.71925
inside sqrt = 1.0*0.0/3 + 3.8416/36 = 0.10671 ; sqrt = 0.32667
halfwidth   = 1.96*0.32667/2.28053  = 0.28075
interval    = [0.4385, 1.0000]   ->  LCB_A = 0.4385
```

Agent B (n = 20, c = 18):

```
z^2/n  = 3.8416/20 = 0.19208         z^2/(2n) = 0.09604
center = (0.9 + 0.09604)/(1 + 0.19208) = 0.99604/1.19208 = 0.83555
inside sqrt = 0.9*0.1/20 + 3.8416/1600 = 0.0045 + 0.0024010 = 0.0069010 ; sqrt = 0.08307
halfwidth   = 1.96*0.08307/1.19208 = 0.13659
interval    = [0.6990, 0.9721]   ->  LCB_B = 0.6990
```

By p-hat, A (1.0) beats B (0.9). By LCB, B (0.6990) correctly ranks above A (0.4385): twenty runs of strong evidence beat three runs of perfect luck. When A accumulates runs and keeps passing (say 19/20), its LCB rises to ~0.76 and it overtakes B on merit. The penalty is automatic, monotone in evidence, and explainable in one sentence on the leaderboard tooltip: "ranked by the worst pass rate still consistent with the data at 95% confidence."

### 3.5 Sample-size-aware display rules

| Condition | Rule |
|---|---|
| n < 5 | "Provisional" badge; **excluded from ranked leaderboards**; cell shows p-hat with Wilson interval, greyed |
| 5 <= n < 10 | Ranked; rendered with wide-interval styling (hatched CI bar) to signal volatility |
| n >= 10 | Full display; bootstrap CI on mean S becomes available (3.3) |
| Hash-verified deterministic agent (contract decision 7) | n = 2; per-task outcome displayed as a degenerate point [X, X] with a "deterministic (hash-verified)" flag instead of a Wilson interval, because the Bernoulli sampling model does not hold for a constant; in pooled domain counts (4.3–4.4) the cell contributes its outcome exactly **once** (n_t = 1, c_t = X) — the second run is hash confirmation, not independent evidence, and counting both would double-count zero-variance runs (an agent passing 20 tasks would post a pooled Wilson LCB of 0.912 at 40/40 vs the honest 0.839 at 20/20), systematically flattering exactly the deterministic agent class. The existing `deterministic` flag routes into the pooling query |
| Always | The interval is rendered adjacent to every point estimate; the API never returns p-hat without (lcb, ucb, n) in the same object |

The exclusion at n < 5 plus LCB ranking is deliberately belt-and-suspenders: LCB already punishes tiny n, but a 1/1 record producing *any* leaderboard position invites screenshots without context.

### 3.6 What works at small n vs what needs more data

| Method | Trustworthy from | Notes |
|---|---|---|
| Wilson interval | n = 1 | Wide but valid; never leaves [0,1] |
| Jeffreys posterior / shrunk mean | n = 1 | Prior = 1 pseudo-observation; honest by construction |
| LCB ranking | n = 1 (display from n = 5) | Penalty is automatic |
| Bootstrap CI on mean S | n >= 10 | Undercovers below; hidden below 10 |
| Stability = max(0, 1 - 2s) | n >= 10 | s at n = 5 is itself extremely noisy (a sample std from 5 points has ~35% relative error); below 10 it is reported as diagnostic-only with a "low-n" flag |
| Rasch / IRT (v1.0) | ~8–10 distinct agent versions, each with broad task coverage | Below that the theta/b decomposition is weakly identified; v1.0 batch job refuses to publish if the agent count is lower |

### 3.7 Coverage self-test: an implementation regression gate

The interval implementation ships with a simulation test that doubles as a unit test of the evaluator:

1. Fix a grid of true pass rates p_true in {0.05, 0.1, 0.2, 0.4, 0.5, 0.6, 0.8, 0.9, 0.95} and sample sizes n in {5, 10, 20, 50}.
2. For each grid cell, simulate M = 10,000 synthetic agents: draw c ~ Binomial(n, p_true) with a fixed RNG seed.
3. Feed each (n, c) through the **production** interval function — the same code path the API uses, imported, not re-derived in the test.
4. Empirical coverage = fraction of the 10,000 intervals containing p_true.
5. Assert: per-cell coverage >= 0.90, and grid-mean coverage in [0.93, 0.97].
6. **Two-stage arm — the procedure production actually runs.** The fixed-n grid above does not match deployment: per decision 7, a cell starts at n = 5 and escalates to n = 10 exactly when 0.2 < p-hat < 0.8. That is data-dependent optional stopping — the cells that get more runs are selected by the interim estimate, and Wilson's coverage guarantees assume n fixed in advance — so fixed-n numbers do not certify the shipped procedure. The harness therefore also simulates the real rule: draw 5, draw 5 more when the interim p-hat lands in the band, and feed the **final** (n, c) through the production interval. Exact enumeration (which M = 10,000 reproduces to Monte-Carlo noise) shows the residual optional-stopping bias is mild and mostly favorable on this grid: coverage dips slightly inside the band (0.9874 vs the fixed-n 0.9898 at p_true = 0.4 and 0.6) and *rises* near the band edges, where escalation rescues unlucky n = 5 cells (0.9616 vs 0.9185 at p_true = 0.1); the two-stage grid minimum is 0.9375 at p_true = 0.5. Assert the same per-cell floor >= 0.90 on this arm. **The two-stage number, not the fixed-n number, is the platform's stated coverage.**
7. **Correlated arm — published, not asserted.** Arms 1–6 draw i.i.d. Bernoulli runs, which the Limitations below explicitly disclaim: real runs in a cell share a model snapshot, a prompt, and systematic blind spots. A third arm replaces the binomial with a beta-binomial (a shared latent per-cell pass probability; ICC rho = 0.2 as a plausible reference point) and recomputes coverage through the unchanged production intervals. Coverage degrades exactly as positive correlation predicts — grid-mean roughly 0.89 at n = 5, 0.84 at n = 10, 0.71 at n = 20, with grid minima lower still — and degrades further as rho grows. These numbers ship in the test report alongside the i.i.d. results so that "95%" is never read as a promise about correlated runs; the arm carries no assertion because the true ICC is unknown.

The asymmetric tolerance is intentional: Wilson coverage oscillates with n and p because the binomial is discrete (exact 95% is unattainable for any method), dipping to ~91% at unlucky (n, p) combinations (the fixed-n grid minimum is 91.4% at n = 10, p = 0.05) and overshooting elsewhere. A cell below 0.90 means a bug (wrong z, an off-by-one in c or n, INFRA_FAILURE leaking into n), not statistical bad luck at M = 10,000. To be precise about what passing certifies: arms 1–6 prove the interval *arithmetic* is implemented correctly under the sampling models they simulate — a regression gate on the code, not a coverage guarantee for production data — and arm 7 quantifies how far reality can sit from nominal. The same harness runs against the Jeffreys credible interval in v0.2 and is the regression gate for any future refactor of the scoring service: if someone "optimizes" the interval math and coverage drops, CI fails. Runtime is a few seconds; it runs on every commit, fully offline.

### 3.8 Preview: hierarchical shrinkage (v1.0)

Wilson and Jeffreys treat every (agent, task) cell independently — n = 5 runs is all the evidence a cell ever gets. v1.0 stops wasting the rest of the grid. In the hierarchical model (full specification in Section 6.4), every run is explained by a global agent ability, a partially pooled domain offset, and a task difficulty:

```
logit P(X_ait = 1) = theta_a + gamma_{a,dom(t)} - b_t

gamma_{a,k} ~ Normal(0, tau^2)
```

where theta_a is agent a's global latent ability, gamma_{a,k} is its offset in domain k — shrunk toward 0, i.e. toward the global theta_a, by the learned spread tau — and b_t absorbs task difficulty. A cell with 5 runs borrows strength three ways: theta_a is informed by the agent's entire grid, gamma_{a,dom(t)} by its 40 other runs in the same domain, and b_t by every agent's attempts at task t. Its posterior interval is therefore narrower than the standalone Wilson interval, and *honestly* so — the extra confidence is purchased with real, related evidence, and tau (fitted, not assumed) controls how much borrowing the data actually supports. As data accumulates, all three components (b_t, gamma_{a,k}, theta_a) tighten together. The deterministic v0.1/v0.2 intervals remain published alongside forever; the hierarchical intervals augment, never replace them.

### Limitations

- **Independence is assumed, not guaranteed.** Wilson, Jeffreys, and the bootstrap all treat the n runs as i.i.d. Bernoulli/score draws. Runs share a sandbox image, a model snapshot, and often a wall-clock window; correlated failure modes (a flaky base image, an Ollama model update mid-batch) make intervals anti-conservative. The INFRA_FAILURE voiding policy removes the worst offenders but cannot remove subtle correlation.
- **No exact 95% exists for discrete data.** Wilson's coverage oscillates between roughly 91% and 99% depending on (n, p). We chose oscillation around nominal over Clopper–Pearson's systematic conservatism; that is a defensible trade, not a free lunch.
- **LCB ranking taxes newcomers by design.** A genuinely strong new agent debuts mid-table until it accumulates ~10–20 runs per task. This is the intended behavior, but it must be communicated, or new-agent authors will read it as a bug.
- **The bootstrap struggles with our score distribution specifically.** Gate-zeroed runs make S bimodal (mass at 0 and near 0.9); percentile intervals on bimodal data at n = 10–20 remain rougher than the "approximate" label fully conveys. BCa was considered and deferred — its acceleration estimate is itself unstable at these n.
- **No multiple-comparison correction in v0.x.** A leaderboard shows many 95% intervals simultaneously; the chance that *some* interval misses its truth is much higher than 5%. Pairwise "A beats B" claims should wait for the v1.0 posterior P(theta_a > theta_b) matrix, which handles this coherently.
- **Stability at n = 5 is decoration.** We display it because the contract defines it, but a standard deviation from 5 points is too noisy to compare agents on; the n >= 10 flag mitigates, not eliminates, this.
