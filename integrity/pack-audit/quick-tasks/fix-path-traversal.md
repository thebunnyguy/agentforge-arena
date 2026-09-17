# AgentForge Benchmark Integrity Report

**Task**: `fix-path-traversal`  
**Version**: `1.0.1`  
**Mode**: `quick`  
**Engine version**: `0.1.0` (schema `1.0.0`)  
**Timestamp**: 2026-09-17T20:39:58.026803+00:00  
**Duration**: 21209 ms

## Status: PROVISIONAL

**Reason**: audit mode is QUICK: mutation testing, semantic mutants beyond declared controls, and a wider determinism sample were not run — run --full for stronger evidence

## Checks

| Check | Category | Status | Severity | Description |
|---|---|---|---|---|
| `reference.solution_validation` | reference | PASS | info | Reference solution scores (1.0, True) identically across 3 repeated grades. |
| `noop.unmodified_baseline` | negative_control | PASS | info | The unmodified snapshot passes regression, fails the hidden suite (T_hidden=0.444), and scores 0.0 / functional_pass=False, as required. |
| `hidden_import_closure.gate7` | isolation | PASS | info | Task uses an editable_paths allow-list, which makes gate 7 (no editable, unprotected oracle-helper import) hold structurally: any local module the hidden/regression suites import that isn't the editable code-under-test is already unreachable by any diff without failing the scope gate. |
| `protected_paths.tampering_probes` | isolation | PASS | info | All 11 protected-path/allow-list probes correctly flagged a scope violation. One known, documented gap (a `_pytest/` shadow package) was also probed and confirmed — see findings. |
| `controls.declared_controls` | controls | PASS | info | All 5 declared control(s) matched their declared expectation via a genuine hidden-test verdict. |
| `determinism.repeated_grading` | determinism | PASS | info | All 1 sampled artifact(s) graded identically across their repeats. |

## Controls

| Name | Kind | Expected | Verdict | Status | Notes |
|---|---|---|---|---|---|
| `dotdot_literal_check` | known_bad | reject | rejected_by_hidden_test | PASS | verdict=rejected_by_hidden_test; failing_hidden_tests=['test_dotdot_within_base_allowed'] |
| `normalized_dotdot_token_check` | known_bad | reject | rejected_by_hidden_test | PASS | verdict=rejected_by_hidden_test; failing_hidden_tests=['test_dotdot_escape_raises', 'test_deep_dotdot_escape_raises', 'test_prefix_collision_sibling_raises'] |
| `wrong_exception_type` | known_bad | reject | rejected_by_hidden_test | PASS | verdict=rejected_by_hidden_test; failing_hidden_tests=['test_dotdot_escape_raises', 'test_absolute_component_raises', 'test_deep_dotdot_escape_raises', 'test_prefix_collision_sibling_raises'] |
| `prefix_startswith_no_separator` | semantic_mutant | reject | rejected_by_hidden_test | PASS | verdict=rejected_by_hidden_test; failing_hidden_tests=['test_prefix_collision_sibling_raises'] |
| `segment_stack_resolution` | alternative | accept | accepted | PASS | verdict=accepted |

## Findings

- **[HIGH] A `_pytest/` package directory is not flagged as a protected-path violation, though grading runs pytest with the cleanroom at sys.path[0].** (`protected_paths.pytest_shadow_package`)
  Injecting 'safepath/_pytest/__init__.py' was NOT flagged as touching a protected path. ALWAYS_PROTECTED_BASENAMES matches basenames, not directory names, so a submission-created `_pytest/` package shadowing the real `_pytest` internals package is currently only stopped by this task's editable_paths allow-list (when configured), not by a structural guarantee. See docs/agents/ORACLE.md for why this is reported rather than silently fixed here.

## Limitations

- Grading executes submitted/mutated code via LocalSandbox, which provides per-run workspace isolation and timeouts but NOT untrusted-agent security isolation (runner/afa_runner/sandbox.py's own module docstring). Every check in this report assumes the code being graded is trying to game the SCORE, not attack the HOST — see isolation.hidden_test_readability for a concrete, always-present consequence of that assumption.
- Mutation testing, a determinism sample over declared controls, and the isolation probe were not run (QUICK mode) — run --full for stronger evidence.
- Mutation equivalence is undecidable in general; a surviving mutant is reported as-is unless explicitly declared equivalent in tasks/<id>/integrity/integrity.json. A mutation kill rate is never treated as a correctness probability (mission §16).

## Provenance

- `task_id`: fix-path-traversal
- `task_version`: 1.0.1
- `task_json_hash`: sha256:9b4f4f3c9f948215ea88babd13f98d6bf36f0c8373357f8fca97628613dd2c1c
- `snapshot_hash`: sha256:c217d60520e70667f258d47390edff450476d7556cdaf7b7ffd24d0259363b77
- `reference_hash`: sha256:ec3c760150a3ac399e9925c48092567c0a87ce964bc9f76f48ab7d2352b3a098
- `grading_hash`: sha256:eba2604fffb5f510456cbfe0568d158e4879523b7c3a579d25408762bed39470
- `controls_hash`: sha256:e81619f9cc465ea042f0c5a84a45f6c047c0ea16c9964ea1a12d11798ec3854e
- `engine_version`: 0.1.0
- `afa_kernel_version`: 0.1.0
- `afa_runner_version`: 0.2.0
- `python_version`: 3.13.2
- `platform`: macOS-26.3-arm64-arm-64bit-Mach-O
