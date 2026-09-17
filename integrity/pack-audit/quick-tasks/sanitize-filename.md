# AgentForge Benchmark Integrity Report

**Task**: `sanitize-filename`  
**Version**: `1.0.1`  
**Mode**: `quick`  
**Engine version**: `0.1.0` (schema `1.0.0`)  
**Timestamp**: 2026-09-17T21:14:40.682918+00:00  
**Duration**: 21047 ms

## Status: INVALID

**Reason**: known-bad control 'strict_allowlist' was ACCEPTED (should have been rejected by the hidden suite)

## Checks

| Check | Category | Status | Severity | Description |
|---|---|---|---|---|
| `reference.solution_validation` | reference | PASS | info | Reference solution scores (1.0, True) identically across 3 repeated grades. |
| `noop.unmodified_baseline` | negative_control | PASS | info | The unmodified snapshot passes regression, fails the hidden suite (T_hidden=0.300), and scores 0.0 / functional_pass=False, as required. |
| `hidden_import_closure.gate7` | isolation | PASS | info | At most one distinct local file (['safename/__init__.py']) is reachable by a diff without failing the scope gate and imported by the hidden/regression suites — unambiguously the code under test, not a separate oracle-helper module. |
| `protected_paths.tampering_probes` | isolation | PASS | info | All 12 protected-path/allow-list probes correctly flagged a scope violation. One known, documented gap (a `_pytest/` shadow package) was also probed and confirmed — see findings. |
| `controls.declared_controls` | controls | FAIL | critical | 1/5 declared control(s) did NOT match their declared expectation via a genuine hidden-test verdict: strict_allowlist. A known-bad solution that is accepted, or a valid alternative that is rejected by the hidden suite, is direct evidence the oracle is either too permissive or too narrow. |
| `determinism.repeated_grading` | determinism | PASS | info | All 1 sampled artifact(s) graded identically across their repeats. |

## Controls

| Name | Kind | Expected | Verdict | Status | Notes |
|---|---|---|---|---|---|
| `sanitize_instead_of_reject` | known_bad | reject | rejected_by_hidden_test | PASS | verdict=rejected_by_hidden_test; failing_hidden_tests=['test_traversal_raises', 'test_separator_raises', 'test_backslash_separator_raises', 'test_null_byte_raises'] |
| `strict_allowlist` | known_bad | reject | accepted | FAIL | verdict=accepted |
| `substring_dotdot` | known_bad | reject | rejected_by_hidden_test | PASS | verdict=rejected_by_hidden_test; failing_hidden_tests=['test_inner_dots_allowed'] |
| `posix_separator_only` | semantic_mutant | reject | rejected_by_hidden_test | PASS | verdict=rejected_by_hidden_test; failing_hidden_tests=['test_backslash_separator_raises'] |
| `regex_single_check` | alternative | accept | accepted | PASS | verdict=accepted |

## Findings

- **[HIGH] A `_pytest/` package directory is not flagged as a protected-path violation, though grading runs pytest with the cleanroom at sys.path[0].** (`protected_paths.pytest_shadow_package`)
  Injecting 'safename/_pytest/__init__.py' was NOT flagged as touching a protected path. ALWAYS_PROTECTED_BASENAMES matches basenames, not directory names, so a submission-created `_pytest/` package shadowing the real `_pytest` internals package is currently only stopped by this task's editable_paths allow-list (when configured), not by a structural guarantee. See docs/agents/ORACLE.md for why this is reported rather than silently fixed here.

## Limitations

- Grading executes submitted/mutated code via LocalSandbox, which provides per-run workspace isolation and timeouts but NOT untrusted-agent security isolation (runner/afa_runner/sandbox.py's own module docstring). Every check in this report assumes the code being graded is trying to game the SCORE, not attack the HOST — see isolation.hidden_test_readability for a concrete, always-present consequence of that assumption.
- Mutation testing and a determinism sample over declared controls were not run — pass --full or --mutation for stronger evidence.
- The isolation probe was not run (FULL mode only) — pass --full to check whether the hidden test source is readable by code being graded.
- Mutation equivalence is undecidable in general; a surviving mutant is reported as-is unless explicitly declared equivalent in tasks/<id>/integrity/integrity.json. A mutation kill rate is never treated as a correctness probability (mission §16).

## Provenance

- `task_id`: sanitize-filename
- `task_version`: 1.0.1
- `task_json_hash`: sha256:f723e04092f89ddae337a57c6ef209bbe8c7f188eb098cf6532fd839e051b4d4
- `snapshot_hash`: sha256:bf8f4ced9822a79a82e412c90564b6daaa8e38ef89c6790879fc13c00b5a3a6a
- `reference_hash`: sha256:e92a20665e0423aab32f3b03e7b7420c610967805ab89d0126b27d2cf3f9d78c
- `grading_hash`: sha256:c58283d2a63dd28920b0dde61ea2f6115203c203b83de43fcac3d14cec7687b5
- `controls_hash`: sha256:3e50db285dc3e6cec61566a65b742841e46c767ce5b8956b25f8a457a0548c1a
- `engine_version`: 0.1.0
- `afa_kernel_version`: 0.1.0
- `afa_runner_version`: 0.2.0
- `python_version`: 3.13.2
- `platform`: macOS-26.3-arm64-arm-64bit-Mach-O
