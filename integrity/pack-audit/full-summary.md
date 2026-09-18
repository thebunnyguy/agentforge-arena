# AgentForge Benchmark Integrity — Pack Audit

**Mode**: `full`  
**Engine version**: `0.1.0` (schema `1.0.0`)  
**Timestamp**: 2026-09-18T07:12:08.701782+00:00  
**Duration**: 666463 ms  
**Tasks audited**: 24

## Status counts

| Status | Count |
|---|---|
| HEALTHY | 15 |
| NEEDS_REVIEW | 2 |
| PROVISIONAL | 7 |

## Per-task results

| Task | Version | Status | Reason |
|---|---|---|---|
| `async-batched` | 1.0.2 | PROVISIONAL | controls.declared_controls: No known-bad solutions, semantic mutants, or alternative solutions declared for this task (tasks/<id>/integri... |
| `async-first-success` | 1.0.2 | PROVISIONAL | controls.declared_controls: No known-bad solutions, semantic mutants, or alternative solutions declared for this task (tasks/<id>/integri... |
| `async-gather-bounded` | 1.0.2 | PROVISIONAL | controls.declared_controls: No known-bad solutions, semantic mutants, or alternative solutions declared for this task (tasks/<id>/integri... |
| `async-retry` | 1.0.2 | HEALTHY | All checks passed with no outstanding findings. |
| `async-timeout` | 1.0.1 | HEALTHY | All checks passed with no outstanding findings. |
| `escape-html` | 1.0.1 | HEALTHY | All checks passed with no outstanding findings. |
| `expression-evaluator` | 1.0.2 | HEALTHY | All checks passed with no outstanding findings. |
| `fix-binary-search` | 1.0.0 | HEALTHY | All checks passed with no outstanding findings. |
| `fix-list-dedup` | 1.0.2 | NEEDS_REVIEW | mutation.generic_ast_mutants: No relevant mutants were generated (all candidates were unsupported, declared-equivalent, intercepted by th... |
| `fix-path-traversal` | 1.0.2 | HEALTHY | All checks passed with no outstanding findings. |
| `fix-roman-numerals` | 1.0.0 | HEALTHY | All checks passed with no outstanding findings. |
| `grid-paths` | 1.0.1 | PROVISIONAL | controls.declared_controls: No known-bad solutions, semantic mutants, or alternative solutions declared for this task (tasks/<id>/integri... |
| `implement-lru-cache` | 1.0.1 | HEALTHY | All checks passed with no outstanding findings. |
| `mask-secrets` | 1.0.2 | HEALTHY | All checks passed with no outstanding findings. |
| `merge-intervals` | 1.0.2 | PROVISIONAL | controls.declared_controls: No known-bad solutions, semantic mutants, or alternative solutions declared for this task (tasks/<id>/integri... |
| `paginator` | 1.0.2 | HEALTHY | All checks passed with no outstanding findings. |
| `query-builder` | 1.0.2 | HEALTHY | All checks passed with no outstanding findings. |
| `refactor-order-validation` | 1.0.3 | NEEDS_REVIEW | hidden_import_closure.gate7: The hidden/regression suites import 2 distinct reachable local files: ['orderkit/__init__.py', 'orderkit/pro... |
| `result-type` | 1.0.2 | HEALTHY | All checks passed with no outstanding findings. |
| `sanitize-filename` | 1.0.2 | HEALTHY | All checks passed with no outstanding findings. |
| `top-k-frequent` | 1.0.3 | PROVISIONAL | controls.declared_controls: No known-bad solutions, semantic mutants, or alternative solutions declared for this task (tasks/<id>/integri... |
| `toposort` | 1.0.2 | HEALTHY | All checks passed with no outstanding findings. |
| `two-sum-indices` | 1.0.1 | PROVISIONAL | controls.declared_controls: No known-bad solutions, semantic mutants, or alternative solutions declared for this task (tasks/<id>/integri... |
| `validate-redirect-url` | 1.0.2 | HEALTHY | All checks passed with no outstanding findings. |

## Common findings across the pack

- **[INFO] A `_pytest/` package nested inside this task's editable subtree is not flagged as a protected-path violation, but empirical testing confirms this is NOT currently exploitable.** (`protected_paths.pytest_shadow_package_nested`)
  Injecting 'listkit/_pytest/__init__.py' (nested inside the editable package, not at the snapshot root) was NOT flagged as touching a protected path — but `python -m pytest` never adds the editable package directory itself to sys.path, so this nested `_pytest/` is only importable as `<package>._pytest`, never as the bare top-level `_pytest` the real pytest package needs; a controlled test confirms `import _pytest` still resolves to the real site-packages module. Recorded as a structural gap (no basename/suffix rule catches a directory named `_pytest`) that would only matter if this task ever lost its editable_paths allow-list, not as a live weakness today. See docs/agents/ORACLE.md.
