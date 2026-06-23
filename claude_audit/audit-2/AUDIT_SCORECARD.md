# AgentForge Arena — Audit-2 Scorecard

**Overall grade: 75 / 100** (audit-1: 53 / 100)
**Commit audited:** `798a5b3` (`master`, synced with `origin/master`)
**Maturity:** trustworthy research-grade benchmark + local CLI harness; **not** product-ready; **not** safe for untrusted agents.
**Fresh checks:** full suite **366 passed (~137s)**; §8 `validate_task` **24/24**; report **byte-reproducible** (SHA `87ca6c77…`); forensic cohort **100% score/test-consistent**.

> Adversarial re-audit at HEAD. Every "closed" claim was independently re-derived by a skeptic agent and reconciled by the lead auditor; one agent false-positive (a claim that `EVALUATION_FRAMEWORK.md` still had the old parsimony curve) was refuted by grep and discarded.

## Finding disposition since audit-1
- **Genuinely closed (15):** P0-1, P0-2, P0-3, P1-1 (forward), P1-2, P1-4, P2-1, P2-2, P2-3, P2-4, P2-6, P3-2, P3-3, P3-4, P3-1 (reduced).
- **Partially closed (1):** P2-5 — the 3 task hidden suites are genuinely stronger (async-batched 5→9-11, top-k 12→16, refactor-order 1→21), but their committed leaderboard cells still reflect v1.0.0 evidence (disclosed via a version badge; not re-evaluated).
- **Still open (3):** P1-3 (no DockerSandbox/untrusted isolation), P1-5 (no product surface), P1-1 legacy half (first 500 runs lack patch/test detail, irrecoverable).
- **New (audit-2):** 1 P2 (untested production version-resolution path) + 9 P3 latent/cosmetic nits.

## Scores

| Dimension | Now | Prior | Δ | Evidence-based justification |
|---|---:|---:|---:|---|
| Scoring / math correctness | **8.5** | 8.5 | 0 | Kernel math unchanged and correct (all anchors recompute exactly); parsimony doc drift now reconciled in **both** framework docs. Only the opt-in `baseline_adjusted_t_hidden` helper was added (not wired). |
| Test suite quality | **9.0** | 8.5 | +0.5 | 366 tests; the report generator now has a mutation-proven integrity test, plus numeric report assertions, persistence, cross-domain integration, and version-match coverage. |
| Task pack quality | **7.5** | 7.0 | +0.5 | 24/24 §8-valid; 3 weak cells genuinely strengthened. Held back by the stale v1.0.0 published cells for those 3 tasks and a single still-thin visible-test layer. |
| Clean-room / security | **7.0** | 6.5 | +0.5 | Case-variant `Conftest.py` and symlink-capture gaps both closed and tested. Still no `DockerSandbox`; hidden tests readable during `act` (trusted-local only). |
| Real-agent evaluation validity | **7.5** | 4.0 | +3.5 | 600 real persisted runs; forensic cohort 100% score/test-consistent; inspected patches trace to real task semantics. Limited by the legacy 500-row forensic gap and non-bit-reproducible LLM sampling. |
| Domain coverage | **8.0** | 5.0 | +3.0 | All 5 models now have ≥25 real runs in every domain (zero gap-fill). Structural backend skew (17/24) remains but is now disclosed. |
| Report quality | **7.5** | 4.5 | +3.0 | DB-first, byte-reproducible, oracle/noop labeled synthetic, real observability (run window, artifact coverage, mean S/Q, version badges). Still no run drilldown/export; stale-cell disclosure is tooltip-only. |
| Reproducibility | **7.5** | 2.5 | +5.0 | DB + HTML tracked and byte-reproducible; pinned model digest, seed, temperature, Ollama version; version-matched resumability. Per-run transcript/digest still unstored; legacy gap. |
| Product usability | **4.5** | 4.0 | +0.5 | CLI/library is genuinely usable and the committed report is honest. Still no dashboard/API/run-viewer/CONTRIBUTING. |
| Documentation accuracy | **7.5** | 3.0 | +4.5 | README counts/tags/labels match the DB; DEVLOG now records the audit (Phases 30–34); both framework docs reconciled. Minor: two parallel framework docs without a source-of-truth marker. |
| **Total** | **75.0** | **53.0** | **+22** | The gain is concentrated in evaluation validity, reproducibility, reporting, domains, and documentation — not new math or product scope. |

## Why the score moved 53 → 75
- **The data is real and reproducible.** Audit-1's headline P0 (50 hardcoded runs/model + synthetic oracle/noop presented as real) is gone: 600 genuine runs, no `KNOWN_OLD`, tracked DB/HTML, byte-identical regeneration, and a forensic cohort whose persisted patches and per-test results are 100% consistent with the stored scores.
- **The edge-case anti-gaming gaps are closed.** Case-variant config injection and symlink capture are both fixed and tested.
- **The docs tell the truth now.** Counts, tags, the parsimony curve, and the audit trail all match reality.
- **The ceiling is honest and structural.** No untrusted isolation, no product surface, a legacy forensic gap, and a set of P3 latent footguns — none of which compromise the validity of the published results.

## Current strongest property
The published leaderboard is a faithful, byte-reproducible projection of a committed 600-run database whose per-run grading artifacts (for the latest cohort) are independently consistent — backed by a correct deterministic kernel and 366 passing tests.

## Current largest risks
1. `LocalSandbox` is not security isolation and no `DockerSandbox` exists — anti-gaming holds only for trusted local agents.
2. No dashboard/API/run-detail surface or contributor workflow.
3. The first 500 legacy runs cannot be inspected at patch/test granularity; only the final 100 have grading artifacts.
4. The 3 strengthened (v1.0.1) tasks publish v1.0.0 pass rates (disclosed, but not re-measured).
