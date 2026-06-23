# AgentForge Arena Audit Scorecard

**Overall: 66 / 100**  
**Maturity: research tool**  
**Commit:** `798a5b3d7aba74c3a95e51119983b2d75091161c`  
**Fresh verification:** 366 passed, 0 failed, 0 skipped, 7 warnings in 147.69 s; report rebuilt byte-identically.

| Dimension | /10 | Decisive evidence |
|---|---:|---|
| Scoring/math correctness | **7.5** | Wilson/formula/domain arithmetic is correct. Executable ranking is micro-pooled while framework requires macro-domain; timeout, deterministic-run, and Q policies are incomplete. |
| Test suite quality | **8.5** | Excellent numeric/path tests and all-task validation. Seven DB warnings; no hostile-agent/reference-leak or semantic task-contract tests. |
| Task pack quality | **7.0** | 24/24 structurally valid. Expression hidden tests award a wrong parser; redirect reference violates its security description; three improved tasks are not reevaluated. |
| Clean-room/security | **5.0** | Strong allow-list/auto-exec/symlink defenses. Full Task paths and host privileges make hidden/reference cheating trivial for arbitrary agents. |
| Real-agent evaluation validity | **7.0** | 600 real DB rows and honest baselines. 500 runs lack patches/tests, 75 rows are stale-version, parser failures are opaque, and at least one pass is false by contract. |
| Domain coverage | **6.0** | All five clear 5 tasks/25 runs, but only barely; backend touches 17/24 and task overlap/idioms distort profiles. |
| Report quality | **7.0** | Strong static overview and provenance. “Wrong-fix” is over-broad; no drilldown, exports, parser/timeout detail, or reproducibility manifest. |
| Reproducibility | **6.5** | Tests/demo/report reproduce. Model runs lack stable per-row seeds, three digests, transcripts, pinned dependency image, and full artifacts. |
| Product usability | **4.5** | Useful examples/static HTML; no product CLI, API, dashboard, run viewer, or contributor workflow. |
| Documentation accuracy | **7.0** | README/current DEVLOG match DB/git and disclose version fork. Full framework promises macro ranking, pinned Q tools, timeout behavior, and secrecy not implemented. |
| **Total** | **66 / 100** | |

## Release-blocking findings

1. Qwen expression run 4 is stored as a pass but fails written arithmetic/unary-minus behavior.
2. Redirect reference accepts hosted `javascript:`/`data:` URLs contrary to the task description.
3. Arbitrary agents can read absolute reference/hidden paths and execute with host privileges.
4. Published matrix includes 75 rows from superseded task versions.
5. Per-run model/config/seed/transcript provenance is insufficient for exact reproduction.

## Bottom line

The aggregate artifact is reproducible; the benchmark claim is not yet fully valid. Fix semantic task oracles and the isolation/provenance boundary before adding models or UI.
