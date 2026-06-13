## 5. Task difficulty modeling and task health

Difficulty estimation and bad-task detection are the same machinery viewed from two sides: a difficulty estimate tells you where a task sits on the ability scale; a health flag tells you when a task is not measuring ability at all. This section fixes the estimators, the detection thresholds, the task lifecycle, and how difficulty feeds (and does not feed) scoring at each stage.

### 5.1 Six candidate methods, one verdict each

**1. Manual difficulty rubric (1–5).** Task authors score four facets, each 1–5: expected human time, files touched, ambiguity of the spec, domain depth. The task's rubric difficulty is the mean, rescaled to `d_rubric = (mean - 1)/4` in [0,1]. **Verdict: ADOPT in v0.1.** It is the only estimator available pre-data, so it is mandatory for cold start. It is biased (authors systematically misjudge what trips agents — agents fail on tooling friction, not conceptual depth), so from v0.2 onward it is demoted to metadata and a sanity check: if `|d_rubric - d_t| > 0.5`, raise a MISCALIBRATED flag for human review.

**2. Empirical difficulty from pooled pass rates with Laplace shrinkage.** Pool all valid runs across all agents on task t:

```
d_t = 1 - (c_pool + 1) / (n_pool + 2)
```

where `n_pool` = total valid runs on task t across the agent pool, `c_pool` = total functional passes among them. The +1/+2 (Laplace, i.e. Beta(1,1) prior) shrinks toward 0.5 and keeps d_t off the boundary at small n. Worked example: 3 agents x 5 runs each, so n_pool = 15; c_pool = 3 passes. Raw failure rate is 1 - 3/15 = 0.80; shrunk difficulty is `d_t = 1 - (3+1)/(15+2) = 1 - 4/17 = 0.7647`. **Verdict: ADOPT in v0.2 as the primary operational difficulty.** Honest, cheap, explainable — but pool-relative: d_t measures "hard for the agents we happen to have", not absolute difficulty (mitigation in 5.5).

**3. Discrimination score (corrected point-biserial item-rest correlation).** Measures whether task t separates strong agents from weak ones. Defined in 5.2. **Verdict: ADOPT in v0.2 — as a health signal, not a difficulty estimate.** Difficulty says where the task sits; discrimination says whether the task measures anything.

**4. Item Response Theory (Rasch 1PL, then 2PL).** Rasch: `P(X=1) = sigmoid(theta_a - b_t)`. 2PL adds a per-task discrimination slope: `P = sigmoid(a_t * (theta_a - b_t))`, where `a_t > 0` plays the model-based role of r_pb. **Verdict: ADOPT Rasch in v1.0; DEFER 2PL.** Identifiability is the binding constraint: you need roughly >= 8–10 distinct agent versions with broad task coverage before b_t (let alone a_t) is well determined. With 3 agents the Rasch fit is barely identified — the posterior on b_t is essentially the prior plus the pooled pass rate, so do not pretend otherwise; ship it only when the agent roster justifies it. 2PL doubles the parameter count and needs strictly more agents; revisit when >= 15 agent versions exist.

**5. Bayesian task difficulty.** Priors on b_t inside the v1.0 hierarchical model (Section contract, decision 9): `b_t ~ N(0, 1.5^2)` fitted jointly with `theta_a ~ N(0,1)` and domain offsets in PyMC as an offline batch job, yielding posterior credible intervals on every b_t. **Verdict: ADOPT — this IS the recommended v1.0 form.** It is not a competitor to method 4; it is method 4 done correctly: partial pooling keeps low-data tasks sane, and joint estimation resolves the circularity in 5.5.

**6. Task reliability score.** Orthogonal to difficulty: does the task grade deterministically? Two checks, run as a weekly batch job: (a) grader determinism — regrade 3 randomly sampled stored diffs per active task, 2 repeats each, in fresh clean-room sandboxes; (b) golden-solution stability — re-apply the task's reference solution and regrade; it must pass 100% of hidden tests. `R_t = 1` iff both checks passed in the last window, else 0. **Verdict: ADOPT as a binary gate; the weekly job ships in v0.2 with the rest of the task-health machinery.** It does not belong in the v0.1 slice: a scheduler plus recurring clean-room compute is real cost for a one-person build, and the staging contract puts task-health flags in v0.2. The v0.1 determinism guarantee is activation gate 1 (Section 8) — the reference solution must regrade byte-identically 3 consecutive times — re-run manually after any grader-image or dependency change. Reliability is never averaged into anything; a task with R_t = 0 is quarantined, full stop. Any nonzero variance when regrading an identical diff is a harness bug, not a task property.

### 5.2 Discrimination: corrected point-biserial (item-rest) correlation

Unit of analysis is the agent (not the run). For each agent a on task t:

- `X_at in {0,1}`: dichotomized pass — 1 iff agent a's majority of valid runs on t pass (p-hat_at >= 0.5).
- `R_a^(-t)`: rest score — agent a's unweighted mean pass rate over all *active* tasks excluding t. Excluding t is the "corrected" part; including it inflates the correlation, badly so with few tasks.

```
r_pb = (M1 - M0) / s_ability * sqrt(p * (1 - p) * n_agents / (n_agents - 1))
```

- `M1` = mean rest score of agents with X_at = 1
- `M0` = mean rest score of agents with X_at = 0
- `s_ability` = sample standard deviation (Bessel-corrected, n-1 denominator) of rest scores across all agents
- `p` = fraction of agents with X_at = 1
- `n_agents` = number of agents; the `n_agents/(n_agents - 1)` factor makes the formula exactly the Pearson correlation between X_at and R^(-t) given the Bessel-corrected s_ability (without it, every |r_pb| is understated by sqrt((n_agents-1)/n_agents))

r_pb is undefined when all agents pass or all fail (p = 0 or 1) or when s_ability = 0; such tasks skip the discrimination rules and are handled by the TOO EASY / TOO HARD rules in 5.3 instead.

Worked example, 5 agents:

```
Agent   rest score R^(-t)   pass on t
A       0.80                1
B       0.70                1
C       0.55                1
D       0.40                0
E       0.25                0

p  = 3/5 = 0.6
M1 = (0.80 + 0.70 + 0.55)/3 = 0.6833
M0 = (0.40 + 0.25)/2        = 0.3250
mean rest = 0.54
s_ability = sqrt[ (0.26^2 + 0.16^2 + 0.01^2 + (-0.14)^2 + (-0.29)^2) / 4 ]
          = sqrt(0.1970/4) = sqrt(0.04925) = 0.2219

r_pb = (0.6833 - 0.3250)/0.2219 * sqrt(0.6*0.4 * 5/4)
     = 1.6147 * 0.5477 = 0.884
```

r_pb = 0.88: strongly discriminative — passers are systematically the stronger agents. If the pass column were inverted (D and E pass, A–C fail), the sign flips to r_pb = -0.88: the strongest possible red flag.

### 5.3 Detection rules and thresholds

All thresholds apply only once the task has runs from **>= 3 diverse agents x >= 5 valid runs each** (diverse = distinct agent families, not two versions of the same script). Before that, flags are suppressed — small-pool r_pb and pooled rates are noise.

| Flag | Rule | Action |
|---|---|---|
| TOO EASY | shrunk pooled pass rate `(c_pool+1)/(n_pool+2) > 0.9` (i.e. d_t < 0.1) | Flag; stays active (weight floor in 5.6 keeps it counting); retirement candidate when its domain has surplus coverage |
| TOO HARD | shrunk pooled pass rate `< 0.1` (d_t > 0.9) | Flag; stays active as frontier headroom, but only if golden solution still grades 100% — otherwise it is broken, not hard |
| NON-DISCRIMINATIVE | `|r_pb| < 0.2` | Flag for review; with < 8 agents treat as advisory only |
| NEGATIVE DISCRIMINATION | `r_pb < -0.1` | Flag for human review; with < 8 agents treat as advisory only — the same guard as NON-DISCRIMINATIVE, because the destructive action deserves at least as strong a gate as the mild one (on 3–5 dichotomized agents a single unlucky pattern yields r_pb near -1). Quarantine only when all three hold: >= 8 agents, golden solution still grades 100% (a broken task and a genuinely hard task look identical in r_pb), and a human confirms. Strong agents fail, weak agents pass: often an ambiguous or mis-specified task (e.g. hidden tests reward the naive reading of the spec), sometimes a hard task a quirky weak agent passes by luck |
| FLAKY | Grader rerun on the IDENTICAL diff produces different outcomes (any nonzero variance), or golden-solution regrade varies over time | **Immediate quarantine.** This is a harness/environment bug (unpinned dependency, wall-clock-sensitive test); fix the harness, not the task stats |
| AMBIGUOUS | Creation time: two humans independently implement from the spec; if their solutions disagree on any hidden test, the spec is ambiguous. Post hoc: negative discrimination is the statistical echo of ambiguity | Block promotion (creation) / quarantine (post hoc) |
| OVERFITTABLE | Pooled score drop > 30% on metamorphic variants (renamed identifiers, reordered functions, paraphrased spec — see Section 8) | Flag; agents flagged here are pattern-matching the surface, the task is leaking its solution shape |

Worked TOO EASY example: n_pool = 30, c_pool = 29 gives shrunk rate 30/32 = 0.9375 > 0.9 — flagged, d_t = 0.0625.

The removal rules are asymmetric by construction: TOO EASY tasks stay active while negative-discrimination quarantine removes tasks the current strong agents fail, so unchecked removal ratchets the active pool easier and quietly inflates and compresses the unweighted v0.1 leaderboard. Guard: every quarantine batch records the active pool's d_t distribution before and after; a sustained downward drift in median d_t is reviewed as a bank-health problem, not a task-level one.

### 5.4 Task lifecycle state machine

```
candidate --> calibrating --> active <--> quarantined --> retired
                  ^                            |
                  +------- (fix + version++) --+
```

- **candidate**: authored. Automated gates before leaving: golden solution passes 100% of hidden tests in the clean room; protected-path config validates; two-human ambiguity check passes. Trigger out: CI green. Failed candidates go back to the author.
- **calibrating**: collecting runs (target: 3 diverse agents x n = 5). **Excluded from all rankings and domain scores.** Trigger out: run quota met AND no health flags -> auto-promote to active. Any flag -> back to author.
- **active**: scored, ranked, monitored weekly by the reliability job and the flag rules in 5.3.
- **quarantined**: triggered automatically by FLAKY, by NEGATIVE DISCRIMINATION only after the >= 8-agent, golden-solution, and human-confirmation guards in 5.3, or manually by a maintainer. Excluded from rankings immediately; existing runs are preserved but marked non-ranking. Exit: a fix increments the task version and re-enters **calibrating** (old runs never mix with the new version), or 30 days unresolved -> retirement review.
- **retired**: manual decision only, with a recorded reason (superseded, leaked publicly, permanently flaky, TOO EASY surplus). Historical runs are kept for longitudinal analysis but excluded from every current aggregate.

### 5.5 Difficulty circularity and its mitigation

Empirical d_t is estimated from the same agent pool being ranked: a strong agent makes tasks look easy, which then down-weights the very tasks it solved. Two-stage fix:

**v0.2 — leave-one-agent-out (LOAO) difficulty.** When difficulty enters agent a's own weighted score, recompute it without a's runs:

```
d_t^(-a) = 1 - (c_pool - c_at + 1) / (n_pool - n_at + 2)
```

where `c_at`, `n_at` are agent a's passes and valid runs on t. Worked example: 4 agents x 5 runs, n_pool = 20, c_pool = 8, so d_t = 1 - 9/22 = 0.5909. Agent A passed 4/5: `d_t^(-A) = 1 - (8-4+1)/(20-5+2) = 1 - 5/17 = 0.7059`. Without A's own successes the task is harder, and A is correctly credited more for solving it (unshrunk weight 1.2059 vs 1.0909 under the naive d_t, before the se-shrinkage in 5.6). LOAO removes self-influence but not set-level circularity (the remaining pool still defines "hard").

**v1.0 — full resolution by joint estimation.** The hierarchical Rasch model estimates theta_a and b_t simultaneously; difficulty and ability are mutually consistent posterior quantities, and partial pooling via the N(0, 1.5^2) prior on b_t handles sparse tasks. This subsumes both d_t and the LOAO correction.

### 5.6 How difficulty feeds scoring

- **v0.1: shown, never weighted.** d_rubric (and, once data exists, d_t) appear on the task dashboard and task detail pages. Rankings remain unweighted Wilson-LCB pass rates per the core contract. Rationale: with a cold-start pool, difficulty estimates are too noisy to multiply into the headline.
- **v0.2: difficulty-weighted domain scores.** Extend the domain formula (contract decision 10) with a difficulty weight:

```
w_t = 0.5 + d_t            (bounded in [0.5, 1.5]: easy tasks still count)
p-hat_k(a) = sum_t [ w_tk * w_t^(-a) * c_at ] / sum_t [ w_tk * w_t^(-a) * n_at ]
```

using LOAO difficulty `w_t^(-a) = 0.5 + d_t^(-a)` for the agent being scored, and the combined weights `w_tk * w_t^(-a)` in the Kish n_eff for the Wilson interval. Worked example: a primary-domain task (w_tk = 1.0) with d_t = 0.7647 contributes with combined weight 1.0 x (0.5 + 0.7647) = 1.2647; the same task as a tertiary tag contributes 0.25 x 1.2647 = 0.3162.

One honesty correction before these weights touch an interval: d_t is a posterior mean, not a known constant. Under the Laplace prior the posterior is `d_t ~ Beta(n_pool - c_pool + 1, c_pool + 1)`, with standard error `se_t = sqrt[(n_pool - c_pool + 1)(c_pool + 1) / ((n_pool + 2)^2 (n_pool + 3))]` — for the worked example (n_pool = 15, c_pool = 3), se_t = 0.100. Plugging the mean into w_t and the Kish n_eff treats the weight as exact, which narrows the weighted Wilson interval precisely when the pool is smallest. Mitigation: shrink the weight toward 1.0 (no weighting) in proportion to that uncertainty, `w_t = 1 + (1 - se_t/se_0) * (d_t - 0.5)` with `se_0 = sqrt(1/12) = 0.2887` (the prior's se, so a d_t that is barely better than the prior contributes barely any weighting; bounds stay [0.5, 1.5]). The worked example's weight shrinks from 1.2647 to 1.173 (tertiary: 0.2933); the same shrinkage applies to the LOAO weights w_t^(-a). The empirical method must therefore populate the `se` column of task_difficulty_estimates (10.2) — it is not optional for method 2. Residual caveat, stated on the dashboard: even shrunk, the weighted interval conditions on the weights and does not fully propagate difficulty-estimate uncertainty. The unweighted v0.1 leaderboard remains published alongside as the canonical headline; difficulty-weighted domain scores are a labeled secondary view.
- **v1.0: difficulty absorbed into IRT.** Explicit weighting is dropped. Under `logit P(X=1) = theta_a + gamma_{a,dom(t)} - b_t`, solving a high-b_t task is automatically stronger evidence for a high theta_a; the leaderboard becomes posterior theta with rank-cluster ties. d_t stays on dashboards as the explainable companion to b_t (they should agree monotonically; rank disagreement is itself a health signal).

### Limitations

- **Pool relativity survives LOAO.** d_t^(-a) removes self-influence, but with 3–5 agents the pool defines difficulty; adding one strong agent reshuffles every d_t. Difficulty values are snapshots of a pool, and we timestamp them as such; cross-snapshot comparisons of d_t are not meaningful until v1.0.
- **Dichotomization discards information.** Majority-vote X_at compresses p-hat_at = 0.6 and 1.0 to the same value; r_pb on 4–5 agents has huge sampling error. We deliberately use r_pb only as a flag (and quarantine on its sign only behind the 5.3 guards), not as a score, but borderline tasks will be misflagged in both directions early on.
- **The negative-discrimination flag can fire on legitimate tasks** in pathological pools (e.g. one strong agent with a systematic tooling failure on one task family). The >= 8-agent gate, the golden-solution check, and the human confirmation in 5.3 exist precisely because the rule is a heuristic, not a theorem.
- **Rubric bias is unquantified at cold start.** Until empirical data accumulates, v0.1 difficulty display reflects author intuition; the MISCALIBRATED check only works once d_t exists.
- **Reliability checks cost grader compute** (3 diffs x 2 repeats x active tasks, weekly from v0.2; in v0.1 only the manual gate-1 regrade exists) and only detect drift after the fact; a dependency that breaks mid-week silently corrupts up to a week of runs before the golden-solution check catches it. INFRA_FAILURE retry plus the regrade audit bounds, but does not eliminate, this window.
- **The metamorphic OVERFITTABLE check depends on Section 8's variant generator**; until variants exist, surface-pattern overfitting is undetectable by this section's machinery.
