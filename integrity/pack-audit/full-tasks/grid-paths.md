# AgentForge Benchmark Integrity Report

**Task**: `grid-paths`  
**Version**: `1.0.0`  
**Mode**: `full`  
**Engine version**: `0.1.0` (schema `1.0.0`)  
**Timestamp**: 2026-09-17T21:17:05.847032+00:00  
**Duration**: 68249 ms

## Status: NEEDS_REVIEW

**Reason**: mutation.generic_ast_mutants: 6/22 relevant mutant(s) survived (kill_rate=0.73 over 22 relevant of 22 generated). A surviving mutant is not automatic proof of a broken oracle — review whether each represents behavior the task contract actually promises to reject (mission §8); see evidence.survived for exact locations.

## Checks

| Check | Category | Status | Severity | Description |
|---|---|---|---|---|
| `reference.solution_validation` | reference | PASS | info | Reference solution scores (1.0, True) identically across 5 repeated grades. |
| `noop.unmodified_baseline` | negative_control | PASS | info | The unmodified snapshot passes regression, fails the hidden suite (T_hidden=0.000), and scores 0.0 / functional_pass=False, as required. |
| `hidden_import_closure.gate7` | isolation | PASS | info | At most one distinct local file (['gridpaths/__init__.py']) is reachable by a diff without failing the scope gate and imported by the hidden/regression suites — unambiguously the code under test, not a separate oracle-helper module. |
| `protected_paths.tampering_probes` | isolation | PASS | info | All 12 protected-path/allow-list probes correctly flagged a scope violation. One known, documented gap (a `_pytest/` shadow package) was also probed and confirmed — see findings. |
| `controls.declared_controls` | controls | SKIPPED | medium | No known-bad solutions, semantic mutants, or alternative solutions declared for this task (tasks/<id>/integrity/controls/). The engine has no task-specific evidence beyond the reference/no-op checks. |
| `mutation.generic_ast_mutants` | mutation | WARNING | medium | 6/22 relevant mutant(s) survived (kill_rate=0.73 over 22 relevant of 22 generated). A surviving mutant is not automatic proof of a broken oracle — review whether each represents behavior the task contract actually promises to reject (mission §8); see evidence.survived for exact locations. |
| `determinism.repeated_grading` | determinism | PASS | info | All 1 sampled artifact(s) graded identically across their repeats. |
| `isolation.hidden_test_readability` | isolation_limitation | UNVERIFIABLE | high | CONFIRMED: code under grading can read the hidden test source during the hidden-suite run (the probe successfully detected and read the hidden test file from its own cwd). This is a known, deliberate limitation of the current trusted-local LocalSandbox threat model, not a defect in this task specifically — real untrusted-agent isolation (e.g. a network-disabled, filesystem-scoped DockerSandbox) is out of scope for this engine (mission §14/§25) and is tracked as a repo-wide 'deliberately still open' item. |

## Mutation analysis

- Generated: 22
- Unsupported (base file failed the unparse round-trip self-check): 0
- Declared equivalent: 0
- Intercepted by regression/scope gate (never reached the hidden suite): 0
- Killed by the hidden suite: 16
- **Survived: 6**

Survived mutants (review whether the task contract actually promises to reject each):

| File | Line | Family | Description |
|---|---|---|---|
| `gridpaths/core.py` | 15 | remove_branch | remove_branch_force_false: if rows <= 0 or cols <= 0:
        return 0 (if-condition forced to False (branch never taken)) |
| `gridpaths/core.py` | 15 | boundary_operator | boundary_operator: rows <= 0 (LtE -> Lt) |
| `gridpaths/core.py` | 15 | swap_boolean_condition | swap_boolean_condition: rows <= 0 or cols <= 0 (Or -> And) |
| `gridpaths/core.py` | 15 | boundary_operator | boundary_operator: cols <= 0 (LtE -> Lt) |
| `gridpaths/core.py` | 16 | return_constant | return_constant: return 0 (return <expr> -> return None) |
| `gridpaths/core.py` | 16 | change_constant | change_constant_increment: 0 (0 -> 1) |

## Findings

- **[HIGH] A `_pytest/` package directory is not flagged as a protected-path violation, though grading runs pytest with the cleanroom at sys.path[0].** (`protected_paths.pytest_shadow_package`)
  Injecting 'gridpaths/_pytest/__init__.py' was NOT flagged as touching a protected path. ALWAYS_PROTECTED_BASENAMES matches basenames, not directory names, so a submission-created `_pytest/` package shadowing the real `_pytest` internals package is currently only stopped by this task's editable_paths allow-list (when configured), not by a structural guarantee. See docs/agents/ORACLE.md for why this is reported rather than silently fixed here.

## Limitations

- Grading executes submitted/mutated code via LocalSandbox, which provides per-run workspace isolation and timeouts but NOT untrusted-agent security isolation (runner/afa_runner/sandbox.py's own module docstring). Every check in this report assumes the code being graded is trying to game the SCORE, not attack the HOST — see isolation.hidden_test_readability for a concrete, always-present consequence of that assumption.
- No known-bad solutions, semantic mutants, or alternative solutions declared for this task (tasks/<id>/integrity/controls/) — absence of evidence here, not evidence of absence.
- Hidden-test readability during grading could not be ruled out (see the isolation.hidden_test_readability check) — this finding is deliberately excluded from the status precedence (afa_integrity.health) because it is a constant, documented property of the current LocalSandbox threat model, not something this specific task can fix.
- Mutation equivalence is undecidable in general; a surviving mutant is reported as-is unless explicitly declared equivalent in tasks/<id>/integrity/integrity.json. A mutation kill rate is never treated as a correctness probability (mission §16).

## Provenance

- `task_id`: grid-paths
- `task_version`: 1.0.0
- `task_json_hash`: sha256:cb98e9612073d643a7313676f2fe58b0b4309a3b651a9967ade3fc4d88c1ee9e
- `snapshot_hash`: sha256:9a19a2b2e806fa13cd53b5f4f6b6e8c429f63abfe1bd914c4bcc04a6b33fa1ad
- `reference_hash`: sha256:de19860acdfaae5b6ee9da26996ccac150a79706ab61b98b3b02adce536ad051
- `grading_hash`: sha256:b902bfc2cdf99b27e51ad4aa30a3df69651247b982c11954e962cd3f0df48e70
- `controls_hash`: None
- `engine_version`: 0.1.0
- `afa_kernel_version`: 0.1.0
- `afa_runner_version`: 0.2.0
- `python_version`: 3.13.2
- `platform`: macOS-26.3-arm64-arm-64bit-Mach-O
