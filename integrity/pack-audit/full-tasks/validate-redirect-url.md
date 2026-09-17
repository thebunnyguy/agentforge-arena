# AgentForge Benchmark Integrity Report

**Task**: `validate-redirect-url`  
**Version**: `1.0.1`  
**Mode**: `full`  
**Engine version**: `0.1.0` (schema `1.0.0`)  
**Timestamp**: 2026-09-17T20:43:24.253224+00:00  
**Duration**: 91125 ms

## Status: INVALID

**Reason**: known-bad control 'host_substring_match' was ACCEPTED (should have been rejected by the hidden suite)

## Checks

| Check | Category | Status | Severity | Description |
|---|---|---|---|---|
| `reference.solution_validation` | reference | PASS | info | Reference solution scores (1.0, True) identically across 5 repeated grades. |
| `noop.unmodified_baseline` | negative_control | PASS | info | The unmodified snapshot passes regression, fails the hidden suite (T_hidden=0.364), and scores 0.0 / functional_pass=False, as required. |
| `hidden_import_closure.gate7` | isolation | PASS | info | Task uses an editable_paths allow-list, which makes gate 7 (no editable, unprotected oracle-helper import) hold structurally: any local module the hidden/regression suites import that isn't the editable code-under-test is already unreachable by any diff without failing the scope gate. |
| `protected_paths.tampering_probes` | isolation | PASS | info | All 11 protected-path/allow-list probes correctly flagged a scope violation. One known, documented gap (a `_pytest/` shadow package) was also probed and confirmed — see findings. |
| `controls.declared_controls` | controls | FAIL | critical | 1/5 declared control(s) did NOT match their declared expectation via a genuine hidden-test verdict: host_substring_match. A known-bad solution that is accepted, or a valid alternative that is rejected by the hidden suite, is direct evidence the oracle is either too permissive or too narrow. |
| `mutation.generic_ast_mutants` | mutation | WARNING | medium | 9/31 relevant mutant(s) survived (kill_rate=0.71 over 31 relevant of 31 generated). A surviving mutant is not automatic proof of a broken oracle — review whether each represents behavior the task contract actually promises to reject (mission §8); see evidence.survived for exact locations. |
| `determinism.repeated_grading` | determinism | PASS | info | All 6 sampled artifact(s) graded identically across their repeats. |
| `isolation.hidden_test_readability` | isolation_limitation | UNVERIFIABLE | high | CONFIRMED: code under grading can read the hidden test source during the hidden-suite run (the probe successfully detected and read the hidden test file from its own cwd). This is a known, deliberate limitation of the current trusted-local LocalSandbox threat model, not a defect in this task specifically — real untrusted-agent isolation (e.g. a network-disabled, filesystem-scoped DockerSandbox) is out of scope for this engine (mission §14/§25) and is tracked as a repo-wide 'deliberately still open' item. |

## Controls

| Name | Kind | Expected | Verdict | Status | Notes |
|---|---|---|---|---|---|
| `host_substring_match` | known_bad | reject | accepted | FAIL | verdict=accepted |
| `protocol_relative_bypass` | known_bad | reject | rejected_by_hidden_test | PASS | verdict=rejected_by_hidden_test; failing_hidden_tests=['test_protocol_relative_raises'] |
| `scheme_blacklist` | known_bad | reject | rejected_by_hidden_test | PASS | verdict=rejected_by_hidden_test; failing_hidden_tests=['test_non_http_scheme_to_allowed_host_raises'] |
| `host_only_scheme_forgotten` | semantic_mutant | reject | rejected_by_hidden_test | PASS | verdict=rejected_by_hidden_test; failing_hidden_tests=['test_hosted_javascript_scheme_raises', 'test_hosted_data_scheme_raises', 'test_non_http_scheme_to_allowed_host_raises'] |
| `allowlist_first_dispatch` | alternative | accept | accepted | PASS | verdict=accepted |

## Mutation analysis

- Generated: 31
- Unsupported (base file failed the unparse round-trip self-check): 0
- Declared equivalent: 0
- Killed: 22
- **Survived: 9**

Survived mutants (review whether the task contract actually promises to reject each):

| File | Line | Family | Description |
|---|---|---|---|
| `saferedirect/redirect.py` | 18 | remove_branch | remove_branch_force_false: if not isinstance(target, str) or not target:
        raise ValueError("redirect target must be a non-empty string") (if-condition forced to False (branch never taken)) |
| `saferedirect/redirect.py` | 18 | remove_validation | remove_validation: if not isinstance(target, str) or not target:
        raise ValueError("redirect target must be a non-empty string") (if-guard's raise removed (body -> pass)) |
| `saferedirect/redirect.py` | 18 | swap_boolean_condition | swap_boolean_condition: not isinstance(target, str) or not target (Or -> And) |
| `saferedirect/redirect.py` | 23 | remove_branch | remove_branch_force_false: if target.startswith("//"):
        raise ValueError("protocol-relative redirect is not allowed: %r" % (target,)) (if-condition forced to False (branch never taken)) |
| `saferedirect/redirect.py` | 23 | remove_validation | remove_validation: if target.startswith("//"):
        raise ValueError("protocol-relative redirect is not allowed: %r" % (target,)) (if-guard's raise removed (body -> pass)) |
| `saferedirect/redirect.py` | 29 | swap_boolean_condition | swap_boolean_condition: not parsed.scheme and not parsed.netloc (And -> Or) |
| `saferedirect/redirect.py` | 30 | remove_branch | remove_branch_force_true: if target.startswith("/"):
            return target (if-condition forced to True (branch always taken)) |
| `saferedirect/redirect.py` | 43 | remove_branch | remove_branch_force_false: if not parsed.netloc:
        raise ValueError("redirect target must have a host: %r" % (target,)) (if-condition forced to False (branch never taken)) |
| `saferedirect/redirect.py` | 43 | remove_validation | remove_validation: if not parsed.netloc:
        raise ValueError("redirect target must have a host: %r" % (target,)) (if-guard's raise removed (body -> pass)) |

## Findings

- **[HIGH] A `_pytest/` package directory is not flagged as a protected-path violation, though grading runs pytest with the cleanroom at sys.path[0].** (`protected_paths.pytest_shadow_package`)
  Injecting 'saferedirect/_pytest/__init__.py' was NOT flagged as touching a protected path. ALWAYS_PROTECTED_BASENAMES matches basenames, not directory names, so a submission-created `_pytest/` package shadowing the real `_pytest` internals package is currently only stopped by this task's editable_paths allow-list (when configured), not by a structural guarantee. See docs/agents/ORACLE.md for why this is reported rather than silently fixed here.

## Limitations

- Grading executes submitted/mutated code via LocalSandbox, which provides per-run workspace isolation and timeouts but NOT untrusted-agent security isolation (runner/afa_runner/sandbox.py's own module docstring). Every check in this report assumes the code being graded is trying to game the SCORE, not attack the HOST — see isolation.hidden_test_readability for a concrete, always-present consequence of that assumption.
- Hidden-test readability during grading could not be ruled out (see the isolation.hidden_test_readability check) — this finding is deliberately excluded from the status precedence (afa_integrity.health) because it is a constant, documented property of the current LocalSandbox threat model, not something this specific task can fix.
- Mutation equivalence is undecidable in general; a surviving mutant is reported as-is unless explicitly declared equivalent in tasks/<id>/integrity/integrity.json. A mutation kill rate is never treated as a correctness probability (mission §16).

## Provenance

- `task_id`: validate-redirect-url
- `task_version`: 1.0.1
- `task_json_hash`: sha256:25514790657be91989b50786fa730b6f3a334b85041697a59901ec3e9a7ecb95
- `snapshot_hash`: sha256:3b2b5343c9e096696e27a87b50de0a6b7b527242713d3fddbffbfec4f48a7bc9
- `reference_hash`: sha256:eb99c49771766479b7fa201d9955e435943a0abd973fa75b4201980dc6a9e255
- `grading_hash`: sha256:1acfc8c1bf3f457933ce53f59bcf2e393bc400166b92491437af09288202fe67
- `controls_hash`: sha256:237493ca913a4c2a5231ff13cea93c971243d675b23fba04e675bef88553dc30
- `engine_version`: 0.1.0
- `afa_kernel_version`: 0.1.0
- `afa_runner_version`: 0.2.0
- `python_version`: 3.13.2
- `platform`: macOS-26.3-arm64-arm-64bit-Mach-O
