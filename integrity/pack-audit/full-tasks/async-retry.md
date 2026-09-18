# AgentForge Benchmark Integrity Report

**Task**: `async-retry`  
**Version**: `1.0.2`  
**Mode**: `full`  
**Engine version**: `0.1.0` (schema `1.0.0`)  
**Timestamp**: 2026-09-18T07:12:08.704503+00:00  
**Duration**: 149874 ms

## Status: HEALTHY

**Reason**: All checks passed with no outstanding findings.

## Checks

| Check | Category | Status | Severity | Description |
|---|---|---|---|---|
| `reference.solution_validation` | reference | PASS | info | Reference solution scores (1.0, True) identically across 5 repeated grades. |
| `noop.unmodified_baseline` | negative_control | PASS | info | The unmodified snapshot passes regression, fails the hidden suite (T_hidden=0.000), and scores 0.0 / functional_pass=False, as required. |
| `hidden_import_closure.gate7` | isolation | PASS | info | At most one distinct local file (['aretry/__init__.py']) is reachable by a diff without failing the scope gate and imported by the hidden/regression suites — unambiguously the code under test, not a separate oracle-helper module. |
| `protected_paths.tampering_probes` | isolation | PASS | info | All 12 protected-path/allow-list probes correctly flagged a scope violation. A `_pytest/` package nested inside the editable subtree is also not flagged, but empirical testing confirms it is NOT exploitable under this task's current editable_paths allow-list — see findings. |
| `controls.declared_controls` | controls | PASS | info | All 5 declared control(s) matched their declared expectation via a genuine hidden-test verdict. |
| `mutation.generic_ast_mutants` | mutation | PASS | info | All 8 relevant mutant(s) were killed by the hidden suite (kill_rate=1.00 over 9 generated, 0 unsupported, 1 declared-equivalent, 0 intercepted by the regression/scope gate before reaching the hidden suite). |
| `determinism.repeated_grading` | determinism | PASS | info | All 6 sampled artifact(s) graded identically across their repeats. |
| `isolation.hidden_test_readability` | isolation_limitation | UNVERIFIABLE | high | CONFIRMED: code under grading can read the hidden test source during the hidden-suite run (the probe successfully detected and read the hidden test file from its own cwd). This is a known, deliberate limitation of the current trusted-local LocalSandbox threat model, not a defect in this task specifically — real untrusted-agent isolation (e.g. a network-disabled, filesystem-scoped DockerSandbox) is out of scope for this engine (mission §14/§25) and is tracked as a repo-wide 'deliberately still open' item. |

## Controls

| Name | Kind | Expected | Verdict | Status | Notes |
|---|---|---|---|---|---|
| `missing_attempts_validation` | known_bad | reject | rejected_by_hidden_test | PASS | verdict=rejected_by_hidden_test; failing_hidden_tests=['test_zero_attempts_raises_value_error'] |
| `off_by_one_extra_attempt` | known_bad | reject | rejected_by_hidden_test | PASS | verdict=rejected_by_hidden_test; failing_hidden_tests=['test_all_attempts_fail_reraises_last', 'test_attempts_one_that_fails_raises'] |
| `reused_coroutine_object` | known_bad | reject | rejected_by_hidden_test | PASS | verdict=rejected_by_hidden_test; failing_hidden_tests=['test_succeeds_on_third_try_after_two_failures', 'test_all_attempts_fail_reraises_last', 'test_does_not_retry_after_success'] |
| `swallows_base_exceptions` | semantic_mutant | reject | rejected_by_hidden_test | PASS | verdict=rejected_by_hidden_test; failing_hidden_tests=['test_cancelled_error_propagates_without_retry'] |
| `recursive_retry` | alternative | accept | accepted | PASS | verdict=accepted |

## Mutation analysis

- Generated: 9
- Unsupported (base file failed the unparse round-trip self-check): 0
- Declared equivalent: 1
- Intercepted by regression/scope gate (never reached the hidden suite): 0
- Killed by the hidden suite: 8
- **Survived: 0**

## Findings

- **[INFO] A `_pytest/` package nested inside this task's editable subtree is not flagged as a protected-path violation, but empirical testing confirms this is NOT currently exploitable.** (`protected_paths.pytest_shadow_package_nested`)
  Injecting 'aretry/_pytest/__init__.py' (nested inside the editable package, not at the snapshot root) was NOT flagged as touching a protected path — but `python -m pytest` never adds the editable package directory itself to sys.path, so this nested `_pytest/` is only importable as `<package>._pytest`, never as the bare top-level `_pytest` the real pytest package needs; a controlled test confirms `import _pytest` still resolves to the real site-packages module. Recorded as a structural gap (no basename/suffix rule catches a directory named `_pytest`) that would only matter if this task ever lost its editable_paths allow-list, not as a live weakness today. See docs/agents/ORACLE.md.

## Limitations

- Grading executes submitted/mutated code via LocalSandbox, which provides per-run workspace isolation and timeouts but NOT untrusted-agent security isolation (runner/afa_runner/sandbox.py's own module docstring). Every check in this report assumes the code being graded is trying to game the SCORE, not attack the HOST — see isolation.hidden_test_readability for a concrete, always-present consequence of that assumption.
- Hidden-test readability during grading could not be ruled out (see the isolation.hidden_test_readability check) — this finding is deliberately excluded from the status precedence (afa_integrity.health) because it is a constant, documented property of the current LocalSandbox threat model, not something this specific task can fix.
- Mutation equivalence is undecidable in general; a surviving mutant is reported as-is unless explicitly declared equivalent in tasks/<id>/integrity/integrity.json. A mutation kill rate is never treated as a correctness probability (mission §16).

## Provenance

- `task_id`: async-retry
- `task_version`: 1.0.2
- `task_json_hash`: sha256:6ee7aca3bcabb8779542a9ab74eac65bccfb0bbf848f685078b141d74a97cc9f
- `snapshot_hash`: sha256:a6f247ca421ca9c0179221c989e7580936615d84f944139554289c8dd4936b16
- `reference_hash`: sha256:7fe30e9ba5ec37f35bcc2473558015e413b98e3b7d316daac255e316030ee70a
- `grading_hash`: sha256:bd3d8907bb93f3d781ff711a33da6be49e144baf0fa734a4acefff8ffdaaf553
- `controls_hash`: sha256:5a8469314af043351a40fdded16db27c4f4aa8d7ce72b41e64177e048144b092
- `engine_version`: 0.1.0
- `afa_kernel_version`: 0.1.0
- `afa_runner_version`: 0.2.0
- `python_version`: 3.13.2
- `platform`: macOS-26.3-arm64-arm-64bit-Mach-O
