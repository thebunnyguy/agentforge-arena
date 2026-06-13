## 1. Raw run scoring

This section defines how one agent run i produces its continuous score S_i in [0,1], its binary functional pass X_i in {0,1}, and its run status. Everything is computable offline from three captured artifacts: the **execution trace** (commands, exit codes, timestamps), the **final diff** (unified diff against the task's pristine snapshot), and the **grader report** (clean-room test and analysis results). No signal requires an LLM judgment.

The run score is:

```
S = G * T_hidden * (0.85 + 0.15 * Q)

G        in {0,1}   product of five binary hard gates (Section 1.1)
T_hidden in [0,1]   weighted fraction of hidden tests passed (Section 1.2)
Q        in [0,1]   quality modifier (Section 1.3)
X = 1  iff  G = 1 AND T_hidden = 1 (every hidden test passed)
```

Correctness (G and T_hidden) carries between 85% and 100% of the score by construction; quality moves it only within that band. A run with perfect quality and zero passing hidden tests scores exactly 0.

### 1.1 Hard gates: definitions, detection, edge cases

G is the product of five binary gates. Each encodes a **validity precondition** — a condition under which the rest of the score is meaningful at all — not a quality dimension.

**setup_ok.** The task recipe's setup phase (dependency install, build, fixtures) must complete with exit code 0 before the agent starts, and the workspace must remain buildable when the grader applies the diff to the pristine snapshot. Only **agent-attributable** failures trip the gate; attribution is differential: the grader runs the identical setup on (a) the pristine snapshot and (b) the snapshot with the diff applied. If (a) fails, the fault is ours — the run voids as INFRA_FAILURE. If (a) succeeds and (b) fails (corrupted lockfile, deleted config, broken build script), setup_ok = 0. Transient errors (mirror hiccup, Docker daemon error, host OOM) match a maintained error-pattern table and classify as INFRA_FAILURE under the retry policy (Section 1.5).

**diff_exists.** The normalized diff (whitespace-normalized line counting; generated artifacts like `dist/`, `__pycache__/`, `node_modules/` excluded via the recipe's ignore list) must contain at least one changed line in a non-ignored path. An agent that modifies nothing has not attempted the task: diff_exists = 0, status AGENT_ERROR. Whitespace-only edits in real source files still count — the gate checks existence, not merit; merit is T_hidden's job.

**scope_ok.** The diff must touch zero **protected paths**: test directories, grading manifests, CI configuration, and `.agentforge/` harness files, enumerated as glob patterns in the task recipe. Detection is a path match over the diff's file list, including rename sources/targets and file-mode changes. This is defense in depth: grading already happens against pristine hidden tests in the clean room, so scope_ok invalidates the *attempt*, not protects the grader.

**regression_pass.** The repo tests recorded as passing at snapshot-creation time must still pass when the grader runs them in the clean room on the patched tree. Tests failing or skipped at baseline are excluded (recorded in the snapshot manifest), so an agent is never punished for pre-existing breakage. This gate makes "fixed the feature, broke three others" score 0 instead of 0.7.

**no_timeout.** The agent must terminate within the task's wall-clock budget (recipe field; default 30 minutes), enforced by SIGKILL. A killed run gets status TIMEOUT, X = 0, S = 0; the partial diff is captured for forensics, not graded. Grader-side timeouts are INFRA_FAILURE, not agent behavior.

**Why binary and multiplicative, not weighted.** A weighted sum lets excellence on one axis buy back a violated precondition: an agent that nukes the regression suite but aces hidden tests would still score well, and the leaderboard would reward vandalism. Multiplication of binaries is a logical AND — every S = 0 has a named, displayable cause ("regression_pass failed: 3 tests"), keeping failures explainable. Gate weights would also be pure invention at v0.1 data volumes; binaries need no calibration.

### 1.2 T_hidden, and why S and X both exist

```
T_hidden = sum_j (w_j * pass_j) / sum_j (w_j)

pass_j in {0,1}   outcome of hidden test j in the clean room
w_j > 0           per-test weight from the task's scoring recipe; default w_j = 1 for all j
```

Hidden tests run only in the **clean room**: the grader applies the captured diff to a pristine repo snapshot inside a separate sandbox the agent never executed in. The agent cannot read, modify, or poison them. Per-test weights let task authors mark a core acceptance test heavier than edge-case probes (e.g., core test w = 3, six edge tests w = 1 each: passing core plus 3 edges gives T_hidden = (3+3)/(3+6) = 0.6667). Default is equal weights.

Worked example: 10 equal-weight hidden tests, 7 pass: T_hidden = 7/10 = 0.7.

Both S and X are kept because they answer different questions. X feeds p-hat = c/n, the Wilson interval, and the headline leaderboard — shipping software needs *all* tests to pass, and the confidence machinery of later sections is built on binary outcomes. S preserves the gradient X discards: an agent at T_hidden = 0.9 across runs differs materially from one at 0.1, though both have p-hat = 0. S powers diagnostics, drill-downs, and stability = max(0, 1 - 2s); it is never the headline.

### 1.3 Quality modifier Q

```
Q = sum_j (v_j * q_j) / sum_j (v_j)      over AVAILABLE components j

Component        v_j     q_j formula
lint             0.20    q_lint = max(0, 1 - L_new/10)
typecheck        0.25    q_type = 1 if typecheck passes on patched tree, else 0
static analysis  0.20    q_static = min(1, max(0, 1 - max(0, W_post - W_base)/10))
security scan    0.20    q_sec = max(0, 1 - V_new/3)
diff parsimony   0.15    q_pars: see below
```

Symbols: L_new = max(0, lint error count on the patched tree minus lint error count at baseline), **plus** every suppression directive added in the diff (`eslint-disable`, `# noqa`, `# type: ignore`, `@SuppressWarnings`) — suppressions count as errors, closing the obvious dodge. A pure count delta, like q_static: matching individual findings across the two trees would require mapping baseline line numbers through the diff's hunk offsets, and the slight coarseness of counts is not worth that machinery. W_base, W_post = static-analysis warning counts (ruff/eslint rule sets pinned per task) at baseline and on the patched tree; only regressions are penalized, and improvements cap at q_static = 1 (no farming negative deltas). V_new = severity-weighted new security findings from offline scanners (bandit/semgrep with local rule packs): high = 3, medium = 1, low = 0.25 — one new high-severity finding zeroes q_sec.

Diff parsimony:

```
A   = lines added + lines removed in the agent's normalized diff (non-ignored paths)
R   = same count for the task's reference solution (stored in the recipe)
rho = A / max(R, 10)

q_pars = 1                    if rho <= 4
q_pars = (10 - rho) / 6       if 4 < rho < 10
q_pars = 0                    if rho >= 10
```

The flat region up to 4x the reference size avoids penalizing legitimate alternative implementations; the penalty is deliberately one-sided and tolerant because R comes from a reference solution the agent never sees (Section 8.1) and therefore cannot calibrate against — a correct solution that adds input validation, error handling, or defensive code the reference omitted is never penalized inside the flat region, and only egregious bloat (10x the reference) zeroes the component. The floor max(R, 10) avoids hair-trigger ratios on tiny tasks. Crucially, **parsimony cannot reward tiny non-solutions**: q_pars caps at 1, and multiplicatively a one-line stub with perfect Q scores S = T_hidden * 1.0 — near 0 for a non-solution. Small diffs earn nothing; only non-bloated *correct* diffs avoid losing up to 15%.

**Availability renormalization (decision):** if a component cannot be computed — no typechecker for the language, baseline already failing lint/typecheck, no reference solution for q_pars — it is dropped and the remaining weights renormalize to sum 1. If *every* component is unavailable, the formula's denominator is 0; in that case Q := 1 (the multiplier collapses to 1 — no quality evidence must not penalize). The grader report records which components were active, so Q is never silently computed over different bases without a flag.

**v0.1 toolchain (decision):** the grader image ships a pinned Python-only toolchain — ruff (lint and static analysis), mypy (typecheck), bandit (security scan) — plus parsimony, which is language-agnostic. For every other ecosystem, those components are unavailable at v0.1 and drop via the renormalization rule above; they gain their toolchains (eslint, tsc, semgrep rule packs, etc.) in v0.2. No formula change is involved — only the supported matrix per release stage.

### 1.4 Signal disposition

Every candidate signal, with its verdict:

| Signal | Disposition |
|---|---|
| Hidden tests passed | **T_hidden** (the correctness core) |
| Regression tests passed | **Gate** regression_pass |
| Setup success | **Gate** setup_ok (agent-attributable only) |
| Final diff exists | **Gate** diff_exists |
| Unexpected files changed (protected) | **Gate** scope_ok |
| Timeout | **Gate** no_timeout — gate, not deduction |
| Lint / typecheck | **Q** (0.20 / 0.25) |
| Static analysis delta | **Q** (0.20) |
| Security checks delta | **Q** (0.20) |
| Lines added/removed | **Q** via parsimony (0.15) |
| Visible tests passed | **Rejected from score; logged** as self-check alignment (below, this section) |
| Runtime / cost / memory | **Rejected from S**; separate multi-objective axes (Pareto dashboard, v0.2) |
| Test coverage of agent's change | **Rejected as reward**; task-validation tool only |
| Mutation testing score | **Rejected as reward**; task-validation tool only |
| Command failures, redundant loops, wall-clock per command | **Trace diagnostics**, never scored (below, this section) |
| Expected files changed (non-protected) | **Diagnostic**: overlap with the recipe's expected-file list is logged, not scored — agents may legitimately touch different files |

**Why visible tests are excluded.** Visible tests are the agent's feedback loop. The moment they carry score weight, the optimal strategy shifts from "solve the task" to "satisfy the visible suite" — special-casing inputs, hardcoding outputs — Goodhart's law exactly. Hidden tests in the clean room are the only correctness oracle. We do log **self-check alignment**: a run whose final visible-test execution passed but X = 0 is flagged `selfcheck_misaligned = 1`. The per-agent misalignment rate (misaligned runs / runs where visible passed) is a deterministic overfitting indicator, and a task where *every* agent misaligns has visible tests that under-specify the hidden contract — a task-health signal.

**Why runtime and cost are excluded from S.** Folding speed into S buries an incommensurable trade-off behind an arbitrary exchange rate ("how many hidden tests is a minute worth?" has no defensible answer) and punishes deliberate agents that verify their work. Runtime, compute cost, and peak memory are recorded per run and surface as separate axes in the v0.2 Pareto dashboard, where dominance is meaningful and a weighted blend would not be. The one time judgment we make is the budget: exceeding it is a binary failure (no_timeout), because an agent that never finishes delivers nothing — but a fast wrong answer must never outscore a slow right one, which is what every continuous time deduction eventually produces.

**Why coverage and mutation score validate tasks, not reward runs.** Both metrics judge a *test suite*, so we point them at the thing that is one: at task-authoring time the hidden suite must reach a coverage threshold on the reference solution's touched lines, and an offline mutation run (mutmut/cosmic-ray) against the reference solution must kill a minimum fraction of mutants — otherwise the task ships with a weak oracle and gets a task-health flag. As per-run agent rewards they fail both criteria for a scored signal: **gameable** (assert-free tests inflate coverage; trivially-killable mutants inflate mutation score) and **noisy** (mutation runs are slow, with run-to-run sampling variance that would dwarf the signal).

**Trace diagnostics (deterministic, unscored).** From the trace we compute command failure rate (non-zero exits / total commands), redundant-loop count (maximal runs of >= 3 consecutive identical normalized command lines), and wall-clock distribution across command categories (build/test/edit/explore, via a fixed regex table). These appear on the run-detail page and feed the v2.0 trace-quality classifier as features. They are never in S: an agent that flails for 20 minutes and then nails every hidden test *solved the task*, and the score must say so.

### 1.5 Run status taxonomy

| Status | In n? | X | S | Trigger |
|---|---|---|---|---|
| VALID | yes | per grading | per formula | normal completion, graded |
| TIMEOUT | yes | 0 | 0 | wall-clock budget exceeded (SIGKILL) |
| AGENT_ERROR | yes | 0 | 0 | agent crash, no diff produced, harness-protocol violation by the agent |
| INFRA_FAILURE | **no** | — | — | sandbox/grader/host fault; pristine-snapshot setup fails; error-pattern match |

INFRA_FAILURE runs are **voided**: excluded from n, auto-retried up to 2 times with fresh sandboxes, operator alert if all three attempts fail. Voiding is an honesty requirement: an infra failure is an outcome of *our* system, independent of agent ability, and infra incidents cluster in time — whichever agents ran during the bad hour would absorb the failures. Folding them into p-hat adds noise correlated with the schedule and uncorrelated with skill, silently corrupting every cross-agent comparison. TIMEOUT and AGENT_ERROR, by contrast, *are* agent outcomes and count as failures in n.

### 1.6 Worked example, end to end

Run: all five gates pass (G = 1). Hidden suite: 10 tests, equal weights, 7 pass. Quality inputs: lint clean with no added suppressions (L_new = 0), typecheck **fails** on the patched tree, static analysis W_base = 12, W_post = 12, security scan V_new = 0, diff A = 200 changed lines vs reference R = 40.

```
T_hidden = 7/10 = 0.7

q_lint   = max(0, 1 - 0/10)        = 1
q_type   = 0                        (typecheck failed)
q_static = min(1, max(0, 1 - 0/10)) = 1
q_sec    = max(0, 1 - 0/3)          = 1
rho      = 200 / max(40,10) = 5
q_pars   = (10 - 5)/6 = 5/6         = 0.8333

Q = 0.20*1 + 0.25*0 + 0.20*1 + 0.20*1 + 0.15*0.8333
  = 0.20 + 0 + 0.20 + 0.20 + 0.125 = 0.725

S = 1 * 0.7 * (0.85 + 0.15*0.725) = 0.7 * 0.9588 = 0.6711
X = 0   (3 hidden tests failed)
```

Status VALID; the run contributes X = 0 to c and S = 0.6711 to the diagnostic distribution.

### 1.7 Gameability analysis

| Scored component | Exploit | What bounds the damage |
|---|---|---|
| T_hidden | Hardcode outputs the tests expect | Agent never sees hidden tests; clean room re-derives results from pristine tests. Overfitting visible tests surfaces as selfcheck misalignment, not score. |
| T_hidden | Edit test files so suites pass locally | Clean room uses pristine tests; scope_ok additionally zeroes the run. |
| q_lint / q_type | Add suppression directives instead of fixing | Each added suppression counts in L_new; typecheck is binary on the real tree. Worst case bounded: all of Q moves at most 15% of S. |
| q_static / q_sec | Mass-fix unrelated warnings to bank credit | Deltas cap at 1; improvements earn nothing beyond the cap. |
| q_pars | Submit a minimal stub diff | Multiplicative structure: stub fails hidden tests, T_hidden ~ 0, so S ~ 0 regardless of q_pars = 1. |
| q_pars | Golf a correct solution into dense one-liners | Parsimony counts changed lines, not characters; the flat region to 4x R leaves no incentive below it. |
| no_timeout | Bail early with garbage to dodge the gate | Early garbage scores ~0 anyway; the gate punishes only non-termination. |
| setup_ok | Self-report success | Gates are computed by the harness and grader from exit codes and differential reruns, never from agent claims. |

The structural defense is uniform: every exploitable surface is either (a) measured in an environment the agent cannot reach, or (b) confined to the multiplicative 15% quality band, which only pays out on top of correctness the agent must earn the hard way.

### Limitations

- **Parsimony depends on a reference solution the agent cannot see.** rho is anchored to R, so an unusually verbose or golfed reference skews q_pars for everyone, and because the reference is private (Section 8.1) the penalty onset is unpredictable from the agent's side — a correct-and-thorough solution beyond 4x R loses up to 2.25% of S for defensiveness the reference omitted. The wide flat region and the 10x zero-point bound this, and tasks without a reference drop the component, so Q's basis varies across tasks. Remaining mitigation is procedural (reference-diff review at authoring), not mathematical.
- **Setup attribution is a pattern table plus a differential rerun.** Novel infra failure modes that reproduce deterministically with the diff applied get misclassified as agent faults until the pattern table catches up; the alert-after-retries rule limits but does not eliminate this.
- **Q's weights (0.20/0.25/0.20/0.20/0.15) are uncalibrated judgment calls** at v0.1 data volumes. Miscalibration is bounded by the 15% band but real; any later re-weighting must recompute historical S from the append-only raw signals.
- **Per-test weights w_j make T_hidden task-local.** Acceptable because cross-task aggregation runs on X, not S — but averaging S across tasks mixes units.
- **V_new severity weights (3/1/0.25) inherit the scanners' noisy severity taxonomy;** one false-positive high finding zeroes q_sec, with no appeal path beyond task-recipe rule suppression.
- **The 30-minute default budget shapes behavior** (discourages long verification loops) even though runtime is otherwise outside S; per-task budget tuning is a task-design responsibility this section only parameterizes.
