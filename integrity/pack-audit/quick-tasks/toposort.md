# AgentForge Benchmark Integrity Report

**Task**: `toposort`  
**Version**: `1.0.1`  
**Mode**: `quick`  
**Engine version**: `0.1.0` (schema `1.0.0`)  
**Timestamp**: 2026-09-17T20:40:10.577128+00:00  
**Duration**: 17551 ms

## Status: INVALID

**Reason**: known-bad control 'first_dependency_only' was ACCEPTED (should have been rejected by the hidden suite)

## Checks

| Check | Category | Status | Severity | Description |
|---|---|---|---|---|
| `reference.solution_validation` | reference | PASS | info | Reference solution scores (1.0, True) identically across 3 repeated grades. |
| `noop.unmodified_baseline` | negative_control | PASS | info | The unmodified snapshot passes regression, fails the hidden suite (T_hidden=0.000), and scores 0.0 / functional_pass=False, as required. |
| `hidden_import_closure.gate7` | isolation | PASS | info | Task uses an editable_paths allow-list, which makes gate 7 (no editable, unprotected oracle-helper import) hold structurally: any local module the hidden/regression suites import that isn't the editable code-under-test is already unreachable by any diff without failing the scope gate. |
| `protected_paths.tampering_probes` | isolation | PASS | info | All 11 protected-path/allow-list probes correctly flagged a scope violation. One known, documented gap (a `_pytest/` shadow package) was also probed and confirmed — see findings. |
| `controls.declared_controls` | controls | FAIL | critical | 1/4 declared control(s) did NOT match their declared expectation via a genuine hidden-test verdict: first_dependency_only. A known-bad solution that is accepted, or a valid alternative that is rejected by the hidden suite, is direct evidence the oracle is either too permissive or too narrow. |
| `determinism.repeated_grading` | determinism | PASS | info | All 1 sampled artifact(s) graded identically across their repeats. |

## Controls

| Name | Kind | Expected | Verdict | Status | Notes |
|---|---|---|---|---|---|
| `first_dependency_only` | known_bad | reject | accepted | FAIL | verdict=accepted |
| `insertion_order_tiebreak` | known_bad | reject | rejected_by_hidden_test | PASS | verdict=rejected_by_hidden_test; failing_hidden_tests=['test_independent_nodes_sorted_lexicographically', 'test_tiebreak_prefers_lexicographic_among_eligible'] |
| `missing_cycle_check` | known_bad | reject | rejected_by_hidden_test | PASS | verdict=rejected_by_hidden_test; failing_hidden_tests=['test_cycle_raises', 'test_self_loop_raises', 'test_longer_cycle_raises', 'test_implicit_dependency_in_cycle_is_still_a_cycle'] |
| `dfs_postorder` | alternative | accept | accepted | PASS | verdict=accepted |

## Findings

- **[HIGH] A `_pytest/` package directory is not flagged as a protected-path violation, though grading runs pytest with the cleanroom at sys.path[0].** (`protected_paths.pytest_shadow_package`)
  Injecting 'graphkit/_pytest/__init__.py' was NOT flagged as touching a protected path. ALWAYS_PROTECTED_BASENAMES matches basenames, not directory names, so a submission-created `_pytest/` package shadowing the real `_pytest` internals package is currently only stopped by this task's editable_paths allow-list (when configured), not by a structural guarantee. See docs/agents/ORACLE.md for why this is reported rather than silently fixed here.

## Limitations

- Grading executes submitted/mutated code via LocalSandbox, which provides per-run workspace isolation and timeouts but NOT untrusted-agent security isolation (runner/afa_runner/sandbox.py's own module docstring). Every check in this report assumes the code being graded is trying to game the SCORE, not attack the HOST — see isolation.hidden_test_readability for a concrete, always-present consequence of that assumption.
- Mutation testing, a determinism sample over declared controls, and the isolation probe were not run (QUICK mode) — run --full for stronger evidence.
- Mutation equivalence is undecidable in general; a surviving mutant is reported as-is unless explicitly declared equivalent in tasks/<id>/integrity/integrity.json. A mutation kill rate is never treated as a correctness probability (mission §16).

## Provenance

- `task_id`: toposort
- `task_version`: 1.0.1
- `task_json_hash`: sha256:6efcd98642b65eb514a7316cfeba74f772ff936cce5e16b898f49c0357068553
- `snapshot_hash`: sha256:221cfc6b802532f4f136d9a032e8c0f5ea3e3d98ce19fe971e56da8ee4de1cc6
- `reference_hash`: sha256:ac230b4610894bf7af079ae3e3f292c4d76ef9461a6d780b90efc809e881af14
- `grading_hash`: sha256:1f3a4707d4625b60caccb6af61de27d6ea1671a3a9edd103e9479d1c8d1d4e1d
- `controls_hash`: sha256:c36ab1ae8a46590f0c01c2e6fea36f5714a661d5d4cd1232b805f0cd4e5d3c79
- `engine_version`: 0.1.0
- `afa_kernel_version`: 0.1.0
- `afa_runner_version`: 0.2.0
- `python_version`: 3.13.2
- `platform`: macOS-26.3-arm64-arm-64bit-Mach-O
