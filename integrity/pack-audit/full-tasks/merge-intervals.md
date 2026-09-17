# AgentForge Benchmark Integrity Report

**Task**: `merge-intervals`  
**Version**: `1.0.1`  
**Mode**: `full`  
**Engine version**: `0.1.0` (schema `1.0.0`)  
**Timestamp**: 2026-09-17T20:41:10.665144+00:00  
**Duration**: 47460 ms

## Status: NEEDS_REVIEW

**Reason**: mutation.generic_ast_mutants: 3/17 relevant mutant(s) survived (kill_rate=0.82 over 17 relevant of 17 generated). A surviving mutant is not automatic proof of a broken oracle — review whether each represents behavior the task contract actually promises to reject (mission §8); see evidence.survived for exact locations.

## Checks

| Check | Category | Status | Severity | Description |
|---|---|---|---|---|
| `reference.solution_validation` | reference | PASS | info | Reference solution scores (1.0, True) identically across 5 repeated grades. |
| `noop.unmodified_baseline` | negative_control | PASS | info | The unmodified snapshot passes regression, fails the hidden suite (T_hidden=0.333), and scores 0.0 / functional_pass=False, as required. |
| `hidden_import_closure.gate7` | isolation | PASS | info | Task uses an editable_paths allow-list, which makes gate 7 (no editable, unprotected oracle-helper import) hold structurally: any local module the hidden/regression suites import that isn't the editable code-under-test is already unreachable by any diff without failing the scope gate. |
| `protected_paths.tampering_probes` | isolation | PASS | info | All 11 protected-path/allow-list probes correctly flagged a scope violation. One known, documented gap (a `_pytest/` shadow package) was also probed and confirmed — see findings. |
| `controls.declared_controls` | controls | SKIPPED | medium | No known-bad solutions, semantic mutants, or alternative solutions declared for this task (tasks/<id>/integrity/controls/). The engine has no task-specific evidence beyond the reference/no-op checks. |
| `mutation.generic_ast_mutants` | mutation | WARNING | medium | 3/17 relevant mutant(s) survived (kill_rate=0.82 over 17 relevant of 17 generated). A surviving mutant is not automatic proof of a broken oracle — review whether each represents behavior the task contract actually promises to reject (mission §8); see evidence.survived for exact locations. |
| `determinism.repeated_grading` | determinism | PASS | info | All 1 sampled artifact(s) graded identically across their repeats. |
| `isolation.hidden_test_readability` | isolation_limitation | UNVERIFIABLE | high | CONFIRMED: code under grading can read the hidden test source during the hidden-suite run (the probe successfully detected and read the hidden test file from its own cwd). This is a known, deliberate limitation of the current trusted-local LocalSandbox threat model, not a defect in this task specifically — real untrusted-agent isolation (e.g. a network-disabled, filesystem-scoped DockerSandbox) is out of scope for this engine (mission §14/§25) and is tracked as a repo-wide 'deliberately still open' item. |

## Mutation analysis

- Generated: 17
- Unsupported (base file failed the unparse round-trip self-check): 0
- Declared equivalent: 0
- Killed: 14
- **Survived: 3**

Survived mutants (review whether the task contract actually promises to reject each):

| File | Line | Family | Description |
|---|---|---|---|
| `intervalkit/merge.py` | 12 | change_constant | change_constant_zero: 1 (1 -> 0) |
| `intervalkit/merge.py` | 13 | change_constant | change_constant_zero: 1 (1 -> 0) |
| `intervalkit/merge.py` | 14 | change_constant | change_constant_zero: 1 (1 -> 0) |

## Findings

- **[HIGH] A `_pytest/` package directory is not flagged as a protected-path violation, though grading runs pytest with the cleanroom at sys.path[0].** (`protected_paths.pytest_shadow_package`)
  Injecting 'intervalkit/_pytest/__init__.py' was NOT flagged as touching a protected path. ALWAYS_PROTECTED_BASENAMES matches basenames, not directory names, so a submission-created `_pytest/` package shadowing the real `_pytest` internals package is currently only stopped by this task's editable_paths allow-list (when configured), not by a structural guarantee. See docs/agents/ORACLE.md for why this is reported rather than silently fixed here.

## Limitations

- Grading executes submitted/mutated code via LocalSandbox, which provides per-run workspace isolation and timeouts but NOT untrusted-agent security isolation (runner/afa_runner/sandbox.py's own module docstring). Every check in this report assumes the code being graded is trying to game the SCORE, not attack the HOST — see isolation.hidden_test_readability for a concrete, always-present consequence of that assumption.
- No known-bad solutions, semantic mutants, or alternative solutions declared for this task (tasks/<id>/integrity/controls/) — absence of evidence here, not evidence of absence.
- Hidden-test readability during grading could not be ruled out (see the isolation.hidden_test_readability check) — this finding is deliberately excluded from the status precedence (afa_integrity.health) because it is a constant, documented property of the current LocalSandbox threat model, not something this specific task can fix.
- Mutation equivalence is undecidable in general; a surviving mutant is reported as-is unless explicitly declared equivalent in tasks/<id>/integrity/integrity.json. A mutation kill rate is never treated as a correctness probability (mission §16).

## Provenance

- `task_id`: merge-intervals
- `task_version`: 1.0.1
- `task_json_hash`: sha256:aff56281ed50cd66c4344292ec0b7180c3959c85ff934f3059a5ab4570180236
- `snapshot_hash`: sha256:29b6b3291238862d00d4515ec6c072cc4c43cb3754bd8232497dd5c57c0ed6b0
- `reference_hash`: sha256:b9df8616043c87592e8f4785484e575eb72ace34d1c5e74ee7c6ec658e180596
- `grading_hash`: sha256:21be86aad4fb708d5f62d23c40263e563fa9b4a801366f8721177cc75ecbe4e8
- `controls_hash`: None
- `engine_version`: 0.1.0
- `afa_kernel_version`: 0.1.0
- `afa_runner_version`: 0.2.0
- `python_version`: 3.13.2
- `platform`: macOS-26.3-arm64-arm-64bit-Mach-O
