"""Reference-solution validation (framework §8 activation gate 1; mission §5).

This is the same invariant runner/afa_runner/pipeline.py:validate_task already
enforces for its "reference" half, reimplemented here as evidence-preserving
(never raises) rather than assert-and-raise, and grading through the exact
same overlay_diff/grade/score_run primitives so the two can never quietly
disagree about what "correct" means.
"""

from __future__ import annotations

import time

from afa_runner.pipeline import overlay_diff
from afa_runner.sandbox import Sandbox
from afa_runner.task import Task

from ..model import CheckStatus, IntegrityCheckResult, Severity
from ..overlay import grade_diff, outcome_fingerprint

QUICK_REPEATS = 3
FULL_REPEATS = 5


def run_reference_check(
    task: Task, sandbox: Sandbox, *, repeats: int = QUICK_REPEATS
) -> IntegrityCheckResult:
    """Overlay the reference solution, grade it `repeats` times, and verify it
    scores exactly (final_score=1.0, functional_pass=True) identically every
    time. Preserves the actual per-repeat evidence rather than a single
    reference_solution = pass boolean (mission §5).
    """
    start = time.monotonic()

    if task.reference_dir is None:
        return IntegrityCheckResult(
            check_id="reference.solution_validation",
            category="reference",
            status=CheckStatus.UNVERIFIABLE,
            severity=Severity.HIGH,
            description="Task has no reference_dir; cannot validate that a "
            "correct solution exists and scores as expected.",
            evidence={},
            duration_ms=int((time.monotonic() - start) * 1000),
        )

    diff = overlay_diff(task, task.reference_dir)
    if not diff.exists():
        return IntegrityCheckResult(
            check_id="reference.solution_validation",
            category="reference",
            status=CheckStatus.ERROR,
            severity=Severity.CRITICAL,
            description="The reference solution overlay produced an EMPTY diff "
            "against the snapshot — the reference is identical to the "
            "unmodified snapshot, or reference_dir is misconfigured.",
            evidence={"files_changed": diff.files_changed},
            duration_ms=int((time.monotonic() - start) * 1000),
        )
    if diff.touched_protected:
        return IntegrityCheckResult(
            check_id="reference.solution_validation",
            category="reference",
            status=CheckStatus.ERROR,
            severity=Severity.CRITICAL,
            description="The reference solution touches a protected or "
            "out-of-scope path — it cannot legitimately score under the "
            "task's own scope gate.",
            evidence={"files_changed": diff.files_changed},
            duration_ms=int((time.monotonic() - start) * 1000),
        )

    repeats_evidence = []
    fingerprints = set()
    for i in range(repeats):
        report, score = grade_diff(task, diff, sandbox)
        fp = outcome_fingerprint(report, score)
        fingerprints.add(fp)
        repeats_evidence.append(
            {
                "attempt": i,
                "final_score": score.final_score,
                "functional_pass": score.functional_pass,
                "gate_product": score.gate_product,
                "t_hidden": score.t_hidden,
                "n_hidden": len(report.hidden.results),
                "hidden_all_passed": report.hidden.all_passed,
                "regression_all_passed": report.regression.all_passed,
                "fingerprint": fp,
            }
        )

    first = repeats_evidence[0]
    correct = first["final_score"] == 1.0 and first["functional_pass"] is True
    deterministic = len(fingerprints) == 1
    duration_ms = int((time.monotonic() - start) * 1000)
    evidence = {
        "repeats": repeats_evidence,
        "n_repeats": repeats,
        "deterministic": deterministic,
        "files_changed": diff.files_changed,
        "lines_added": diff.lines_added,
        "lines_removed": diff.lines_removed,
    }

    if not correct:
        return IntegrityCheckResult(
            check_id="reference.solution_validation",
            category="reference",
            status=CheckStatus.FAIL,
            severity=Severity.CRITICAL,
            description=(
                "The reference solution does not score (1.0, functional_pass="
                f"True): got (final_score={first['final_score']}, "
                f"functional_pass={first['functional_pass']}). Either the "
                "reference is broken/outdated or the hidden suite has drifted "
                "away from what the reference implements."
            ),
            evidence=evidence,
            duration_ms=duration_ms,
        )
    if not deterministic:
        return IntegrityCheckResult(
            check_id="reference.solution_validation",
            category="reference",
            status=CheckStatus.FAIL,
            severity=Severity.CRITICAL,
            description=(
                f"GRADER_NONDETERMINISM: grading the identical reference "
                f"overlay {repeats} times produced {len(fingerprints)} "
                "distinct outcomes. Any variance regrading an identical "
                "artifact is a harness/grader bug, not a task property "
                "(framework §9/§5.3) — this task's scores cannot be trusted "
                "until the grader is deterministic for it."
            ),
            evidence=evidence,
            duration_ms=duration_ms,
        )

    return IntegrityCheckResult(
        check_id="reference.solution_validation",
        category="reference",
        status=CheckStatus.PASS,
        severity=Severity.INFO,
        description=(
            f"Reference solution scores (1.0, True) identically across "
            f"{repeats} repeated grades."
        ),
        evidence=evidence,
        duration_ms=duration_ms,
    )
