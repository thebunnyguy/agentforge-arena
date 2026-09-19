# ORACLE journal — Benchmark Integrity Engine

ORACLE is an independent workstream on the `oracle` branch, building AgentForge's
first Benchmark Integrity Engine: automated evidence that a task's oracle
(reference solution + hidden tests + grader) can be trusted, separate from
whatever a run scored. This file is ORACLE's own engineering log. It does not
coordinate with, read, or edit any ATLAS branch or journal.

## 2026-09-18 — Orientation

Surveyed the existing system (docs/EVALUATION_FRAMEWORK.md +
docs/evaluation-framework/*, kernel/afa_kernel, runner/afa_runner, all 24 tasks,
DEVLOG.md, audit/, codex-audit/, docs/FAILURE_INSPECTION.md) with six parallel
research agents before writing any code. Key findings that shaped the design:

- **`runner/afa_runner/pipeline.py:validate_task()` already implements the
  framework's §8 activation gates 1–3** (reference-solution 3x-determinism
  check, empty-diff negative control). It is pytest-only: it raises
  `AssertionError` on the first violation and discards the evidence otherwise.
  It is a **subset** of what this engine does, not something to duplicate —
  the engine calls the same underlying primitives (`capture_diff`, `grade`,
  `score_run`) that `validate_task` calls, so `validate_task` and the engine's
  `reference`/`noop` checks can never silently diverge in what "correct"
  means.
- **Gates 4 (mutation adequacy) and 7 (hidden-test import closure) are
  documented in `08-benchmark-design.md` but have zero implementation
  anywhere.** These are the two biggest "documented idea → executable check"
  gaps this engine closes.
- **Known-bad negative controls (revert diff, deliberately-wrong patch) are
  asserted as a v0.1 self-validation requirement in
  `11-roadmap-and-recommendation.md:93` but have no corresponding mechanism.**
  Nothing in `tasks/` has ever declared one.
- **The diff model is whole-file, not unified patches**
  (`runner/afa_runner/diffing.py`: `Diff.changed = {relpath: text}`,
  `capture_diff`/`apply_diff`). The mission brief's sketch of
  `integrity/controls/<task>/mutant_01.patch` doesn't fit this codebase —
  patch files would need a patch-parser that doesn't exist anywhere in this
  stdlib-only project. Controls and mutants are instead **overlay directories**
  that mirror `reference/`'s existing convention: a tree of files that
  replaces/adds onto the pristine snapshot, captured via the same
  `capture_diff` used for everything else.
- **Every real task in the pack (`grep -L editable_paths tasks/*/task.json` →
  no hits) already ships an `editable_paths` allow-list.** The stronger
  allow-list scope defense is universal in practice, not merely a fallback —
  useful context for how much weight the protected-path checks should give a
  hypothetical missing allow-list.
- **A real, undocumented isolation gap**: `ALWAYS_PROTECTED_BASENAMES` in
  `diffing.py` protects `conftest.py`, `sitecustomize.py`, `*.pth`, etc., but
  not a root-level `pytest.py` (or a package literally named `_pytest/`)
  shadowing the real `pytest` module — since grading runs
  `sys.executable -m pytest` with `cwd=cleanroom`, that shadow would sit at
  `sys.path[0]`. Currently the only thing stopping an agent from exploiting
  this is that every task happens to ship an `editable_paths` allow-list that
  excludes it — not a structural guarantee. See "Runner touches" below for the
  narrow fix.
- **Hidden tests are readable by a submission's own code during grading.**
  `grader.py` materializes `grading/test_hidden.py` into the cleanroom
  *before* running the hidden suite, in the same directory the submission's
  code executes from. "Never mounted in the agent workspace" (true, and it's
  what stops an agent from reading it *while working*) is a different claim
  from "unreadable to the code being graded" (false). This is a real,
  by-construction limitation of the current trusted-local threat model, not a
  bug to silently fix here (that's the Docker-sandbox work this mission
  explicitly excludes) — the engine reports it as an `UNVERIFIABLE` isolation
  finding with the grader.py line evidence, and does not let it drag every
  task's overall status down to `UNVERIFIABLE` (that would make the status
  useless — see Design decisions).
- **No CLI framework exists anywhere in the repo** (no click/typer/argparse
  app, no console_scripts). Dev tooling convention is a standalone script
  under `examples/` doing `sys.path[:0] = [".../kernel", ".../runner"]` then
  positional-argv parsing. The engine's CLI follows this: a real `argparse`
  subcommand app lives in `afa_integrity.cli` (needed for `--quick/--full/
  --json/--markdown` flags that positional argv can't express cleanly), with
  a thin `examples/benchmark_audit.py` launcher matching house style.
- **House report convention**: `audit/audit-N/{AUDIT_REPORT.md,
  AUDIT_SCORECARD.md, AUDIT_FINDINGS.json}` — JSON schema + Markdown
  narrative, versioned by folder. The integrity engine's JSON+Markdown report
  pair follows this pattern rather than inventing a new one.

Consulted an independent advisor pass before writing code; its architecture
review is folded into the design decisions below (including several traps
worth naming explicitly since they are exactly the kind of mistake a "does the
validator validate itself" system cannot afford).

## Design decisions

1. **Package**: `integrity/afa_integrity/`, sibling to `kernel/afa_kernel` and
   `runner/afa_runner`, stdlib-only, depends on both (never the reverse).
   Added to root `pyproject.toml`'s `pythonpath`/`testpaths` — the only
   "shared file" touch of this kind, and it's purely additive.
2. **Overlay is the one primitive everything is built from.** `capture_diff`
   (existing, public) turns "these files replace/add onto the snapshot" into
   a `Diff`; `grade` + `score_run` (existing, public) turn a `Diff` into a
   score. Reference-solution validation, no-op checks, known-bad controls,
   semantic mutants, alternative solutions, and generic AST mutants are all
   the *same* overlay-then-grade-then-score call with a different source of
   files. Two small constructors: `overlay_diff(task, dir)` (generalized out
   of `pipeline._reference_diff`, now in `runner/afa_runner/pipeline.py` and
   reused by both `validate_task` and the engine) for directory-based
   overlays, and `afa_integrity.overlay.overlay_files_diff(task, files_dict)`
   for the in-memory case (AST mutants), which skips a redundant tempdir
   round-trip per mutant.
3. **Controls live at `tasks/<id>/integrity/controls/<kind>/<name>/`**
   (`kind` ∈ `known_bad`, `semantic_mutants`, `alternatives`), each an overlay
   directory plus a `control.json` sidecar (name, description, expected
   verdict). This mirrors the existing `reference/` convention exactly, keeps
   a task's integrity fixtures next to the task (discoverable by task
   authors, per mission §7/§10's "without modifying the central engine"), and
   never touches an existing task's `task.json`, snapshot, grading, or
   reference — purely additive new files, so there is nothing here for a
   version bump to react to. `tasks/<id>/integrity/integrity.json` (optional)
   holds a declared-equivalent-mutant allowlist and per-task mutation config
   (timeout override, excluded files).
4. **Verdict vocabulary, shared across mutants and controls**: grading any
   overlay produces one of `accepted`, `rejected_by_hidden_test`,
   `rejected_by_regression_gate`, `rejected_by_scope_gate`,
   `rejected_by_timeout_or_error`. This single vocabulary is what lets the
   engine tell "the hidden suite genuinely caught this" apart from "this
   control was rejected for an unrelated reason" — see trap 4 below.
5. **Mutation engine is a small stdlib `ast` layer, not mutmut/cosmic-ray.**
   mutmut drives pytest itself and mutates files in place; it cannot compose
   with the clean-room `grade()` boundary (a fresh tempdir copy per grade,
   diff-based application) without forking that logic, and it would be the
   first third-party dependency in an otherwise stdlib-only kernel+runner+
   integrity stack. One AST node mutated per mutant (classic mutation-testing
   practice), `ast.unparse` back to source, wrapped as a `Diff` via
   `overlay_files_diff`. Only files matching the task's `editable_paths` are
   mutated (mutating outside it can't teach us anything about hidden-test
   quality — it would just fail the scope gate).
6. **Status is a pure, independently-tested precedence function**
   (`afa_integrity.health`), not scattered if/else across checks. See its
   docstring for the exact precedence table (`INVALID` >
   `NEEDS_REVIEW` > `UNVERIFIABLE` > `PROVISIONAL` > `HEALTHY`).
7. **CLI**: `python -m afa_integrity audit <task_id>` /
   `python -m afa_integrity audit --all`, `--quick`/`--full`, `--json`,
   `--markdown`, `--mutation` (force mutation analysis even in quick mode). A
   thin `examples/benchmark_audit.py` wraps it in house style so it runs
   without an editable install.

## Traps found and closed (credit: advisor pass)

- **Determinism fingerprint must exclude `SuiteOutcome.notes` /
  `GradeReport.notes`** (they carry raw pytest stdout, which is never
  byte-identical across runs — timings, temp paths). The fingerprint hashes
  `(gates, hidden test tuples, regression test tuples, final_score,
  functional_pass)` only.
- **Mutant timeouts.** A loop-condition mutant on e.g. `fix-binary-search` or
  any `async-*` task can infinite-loop. Every mutation/control grade uses a
  capped `timeout_s` via `dataclasses.replace(task, timeout_s=...)` (`Task` is
  frozen; `replace` needs no grader change), not the task's own (up to 120s)
  timeout — otherwise one runaway mutant can dominate a whole audit's wall
  clock.
- **`ast.unparse` reformats the whole file.** Before trusting any mutant
  generated from a file, the engine first grades the *unmutated,
  round-tripped* (`unparse(parse(source))`) reference overlay; if that
  doesn't still score `(1.0, True)`, every mutant for that file is marked
  `unsupported` with the reason recorded, instead of silently reporting
  mutation results built on a reformatting-induced behavior change.
- **Scope-gate masking.** A known-bad control or mutant that happens to touch
  a file outside `editable_paths` gets `gate_product=0` for a reason that has
  nothing to do with hidden-test quality. The verdict vocabulary (decision 4)
  makes this explicit: only `rejected_by_hidden_test` counts as the hidden
  suite doing its job. A known-bad control that comes back
  `rejected_by_regression_gate` or `rejected_by_scope_gate` is flagged as a
  control-authoring **error**, not scored as a pass.
- **Isolation UNVERIFIABLE must not become contagious.** The isolation-probe
  check (hidden-test readability during grading) is real and — as expected
  from reading `grader.py`'s materialize order — always comes back positive
  under the current `LocalSandbox`. If that flowed into the same status
  precedence as every other check, every task in the pack would be
  `UNVERIFIABLE` and the status field would carry no information. It is
  reported as a limitation/finding on every report, explicitly excluded from
  the health-status precedence function.
- **Equivalent mutants are not auto-detected** (equivalence is undecidable in
  general; this engine doesn't pretend otherwise). A survived mutant is
  reported as `survived` with full location/family evidence unless a task
  author has explicitly declared it equivalent in
  `tasks/<id>/integrity/integrity.json` (keyed by file + a hash of the
  mutant's normalized diff, so a re-run doesn't need to be re-triaged by
  hand).
- **No mutation-score-as-correctness-probability.** Reports always show raw
  counts (generated / unsupported / declared-equivalent / killed-by-hidden /
  killed-by-regression / killed-by-error-or-timeout / survived) alongside any
  rate, per mission §16.

## Runner touches (small, isolated, documented here per the non-overlap rule)

Both are additive, behavior-preserving for every existing task, and unrelated
to Phase-0/evaluation-job/product surfaces ATLAS owns:

1. `runner/afa_runner/pipeline.py`: extracted `overlay_diff(task, overlay_root)`
   out of the body of `_reference_diff`; `_reference_diff` now calls it. No
   behavior change — `validate_task` and every existing test that exercises it
   are unaffected. Re-exported from `runner/afa_runner/__init__.py`.
2. `runner/afa_runner/diffing.py`: added `"pytest.py"` to
   `ALWAYS_PROTECTED_BASENAMES`. Finding: grading invokes
   `sys.executable -m pytest` with `cwd=cleanroom`, which puts the cleanroom
   at `sys.path[0]`; a submission-introduced `pytest.py` there would shadow
   the real `pytest` module for the grading interpreter, exactly the class of
   attack `conftest.py`/`*.pth` are already blocked for. Every task in the
   current pack happens to have an `editable_paths` allow-list that excludes
   this incidentally, so no currently-scored run was ever affected — this
   closes the gap structurally instead of leaving it to accident. **Not**
   fixed: a package directory literally named `_pytest/` shadowing the real
   `_pytest` package. That needs directory-name matching, not basename
   matching, and edges toward the sandboxing redesign this mission explicitly
   excludes (§14/§25) — recorded as a limitation instead.

## 2026-09-17/18 — Building the engine: validated end to end

Built `integrity/afa_integrity/` incrementally, smoke-testing against real
tasks after each layer rather than writing the whole thing before running
anything:

- QUICK audit of `fix-binary-search`: ~9.5s, correctly PROVISIONAL (no
  controls declared yet), correctly surfaced the `_pytest/` shadow-package
  gap as a finding.
- FULL audit of `fix-binary-search` (before any controls existed): 15/15
  generic AST mutants killed, isolation probe confirmed the hidden-test
  readability limitation exactly as predicted from reading `grader.py`.
- Caught two real bugs against my own fixtures during this process (see
  "Bugs found in ORACLE's own first draft" below) — the fixtures did their
  job.

### Bugs found in ORACLE's own first draft (before any commit)

1. **Control overlays leaked their own `control.json` sidecar as a stray
   file.** `Control.overlay_dir` contains both the spec and the overlay
   files; the first version of `checks/controls_check.py` pointed
   `afa_runner.pipeline.overlay_diff` straight at `overlay_dir`, which
   walks *everything* under it — including `control.json` itself, applied
   as a new file at the snapshot root. Since every real task uses an
   `editable_paths` allow-list, this always failed the scope gate,
   surfacing as every control coming back `rejected_by_scope_gate`
   ("control-authoring error") on the very first fixture test. Fixed by
   giving `Control.overlay_files()` (`controls.py`) a filter that excludes
   `control.json`, used everywhere a control is graded
   (`checks/controls_check.py`, `audit.py`'s determinism sampling).
2. **`provenance.py` computed and discarded a full-tree hash for no
   reason**: `_hash_tree(task.task_dir) and _hash_single_file(...)` hashed
   the entire task directory (snapshot + reference + grading + controls,
   redundant with the other explicit hashes already computed) purely to
   use its truthy result as a gate before computing the value actually
   wanted. Fixed to call `_hash_single_file` directly.
3. **The `healthy` fixture wasn't actually healthy on first attempt**: an
   off-by-one bug that only misclassifies a single boundary value (`n==10`)
   leaves most hidden tests passing on the unmodified snapshot (3/4,
   `T_hidden=0.75`), which is exactly what the new `noop` check's
   documented-`>=0.5`-ceiling warning is supposed to catch — it caught it
   immediately, on my own fixture. Fixed the fixture, not the check, by
   weighting the boundary test in `task.json`'s `hidden.weights` (the real
   per-test weight mechanism — confirmed `scoring_recipe.hidden_weights` is
   vestigial and unread anywhere in `runner`, matching what the survey
   found).
4. **`pytest`'s own collection swept up all 7 fixture task directories.**
   Root `pyproject.toml`'s `testpaths` included `"integrity/tests"`;
   fixtures originally lived at `integrity/tests/fixtures/`, so pytest's
   default collection walked into every fixture's
   `grading/test_hidden.py` / `snapshot/tests_visible/test_visible.py` and
   tried to import 7 different, colliding `pkg` packages directly —
   `ModuleNotFoundError`/`ImportError` on a full `python3 -m pytest` run
   from repo root (never seen when running `integrity/tests/` alone, only
   with the full suite). Moved fixtures to `integrity/fixtures/`, a
   *sibling* of `integrity/tests/`, matching exactly why the real `tasks/`
   directory is not itself listed in `testpaths`.
5. **A second, subtler collision from the same root cause**: adding
   `"integrity"` to root `pyproject.toml`'s `pythonpath` put
   `integrity/tests/` on `sys.path` directly (the same way `kernel/tests`
   and `runner/tests` are); since `integrity/tests/` had an `__init__.py`
   (unlike `kernel/tests`/`runner/tests`, which don't), it became
   importable as bare `tests` — the exact same top-level name as the real
   root-level `tests/` package (also on `sys.path` via pythonpath `"."`
   + its own `__init__.py`). `python3 -m pytest` from repo root failed
   collecting `tests/test_api_readonly.py` and `tests/test_jobs_api.py`
   with `ModuleNotFoundError: No module named 'tests.test_api_readonly'`
   — Python had already bound `tests` to the *other* package. Fixed by
   removing `integrity/tests/__init__.py`, matching the established
   no-`__init__.py` convention for `kernel/tests`/`runner/tests` (only
   `afa_api/tests` has one, and `afa_api` is never added to `pythonpath`
   as a bare directory the way `kernel`/`runner`/`integrity` are, so it
   never collides).

All caught before the first commit, by actually running things rather than
only reading code — validates the mission's own emphasis on "validate the
validator" (§22/§23): a benchmark-integrity engine that only compiles is
worth nothing.

## 2026-09-18 — Pack-level results

Ran the full pipeline against the real 24-task pack: QUICK across all 24
(`integrity/pack-audit/quick-summary.{json,md}`), FULL across all 24 with
generic mutation testing (`integrity/pack-audit/full-summary.{json,md}`),
and authored controls (known-bad + task-specific semantic mutants for the 5
security-relevant tasks + one alternative each) for 10 tasks via 10 parallel
agents, each given only that one task's real code and required to
independently verify their own controls against the real engine before
reporting back (`integrity/afa_integrity` mode, not the agent's self-report
alone — I re-ran every control myself afterward; see "Findings" below).

### Findings — confirmed genuine, not authoring mistakes

Every one of these was independently re-verified by reading the actual
hidden test file and tracing the buggy implementation against it by hand
before treating it as a real finding, not just trusting the authoring
agent's or the engine's say-so (mission §23, "use independent evidence
paths"):

1. **`sanitize-filename` — INVALID.** A known-bad control that adds an
   undocumented extra restriction (only `[A-Za-z0-9._-]` characters
   allowed) is `ACCEPTED`. The task spec (per the reference's own
   docstring) requires returning any name unchanged unless it matches one
   of 5 specific unsafe conditions — this over-rejects valid names like
   `"my file.txt"` or `"résumé.pdf"`. Confirmed: every existing "valid
   name" hidden test (`test_plain_name_unchanged`, `test_inner_dots_allowed`,
   etc.) only ever uses letters, digits, and dots — nothing exercises a
   space, non-ASCII character, or ordinary punctuation, so the
   over-restrictive allowlist never gets exercised by the "must accept"
   side of the suite at all.
2. **`toposort` — INVALID.** A known-bad control that silently drops every
   dependency but the *first* in a multi-dependency list (`deps[0]`
   instead of the full list) is `ACCEPTED` by
   `test_multiple_implicit_dependencies` — the one test whose own docstring
   explicitly calls out this exact bug. Traced by hand: for
   `{"app": ["lib", "core"]}`, dropping the `app -> core` edge still leaves
   `"core"` topologically before `"app"` in the output, because `"core"`
   sorts alphabetically before `"lib"` and both start with in-degree 0 once
   the edge is dropped — the test's assertions hold via the lexicographic
   tiebreak coincidence, not because the (silently dropped) dependency edge
   was ever enforced.
3. **`validate-redirect-url` — INVALID.** A known-bad control using
   substring containment (`allowed_host in hostname`) instead of exact
   equality is `ACCEPTED`. Confirmed by hand-execution: for
   `allowed_host="app.example.com"`, the target
   `"https://app.example.com.evil.com/x"` (a domain fully controlled by an
   attacker) is returned unchanged. No existing hidden test uses a
   look-alike host that merely *contains* the allowed host as a substring
   — only a completely unrelated host (`evil.com`) is tested for rejection.
4. **`fix-list-dedup` — NEEDS_REVIEW** (new: the noop `T_hidden >= 0.5`
   check, never computed anywhere before this engine). The unmodified,
   `set()`-based (order-losing) snapshot scores exactly `T_hidden=0.500` —
   traced by hand: 3 of the 6 hidden tests (`test_empty_list`,
   `test_already_unique_preserved`, and, non-obviously,
   `test_element_appearing_three_or_more_times`, whose three assertions all
   happen to use small ascending integers) pass purely because CPython's
   `set` iteration order for small integers inserted into an empty set
   incidentally comes out ascending — an implementation detail, not a
   property of correctness. This sits *exactly* at the framework's own
   documented gate-2 ceiling (`08-benchmark-design.md:74`), which nothing
   in the codebase computed before this check existed.
5. **Three `semantic_mutants` survive, correctly classified NEEDS_REVIEW
   (never INVALID) per mission §8** ("a surviving mutant is not automatic
   proof the benchmark is broken"):
   - `async-retry`: broadening `except Exception` to `except BaseException`
     silently swallows `asyncio.CancelledError` (retrying instead of
     letting cancellation propagate) — an availability-relevant near-miss
     no existing hidden test can catch since none of them raise anything
     but `Exception` subclasses.
   - `expression-evaluator`: an `eval()`-based implementation — the task
     description explicitly says not to use `eval()` (arbitrary-code-
     execution risk), but Python's own operator precedence/associativity
     happens to match the spec exactly on every hidden-suite input, so a
     purely behavioral suite has no way to catch the banned-primitive
     violation.
   - `mask-secrets`: wrapping every secret pattern in `\b` word-boundary
     anchors (a plausible "tightening" fix for the audit's own prior
     "regex grammar is ambiguous" note) silently stops matching a secret
     glued directly onto adjacent text with no delimiter.
6. **Systemic finding (every task): the `_pytest/` shadow-package gap**
   (documented above under "Runner touches") — confirmed present pack-wide,
   not task-specific.
7. **Incidental, not a hidden-suite finding** (`fix-path-traversal`, found
   by the controls-authoring agent while cross-checking its alternative
   against the reference over ~4095 (base, parts) combinations):
   `reference/safepath/join.py` itself spuriously rejects a legitimate
   child of the literal relative base `"."` (e.g. `safe_join(".", "reports")`)
   because its `sep_prefix` check doesn't survive `posixpath.normpath`
   stripping a leading `./`. Out of the task's actual tested domain
   (absolute bases only) and untested either way — noted here, NOT fixed
   (out of scope: it would touch `reference/`, which the mission reserves
   for task hardening, not integrity-engine work).

### What did NOT need any control fixes

`fix-path-traversal`, `escape-html`, `implement-lru-cache`,
`fix-roman-numerals` (all 4-5 controls each): every known-bad control was
correctly `rejected_by_hidden_test`, every alternative correctly `accepted`,
zero `rejected_by_scope_gate`/`rejected_by_regression_gate` authoring
errors — these tasks' hidden suites held up against everything thrown at
them in this pass.

### Mutation cap disclosure (no silent caps)

The pack-wide FULL run used `--max-mutants 40` (not the default 60, to keep
the whole-pack wall clock reasonable). Two tasks hit that cap and did NOT
get their full candidate set graded: `expression-evaluator` (112 candidates
generated, only the first 40 graded — 72 not graded this run) and
`refactor-order-validation` (72 generated, 40 graded, 32 not graded). Both
are recorded in `evidence.notes` on their `mutation.generic_ast_mutants`
check, but the check's own headline ("N relevant of 40 generated") reads as
if 40 were the natural count for that file, not a cap — stated here
explicitly so it isn't missed. Every other task's mutation count in this
run is the true total (no cap applied). A future full run with a higher
`--max-mutants` (or per-file, rather than per-task, budgeting) would give
these two tasks a fairer shake; this run did not attempt that.

### FULL-mode pack audit: status and mutation-family patterns

`integrity/pack-audit/full-summary.md` (24 tasks, ~6.4 minutes wall clock at
8 workers): **HEALTHY 2** (`escape-html`, `implement-lru-cache`),
**NEEDS_REVIEW 14**, **INVALID 3** (the three above), **PROVISIONAL 5** (no
controls declared: `async-timeout`, `fix-binary-search`, `paginator`,
`query-builder`, `result-type`).

Pack-wide surviving-generic-mutant family counts:
`remove_branch` (16), `remove_validation` (9), `change_constant` (7),
`boundary_operator` (5), `swap_boolean_condition` (3), `delete_state_update`
(2), `drop_exception_handling`/`swap_boolean_literal`/`invert_comparison`/
`return_constant` (1 each). `remove_branch`/`remove_validation` dominate,
almost always clustered on the same line — an input-validation guard clause.

**Spot-verified by hand** (not just trusted from the count) on
`validate-redirect-url`, the task with the most survivors (9): the pattern
is a **mix**, not a uniform gap. Traced two representative survivors through
the actual control flow:
- The protocol-relative guard (`if target.startswith("//"): raise ...`) is
  **safely redundant**: removing it, `"//evil.com"` still gets rejected two
  checks later (`parsed.scheme` is `""`, which fails the
  `scheme not in ("http", "https")` check) — genuine defense-in-depth, not
  an untested gap.
- The non-string/empty-target guard (`if not isinstance(target, str) or not
  target: raise ...`) **is** a genuine, if low-severity, coverage gap: no
  hidden test ever calls `safe_redirect` with a non-string or empty target,
  so nothing downstream catches it either.

This is exactly the nuance mission §16 warns about: a "16 remove_branch
mutants survived pack-wide" headline would overclaim if presented alone.
The engine's report avoids stating an aggregate correctness conclusion from
mutation counts; a human still has to look at each survival location, which
is exactly what `evidence.survived` in each check result is for.

## 2026-09-18 — Independent code review of the engine itself (9/9 confirmed)

Ran `/code-review high --path integrity/afa_integrity` against the engine
code (not the task content) before treating it as done. All 9 findings were
independently verified (not just asserted) and fixed; the fix for #6 was
then confirmed to have real, measurable impact on already-collected
results, not just a theoretical one — see below.

1. **`hidden_import_closure.py`: allow-list mode returned an unconditional
   PASS without checking whether a resolved import fell WITHIN
   `editable_paths`** — exactly the agent-rewritable oracle-helper case
   gate 7 exists to catch (a helper module living in the same editable
   package as the code under test, e.g. `safepath/expected.py` under glob
   `safepath/**`, is just as rewritable as the code under test itself; an
   allow-list only rules out imports OUTSIDE it). Fixed: both regimes now
   compute which resolved imports are *reachable* (matching editable_paths
   in allow-list mode, or NOT matching protected_paths in deny-list mode)
   and warn when more than one distinct reachable file is imported — PASS
   is now only claimed when at most one file is reachable (unambiguously
   the code under test). **Verified against the real pack**: this
   immediately surfaced a genuine, previously invisible case —
   `refactor-order-validation`'s hidden+regression suites together import
   both `orderkit/__init__.py` and `orderkit/process.py`. Traced by hand:
   this is a benign 3-file refactor task (`orderkit/{__init__,money,process}.py`)
   where `__init__.py`'s import is just the normal parent-package import
   Python does for `from orderkit.process import ...` plus a regression
   test doing `from orderkit import ...` directly — not a hidden oracle
   helper. Exactly the right outcome for a static heuristic: flag for
   human review rather than assert false certainty, and a human reviewing
   it clears it in one look.
2. **`_local_imports` silently dropped bare relative imports**
   (`from . import x`, `node.module is None`). Fixed: these are now
   collected into a reported `unresolved_relative_imports` list instead of
   disappearing, and downgrade the check to WARNING (not a silent PASS)
   when present. No real task in the pack uses one today.
3. **`protected_paths.py` never probed the `.pth` suffix rule**
   (`ALWAYS_PROTECTED_SUFFIXES` in `afa_runner/diffing.py`), only basenames
   — the suffix-based defense was completely untested by this check. Added
   a dedicated probe.
4. **`control.json`'s `expect` field was compared with a bare `==
   "accept"`** — a typo (`"Accept"`, `"accepted"`) would silently invert a
   control's expected outcome with no warning anywhere. Fixed: normalized
   and validated at load time, raising `ValueError` on anything other than
   `"accept"`/`"reject"` — loud failure at authoring time, matching how
   `afa_runner.task.load_task` already treats a malformed spec.
5. **A hardcoded 30s timeout for graded controls** (`controls_check.py`,
   and the same pattern independently duplicated in `audit.py`'s
   determinism sampling and `checks/isolation.py`) was sometimes *looser*
   than a short-timeout task's own budget (contradicting its own "well
   under the task's timeout" docstring) and sometimes *tighter* than a
   legitimately-slower-but-valid control's real needs on a long-timeout
   task. Fixed by removing the override entirely for all three: declared
   controls and the isolation probe are human-authored/purpose-built, not
   the product of random mutation most likely to hang, so they grade
   against the task's own `timeout_s` like every other real grade call in
   this codebase.
6. **Mutation kill-rate silently counted regression/scope-gate-intercepted
   mutants as "killed"** — `summarize_mutants` (and `report.py`'s Markdown
   renderer, which independently duplicated the same inflated arithmetic)
   folded `killed_by_regression`/`killed_by_scope` into `killed_total`,
   contradicting `controls_check.py`'s own explicit rule (documented in
   this very journal as "scope-gate masking") that a regression/scope kill
   never actually exercised the hidden suite. Fixed: these are now their
   own `mutants_intercepted_by_regression_or_scope` bucket, excluded from
   both the numerator and denominator of `kill_rate`. **This was not a
   theoretical fix** — re-running against the real pack after the fix
   changed `fix-path-traversal`'s reported kill rate from **0.87 (13/15,
   0 intercepted)** to **0.67 (4/6 relevant, 9 intercepted)**: 9 of the
   original 15 mutants had never actually reached the hidden suite at all.
   The 2 genuinely-surviving mutants are unchanged — only the honesty of
   the denominator changed. The full pack-level audit was re-run after
   this fix (see below); the previously-committed pre-fix numbers are
   superseded.
7. **`pack.py`: an unhandled exception from one task's audit (e.g. a
   malformed `task.json`) propagated out of `ThreadPoolExecutor.as_completed`
   and discarded every other already-completed task's report** — a 23/24
   successful pack audit would come back as a bare traceback with zero
   evidence preserved. Fixed: each task's future is resolved individually
   with its own `try/except`; failures are collected into a new
   `PackAuditSummary.failures: dict[task_id, error]` field, surfaced in the
   Markdown/JSON output, and forced into at least an INVALID-equivalent
   CLI exit code (a task that couldn't be audited is at least as bad as an
   invalid one) rather than silently passing through as if unaudited meant
   healthy.
8. **`read_overlay_files` only caught `(UnicodeDecodeError, ValueError)`**,
   so a permission error or a racing/dangling symlink would crash an
   entire audit — contradicting this module's own "never raises for an
   expected-shape problem" design principle. Added `OSError`.
9. **The QUICK-mode PROVISIONAL fallback text, and the matching
   "not run" limitations in `audit.py`, were keyed on `AuditMode` instead
   of on which checks actually ran** — running `--quick --mutation`
   produces a report where `mutation.generic_ast_mutants` genuinely PASSED
   but the reason field still claimed "mutation testing ... were not run,"
   and separately the isolation probe's absence (gated on FULL mode alone,
   unaffected by `--mutation`) was never mentioned anywhere. Fixed:
   `determine_health_status` no longer takes a `mode` parameter at all —
   it derives "was FULL-only evidence collected" purely by checking for
   `mutation.generic_ast_mutants`/`isolation.hidden_test_readability` in
   the actual `checks` list, and `audit.py`'s two limitation messages are
   now each tied to the exact condition that gates the check they
   describe, not to the mode as a whole, so they can no longer contradict
   each other or a check result in the same report. `integrity/tests/
   test_health.py` was rewritten around `QUICK_PASS_CHECKS`/`FULL_PASS_CHECKS`
   fixtures (which checks are present) instead of an `AuditMode` argument,
   since the underlying bug was exactly that mode-based inference doesn't
   match reality.

All fixes verified: the fast unit suite (`test_health.py`,
`test_mutation_engine.py`, `test_overlay.py`, `test_controls.py`, 37 tests)
and the full fixture integration suite (`test_audit_fixtures.py`, 8 tests,
real grading) both pass after every fix. The pack-level QUICK and FULL
audits were re-run from scratch afterward (fix #6 changes real numbers) —
see the updated pack-audit section above, which reflects the corrected
engine, not the pre-fix run.

## Open questions / follow-ups for whoever picks this up next

- 14 of the 24 tasks still have zero declared controls (everything outside
  the 10 tackled here) — PROVISIONAL by design, not a defect. Natural next
  batch: `query-builder` (prior audit flagged a suspicious 1/25 pass rate —
  possible adapter confound, worth an alternative-solution check),
  `merge-intervals`, `paginator`, `result-type`, `refactor-order-validation`,
  the remaining `async-*` tasks.
- The `fix-list-dedup` finding suggests it's worth grepping the rest of the
  pack for other "order not preserved by set()" or similarly
  implementation-detail-dependent no-op behaviors — I did not do a
  systematic sweep for this pattern beyond what the noop check already
  caught automatically.
- Mutation testing (FULL mode) was run pack-wide; see
  `integrity/pack-audit/full-summary.md` for which tasks have surviving
  generic mutants beyond what's captured above via declared semantic
  mutants.
- `expression-evaluator` (112 candidates) and `refactor-order-validation`
  (72 candidates) both hit the `--max-mutants 40` cap used for the pack-wide
  FULL run and did not get their full candidate set graded — see "Mutation
  cap disclosure" above. Worth a dedicated, uncapped run on just these two.
- **Exact remediation test cases for the three INVALID tasks**, so a
  benchmark author has something to act on directly instead of just a
  verdict:
  - `sanitize-filename`: add a hidden test asserting a name with a space,
    punctuation, or non-ASCII character (e.g. `"my file.txt"`,
    `"résumé.pdf"`) is returned UNCHANGED — the spec already promises this,
    nothing currently checks it.
  - `toposort`: add a case where the dropped-dependency bug ISN'T rescued
    by the alphabetical tiebreak, e.g. `{"app": ["lib", "aaa"]}` — "aaa"
    sorts BEFORE "lib" alphabetically, so if the `app -> aaa` edge is
    silently dropped, "aaa" would incorrectly need to come before "app" by
    coincidence only if it already would anyway; picking a dependency name
    that sorts AFTER the other candidates (e.g. `{"app": ["lib", "zzz"]}`)
    forces the edge itself to be what puts "zzz" before "app", so a
    dropped-edge implementation actually fails the ordering assertion
    instead of passing by alphabetical accident.
  - `validate-redirect-url`: add a hidden test with a look-alike host that
    CONTAINS the allowed host as a substring or prefix, e.g.
    `safe_redirect("https://app.example.com.evil.com/x", ALLOWED)` must
    raise — nothing currently tests this attacker-controlled-superstring
    shape, only a completely unrelated host (`evil.com`).
- **Commit-history disclosure for a bisecting reviewer**: `62bdcc7`
  ("domain model + reference/no-op checks") ships an `afa_integrity/
  __init__.py` that imports `audit.py`/`pack.py`/`health.py`/`report.py`,
  which don't exist until `c76eb50`/`bc00d4d` — `afa_integrity` is not
  importable at that intermediate commit. Deliberate: rewriting history to
  make every commit independently importable was weighed against "always
  create NEW commits, never rewrite" and the latter won; every commit is a
  real, reviewable logical unit, just not independently `pip install`-able
  until `bc00d4d`. Also: `c48e1ef` (the first pack-audit run, pre-code-review)
  is superseded by `bf475b9` (post-fix re-run) — the numbers in `c48e1ef`
  should not be cited as current.
- **Merge considerations for whoever reconciles this with ATLAS's branch**:
  `pyproject.toml`'s `[tool.pytest.ini_options]` (`pythonpath`/`testpaths`)
  is the most likely conflict — ATLAS's Phase-0 work plausibly touches the
  same block. `runner/afa_runner/__init__.py`'s export list is a secondary,
  lower-probability conflict point (a new export added on a nearby line).
  `runner/afa_runner/diffing.py` and `pipeline.py` are purely additive
  (a new frozenset entry, a new top-level function) and very unlikely to
  conflict with anything Phase-0-shaped.

---

# Mission 2 — Benchmark Remediation & Coverage Hardening

## 2026-09-18 — Corrected: the `_pytest` shadow-package finding was overstated

Before touching any task's hidden suite, revisited mission-2's explicit
instruction to investigate the `_pytest` shadow-package finding's *exact
exploitability*, since the first-mission finding was reported at HIGH
severity as if it were a live gap.

**It was overstated.** The original probe (`checks/protected_paths.py`)
injects `_pytest/__init__.py` **nested inside the task's editable_paths
subtree** (e.g. `searchkit/_pytest/__init__.py`), since `editable_prefix`
is derived from `editable_paths[0]` — every task in the pack has one. I
built a controlled reproduction rather than trusting the theoretical
argument:

```python
# searchkit/__init__.py does `import _pytest; print(_pytest.__file__)`
# with a malicious searchkit/_pytest/__init__.py sitting right next to it.
# Result: RESOLVED _pytest FROM: .../site-packages/_pytest/__init__.py
```

**Empirically confirmed harmless**: `python -m pytest` never adds the
editable package directory itself to `sys.path` — only the cleanroom
*root* is on `sys.path[0]` — so a nested `_pytest/` is only ever
importable as `searchkit._pytest`, never as the bare top-level `_pytest`
the real pytest package needs internally. The exact same experiment with
the malicious package placed at the **cleanroom root** instead (only
reachable if a task had NO `editable_paths` allow-list at all — a
deny-list-only configuration) does shadow the real one and **crashes
pytest's own bootstrap**:

```text
ImportError: cannot import name '__version__' from '_pytest'
(.../tmp.../  _pytest/__init__.py)
```

**Conclusion, verified against all 24 tasks' `task.json`**: every single
task ships a non-empty `editable_paths` allow-list of the shape
`<package>/**` — none permits a root-level write, and none is
deny-list-only. **No task in the current pack is exploitable via this
route today.** The theoretical concern only applies to a hypothetical
future deny-list-only task, and even then only via a root-level
placement, not a nested one.

**Fix** (dedicated commit, engine-only, no task files touched):
`checks/protected_paths.py` now distinguishes the two cases explicitly —
a nested-in-editable-subtree finding is downgraded to `INFO` severity with
an explicit `exploitable_today: false` evidence flag and the empirical
reasoning above; a genuine root-level finding on an actual deny-list-only
task keeps `HIGH` severity (that variant IS real, per the second
experiment). Added `integrity/tests/test_protected_paths.py`, including a
standing pack-wide invariant test (`test_no_task_in_the_real_pack_is_in_
deny_list_only_mode`) that fails loudly if any future task ever ships
without an `editable_paths` allow-list — the exact moment this finding
would stop being theoretical.

**No prior finding is invalidated by this fix** beyond its own severity
label — the underlying mechanics (`touched_protected=False` for the nested
case) were always correctly measured; only the Finding's narrative
overclaimed live exploitability. Per mission-2 §14: minimal structural
protection was considered and rejected — catching a directory literally
named `_pytest` anywhere would need new directory-name-matching logic (not
a one-line basename addition like the `pytest.py` fix from mission 1), for
a scenario with zero current exposure. Documented as a residual, currently
inert limitation instead, exactly as mission-2 §14 anticipates ("or
whether it must remain a documented LocalSandbox limitation").

## 2026-09-18 — An OS-level file-access outage hit mid-remediation

Partway through applying the two remediation workflows' results, every tool
touching `/Users/manuk/Downloads/...` (Bash subprocesses AND the Read/Edit
tools themselves) started failing with `EPERM: Operation not permitted` —
first for `python3`/`ls`/`cat`, then escalating to `Read`/`Edit`, while
`stat`/`touch` kept working on the exact same paths. `git status`/`git -C
... status` failed at `Unable to read current working directory`, a total
block, not a file-specific one. Independently confirmed by three concurrent
subagents (fixing `async-timeout`, `paginator`, `query-builder`) hitting the
identical symptom at the same time, ruling out a single-process fluke.

Best-supported diagnosis (not fully confirmed, since it resolved before
root-causing further): a macOS TCC "Files and Folders / Downloads Folder"
permission revoked mid-session for whatever process runs these tools' shells
— `stat`/`touch` can succeed under TCC gating that still blocks `open`/
`readdir`, which matches the exact split observed. The system volume was
also at 100% capacity (889Gi/926Gi) at the time, a plausibly-contributing
but not fully explanatory factor on its own.

**Handling**: every in-flight subagent correctly stopped mutating files the
moment tool calls started failing, hand-backed a structured report of what
it had confirmed vs. designed-but-unverified, and did not attempt to route
around the block through a peer session (recognized and declined as
permission laundering). Three subagents' completed edits (paginator,
query-builder, result-type) had already landed via the Edit tool before the
outage and survived it intact. One (async-timeout) had only reached the
design stage; its prepared fix (reviewed and found correct before applying)
was manually applied by the orchestrating session once access returned.

**Side effect discovered on recovery**: this session's own `/private/tmp`
scratchpad area (holding the structured JSON returned by the first
remediation workflow) was gone once access returned — apparently cleared
during whatever recovery/remount happened, not something any agent deleted.
The remediation manifest below was rebuilt from git history instead (the
commit messages for `e2e4513`/`36650d7` already carried the full per-task
finding/classification/action detail) plus a fresh `runs.sqlite` query —
a durable source that didn't depend on ephemeral session state surviving.
**Lesson for next time**: anything meant to outlive a single tool call
should land in the git-tracked working tree or a committed file as soon as
it's ready, not held only in an agent's return value or scratch directory.

## 2026-09-18 — Post-remediation FULL pack audit (commit `36650d7`)

Ran `python -m afa_integrity audit --all --full --max-mutants 60` against
the fully-remediated tree. Before vs. after mission 2:

```
              BEFORE (bf475b9)   AFTER (36650d7)
HEALTHY               2                15
NEEDS_REVIEW          14                2
PROVISIONAL           5                 7
INVALID               3                 0
```

**INVALID: 3 → 0.** All three originally-INVALID tasks are now HEALTHY.
**NEEDS_REVIEW: 14 → 2** — `fix-list-dedup` (mutation adequacy could not be
assessed this run: every generated mutant was intercepted by the
regression/scope gate before reaching the hidden suite — an engine-reported
limitation, not a new defect) and `refactor-order-validation` (the gate7
import-closure WARNING, already investigated and confirmed
`BENIGN_IMPORT_CLOSURE` — the engine has no mechanism to auto-clear a
structurally-correct WARNING once a human has reviewed it, which is
intentional: silently downgrading it would be exactly the "make the grader
look healthy" behavior mission 2's north star prohibits).

**PROVISIONAL: 5 → 7** (up, not down) — this is correct, not a regression.
Several tasks that were NEEDS_REVIEW before (their hidden suite got fixed,
clearing the mutation/gap findings) still have zero declared controls, so
they land in PROVISIONAL rather than HEALTHY: `async-first-success`,
`async-gather-bounded`, `grid-paths`, `merge-intervals`, `top-k-frequent`
(all newly PROVISIONAL, having graduated out of NEEDS_REVIEW) plus
`async-batched` and `two-sum-indices` (unchanged, already PROVISIONAL).
None of these were force-fed controls just to inflate the HEALTHY count —
per the mission's own instruction, "quality > quantity" and PROVISIONAL for
"no controls declared" is an honest, correct state, not a defect to hide.

**Evidence storage policy applied** (`docs/AUDIT_EVIDENCE_POLICY.md`):
kept per-task detailed JSON+MD for the 18 version-changed tasks (all
manifest-relevant) plus `fix-binary-search` and `fix-roman-numerals` (both
newly HEALTHY via declared-equivalent-mutant/controls work worth a
permanent worked example); dropped the routine, untouched-by-mission-2
`escape-html`, `implement-lru-cache`, `async-batched`, `two-sum-indices`
per-task files (their one-line pack-summary entry already says everything
needed; full evidence is one CLI command away on demand).

## Remediation manifest (`integrity/pack-audit/remediation-manifest.{json,md}`)

18 tasks, 540 historical runs (6 models × 5 reps × 18 tasks) no longer
directly comparable to their new task version, 51 model/task cells that
previously scored a functional PASS and are the highest-priority
re-evaluation targets (queried fresh from `reports/runs.sqlite`, not
estimated). One correction applied during manifest assembly: `toposort`'s
own remediation report had concluded `reevaluation_required: false`,
reasoning that because the integrity engine's synthetic-control audit
already flagged it INVALID, no real historical run was affected — a
category error (the engine's synthetic verdict says nothing about the 30
real historical runs, all of which scored `functional_pass=False` anyway,
since toposort is a task no model in the pack has ever solved). Corrected
to `true`, consistent with every other version-bumped task, with the
reasoning error documented in the manifest entry itself.

Spot-checked (not assumed) whether any REAL historical submission actually
exploited the two most severe fixed gaps, by reading the actual stored
patches: none of `sanitize-filename`'s 10 historically-passing submissions
use a character-allowlist pattern, and none of `validate-redirect-url`'s 4
use substring/`in`-based host matching (all use exact `==`) — so while the
fixes close genuinely real vulnerability classes (confirmed via synthetic
controls empirically accepted by the old suite), no *currently stored*
score is definitively known to be wrong for these two tasks specifically.
Re-evaluation is still required to make any *current* claim (the grading
instrument changed), but this is an honest, evidence-checked distinction
between "the gap is real" and "we know a specific stored score is wrong" —
not an assumption in either direction.


## Integration erratum (2026-09-19): a stale test pin on the frozen ORACLE branch

While integrating ORACLE with ATLAS (see `docs/integration/PHASE0_INTEGRATION_REPORT.md`) the **complete repository suite** was run for the first time since the mission-2 remediation, and it showed two failures that pre-date the merge: `runner/tests/test_grader.py::test_reference_overlay_scores_perfect` and `::test_grade_ignores_stale_snapshot_bytecode` pinned `len(report.run_input.hidden) == 6` for `fix-list-dedup`. Remediation commit `e2e4513` legitimately added two hidden tests to that task (6 -> 8) but did not update the pin, so the frozen `oracle@d0efbc4` fails the full suite. The integrity suite and the pack audits were green; the mission-2 verification did not re-run `runner/tests` after the hidden-suite change.

Attribution was checked, not assumed: the two tests fail on the ORACLE-only tree and pass on the frozen ATLAS branch, so this is an ORACLE-side defect, not an integration effect. The integration branch fixes it (`1142d39`) by asserting that the graded test **names** equal the test functions the hidden suite defines (read from its source) instead of pinning a count; that is stricter than the count and stays valid the next time the oracle is hardened.

Lesson: after any hidden-suite change, run the whole repository suite, not only the integrity suite.
