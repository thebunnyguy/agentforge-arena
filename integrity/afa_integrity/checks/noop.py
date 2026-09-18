"""No-op / unmodified-baseline negative control (framework §8 activation gates
2-3; mission §6).

Grades the empty diff (the pristine, unmodified snapshot) and checks:
  - regression must PASS (the snapshot isn't already rotten — gate 3),
  - hidden must NOT fully pass (there is a real bug to fix — gate 2), and,
    going beyond what validate_task currently checks: the weighted hidden
    pass fraction (T_hidden) on the untouched snapshot must be well below the
    "at least one weighted hidden test failing with weight share >= 0.5" bar
    the framework documents (08-benchmark-design.md:74) but never actually
    computes anywhere in the codebase today.
"""

from __future__ import annotations

import time

from afa_runner.diffing import capture_diff
from afa_runner.sandbox import Sandbox
from afa_runner.task import Task

from ..model import CheckStatus, IntegrityCheckResult, Severity
from ..overlay import grade_diff

# Framework §8.2 gate 2: "require at least one weighted hidden test failing
# with weight share >= 0.5, so the task cannot be passed by doing nothing or
# nearly nothing." Equivalently, T_hidden on the untouched snapshot must not
# exceed 0.5.
NOOP_T_HIDDEN_CEILING = 0.5


def run_noop_check(task: Task, sandbox: Sandbox) -> IntegrityCheckResult:
    start = time.monotonic()

    empty_diff = capture_diff(
        task.snapshot_dir,
        task.snapshot_dir,
        protected_globs=task.protected_paths,
        editable_globs=task.editable_paths,
    )
    if empty_diff.exists():
        # capture_diff(snapshot, snapshot, ...) must be empty by construction;
        # a non-empty result means the snapshot isn't self-consistent on disk
        # (e.g. it contains a file capture_diff sees as diffing from itself,
        # which would indicate a filesystem/encoding oddity, not a real bug).
        return IntegrityCheckResult(
            check_id="noop.unmodified_baseline",
            category="negative_control",
            status=CheckStatus.ERROR,
            severity=Severity.HIGH,
            description="Diffing the snapshot against itself was non-empty; "
            "the snapshot directory is not self-consistent.",
            evidence={"files_changed": empty_diff.files_changed},
            duration_ms=int((time.monotonic() - start) * 1000),
        )

    report, score = grade_diff(task, empty_diff, sandbox)
    duration_ms = int((time.monotonic() - start) * 1000)

    regression_ok = report.regression.all_passed and not report.regression.errored
    hidden_fully_passes = report.hidden.all_passed
    t_hidden = score.t_hidden

    evidence = {
        "final_score": score.final_score,
        "functional_pass": score.functional_pass,
        "t_hidden": t_hidden,
        "regression_all_passed": report.regression.all_passed,
        "regression_errored": report.regression.errored,
        "hidden_all_passed": report.hidden.all_passed,
        "hidden_errored": report.hidden.errored,
        "n_hidden": len(report.hidden.results),
        "diff_exists_gate": report.run_input.gates.diff_exists,
    }

    if not regression_ok:
        return IntegrityCheckResult(
            check_id="noop.unmodified_baseline",
            category="negative_control",
            status=CheckStatus.FAIL,
            severity=Severity.CRITICAL,
            description=(
                "The UNMODIFIED snapshot fails its own regression suite — the "
                "snapshot is rotten (framework §8.2 gate 3): agents would be "
                "penalized for pre-existing breakage they didn't cause."
            ),
            evidence=evidence,
            duration_ms=duration_ms,
        )
    if hidden_fully_passes:
        return IntegrityCheckResult(
            check_id="noop.unmodified_baseline",
            category="negative_control",
            status=CheckStatus.FAIL,
            severity=Severity.CRITICAL,
            description=(
                "The UNMODIFIED snapshot fully passes the hidden suite "
                "(framework §8.2 gate 2 violation): the task can be scored a "
                "full pass by doing nothing at all."
            ),
            evidence=evidence,
            duration_ms=duration_ms,
        )
    if score.final_score != 0.0 or score.functional_pass:
        return IntegrityCheckResult(
            check_id="noop.unmodified_baseline",
            category="negative_control",
            status=CheckStatus.FAIL,
            severity=Severity.CRITICAL,
            description=(
                "The empty diff did not score 0.0 / functional_pass=False as "
                "the diff_exists gate requires."
            ),
            evidence=evidence,
            duration_ms=duration_ms,
        )
    if t_hidden >= NOOP_T_HIDDEN_CEILING:
        return IntegrityCheckResult(
            check_id="noop.unmodified_baseline",
            category="negative_control",
            status=CheckStatus.WARNING,
            severity=Severity.HIGH,
            description=(
                f"The unmodified snapshot's weighted hidden pass fraction "
                f"(T_hidden={t_hidden:.3f}) is >= the documented "
                f"{NOOP_T_HIDDEN_CEILING} ceiling (framework §8.2 gate 2, "
                "08-benchmark-design.md:74): a large fraction of hidden-test "
                "weight already passes on doing nothing, so a near-empty or "
                "trivial submission could bank substantial continuous score "
                "without solving the core requirement. This condition is "
                "documented but was never computed anywhere in the codebase "
                "before this check — it is not equivalent to the binary "
                "hidden_all_passed gate above."
            ),
            evidence=evidence,
            duration_ms=duration_ms,
        )

    return IntegrityCheckResult(
        check_id="noop.unmodified_baseline",
        category="negative_control",
        status=CheckStatus.PASS,
        severity=Severity.INFO,
        description=(
            "The unmodified snapshot passes regression, fails the hidden "
            f"suite (T_hidden={t_hidden:.3f}), and scores 0.0 / "
            "functional_pass=False, as required."
        ),
        evidence=evidence,
        duration_ms=duration_ms,
    )
