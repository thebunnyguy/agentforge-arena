# AgentForge Benchmark Integrity Report

**Task**: `async-first-success`  
**Version**: `1.0.1`  
**Mode**: `full`  
**Engine version**: `0.1.0` (schema `1.0.0`)  
**Timestamp**: 2026-09-17T20:41:58.126993+00:00  
**Duration**: 96611 ms

## Status: NEEDS_REVIEW

**Reason**: mutation.generic_ast_mutants: 3/21 relevant mutant(s) survived (kill_rate=0.86 over 21 relevant of 21 generated). A surviving mutant is not automatic proof of a broken oracle — review whether each represents behavior the task contract actually promises to reject (mission §8); see evidence.survived for exact locations.

## Checks

| Check | Category | Status | Severity | Description |
|---|---|---|---|---|
| `reference.solution_validation` | reference | PASS | info | Reference solution scores (1.0, True) identically across 5 repeated grades. |
| `noop.unmodified_baseline` | negative_control | PASS | info | The unmodified snapshot passes regression, fails the hidden suite (T_hidden=0.000), and scores 0.0 / functional_pass=False, as required. |
| `hidden_import_closure.gate7` | isolation | PASS | info | Task uses an editable_paths allow-list, which makes gate 7 (no editable, unprotected oracle-helper import) hold structurally: any local module the hidden/regression suites import that isn't the editable code-under-test is already unreachable by any diff without failing the scope gate. |
| `protected_paths.tampering_probes` | isolation | PASS | info | All 11 protected-path/allow-list probes correctly flagged a scope violation. One known, documented gap (a `_pytest/` shadow package) was also probed and confirmed — see findings. |
| `controls.declared_controls` | controls | SKIPPED | medium | No known-bad solutions, semantic mutants, or alternative solutions declared for this task (tasks/<id>/integrity/controls/). The engine has no task-specific evidence beyond the reference/no-op checks. |
| `mutation.generic_ast_mutants` | mutation | WARNING | medium | 3/21 relevant mutant(s) survived (kill_rate=0.86 over 21 relevant of 21 generated). A surviving mutant is not automatic proof of a broken oracle — review whether each represents behavior the task contract actually promises to reject (mission §8); see evidence.survived for exact locations. |
| `determinism.repeated_grading` | determinism | PASS | info | All 1 sampled artifact(s) graded identically across their repeats. |
| `isolation.hidden_test_readability` | isolation_limitation | UNVERIFIABLE | high | CONFIRMED: code under grading can read the hidden test source during the hidden-suite run (the probe successfully detected and read the hidden test file from its own cwd). This is a known, deliberate limitation of the current trusted-local LocalSandbox threat model, not a defect in this task specifically — real untrusted-agent isolation (e.g. a network-disabled, filesystem-scoped DockerSandbox) is out of scope for this engine (mission §14/§25) and is tracked as a repo-wide 'deliberately still open' item. |

## Mutation analysis

- Generated: 21
- Unsupported (base file failed the unparse round-trip self-check): 0
- Declared equivalent: 0
- Killed: 18
- **Survived: 3**

Survived mutants (review whether the task contract actually promises to reject each):

| File | Line | Family | Description |
|---|---|---|---|
| `afirst/first.py` | 14 | remove_branch | remove_branch_force_false: if not factories:
        raise ValueError("make_coros must be non-empty") (if-condition forced to False (branch never taken)) |
| `afirst/first.py` | 14 | remove_validation | remove_validation: if not factories:
        raise ValueError("make_coros must be non-empty") (if-guard's raise removed (body -> pass)) |
| `afirst/first.py` | 40 | drop_exception_handling | drop_exception_handling: except BaseException:
        await _cancel_all()
        raise (except-handler body replaced with pass (error swallowed silently)) |

## Findings

- **[HIGH] A `_pytest/` package directory is not flagged as a protected-path violation, though grading runs pytest with the cleanroom at sys.path[0].** (`protected_paths.pytest_shadow_package`)
  Injecting 'afirst/_pytest/__init__.py' was NOT flagged as touching a protected path. ALWAYS_PROTECTED_BASENAMES matches basenames, not directory names, so a submission-created `_pytest/` package shadowing the real `_pytest` internals package is currently only stopped by this task's editable_paths allow-list (when configured), not by a structural guarantee. See docs/agents/ORACLE.md for why this is reported rather than silently fixed here.

## Limitations

- Grading executes submitted/mutated code via LocalSandbox, which provides per-run workspace isolation and timeouts but NOT untrusted-agent security isolation (runner/afa_runner/sandbox.py's own module docstring). Every check in this report assumes the code being graded is trying to game the SCORE, not attack the HOST — see isolation.hidden_test_readability for a concrete, always-present consequence of that assumption.
- No known-bad solutions, semantic mutants, or alternative solutions declared for this task (tasks/<id>/integrity/controls/) — absence of evidence here, not evidence of absence.
- Hidden-test readability during grading could not be ruled out (see the isolation.hidden_test_readability check) — this finding is deliberately excluded from the status precedence (afa_integrity.health) because it is a constant, documented property of the current LocalSandbox threat model, not something this specific task can fix.
- Mutation equivalence is undecidable in general; a surviving mutant is reported as-is unless explicitly declared equivalent in tasks/<id>/integrity/integrity.json. A mutation kill rate is never treated as a correctness probability (mission §16).

## Provenance

- `task_id`: async-first-success
- `task_version`: 1.0.1
- `task_json_hash`: sha256:413fb7d7eedddc22a56a2f2233f26c8ab61229b08c5945f348240e00b0f1ee66
- `snapshot_hash`: sha256:9778f900bfaaf8de42a986eaf3dd26998e58e2d6df6f3908f140bca21662b639
- `reference_hash`: sha256:9bd72086e237be086e1f97840f451cb1cfaa26043d90ec37df77355bae965fb0
- `grading_hash`: sha256:c37474eae0864d3197757a150f3d3937e3a7f592dabb961a9f823b6310e0ce09
- `controls_hash`: None
- `engine_version`: 0.1.0
- `afa_kernel_version`: 0.1.0
- `afa_runner_version`: 0.2.0
- `python_version`: 3.13.2
- `platform`: macOS-26.3-arm64-arm-64bit-Mach-O
