# Release-hardening audit — fresh FULL pack audit vs. the integrated baseline

Purpose: the release-hardening pass changed `runner/afa_runner/store.py` (formula pin, read snapshot, tolerant text decoding, row-naming
errors for unreadable / non-finite / out-of-range columns) and everything under `afa_api/`, `examples/` and `web/`. It must not change what the integrity engine says about
the benchmark. This is the check.

| | Baseline | This run |
|---|---|---|
| Source | integrated ORACLE+ATLAS branch, `4b7d712` | release branch `81f9265` (clean detached worktree; final code) |
| Command | `PYTHONPATH=integrity:runner:kernel python3 -m afa_integrity audit --all --full --workers 4` | identical |
| Summary | [`integrated-full-summary.md`](integrated-full-summary.md) | [`release-full-summary.md`](release-full-summary.md) |
| Tasks audited | 24 | 24 |
| Duration | 772,797 ms | 724,457 ms |
| Process exit | 1 | 1 (the engine exits non-zero whenever any task is not HEALTHY; both runs have 9) |
| `reports/runs.sqlite` sha256 before / after | `42b6dad85ee662d6d5d7f75ffbda5a3b95d50837837f81c875730a8987838ced` (unchanged) | `42b6dad85ee662d6d5d7f75ffbda5a3b95d50837837f81c875730a8987838ced` / `42b6dad85ee662d6d5d7f75ffbda5a3b95d50837837f81c875730a8987838ced` (unchanged; also unchanged in the main checkout) |
| `*.pyc` created under `tasks/` | — | 0 |

## Result

| HEALTHY | NEEDS_REVIEW | PROVISIONAL | INVALID |
|---:|---:|---:|---:|
| 15 | 2 | 7 | 0 |

Same counts as the baseline. The numbers were not forced: they were compared **per task, per check, per control** with
`compare_audits.py` (status, every check id/status/severity, every control name/kind/verdict/expectation, mutation
accounting — generated, unsupported, declared-equivalent, intercepted, relevant, killed by hidden test / by timeout,
survivors, kill rate — findings, and the five provenance hashes `task_json`, `snapshot`, `reference`, `grading`,
`controls`):

```
tasks compared: 24  (only in one side: none)
status counts A: {'provisional': 7, 'healthy': 15, 'needs_review': 2}
status counts B: {'provisional': 7, 'healthy': 15, 'needs_review': 2}
RESULT: IDENTICAL on status, every check result, every control verdict, mutation accounting, findings and provenance
        hashes for all 24 tasks
```

Check totals for this run (24 tasks): 157 pass, 2 warning, 9 skipped, 24 unverifiable.
Controls (73): 45 known-bad solutions rejected by the hidden tests, 13 semantic mutants rejected, 15 alternative
solutions accepted — every one matched its declared expectation.

## What the non-HEALTHY statuses are (unchanged, not introduced here)

* **24 × `isolation.hidden_test_readability` = UNVERIFIABLE.** The engine cannot prove the agent sandbox hides the hidden
  tests from the agent. This is a standing limitation of the trusted-local execution model, not a per-task defect.
* **7 PROVISIONAL** (`async-batched`, `async-first-success`, `async-gather-bounded`, `grid-paths`, `merge-intervals`,
  `top-k-frequent`, `two-sum-indices`): `controls.declared_controls` skipped — no known-bad / mutant / alternative
  solutions are declared for them, so their discrimination evidence is thinner.
* **2 NEEDS_REVIEW**: `fix-list-dedup` (`mutation.generic_ast_mutants` — no relevant mutants could be generated) and
  `refactor-order-validation` (`hidden_import_closure.gate7` — hidden/regression suites import two reachable local
  files). Detailed evidence for these two is committed in [`release-full-tasks/`](release-full-tasks/) per
  `docs/AUDIT_EVIDENCE_POLICY.md`; the other 22 tasks' per-task files are reproducible on demand and are not committed.

The pack-level JSON is not committed a second time: a recursive diff of it against `integrated-full-summary.json` shows
that the only differing fields are `created_at` and `duration_ms` (pack, per-task and per-check), and it would add
~940 KB of duplicate history.
