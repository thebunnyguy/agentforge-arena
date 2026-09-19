# AgentForge Benchmark Integrity Report

**Task**: `refactor-order-validation`  
**Version**: `1.0.3`  
**Mode**: `full`  
**Engine version**: `0.1.0` (schema `1.0.0`)  
**Timestamp**: 2026-09-19T00:48:42.394176+00:00  
**Duration**: 129416 ms

## Status: NEEDS_REVIEW

**Reason**: hidden_import_closure.gate7: The hidden/regression suites import 2 distinct reachable local files: ['orderkit/__init__.py', 'orderkit/process.py']. Static import analysis cannot tell 'this is the intended code under test' apart from 'this is an oracle helper an agent could rewrite' when more than one file is reachable — review manually (framework §8.2 gate 7).

## Checks

| Check | Category | Status | Severity | Description |
|---|---|---|---|---|
| `reference.solution_validation` | reference | PASS | info | Reference solution scores (1.0, True) identically across 5 repeated grades. |
| `noop.unmodified_baseline` | negative_control | PASS | info | The unmodified snapshot passes regression, fails the hidden suite (T_hidden=0.000), and scores 0.0 / functional_pass=False, as required. |
| `hidden_import_closure.gate7` | isolation | WARNING | medium | The hidden/regression suites import 2 distinct reachable local files: ['orderkit/__init__.py', 'orderkit/process.py']. Static import analysis cannot tell 'this is the intended code under test' apart from 'this is an oracle helper an agent could rewrite' when more than one file is reachable — review manually (framework §8.2 gate 7). |
| `protected_paths.tampering_probes` | isolation | PASS | info | All 12 protected-path/allow-list probes correctly flagged a scope violation. A `_pytest/` package nested inside the editable subtree is also not flagged, but empirical testing confirms it is NOT exploitable under this task's current editable_paths allow-list — see findings. |
| `controls.declared_controls` | controls | SKIPPED | medium | No known-bad solutions, semantic mutants, or alternative solutions declared for this task (tasks/<id>/integrity/controls/). The engine has no task-specific evidence beyond the reference/no-op checks. |
| `mutation.generic_ast_mutants` | mutation | PASS | info | All 7 relevant mutant(s) were killed by the hidden suite (kill_rate=1.00 over 60 generated, 0 unsupported, 1 declared-equivalent, 52 intercepted by the regression/scope gate before reaching the hidden suite). |
| `determinism.repeated_grading` | determinism | PASS | info | All 1 sampled artifact(s) graded identically across their repeats. |
| `isolation.hidden_test_readability` | isolation_limitation | UNVERIFIABLE | high | CONFIRMED: code under grading can read the hidden test source during the hidden-suite run (the probe successfully detected and read the hidden test file from its own cwd). This is a known, deliberate limitation of the current trusted-local LocalSandbox threat model, not a defect in this task specifically — real untrusted-agent isolation (e.g. a network-disabled, filesystem-scoped DockerSandbox) is out of scope for this engine (mission §14/§25) and is tracked as a repo-wide 'deliberately still open' item. |

## Mutation analysis

- Generated: 60
- Unsupported (base file failed the unparse round-trip self-check): 0
- Declared equivalent: 1
- Intercepted by regression/scope gate (never reached the hidden suite): 52
- Killed by the hidden suite: 7
- **Survived: 0**

## Findings

- **[INFO] A `_pytest/` package nested inside this task's editable subtree is not flagged as a protected-path violation, but empirical testing confirms this is NOT currently exploitable.** (`protected_paths.pytest_shadow_package_nested`)
  Injecting 'orderkit/_pytest/__init__.py' (nested inside the editable package, not at the snapshot root) was NOT flagged as touching a protected path — but `python -m pytest` never adds the editable package directory itself to sys.path, so this nested `_pytest/` is only importable as `<package>._pytest`, never as the bare top-level `_pytest` the real pytest package needs; a controlled test confirms `import _pytest` still resolves to the real site-packages module. Recorded as a structural gap (no basename/suffix rule catches a directory named `_pytest`) that would only matter if this task ever lost its editable_paths allow-list, not as a live weakness today. See docs/agents/ORACLE.md.

## Limitations

- Grading executes submitted/mutated code via LocalSandbox, which provides per-run workspace isolation and timeouts but NOT untrusted-agent security isolation (runner/afa_runner/sandbox.py's own module docstring). Every check in this report assumes the code being graded is trying to game the SCORE, not attack the HOST — see isolation.hidden_test_readability for a concrete, always-present consequence of that assumption.
- No known-bad solutions, semantic mutants, or alternative solutions declared for this task (tasks/<id>/integrity/controls/) — absence of evidence here, not evidence of absence.
- Hidden-test readability during grading could not be ruled out (see the isolation.hidden_test_readability check) — this finding is deliberately excluded from the status precedence (afa_integrity.health) because it is a constant, documented property of the current LocalSandbox threat model, not something this specific task can fix.
- Mutation equivalence is undecidable in general; a surviving mutant is reported as-is unless explicitly declared equivalent in tasks/<id>/integrity/integrity.json. A mutation kill rate is never treated as a correctness probability (mission §16).

## Provenance

- `task_id`: refactor-order-validation
- `task_version`: 1.0.3
- `task_json_hash`: sha256:12b6a81e03122e235be61fdc1b4ba5699402c31336c17b61b45fc12d3ff2c34f
- `snapshot_hash`: sha256:4b29e27e6d180216fded49e1a77d1fadaa0698e43b5152c18e13d6c3aa32f856
- `reference_hash`: sha256:b2bf5c07776faa4ff56f7076641c209fd5bca28c0e096bdc6d87520336edd4e8
- `grading_hash`: sha256:e947850412d5f52e298e8f33d51289e994640fc355dca540c7c6cf753379c0ba
- `controls_hash`: None
- `engine_version`: 0.1.0
- `afa_kernel_version`: 0.1.0
- `afa_runner_version`: 0.2.0
- `python_version`: 3.13.2
- `platform`: macOS-26.3-arm64-arm-64bit-Mach-O
