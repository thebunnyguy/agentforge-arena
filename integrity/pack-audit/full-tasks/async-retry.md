# AgentForge Benchmark Integrity Report

**Task**: `async-retry`  
**Version**: `1.0.1`  
**Mode**: `full`  
**Engine version**: `0.1.0` (schema `1.0.0`)  
**Timestamp**: 2026-09-17T20:40:45.120261+00:00  
**Duration**: 68727 ms

## Status: NEEDS_REVIEW

**Reason**: mutation.generic_ast_mutants: 1/9 relevant mutant(s) survived (kill_rate=0.89 over 9 relevant of 9 generated). A surviving mutant is not automatic proof of a broken oracle — review whether each represents behavior the task contract actually promises to reject (mission §8); see evidence.survived for exact locations.; semantic mutant 'swallows_base_exceptions' survived (should have been rejected by the hidden suite)

## Checks

| Check | Category | Status | Severity | Description |
|---|---|---|---|---|
| `reference.solution_validation` | reference | PASS | info | Reference solution scores (1.0, True) identically across 5 repeated grades. |
| `noop.unmodified_baseline` | negative_control | PASS | info | The unmodified snapshot passes regression, fails the hidden suite (T_hidden=0.000), and scores 0.0 / functional_pass=False, as required. |
| `hidden_import_closure.gate7` | isolation | PASS | info | Task uses an editable_paths allow-list, which makes gate 7 (no editable, unprotected oracle-helper import) hold structurally: any local module the hidden/regression suites import that isn't the editable code-under-test is already unreachable by any diff without failing the scope gate. |
| `protected_paths.tampering_probes` | isolation | PASS | info | All 11 protected-path/allow-list probes correctly flagged a scope violation. One known, documented gap (a `_pytest/` shadow package) was also probed and confirmed — see findings. |
| `controls.declared_controls` | controls | FAIL | critical | 1/5 declared control(s) did NOT match their declared expectation via a genuine hidden-test verdict: swallows_base_exceptions. A known-bad solution that is accepted, or a valid alternative that is rejected by the hidden suite, is direct evidence the oracle is either too permissive or too narrow. |
| `mutation.generic_ast_mutants` | mutation | WARNING | medium | 1/9 relevant mutant(s) survived (kill_rate=0.89 over 9 relevant of 9 generated). A surviving mutant is not automatic proof of a broken oracle — review whether each represents behavior the task contract actually promises to reject (mission §8); see evidence.survived for exact locations. |
| `determinism.repeated_grading` | determinism | PASS | info | All 6 sampled artifact(s) graded identically across their repeats. |
| `isolation.hidden_test_readability` | isolation_limitation | UNVERIFIABLE | high | CONFIRMED: code under grading can read the hidden test source during the hidden-suite run (the probe successfully detected and read the hidden test file from its own cwd). This is a known, deliberate limitation of the current trusted-local LocalSandbox threat model, not a defect in this task specifically — real untrusted-agent isolation (e.g. a network-disabled, filesystem-scoped DockerSandbox) is out of scope for this engine (mission §14/§25) and is tracked as a repo-wide 'deliberately still open' item. |

## Controls

| Name | Kind | Expected | Verdict | Status | Notes |
|---|---|---|---|---|---|
| `missing_attempts_validation` | known_bad | reject | rejected_by_hidden_test | PASS | verdict=rejected_by_hidden_test; failing_hidden_tests=['test_zero_attempts_raises_value_error'] |
| `off_by_one_extra_attempt` | known_bad | reject | rejected_by_hidden_test | PASS | verdict=rejected_by_hidden_test; failing_hidden_tests=['test_all_attempts_fail_reraises_last', 'test_attempts_one_that_fails_raises'] |
| `reused_coroutine_object` | known_bad | reject | rejected_by_hidden_test | PASS | verdict=rejected_by_hidden_test; failing_hidden_tests=['test_succeeds_on_third_try_after_two_failures', 'test_all_attempts_fail_reraises_last', 'test_does_not_retry_after_success'] |
| `swallows_base_exceptions` | semantic_mutant | reject | accepted | FAIL | verdict=accepted |
| `recursive_retry` | alternative | accept | accepted | PASS | verdict=accepted |

## Mutation analysis

- Generated: 9
- Unsupported (base file failed the unparse round-trip self-check): 0
- Declared equivalent: 0
- Killed: 8
- **Survived: 1**

Survived mutants (review whether the task contract actually promises to reject each):

| File | Line | Family | Description |
|---|---|---|---|
| `aretry/retry.py` | 12 | delete_state_update | delete_state_update: last_exc = None (assignment/state-update statement deleted (replaced with pass)) |

## Findings

- **[HIGH] A `_pytest/` package directory is not flagged as a protected-path violation, though grading runs pytest with the cleanroom at sys.path[0].** (`protected_paths.pytest_shadow_package`)
  Injecting 'aretry/_pytest/__init__.py' was NOT flagged as touching a protected path. ALWAYS_PROTECTED_BASENAMES matches basenames, not directory names, so a submission-created `_pytest/` package shadowing the real `_pytest` internals package is currently only stopped by this task's editable_paths allow-list (when configured), not by a structural guarantee. See docs/agents/ORACLE.md for why this is reported rather than silently fixed here.

## Limitations

- Grading executes submitted/mutated code via LocalSandbox, which provides per-run workspace isolation and timeouts but NOT untrusted-agent security isolation (runner/afa_runner/sandbox.py's own module docstring). Every check in this report assumes the code being graded is trying to game the SCORE, not attack the HOST — see isolation.hidden_test_readability for a concrete, always-present consequence of that assumption.
- Hidden-test readability during grading could not be ruled out (see the isolation.hidden_test_readability check) — this finding is deliberately excluded from the status precedence (afa_integrity.health) because it is a constant, documented property of the current LocalSandbox threat model, not something this specific task can fix.
- Mutation equivalence is undecidable in general; a surviving mutant is reported as-is unless explicitly declared equivalent in tasks/<id>/integrity/integrity.json. A mutation kill rate is never treated as a correctness probability (mission §16).

## Provenance

- `task_id`: async-retry
- `task_version`: 1.0.1
- `task_json_hash`: sha256:3d6e47300146091107964487adb742896c2a796462607c3d70329e8ddd0e8b9a
- `snapshot_hash`: sha256:a6f247ca421ca9c0179221c989e7580936615d84f944139554289c8dd4936b16
- `reference_hash`: sha256:7fe30e9ba5ec37f35bcc2473558015e413b98e3b7d316daac255e316030ee70a
- `grading_hash`: sha256:5b33fe50a7843f35fda9340be13f3696cff6286c78c7a9dadd2301261f016326
- `controls_hash`: sha256:5a8469314af043351a40fdded16db27c4f4aa8d7ce72b41e64177e048144b092
- `engine_version`: 0.1.0
- `afa_kernel_version`: 0.1.0
- `afa_runner_version`: 0.2.0
- `python_version`: 3.13.2
- `platform`: macOS-26.3-arm64-arm-64bit-Mach-O
