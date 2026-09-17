# AgentForge Benchmark Integrity Report

**Task**: `expression-evaluator`  
**Version**: `1.0.1`  
**Mode**: `full`  
**Engine version**: `0.1.0` (schema `1.0.0`)  
**Timestamp**: 2026-09-17T21:18:28.161486+00:00  
**Duration**: 216684 ms

## Status: NEEDS_REVIEW

**Reason**: mutation.generic_ast_mutants: 5/40 relevant mutant(s) survived (kill_rate=0.88 over 40 relevant of 40 generated). A surviving mutant is not automatic proof of a broken oracle — review whether each represents behavior the task contract actually promises to reject (mission §8); see evidence.survived for exact locations.; semantic mutant 'eval_based_implementation' survived (should have been rejected by the hidden suite)

## Checks

| Check | Category | Status | Severity | Description |
|---|---|---|---|---|
| `reference.solution_validation` | reference | PASS | info | Reference solution scores (1.0, True) identically across 5 repeated grades. |
| `noop.unmodified_baseline` | negative_control | PASS | info | The unmodified snapshot passes regression, fails the hidden suite (T_hidden=0.000), and scores 0.0 / functional_pass=False, as required. |
| `hidden_import_closure.gate7` | isolation | PASS | info | At most one distinct local file (['calckit/__init__.py']) is reachable by a diff without failing the scope gate and imported by the hidden/regression suites — unambiguously the code under test, not a separate oracle-helper module. |
| `protected_paths.tampering_probes` | isolation | PASS | info | All 12 protected-path/allow-list probes correctly flagged a scope violation. One known, documented gap (a `_pytest/` shadow package) was also probed and confirmed — see findings. |
| `controls.declared_controls` | controls | FAIL | critical | 1/5 declared control(s) did NOT match their declared expectation via a genuine hidden-test verdict: eval_based_implementation. A known-bad solution that is accepted, or a valid alternative that is rejected by the hidden suite, is direct evidence the oracle is either too permissive or too narrow. |
| `mutation.generic_ast_mutants` | mutation | WARNING | medium | 5/40 relevant mutant(s) survived (kill_rate=0.88 over 40 relevant of 40 generated). A surviving mutant is not automatic proof of a broken oracle — review whether each represents behavior the task contract actually promises to reject (mission §8); see evidence.survived for exact locations. |
| `determinism.repeated_grading` | determinism | PASS | info | All 6 sampled artifact(s) graded identically across their repeats. |
| `isolation.hidden_test_readability` | isolation_limitation | UNVERIFIABLE | high | CONFIRMED: code under grading can read the hidden test source during the hidden-suite run (the probe successfully detected and read the hidden test file from its own cwd). This is a known, deliberate limitation of the current trusted-local LocalSandbox threat model, not a defect in this task specifically — real untrusted-agent isolation (e.g. a network-disabled, filesystem-scoped DockerSandbox) is out of scope for this engine (mission §14/§25) and is tracked as a repo-wide 'deliberately still open' item. |

## Controls

| Name | Kind | Expected | Verdict | Status | Notes |
|---|---|---|---|---|---|
| `integer_division_truncation` | known_bad | reject | rejected_by_hidden_test | PASS | verdict=rejected_by_hidden_test; failing_hidden_tests=['test_division_produces_float'] |
| `right_associative_subtraction` | known_bad | reject | rejected_by_hidden_test | PASS | verdict=rejected_by_hidden_test; failing_hidden_tests=['test_left_associative_subtraction', 'test_left_associative_division', 'test_chained_subtraction'] |
| `unary_minus_non_leading_crash` | known_bad | reject | rejected_by_hidden_test | PASS | verdict=rejected_by_hidden_test; failing_hidden_tests=['test_unary_minus_in_parens', 'test_unary_minus_after_operator', 'test_unary_minus_after_binary_minus'] |
| `eval_based_implementation` | semantic_mutant | reject | accepted | FAIL | verdict=accepted |
| `shunting_yard_rpn` | alternative | accept | accepted | PASS | verdict=accepted |

## Mutation analysis

- Generated: 40
- Unsupported (base file failed the unparse round-trip self-check): 0
- Declared equivalent: 0
- Intercepted by regression/scope gate (never reached the hidden suite): 0
- Killed by the hidden suite: 35
- **Survived: 5**

Survived mutants (review whether the task contract actually promises to reject each):

| File | Line | Family | Description |
|---|---|---|---|
| `calckit/evaluate.py` | 28 | remove_branch | remove_branch_force_true: if c.isdigit() or c == ".":
            j = i
            seen_dot = False
            while j < n and (expr[j].isdigit() or expr[j] == "."):
                if expr[j] == ".":
                    if  (if-condition forced to True (branch always taken)) |
| `calckit/evaluate.py` | 28 | invert_comparison | invert_comparison: c == "." (Eq -> NotEq) |
| `calckit/evaluate.py` | 32 | remove_branch | remove_branch_force_false: if expr[j] == ".":
                    if seen_dot:
                        raise ValueError("invalid number literal in %r" % expr)
                    seen_dot = True (if-condition forced to False (branch never taken)) |
| `calckit/evaluate.py` | 33 | remove_branch | remove_branch_force_false: if seen_dot:
                        raise ValueError("invalid number literal in %r" % expr) (if-condition forced to False (branch never taken)) |
| `calckit/evaluate.py` | 33 | remove_validation | remove_validation: if seen_dot:
                        raise ValueError("invalid number literal in %r" % expr) (if-guard's raise removed (body -> pass)) |

## Findings

- **[HIGH] A `_pytest/` package directory is not flagged as a protected-path violation, though grading runs pytest with the cleanroom at sys.path[0].** (`protected_paths.pytest_shadow_package`)
  Injecting 'calckit/_pytest/__init__.py' was NOT flagged as touching a protected path. ALWAYS_PROTECTED_BASENAMES matches basenames, not directory names, so a submission-created `_pytest/` package shadowing the real `_pytest` internals package is currently only stopped by this task's editable_paths allow-list (when configured), not by a structural guarantee. See docs/agents/ORACLE.md for why this is reported rather than silently fixed here.

## Limitations

- Grading executes submitted/mutated code via LocalSandbox, which provides per-run workspace isolation and timeouts but NOT untrusted-agent security isolation (runner/afa_runner/sandbox.py's own module docstring). Every check in this report assumes the code being graded is trying to game the SCORE, not attack the HOST — see isolation.hidden_test_readability for a concrete, always-present consequence of that assumption.
- Hidden-test readability during grading could not be ruled out (see the isolation.hidden_test_readability check) — this finding is deliberately excluded from the status precedence (afa_integrity.health) because it is a constant, documented property of the current LocalSandbox threat model, not something this specific task can fix.
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
