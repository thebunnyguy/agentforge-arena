# AgentForge Benchmark Integrity Report

**Task**: `expression-evaluator`  
**Version**: `1.0.2`  
**Mode**: `full`  
**Engine version**: `0.1.0` (schema `1.0.0`)  
**Timestamp**: 2026-09-18T07:17:14.878458+00:00  
**Duration**: 360286 ms

## Status: HEALTHY

**Reason**: All checks passed with no outstanding findings.

## Checks

| Check | Category | Status | Severity | Description |
|---|---|---|---|---|
| `reference.solution_validation` | reference | PASS | info | Reference solution scores (1.0, True) identically across 5 repeated grades. |
| `noop.unmodified_baseline` | negative_control | PASS | info | The unmodified snapshot passes regression, fails the hidden suite (T_hidden=0.000), and scores 0.0 / functional_pass=False, as required. |
| `hidden_import_closure.gate7` | isolation | PASS | info | At most one distinct local file (['calckit/__init__.py']) is reachable by a diff without failing the scope gate and imported by the hidden/regression suites — unambiguously the code under test, not a separate oracle-helper module. |
| `protected_paths.tampering_probes` | isolation | PASS | info | All 12 protected-path/allow-list probes correctly flagged a scope violation. A `_pytest/` package nested inside the editable subtree is also not flagged, but empirical testing confirms it is NOT exploitable under this task's current editable_paths allow-list — see findings. |
| `controls.declared_controls` | controls | PASS | info | All 5 declared control(s) matched their declared expectation via a genuine hidden-test verdict. |
| `mutation.generic_ast_mutants` | mutation | PASS | info | All 55 relevant mutant(s) were killed by the hidden suite (kill_rate=1.00 over 60 generated, 0 unsupported, 5 declared-equivalent, 0 intercepted by the regression/scope gate before reaching the hidden suite). |
| `determinism.repeated_grading` | determinism | PASS | info | All 6 sampled artifact(s) graded identically across their repeats. |
| `isolation.hidden_test_readability` | isolation_limitation | UNVERIFIABLE | high | CONFIRMED: code under grading can read the hidden test source during the hidden-suite run (the probe successfully detected and read the hidden test file from its own cwd). This is a known, deliberate limitation of the current trusted-local LocalSandbox threat model, not a defect in this task specifically — real untrusted-agent isolation (e.g. a network-disabled, filesystem-scoped DockerSandbox) is out of scope for this engine (mission §14/§25) and is tracked as a repo-wide 'deliberately still open' item. |

## Controls

| Name | Kind | Expected | Verdict | Status | Notes |
|---|---|---|---|---|---|
| `integer_division_truncation` | known_bad | reject | rejected_by_hidden_test | PASS | verdict=rejected_by_hidden_test; failing_hidden_tests=['test_division_produces_float'] |
| `right_associative_subtraction` | known_bad | reject | rejected_by_hidden_test | PASS | verdict=rejected_by_hidden_test; failing_hidden_tests=['test_left_associative_subtraction', 'test_left_associative_division', 'test_chained_subtraction'] |
| `unary_minus_non_leading_crash` | known_bad | reject | rejected_by_hidden_test | PASS | verdict=rejected_by_hidden_test; failing_hidden_tests=['test_unary_minus_in_parens', 'test_unary_minus_after_operator', 'test_unary_minus_after_binary_minus', 'test_unary_plus_supported'] |
| `eval_based_implementation` | semantic_mutant | reject | rejected_by_hidden_test | PASS | verdict=rejected_by_hidden_test; failing_hidden_tests=['test_invalid_character_is_rejected', 'test_trailing_tokens_are_rejected', 'test_missing_operand_raises_value_error'] |
| `shunting_yard_rpn` | alternative | accept | accepted | PASS | verdict=accepted |

## Mutation analysis

- Generated: 60
- Unsupported (base file failed the unparse round-trip self-check): 0
- Declared equivalent: 5
- Intercepted by regression/scope gate (never reached the hidden suite): 0
- Killed by the hidden suite: 55
- **Survived: 0**

## Findings

- **[INFO] A `_pytest/` package nested inside this task's editable subtree is not flagged as a protected-path violation, but empirical testing confirms this is NOT currently exploitable.** (`protected_paths.pytest_shadow_package_nested`)
  Injecting 'calckit/_pytest/__init__.py' (nested inside the editable package, not at the snapshot root) was NOT flagged as touching a protected path — but `python -m pytest` never adds the editable package directory itself to sys.path, so this nested `_pytest/` is only importable as `<package>._pytest`, never as the bare top-level `_pytest` the real pytest package needs; a controlled test confirms `import _pytest` still resolves to the real site-packages module. Recorded as a structural gap (no basename/suffix rule catches a directory named `_pytest`) that would only matter if this task ever lost its editable_paths allow-list, not as a live weakness today. See docs/agents/ORACLE.md.

## Limitations

- Grading executes submitted/mutated code via LocalSandbox, which provides per-run workspace isolation and timeouts but NOT untrusted-agent security isolation (runner/afa_runner/sandbox.py's own module docstring). Every check in this report assumes the code being graded is trying to game the SCORE, not attack the HOST — see isolation.hidden_test_readability for a concrete, always-present consequence of that assumption.
- Hidden-test readability during grading could not be ruled out (see the isolation.hidden_test_readability check) — this finding is deliberately excluded from the status precedence (afa_integrity.health) because it is a constant, documented property of the current LocalSandbox threat model, not something this specific task can fix.
- Mutation equivalence is undecidable in general; a surviving mutant is reported as-is unless explicitly declared equivalent in tasks/<id>/integrity/integrity.json. A mutation kill rate is never treated as a correctness probability (mission §16).

## Provenance

- `task_id`: expression-evaluator
- `task_version`: 1.0.2
- `task_json_hash`: sha256:5dc0f18d2aed1752503933af0fff053a1bad53a3191cbec1992a0f7e04039b3a
- `snapshot_hash`: sha256:8106925ef1914e61100bfc3aecd8a3f5db3a4e250298e6b2e3e61c2d7bf1c88b
- `reference_hash`: sha256:1dfcab47cdd1129d772888ef4642d9356dd31991cfb3edbbaff79f3694880132
- `grading_hash`: sha256:368676073db5e191842cd508dae727ce8d42bbf0cd7a81d9f34b2187ea714a8f
- `controls_hash`: sha256:6637cb766a38482bc27d06538ce2ea77356ce3cd3adfa249bf3668127dce2752
- `engine_version`: 0.1.0
- `afa_kernel_version`: 0.1.0
- `afa_runner_version`: 0.2.0
- `python_version`: 3.13.2
- `platform`: macOS-26.3-arm64-arm-64bit-Mach-O
