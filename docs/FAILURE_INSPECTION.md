# Failure Inspection — four suspicious cells

A forensic look at the four most suspicious (agent × task) cells in the initial
v0.2 data snapshot (24 tasks × 5 models, 500 runs at inspection time). The DB
now contains 600 model runs; this document preserves the evidence available
when the inspection was performed.

Each cell was inspected by an agent and then **adversarially re-verified** by an
independent skeptic that re-pulled the raw data and tried to refute the
diagnosis. All four verdicts survived. Provenance is at the bottom.

---

## Read this first — what the data does and doesn't contain

The first 500 legacy rows persisted **only aggregate metrics** per run: `status`,
the gate product `G`, `t_hidden`, the final score `S`, `functional_pass` (`X`),
`files_changed`, and lines added/removed. Those rows did **not** persist the
agent's patch or per-test results. This was fixed before the final 100 P0 runs:
pipeline records now carry their `GradeReport`, and `eval_persist.py` passes it
to the store so new rows include patch and per-test artifacts.

Consequently the per-run diagnoses below are **inferences from the aggregate
signals**, cross-checked against (a) the snapshot/reference baselines re-measured
directly for this report and (b) the hidden-suite source — *not* reads of the
actual patch or per-assertion pass/fail. When a run is labelled `wrong-fix` it
means "G=1, regression passed, but 0 of N hidden passed"; the exact wrong line
cannot be shown from this DB. The cell-level verdicts do **not** depend on the
missing data — they rest on `G`, `t_hidden`, `X`, and the line counts, which are
all persisted and independently re-derived.

**Scoring recap.** `S = G · T_hidden · (0.85 + 0.15·Q)`. Quality inputs are
absent offline, so `Q = 1` and **`S = T_hidden` whenever `G = 1`**. `G ∈ {0,1}`
is the product of five hard gates (`setup_ok`, `diff_exists`, `scope_ok`,
`regression_pass`, `no_timeout`); any failing gate ⇒ `G = 0 ⇒ S = 0`. The
leaderboard `p_hat = functional_passes / valid_runs`, and `X` (functional pass)
is true **only if `G = 1` and every hidden test passes** — so partial hidden
credit never reaches `p_hat`.

---

## Verified baselines (measured for this report, DB-independent)

Run directly here: the unmodified snapshot and the reference fix, each against
the task's hidden suite. These anchor every "baseline coincidence" claim below.

| task | hidden tests | unmodified snapshot | reference fix |
|---|---|---|---|
| fix-binary-search | 9 | **3 / 9 = 0.333** | 9 / 9 = 1.000 |
| toposort | 12 | 0 / 12 = 0.000 | 12 / 12 = 1.000 |
| expression-evaluator | 10 | 0 / 10 = 0.000 | 10 / 10 = 1.000 |
| top-k-frequent | 12 | 0 / 12 = 0.000 | 12 / 12 = 1.000 (300k-input test in 0.16 s) |

---

## Cell 1 — `fix-binary-search` (mixed; the 0.333 mirage)

**The bug.** The snapshot's `bisect_left` has an extra branch
`elif sorted_list[mid] == target: lo = mid + 1`, which advances the lower bound
past equal elements — turning a leftmost-insertion search into an *upper-bound*
(`bisect_right`). The fix is to delete that branch (fold it into `else: hi = mid`).

**Why the snapshot already scores 3/9.** Three hidden tests don't exercise the
duplicate/leftmost bug at all (`test_target_absent_insertion_point`,
`test_before_first_and_after_last`, `test_empty_list`), so the *unmodified* buggy
code passes them. That 3/9 = **0.333** is the recurring number below.

| agent | run | G | T_hidden | S | X | Δlines | mode |
|---|---|---|---|---|---|---|---|
| deepseek-coder:6.7b | #0 | 0 | 0.000 | 0.000 | ✗ | +3/−3 | gate-fail |
| deepseek-coder:6.7b | #1 | 0 | 0.000 | 0.000 | ✗ | +0/−21 | gate-fail (gutted file) |
| deepseek-coder:6.7b | #2 | 0 | 0.000 | 0.000 | ✗ | +0/−21 | gate-fail (gutted file) |
| deepseek-coder:6.7b | #3 | 0 | 0.000 | 0.000 | ✗ | +3/−3 | gate-fail |
| deepseek-coder:6.7b | #4 | 0 | 0.333 | 0.000 | ✗ | +0/−0 | no-diff (baseline) |
| gemma2:2b | #0 | 1 | 0.000 | 0.000 | ✗ | +3/−2 | wrong-fix |
| gemma2:2b | #1 | 0 | 0.333 | 0.000 | ✗ | +0/−0 | no-diff (baseline) |
| gemma2:2b | #2 | 1 | 0.000 | 0.000 | ✗ | +2/−2 | wrong-fix |
| gemma2:2b | #3 | 0 | 0.000 | 0.000 | ✗ | +24/−0 | gate-fail |
| gemma2:2b | #4 | 1 | 0.000 | 0.000 | ✗ | +3/−2 | wrong-fix |
| qwen2.5-coder:3b | #0 | 0 | 0.333 | 0.000 | ✗ | +0/−0 | no-diff (baseline) |
| qwen2.5-coder:3b | #1 | 0 | 0.333 | 0.000 | ✗ | +0/−0 | no-diff (baseline) |
| **qwen2.5-coder:3b** | **#2** | **1** | **0.333** | **0.333** | ✗ | **+1/−1** | **partial-fix (no-op)** |
| qwen2.5-coder:3b | #3 | 0 | 0.333 | 0.000 | ✗ | +0/−0 | no-diff (baseline) |
| **qwen2.5-coder:3b** | **#4** | **1** | **1.000** | **1.000** | **✓** | **+1/−6** | **LEGIT PASS** |

Modes: 5 gate-fail, 5 no-diff (baseline), 3 wrong-fix, 1 partial-fix, 1 pass.
Functional passes: **1 / 15**.

**What the scoring got right.**
- The five `files_changed=0` runs show `T_hidden=0.333`, but the `diff_exists`
  gate fails ⇒ `G=0`, `S=0`, `X=False`. **The 0.333 mirage is contained to the
  `t_hidden` column and never reaches `p_hat`.**
- The three gemma `wrong-fix` runs (`G=1`, `T_hidden=0`) score **below** the
  do-nothing baseline — a confidently wrong rewrite. They pass `G` only because
  the regression suite is *deliberately weak* (it checks `is_sorted` and that the
  return is an `int`), by design, so the hidden suite is the sole correctness
  signal. It caught them.
- The one genuine pass, qwen2.5-coder:3b #4 (`+1/−6`, deletes the bad branch),
  clears all 9 hidden tests = the reference fix.

**The one sharp edge — over-generous partial credit.** qwen2.5-coder:3b #2
(`+1/−1`, `G=1`) lands `S=0.333` — *exactly the do-nothing baseline*. It is a
behavioural no-op that still banks a third of the score. It does **not** inflate
`p_hat` (`X=False`, so the cell is still 1/15 = 0.067), but `S=0.333` flatters a
non-fix on the mean. → See recommendation 2.

**Verdict (verified):** legitimate measurement, with a correctly-contained
baseline-coincidence artifact and one over-generous partial-credit run.

---

## Cell 2 — `toposort` 0/5 (partial credit without correctness)

**The task.** Implement a deterministic topological sort from a stub. The 12
hidden tests demand **three independent behaviours at once**: collecting implicit
nodes (those appearing only as a dependency), a strict **lexicographic** tiebreak
among simultaneously-ready nodes (a min-heap / `sorted` Kahn), and **cycle
detection** raising `CycleError`.

| agent | runs | G | T_hidden range | X | dominant mode |
|---|---|---|---|---|---|
| deepseek-coder:6.7b | #0–#4 | 1 (×4), 0 (×1) | 0.083 – 0.417 | 0/5 | partial-fix |
| gemma2:2b | #0–#4 | 1 (×5) | 0.083 – 0.500 | 0/5 | partial-fix |
| qwen2.5-coder:3b | #0–#4 | mixed | 0.000 – 0.417 | 0/5 | no-diff / partial |

Modes across the cell: **10 partial-fix**, 3 no-diff, 1 wrong-fix, 1 gate-fail.
Functional passes: **0 / 15**. Best single run: gemma2:2b #1 at `T_hidden=0.500`
(6/12).

**Why 0/5 is real.** No model produced all three behaviours simultaneously, and
`X` requires all 12 hidden tests. The discriminating failures are consistent
across models: the two strict-lexicographic determinism tests
(`…_deterministic_lexicographic`, `…_prefers_lexicographic_among_eligible`) and
the cycle tests (especially `…_implicit_dependency_in_cycle_is_still_a_cycle`). A
plain DFS/Kahn without a min-heap produces a *valid but non-deterministic* order
that fails the exact-equality determinism tests.

**The honesty nuance.** Partial credit up to 0.5 is somewhat **over-generous as a
correctness signal**: 3 of the 12 hidden tests only assert pairwise
"dependency-before-dependent" (`_before`) and accept *any* valid topo order, so a
model that never wrote a tiebreak or cycle check can still bank ~5/12. But this
**cannot** move the leaderboard: `p_hat` counts only functional passes (all 12),
which stays 0/5. The partial `T_hidden` shows up only in the domain-profile mean,
where it should be read as **"close," not "partially correct against the
contract."**

**Verdict (verified):** legitimate 0/5; partial credit is informative progress,
not partial contract-correctness.

---

## Cell 3 — `expression-evaluator` 0/5 (hard, not mis-specified)

**The task.** Implement a precedence-aware arithmetic evaluator (recursive
descent / shunting-yard, no `eval`) from a stub. Difficulty 5 — the hardest task
in the pack.

| mode | count | meaning |
|---|---|---|
| wrong-fix (G=1, T_hidden=0) | 10 | large parser rewrite passes regression, fails every hidden test |
| gate-fail | 3 | broke import/scope or regression |
| partial-fix | 1 | deepseek #3, `T_hidden=0.300` |
| no-diff (baseline) | 1 | qwen #0 |

Functional passes: **0 / 15**. Ten runs emit parser-shaped diffs of **+59…+77
lines** that clear the gates but fail all 10 precedence / parens / unary-minus /
float-division tests; only one run reached even partial credit.

**Why it's fair, not over-constrained.** Re-measured here: the reference parser
passes all 10 hidden + 4 regression tests; the stub scores 0/10; there is **no
baseline-coincidence channel** (every hidden test raises on the stub). So 0/5 is
a real capability signal — these small models cannot one-shot a correct
precedence-respecting parser with unary minus and float division. The task is
genuinely hard, not mis-specified.

**Verdict (verified):** legitimate hard task; the floor is the model, not the
benchmark.

---

## Cell 4 — `gemma2:2b` on `top-k-frequent` 4/5 (the legit outlier)

The single most counter-intuitive cell: the **weakest** model overall
(leaderboard `p_hat ≈ 0.05`) scores **4/5** on a *performance* task.

| agent | run | G | T_hidden | S | X | Δlines | mode |
|---|---|---|---|---|---|---|---|
| gemma2:2b | #0 | 1 | 1.000 | 1.000 | ✓ | +10/−1 | LEGIT PASS |
| gemma2:2b | #1 | 1 | 1.000 | 1.000 | ✓ | +7/−1 | LEGIT PASS |
| gemma2:2b | #2 | 1 | 1.000 | 1.000 | ✓ | +12/−1 | LEGIT PASS |
| gemma2:2b | #3 | 1 | 1.000 | 1.000 | ✓ | +13/−1 | LEGIT PASS |
| gemma2:2b | #4 | 1 | 0.000 | 0.000 | ✗ | +2/−1 | wrong-fix |

**Ruling: the 4 passes are genuine — correct *and* efficient.** Efficiency is
enforced by the `no_timeout` **hard gate** on a 300 000-element hidden input: a
quadratic `items.count()` solution is cut off and zeroes `G`. All four passing
runs have **both `G=1` and `T_hidden=1.0`**, which is only possible if the
large-input tests passed under the 20 s timeout *and* all 12 assertions held.
This is not baseline-coincidence (every run has `files_changed=1`) and not
over-generous partial credit (the one failure is a clean `T_hidden=0.0`).

**Why a weak model aces it.** `collections.Counter(items).most_common(k)` is an
O(n) idiom a small model can emit verbatim — and its stable sort happens to honor
the required first-appearance tiebreak. **Per-task pass rate is not monotonic in
overall model strength**: gemma's low overall score is dominated by harder tasks;
this one matches a known idiom and is time-gated against the cheap shortcut, so
the outlier is real and honest.

**Correction caught by verification.** An earlier draft of the diagnosis claimed
"stronger models (llama3.2, qwen2.5-coder:7b) pass with the same signature." The
skeptic refuted it: qwen2.5-coder:7b passes only **1 of 5** top-k runs (idx 2;
the rest at `T_hidden` 0.083/0/0/0), and the agent is recorded as
`llama3.2:latest`. The claim was **removed** — the four gemma passes stand on
their own gate + `T_hidden` evidence and need no cross-model prop.

**Verdict (verified):** legitimate; the outlier is real.

---

## What this confirms about the framework

- **`diff_exists` contains the baseline mirage** — a no-diff run can show
  `T_hidden>0` from snapshot coincidence, but `G=0` keeps it out of `S` and `p_hat`.
- **Weak-regression-by-design isolates the hidden suite** — a confidently wrong
  fix that scores *below* the do-nothing baseline is still caught (gemma binary-search).
- **`no_timeout` makes performance non-fakeable** — the quadratic shortcut can't
  pass top-k; only a near-linear solution clears the gate.
- **`functional_pass = all-hidden` keeps `p_hat` honest** — toposort's generous
  partial credit never becomes a leaderboard pass.

## Findings / recommendations

1. **[resolved data gap]** The first 500 rows lack patch/per-test artifacts.
   `eval_persist.py` and the pipeline now pass the `GradeReport` into
   `SqliteRunStore.save_run`; the 100 completion runs persist real patches and
   available regression/hidden test outcomes.
2. **[scoring]** Over-generous partial credit when a "fix" merely matches the
   do-nothing baseline (qwen2.5-coder:3b binary-search #2: `S=0.333` for a no-op).
   Consider flooring `T_hidden` against the snapshot baseline so a change that
   doesn't beat "do nothing" earns 0 on `S`. (`p_hat` is already immune.)
3. **[reporting]** Present toposort/expr partial credit as *progress toward* the
   contract, not partial correctness *of* it — the domain-profile mean can read as
   "close" when zero runs actually satisfy the full spec.

## Provenance

- **Workflow** `failure-inspection`: 8 agents (4 forensic inspectors + 4
  adversarial verifiers). All four cell verdicts held under verification; the
  verifiers corrected one overstatement (cell 4 cross-model claim) and flagged the
  patch_text/test_results data gap.
- **Baselines** (snapshot & reference hidden-suite scores) re-measured directly in
  this session, independent of the run DB.
- **Tables** derived deterministically from `reports/runs.sqlite` aggregate
  columns. Cells: 15 / 15 / 15 / 5 runs (of 500 total).
