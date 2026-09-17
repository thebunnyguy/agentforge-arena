# AgentForge Benchmark Integrity Report

**Task**: `escape-html`  
**Version**: `1.0.1`  
**Mode**: `quick`  
**Engine version**: `0.1.0` (schema `1.0.0`)  
**Timestamp**: 2026-09-17T20:39:36.771995+00:00  
**Duration**: 21212 ms

## Status: PROVISIONAL

**Reason**: audit mode is QUICK: mutation testing, semantic mutants beyond declared controls, and a wider determinism sample were not run — run --full for stronger evidence

## Checks

| Check | Category | Status | Severity | Description |
|---|---|---|---|---|
| `reference.solution_validation` | reference | PASS | info | Reference solution scores (1.0, True) identically across 3 repeated grades. |
| `noop.unmodified_baseline` | negative_control | PASS | info | The unmodified snapshot passes regression, fails the hidden suite (T_hidden=0.333), and scores 0.0 / functional_pass=False, as required. |
| `hidden_import_closure.gate7` | isolation | PASS | info | Task uses an editable_paths allow-list, which makes gate 7 (no editable, unprotected oracle-helper import) hold structurally: any local module the hidden/regression suites import that isn't the editable code-under-test is already unreachable by any diff without failing the scope gate. |
| `protected_paths.tampering_probes` | isolation | PASS | info | All 11 protected-path/allow-list probes correctly flagged a scope violation. One known, documented gap (a `_pytest/` shadow package) was also probed and confirmed — see findings. |
| `controls.declared_controls` | controls | PASS | info | All 5 declared control(s) matched their declared expectation via a genuine hidden-test verdict. |
| `determinism.repeated_grading` | determinism | PASS | info | All 1 sampled artifact(s) graded identically across their repeats. |

## Controls

| Name | Kind | Expected | Verdict | Status | Notes |
|---|---|---|---|---|---|
| `missing_semicolon_typo` | known_bad | reject | rejected_by_hidden_test | PASS | verdict=rejected_by_hidden_test; failing_hidden_tests=['test_escapes_double_quote', 'test_combined_attribute_value', 'test_escapes_repeated_ampersands_and_brackets'] |
| `missing_single_quote` | known_bad | reject | rejected_by_hidden_test | PASS | verdict=rejected_by_hidden_test; failing_hidden_tests=['test_escapes_single_quote', 'test_combined_attribute_value', 'test_escapes_repeated_ampersands_and_brackets'] |
| `order_bug_ampersand_last` | known_bad | reject | rejected_by_hidden_test | PASS | verdict=rejected_by_hidden_test; failing_hidden_tests=['test_escapes_angle_brackets', 'test_ampersand_first_no_double_escape', 'test_escapes_double_quote', 'test_escapes_single_quote', 'test_combined_attribute_value', 'test_escapes_repeated_occurrences', 'test_escapes_repeated_ampersands_and_brackets'] |
| `missing_quotes_attribute_injection` | semantic_mutant | reject | rejected_by_hidden_test | PASS | verdict=rejected_by_hidden_test; failing_hidden_tests=['test_escapes_double_quote', 'test_escapes_single_quote', 'test_combined_attribute_value', 'test_escapes_repeated_ampersands_and_brackets'] |
| `char_by_char_lookup` | alternative | accept | accepted | PASS | verdict=accepted |

## Findings

- **[HIGH] A `_pytest/` package directory is not flagged as a protected-path violation, though grading runs pytest with the cleanroom at sys.path[0].** (`protected_paths.pytest_shadow_package`)
  Injecting 'htmlesc/_pytest/__init__.py' was NOT flagged as touching a protected path. ALWAYS_PROTECTED_BASENAMES matches basenames, not directory names, so a submission-created `_pytest/` package shadowing the real `_pytest` internals package is currently only stopped by this task's editable_paths allow-list (when configured), not by a structural guarantee. See docs/agents/ORACLE.md for why this is reported rather than silently fixed here.

## Limitations

- Grading executes submitted/mutated code via LocalSandbox, which provides per-run workspace isolation and timeouts but NOT untrusted-agent security isolation (runner/afa_runner/sandbox.py's own module docstring). Every check in this report assumes the code being graded is trying to game the SCORE, not attack the HOST — see isolation.hidden_test_readability for a concrete, always-present consequence of that assumption.
- Mutation testing, a determinism sample over declared controls, and the isolation probe were not run (QUICK mode) — run --full for stronger evidence.
- Mutation equivalence is undecidable in general; a surviving mutant is reported as-is unless explicitly declared equivalent in tasks/<id>/integrity/integrity.json. A mutation kill rate is never treated as a correctness probability (mission §16).

## Provenance

- `task_id`: escape-html
- `task_version`: 1.0.1
- `task_json_hash`: sha256:66d2fcb918107efb6566c9e61b0e2993d789ea9e6c34897dbdfe51140eae1ab0
- `snapshot_hash`: sha256:8dbe7df4d7039f38f32ea699b281f20194bb58bb447cb2ebb6c0f0f3f29dc3d4
- `reference_hash`: sha256:5c98f6e3b7d54f17d426428041b562f79f95c60590cca093f6ac4bf45b3c7d45
- `grading_hash`: sha256:0f50556e6b2a3c5ee3786250a43e54801ef879a6134608e193a0b866ea0efdf1
- `controls_hash`: sha256:d315c28e37f4e81bb0ee0c0aefb4cbc0a573a318fdc376100e30b1beae6fab35
- `engine_version`: 0.1.0
- `afa_kernel_version`: 0.1.0
- `afa_runner_version`: 0.2.0
- `python_version`: 3.13.2
- `platform`: macOS-26.3-arm64-arm-64bit-Mach-O
