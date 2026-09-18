# AgentForge Benchmark Integrity Report

**Task**: `result-type`  
**Version**: `1.0.2`  
**Mode**: `full`  
**Engine version**: `0.1.0` (schema `1.0.0`)  
**Timestamp**: 2026-09-18T07:14:24.714027+00:00  
**Duration**: 152367 ms

## Status: HEALTHY

**Reason**: All checks passed with no outstanding findings.

## Checks

| Check | Category | Status | Severity | Description |
|---|---|---|---|---|
| `reference.solution_validation` | reference | PASS | info | Reference solution scores (1.0, True) identically across 5 repeated grades. |
| `noop.unmodified_baseline` | negative_control | PASS | info | The unmodified snapshot passes regression, fails the hidden suite (T_hidden=0.000), and scores 0.0 / functional_pass=False, as required. |
| `hidden_import_closure.gate7` | isolation | PASS | info | At most one distinct local file (['resultkit/__init__.py']) is reachable by a diff without failing the scope gate and imported by the hidden/regression suites — unambiguously the code under test, not a separate oracle-helper module. |
| `protected_paths.tampering_probes` | isolation | PASS | info | All 12 protected-path/allow-list probes correctly flagged a scope violation. A `_pytest/` package nested inside the editable subtree is also not flagged, but empirical testing confirms it is NOT exploitable under this task's current editable_paths allow-list — see findings. |
| `controls.declared_controls` | controls | PASS | info | All 6 declared control(s) matched their declared expectation via a genuine hidden-test verdict. |
| `mutation.generic_ast_mutants` | mutation | PASS | info | All 19 relevant mutant(s) were killed by the hidden suite (kill_rate=1.00 over 19 generated, 0 unsupported, 0 declared-equivalent, 0 intercepted by the regression/scope gate before reaching the hidden suite). |
| `determinism.repeated_grading` | determinism | PASS | info | All 7 sampled artifact(s) graded identically across their repeats. |
| `isolation.hidden_test_readability` | isolation_limitation | UNVERIFIABLE | high | CONFIRMED: code under grading can read the hidden test source during the hidden-suite run (the probe successfully detected and read the hidden test file from its own cwd). This is a known, deliberate limitation of the current trusted-local LocalSandbox threat model, not a defect in this task specifically — real untrusted-agent isolation (e.g. a network-disabled, filesystem-scoped DockerSandbox) is out of scope for this engine (mission §14/§25) and is tracked as a repo-wide 'deliberately still open' item. |

## Controls

| Name | Kind | Expected | Verdict | Status | Notes |
|---|---|---|---|---|---|
| `map_calls_fn_on_err` | known_bad | reject | rejected_by_hidden_test | PASS | verdict=rejected_by_hidden_test; failing_hidden_tests=['test_err_map_stays_err_without_calling_fn'] |
| `unwrap_err_returns_none` | known_bad | reject | rejected_by_hidden_test | PASS | verdict=rejected_by_hidden_test; failing_hidden_tests=['test_err_unwrap_raises_value_error'] |
| `unwrap_or_guard_reversed` | known_bad | reject | rejected_by_hidden_test | PASS | verdict=rejected_by_hidden_test; failing_hidden_tests=['test_err_unwrap_or_returns_default', 'test_ok_unwrap_or_returns_value', 'test_err_map_stays_err_without_calling_fn', 'test_ok_with_falsy_value_unwraps_to_that_value'] |
| `map_mutates_in_place` | semantic_mutant | reject | rejected_by_hidden_test | PASS | verdict=rejected_by_hidden_test; failing_hidden_tests=['test_ok_map_returns_new_result_without_mutating_original'] |
| `unwrap_or_truthiness_bypass` | semantic_mutant | reject | rejected_by_hidden_test | PASS | verdict=rejected_by_hidden_test; failing_hidden_tests=['test_ok_with_falsy_value_unwraps_to_that_value'] |
| `ok_err_subclasses` | alternative | accept | accepted | PASS | verdict=accepted |

## Mutation analysis

- Generated: 19
- Unsupported (base file failed the unparse round-trip self-check): 0
- Declared equivalent: 0
- Intercepted by regression/scope gate (never reached the hidden suite): 0
- Killed by the hidden suite: 19
- **Survived: 0**

## Findings

- **[INFO] A `_pytest/` package nested inside this task's editable subtree is not flagged as a protected-path violation, but empirical testing confirms this is NOT currently exploitable.** (`protected_paths.pytest_shadow_package_nested`)
  Injecting 'resultkit/_pytest/__init__.py' (nested inside the editable package, not at the snapshot root) was NOT flagged as touching a protected path — but `python -m pytest` never adds the editable package directory itself to sys.path, so this nested `_pytest/` is only importable as `<package>._pytest`, never as the bare top-level `_pytest` the real pytest package needs; a controlled test confirms `import _pytest` still resolves to the real site-packages module. Recorded as a structural gap (no basename/suffix rule catches a directory named `_pytest`) that would only matter if this task ever lost its editable_paths allow-list, not as a live weakness today. See docs/agents/ORACLE.md.

## Limitations

- Grading executes submitted/mutated code via LocalSandbox, which provides per-run workspace isolation and timeouts but NOT untrusted-agent security isolation (runner/afa_runner/sandbox.py's own module docstring). Every check in this report assumes the code being graded is trying to game the SCORE, not attack the HOST — see isolation.hidden_test_readability for a concrete, always-present consequence of that assumption.
- Hidden-test readability during grading could not be ruled out (see the isolation.hidden_test_readability check) — this finding is deliberately excluded from the status precedence (afa_integrity.health) because it is a constant, documented property of the current LocalSandbox threat model, not something this specific task can fix.
- Mutation equivalence is undecidable in general; a surviving mutant is reported as-is unless explicitly declared equivalent in tasks/<id>/integrity/integrity.json. A mutation kill rate is never treated as a correctness probability (mission §16).

## Provenance

- `task_id`: result-type
- `task_version`: 1.0.2
- `task_json_hash`: sha256:747fa068d75e4a5d5215a36c09eceab1418193ccf002fa22d969a9f5f8918dff
- `snapshot_hash`: sha256:88619df6d32369c3265e1bff793b0ef60dc0dbf2b2f072d10e498e0eddc4abb3
- `reference_hash`: sha256:f632541f80e8b6eca26239d98d5bb9752abd1a50ea1172eab9e66192a6c00297
- `grading_hash`: sha256:70f22bb2c35b33355415761c7f00d82cce99ec47aca8d6366f240296f20a5ddf
- `controls_hash`: sha256:7c2825ec0c055ae29d9d942a5fadeeb16db571c92083826a203542f683af410d
- `engine_version`: 0.1.0
- `afa_kernel_version`: 0.1.0
- `afa_runner_version`: 0.2.0
- `python_version`: 3.13.2
- `platform`: macOS-26.3-arm64-arm-64bit-Mach-O
