# AgentForge Benchmark Integrity Report

**Task**: `async-gather-bounded`  
**Version**: `1.0.1`  
**Mode**: `quick`  
**Engine version**: `0.1.0` (schema `1.0.0`)  
**Timestamp**: 2026-09-17T20:39:57.985931+00:00  
**Duration**: 12660 ms

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
  Injecting 'asynckit/_pytest/__init__.py' was NOT flagged as touching a protected path. ALWAYS_PROTECTED_BASENAMES matches basenames, not directory names, so a submission-created `_pytest/` package shadowing the real `_pytest` internals package is currently only stopped by this task's editable_paths allow-list (when configured), not by a structural guarantee. See docs/agents/ORACLE.md for why this is reported rather than silently fixed here.

## Limitations

- Grading executes submitted/mutated code via LocalSandbox, which provides per-run workspace isolation and timeouts but NOT untrusted-agent security isolation (runner/afa_runner/sandbox.py's own module docstring). Every check in this report assumes the code being graded is trying to game the SCORE, not attack the HOST — see isolation.hidden_test_readability for a concrete, always-present consequence of that assumption.
- No known-bad solutions, semantic mutants, or alternative solutions declared for this task (tasks/<id>/integrity/controls/) — absence of evidence here, not evidence of absence.
- Mutation testing, a determinism sample over declared controls, and the isolation probe were not run (QUICK mode) — run --full for stronger evidence.
- Mutation equivalence is undecidable in general; a surviving mutant is reported as-is unless explicitly declared equivalent in tasks/<id>/integrity/integrity.json. A mutation kill rate is never treated as a correctness probability (mission §16).

## Provenance

- `task_id`: async-gather-bounded
- `task_version`: 1.0.1
- `task_json_hash`: sha256:efad5a873f3a46c7e3d10fefca79061323a266e3864d738131e7e10e4c57d321
- `snapshot_hash`: sha256:0d3085ab0de9e056f5dbd82922874b3b96ad8a3dfbcfd603219dbc0b33403875
- `reference_hash`: sha256:3b50b279298f9a4a977c896d11a97fc4caca74313015e53d9ee1a6901c8ccaa6
- `grading_hash`: sha256:9c7dd89d7adb8b5db1d236e801e7b2bb6fcb8837720f3c8ea3e447a93594dde1
- `controls_hash`: None
- `engine_version`: 0.1.0
- `afa_kernel_version`: 0.1.0
- `afa_runner_version`: 0.2.0
- `python_version`: 3.13.2
- `platform`: macOS-26.3-arm64-arm-64bit-Mach-O
