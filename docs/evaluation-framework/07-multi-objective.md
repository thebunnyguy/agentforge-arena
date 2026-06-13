## 7. Multi-objective evaluation

There is no single best agent. A slow local LLM agent with a high pass rate, a fast ScriptAgent with a mediocre one, and a frugal CLI agent with excellent stability are all "best" for somebody. This section defines how the platform compares agents without collapsing that structure prematurely: a fixed objective vector per agent, Pareto dominance for the honest picture, epsilon-constraint queries as the primary UX, and a small set of scalarization presets with published weights for users who want one number anyway.

### 7.1 The objective vector

For an agent `a` evaluated over a task scope `T_scope` (the full benchmark, one domain `k`, or any filtered task set), we compute a fixed objective vector `g(a) = (g_pass, g_speed, g_cost, g_stab, g_mem)`. Every component is normalized to [0,1] with **higher is better**, so all frontier math points the same direction.

```
g_pass  = Wilson 95% lower bound (LCB) of the pooled pass rate over T_scope
g_speed = 1 - median_i( runtime_i / timeout_t(i) )        clamped to [0,1]
g_cost  = 1 - median_i( cpu_seconds_i / B_cpu(t(i)) )     clamped to [0,1]
g_stab  = sum_t m_t * stab_t / sum_t m_t                  stab_t = max(0, 1 - 2*s_t)  (Section contract, decision 6)
g_mem   = 1 - median_i( peak_rss_i / M_limit(t(i)) )      clamped to [0,1]
```

Symbols: `runtime_i` is wall-clock seconds of run `i`; `timeout_t(i)` is the timeout of the task that run belongs to; `cpu_seconds_i` is total CPU time from the sandbox cgroup; `B_cpu(t) = timeout_t * vcpu_limit_t` is the fixed CPU budget (the maximum CPU-seconds a run could legally consume); `peak_rss_i` is peak resident memory from `memory.peak`; `M_limit(t)` is the container memory limit; `s_t` is the Bessel-corrected sample standard deviation of run scores `S_i` on task `t`, and `m_t` is task `t`'s run mass — `w_tk * n_t` when the scope is a domain `k`, so domain-scope `g_stab` **equals Section 4.5's `Stab_k` exactly**, and plain `n_t` for the full benchmark or a filtered task set. A single pooled std over all runs in the scope is rejected: it mixes between-task score differences into the spread, so a perfectly consistent agent scoring 0.9 on one task and 0.3 on another would read as unstable (pooled `s = 0.316`, `g_stab = 0.37`, against the correct 1.0). One definition owns the name "stability" at every scope, and it is 4.5's. Each run is normalized by **its own task's** anchors first, then the median is taken across all VALID runs in the scope, so tasks with different timeouts mix correctly.

Censoring rules (decisive): TIMEOUT runs enter the runtime median at exactly `runtime_i = timeout_t` (so they contribute `g_speed` mass of 0), because the true runtime is right-censored at the timeout and any smaller value would flatter the agent. INFRA_FAILURE runs are excluded everywhere, consistent with run-status decision 4.

Secondary cost columns, never inside `g`: tokens/run for LLM agents (Ollama exposes prompt + completion token counts; recorded per run, shown as a column), and $/run **only** if external API agents are ever enabled — the column does not exist until then. Runtime, cost, and memory are never inside `S` (decision 2); they live only here.

Worked example, one objective at a time. Agent A on a single-task scope with `n = 5, c = 3` (`p-hat = 0.6`): the Wilson 95% interval is `[0.2307, 0.8824]`, so `g_pass = 0.2307` — deliberately punishing at `n = 5`, which is exactly why escalation to `n = 10` triggers in the `0.2 < p-hat < 0.8` band (decision 7). Task timeout 600 s, median runtime 180 s: `g_speed = 1 - 180/600 = 0.70`. vCPU limit 2, so `B_cpu = 1200` CPU-s; median CPU use 240 CPU-s: `g_cost = 1 - 240/1200 = 0.80`. Run-score std `s_t = 0.10`: `stab_t = max(0, 1 - 0.2) = 0.80`, and with a single task the mass-weighted mean is just `g_stab = 0.80`. Memory limit 2048 MB, median peak 512 MB: `g_mem = 1 - 512/2048 = 0.75`. Vector: `g(A) = (0.2307, 0.70, 0.80, 0.80, 0.75)`.

### 7.2 Pareto dominance and the frontier

Definition: agent `a` **dominates** agent `b` iff `g_j(a) >= g_j(b)` for every objective `j` and `g_j(a) > g_j(b)` for at least one. The **Pareto frontier** is the set of non-dominated agents — agents nobody beats on everything.

With `m` agents and `d` objectives, the naive pairwise sweep is `O(m^2 * d)`. AgentForge Arena will host on the order of 5–20 agents; at `m = 20, d = 5` that is at most 2,000 float comparisons, microseconds in Python. The sort-based `O(m log m)` method exists for `d = 2` (sort by one objective, sweep keeping the running max of the other) and the divide-and-conquer generalizations exist for higher `d`; both are unnecessary at this scale and the naive sweep is the **decided** implementation — it is trivially correct, trivially testable, and handles any `d`.

```
def pareto_frontier(agents, g):           # g[a] = tuple of d objectives, higher = better
    frontier = []
    for a in agents:
        dominated = False
        for b in agents:
            if b is a: continue
            if all(g[b][j] >= g[a][j] for j in range(d)) and \
               any(g[b][j] >  g[a][j] for j in range(d)):
                dominated = True
                break
        if not dominated:
            frontier.append(a)
    return frontier
```

Worked example, three agents on `(g_pass, g_speed, g_cost)`:

```
A = (0.60, 0.70, 0.80)
B = (0.55, 0.65, 0.75)
C = (0.70, 0.50, 0.85)
```

A dominates B (greater on all three). C vs A: C is higher on pass and cost but lower on speed, so neither dominates the other. Frontier = `{A, C}`; B is dominated and drawn dimmed in every dashboard view.

Ties in `g` produce neither-dominates by definition (no strict improvement), so exact duplicates both stay on the frontier; this is correct behavior, not a bug to fix.

**Mixed-estimator caveat (decisive, v0.1).** The vector is not estimator-homogeneous: `g_pass` is a Wilson LCB while the other four objectives enter dominance as point estimates (medians, mass-weighted `stab_t`). The mix makes frontier membership run-count-sensitive — at `p-hat = 0.6` the LCB is 0.2307 at `n = 5` but 0.4618 at `n = 50` — so an under-sampled agent can be dominated off the frontier with no true difference in correctness or speed. Until the v0.2 bootstrap CIs (decision 9) provide like-for-like lower bounds on all five objectives, the rule is: any dominance verdict that hinges on `g_pass` is suppressed when the two agents' valid-run counts differ by more than a factor of 2 — the pair renders as mutually non-dominated with a "run counts differ" badge instead of a "dominated by" tooltip.

### 7.3 Dashboard views

Two views, both computed in FastAPI from one materialized `agent_scope_metrics` table (schema in Section 10.2's derived layer) and rendered in Next.js:

1. **Frontier scatter** — x = median wall-clock runtime (raw seconds, log scale toggle), y = pass-rate LCB. Frontier agents get a connected staircase highlight; dominated agents are dimmed with the dominating agent named in the tooltip ("dominated by A on all objectives"). Axis pickers let the user swap in any pair from the objective vector; the frontier shown is always recomputed for the **displayed pair**, with a caption noting the full 5-objective frontier may differ.
2. **Per-domain frontiers** — the same scatter faceted by domain `k` (decision 10 weights apply to the pooled pass rate per domain). The frontier in `backend` routinely differs from `devops`: an agent strong at API code but weak at shell/YAML moves from frontier to dominated as you switch facets. This is a feature, not noise — it is the visual argument against a single global ranking.

### 7.4 Epsilon-constraint queries: the primary UX

The primary comparison interface is **not** a weighted score. It is the epsilon-constraint form: optimize one objective subject to floors on the others. This matches how users actually think ("I need at least 60% reliability, then I care about speed") and it is honest — no hidden exchange rate between correctness and latency. Implementation is a SQL `WHERE` + `ORDER BY`, nothing more:

```sql
-- "fastest agent with LCB >= 0.6"
SELECT agent_id, g_speed, g_pass
FROM agent_scope_metrics
WHERE scope_id = :scope AND g_pass >= 0.6
ORDER BY g_speed DESC, g_pass DESC      -- second key breaks ties
LIMIT 1;

-- "cheapest agent with stability >= 0.8"
... WHERE scope_id = :scope AND g_stab >= 0.8
ORDER BY g_cost DESC, g_pass DESC LIMIT 1;
```

If the constraint set is empty, the API returns "no agent meets the constraints" plus the nearest-miss agent and its gap — it never silently relaxes the floor. The query builder UI exposes one slider per objective as a floor and one radio button as the sort target. Decision: this view is the default "compare agents" page; presets (7.5) and the frontier scatter link into it.

### 7.5 Use-case presets: scalarization with published weights

For users who want one number, we provide presets of the linear form

```
U(a) = sum_j w_j * g_j(a),    sum_j w_j = 1,   each g_j in [0,1]  =>  U in [0,1]
```

with the weights **rendered in the UI next to the score**, always. Hidden weights are how leaderboards lie. The shipped presets:

| Preset | Definition |
|---|---|
| Best backend agent | scope = domain `backend`; `U = 0.7*g_pass + 0.2*g_stab + 0.1*g_speed` |
| Most reliable agent | `U = 0.5*g_stab + 0.3*g_worst + 0.2*g_pass` |
| Fastest acceptable | epsilon-constraint, not scalarization: `g_pass >= 0.5`, sort by `g_speed` |
| Best local/offline agent | filter `agent_kind IN (mock, script, cli, ollama)`, then default LCB sort |
| Best for risky security tasks | scope = domain `security`; `U = 0.4*g_worst + 0.3*g_scope + 0.3*g_secclean` |
| Best for large refactors | scope = tasks with `scale = L`; `U = 0.4*g_regr + 0.4*g_pass + 0.2*g_par` |

Auxiliary objectives used only by presets, all fixed-anchor and higher-is-better: `g_worst` = macro-average over tasks in scope of the per-task minimum run score `min_i S_i` (worst-case behavior; with the security preset rationale that in risky contexts the tail matters more than the mean — a 9-of-10 agent whose 10th run deletes a config file is worse than a steady 7-of-10 agent); `g_scope` = fraction of VALID runs with `scope_ok = 1` (scope discipline beyond the gate's pass/fail effect); `g_secclean` = fraction of VALID runs whose diff introduces zero new high-severity findings from the offline static security scanner (Semgrep/Bandit rulesets, no network); `g_regr` = fraction of VALID runs with `regression_pass = 1`; `g_par` = parsimony, `max(0, 1 - median_i(changed_lines_i) / (4 * L_ref))` where `L_ref` is the reference solution's changed-line count and `4*L_ref` is the fixed diff budget. `g_par` shares its anchor with Section 1's per-run `q_pars` (`L_ref` is `R`) but is deliberately a different, stricter curve: `q_pars` lives inside `Q` with a flat forgiveness region up to `2R` so legitimate alternative implementations are not penalized within `S`, while `g_par` is a scope-level preset axis kept linear from zero so it can still rank refactors that have already cleared the gates — at 3x the reference, `q_pars = 0.833` inside `S` but `g_par = 0.25` here. The two quantities answer different questions and are never interchangeable.

Worked example, "Best backend agent" (`w = 0.7 / 0.2 / 0.1` on `g_pass, g_stab, g_speed`), backend-domain scope:

```
Agent A: g_pass = 0.62, g_stab = 0.80, g_speed = 0.70
U(A) = 0.7*0.62 + 0.2*0.80 + 0.1*0.70 = 0.434 + 0.160 + 0.070 = 0.664

Agent B: g_pass = 0.55, g_stab = 0.95, g_speed = 0.90
U(B) = 0.7*0.55 + 0.2*0.95 + 0.1*0.90 = 0.385 + 0.190 + 0.090 = 0.665
```

B "wins" by 0.001 despite a 7-point lower pass rate. This is exactly why scalarization is a preset, not the core: a one-thousandth gap under one weighting is noise, and the UI must show both `U` and the underlying vector, with the frontier badge, so the user sees that A and B are mutually non-dominated rather than ranked by truth. The gap is also not *symmetric* noise: `g_pass` enters `U` at its Wilson LCB while `g_stab` and `g_speed` enter at point estimates, so every preset containing `g_pass` systematically discounts correctness relative to the other axes — a directional lean toward fast/cheap that cuts against 7.7's load-bearing-axis priority. Until v0.2's bootstrap lower bounds put all objectives on like-for-like bounds, preset pages carry the fixed caption "correctness is a conservative bound; other axes are central estimates."

### 7.6 Normalization honesty: fixed anchors only

Min-max normalization over the **current agent set** (`g = (x - min_agents) / (max_agents - min_agents)`) is rejected as a rule. It makes every agent's score a function of who else is enrolled: add one very slow agent and everyone else's `g_speed` jumps; remove the cheapest agent and `g_cost` reshuffles; historical scores silently change meaning. That breaks reproducibility, breaks score history, and enables rank reversals from roster changes alone.

**The rule:** every normalized objective uses a fixed, versioned anchor that is a property of the task or the platform configuration, never of the agent population. Runtime is anchored to the task timeout (`g_speed = 1 - median_runtime/timeout`); CPU cost to the per-task CPU budget `B_cpu = timeout * vcpu_limit`; memory to the container limit; pass rate and stability are natively [0,1] and need no anchor. Anchors are stored with a version id in PostgreSQL; if a task's timeout is ever changed, the anchor version increments and previously computed `g_speed` values are recomputed in the same migration — no mixed-anchor tables.

### 7.7 Default sort and the no-crowning rule

The default leaderboard sort remains the conservative pass rate — Wilson LCB on the macro-averaged scope per decisions 5 and 10 — because correctness is the load-bearing axis and the LCB is the only component with a calibrated uncertainty story in v0.1. The Pareto frontier badge is **always rendered** on the leaderboard, on every preset view, and on every scatter. The UI never displays a single global "best agent": superlatives are always scoped ("best for backend", "fastest with LCB ≥ 0.5") and every preset page links to the underlying objective vectors. Auto-crowning across use cases is prohibited as a product rule, not just a stylistic one — the entire premise of this section is that the maximizer changes with the use case.

### Limitations

- **Five-objective frontiers barely discriminate at small m.** With `d = 5` objectives and 5–10 agents, most agents end up non-dominated (dominance requires losing on *every* axis), so "on the frontier" carries little information. The 2D scatters and epsilon-constraint queries do the real work; the full frontier is a sanity overlay.
- **No uncertainty on the frontier itself.** `g_pass` carries a Wilson interval, but dominance is computed on point estimates of `g_speed`, `g_cost`, `g_stab`, `g_mem`. Two agents 0.01 apart in median runtime are treated as strictly ordered. Bootstrap CIs on the continuous objectives arrive in v0.2 (B = 2000, decision 9); until then, near-ties on the frontier should be read as ties — and the estimator mix is directional, not just noisy: a lower bound on one axis against central estimates on the rest biases both dominance and presets toward fast/cheap and ties frontier membership to run counts, contained in v0.1 by the suppression rule in 7.2 and the preset caption in 7.5.
- **Preset weights are editorial, not derived.** 0.7/0.2/0.1 encodes our judgment of a backend user's priorities; no sensitivity analysis ships in v0.1. A weight-perturbation rank-stability check (does the preset winner survive ±0.1 weight jitter?) is a cheap v0.2 addition.
- **CPU-seconds undercounts Ollama agents.** GPU time is not captured uniformly across Metal/CUDA/CPU inference backends, so `g_cost` understates the true compute of local LLM agents relative to script agents. Tokens/run partially compensates but depends on each model's tokenizer, so cross-model token comparisons are loose.
- **`g_worst` is a noisy order statistic.** With `n = 5`, the per-task minimum run score is high-variance; the reliability and security presets inherit that noise. The `n = 10` escalation band helps exactly where it matters most (mid pass rates), but worst-case estimates stay rough until run counts grow.
- **Timeout anchoring couples scoring to configuration.** `g_speed` and `g_cost` change meaning if timeouts are retuned; the anchor-versioning rule contains this but cross-version speed comparisons are invalid by construction and the UI must refuse to draw them.
