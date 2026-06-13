## 2. Repeated-run aggregation

A single run of a stochastic agent is an anecdote. This section fixes how AgentForge Arena turns n repeated runs of one (agent, task) pair into a small set of aggregates, what each aggregate is allowed to claim, and which aggregates are headline versus diagnostic. Per the architecture contract, n = 5 by default, escalating to n = 10 when 0.2 < p-hat < 0.8; INFRA_FAILURE runs are voided and excluded from n; TIMEOUT and AGENT_ERROR runs are valid failures inside n.

All formulas below operate on the multiset of valid runs {(S_1, X_1), ..., (S_n, X_n)} where S_i in [0,1] is the gated run score and X_i in {0,1} is functional pass.

### 2.1 Running example: one (agent, task) cell

Every aggregate in this section is computed from this single table so the numbers can be cross-checked end to end. Agent a ran task t; 6 sandbox attempts occurred, 1 was voided as INFRA_FAILURE (network blip pulling the base image) and auto-retried successfully, leaving n = 5 valid runs.

| Run i | Status      | G | T_hidden | Q    | S_i = G * T_hidden * (0.85 + 0.15Q) | X_i |
|-------|-------------|---|----------|------|--------------------------------------|-----|
| 1     | VALID       | 1 | 1.00     | 0.60 | 0.94                                 | 1   |
| 2     | VALID       | 1 | 0.40     | 0.00 | 0.34                                 | 0   |
| 3     | VALID       | 1 | 1.00     | 0.40 | 0.91                                 | 1   |
| 4     | TIMEOUT     | 0 | —        | —    | 0.00                                 | 0   |
| 5     | VALID       | 1 | 1.00     | 0.80 | 0.97                                 | 1   |

So the score multiset is {0.94, 0.34, 0.91, 0.00, 0.97}, c = 3 passes, n = 5.

### 2.2 Location and spread of S

**Mean.**

```
mean(S) = (1/n) * sum_{i=1..n} S_i
```

Worked: (0.94 + 0.34 + 0.91 + 0.00 + 0.97) / 5 = 3.16 / 5 = **0.632**.

**Sample variance and standard deviation (Bessel-corrected, n-1 denominator).**

```
s^2 = (1/(n-1)) * sum_{i=1..n} (S_i - mean(S))^2
s   = sqrt(s^2)
```

Worked: deviations from 0.632 are (0.308, -0.292, 0.278, -0.632, 0.338); squared sum = 0.094864 + 0.085264 + 0.077284 + 0.399424 + 0.114244 = 0.771080; s^2 = 0.771080 / 4 = **0.19277**; s = **0.4391**. Bessel correction is mandatory: at n = 5 the biased (1/n) estimator understates spread by a factor of sqrt(4/5) ≈ 0.894 — about 11% low — which is exactly the regime this platform lives in.

**Median.** Sorted scores: (0.00, 0.34, 0.91, 0.94, 0.97); median = **0.91** (middle element for odd n; average of the two middle elements for even n). Note the median (0.91) and mean (0.632) disagree badly here — that disagreement is itself a signal (see 2.8).

**Min — worst case.** min(S_i) = **0.00**. This is the "what is the worst thing this agent did on this task" number; it is what an operator deploying the agent once, unsupervised, should fear.

**Max — best case.** max(S_i) = **0.97**. This is explicitly labeled a **cherry-picking hazard**: it is the number a demo reel would show and the number the leaderboard must never use. It answers "what can this agent do with unlimited retries and an oracle selecting the winner," which no deployment has. It is stored, displayed last, and never ranked on.

### 2.3 Rate metrics

**Pass rate.**

```
p-hat = c / n
```

Worked: 3/5 = **0.6**. Its Wilson 95% interval (formula in Section 3) is **[0.2307, 0.8824]** — the contract anchor. The width of that interval at n = 5 is the entire argument for repeated runs and for LCB ranking.

**Timeout rate.**

```
timeout_rate = (# TIMEOUT runs) / n
```

Worked: 1/5 = **0.2**. Timeouts are inside n (they are valid failures) but tracked separately because a 20% timeout rate and a 20% wrong-answer rate demand different fixes (budget/looping vs capability).

**Infra-void rate.** Let v = number of attempts voided as INFRA_FAILURE.

```
infra_void_rate = v / (n + v)
```

Worked: 1/6 = **0.1667**. This is a *harness health* metric, not an agent metric: voided attempts never enter n. Decision: if infra_void_rate > 0.2 over any batch, the batch is flagged and the infrastructure — not the agent — is investigated; per the contract each infra failure is auto-retried up to 2 times and alerts after.

### 2.4 Retry success: unbiased pass@k

"Retry success" answers: if we deployed this agent on this task and allowed up to k independent attempts, taking the first pass, what is the probability of success? We use the unbiased estimator (Chen et al. 2021 style), never the naive 1 - (1 - p-hat)^k plug-in, which is biased downward for small n:

```
pass@k = 1 - C(n - c, k) / C(n, k)        (defined only for k <= n)
```

where C(.,.) is the binomial coefficient and C(m, k) = 0 when k > m. It is the exact probability that a uniformly random size-k subset of the n observed runs contains at least one pass.

Contract anchor, reproduced: n = 5, c = 2, k = 3:

```
pass@3 = 1 - C(3,3)/C(5,3) = 1 - 1/10 = 0.9
```

Running example (n = 5, c = 3):

```
pass@1 = 1 - C(2,1)/C(5,1) = 1 - 2/5  = 0.6   (equals p-hat, as it must)
pass@2 = 1 - C(2,2)/C(5,2) = 1 - 1/10 = 0.9
pass@3 = 1 - C(2,3)/C(5,3) = 1 - 0    = 1.0
```

Decision: we report pass@k for k in {1, 2, 3} at n = 5 (adding k = 5 at n = 10) and never for k > n.

**Independence caveat (mandatory in UI copy).** The estimator is unbiased only if runs are i.i.d., and runs are conditionally i.i.d. *only given a clean sandbox per run* — which the harness guarantees mechanically. What it cannot guarantee is independence of the agent's failure modes: the same weights, same prompt, and same systematic blind spot make failures correlated across retries. The pass@3 = 1.0 above is exact *within the observed sample* (every 3-subset of these 5 runs contains a pass) but as a forecast of three fresh retries it is optimistic. Treat pass@k as an in-sample summary, not an extrapolation; extrapolated retry claims beyond observed n are forbidden in the product.

### 2.5 Conservative score

Two tracks, both answering "what is this agent *at least* good for, with 95% confidence?"

**Binary track:** the Wilson 95% lower confidence bound (LCB) on p-hat — formula and worked anchor in Section 3. For the running example: LCB = **0.2307**.

**Continuous track:** a one-sided lower confidence bound on the mean of S using Student's t, because n is small and the population variance is unknown — z = 1.96 would be falsely tight at n = 5:

```
conservative_S = max(0, mean(S) - t_{0.95, n-1} * s / sqrt(n))

t_{0.95, 4} = 2.132   (n = 5)
t_{0.95, 9} = 1.833   (n = 10)
```

Worked (running example): 0.632 - 2.132 * 0.4391 / sqrt(5) = 0.632 - 2.132 * 0.19635 = 0.632 - 0.4186 = **0.2134**. The clamp at 0 matters: high-variance cells at n = 5 routinely go negative, and a negative lower bound on a [0,1] score is noise, not information. (S is bounded and non-normal, so the t interval is an approximation; v0.2 replaces it with the bootstrap percentile CI, B = 2000, per the staging contract — the t bound is the v0.1 stand-in and is labeled as such.)

### 2.6 Stability

```
stability = max(0, 1 - 2s)
```

Rationale: a [0,1]-bounded variable has maximum possible standard deviation 0.5 (achieved by a 50/50 mass at 0 and 1), so 2s maps spread onto [0,1] and the complement reads as "fraction of maximal consistency." Worked: s = 0.4391 gives stability = max(0, 1 - 0.8781) = **0.1219**; an agent with s = 0.05 would score 0.90.

Operational meaning: stability is the *predictability of a single deployment*. Stability 0.9 means one run tells you nearly everything; stability 0.12 (our example) means a single run of this agent on this task is close to a coin flip over outcome quality, and any single-run evaluation of it is meaningless. Stability deliberately ignores *where* the scores sit — an agent that reliably scores 0.0 has stability 1.0. It is a consistency axis, never a quality axis, which is why it ranks below pass rate and conservative score in 2.9.

### 2.7 Reliability vs stability vs pass rate

Three different words for three different failure surfaces; conflating them hides failure modes.

```
reliability = (# valid runs with status not in {TIMEOUT, AGENT_ERROR}) / n
```

- **Reliability** = operational completion: did the agent finish its attempt without timing out or crashing? Running example: run 4 timed out, so reliability = 4/5 = **0.8**.
- **Pass rate** = functional correctness of the attempt: p-hat = 0.6.
- **Stability** = consistency of the score across attempts: 0.1219.

The gap reliability - p-hat = 0.2 here is run 2: the agent completed cleanly and was simply wrong. An agent with reliability 1.0 and p-hat 0.4 needs capability work; an agent with reliability 0.4 and p-hat 0.4 needs harness-interaction or robustness work (every completed run passed). A single blended number would render these two opposite diagnoses identical. All three are therefore reported side by side on the cell detail view.

### 2.8 Determinism detection and distribution honesty

**Determinism.** Each run records h_i = SHA-256(command transcript || final unified diff). If all n hashes are identical, the agent is deterministic on this task: per the contract, 2 confirming runs suffice thereafter, and s = 0 is reported as **variance 0-by-construction** with an explicit `deterministic` flag. The flag exists so that a ScriptAgent's stability 1.0 is never read as the same achievement as a stochastic LLM agent earning stability 1.0 across genuinely independent samples — the first is a property of the artifact, the second is evidence about a distribution.

**Distribution honesty.** The full run-score multiset is always stored and rendered (n is small; there is no excuse to show only moments). The mean of a bimodal distribution is a fiction: for the multiset {0.97, 0.94, 0.96, 0.02, 0.00} (c = 3), mean(S) = 0.578 describes *no run that ever happened* — the agent either nails the task or produces nothing. Bimodality flag (cheap, deterministic):

```
bimodal := max(c, n - c) < n            (both outcome groups non-empty)
           AND min{S_i : X_i = 1} > 0.9
           AND max{S_i : X_i = 0} < 0.1
```

That multiset trips the flag (passes {0.97, 0.96, 0.94} all > 0.9; fails {0.02, 0.00} all < 0.1); when flagged, the UI suppresses the mean as a summary and leads with p-hat plus the two cluster centers. The running example of 2.1 does *not* trip it (fail score 0.34 is partial progress, not collapse), correctly distinguishing "all-or-nothing" from "sometimes gets halfway."

### 2.9 Which aggregates matter, ranked

1. **Pass rate p-hat with Wilson 95% CI** — the headline. Functional correctness with honest uncertainty; the only number that feeds leaderboard ranking (via the LCB, Section 3).
2. **Conservative score** (Wilson LCB / t-lower-bound) — the deployment-decision number: what you can count on, not what you hope for.
3. **Stability** — whether one observation generalizes; gates how much to trust any single-run anecdote about this agent.
4. **Median S** — robust typical quality, immune to the one zero or the one fluke; preferred over the mean whenever the bimodality flag is up.
5. **Min S (worst case)** — tail risk for unsupervised single-shot use.
6. **Max S (best case) — last, diagnostic only.** Shows headroom under oracle selection; a cherry-picking hazard that never appears in rankings or summaries.

The mean of S is computed and stored but ranks below the median in presentation priority because at n = 5 it is dominated by single outliers and lies under bimodality.

### 2.10 Aggregate summary of the running example

| Aggregate            | Value              |
|----------------------|--------------------|
| n (valid runs)       | 5                  |
| mean(S)              | 0.632              |
| s^2 / s              | 0.19277 / 0.4391   |
| median(S)            | 0.91               |
| min(S) (worst case)  | 0.00               |
| max(S) (best case, diagnostic) | 0.97     |
| p-hat (Wilson 95%)   | 0.6 [0.2307, 0.8824] |
| timeout rate         | 0.2                |
| infra-void rate      | 0.1667 (1 of 6 attempts) |
| pass@1 / pass@2 / pass@3 | 0.6 / 0.9 / 1.0 |
| conservative_S (t, one-sided 95%) | 0.2134 |
| stability            | 0.1219             |
| reliability          | 0.8                |
| deterministic flag   | false (5 distinct transcript hashes) |
| bimodality flag      | false              |

Implementation note: every aggregate above is a pure function of the stored run rows; all are computed in SQL or trivially in Python at read time and materialized per (agent, task) cell on run completion. No aggregate requires more state than (n, c, the S multiset, statuses, hashes).

### Limitations

- **n = 5 is thin.** Every interval here is wide by construction; the Wilson CI on p-hat = 0.6 spans 0.65 of probability mass. The escalation rule to n = 10 narrows but does not solve this; conclusions at the cell level are coarse until v0.2 shrinkage (Jeffreys) pools strength across the grid.
- **The t-based conservative_S assumes approximate normality of the sample mean.** S is bounded, often skewed, and sometimes bimodal at n = 5; the bound is a labeled approximation until the v0.2 bootstrap replaces it.
- **pass@k cannot see correlated failures.** It is exact in-sample, but agents fail for systematic reasons; real retry success at k > 1 will generally be below the reported value, and we have no offline way to estimate the correlation at n = 5.
- **The bimodality flag is deliberately crude.** Thresholds 0.9/0.1 catch the all-or-nothing pattern but miss trimodal or smeared distributions; it is a UI honesty trigger, not a statistical test (a dip test is unjustifiable at n = 5).
- **Determinism is per-task, not global.** Identical hashes on one task do not prove the agent deterministic elsewhere; the flag must be re-earned per (agent, task) cell, and transcript hashing is sensitive to benign nondeterminism (timestamps in tool output) that the harness must canonicalize away or the flag will under-fire.
- **Stability conflates sources of variance.** Sandbox-level noise (flaky tests already gated, but also resource jitter affecting Q) and genuine agent stochasticity both land in s; the metric cannot apportion blame between them.
