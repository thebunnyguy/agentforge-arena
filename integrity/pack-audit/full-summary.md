# AgentForge Benchmark Integrity — Pack Audit

**Mode**: `full`  
**Engine version**: `0.1.0` (schema `1.0.0`)  
**Timestamp**: 2026-09-17T21:15:24.036555+00:00  
**Duration**: 400810 ms  
**Tasks audited**: 24

## Status counts

| Status | Count |
|---|---|
| HEALTHY | 2 |
| INVALID | 3 |
| NEEDS_REVIEW | 14 |
| PROVISIONAL | 5 |

## Per-task results

| Task | Version | Status | Reason |
|---|---|---|---|
| `async-batched` | 1.0.2 | NEEDS_REVIEW | mutation.generic_ast_mutants: 1/11 relevant mutant(s) survived (kill_rate=0.91 over 11 relevant of 11 generated). A surviving mutant is n... |
| `async-first-success` | 1.0.1 | NEEDS_REVIEW | mutation.generic_ast_mutants: 3/21 relevant mutant(s) survived (kill_rate=0.86 over 21 relevant of 21 generated). A surviving mutant is n... |
| `async-gather-bounded` | 1.0.1 | NEEDS_REVIEW | mutation.generic_ast_mutants: 5/17 relevant mutant(s) survived (kill_rate=0.71 over 17 relevant of 17 generated). A surviving mutant is n... |
| `async-retry` | 1.0.1 | NEEDS_REVIEW | mutation.generic_ast_mutants: 1/9 relevant mutant(s) survived (kill_rate=0.89 over 9 relevant of 9 generated). A surviving mutant is not ... |
| `async-timeout` | 1.0.0 | PROVISIONAL | controls.declared_controls: No known-bad solutions, semantic mutants, or alternative solutions declared for this task (tasks/<id>/integri... |
| `escape-html` | 1.0.1 | HEALTHY | All checks passed with no outstanding findings. |
| `expression-evaluator` | 1.0.1 | NEEDS_REVIEW | mutation.generic_ast_mutants: 5/40 relevant mutant(s) survived (kill_rate=0.88 over 40 relevant of 40 generated). A surviving mutant is n... |
| `fix-binary-search` | 1.0.0 | PROVISIONAL | controls.declared_controls: No known-bad solutions, semantic mutants, or alternative solutions declared for this task (tasks/<id>/integri... |
| `fix-list-dedup` | 1.0.1 | NEEDS_REVIEW | noop.unmodified_baseline: The unmodified snapshot's weighted hidden pass fraction (T_hidden=0.500) is >= the documented 0.5 ceiling (fram... |
| `fix-path-traversal` | 1.0.1 | NEEDS_REVIEW | mutation.generic_ast_mutants: 2/6 relevant mutant(s) survived (kill_rate=0.67 over 6 relevant of 15 generated). A surviving mutant is not... |
| `fix-roman-numerals` | 1.0.0 | NEEDS_REVIEW | mutation.generic_ast_mutants: 1/17 relevant mutant(s) survived (kill_rate=0.94 over 17 relevant of 27 generated). A surviving mutant is n... |
| `grid-paths` | 1.0.0 | NEEDS_REVIEW | mutation.generic_ast_mutants: 6/22 relevant mutant(s) survived (kill_rate=0.73 over 22 relevant of 22 generated). A surviving mutant is n... |
| `implement-lru-cache` | 1.0.1 | HEALTHY | All checks passed with no outstanding findings. |
| `mask-secrets` | 1.0.1 | NEEDS_REVIEW | semantic mutant 'boundary_anchored_secrets' survived (should have been rejected by the hidden suite) |
| `merge-intervals` | 1.0.1 | NEEDS_REVIEW | mutation.generic_ast_mutants: 3/12 relevant mutant(s) survived (kill_rate=0.75 over 12 relevant of 17 generated). A surviving mutant is n... |
| `paginator` | 1.0.1 | PROVISIONAL | controls.declared_controls: No known-bad solutions, semantic mutants, or alternative solutions declared for this task (tasks/<id>/integri... |
| `query-builder` | 1.0.1 | PROVISIONAL | controls.declared_controls: No known-bad solutions, semantic mutants, or alternative solutions declared for this task (tasks/<id>/integri... |
| `refactor-order-validation` | 1.0.2 | NEEDS_REVIEW | hidden_import_closure.gate7: The hidden/regression suites import 2 distinct reachable local files: ['orderkit/__init__.py', 'orderkit/pro... |
| `result-type` | 1.0.1 | PROVISIONAL | controls.declared_controls: No known-bad solutions, semantic mutants, or alternative solutions declared for this task (tasks/<id>/integri... |
| `sanitize-filename` | 1.0.1 | INVALID | known-bad control 'strict_allowlist' was ACCEPTED (should have been rejected by the hidden suite) |
| `top-k-frequent` | 1.0.2 | NEEDS_REVIEW | mutation.generic_ast_mutants: 2/13 relevant mutant(s) survived (kill_rate=0.85 over 13 relevant of 13 generated). A surviving mutant is n... |
| `toposort` | 1.0.1 | INVALID | known-bad control 'first_dependency_only' was ACCEPTED (should have been rejected by the hidden suite) |
| `two-sum-indices` | 1.0.1 | NEEDS_REVIEW | mutation.generic_ast_mutants: 1/11 relevant mutant(s) survived (kill_rate=0.91 over 11 relevant of 11 generated). A surviving mutant is n... |
| `validate-redirect-url` | 1.0.1 | INVALID | known-bad control 'host_substring_match' was ACCEPTED (should have been rejected by the hidden suite) |

## Common findings across the pack

- **[HIGH] A `_pytest/` package directory is not flagged as a protected-path violation, though grading runs pytest with the cleanroom at sys.path[0].** (`protected_paths.pytest_shadow_package`)
  Injecting 'atimeout/_pytest/__init__.py' was NOT flagged as touching a protected path. ALWAYS_PROTECTED_BASENAMES matches basenames, not directory names, so a submission-created `_pytest/` package shadowing the real `_pytest` internals package is currently only stopped by this task's editable_paths allow-list (when configured), not by a structural guarantee. See docs/agents/ORACLE.md for why this is reported rather than silently fixed here.
