# AgentForge Benchmark Integrity Report

**Task**: `refactor-order-validation`  
**Version**: `1.0.2`  
**Mode**: `full`  
**Engine version**: `0.1.0` (schema `1.0.0`)  
**Timestamp**: 2026-09-17T21:17:33.260089+00:00  
**Duration**: 97922 ms

## Status: NEEDS_REVIEW

**Reason**: hidden_import_closure.gate7: The hidden/regression suites import 2 distinct reachable local files: ['orderkit/__init__.py', 'orderkit/process.py']. Static import analysis cannot tell 'this is the intended code under test' apart from 'this is an oracle helper an agent could rewrite' when more than one file is reachable — review manually (framework §8.2 gate 7).; mutation.generic_ast_mutants: 4/8 relevant mutant(s) survived (kill_rate=0.50 over 8 relevant of 40 generated). A surviving mutant is not automatic proof of a broken oracle — review whether each represents behavior the task contract actually promises to reject (mission §8); see evidence.survived for exact locations.

## Checks

| Check | Category | Status | Severity | Description |
|---|---|---|---|---|
| `reference.solution_validation` | reference | PASS | info | Reference solution scores (1.0, True) identically across 5 repeated grades. |
| `noop.unmodified_baseline` | negative_control | PASS | info | The unmodified snapshot passes regression, fails the hidden suite (T_hidden=0.000), and scores 0.0 / functional_pass=False, as required. |
| `hidden_import_closure.gate7` | isolation | WARNING | medium | The hidden/regression suites import 2 distinct reachable local files: ['orderkit/__init__.py', 'orderkit/process.py']. Static import analysis cannot tell 'this is the intended code under test' apart from 'this is an oracle helper an agent could rewrite' when more than one file is reachable — review manually (framework §8.2 gate 7). |
| `protected_paths.tampering_probes` | isolation | PASS | info | All 12 protected-path/allow-list probes correctly flagged a scope violation. One known, documented gap (a `_pytest/` shadow package) was also probed and confirmed — see findings. |
| `controls.declared_controls` | controls | SKIPPED | medium | No known-bad solutions, semantic mutants, or alternative solutions declared for this task (tasks/<id>/integrity/controls/). The engine has no task-specific evidence beyond the reference/no-op checks. |
| `mutation.generic_ast_mutants` | mutation | WARNING | medium | 4/8 relevant mutant(s) survived (kill_rate=0.50 over 8 relevant of 40 generated). A surviving mutant is not automatic proof of a broken oracle — review whether each represents behavior the task contract actually promises to reject (mission §8); see evidence.survived for exact locations. |
| `determinism.repeated_grading` | determinism | PASS | info | All 1 sampled artifact(s) graded identically across their repeats. |
| `isolation.hidden_test_readability` | isolation_limitation | UNVERIFIABLE | high | CONFIRMED: code under grading can read the hidden test source during the hidden-suite run (the probe successfully detected and read the hidden test file from its own cwd). This is a known, deliberate limitation of the current trusted-local LocalSandbox threat model, not a defect in this task specifically — real untrusted-agent isolation (e.g. a network-disabled, filesystem-scoped DockerSandbox) is out of scope for this engine (mission §14/§25) and is tracked as a repo-wide 'deliberately still open' item. |

## Mutation analysis

- Generated: 40
- Unsupported (base file failed the unparse round-trip self-check): 0
- Declared equivalent: 0
- Intercepted by regression/scope gate (never reached the hidden suite): 32
- Killed by the hidden suite: 4
- **Survived: 4**

Survived mutants (review whether the task contract actually promises to reject each):

| File | Line | Family | Description |
|---|---|---|---|
| `orderkit/__init__.py` | 4 | delete_state_update | delete_state_update: __all__ = ["process_order", "to_cents", "format_cents"] (assignment/state-update statement deleted (replaced with pass)) |
| `orderkit/money.py` | 14 | change_constant | change_constant_increment: 100 (100 -> 101) |
| `orderkit/process.py` | 20 | remove_branch | remove_branch_force_false: if not isinstance(item, dict):
            raise ValueError("each item must be a dict") (if-condition forced to False (branch never taken)) |
| `orderkit/process.py` | 20 | remove_validation | remove_validation: if not isinstance(item, dict):
            raise ValueError("each item must be a dict") (if-guard's raise removed (body -> pass)) |

## Findings

- **[HIGH] A `_pytest/` package directory is not flagged as a protected-path violation, though grading runs pytest with the cleanroom at sys.path[0].** (`protected_paths.pytest_shadow_package`)
  Injecting 'orderkit/_pytest/__init__.py' was NOT flagged as touching a protected path. ALWAYS_PROTECTED_BASENAMES matches basenames, not directory names, so a submission-created `_pytest/` package shadowing the real `_pytest` internals package is currently only stopped by this task's editable_paths allow-list (when configured), not by a structural guarantee. See docs/agents/ORACLE.md for why this is reported rather than silently fixed here.

## Limitations

- Grading executes submitted/mutated code via LocalSandbox, which provides per-run workspace isolation and timeouts but NOT untrusted-agent security isolation (runner/afa_runner/sandbox.py's own module docstring). Every check in this report assumes the code being graded is trying to game the SCORE, not attack the HOST — see isolation.hidden_test_readability for a concrete, always-present consequence of that assumption.
- No known-bad solutions, semantic mutants, or alternative solutions declared for this task (tasks/<id>/integrity/controls/) — absence of evidence here, not evidence of absence.
- Hidden-test readability during grading could not be ruled out (see the isolation.hidden_test_readability check) — this finding is deliberately excluded from the status precedence (afa_integrity.health) because it is a constant, documented property of the current LocalSandbox threat model, not something this specific task can fix.
- Mutation equivalence is undecidable in general; a surviving mutant is reported as-is unless explicitly declared equivalent in tasks/<id>/integrity/integrity.json. A mutation kill rate is never treated as a correctness probability (mission §16).

## Provenance

- `task_id`: refactor-order-validation
- `task_version`: 1.0.2
- `task_json_hash`: sha256:1a8f44a92d988abd17bf34587b2ec1c01c0e9126e0374d36cc593d52d5ba7f49
- `snapshot_hash`: sha256:4b29e27e6d180216fded49e1a77d1fadaa0698e43b5152c18e13d6c3aa32f856
- `reference_hash`: sha256:b2bf5c07776faa4ff56f7076641c209fd5bca28c0e096bdc6d87520336edd4e8
- `grading_hash`: sha256:e16fce909daf4245a05596c7b55dded2bc39d9ee3f3d1a71e0db1b782214e06b
- `controls_hash`: None
- `engine_version`: 0.1.0
- `afa_kernel_version`: 0.1.0
- `afa_runner_version`: 0.2.0
- `python_version`: 3.13.2
- `platform`: macOS-26.3-arm64-arm-64bit-Mach-O
