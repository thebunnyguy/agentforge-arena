# AgentForge Benchmark Integrity Report

**Task**: `top-k-frequent`  
**Version**: `1.0.2`  
**Mode**: `quick`  
**Engine version**: `0.1.0` (schema `1.0.0`)  
**Timestamp**: 2026-09-17T20:40:09.225541+00:00  
**Duration**: 12671 ms

## Status: PROVISIONAL

**Reason**: controls.declared_controls: No known-bad solutions, semantic mutants, or alternative solutions declared for this task (tasks/<id>/integrity/controls/). The engine has no task-specific evidence beyond the reference/no-op checks.

## Checks

| Check | Category | Status | Severity | Description |
|---|---|---|---|---|
| `reference.solution_validation` | reference | PASS | info | Reference solution scores (1.0, True) identically across 3 repeated grades. |
| `noop.unmodified_baseline` | negative_control | PASS | info | The unmodified snapshot passes regression, fails the hidden suite (T_hidden=0.000), and scores 0.0 / functional_pass=False, as required. |
| `hidden_import_closure.gate7` | isolation | PASS | info | Task uses an editable_paths allow-list, which makes gate 7 (no editable, unprotected oracle-helper import) hold structurally: any local module the hidden/regression suites import that isn't the editable code-under-test is already unreachable by any diff without failing the scope gate. |
| `protected_paths.tampering_probes` | isolation | PASS | info | All 11 protected-path/allow-list probes correctly flagged a scope violation. One known, documented gap (a `_pytest/` shadow package) was also probed and confirmed — see findings. |
| `controls.declared_controls` | controls | SKIPPED | medium | No known-bad solutions, semantic mutants, or alternative solutions declared for this task (tasks/<id>/integrity/controls/). The engine has no task-specific evidence beyond the reference/no-op checks. |
| `determinism.repeated_grading` | determinism | PASS | info | All 1 sampled artifact(s) graded identically across their repeats. |

## Findings

- **[HIGH] A `_pytest/` package directory is not flagged as a protected-path violation, though grading runs pytest with the cleanroom at sys.path[0].** (`protected_paths.pytest_shadow_package`)
  Injecting 'topk/_pytest/__init__.py' was NOT flagged as touching a protected path. ALWAYS_PROTECTED_BASENAMES matches basenames, not directory names, so a submission-created `_pytest/` package shadowing the real `_pytest` internals package is currently only stopped by this task's editable_paths allow-list (when configured), not by a structural guarantee. See docs/agents/ORACLE.md for why this is reported rather than silently fixed here.

## Limitations

- Grading executes submitted/mutated code via LocalSandbox, which provides per-run workspace isolation and timeouts but NOT untrusted-agent security isolation (runner/afa_runner/sandbox.py's own module docstring). Every check in this report assumes the code being graded is trying to game the SCORE, not attack the HOST — see isolation.hidden_test_readability for a concrete, always-present consequence of that assumption.
- No known-bad solutions, semantic mutants, or alternative solutions declared for this task (tasks/<id>/integrity/controls/) — absence of evidence here, not evidence of absence.
- Mutation testing, a determinism sample over declared controls, and the isolation probe were not run (QUICK mode) — run --full for stronger evidence.
- Mutation equivalence is undecidable in general; a surviving mutant is reported as-is unless explicitly declared equivalent in tasks/<id>/integrity/integrity.json. A mutation kill rate is never treated as a correctness probability (mission §16).

## Provenance

- `task_id`: top-k-frequent
- `task_version`: 1.0.2
- `task_json_hash`: sha256:710fb31abaf94f648cbf825515c30333898e1be0896f5e26f19a5565a30a11dd
- `snapshot_hash`: sha256:11d820c237c4b26088b3a254db6180a6e9a46668befd3ccdf39d2b655a59483b
- `reference_hash`: sha256:20d95c9e137ae74d4d2e40962d1e1d80f7fad753a41d1329081e0040eea5dbcb
- `grading_hash`: sha256:02734c9331d8c0c1a42d145133d5986f4d7327344e1248f4d6e7659470628480
- `controls_hash`: None
- `engine_version`: 0.1.0
- `afa_kernel_version`: 0.1.0
- `afa_runner_version`: 0.2.0
- `python_version`: 3.13.2
- `platform`: macOS-26.3-arm64-arm-64bit-Mach-O
