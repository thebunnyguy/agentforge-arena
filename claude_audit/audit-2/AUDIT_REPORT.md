# AgentForge Arena — Audit-2 Report (adversarial re-audit)

> External, strict, evidence-backed **re-audit** at commit `798a5b3` (`master`, clean, synced with `origin/master`). Read-only — no production code was changed by this audit. This is **audit-2**; it supersedes audit-1 (53/100 at `036cde4`) for current-state claims and preserves audit-1's finding IDs so closure is traceable.
>
> **Method.** The lead auditor re-verified the load-bearing facts first-hand (full pytest, §8 `validate_task` over all 24 tasks, SQLite integrity, byte-reproducibility, Wilson recompute, forensic-cohort consistency). A 13-agent **adversarial** re-audit workflow then tried to prove each "closed" finding was actually papered over, inspected the new patch-level forensic cohort, hunted for new defects, and re-scored all 10 dimensions. Every agent finding was reconciled against first-hand evidence; **one agent false-positive was caught and discarded** (see below).

---

## Executive verdict

- **Overall grade: 75 / 100** (audit-1: 53/100; **+22**).
- **P0 status: 3/3 genuinely closed** under independent adversarial re-derivation.
- **Maturity:** trustworthy research-grade **evaluation benchmark + local CLI harness**. Still **not product-ready** and **not safe for untrusted agents**.
- **Biggest strength:** evaluation validity is recovered — 600 real persisted runs, a forensic cohort that is 100% score/test-consistent, and persisted patches that trace to real task semantics; the leaderboard regenerates **byte-identically** from the committed DB.
- **Biggest weakness:** still a CLI/library — no dashboard/API/run-viewer/CONTRIBUTING — and no untrusted-agent isolation (`DockerSandbox` unimplemented).
- **Most dangerous unresolved risk:** anti-gaming holds only under the trusted-local-agent assumption (hidden tests readable on the shared FS during `act`; no `DockerSandbox`). Fine for the current local eval; blocking for any untrusted/public use.
- **Next mandatory step:** none blocking for a research/portfolio benchmark. To advance maturity: re-evaluate the 3 strengthened (v1.0.1) tasks so their published cells match their current hidden suites, and implement `DockerSandbox` before admitting untrusted agents.

The honest one-liner: **audit-1's integrity hole is genuinely fixed — the benchmark now is what it claims to be — and what's left is scope (product surface, untrusted isolation), not honesty.**

---

## Scorecard

(Full justification + deltas in `AUDIT_SCORECARD.md`.)

| Dimension | Now | Prior |
|---|---:|---:|
| Scoring / math correctness | 8.5 | 8.5 |
| Test suite quality | 9.0 | 8.5 |
| Task pack quality | 7.5 | 7.0 |
| Clean-room / security | 7.0 | 6.5 |
| Real-agent evaluation validity | 7.5 | 4.0 |
| Domain coverage | 8.0 | 5.0 |
| Report quality | 7.5 | 4.5 |
| Reproducibility | 7.5 | 2.5 |
| Product usability | 4.5 | 4.0 |
| Documentation accuracy | 7.5 | 3.0 |
| **Total** | **75** | **53** |

---

## Closure verification (the core of a re-audit)

Each audit-1 finding was re-derived adversarially. Verdicts:

### Genuinely closed
- **P0-1 — fabricated leaderboard.** `report_combined.py` is DB-first; `KNOWN_OLD`/`recon` are absent; the DB holds 600 real rows with 0 synthetic-named/recon/voided/duplicate; pass counts (qwen7b 68, deepseek 38, qwen3b 32, llama 26, gemma2 6) match. Oracle/noop are injected in-memory only, labeled `(synthetic baseline)`.
- **P0-2 — non-reproducible.** `runs.sqlite` and `leaderboard.html` are git-tracked; regenerating the report **3×** yields a byte-identical leaderboard (SHA `87ca6c77…`) and unchanged DB (SHA `519bee8a…`). The only date string is a DB-derived "run window", not wall-clock.
- **P0-3 — gap-filled domains.** Every one of the 5 models now has ≥5 tasks **and** ≥25 real runs in **every** domain (api/async/perf/security = 25 runs, backend = 85). Zero cells gap-filled.
- **P1-1 (forward) — empty forensic layer.** `GradeReport` is threaded through pipeline → store → `eval_persist`; the last 100 runs carry 100 patches + 1,218 per-test rows; the first 500 remain NULL (legacy, irrecoverable).
- **P1-2 — README/data contradictions.** README is `v0.2.0`, `llama3.2:latest@a80c4f17acd5`, `python3`; the leaderboard matches the DB; the 500→600 transition is dated in `FAILURE_INSPECTION.md`.
- **P1-4 — untested generator.** `test_report_combined.py` is proven **non-smoke by mutation**: injecting a fabricated `recon` row makes it FAIL (`assert 2 == 1`).
- **P2-1 — parsimony doc drift.** Reconciled in **both** framework docs (`01-run-scoring.md` and the consolidated `EVALUATION_FRAMEWORK.md`): 2×/8× added-only, §1.6 example `S = 0.6659`, no residual `4x/10x/0.6711`.
- **P2-2 — case-sensitive guard / P2-3 — symlink capture.** `diffing.py` normalizes `/` and `\` and uses `casefold()`; `snapshot_tree` skips any symlinked path component. Both tested.
- **P2-4 — substring-only report tests.** Report tests now assert numeric Wilson values/rank ranges + counts; a cross-domain integration test was added.
- **P2-6 — undisclosed domain skew.** README/docs/report disclose backend 17/24 and api/perf 3 primary tasks, with weights and a coverage caveat.
- **P3-3 — over-generous partial credit / P3-4 — n_tasks overcount.** `baseline_adjusted_t_hidden` is defined + tested but deliberately **not wired** into `score_run` (formula v0.1 unchanged); `domain_profile` now counts only tasks with ≥1 valid run.

### Partially closed
- **P2-5 — weak task cells.** The hidden suites were genuinely strengthened (async-batched 5→9–11, top-k 12→16, **refactor-order-validation 1→21** — its `validate_task` `n_hidden=1` is a collection-error artifact on the bare snapshot, not the real count). **But** the committed leaderboard cells for these 3 tasks still reflect v1.0.0 grading; the report discloses this with a version badge rather than re-evaluating. Strengthened, not re-measured.

### Still open (disclosed)
- **P1-3 — untrusted isolation.** No `class DockerSandbox` exists; the agent receives `task.task_dir` and hidden tests are readable on the shared FS during `act`. Valid only under the trusted-local-agent assumption.
- **P1-5 — no product surface.** No FastAPI/uvicorn/Next.js, no run-detail viewer, no `CONTRIBUTING`.
- **P1-1 legacy half.** The first 500 runs have no patch/per-test detail and cannot be reconstructed.

### Lead-auditor correction (false positive caught)
One re-audit agent claimed **P2-1 was papered over** because `EVALUATION_FRAMEWORK.md` "still has the old parsimony curve." This is **false** — grep shows that file already carries the 2×/8× curve (lines 163–164) and `S = 0.6659` (line 235). The finding was discarded; P2-1 is fully closed. (Recorded here for transparency about the method.)

---

## Patch-level forensic confirmation (newly possible)

Audit-1 could only infer failure modes from aggregates (`patch_text` was NULL ×500). The last 100 runs now persist patches + per-test results, so this audit inspected them directly. The cohort is **genuine and internally consistent**:

- Cohort = exactly 100 patches, 1,218 test rows across 99 runs (one timeout has a patch but no testcases — consistent: its gates failed, so no hidden suite ran).
- All three consistency invariants hold across the cohort: `functional_pass=1` with a hidden failure = **0**; `G=1 & all-hidden-passed` but not a pass = **0**; persisted `t_hidden` ≠ per-test fraction = **0**.
- Inspected patches trace to real semantics: a genuine fix removing the `bisect_left` over-advance branch; a real `asyncio.Semaphore` bounded-gather implementation; a wrong-fix that adds a prefix check but **no `..` normalization** (fails exactly the traversal tests); a toposort wrong-fix that inverts edge direction via `nx.DiGraph`. These are real model behaviors, not fabricated data.

This upgrades "the numbers are real" from a claim to a verified property.

---

## Evidence-backed results

### Leaderboard (DB-first; oracle/noop are render-only synthetic baselines)

| Rank | Agent | Source | n | Passes | p̂ | Wilson LCB |
|---|---|---|---:|---:|---:|---:|
| 1 | oracle (synthetic baseline) | render-only | 120 | 120 | 1.000 | 0.969 |
| 2 | qwen2.5-coder:7b | persisted DB | 120 | 68 | 0.567 | 0.477 |
| 3–4 | deepseek-coder:6.7b | persisted DB | 120 | 38 | 0.317 | 0.240 |
| 3–5 | qwen2.5-coder:3b | persisted DB | 120 | 32 | 0.267 | 0.196 |
| 4–5 | llama3.2:latest | persisted DB | 120 | 26 | 0.217 | 0.152 |
| 6 | gemma2:2b | persisted DB | 120 | 6 | 0.050 | 0.023 |
| 7 | noop (synthetic baseline) | render-only | 120 | 0 | 0.000 | 0.000 |

All LCBs recompute exactly. Unlike audit-1, **every model row is now backed by 120 real persisted runs** (no gap-fill).

### Domain profile — real DB (all cells now displayable, ≥25 runs)

| Agent | api-design | async | backend | performance | security |
|---|---|---|---|---|---|
| deepseek-coder:6.7b | 25% | 24% | 27% | 45% | 52% |
| gemma2:2b | 0% | 0% | 6% | 20% | 0% |
| qwen2.5-coder:3b | 30% | 0% | 33% | 22% | 40% |
| qwen2.5-coder:7b | 75% | 24% | 62% | 50% | 68% |
| llama3.2:latest | 12% | 4% | 24% | 50% | 24% |

backend (17/24 tasks) structurally dominates the macro-average — now disclosed in README/docs/report.

---

## New findings (audit-2)

All are minor; **none compromises the validity of the published results.**

**P2**
- **A2-P2-1 — Production task-version resolution path is untested.** `manifest.json` items carry no `version` key (0/24), so `_current_task_version()` falls back to reading `task.json` from disk in production — but both tests pass `version` inline, exercising only the dict branch. The path that actually runs is uncovered.

**P3 (latent / cosmetic)**
- **A2-P3-1** `build_report` silently *excludes* any real agent not in the hardcoded `MODELS` list (under-reporting, safe; moot today).
- **A2-P3-2** `save_run` silently persists detail-less rows when `report is None` (unreachable in production; a defensive assert would harden P1-1).
- **A2-P3-3 / A2-P3-4 / A2-P3-5** version/baseline disclosure nuances: synthetic baselines injected at v1.0.1 pool two versions for the 3 hardened tasks; the stale-version discrepancy is shown only in a hover tooltip; oracle/noop rank like measured agents with only a name-suffix label.
- **A2-P3-6** `store` load/summary INNER-JOIN to `diffs` would drop a diff-less run (moot today).
- **A2-P3-7** empty-diff runs are recorded `status='valid'` (G=0) rather than the doc-specified `AGENT_ERROR` (scoring correct either way).
- **A2-P3-8** the "runs with patch artifacts = 100/600" stat counts 5 empty-string (no-edit) patches as present.
- **A2-P3-9** two parallel canonical framework docs (modular + consolidated) without a source-of-truth marker — currently consistent, but a drift hazard.

---

## Report audit

The report is now **honest, mathematically faithful, and reproducible**: DB-first, every rate carries n + a Wilson interval, oracle/noop are labeled synthetic, ranks cluster on overlap, and it adds real observability (run window, artifact coverage, per-model mean S/Q, failure splits, version badges). Recomputing its numbers from SQLite matches the DB exactly. It still **lacks**: a raw-run/diff/transcript drilldown, run timestamps beyond the DB window, CSV/JSON export, and interactivity; and the stale-cell (v1.0.0-under-v1.0.1) disclosure deserves more than a tooltip. Net: a trustworthy static report, not yet an interactive observability product.

---

## Reproducibility checklist

| Item | Result |
|---|---|
| README quickstart works verbatim | PASS (`python3`) |
| Dependencies / Python version documented | PASS (v0.2.0, 3.13) |
| Model server + exact tag pinned | PASS (Ollama version; `llama3.2:latest@a80c4f17acd5`) |
| Run command / n / DB location / report command documented | PASS |
| DB + report committed | PASS (tracked) |
| Report reproducible from data | PASS (byte-identical ×3) |
| Seeds / temperature documented | PASS |
| Resumability | PASS (version-matched) |
| Infra failures recorded separately | PARTIAL (mechanism present + tested; no voided rows in this run) |
| Per-run transcript / model digest stored | FAIL (aggregates only; LLM sampling not bit-reproducible) |
| Legacy runs inspectable | FAIL (first 500 lack patch/test detail) |

---

## What to do next

**Mandatory:** none blocking for a research/portfolio benchmark.

**Should do**
1. Re-evaluate the 3 v1.0.1 tasks so their published cells match their strengthened hidden suites — or make the stale-version disclosure prominent (not tooltip-only).
2. Add a defensive `assert` in `save_run` when a real run is persisted without a `GradeReport`.
3. Cover the production task-version resolution (disk-read) path with a test.

**Optional**
4. Persist per-run model digest + transcript (generation-level reproducibility).
5. Render oracle/noop visually distinct from measured agents.
6. Designate one canonical framework doc; mark the other derived.
7. Floor `T_hidden` against the snapshot baseline (wire `baseline_adjusted_t_hidden`) under a formula-version bump + recompute.

**Do not do yet**
8. Do not admit untrusted agents until `DockerSandbox` (or equivalent isolation) exists.
9. Do not build the Postgres/Next.js dashboard before confirming the static report + DB don't already meet the need.

---

## Auditor's closing note

Audit-1 found a strong engine wrapped around a dishonest results page. Audit-2 finds that the results page now tells the truth: the fabrication is gone, the data is real and byte-reproducible, the forensic trail (for the latest cohort) is independently consistent, and the documentation matches reality. The work was done properly — closures hold under adversarial re-derivation, not just by assertion. What remains is genuinely scope, not integrity: there is no product surface and no untrusted-agent isolation, the first 500 runs can't be inspected at fine grain, and three strengthened tasks await re-measurement. A benchmark you can trust the numbers of — now it needs a surface to use them through.
