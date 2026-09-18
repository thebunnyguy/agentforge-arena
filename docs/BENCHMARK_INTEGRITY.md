# AgentForge Arena — Benchmark Integrity Engine

> AgentForge must never be more confident in an agent score than it is in the
> benchmark that produced that score.

This document describes `integrity/afa_integrity`, AgentForge Arena's
Benchmark Integrity Engine. It answers a different question than
`afa_kernel`/`afa_runner`: not "how did this agent score," but "can we trust
the benchmark that produced that score." For the engineering log — design
decisions, rejected approaches, traps found — see
[`docs/agents/ORACLE.md`](agents/ORACLE.md). For the underlying scoring model
this engine validates, see
[`docs/EVALUATION_FRAMEWORK.md`](EVALUATION_FRAMEWORK.md).

## Why this exists

`docs/EVALUATION_FRAMEWORK.md` §8.2 documents seven "activation gates" a task
must pass before it's trusted, and prior audits (`audit/`, `codex-audit/`,
`docs/FAILURE_INSPECTION.md`) found real, shipped defects that a benchmark
that only checks "the reference scores 1.0" would have missed entirely — a
reference that itself violated its task's security contract
(`validate-redirect-url`), a hidden suite that rewarded a parser with wrong
associativity (`expression-evaluator`), and confirmed false passes on stored
runs. Only three of those seven gates had any executable implementation
before this engine (`runner/afa_runner/pipeline.py:validate_task`, covering
gates 1–3, pytest-only, assert-and-raise). This engine makes the rest
executable and turns "pass/fail" into preserved evidence.

## Architecture

```
              afa_kernel  (scoring math)
                   ^
              afa_runner  (task loading, diffing, clean-room grading)
                   ^
            afa_integrity  (THIS — benchmark integrity)
```

`afa_integrity` never re-derives scoring or grading logic. Every check
bottoms out in the same three calls every real run uses:
`capture_diff` → `grade` → `score_run`. The one new primitive is the
**overlay**: "these files replace/add onto the pristine snapshot" (exactly
what `tasks/<id>/reference/` already is). A reference solution, a no-op, a
known-bad control, a semantic mutant, an alternative solution, and a
generic AST mutant are all *the same operation* — overlay, then grade, then
score — with a different source of files:

- `afa_runner.pipeline.overlay_diff(task, dir)` — directory-based overlay
  (generalized out of what was previously `_reference_diff`'s private body).
- `afa_integrity.overlay.overlay_files_diff(task, files_dict)` — in-memory
  overlay, for mutation testing (skips a redundant tempdir round-trip per
  mutant).
- `afa_integrity.overlay.classify_verdict(report, score)` — the ONE place
  that turns a graded overlay into a shared vocabulary: `accepted`,
  `rejected_by_hidden_test`, `rejected_by_regression_gate`,
  `rejected_by_scope_gate`, `rejected_by_timeout_or_error`. Only
  `rejected_by_hidden_test` means the hidden suite actually caught something
  — a control rejected by the scope or regression gate is a control-authoring
  bug, not oracle evidence (see "scope-gate masking" in the journal).

### Domain model (`afa_integrity/model.py`)

- `IntegrityCheckResult` — one check's `status` (`PASS`/`FAIL`/`WARNING`/
  `SKIPPED`/`UNVERIFIABLE`/`ERROR` — never collapsed to a boolean),
  `severity`, `description`, and JSON-serializable `evidence`.
- `MutationRecord` / `ControlResult` — one graded mutant/control, its
  `Verdict`, and whether it matched what it declared.
- `Finding` — a specific, actionable observation, independent of which check
  produced it (used for cross-cutting things like the `_pytest/` shadow-
  package gap).
- `BenchmarkIntegrityReport` — the full bundle: `checks`, `mutations`,
  `controls`, `findings`, `limitations`, `provenance`, one `status` +
  `reason`.
- `HealthStatus` — `HEALTHY` / `PROVISIONAL` / `NEEDS_REVIEW` / `INVALID` /
  `UNVERIFIABLE`. No fabricated percentage.

## Checks implemented

| Check | File | Framework gate | Semantics |
|---|---|---|---|
| `reference.solution_validation` | `checks/reference.py` | Gate 1 | Overlay the reference, grade it 3× (QUICK) / 5× (FULL), require `(1.0, True)` identically every time. |
| `noop.unmodified_baseline` | `checks/noop.py` | Gates 2–3 | Empty diff must pass regression, fail hidden, score 0. **New**: also computes `T_hidden` on the untouched snapshot and warns at the documented `>= 0.5` ceiling — this number was never computed anywhere in the codebase before. |
| `hidden_import_closure.gate7` | `checks/hidden_import_closure.py` | Gate 7 (never implemented before) | Statically resolves every import in the hidden/regression suites and asks which resolved files are *reachable* by a diff without failing the scope gate — matching `editable_paths` in allow-list mode, or NOT matching `protected_paths` in deny-list mode (an allow-list only rules out imports outside the editable tree, not a helper module living inside it alongside the code under test). PASS only when at most one distinct reachable file exists (unambiguously the code under test); more than one gets flagged for human review. Caught a real case on the first pack run: `refactor-order-validation` imports both `orderkit/__init__.py` and `orderkit/process.py` — traced by hand and confirmed benign (a normal parent-package import in a 3-file refactor task), but correctly surfaced rather than silently passed. |
| `protected_paths.tampering_probes` | `checks/protected_paths.py` | §8.3 anti-cheating | Constructs real adversarial diffs (every protected glob, every always-protected basename, an allow-list-outside probe) via the actual public `capture_diff`. Also probes a known, documented gap (a `_pytest/` shadow package) and reports it as a finding rather than a check failure. |
| `controls.declared_controls` | `checks/controls_check.py` | §7/§9/§10 | Grades every declared control and checks it against its author's `expect`. |
| `mutation.generic_ast_mutants` | `mutation/engine.py` | §8 (never implemented before) | Generic AST mutation testing — see below. |
| `determinism.repeated_grading` | `checks/determinism.py` | §9/§5.3/§11 | Repeat-grades a sample (always the no-op; FULL mode adds every declared control) and flags any variance as `GRADER_NONDETERMINISM`. |
| `isolation.hidden_test_readability` | `checks/isolation.py` | §13/§14 | **Always** `UNVERIFIABLE` under the current `LocalSandbox` — confirmed empirically (a probe that detects it can read the hidden test file from its own cwd during grading) and cited from `grader.py`'s materialize order. Deliberately excluded from the health-status precedence (see below) so this constant, honest limitation doesn't make every report say `UNVERIFIABLE` and stop meaning anything. |

FULL mode runs all of the above; QUICK mode skips mutation testing, the
control-sample determinism check, and the isolation probe (mission §24).

## Mutation design

**Generic (`mutation/operators.py`, `mutation/engine.py`)**: a small stdlib
`ast` layer, not mutmut/cosmic-ray — see the journal for why (mutmut can't
compose with the clean-room `grade()` boundary without forking its logic,
and would be the first third-party dependency in an otherwise stdlib-only
stack). 12 operator families (invert comparison, boundary operator, boolean
condition/literal swap, constant increment/zero, remove validation, drop
exception handling, force-branch true/false, return-constant,
delete-state-update, drop-not, break/continue swap), one AST node mutated
per mutant. Only files matching `editable_paths` are mutated. Before
trusting any mutant from a file, the engine grades that file's own
`ast.unparse(ast.parse(source))` round-trip and marks the whole file
`unsupported` if reformatting alone changed the score.

**Semantic (task-specific, `tasks/<id>/integrity/controls/semantic_mutants/`)**:
an overlay directory + `control.json`, same shape as a known-bad control,
authored by a task author (or, for the initial pack pass, by ORACLE — see
below) to encode a near-miss specific to that task's contract (e.g. for
`fix-path-traversal`: containment enforced via naive `startswith(base)`
without a trailing separator, reintroducing a prefix-collision bug the real
hidden suite already tests for).

Reports never reduce mutation results to a single score: counts are
generated / unsupported / declared-equivalent / killed-by-hidden /
killed-by-regression / killed-by-scope / killed-by-error-or-timeout /
survived, plus a `kill_rate` computed only over *relevant* mutants — shown
alongside the counts, never presented alone (mission §16). Equivalence is
never auto-detected (undecidable in general); a task author declares one in
`tasks/<id>/integrity/integrity.json` by (file, diff hash).

## Task-level integrity conventions

```
tasks/<id>/integrity/
    integrity.json                          # optional: mutation config, equivalent-mutant allowlist
    controls/
        known_bad/<name>/       control.json + overlay files, expect:"reject"
        semantic_mutants/<name>/control.json + overlay files, expect:"reject"
        alternatives/<name>/    control.json + overlay files, expect:"accept"
```

Purely additive to a task — nothing here changes `task.json`, `snapshot/`,
`grading/`, or `reference/`, so no task version bump is implied by adding
controls. A task author adds a control by adding a directory; the engine
never needs to change.

## Health status

A pure, independently-tested precedence function
(`afa_integrity/health.py`): `INVALID` > `NEEDS_REVIEW` > `UNVERIFIABLE` >
`PROVISIONAL` > `HEALTHY`. `INVALID` requires a genuine defect (reference
doesn't score 1.0, no-op passes, a known-bad control is accepted, grading is
nondeterministic, a protected-path probe fails). `NEEDS_REVIEW` covers
things a human should look at but that aren't proof of a broken oracle
(a semantic mutant survived, an alternative was rejected, mutation testing
found a survivor, a control was rejected for the wrong reason).
`PROVISIONAL` means less evidence was collected than the engine is capable
of (QUICK mode, or no controls declared at all) — not that anything failed.

## CLI

No CLI framework exists anywhere else in this repo (dev tooling is a
standalone script under `examples/` with `sys.path` injection + positional
argv). This engine needs real flags (`--quick`/`--full`/`--json`/
`--markdown`), so `afa_integrity/cli.py` uses stdlib `argparse` (still zero
third-party dependencies), exposed two ways:

```bash
python -m afa_integrity audit fix-binary-search --full
python -m afa_integrity audit --all --quick --json-dir reports/integrity

python examples/benchmark_audit.py audit fix-path-traversal --full --markdown reports/integrity/fix-path-traversal.md
```

Exit codes: `0` (healthy/provisional), `1` (needs_review/unverifiable),
`2` (invalid) — usable as a CI gate.

## Performance

QUICK ≈ 10–20 grade calls per task (a few seconds to ~10s locally). FULL
adds generic mutation testing (bounded to 60 mutants per task by default,
each capped at a 20s grading timeout so one runaway-loop mutant can't
dominate an audit), a determinism sample per declared control, and the
isolation probe — a few minutes per task on this machine. `afa_integrity.pack`
runs the pack across a `ThreadPoolExecutor` (grading is subprocess-bound —
each call shells out to `pytest` and waits — so thread parallelism across
*tasks* is safe with no shared mutable state).

## Limitations (always stated, never silently assumed away)

- **No untrusted-agent isolation.** `LocalSandbox` provides per-run
  workspace isolation and timeouts, not security isolation. Every check
  here assumes the code being graded is trying to game the *score*, not
  attack the *host*. The isolation probe makes the sharpest consequence of
  this concrete (hidden-test source is readable by the code being graded
  during the hidden-suite run) and is intentionally excluded from the
  status precedence rather than making every report `UNVERIFIABLE`.
- **Mutation equivalence is undecidable in general.** Survived mutants are
  reported as-is unless a task author declares one equivalent.
- **A surviving mutant is not proof of a broken oracle**, and a 100% kill
  rate is not a correctness certificate. Both directions of overclaiming are
  deliberately avoided in the report language.
- **Import-closure analysis (gate 7) cannot distinguish intent** (code-under-
  test vs. an oracle helper) from static imports alone, in EITHER scope
  regime — an allow-list only narrows which imports are reachable at all
  (those matching `editable_paths`), it does not by itself prove a reachable
  import is safe. The check surfaces candidates for human review (more than
  one distinct reachable file) rather than asserting a verdict; see
  `refactor-order-validation` above for a real, benign example.
- **No hardcoding/literal-overlap detector (mission §13, framework §8.3).**
  The framework documents an AST/tree-sitter literal-overlap heuristic
  ("`overlap > 0.5 AND count >= 3`") for detecting a submission that special-
  cases hidden-test inputs, explicitly gated as "reviewed by a human, never
  an automatic S = 0" because of known false positives. This engine does not
  implement it — a general literal-overlap heuristic is brittle exactly as
  documented, and the known-bad/semantic-mutant control mechanism already
  covers "returns expected constants" and "special-cases hidden inputs" as
  concrete, checkable behaviors instead of a fuzzy static signal. It does
  NOT cover every form of gaming: `expression-evaluator`'s
  `eval_based_implementation` semantic mutant is the concrete example this
  pack run found — a purely behavioral hidden suite has no way to enforce a
  "don't use `eval()`" constraint the task prose states in English, because
  `eval()` produces byte-identical results to a correct parser on every
  benign input the suite happens to exercise.
- **A `_pytest/` shadow-package gap is reported, not silently fixed** — see
  the journal for why (it edges into the sandboxing redesign this engine's
  mission explicitly excludes).
