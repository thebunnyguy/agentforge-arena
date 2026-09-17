# AgentForge Benchmark Integrity Report

**Task**: `fix-roman-numerals`  
**Version**: `1.0.0`  
**Mode**: `full`  
**Engine version**: `0.1.0` (schema `1.0.0`)  
**Timestamp**: 2026-09-17T21:15:24.039424+00:00  
**Duration**: 98102 ms

## Status: NEEDS_REVIEW

**Reason**: mutation.generic_ast_mutants: 1/17 relevant mutant(s) survived (kill_rate=0.94 over 17 relevant of 27 generated). A surviving mutant is not automatic proof of a broken oracle — review whether each represents behavior the task contract actually promises to reject (mission §8); see evidence.survived for exact locations.

## Checks

| Check | Category | Status | Severity | Description |
|---|---|---|---|---|
| `reference.solution_validation` | reference | PASS | info | Reference solution scores (1.0, True) identically across 5 repeated grades. |
| `noop.unmodified_baseline` | negative_control | PASS | info | The unmodified snapshot passes regression, fails the hidden suite (T_hidden=0.222), and scores 0.0 / functional_pass=False, as required. |
| `hidden_import_closure.gate7` | isolation | PASS | info | At most one distinct local file (['romankit/__init__.py']) is reachable by a diff without failing the scope gate and imported by the hidden/regression suites — unambiguously the code under test, not a separate oracle-helper module. |
| `protected_paths.tampering_probes` | isolation | PASS | info | All 12 protected-path/allow-list probes correctly flagged a scope violation. One known, documented gap (a `_pytest/` shadow package) was also probed and confirmed — see findings. |
| `controls.declared_controls` | controls | PASS | info | All 4 declared control(s) matched their declared expectation via a genuine hidden-test verdict. |
| `mutation.generic_ast_mutants` | mutation | WARNING | medium | 1/17 relevant mutant(s) survived (kill_rate=0.94 over 17 relevant of 27 generated). A surviving mutant is not automatic proof of a broken oracle — review whether each represents behavior the task contract actually promises to reject (mission §8); see evidence.survived for exact locations. |
| `determinism.repeated_grading` | determinism | PASS | info | All 5 sampled artifact(s) graded identically across their repeats. |
| `isolation.hidden_test_readability` | isolation_limitation | UNVERIFIABLE | high | CONFIRMED: code under grading can read the hidden test source during the hidden-suite run (the probe successfully detected and read the hidden test file from its own cwd). This is a known, deliberate limitation of the current trusted-local LocalSandbox threat model, not a defect in this task specifically — real untrusted-agent isolation (e.g. a network-disabled, filesystem-scoped DockerSandbox) is out of scope for this engine (mission §14/§25) and is tracked as a repo-wide 'deliberately still open' item. |

## Controls

| Name | Kind | Expected | Verdict | Status | Notes |
|---|---|---|---|---|---|
| `missing_xc_substitution` | known_bad | reject | rejected_by_hidden_test | PASS | verdict=rejected_by_hidden_test; failing_hidden_tests=['test_xc', 'test_mcmxciv'] |
| `off_by_one_comparison` | known_bad | reject | rejected_by_hidden_test | PASS | verdict=rejected_by_hidden_test; failing_hidden_tests=['test_iii', 'test_lviii'] |
| `transposed_pair_typo` | known_bad | reject | rejected_by_hidden_test | PASS | verdict=rejected_by_hidden_test; failing_hidden_tests=['test_ix', 'test_cm'] |
| `forward_lookahead` | alternative | accept | accepted | PASS | verdict=accepted |

## Mutation analysis

- Generated: 27
- Unsupported (base file failed the unparse round-trip self-check): 0
- Declared equivalent: 0
- Intercepted by regression/scope gate (never reached the hidden suite): 10
- Killed by the hidden suite: 16
- **Survived: 1**

Survived mutants (review whether the task contract actually promises to reject each):

| File | Line | Family | Description |
|---|---|---|---|
| `romankit/parse.py` | 20 | change_constant | change_constant_increment: 0 (0 -> 1) |

## Findings

- **[HIGH] A `_pytest/` package directory is not flagged as a protected-path violation, though grading runs pytest with the cleanroom at sys.path[0].** (`protected_paths.pytest_shadow_package`)
  Injecting 'romankit/_pytest/__init__.py' was NOT flagged as touching a protected path. ALWAYS_PROTECTED_BASENAMES matches basenames, not directory names, so a submission-created `_pytest/` package shadowing the real `_pytest` internals package is currently only stopped by this task's editable_paths allow-list (when configured), not by a structural guarantee. See docs/agents/ORACLE.md for why this is reported rather than silently fixed here.

## Limitations

- Grading executes submitted/mutated code via LocalSandbox, which provides per-run workspace isolation and timeouts but NOT untrusted-agent security isolation (runner/afa_runner/sandbox.py's own module docstring). Every check in this report assumes the code being graded is trying to game the SCORE, not attack the HOST — see isolation.hidden_test_readability for a concrete, always-present consequence of that assumption.
- Hidden-test readability during grading could not be ruled out (see the isolation.hidden_test_readability check) — this finding is deliberately excluded from the status precedence (afa_integrity.health) because it is a constant, documented property of the current LocalSandbox threat model, not something this specific task can fix.
- Mutation equivalence is undecidable in general; a surviving mutant is reported as-is unless explicitly declared equivalent in tasks/<id>/integrity/integrity.json. A mutation kill rate is never treated as a correctness probability (mission §16).

## Provenance

- `task_id`: fix-roman-numerals
- `task_version`: 1.0.0
- `task_json_hash`: sha256:53a083fcf62627e646cfc28d25f6ff8ac4442d013eb9e66bfcf32f1218d1972a
- `snapshot_hash`: sha256:1577fe79ffc2235cb2ca344714a40752fe4a4de60453bfe1ed0d3a54cb570f3b
- `reference_hash`: sha256:bee752956f50d4cbde2c993197664bad69b6f5d4c1f8f800ad420785f145092c
- `grading_hash`: sha256:757b073362f83dec7c6ee10db949fedc68ca0eb07c0e76bfd11fc23ec5bd5fe0
- `controls_hash`: sha256:1e2e2b9af047d6e6acf472110d4461b0f3df86a5e334696d3ab1445904ecaeb8
- `engine_version`: 0.1.0
- `afa_kernel_version`: 0.1.0
- `afa_runner_version`: 0.2.0
- `python_version`: 3.13.2
- `platform`: macOS-26.3-arm64-arm-64bit-Mach-O
