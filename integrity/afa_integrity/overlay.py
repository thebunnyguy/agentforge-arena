"""Overlay-then-grade-then-score: the one primitive every check in this
package is built from.

afa_runner already has everything needed: capture_diff turns "these files
replace/add onto the snapshot" into a Diff, and grade()+score_run() turn a
Diff into a score. This module adds exactly two things afa_runner doesn't
already have: an in-memory (dict-based) overlay constructor for mutation
testing, and a shared Verdict classifier so every caller (reference check,
no-op check, controls, mutants) agrees on what "the hidden suite caught it"
means. It never re-derives scoring, gating, or diffing logic itself.
"""

from __future__ import annotations

import hashlib
import shutil
import tempfile
from dataclasses import replace
from pathlib import Path

from afa_runner.diffing import Diff, capture_diff
from afa_runner.grader import GradeReport, grade
from afa_runner.sandbox import Sandbox
from afa_runner.task import Task

from afa_kernel.scoring import score_run
from afa_kernel.types import RunScore

from .model import Verdict


def read_overlay_files(root: Path | str) -> dict[str, str]:
    """Read every text file under root into {posix_relpath: text}.

    Mirrors afa_runner.diffing.snapshot_tree's text-only model (binary/
    undecodable files are skipped) so overlay directories behave exactly like
    the snapshot/reference directories the runner already walks.
    """
    root = Path(root)
    files: dict[str, str] = {}
    for src in sorted(root.rglob("*")):
        if not src.is_file():
            continue
        rel = src.relative_to(root).as_posix()
        try:
            files[rel] = src.read_text(encoding="utf-8")
        except (UnicodeDecodeError, ValueError):
            continue
    return files


def overlay_files_diff(task: Task, files: dict[str, str]) -> Diff:
    """Build the Diff for overlaying an in-memory {relpath: text} map onto a
    throwaway copy of the task's snapshot.

    This is the dict-based sibling of afa_runner.pipeline.overlay_diff (which
    reads a directory from disk): mutation testing already has final file
    contents in memory (a reference file with one AST node mutated), so this
    skips writing a full overlay directory to disk per mutant.
    """
    tmp_root = Path(tempfile.mkdtemp(prefix="afa_integrity_overlay_"))
    workspace = tmp_root / "workspace"
    try:
        shutil.copytree(task.snapshot_dir, workspace)
        for rel, text in files.items():
            dest = workspace / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(text, encoding="utf-8")
        return capture_diff(
            task.snapshot_dir,
            workspace,
            protected_globs=task.protected_paths,
            editable_globs=task.editable_paths,
        )
    finally:
        shutil.rmtree(tmp_root, ignore_errors=True)


def grade_diff(
    task: Task,
    diff: Diff,
    sandbox: Sandbox,
    *,
    timeout_s: int | None = None,
) -> tuple[GradeReport, RunScore]:
    """Grade a Diff and score it through the exact same two calls the runner
    itself uses (grade() then score_run()) — never a re-derivation.

    timeout_s, when given, grades against a copy of the task with that timeout
    instead of the task's own (Task is frozen; dataclasses.replace needs no
    grader change). Used by mutation testing to cap a runaway mutant's
    grading time well below a task's normal (up to 120s) budget, so one
    infinite-looping mutant can't dominate an audit's wall clock.
    """
    graded_task = task if timeout_s is None else replace(task, timeout_s=timeout_s)
    report = grade(graded_task, diff, sandbox)
    score = score_run(report.run_input)
    return report, score


def classify_verdict(report: GradeReport, score: RunScore) -> Verdict:
    """The one place that turns a graded overlay into the shared Verdict
    vocabulary. Order matters: scope and regression are checked before hidden,
    because a diff that fails scope or regression never meaningfully exercised
    the hidden suite as an oracle for this overlay — see docs/agents/ORACLE.md
    ("scope-gate masking").
    """
    if score.functional_pass:
        return Verdict.ACCEPTED
    gates = report.run_input.gates
    if not gates.scope_ok:
        return Verdict.REJECTED_BY_SCOPE_GATE
    if report.regression.errored or not report.regression.all_passed:
        return Verdict.REJECTED_BY_REGRESSION_GATE
    if report.hidden.errored:
        return Verdict.REJECTED_BY_TIMEOUT_OR_ERROR
    return Verdict.REJECTED_BY_HIDDEN_TEST


def killed_by_tests(report: GradeReport) -> tuple[str, ...]:
    """Names of the specific hidden tests that failed for this grade, in the
    order pytest reported them — the concrete evidence for "which test caught
    this," not just that some test did.
    """
    return tuple(t.name for t in report.hidden.results if not t.passed)


def outcome_fingerprint(report: GradeReport, score: RunScore) -> str:
    """Canonical hash of a grade's OUTCOME, for repeated-grading determinism
    checks (framework §9 / mission §11).

    Deliberately excludes SuiteOutcome.notes and GradeReport.notes: those carry
    raw pytest stdout/stderr (timings, temp paths, retry diagnostics) that is
    never byte-identical across runs even when the actual grading OUTCOME is —
    hashing them would make every task in the pack look flaky. Two grades of
    the same Diff are "the same outcome" iff gates, the per-test (name, passed,
    weight) tuples for both suites, and the derived score/functional_pass all
    match.
    """
    def suite_key(suite):
        return (
            suite.all_passed,
            suite.errored,
            tuple((t.name, t.passed, t.weight) for t in suite.results),
        )

    payload = repr(
        (
            report.run_input.gates,
            suite_key(report.hidden),
            suite_key(report.regression),
            score.final_score,
            score.functional_pass,
        )
    )
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def diff_hash(diff: Diff) -> str:
    """Stable identity for a Diff's content, used for the declared-equivalent-
    mutant allowlist (tasks/<id>/integrity/integrity.json) and for de-duplicating
    identical mutants generated from different AST walks."""
    return "sha256:" + hashlib.sha256(diff.patch_text.encode("utf-8", "replace")).hexdigest()
