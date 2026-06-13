## 4. Domain capability profiling

A single pass rate tells you *whether* an agent is good; a capability profile tells you *where*. This section defines the task taxonomy, the per-domain scoring math, the uncertainty treatment for pooled scores, and the display contract that keeps the profile honest when data is thin.

### 4.1 Two-axis taxonomy plus scale tag

Every task carries tags on two orthogonal axes plus one scale tag:

**Axis 1 — DOMAIN** (what subsystem/technology the change lives in). Fixed vocabulary, K = 8:

`backend, frontend, database, devops, security, performance, api-design, async-concurrency`

**Axis 2 — ACTIVITY** (what kind of change is being asked for). Fixed vocabulary, 6 values:

`debugging-bugfix, feature-implementation, refactoring, test-writing, migration, documentation`

**Scale tag** (expected magnitude of the change), one of `XS / S / M / L`, assigned at task authoring time from two estimates:

| Scale | Expected diff size | Expected context to navigate |
|-------|--------------------|------------------------------|
| XS    | <= 10 changed lines  | <= 2 files |
| S     | <= 50 changed lines  | <= 5 files |
| M     | <= 200 changed lines | <= 20 files |
| L     | > 200 changed lines, or repo-wide | > 20 files / cross-module |

Large-codebase navigation is deliberately **not** a domain. It is captured by scale `L` plus a numeric metadata field `context_size_kloc` (KLOC of code the task author judges the agent must read to solve the task). Domains describe *what the code is about*; codebase size describes *how much of it there is* — conflating them would make "large-codebase" steal mass from every real domain.

**Why two axes instead of one flat tag list.** "Debugging" is not parallel to "backend": a task is *debugging IN backend*. A one-axis taxonomy that mixes the two levels fails in one of two ways. (a) **Double-counting:** if a task is tagged both `backend` and `debugging` in a single flat scheme, the same runs feed two pseudo-domains, and any macro-average over the flat list counts that evidence twice — an agent strong at backend bugfixes inflates two of the averaged components with one skill. (b) **Under-coverage:** if the scheme forces one tag per task, the author must choose `backend` *or* `debugging`, and the profile silently loses the other dimension; you can never answer "is this agent bad at debugging in general, or bad at backend in general?" The cross-product design answers exactly that question via the drill-down cells in 4.8, while keeping each axis internally exclusive so nothing is counted twice.

### 4.2 Tagging rules

Hard constraints, enforced by a DB CHECK + application validation at task creation:

1. **Domain:** at most 3 domain tags with fixed weights — primary `w = 1.0`, secondary `w = 0.5`, tertiary `w = 0.25`. Every task has **exactly one primary** domain. Weights are fixed constants, not author-tunable: tunable weights invite gaming a domain's leaderboard by re-weighting tasks after the fact.
2. **Activity:** exactly 1 tag. If a task genuinely spans two activities ("migrate the schema and fix the bug it exposes"), it is two tasks; split it.
3. **Scale:** exactly 1 tag, plus the `context_size_kloc` metadata field (required for `M` and `L`, optional below).

Tag changes after a task has graded runs create a new task version; existing runs stay attached to the old version (tags are part of grading provenance, per the task-versioning rules elsewhere in this document).

### 4.3 Per-domain score: pooled weighted pass rate

For agent `a` and domain `k`:

```
p-hat_k = ( sum over tasks t of  w_tk * c_t ) / ( sum over tasks t of  w_tk * n_t )

w_tk : domain weight of task t for domain k (1.0 / 0.5 / 0.25, or 0 if untagged)
c_t  : number of functionally passing runs (X_i = 1) of agent a on task t
n_t  : number of VALID runs of agent a on task t (INFRA_FAILURE excluded)
```

This is a run-level pooled rate, not a mean of per-task rates: each run contributes mass `w_tk`, so a task where the agent ran n = 10 (escalated under the high-variance rule) correctly contributes more evidence than a task with n = 2.

**Worked example** — agent A, domain k = `backend`, three tagged tasks:

| Task | backend weight w_tk | n_t | c_t |
|------|--------------------:|----:|----:|
| t1 (primary backend)   | 1.00 | 5  | 3 |
| t2 (secondary backend) | 0.50 | 5  | 5 |
| t3 (tertiary backend)  | 0.25 | 10 | 2 |

```
numerator   = 1.0*3 + 0.5*5 + 0.25*2  = 3 + 2.5 + 0.5  = 6.0
denominator = 1.0*5 + 0.5*5 + 0.25*10 = 5 + 2.5 + 2.5  = 10.0
p-hat_backend = 6.0 / 10.0 = 0.60
```

### 4.4 Per-domain confidence: Kish effective sample size + Wilson

The 20 raw runs above are not 20 equal pieces of evidence — weighting reduces the effective information. We use the Kish effective sample size:

```
n_eff = ( sum_t w_tk * n_t )^2 / ( sum_t w_tk^2 * n_t )
```

and plug `n_eff` (in place of n) and the pooled `p-hat_k` into the standard Wilson 95% interval (z = 1.96):

```
center = ( p + z^2/(2*n_eff) ) / ( 1 + z^2/n_eff )
half   = z * sqrt( p*(1-p)/n_eff + z^2/(4*n_eff^2) ) / ( 1 + z^2/n_eff )
CI     = [ center - half , center + half ]
```

**Worked example** (continuing 4.3):

```
sum w*n    = 10.0                       (from 4.3)
sum w^2*n  = 1.0^2*5 + 0.5^2*5 + 0.25^2*10 = 5 + 1.25 + 0.625 = 6.875
n_eff      = 10.0^2 / 6.875 = 14.5455

z^2/n_eff       = 3.8416 / 14.5455 = 0.26411
center          = (0.60 + 0.13206) / 1.26411 = 0.5791
half            = 1.96 * sqrt(0.24/14.5455 + 0.26411/58.182) / 1.26411
                = 1.96 * sqrt(0.016500 + 0.004539) / 1.26411 = 0.2249
CI_backend      = [0.3542, 0.8040]
```

Sanity checks: with the naive raw count n = 20 the interval would be [0.3866, 0.7812] — overconfident; Kish correctly widens it. And task t1 alone (n = 5, c = 3) reproduces the contract anchor Wilson interval [0.2307, 0.8824], so the pooled three-task interval being much tighter than the single-task interval is exactly the value pooling buys.

**Exchangeability caveat (stated, not hidden).** Pooling runs into one binomial assumes tasks within the domain are exchangeable — same underlying pass probability. They are not: an XS backend bugfix and an L backend feature have very different difficulty, so the pooled interval is **optimistic** (real between-task variance is extra dispersion the binomial model does not see). Mitigation is staged per the architecture: v0.2 introduces empirical task difficulty `d_t = 1 - (c_pool+1)/(n_pool+2)` enabling difficulty-stratified reporting, and v1.0's hierarchical Rasch model replaces pooling entirely with per-task difficulty parameters `b_t` and per-domain ability offsets `gamma_{a,k}`, which is the principled fix. In v0.1 we ship the Kish-Wilson interval and label it "assumes within-domain exchangeability" in the API response metadata.

### 4.5 Per-domain stability

Per-task stability is fixed by the contract: `stab_t = max(0, 1 - 2*s_t)` where `s_t` is the Bessel-corrected sample std of the run scores `S_i` on task t. The domain-level figure is the **run-mass-weighted mean**, using the same `w_tk * n_t` mass as the pooled pass rate (so the pass rate and its stability companion describe the same evidence pool):

```
Stab_k = ( sum_t w_tk * n_t * stab_t ) / ( sum_t w_tk * n_t )
```

**Worked example** (same three tasks; per-task stds s_t = 0.10, 0.02, 0.25 give stab_t = 0.80, 0.96, 0.50):

```
Stab_backend = (1.0*5*0.80 + 0.5*5*0.96 + 0.25*10*0.50) / 10.0
             = (4.0 + 2.4 + 1.25) / 10.0 = 0.765
```

Deterministic agents (variance 0-by-construction per the run policy) report `stab_t = 1.0` with the `deterministic` flag propagated to the domain level: a domain stability of 1.0 renders with the flag, never silently.

**Low-n guard (inherited from 3.6, not renegotiated here).** A sample std from 5 points has ~35% relative error; 3.6 fixes the trust threshold for stability at **n >= 10**, below which `stab_t` is diagnostic-only with a low-n flag — "stability at n = 5 is decoration", and pooling decorations does not promote them to evidence. The guard travels with the value everywhere it goes:

- `Stab_k` carries a boolean **`stability_low_n`** flag, set whenever the majority of the run mass `sum_t w_tk * n_t` comes from tasks with `n_t < 10`. In the worked example only t3 meets the threshold (mass 2.5 of 10.0), so `Stab_backend = 0.765` ships **flagged**.
- The flag is stored alongside `stability` in `capability_profiles` (Section 10) and rendered alongside it in every view — a flagged stability never displays as a bare number.
- Downstream consumers must treat a flagged stability as **"insufficient data", not as a sortable value**: it does not participate in Pareto dominance via `g_stab` (Section 7.1) and cannot be the load-bearing term in any preset (e.g. "Most reliable agent") — otherwise a fluke-low `s_t` at n = 5 puts an agent on the frontier or wins the reliability preset on noise. Stability acquires an uncertainty band before it is allowed to move any ranking.

### 4.6 Overall score: macro-average with a comparability contract

```
Overall_a = (1/|K*|) * sum over k in K* of p-hat_k
K* = { domains k : number of tasks tagged with k (any weight) >= 5 }
```

**Why macro, not micro.** A micro (per-task or per-run) average is dominated by whatever domain happens to have the most tasks: if the v0.1 task bank has 40 backend tasks and 6 security tasks, a micro-average is ~87% a backend score wearing an "overall" costume, and adding 10 more backend tasks *changes every agent's overall score* without any agent changing. Macro-averaging gives each sufficiently-covered domain equal voice, so the overall score measures breadth across the capability space we defined, and is stable under re-balancing of the task bank within domains.

**Non-comparability rule.** Two agents' overall scores are comparable **only if computed over the same domain set K***. If agent A was evaluated on 7 domains and agent B on 4 (e.g., B's sandbox lacks a browser so frontend tasks were skipped), their macro-averages are averages of different quantities — comparing them is a category error, not a small bias. Enforcement: the API returns `domains_covered` alongside `overall`; the leaderboard UI greys out the overall column whenever the visible agents differ in K* and shows the banner "Overall scores computed over different domain sets — compare per-domain"; per-domain columns remain comparable and are the fallback.

**Worst-domain disclosure rule.** The non-comparability rule guards against K* mismatch across agents; it does nothing about a damning domain hidden *inside* the same K*. A macro-average buries a catastrophe: an agent at p-hat = 0.0 in `security` and 0.9 in six other domains shows `Overall = 0.77`, and a security-sensitive user sorting by Overall (the default sort, 7.7) picks a catastrophic agent. Two display obligations therefore attach to every rendering of `Overall_a`:

1. **The minimum per-domain LCB and its domain name render adjacent to Overall, always**: "Overall 0.77 — weakest: security 0.00". Whenever any covered domain's LCB falls below a configured floor (`overall_floor_lcb`, default 0.2), the agent's Overall sort value carries an inline warning badge — the default sort never presents an agent that is catastrophic in a covered domain without it.
2. **Domains excluded from K* (< 5 tasks) are listed next to Overall with their raw counts, never silently dropped.** Per the 4.8 honesty rule, a thin domain renders "insufficient data: m tasks / r runs"; if its observed runs are failing, it renders "insufficient data — observed failing (`sum c_t` / `sum n_t`)" rather than vanishing from the headline. Exclusion from the average must not become exclusion from the page.

### 4.7 Skill vector: representation, storage, display

The capability profile of agent a is the pair:

```
v_a = ( p-hat_1, ..., p-hat_K )      in [0,1]^K     (NULL where below threshold)
u_a = ( width_1, ..., width_K )                      width_k = UCB_k - LCB_k  (Wilson on n_eff)
```

**Storage.** Materialized in PostgreSQL, recomputed incrementally on run ingestion (cheap: per-domain running sums of `w*c`, `w*n`, `w^2*n` are sufficient statistics). The table is **`capability_profiles`, defined once in Section 10 (§10.2)** — this section deliberately ships no DDL of its own. Three properties of that single definition are load-bearing here:

1. **Keyed by `agent_version_id`, never by agent.** Per 9.6, any config change is a new agent version and a separate leaderboard entity; a per-agent key would pool runs across config changes, which the platform makes impossible by design rather than merely discouraged.
2. **`domain_id` is an FK to the `domains` table** (no inline text CHECK that drifts when the taxonomy is versioned), and rows are scoped to the pack per 8.5's comparability rule — the working key is `(agent_version_id, domain_id, pack_id, formula_version)`.
3. **Every row carries `formula_version`** per 10's derived-layer rule: derived rows are insert-only, a correction is a new version, never an UPDATE in place.

The Next.js frontend reads `capability_profiles` directly; `v_a`/`u_a` are assembled as a fixed-order (alphabetical domain order) JSON array at query time, never stored denormalized.

**Display.** Radar chart with K = 8 axes; for each shown domain the solid polygon vertex is `p_hat` and a shaded band spans `[lcb, ucb]` — the band is mandatory, a point estimate without its interval is banned in every domain view. **Minimum display thresholds:** a domain axis is hidden (rendered as a gap with the label "insufficient data: m tasks / r runs") unless **n_tasks >= 5 AND n_valid_runs >= 25** for that (agent, domain). Rationale: 5 tasks is the same coverage floor as the macro-average; 25 valid runs is 5 tasks at the default n = 5, below which the Wilson band spans most of [0,1] and the vertex position is visual noise that readers will over-interpret.

### 4.8 Drill-down: (domain x activity) cells

The profile page exposes the full 8 x 6 grid of cells — "debugging in backend", "migration in database" — each computed with exactly the machinery of 4.3–4.4 restricted to tasks with that (domain tag, activity tag) combination: pooled `p-hat`, Kish `n_eff`, Wilson band. Cell thresholds are lower than domain thresholds because cells are diagnostic, not ranked: a cell renders its estimate when it has **>= 3 tasks AND >= 15 valid runs**.

**Honesty rule (non-negotiable):** a cell below threshold renders the literal string `insufficient data` with its raw counts on hover — **never** 0, never blank-as-zero, never an extrapolation from neighboring cells or from the marginals. A rendered 0 is a strong claim ("tried and always failed"); an empty cell is a different fact ("not measured"); the UI must never convert the second into the first. The grid color scale therefore has a dedicated "no data" hatch pattern outside the value colormap.

### 4.9 Anti-claim: there is no universal score

We explicitly reject the single overall number as an *explanatory* device. `Overall_a` is a benchmark-relative macro skill average over the covered domains of **this task bank** — it exists in the UI for exactly one reason: a leaderboard needs a default sort key. It carries a permanent tooltip: *"Macro-average of per-domain pass rates on this benchmark's domains. Not a general intelligence or general coding-ability score. Click any domain for the real picture."* Every report, API response, and export labels it `macro_avg_domain_pass_rate`, never `score` or `ability`. The objects this framework treats as real are the skill vector `v_a` with its uncertainty `u_a`, the (domain x activity) grid, and — from v1.0 — the Rasch ability `theta_a` with per-domain offsets `gamma_{a,k}`, which is the statistically grounded successor to the macro-average, not to the profile.

### Limitations

- **Pooled intervals are optimistic under heterogeneity.** Kish n_eff corrects for unequal *weights*, not for between-task difficulty variance; a domain mixing trivial and brutal tasks will show a Wilson band narrower than honest. This is structural in v0.1 and only truly fixed by the v1.0 hierarchical model; until then the exchangeability label is a warning, not a remedy.
- **Fixed tag weights (1.0/0.5/0.25) are a convention, not an estimate.** Whether a "secondary" domain deserves half the evidential weight of a primary is asserted, not measured. v0.2's discrimination statistics can flag tasks whose secondary-domain outcomes correlate poorly with that domain's other tasks, but v0.1 has no defense beyond tagging discipline.
- **Taxonomy drift.** Eight domains and six activities will not survive contact with a growing task bank (where does "ML pipeline" go?). Adding a domain renders historical skill vectors length-incomparable; the planned mitigation is versioned taxonomies with scores keyed to taxonomy version, but cross-version comparison is simply lost.
- **Author-assigned scale tags are subjective.** Expected diff size is estimated before any agent runs; a task tagged S that consistently requires M-sized diffs (observable from captured diffs) silently miscalibrates any scale-stratified view. A v0.2 task-health flag comparing expected vs. observed median diff size is specified, but v0.1 ships without it.
- **Single activity tag forces lossy splits.** Real tasks sometimes are inseparably "migrate + fix"; splitting them changes the task's character. We accept the distortion to keep the activity axis exclusive; the alternative (weighted activity tags) would double the cell-grid sparsity problem.
- **Thresholds (5/25 domain, 3/15 cell) are judgment calls**, chosen so the Wilson band is meaningfully narrower than [0,1], not derived from a power analysis. With 8 x 6 = 48 cells, most cells will read "insufficient data" for a long time — that is the honest state, but it makes the drill-down underwhelming until the task bank is large.
