# AgentForge Benchmark Integrity Report

**Task**: `fix-list-dedup`  
**Version**: `1.0.1`  
**Mode**: `quick`  
**Engine version**: `0.1.0` (schema `1.0.0`)  
**Timestamp**: 2026-09-17T20:39:36.777828+00:00  
**Duration**: 12627 ms

## Status: NEEDS_REVIEW

**Reason**: noop.unmodified_baseline: The unmodified snapshot's weighted hidden pass fraction (T_hidden=0.500) is >= the documented 0.5 ceiling (framework §8.2 gate 2, 08-benchmark-design.md:74): a large fraction of hidden-test weight already passes on doing nothing, so a near-empty or trivial submission could bank substantial continuous score without solving the core requirement. This condition is documented but was never computed anywhere in the codebase before this check — it is not equivalent to the binary hidden_all_passed gate above.

## Checks

| Check | Category | Status | Severity | Description |
|---|---|---|---|---|
| `reference.solution_validation` | reference | PASS | info | Reference solution scores (1.0, True) identically across 3 repeated grades. |
| `noop.unmodified_baseline` | negative_control | WARNING | high | The unmodified snapshot's weighted hidden pass fraction (T_hidden=0.500) is >= the documented 0.5 ceiling (framework §8.2 gate 2, 08-benchmark-design.md:74): a large fraction of hidden-test weight already passes on doing nothing, so a near-empty or trivial submission could bank substantial continuous score without solving the core requirement. This condition is documented but was never computed anywhere in the codebase before this check — it is not equivalent to the binary hidden_all_passed gate above. |
| `hidden_import_closure.gate7` | isolation | PASS | info | Task uses an editable_paths allow-list, which makes gate 7 (no editable, unprotected oracle-helper import) hold structurally: any local module the hidden/regression suites import that isn't the editable code-under-test is already unreachable by any diff without failing the scope gate. |
| `protected_paths.tampering_probes` | isolation | PASS | info | All 11 protected-path/allow-list probes correctly flagged a scope violation. One known, documented gap (a `_pytest/` shadow package) was also probed and confirmed — see findings. |
| `controls.declared_controls` | controls | SKIPPED | medium | No known-bad solutions, semantic mutants, or alternative solutions declared for this task (tasks/<id>/integrity/controls/). The engine has no task-specific evidence beyond the reference/no-op checks. |
| `determinism.repeated_grading` | determinism | PASS | info | All 1 sampled artifact(s) graded identically across their repeats. |

## Findings

- **[HIGH] A `_pytest/` package directory is not flagged as a protected-path violation, though grading runs pytest with the cleanroom at sys.path[0].** (`protected_paths.pytest_shadow_package`)
  Injecting 'listkit/_pytest/__init__.py' was NOT flagged as touching a protected path. ALWAYS_PROTECTED_BASENAMES matches basenames, not directory names, so a submission-created `_pytest/` package shadowing the real `_pytest` internals package is currently only stopped by this task's editable_paths allow-list (when configured), not by a structural guarantee. See docs/agents/ORACLE.md for why this is reported rather than silently fixed here.

## Limitations

- Grading executes submitted/mutated code via LocalSandbox, which provides per-run workspace isolation and timeouts but NOT untrusted-agent security isolation (runner/afa_runner/sandbox.py's own module docstring). Every check in this report assumes the code being graded is trying to game the SCORE, not attack the HOST — see isolation.hidden_test_readability for a concrete, always-present consequence of that assumption.
- No known-bad solutions, semantic mutants, or alternative solutions declared for this task (tasks/<id>/integrity/controls/) — absence of evidence here, not evidence of absence.
- Mutation testing, a determinism sample over declared controls, and the isolation probe were not run (QUICK mode) — run --full for stronger evidence.
- Mutation equivalence is undecidable in general; a surviving mutant is reported as-is unless explicitly declared equivalent in tasks/<id>/integrity/integrity.json. A mutation kill rate is never treated as a correctness probability (mission §16).

## Provenance

- `task_id`: fix-list-dedup
- `task_version`: 1.0.1
- `task_json_hash`: sha256:4585844052dd0167f8cac54821b0312e68fe43e6ed638f8961252c7bfc68043b
- `snapshot_hash`: sha256:bc096636c1ab273604c142e71f78abb349a3a564d4ad30df425b54d7bde37efa
- `reference_hash`: sha256:4e1907024a54fdd10ed7dbd65e9e03def5ad7afcfc75781c626382479aa8e617
- `grading_hash`: sha256:dfbde90c3059114428f7318e72d7ffd327053e3d0d0b29e1017acc9a49818397
- `controls_hash`: None
- `engine_version`: 0.1.0
- `afa_kernel_version`: 0.1.0
- `afa_runner_version`: 0.2.0
- `python_version`: 3.13.2
- `platform`: macOS-26.3-arm64-arm-64bit-Mach-O
