## 6. Ranking algorithms

A leaderboard is a claim about ordering, and most ranking systems were built for a problem we do not have. Our setting is a **static agent-by-task grid**: a fixed item bank of tasks, batch-evaluated agents, n repeated runs per (agent, task) cell, binary functional pass X_i and continuous score S_i per run. This section compares the candidate methods, rejects the wrong-fit ones with a concrete demonstration, and commits to the staged plan.

### 6.1 Method comparison

| Method | Problem it solves | Pros | Cons | Data required | Works with small data? | Implementation difficulty | Verdict + stage |
|---|---|---|---|---|---|---|---|
| Simple average (mean p-hat or mean S) | Quick scalar summary | Trivial; explainable | Ignores uncertainty; 1/1 beats 9/10; ignores task difficulty | Any runs | Misleadingly "yes" | Trivial | Diagnostic only, never headline (all stages) |
| Difficulty-weighted average | Easy tasks dominating the score | Rewards hard-task wins; still closed-form | Needs pooled difficulty estimates; circular if pool is tiny | >= ~3 agents pooled per task | Partially (needs shrinkage) | Easy | **Adopt v0.2 as a labeled secondary view** with w_t = 0.5 + d_t^(-a) (5.6); unweighted LCB stays the headline |
| Conservative LCB ranking (Wilson lower bound) | Small-n overconfidence | Penalizes thin evidence; closed-form; deterministic | Conservative; ignores difficulty on its own | n >= 2 per cell | **Yes — designed for it** | Easy | **Adopt v0.1** (headline), kept as fallback forever |
| Elo | Sequential pairwise matches, drifting skill | Familiar; online updates | Order-dependent (see 6.2); K-factor noise; no uncertainty; wrong data model | Long match streams | No | Easy | **Reject** for core; revisit only for duel events |
| Glicko-2 | Elo + rating deviation + volatility | Models uncertainty and drift | Still sequential/order-sensitive; volatility hyperparameter; drift is a non-feature here (agents are versioned, not drifting) | Long match streams in rating periods | No | Moderate | **Reject** for core; duel events only |
| TrueSkill | Multiplayer/team matches | Handles teams, partial orders | Microsoft patent encumbrance; sequential; opaque factor-graph updates | Long match streams | No | Hard | **Reject** (patent + wrong fit) |
| Bradley-Terry | Probabilities from pairwise win counts | Principled; order-free MLE over batch data | Applied to agent-vs-task it *is* Rasch (see 6.3); separate implementation is redundant | Full outcome grid | Moderate | Moderate | **Subsumed by v1.0 Rasch** — do not implement separately |
| Bayesian hierarchical Rasch/IRT | Joint ability + difficulty + uncertainty from the full grid | Order-free; pools strength across grid; credible intervals; pairwise P(theta_a > theta_b); handles missing cells | Needs MCMC batch job; priors to justify; overkill below ~10 agents x ~50 tasks | Reasonably filled grid | Partially (priors regularize, but wide intervals) | Hard (PyMC, offline batch) | **Adopt v1.0** as primary ranking engine |
| Pareto ranking | Multi-objective trade-offs (S vs runtime/cost/memory) | No arbitrary weights; honest about incomparability | Not a total order; not a scalar; front membership is binary | Per-run resource axes | Yes | Easy | **Adopt v0.2 as a separate dashboard** (section 7), never the scalar leaderboard |

### 6.2 Why Elo, Glicko-2, and TrueSkill are the wrong fit

All three model **sequential matches between players whose latent skill drifts over time**. Every assumption fails here:

1. **Tasks are a fixed item bank, not opponents who learn.** Task difficulty b_t is a static property; rating systems waste machinery tracking drift that cannot occur.
2. **Outcomes arrive in batches with no meaningful order.** We run the full grid; "match order" is a scheduling artifact. Elo's output depends on it. Demonstration with K = 32, expected score E = 1/(1 + 10^((R_opp - R)/400)), update R' = R + K*(X - E). Agent A (rating 1000) plays tasks T1 and T2 (both rated 1000): a **win vs T1** and a **loss vs T2** — identical evidence, two processing orders:

```
Order 1: win first, then loss
  vs T1: E = 0.5            -> A = 1000 + 32*(1 - 0.5)      = 1016.00
  vs T2: E = 1/(1+10^(-16/400)) = 0.5230
                            -> A = 1016 + 32*(0 - 0.5230)   = 999.26

Order 2: loss first, then win
  vs T2: E = 0.5            -> A = 1000 + 32*(0 - 0.5)      = 984.00
  vs T1: E = 1/(1+10^(16/400))  = 0.4770
                            -> A = 984  + 32*(1 - 0.4770)   = 1000.74
```

Same two outcomes, final rating 999.26 vs 1000.74 — a 1.47-point split manufactured by the scheduler. With hundreds of grid cells the path-dependence compounds, and a leaderboard whose ordering depends on job-queue order is indefensible.

3. **Hyperparameters inject noise.** Elo's K-factor and Glicko-2's volatility parameter tau are tuning knobs with no ground truth in our setting; different choices yield different orderings of the *same* grid.
4. **TrueSkill adds patent encumbrance** (Microsoft) on top of the same wrong data model and an opaque factor-graph update — directly against the explainability constraint.

These systems become relevant **only** if the platform later adds head-to-head duel events (two agents racing on the same live task instance). That is a genuinely sequential pairwise stream and Glicko-2 would be the candidate there. It is out of scope for the core leaderboard at every stage.

### 6.3 Bradley-Terry is Rasch in disguise

Bradley-Terry assigns each competitor a strength; applied to "agent a vs task t" outcomes with strengths e^theta_a and e^b_t:

```
P(a beats t) = e^theta_a / (e^theta_a + e^b_t) = sigmoid(theta_a - b_t)
```

where theta_a is agent ability and b_t is task difficulty on the same logit scale. This is **exactly the Rasch (1PL IRT) model**. Worked check: theta_a = 0.5, b_t = -0.3 gives sigmoid(0.5 - (-0.3)) = sigmoid(0.8) = 0.6900 — a 69.0% pass probability either way you derive it. Decision: **no separate Bradley-Terry implementation, ever.** The v1.0 hierarchical Rasch fit subsumes it and adds priors, domain offsets, and full posterior uncertainty.

### 6.4 The v1.0 model in full

Nightly offline batch job (PyMC, NUTS sampler — no network, no API, satisfies the offline constraint):

```
logit P(X_ait = 1) = theta_a + gamma_{a,dom(t)} - b_t

theta_a ~ Normal(0, 1)            # agent ability
b_t     ~ Normal(0, 1.5^2)        # task difficulty (wider: tasks vary more)
gamma_{a,k} ~ Normal(0, tau^2)    # agent-by-domain offset, domain k = dom(t)
tau     ~ HalfNormal(0.5)         # shrinks domain offsets toward 0 when data is thin
```

X_ait is the binary functional pass of run i of agent a on task t (gated as per section on scoring; INFRA_FAILURE runs are excluded before the fit). Every VALID/TIMEOUT/AGENT_ERROR run is one Bernoulli observation — repeated runs enter individually, no pre-aggregation.

**Outputs written to PostgreSQL per fit:** posterior mean and 95% credible interval for each theta_a; per-domain offsets gamma_{a,k} with intervals; per-task b_t (feeds task-health review); and the pairwise matrix P(theta_a > theta_b), computed directly as the fraction of posterior draws in which theta_a exceeds theta_b. Worked example: with 4 chains x 1,000 retained draws = 4,000 samples, if theta_A > theta_B in 3,120 draws, P(theta_A > theta_B) = 3120/4000 = 0.78.

**Runtime expectations:** at realistic scale (20 agents x 200 tasks x 5 runs = 20,000 Bernoulli observations, 221 + 20K free parameters for K domains — e.g. ~320 at K = 5), NUTS with 4 chains x (1,000 warmup + 1,000 draws) completes in seconds to a few minutes on a laptop CPU. This is comfortably a nightly job; failure of the job leaves yesterday's posterior in place and the v0.1/v0.2 closed-form leaderboard is always computable as the live fallback.

### 6.5 Ranking presentation: never print a fake total order

Strict ranks 1, 2, 3 over overlapping intervals are statistical fiction. Both stages use **rank clusters with rank ranges**.

**v0.1 rule (decided):** agents a and b are **tied unless LCB_a > p-hat_b** — a's Wilson lower bound must exceed b's *point estimate*. Requiring LCB_a > UCB_b almost never separates anyone at n = 5; requiring only p-hat_a > p-hat_b is fake precision. This middle ground is the deliberate, conservative compromise, and it is the single v0.1 rule. It is also knowingly one-sided: b's uncertainty is ignored, and no family-wise correction is applied across the O(agents^2) pairwise comparisons, so as the roster grows some "strictly above" separations will be spurious — when in doubt, merge into the wider rank-range cluster, and defer firm pairwise ordering claims to the v1.0 P(theta_a > theta_b) matrix. (In production the rule is applied to the macro-domain score using Kish n_eff in the Wilson interval; the example below uses one pooled rate for clarity.)

Worked example (z = 1.96):

```
Agent A: n=10, c=9  -> p-hat = 0.9,  Wilson 95% = [0.5958, 0.9821]
Agent B: n=5,  c=3  -> p-hat = 0.6,  Wilson 95% = [0.2307, 0.8824]   (contract anchor)
Agent C: n=10, c=2  -> p-hat = 0.2,  Wilson 95% = [0.0567, 0.5098]

A vs B: LCB_A = 0.5958 < p-hat_B = 0.6   -> TIED
A vs C: LCB_A = 0.5958 > p-hat_C = 0.2   -> A strictly above C
B vs C: LCB_B = 0.2307 > p-hat_C = 0.2   -> B strictly above C

Displayed: A rank 1-2, B rank 1-2, C rank 3
```

Rank-range computation: best rank = 1 + (number of agents strictly above); worst rank = (number of agents not strictly below). Display the range ("1–2"), sort rows by LCB within a cluster for layout only, and render tied clusters visually grouped.

**v1.0 rule (decided):** a and b are **tied unless P(theta_a > theta_b) > 0.75** — posterior odds of at least 3:1. Threshold rationale: 0.95 would almost never split agents at benchmark scale (everything ties, leaderboard is useless); anything near 0.5 reintroduces coin-flip orderings. 0.75 is fixed, not configurable per leaderboard. With the example above, P(theta_A > theta_B) = 0.78 > 0.75 separates A above B once the Rasch fit pools evidence across the whole grid — exactly the small-data gain the hierarchy buys.

### 6.6 Staged recommendation

- **v0.1 — macro-domain LCB ranking.** Per-domain pooled p-hat_k with Kish n_eff Wilson intervals, macro-averaged over domains with >= 5 tasks; rank by LCB; ties per the LCB_a > p-hat_b rule; rank ranges displayed. Entirely closed-form SQL + Python.
- **v0.2 — task-health filtering + difficulty-weighted secondary view.** The unweighted v0.1 LCB leaderboard **stays the canonical headline** — the sort key does not change between v0.1 and v0.2 (per 5.6 and 3.2), so rankings stay directly comparable. Difficulty enters as a labeled secondary view with task weight w_t = 0.5 + d_t^(-a) (bounded in [0.5, 1.5], so easy tasks still count), where d_t^(-a) = 1 - (c_pool - c_at + 1)/(n_pool - n_at + 2) is the leave-one-agent-out Laplace-shrunk difficulty of 5.5. Worked example (matching 5.5): n_pool = 20, c_pool = 8, agent A passed 4/5 -> d_t^(-A) = 1 - 5/17 = 0.7059, weight w_t = 1.2059. Weighted pass rate per agent: sum_t(w_t * c_at) / sum_t(w_t * n_at), with Kish n_eff = (sum w_t*n_at)^2 / (sum w_t^2 * n_at) in the Wilson interval — the same machinery as domain scores. Two-task example, LOAO difficulties d^(-a) = 0.2 (agent 5/5) and d^(-a) = 0.8 (agent 1/5), so weights 0.7 and 1.3: plain pooled p-hat = 6/10 = 0.6, difficulty-weighted = (0.7*5 + 1.3*1)/(0.7*5 + 1.3*5) = 4.8/10 = 0.48, n_eff = 100/10.9 = 9.17 — easy-task wins no longer mask hard-task failure, while the 0.5 floor keeps the penalty proportionate. Tasks quarantined by health flags (FLAKY, negative discrimination r_pb < -0.1, or manual quarantine — triggers per 5.3/5.4, not restated here) are **excluded from ranking entirely**, not down-weighted.
- **v1.0 — hierarchical Bayesian Rasch** (section 6.4) becomes the primary engine: credible-interval rank clusters via the P > 0.75 rule, the pairwise P(theta_a > theta_b) matrix as a first-class UI artifact, per-domain gamma offsets replacing raw macro-averages for the headline. The v0.1/v0.2 closed-form leaderboard remains computed and visible as the cross-check; a large disagreement between the two is itself a monitoring alert.
- **Pareto ranking** is the multi-objective layer over (S, runtime, cost, memory) — section 7. It is a complementary dashboard, never a replacement for the scalar leaderboard, because front membership is binary and gives no graded ordering.

### Limitations

- **The v0.1 tie rule is asymmetric and intransitive.** "Tied" is not transitive: a can be tied with b and b tied with c while LCB_a > p-hat_c still separates a from c (the *separation* relation itself is transitive, since LCB_b <= p-hat_b always); we resolve this by taking the transitive closure of "tied" (clusters are connected components), which can merge agents that pairwise look separable. Accepted cost of conservatism at n = 5. The rule also tests a's lower bound against b's *point estimate* only, with no multiple-comparison control across the pairwise grid, so the expected number of spurious separations grows with the agent roster; the rank-range display limits but does not remove this overstatement, which is one more reason v1.0's posterior pairwise matrix replaces it as the basis for ordering claims.
- **Difficulty weights are pool-relative and circular at small agent counts.** With 2–3 agents, d_t mostly reflects those agents' idiosyncrasies; Laplace shrinkage and the LOAO correction bound but do not eliminate this (5.5). Difficulty weighting is therefore a v0.2 secondary view, gated on a minimum pool (>= 3 agents per task), never the v0.x headline.
- **The Rasch model assumes unidimensional ability plus additive domain offsets.** A 1PL model has no discrimination parameter: a leaky or degenerate task biases b_t rather than being down-weighted automatically. We mitigate via v0.2 task-health quarantine *before* the fit, not within it. A 2PL upgrade is possible later but doubles the parameter count on small data.
- **The 0.75 pairwise threshold is a judgment call**, not derived from a loss function. It also does not control family-wise error across the full pairwise matrix; with many agents, some >0.75 separations will be spurious. We accept this because the displayed artifact is the rank *range*, which degrades gracefully.
- **MCMC is a batch artifact.** Between nightly fits, new runs appear only in the closed-form leaderboard; the two views can disagree intra-day. The UI must timestamp the Rasch fit explicitly.
- **Everything here ranks within this benchmark's task bank.** A theta_a ordering is benchmark-relative; it says nothing about tasks unlike the bank, and the leaderboard must carry the contract-mandated macro-skill-average labeling, never a general-capability claim.
