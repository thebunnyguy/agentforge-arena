"""Grade every declared control (known-bad, semantic mutant, alternative) for
a task and check it against its author-declared expectation (mission §7/§9/
§10).

Status per control follows the verdict vocabulary in afa_integrity.overlay:
only a REJECTED_BY_HIDDEN_TEST verdict means "the hidden suite caught it" —
a control rejected by the scope or regression gate is a control-AUTHORING
error (ERROR), not evidence either way about the oracle (see
docs/agents/ORACLE.md, "scope-gate masking").
"""

from __future__ import annotations

import time

from afa_runner.sandbox import Sandbox
from afa_runner.task import Task

from ..controls import Control, discover_controls
from ..model import CheckStatus, ControlResult, IntegrityCheckResult, Severity, Verdict
from ..overlay import classify_verdict, grade_diff, killed_by_tests, overlay_files_diff

# Mutants/controls that hang the reference's own bug back in (e.g. an
# adversarial known-bad overlay with a runaway loop) are capped well under a
# task's normal timeout so one bad control can't dominate an audit.
CONTROL_TIMEOUT_S = 30


def _grade_control(task: Task, control: Control, sandbox: Sandbox) -> ControlResult:
    diff = overlay_files_diff(task, control.overlay_files())
    report, score = grade_diff(task, diff, sandbox, timeout_s=CONTROL_TIMEOUT_S)
    verdict = classify_verdict(report, score)
    matched_hidden_test_names = killed_by_tests(report)

    if control.expect_accept:
        if verdict == Verdict.ACCEPTED:
            status, matched = CheckStatus.PASS, True
        elif verdict == Verdict.REJECTED_BY_HIDDEN_TEST:
            status, matched = CheckStatus.FAIL, False
        elif verdict in (
            Verdict.REJECTED_BY_REGRESSION_GATE,
            Verdict.REJECTED_BY_SCOPE_GATE,
        ):
            status, matched = CheckStatus.ERROR, False
        else:
            status, matched = CheckStatus.WARNING, False
    else:
        if verdict == Verdict.REJECTED_BY_HIDDEN_TEST:
            status, matched = CheckStatus.PASS, True
        elif verdict == Verdict.ACCEPTED:
            status, matched = CheckStatus.FAIL, False
        elif verdict in (
            Verdict.REJECTED_BY_REGRESSION_GATE,
            Verdict.REJECTED_BY_SCOPE_GATE,
        ):
            status, matched = CheckStatus.ERROR, False
        else:
            status, matched = CheckStatus.WARNING, False

    notes_parts = [f"verdict={verdict.value}"]
    if matched_hidden_test_names:
        notes_parts.append(f"failing_hidden_tests={list(matched_hidden_test_names)}")

    return ControlResult(
        name=control.name,
        kind=control.kind,
        description=control.description,
        expected_accept=control.expect_accept,
        verdict=verdict,
        final_score=score.final_score,
        functional_pass=score.functional_pass,
        matched_expectation=matched,
        status=status,
        notes="; ".join(notes_parts),
    )


def run_controls_check(
    task: Task, sandbox: Sandbox
) -> tuple[IntegrityCheckResult, list[ControlResult]]:
    start = time.monotonic()
    controls = discover_controls(task)

    if not controls:
        duration_ms = int((time.monotonic() - start) * 1000)
        return (
            IntegrityCheckResult(
                check_id="controls.declared_controls",
                category="controls",
                status=CheckStatus.SKIPPED,
                severity=Severity.MEDIUM,
                description=(
                    "No known-bad solutions, semantic mutants, or alternative "
                    "solutions declared for this task "
                    "(tasks/<id>/integrity/controls/). The engine has no "
                    "task-specific evidence beyond the reference/no-op checks."
                ),
                evidence={"n_controls": 0},
                duration_ms=duration_ms,
            ),
            [],
        )

    results = [_grade_control(task, c, sandbox) for c in controls]
    duration_ms = int((time.monotonic() - start) * 1000)

    by_kind: dict[str, list[ControlResult]] = {}
    for r in results:
        by_kind.setdefault(r.kind.value, []).append(r)

    errors = [r for r in results if r.status == CheckStatus.ERROR]
    fails = [r for r in results if r.status == CheckStatus.FAIL]
    warnings = [r for r in results if r.status == CheckStatus.WARNING]

    evidence = {
        "n_controls": len(results),
        "by_kind": {
            kind: {
                "n": len(rs),
                "matched": sum(1 for r in rs if r.matched_expectation),
            }
            for kind, rs in by_kind.items()
        },
        "errors": [r.name for r in errors],
        "fails": [r.name for r in fails],
        "warnings": [r.name for r in warnings],
    }

    if fails:
        names = ", ".join(r.name for r in fails)
        status = CheckStatus.FAIL
        severity = Severity.CRITICAL
        description = (
            f"{len(fails)}/{len(results)} declared control(s) did NOT match "
            f"their declared expectation via a genuine hidden-test verdict: "
            f"{names}. A known-bad solution that is accepted, or a valid "
            "alternative that is rejected by the hidden suite, is direct "
            "evidence the oracle is either too permissive or too narrow."
        )
    elif errors:
        names = ", ".join(r.name for r in errors)
        status = CheckStatus.ERROR
        severity = Severity.MEDIUM
        description = (
            f"{len(errors)}/{len(results)} declared control(s) were rejected "
            f"by the scope or regression gate rather than the hidden suite: "
            f"{names}. This is a control-authoring problem (the overlay "
            "touches an out-of-scope file, or breaks pre-existing behavior "
            "incidentally) — it says nothing about hidden-test quality and "
            "should be fixed in the control, not treated as a benchmark "
            "defect."
        )
    elif warnings:
        names = ", ".join(r.name for r in warnings)
        status = CheckStatus.WARNING
        severity = Severity.LOW
        description = (
            f"{len(warnings)}/{len(results)} declared control(s) were "
            f"rejected by a timeout or grading error rather than a clean "
            f"hidden-test verdict: {names}. Ambiguous — review manually."
        )
    else:
        status = CheckStatus.PASS
        severity = Severity.INFO
        description = (
            f"All {len(results)} declared control(s) matched their declared "
            "expectation via a genuine hidden-test verdict."
        )

    return (
        IntegrityCheckResult(
            check_id="controls.declared_controls",
            category="controls",
            status=status,
            severity=severity,
            description=description,
            evidence=evidence,
            duration_ms=duration_ms,
        ),
        results,
    )
