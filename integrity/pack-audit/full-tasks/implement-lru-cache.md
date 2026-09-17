# AgentForge Benchmark Integrity Report

**Task**: `implement-lru-cache`  
**Version**: `1.0.1`  
**Mode**: `full`  
**Engine version**: `0.1.0` (schema `1.0.0`)  
**Timestamp**: 2026-09-17T20:40:45.122305+00:00  
**Duration**: 75585 ms

## Status: HEALTHY

**Reason**: All checks passed with no outstanding findings.

## Checks

| Check | Category | Status | Severity | Description |
|---|---|---|---|---|
| `reference.solution_validation` | reference | PASS | info | Reference solution scores (1.0, True) identically across 5 repeated grades. |
| `noop.unmodified_baseline` | negative_control | PASS | info | The unmodified snapshot passes regression, fails the hidden suite (T_hidden=0.000), and scores 0.0 / functional_pass=False, as required. |
| `hidden_import_closure.gate7` | isolation | PASS | info | Task uses an editable_paths allow-list, which makes gate 7 (no editable, unprotected oracle-helper import) hold structurally: any local module the hidden/regression suites import that isn't the editable code-under-test is already unreachable by any diff without failing the scope gate. |
| `protected_paths.tampering_probes` | isolation | PASS | info | All 11 protected-path/allow-list probes correctly flagged a scope violation. One known, documented gap (a `_pytest/` shadow package) was also probed and confirmed — see findings. |
| `controls.declared_controls` | controls | PASS | info | All 4 declared control(s) matched their declared expectation via a genuine hidden-test verdict. |
| `mutation.generic_ast_mutants` | mutation | PASS | info | All 17 relevant mutant(s) were killed (kill_rate=1.00 over 17 generated, 0 unsupported, 0 declared-equivalent). |
| `determinism.repeated_grading` | determinism | PASS | info | All 5 sampled artifact(s) graded identically across their repeats. |
| `isolation.hidden_test_readability` | isolation_limitation | UNVERIFIABLE | high | CONFIRMED: code under grading can read the hidden test source during the hidden-suite run (the probe successfully detected and read the hidden test file from its own cwd). This is a known, deliberate limitation of the current trusted-local LocalSandbox threat model, not a defect in this task specifically — real untrusted-agent isolation (e.g. a network-disabled, filesystem-scoped DockerSandbox) is out of scope for this engine (mission §14/§25) and is tracked as a repo-wide 'deliberately still open' item. |

## Controls

| Name | Kind | Expected | Verdict | Status | Notes |
|---|---|---|---|---|---|
| `evicts_mru_instead_of_lru` | known_bad | reject | rejected_by_hidden_test | PASS | verdict=rejected_by_hidden_test; failing_hidden_tests=['test_evicts_least_recently_used_on_overflow', 'test_get_refreshes_recency_so_other_key_is_evicted', 'test_put_existing_key_updates_value_and_recency', 'test_capacity_one_keeps_only_latest', 'test_capacity_three_evicts_true_lru', 'test_capacity_three_get_refreshes_recency'] |
| `get_ignores_recency` | known_bad | reject | rejected_by_hidden_test | PASS | verdict=rejected_by_hidden_test; failing_hidden_tests=['test_get_refreshes_recency_so_other_key_is_evicted', 'test_capacity_three_get_refreshes_recency'] |
| `off_by_one_capacity` | known_bad | reject | rejected_by_hidden_test | PASS | verdict=rejected_by_hidden_test; failing_hidden_tests=['test_evicts_least_recently_used_on_overflow', 'test_get_refreshes_recency_so_other_key_is_evicted', 'test_put_existing_key_updates_value_and_recency', 'test_capacity_one_keeps_only_latest', 'test_capacity_three_evicts_true_lru', 'test_capacity_three_get_refreshes_recency'] |
| `linked_list_lru` | alternative | accept | accepted | PASS | verdict=accepted |

## Mutation analysis

- Generated: 17
- Unsupported (base file failed the unparse round-trip self-check): 0
- Declared equivalent: 0
- Killed: 17
- **Survived: 0**

## Findings

- **[HIGH] A `_pytest/` package directory is not flagged as a protected-path violation, though grading runs pytest with the cleanroom at sys.path[0].** (`protected_paths.pytest_shadow_package`)
  Injecting 'cachekit/_pytest/__init__.py' was NOT flagged as touching a protected path. ALWAYS_PROTECTED_BASENAMES matches basenames, not directory names, so a submission-created `_pytest/` package shadowing the real `_pytest` internals package is currently only stopped by this task's editable_paths allow-list (when configured), not by a structural guarantee. See docs/agents/ORACLE.md for why this is reported rather than silently fixed here.

## Limitations

- Grading executes submitted/mutated code via LocalSandbox, which provides per-run workspace isolation and timeouts but NOT untrusted-agent security isolation (runner/afa_runner/sandbox.py's own module docstring). Every check in this report assumes the code being graded is trying to game the SCORE, not attack the HOST — see isolation.hidden_test_readability for a concrete, always-present consequence of that assumption.
- Hidden-test readability during grading could not be ruled out (see the isolation.hidden_test_readability check) — this finding is deliberately excluded from the status precedence (afa_integrity.health) because it is a constant, documented property of the current LocalSandbox threat model, not something this specific task can fix.
- Mutation equivalence is undecidable in general; a surviving mutant is reported as-is unless explicitly declared equivalent in tasks/<id>/integrity/integrity.json. A mutation kill rate is never treated as a correctness probability (mission §16).

## Provenance

- `task_id`: implement-lru-cache
- `task_version`: 1.0.1
- `task_json_hash`: sha256:ac9f5d15dca88ecfe3caf7cdf70c2a4fa81157f99a73a60abfd8f52b7e66fc45
- `snapshot_hash`: sha256:a5e91305ea7d88e97ec01b6137d0fc72092e92d23138e1d93da3d147c051edb5
- `reference_hash`: sha256:a63e079f78dfb8df30bc761a051cd72d8d4437ff2bb7ec5e4dcc6046bf17e854
- `grading_hash`: sha256:59287b66f0f17d1707a8e6d9406edfdad6f167962a9aec92415d98aed4cf0f8d
- `controls_hash`: sha256:89d3818856e89a36f6501ec7af1fa704892ca9534aaf00ac768122b1dd4fe723
- `engine_version`: 0.1.0
- `afa_kernel_version`: 0.1.0
- `afa_runner_version`: 0.2.0
- `python_version`: 3.13.2
- `platform`: macOS-26.3-arm64-arm-64bit-Mach-O
