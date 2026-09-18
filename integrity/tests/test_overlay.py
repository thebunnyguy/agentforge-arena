"""Unit tests for the verdict classifier and the determinism fingerprint,
built from hand-constructed GradeReport/RunScore objects — no real grading,
so these run instantly and pin down the exact classification rules.
"""

from afa_kernel.types import Gates, RunInput, RunStatus, RunScore, TestResult
from afa_runner.diffing import Diff
from afa_runner.grader import GradeReport, SuiteOutcome

from afa_integrity.model import Verdict
from afa_integrity.overlay import classify_verdict, diff_hash, outcome_fingerprint

PASS_TEST = TestResult(name="test_a", passed=True, weight=1.0)
FAIL_TEST = TestResult(name="test_b", passed=False, weight=1.0)


def _report(*, scope_ok=True, regression_passed=True, regression_errored=False,
            hidden_results=(PASS_TEST,), hidden_errored=False) -> GradeReport:
    gates = Gates(
        setup_ok=True,
        diff_exists=True,
        scope_ok=scope_ok,
        regression_pass=regression_passed and not regression_errored,
        no_timeout=True,
    )
    run_input = RunInput(status=RunStatus.VALID, gates=gates, hidden=hidden_results)
    regression = SuiteOutcome(
        results=(TestResult(name="reg", passed=regression_passed, weight=1.0),),
        all_passed=regression_passed,
        errored=regression_errored,
    )
    hidden = SuiteOutcome(results=hidden_results, all_passed=all(t.passed for t in hidden_results), errored=hidden_errored)
    diff = Diff(changed={"pkg/core.py": "x"}, deleted=(), files_changed=1, lines_added=1, lines_removed=0, touched_protected=not scope_ok, patch_text="--- a\n+++ b\n")
    return GradeReport(
        run_input=run_input, status=RunStatus.VALID, diff=diff,
        hidden=hidden, regression=regression, setup_ok=True, timed_out=False, notes="",
    )


def _score(report: GradeReport) -> RunScore:
    gate_product = report.run_input.gates.product()
    hidden = report.hidden.results
    t_hidden = (sum(t.weight for t in hidden if t.passed) / sum(t.weight for t in hidden)) if hidden else 0.0
    functional_pass = bool(gate_product) and len(hidden) > 0 and all(t.passed for t in hidden) and t_hidden > 0
    final_score = gate_product * t_hidden
    return RunScore(
        status=RunStatus.VALID, gate_product=gate_product, t_hidden=t_hidden, q=1.0,
        q_components={}, final_score=final_score, functional_pass=functional_pass, voided=False,
    )


def test_functional_pass_is_accepted():
    report = _report(hidden_results=(PASS_TEST,))
    score = _score(report)
    assert score.functional_pass is True
    assert classify_verdict(report, score) == Verdict.ACCEPTED


def test_scope_violation_is_rejected_by_scope_gate_even_if_hidden_looks_fine():
    report = _report(scope_ok=False, hidden_results=(PASS_TEST,))
    score = _score(report)
    # scope_ok=False forces gate_product=0, so functional_pass is False even
    # though every hidden test "passed" — scope must be checked BEFORE hidden.
    assert classify_verdict(report, score) == Verdict.REJECTED_BY_SCOPE_GATE


def test_regression_failure_is_rejected_by_regression_gate():
    report = _report(scope_ok=True, regression_passed=False, hidden_results=(PASS_TEST,))
    score = _score(report)
    assert classify_verdict(report, score) == Verdict.REJECTED_BY_REGRESSION_GATE


def test_hidden_suite_error_is_rejected_by_timeout_or_error():
    report = _report(scope_ok=True, regression_passed=True, hidden_results=(), hidden_errored=True)
    score = _score(report)
    assert classify_verdict(report, score) == Verdict.REJECTED_BY_TIMEOUT_OR_ERROR


def test_genuine_hidden_test_failure_is_rejected_by_hidden_test():
    report = _report(scope_ok=True, regression_passed=True, hidden_results=(FAIL_TEST,))
    score = _score(report)
    assert classify_verdict(report, score) == Verdict.REJECTED_BY_HIDDEN_TEST


def test_fingerprint_ignores_notes_and_timing():
    r1 = _report(hidden_results=(PASS_TEST,))
    r2 = GradeReport(
        run_input=r1.run_input, status=r1.status, diff=r1.diff,
        hidden=r1.hidden, regression=r1.regression, setup_ok=r1.setup_ok,
        timed_out=r1.timed_out, notes="COMPLETELY DIFFERENT NOTES WITH TIMINGS 12:34:56",
    )
    s = _score(r1)
    assert outcome_fingerprint(r1, s) == outcome_fingerprint(r2, s)


def test_fingerprint_differs_when_hidden_results_differ():
    r1 = _report(hidden_results=(PASS_TEST,))
    r2 = _report(hidden_results=(FAIL_TEST,))
    s1, s2 = _score(r1), _score(r2)
    assert outcome_fingerprint(r1, s1) != outcome_fingerprint(r2, s2)


def test_diff_hash_stable_for_identical_patch_text():
    d1 = Diff(changed={}, deleted=(), files_changed=1, lines_added=1, lines_removed=0, touched_protected=False, patch_text="same")
    d2 = Diff(changed={}, deleted=(), files_changed=1, lines_added=1, lines_removed=0, touched_protected=False, patch_text="same")
    assert diff_hash(d1) == diff_hash(d2)


def test_diff_hash_differs_for_different_patch_text():
    d1 = Diff(changed={}, deleted=(), files_changed=1, lines_added=1, lines_removed=0, touched_protected=False, patch_text="a")
    d2 = Diff(changed={}, deleted=(), files_changed=1, lines_added=1, lines_removed=0, touched_protected=False, patch_text="b")
    assert diff_hash(d1) != diff_hash(d2)
