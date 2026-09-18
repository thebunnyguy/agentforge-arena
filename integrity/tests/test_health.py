"""Unit tests for the health-status precedence function in isolation — no
grading, no I/O. This is the piece that must be independently correct: get
this wrong and every audit's headline status is wrong regardless of how
correct the underlying checks are.
"""

from afa_integrity.health import determine_health_status
from afa_integrity.model import (
    CheckStatus,
    ControlKind,
    ControlResult,
    IntegrityCheckResult,
    Severity,
    Verdict,
)


def _check(check_id, status, category="test") -> IntegrityCheckResult:
    return IntegrityCheckResult(
        check_id=check_id,
        category=category,
        status=status,
        severity=Severity.INFO,
        description=f"{check_id} description",
    )


def _control(name, kind, status, expected_accept=False) -> ControlResult:
    return ControlResult(
        name=name,
        kind=kind,
        description="",
        expected_accept=expected_accept,
        verdict=Verdict.ACCEPTED if status == CheckStatus.FAIL and not expected_accept else Verdict.REJECTED_BY_HIDDEN_TEST,
        final_score=1.0,
        functional_pass=True,
        matched_expectation=(status == CheckStatus.PASS),
        status=status,
    )


# A QUICK-shaped run: no mutation testing, no isolation probe.
QUICK_PASS_CHECKS = [
    _check("reference.solution_validation", CheckStatus.PASS),
    _check("noop.unmodified_baseline", CheckStatus.PASS),
    _check("controls.declared_controls", CheckStatus.PASS),
    _check("determinism.repeated_grading", CheckStatus.PASS),
]

# A FULL-shaped run: everything QUICK has, plus mutation testing and the
# isolation probe actually present in the checks list.
FULL_PASS_CHECKS = QUICK_PASS_CHECKS + [
    _check("mutation.generic_ast_mutants", CheckStatus.PASS),
    _check(
        "isolation.hidden_test_readability",
        CheckStatus.UNVERIFIABLE,
        category="isolation_limitation",
    ),
]


def test_missing_full_mode_evidence_is_provisional():
    """determine_health_status no longer takes a `mode` argument — whether
    FULL-only evidence was collected is read from which checks are actually
    present, so `--quick --mutation` (mutation ran, isolation probe did not)
    can never contradict itself the way a mode-keyed message could."""
    status, reason = determine_health_status(QUICK_PASS_CHECKS, [])
    assert status.value == "provisional"
    assert "mutation testing" in reason
    assert "isolation probe" in reason


def test_mutation_ran_without_isolation_probe_only_flags_isolation_probe():
    checks = QUICK_PASS_CHECKS + [_check("mutation.generic_ast_mutants", CheckStatus.PASS)]
    status, reason = determine_health_status(checks, [])
    assert status.value == "provisional"
    assert "mutation testing" not in reason
    assert "isolation probe" in reason


def test_full_evidence_all_pass_is_healthy():
    status, reason = determine_health_status(FULL_PASS_CHECKS, [])
    assert status.value == "healthy"
    assert reason == "All checks passed with no outstanding findings."


def test_no_controls_declared_is_provisional_even_with_full_evidence():
    checks = [c for c in FULL_PASS_CHECKS if c.check_id != "controls.declared_controls"]
    checks.append(_check("controls.declared_controls", CheckStatus.SKIPPED))
    status, reason = determine_health_status(checks, [])
    assert status.value == "provisional"


def test_any_fail_is_invalid():
    checks = FULL_PASS_CHECKS + [_check("noop.unmodified_baseline", CheckStatus.FAIL)]
    status, reason = determine_health_status(checks, [])
    assert status.value == "invalid"
    assert "noop.unmodified_baseline" in reason


def test_warning_without_fail_is_needs_review():
    checks = QUICK_PASS_CHECKS + [_check("mutation.generic_ast_mutants", CheckStatus.WARNING)]
    status, reason = determine_health_status(checks, [])
    assert status.value == "needs_review"


def test_unverifiable_without_fail_or_warning_is_unverifiable():
    checks = FULL_PASS_CHECKS + [_check("reference.solution_validation", CheckStatus.UNVERIFIABLE)]
    status, _ = determine_health_status(checks, [])
    assert status.value == "unverifiable"


def test_isolation_check_is_excluded_from_status_entirely():
    status, reason = determine_health_status(FULL_PASS_CHECKS, [])
    assert status.value == "healthy", (
        "the isolation probe always reads UNVERIFIABLE under LocalSandbox; "
        "if it isn't excluded, every task in the pack would be UNVERIFIABLE "
        "and the status field would carry no information"
    )


def test_known_bad_control_accepted_is_invalid():
    controls = [_control("evil", ControlKind.KNOWN_BAD, CheckStatus.FAIL)]
    status, reason = determine_health_status(FULL_PASS_CHECKS, controls)
    assert status.value == "invalid"
    assert "known-bad control 'evil'" in reason
    assert "ACCEPTED" in reason


def test_semantic_mutant_survives_is_needs_review_not_invalid():
    controls = [_control("mutant1", ControlKind.SEMANTIC_MUTANT, CheckStatus.FAIL)]
    status, reason = determine_health_status(FULL_PASS_CHECKS, controls)
    assert status.value == "needs_review"
    assert "semantic mutant 'mutant1'" in reason


def test_alternative_rejected_is_needs_review_not_invalid():
    controls = [_control("alt1", ControlKind.ALTERNATIVE, CheckStatus.FAIL, expected_accept=True)]
    status, reason = determine_health_status(FULL_PASS_CHECKS, controls)
    assert status.value == "needs_review"
    assert "alternative solution 'alt1'" in reason


def test_control_error_is_needs_review_not_invalid():
    controls = [_control("bad_control", ControlKind.KNOWN_BAD, CheckStatus.ERROR)]
    status, reason = determine_health_status(FULL_PASS_CHECKS, controls)
    assert status.value == "needs_review"
    assert "control-authoring issue" in reason


def test_precedence_invalid_beats_everything():
    checks = FULL_PASS_CHECKS + [
        _check("noop.unmodified_baseline", CheckStatus.FAIL),
        _check("some_other.check", CheckStatus.WARNING),
        _check("reference.solution_validation", CheckStatus.UNVERIFIABLE),
    ]
    status, _ = determine_health_status(checks, [])
    assert status.value == "invalid"


def test_precedence_needs_review_beats_unverifiable_and_provisional():
    checks = FULL_PASS_CHECKS + [
        _check("some_other.check", CheckStatus.WARNING),
        _check("reference.solution_validation", CheckStatus.UNVERIFIABLE),
        _check("some.other", CheckStatus.SKIPPED),
    ]
    status, _ = determine_health_status(checks, [])
    assert status.value == "needs_review"


def test_precedence_unverifiable_beats_provisional():
    checks = FULL_PASS_CHECKS + [
        _check("reference.solution_validation", CheckStatus.UNVERIFIABLE),
        _check("some.other", CheckStatus.SKIPPED),
    ]
    status, _ = determine_health_status(checks, [])
    assert status.value == "unverifiable"
