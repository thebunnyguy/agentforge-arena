# AgentForge Benchmark Integrity Report

**Task**: `expression-evaluator`  
**Version**: `1.0.1`  
**Mode**: `quick`  
**Engine version**: `0.1.0` (schema `1.0.0`)  
**Timestamp**: 2026-09-17T21:14:58.228047+00:00  
**Duration**: 17661 ms

## Status: NEEDS_REVIEW

**Reason**: semantic mutant 'eval_based_implementation' survived (should have been rejected by the hidden suite)

## Checks

| Check | Category | Status | Severity | Description |
|---|---|---|---|---|
| `reference.solution_validation` | reference | PASS | info | Reference solution scores (1.0, True) identically across 3 repeated grades. |
| `noop.unmodified_baseline` | negative_control | PASS | info | The unmodified snapshot passes regression, fails the hidden suite (T_hidden=0.000), and scores 0.0 / functional_pass=False, as required. |
| `hidden_import_closure.gate7` | isolation | PASS | info | At most one distinct local file (['calckit/__init__.py']) is reachable by a diff without failing the scope gate and imported by the hidden/regression suites — unambiguously the code under test, not a separate oracle-helper module. |
| `protected_paths.tampering_probes` | isolation | PASS | info | All 12 protected-path/allow-list probes correctly flagged a scope violation. One known, documented gap (a `_pytest/` shadow package) was also probed and confirmed — see findings. |
| `controls.declared_controls` | controls | FAIL | critical | 1/5 declared control(s) did NOT match their declared expectation via a genuine hidden-test verdict: eval_based_implementation. A known-bad solution that is accepted, or a valid alternative that is rejected by the hidden suite, is direct evidence the oracle is either too permissive or too narrow. |
| `determinism.repeated_grading` | determinism | PASS | info | All 1 sampled artifact(s) graded identically across their repeats. |

## Controls

| Name | Kind | Expected | Verdict | Status | Notes |
|---|---|---|---|---|---|
| `integer_division_truncation` | known_bad | reject | rejected_by_hidden_test | PASS | verdict=rejected_by_hidden_test; failing_hidden_tests=['test_division_produces_float'] |
| `right_associative_subtraction` | known_bad | reject | rejected_by_hidden_test | PASS | verdict=rejected_by_hidden_test; failing_hidden_tests=['test_left_associative_subtraction', 'test_left_associative_division', 'test_chained_subtraction'] |
| `unary_minus_non_leading_crash` | known_bad | reject | rejected_by_hidden_test | PASS | verdict=rejected_by_hidden_test; failing_hidden_tests=['test_unary_minus_in_parens', 'test_unary_minus_after_operator', 'test_unary_minus_after_binary_minus'] |
| `eval_based_implementation` | semantic_mutant | reject | accepted | FAIL | verdict=accepted |
| `shunting_yard_rpn` | alternative | accept | accepted | PASS | verdict=accepted |

## Findings

- **[HIGH] A `_pytest/` package directory is not flagged as a protected-path violation, though grading runs pytest with the cleanroom at sys.path[0].** (`protected_paths.pytest_shadow_package`)
  Injecting 'calckit/_pytest/__init__.py' was NOT flagged as touching a protected path. ALWAYS_PROTECTED_BASENAMES matches basenames, not directory names, so a submission-created `_pytest/` package shadowing the real `_pytest` internals package is currently only stopped by this task's editable_paths allow-list (when configured), not by a structural guarantee. See docs/agents/ORACLE.md for why this is reported rather than silently fixed here.

## Limitations

- Grading executes submitted/mutated code via LocalSandbox, which provides per-run workspace isolation and timeouts but NOT untrusted-agent security isolation (runner/afa_runner/sandbox.py's own module docstring). Every check in this report assumes the code being graded is trying to game the SCORE, not attack the HOST — see isolation.hidden_test_readability for a concrete, always-present consequence of that assumption.
- Mutation testing and a determinism sample over declared controls were not run — pass --full or --mutation for stronger evidence.
- The isolation probe was not run (FULL mode only) — pass --full to check whether the hidden test source is readable by code being graded.
- Mutation equivalence is undecidable in general; a surviving mutant is reported as-is unless explicitly declared equivalent in tasks/<id>/integrity/integrity.json. A mutation kill rate is never treated as a correctness probability (mission §16).

## Provenance

- `task_id`: expression-evaluator
- `task_version`: 1.0.1
- `task_json_hash`: sha256:b9c081555ab8c6c91dbc5712b3707fb6f38177f07487fb581f1c30cdb2bee23c
- `snapshot_hash`: sha256:8106925ef1914e61100bfc3aecd8a3f5db3a4e250298e6b2e3e61c2d7bf1c88b
- `reference_hash`: sha256:1dfcab47cdd1129d772888ef4642d9356dd31991cfb3edbbaff79f3694880132
- `grading_hash`: sha256:4e65cf64f7d373b6fee8baaeadc0e368ae8de44b8e16fe25499a0c055228beae
- `controls_hash`: sha256:6637cb766a38482bc27d06538ce2ea77356ce3cd3adfa249bf3668127dce2752
- `engine_version`: 0.1.0
- `afa_kernel_version`: 0.1.0
- `afa_runner_version`: 0.2.0
- `python_version`: 3.13.2
- `platform`: macOS-26.3-arm64-arm-64bit-Mach-O
