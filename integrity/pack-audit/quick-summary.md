# AgentForge Benchmark Integrity — Pack Audit

**Mode**: `quick`  
**Engine version**: `0.1.0` (schema `1.0.0`)  
**Timestamp**: 2026-09-17T20:39:36.767556+00:00  
**Duration**: 55521 ms  
**Tasks audited**: 24

## Status counts

| Status | Count |
|---|---|
| INVALID | 3 |
| NEEDS_REVIEW | 4 |
| PROVISIONAL | 17 |

## Per-task results

| Task | Version | Status | Reason |
|---|---|---|---|
| `async-batched` | 1.0.2 | PROVISIONAL | controls.declared_controls: No known-bad solutions, semantic mutants, or alternative solutions declared for this task (tasks/<id>/integri... |
| `async-first-success` | 1.0.1 | PROVISIONAL | controls.declared_controls: No known-bad solutions, semantic mutants, or alternative solutions declared for this task (tasks/<id>/integri... |
| `async-gather-bounded` | 1.0.1 | PROVISIONAL | controls.declared_controls: No known-bad solutions, semantic mutants, or alternative solutions declared for this task (tasks/<id>/integri... |
| `async-retry` | 1.0.1 | NEEDS_REVIEW | semantic mutant 'swallows_base_exceptions' survived (should have been rejected by the hidden suite) |
| `async-timeout` | 1.0.0 | PROVISIONAL | controls.declared_controls: No known-bad solutions, semantic mutants, or alternative solutions declared for this task (tasks/<id>/integri... |
| `escape-html` | 1.0.1 | PROVISIONAL | audit mode is QUICK: mutation testing, semantic mutants beyond declared controls, and a wider determinism sample were not run — run --ful... |
| `expression-evaluator` | 1.0.1 | NEEDS_REVIEW | semantic mutant 'eval_based_implementation' survived (should have been rejected by the hidden suite) |
| `fix-binary-search` | 1.0.0 | PROVISIONAL | controls.declared_controls: No known-bad solutions, semantic mutants, or alternative solutions declared for this task (tasks/<id>/integri... |
| `fix-list-dedup` | 1.0.1 | NEEDS_REVIEW | noop.unmodified_baseline: The unmodified snapshot's weighted hidden pass fraction (T_hidden=0.500) is >= the documented 0.5 ceiling (fram... |
| `fix-path-traversal` | 1.0.1 | PROVISIONAL | audit mode is QUICK: mutation testing, semantic mutants beyond declared controls, and a wider determinism sample were not run — run --ful... |
| `fix-roman-numerals` | 1.0.0 | PROVISIONAL | audit mode is QUICK: mutation testing, semantic mutants beyond declared controls, and a wider determinism sample were not run — run --ful... |
| `grid-paths` | 1.0.0 | PROVISIONAL | controls.declared_controls: No known-bad solutions, semantic mutants, or alternative solutions declared for this task (tasks/<id>/integri... |
| `implement-lru-cache` | 1.0.1 | PROVISIONAL | audit mode is QUICK: mutation testing, semantic mutants beyond declared controls, and a wider determinism sample were not run — run --ful... |
| `mask-secrets` | 1.0.1 | NEEDS_REVIEW | semantic mutant 'boundary_anchored_secrets' survived (should have been rejected by the hidden suite) |
| `merge-intervals` | 1.0.1 | PROVISIONAL | controls.declared_controls: No known-bad solutions, semantic mutants, or alternative solutions declared for this task (tasks/<id>/integri... |
| `paginator` | 1.0.1 | PROVISIONAL | controls.declared_controls: No known-bad solutions, semantic mutants, or alternative solutions declared for this task (tasks/<id>/integri... |
| `query-builder` | 1.0.1 | PROVISIONAL | controls.declared_controls: No known-bad solutions, semantic mutants, or alternative solutions declared for this task (tasks/<id>/integri... |
| `refactor-order-validation` | 1.0.2 | PROVISIONAL | controls.declared_controls: No known-bad solutions, semantic mutants, or alternative solutions declared for this task (tasks/<id>/integri... |
| `result-type` | 1.0.1 | PROVISIONAL | controls.declared_controls: No known-bad solutions, semantic mutants, or alternative solutions declared for this task (tasks/<id>/integri... |
| `sanitize-filename` | 1.0.1 | INVALID | known-bad control 'strict_allowlist' was ACCEPTED (should have been rejected by the hidden suite) |
| `top-k-frequent` | 1.0.2 | PROVISIONAL | controls.declared_controls: No known-bad solutions, semantic mutants, or alternative solutions declared for this task (tasks/<id>/integri... |
| `toposort` | 1.0.1 | INVALID | known-bad control 'first_dependency_only' was ACCEPTED (should have been rejected by the hidden suite) |
| `two-sum-indices` | 1.0.1 | PROVISIONAL | controls.declared_controls: No known-bad solutions, semantic mutants, or alternative solutions declared for this task (tasks/<id>/integri... |
| `validate-redirect-url` | 1.0.1 | INVALID | known-bad control 'host_substring_match' was ACCEPTED (should have been rejected by the hidden suite) |

## Common findings across the pack

- **[HIGH] A `_pytest/` package directory is not flagged as a protected-path violation, though grading runs pytest with the cleanroom at sys.path[0].** (`protected_paths.pytest_shadow_package`)
  Injecting 'listkit/_pytest/__init__.py' was NOT flagged as touching a protected path. ALWAYS_PROTECTED_BASENAMES matches basenames, not directory names, so a submission-created `_pytest/` package shadowing the real `_pytest` internals package is currently only stopped by this task's editable_paths allow-list (when configured), not by a structural guarantee. See docs/agents/ORACLE.md for why this is reported rather than silently fixed here.
