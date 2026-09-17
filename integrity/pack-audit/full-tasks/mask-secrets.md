# AgentForge Benchmark Integrity Report

**Task**: `mask-secrets`  
**Version**: `1.0.1`  
**Mode**: `full`  
**Engine version**: `0.1.0` (schema `1.0.0`)  
**Timestamp**: 2026-09-17T20:40:45.122146+00:00  
**Duration**: 67000 ms

## Status: NEEDS_REVIEW

**Reason**: semantic mutant 'boundary_anchored_secrets' survived (should have been rejected by the hidden suite)

## Checks

| Check | Category | Status | Severity | Description |
|---|---|---|---|---|
| `reference.solution_validation` | reference | PASS | info | Reference solution scores (1.0, True) identically across 5 repeated grades. |
| `noop.unmodified_baseline` | negative_control | PASS | info | The unmodified snapshot passes regression, fails the hidden suite (T_hidden=0.000), and scores 0.0 / functional_pass=False, as required. |
| `hidden_import_closure.gate7` | isolation | PASS | info | Task uses an editable_paths allow-list, which makes gate 7 (no editable, unprotected oracle-helper import) hold structurally: any local module the hidden/regression suites import that isn't the editable code-under-test is already unreachable by any diff without failing the scope gate. |
| `protected_paths.tampering_probes` | isolation | PASS | info | All 11 protected-path/allow-list probes correctly flagged a scope violation. One known, documented gap (a `_pytest/` shadow package) was also probed and confirmed — see findings. |
| `controls.declared_controls` | controls | FAIL | critical | 1/5 declared control(s) did NOT match their declared expectation via a genuine hidden-test verdict: boundary_anchored_secrets. A known-bad solution that is accepted, or a valid alternative that is rejected by the hidden suite, is direct evidence the oracle is either too permissive or too narrow. |
| `mutation.generic_ast_mutants` | mutation | PASS | info | All 8 relevant mutant(s) were killed (kill_rate=1.00 over 8 generated, 0 unsupported, 0 declared-equivalent). |
| `determinism.repeated_grading` | determinism | PASS | info | All 6 sampled artifact(s) graded identically across their repeats. |
| `isolation.hidden_test_readability` | isolation_limitation | UNVERIFIABLE | high | CONFIRMED: code under grading can read the hidden test source during the hidden-suite run (the probe successfully detected and read the hidden test file from its own cwd). This is a known, deliberate limitation of the current trusted-local LocalSandbox threat model, not a defect in this task specifically — real untrusted-agent isolation (e.g. a network-disabled, filesystem-scoped DockerSandbox) is out of scope for this engine (mission §14/§25) and is tracked as a repo-wide 'deliberately still open' item. |

## Controls

| Name | Kind | Expected | Verdict | Status | Notes |
|---|---|---|---|---|---|
| `bearer_quantifier_reversed` | known_bad | reject | rejected_by_hidden_test | PASS | verdict=rejected_by_hidden_test; failing_hidden_tests=['test_masks_whole_bearer_credential_not_just_token'] |
| `bearer_token_partial_mask` | known_bad | reject | rejected_by_hidden_test | PASS | verdict=rejected_by_hidden_test; failing_hidden_tests=['test_masks_whole_bearer_credential_not_just_token'] |
| `sk_key_length_off_by_one` | known_bad | reject | rejected_by_hidden_test | PASS | verdict=rejected_by_hidden_test; failing_hidden_tests=['test_masks_api_key', 'test_handles_two_secrets_on_one_line'] |
| `boundary_anchored_secrets` | semantic_mutant | reject | accepted | FAIL | verdict=accepted |
| `span_merge_rebuild` | alternative | accept | accepted | PASS | verdict=accepted |

## Mutation analysis

- Generated: 8
- Unsupported (base file failed the unparse round-trip self-check): 0
- Declared equivalent: 0
- Killed: 8
- **Survived: 0**

## Findings

- **[HIGH] A `_pytest/` package directory is not flagged as a protected-path violation, though grading runs pytest with the cleanroom at sys.path[0].** (`protected_paths.pytest_shadow_package`)
  Injecting 'maskkit/_pytest/__init__.py' was NOT flagged as touching a protected path. ALWAYS_PROTECTED_BASENAMES matches basenames, not directory names, so a submission-created `_pytest/` package shadowing the real `_pytest` internals package is currently only stopped by this task's editable_paths allow-list (when configured), not by a structural guarantee. See docs/agents/ORACLE.md for why this is reported rather than silently fixed here.

## Limitations

- Grading executes submitted/mutated code via LocalSandbox, which provides per-run workspace isolation and timeouts but NOT untrusted-agent security isolation (runner/afa_runner/sandbox.py's own module docstring). Every check in this report assumes the code being graded is trying to game the SCORE, not attack the HOST — see isolation.hidden_test_readability for a concrete, always-present consequence of that assumption.
- Hidden-test readability during grading could not be ruled out (see the isolation.hidden_test_readability check) — this finding is deliberately excluded from the status precedence (afa_integrity.health) because it is a constant, documented property of the current LocalSandbox threat model, not something this specific task can fix.
- Mutation equivalence is undecidable in general; a surviving mutant is reported as-is unless explicitly declared equivalent in tasks/<id>/integrity/integrity.json. A mutation kill rate is never treated as a correctness probability (mission §16).

## Provenance

- `task_id`: mask-secrets
- `task_version`: 1.0.1
- `task_json_hash`: sha256:bf57054ee7e8f8c8f1c04d214112e1220ba263d9bde27e01d4bb31900f5af745
- `snapshot_hash`: sha256:d788c1b90a08e5c267396601f967ca42493ca5008d702ec0fb83a6c7f437313a
- `reference_hash`: sha256:67f297b3cda1845d8880975f61a31da15c6f25150fc84e5600d355e35d881146
- `grading_hash`: sha256:54050ea4c34613a9269da1e865baa54d223dd43a6c5f59ac6eb1700dd60a16cd
- `controls_hash`: sha256:7a881a94a1b1bcb7aa425fc138da1752d209e12c7591773c5652e47c1830d0dc
- `engine_version`: 0.1.0
- `afa_kernel_version`: 0.1.0
- `afa_runner_version`: 0.2.0
- `python_version`: 3.13.2
- `platform`: macOS-26.3-arm64-arm-64bit-Mach-O
