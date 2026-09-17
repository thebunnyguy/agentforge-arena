"""Repeated-grading determinism / flakiness analysis across a SAMPLE of
artifacts (mission §11), beyond what the reference check already covers on
its own.

The reference check (checks/reference.py) already repeat-grades the reference
solution as part of validating gate 1. This check extends the same idea to
other artifacts a real benchmark run might grade repeatedly: the no-op
baseline always, and — when the caller has them (FULL-mode mutants/controls)
— a small sample of those too. Any variance regrading an IDENTICAL diff is a
harness/grader bug, never a task property (framework §5.3/§9): this check's
job is only to say clearly which artifact, if any, showed it.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from afa_runner.diffing import Diff
from afa_runner.sandbox import Sandbox
from afa_runner.task import Task

from ..model import CheckStatus, IntegrityCheckResult, Severity
from ..overlay import grade_diff, outcome_fingerprint

DEFAULT_REPEATS = 3


@dataclass(frozen=True)
class DeterminismSample:
    label: str
    diff: Diff
    repeats: int = DEFAULT_REPEATS
    timeout_s: int | None = None


def _regrade(task: Task, sample: DeterminismSample, sandbox: Sandbox) -> dict:
    outcomes = []
    fingerprints = []
    for i in range(sample.repeats):
        report, score = grade_diff(task, sample.diff, sandbox, timeout_s=sample.timeout_s)
        fp = outcome_fingerprint(report, score)
        fingerprints.append(fp)
        outcomes.append(
            {
                "attempt": i,
                "final_score": score.final_score,
                "functional_pass": score.functional_pass,
                "fingerprint": fp,
            }
        )
    distinct = sorted(set(fingerprints))
    return {
        "label": sample.label,
        "n_repeats": sample.repeats,
        "deterministic": len(distinct) == 1,
        "n_distinct_outcomes": len(distinct),
        "outcomes": outcomes,
    }


def run_determinism_check(
    task: Task, samples: list[DeterminismSample], sandbox: Sandbox
) -> IntegrityCheckResult:
    start = time.monotonic()
    if not samples:
        return IntegrityCheckResult(
            check_id="determinism.repeated_grading",
            category="determinism",
            status=CheckStatus.SKIPPED,
            severity=Severity.LOW,
            description="No samples supplied for repeated-grading analysis.",
            evidence={},
            duration_ms=int((time.monotonic() - start) * 1000),
        )

    results = [_regrade(task, s, sandbox) for s in samples]
    duration_ms = int((time.monotonic() - start) * 1000)
    flaky = [r for r in results if not r["deterministic"]]
    evidence = {"samples": results}

    if flaky:
        labels = ", ".join(r["label"] for r in flaky)
        detail_lines = []
        for r in flaky:
            passes = [o["functional_pass"] for o in r["outcomes"]]
            detail_lines.append(f"{r['label']}: functional_pass sequence {passes}")
        return IntegrityCheckResult(
            check_id="determinism.repeated_grading",
            category="determinism",
            status=CheckStatus.FAIL,
            severity=Severity.CRITICAL,
            description=(
                f"GRADER_NONDETERMINISM: {len(flaky)}/{len(results)} sample(s) "
                f"produced different outcomes across repeated grades of the "
                f"IDENTICAL diff: {labels}. " + " | ".join(detail_lines)
            ),
            evidence=evidence,
            duration_ms=duration_ms,
        )

    return IntegrityCheckResult(
        check_id="determinism.repeated_grading",
        category="determinism",
        status=CheckStatus.PASS,
        severity=Severity.INFO,
        description=(
            f"All {len(results)} sampled artifact(s) graded identically "
            "across their repeats."
        ),
        evidence=evidence,
        duration_ms=duration_ms,
    )
