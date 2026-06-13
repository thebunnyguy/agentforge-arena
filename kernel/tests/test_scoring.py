"""Tests for afa_kernel.scoring (framework §1).

Each expected value is recomputed from first principles in the test (or in the
inline comments) and asserted independently — never echoed back from the
implementation. Canonical anchors come from the build spec / framework §1.
"""

from __future__ import annotations

import pytest

from afa_kernel.scoring import (
    QUALITY_WEIGHTS,
    compute_quality,
    compute_t_hidden,
    score_run,
)
from afa_kernel.types import (
    Gates,
    QualityInputs,
    RunInput,
    RunStatus,
    SecurityFindings,
    TestResult,
)

TOL = 1e-4


# --------------------------------------------------------------------------- #
# Fixtures / helpers
# --------------------------------------------------------------------------- #

def all_pass_gates() -> Gates:
    return Gates(
        setup_ok=True,
        diff_exists=True,
        scope_ok=True,
        regression_pass=True,
        no_timeout=True,
    )


def make_hidden(n_pass: int, n_total: int) -> tuple[TestResult, ...]:
    return tuple(
        TestResult(name=f"t{i}", passed=(i < n_pass)) for i in range(n_total)
    )


# --------------------------------------------------------------------------- #
# QUALITY_WEIGHTS sanity
# --------------------------------------------------------------------------- #

def test_quality_weights_sum_to_one():
    assert sum(QUALITY_WEIGHTS.values()) == pytest.approx(1.0, abs=1e-12)


def test_quality_weights_values():
    # The documented default weights.
    assert QUALITY_WEIGHTS == {
        "lint": 0.20,
        "typecheck": 0.25,
        "static": 0.20,
        "security": 0.20,
        "parsimony": 0.15,
    }


# --------------------------------------------------------------------------- #
# compute_t_hidden
# --------------------------------------------------------------------------- #

def test_t_hidden_no_tests_is_zero():
    run = RunInput(status=RunStatus.VALID, gates=all_pass_gates(), hidden=())
    assert compute_t_hidden(run) == 0.0


def test_t_hidden_equal_weights_seven_of_ten():
    # 7 of 10 equal-weight tests -> 0.7 (scoring worked example anchor).
    run = RunInput(
        status=RunStatus.VALID, gates=all_pass_gates(), hidden=make_hidden(7, 10)
    )
    assert compute_t_hidden(run) == pytest.approx(0.7, abs=TOL)


def test_t_hidden_all_pass_is_one():
    run = RunInput(
        status=RunStatus.VALID, gates=all_pass_gates(), hidden=make_hidden(5, 5)
    )
    assert compute_t_hidden(run) == pytest.approx(1.0, abs=TOL)


def test_t_hidden_all_fail_is_zero():
    run = RunInput(
        status=RunStatus.VALID, gates=all_pass_gates(), hidden=make_hidden(0, 4)
    )
    assert compute_t_hidden(run) == 0.0


def test_t_hidden_weighted():
    # passed test weight 3, failed test weight 1 -> 3 / 4 = 0.75.
    hidden = (
        TestResult(name="a", passed=True, weight=3.0),
        TestResult(name="b", passed=False, weight=1.0),
    )
    run = RunInput(status=RunStatus.VALID, gates=all_pass_gates(), hidden=hidden)
    assert compute_t_hidden(run) == pytest.approx(0.75, abs=TOL)


def test_t_hidden_zero_total_weight_is_zero():
    # Degenerate: all weights zero -> no signal -> 0.0 (no div by zero).
    hidden = (
        TestResult(name="a", passed=True, weight=0.0),
        TestResult(name="b", passed=True, weight=0.0),
    )
    run = RunInput(status=RunStatus.VALID, gates=all_pass_gates(), hidden=hidden)
    assert compute_t_hidden(run) == 0.0


def test_zero_total_weight_is_not_a_functional_pass():
    # X must stay consistent with S: an all-zero-weight hidden suite scores
    # S = 0, so even with every test "passed" it must NOT register as a pass.
    hidden = (
        TestResult(name="a", passed=True, weight=0.0),
        TestResult(name="b", passed=True, weight=0.0),
    )
    run = RunInput(status=RunStatus.VALID, gates=all_pass_gates(), hidden=hidden)
    score = score_run(run)
    assert score.t_hidden == 0.0
    assert score.final_score == 0.0
    assert score.functional_pass is False


# --------------------------------------------------------------------------- #
# compute_quality — component formulas
# --------------------------------------------------------------------------- #

def test_quality_all_unavailable_is_one_empty_components():
    # Every field None -> Q := 1.0, components empty (anchor).
    q, comps = compute_quality(QualityInputs())
    assert q == pytest.approx(1.0, abs=1e-12)
    assert comps == {}


def test_quality_lint_only():
    # lint_new_errors=5 -> q_lint = 1 - 5/10 = 0.5; only component -> Q = 0.5.
    q, comps = compute_quality(QualityInputs(lint_new_errors=5))
    assert comps == {"lint": pytest.approx(0.5, abs=TOL)}
    assert q == pytest.approx(0.5, abs=TOL)


def test_quality_lint_clamped_at_zero():
    # lint_new_errors=20 -> 1 - 20/10 = -1 -> clamped to 0.
    q, comps = compute_quality(QualityInputs(lint_new_errors=20))
    assert comps["lint"] == pytest.approx(0.0, abs=TOL)
    assert q == pytest.approx(0.0, abs=TOL)


def test_quality_lint_zero_errors_is_one():
    q, comps = compute_quality(QualityInputs(lint_new_errors=0))
    assert comps["lint"] == pytest.approx(1.0, abs=TOL)


def test_quality_typecheck_true_and_false():
    q_ok, comps_ok = compute_quality(QualityInputs(typecheck_ok=True))
    assert comps_ok["typecheck"] == 1.0
    assert q_ok == pytest.approx(1.0, abs=TOL)

    q_bad, comps_bad = compute_quality(QualityInputs(typecheck_ok=False))
    assert comps_bad["typecheck"] == 0.0
    assert q_bad == pytest.approx(0.0, abs=TOL)


def test_quality_static_negative_findings_no_penalty():
    # static_new_findings = -5 -> max(0, -5) = 0 -> q_static = 1.
    q, comps = compute_quality(QualityInputs(static_new_findings=-5.0))
    assert comps["static"] == pytest.approx(1.0, abs=TOL)


def test_quality_static_findings_linear():
    # static_new_findings = 4 -> 1 - 4/10 = 0.6.
    q, comps = compute_quality(QualityInputs(static_new_findings=4.0))
    assert comps["static"] == pytest.approx(0.6, abs=TOL)


def test_quality_static_clamped_at_zero():
    # static_new_findings = 25 -> 1 - 25/10 = -1.5 -> clamped to 0.
    q, comps = compute_quality(QualityInputs(static_new_findings=25.0))
    assert comps["static"] == pytest.approx(0.0, abs=TOL)


def test_quality_security_weighting():
    # high=3,medium=1,low=0.25 severity weights.
    # one high -> weighted = 3 -> q_sec = 1 - 3/3 = 0.
    q_h, comps_h = compute_quality(
        QualityInputs(security_new=SecurityFindings(high=1))
    )
    assert comps_h["security"] == pytest.approx(0.0, abs=TOL)

    # one medium -> weighted = 1 -> q_sec = 1 - 1/3 = 0.6667.
    q_m, comps_m = compute_quality(
        QualityInputs(security_new=SecurityFindings(medium=1))
    )
    assert comps_m["security"] == pytest.approx(2.0 / 3.0, abs=TOL)

    # clean (all zero) -> weighted = 0 -> q_sec = 1.
    q_c, comps_c = compute_quality(
        QualityInputs(security_new=SecurityFindings())
    )
    assert comps_c["security"] == pytest.approx(1.0, abs=TOL)


def test_quality_security_clamped_at_zero():
    # two highs -> weighted = 6 -> 1 - 6/3 = -1 -> clamped to 0.
    q, comps = compute_quality(
        QualityInputs(security_new=SecurityFindings(high=2))
    )
    assert comps["security"] == pytest.approx(0.0, abs=TOL)


# --------------------------------------------------------------------------- #
# compute_quality — parsimony piecewise (2/8 curve from docstring)
# --------------------------------------------------------------------------- #

def test_parsimony_flat_region_rho_le_2():
    # lines_added=80, reference_lines=40 -> rho=2.0 (boundary) -> q_pars=1.
    q, comps = compute_quality(
        QualityInputs(lines_added=80, reference_lines=40)
    )
    assert comps["parsimony"] == pytest.approx(1.0, abs=TOL)


def test_parsimony_anchor_rho_2_4():
    # Anchor: lines_added=96, reference_lines=40 -> rho=2.4 -> (8-2.4)/6 = 0.93333.
    q, comps = compute_quality(
        QualityInputs(lines_added=96, reference_lines=40)
    )
    assert comps["parsimony"] == pytest.approx((8 - 2.4) / 6, abs=TOL)
    assert comps["parsimony"] == pytest.approx(0.93333, abs=TOL)


def test_parsimony_midband_rho_5():
    # lines_added=50, reference_lines=10 -> rho=5 -> (8-5)/6 = 0.5.
    q, comps = compute_quality(
        QualityInputs(lines_added=50, reference_lines=10)
    )
    assert comps["parsimony"] == pytest.approx(0.5, abs=TOL)


def test_parsimony_zero_at_rho_8():
    # lines_added=80, reference_lines=10 -> rho=8 -> else branch -> 0.
    q, comps = compute_quality(
        QualityInputs(lines_added=80, reference_lines=10)
    )
    assert comps["parsimony"] == pytest.approx(0.0, abs=TOL)


def test_parsimony_zero_above_rho_8():
    # lines_added=200, reference_lines=10 -> rho=20 -> 0.
    q, comps = compute_quality(
        QualityInputs(lines_added=200, reference_lines=10)
    )
    assert comps["parsimony"] == pytest.approx(0.0, abs=TOL)


def test_parsimony_floor_on_tiny_reference():
    # reference_lines=2 floored to 10; lines_added=5 -> rho=0.5 -> q_pars=1.
    q, comps = compute_quality(
        QualityInputs(lines_added=5, reference_lines=2)
    )
    assert comps["parsimony"] == pytest.approx(1.0, abs=TOL)


def test_parsimony_requires_both_inputs():
    # lines_added present but reference_lines None -> parsimony unavailable.
    _, comps_a = compute_quality(QualityInputs(lines_added=100))
    assert "parsimony" not in comps_a
    # reference_lines present but lines_added None -> parsimony unavailable.
    _, comps_b = compute_quality(QualityInputs(reference_lines=40))
    assert "parsimony" not in comps_b


# --------------------------------------------------------------------------- #
# compute_quality — renormalisation
# --------------------------------------------------------------------------- #

def test_quality_renormalisation_two_components():
    # lint (q=1.0, w=.20) + typecheck=False (q=0.0, w=.25).
    # renorm denom = .45 ; Q = (.20*1 + .25*0)/.45 = 0.44444.
    q, comps = compute_quality(
        QualityInputs(lint_new_errors=0, typecheck_ok=False)
    )
    assert set(comps) == {"lint", "typecheck"}
    assert q == pytest.approx((0.20 * 1.0 + 0.25 * 0.0) / 0.45, abs=TOL)
    assert q == pytest.approx(0.44444, abs=TOL)


def test_quality_full_worked_example():
    # Scoring worked example (framework §1):
    # lint=0 (q=1), typecheck=False (q=0), static=0 (q=1), security none (q=1),
    # lines_added=96 reference_lines=40 -> q_pars=0.93333. All five available so
    # weights already sum to 1: Q = .20*1 + .25*0 + .20*1 + .20*1 + .15*0.93333.
    q, comps = compute_quality(
        QualityInputs(
            lint_new_errors=0,
            typecheck_ok=False,
            static_new_findings=0.0,
            security_new=SecurityFindings(),
            lines_added=96,
            reference_lines=40,
        )
    )
    expected = (
        0.20 * 1.0
        + 0.25 * 0.0
        + 0.20 * 1.0
        + 0.20 * 1.0
        + 0.15 * ((8 - 2.4) / 6)
    )
    assert expected == pytest.approx(0.74, abs=TOL)
    assert q == pytest.approx(0.74, abs=TOL)
    assert set(comps) == {"lint", "typecheck", "static", "security", "parsimony"}


# --------------------------------------------------------------------------- #
# score_run
# --------------------------------------------------------------------------- #

def test_score_run_worked_example():
    # Full anchor: S = 1 * 0.7 * (0.85 + 0.15*0.74) = 0.6727 ; X = False.
    run = RunInput(
        status=RunStatus.VALID,
        gates=all_pass_gates(),
        hidden=make_hidden(7, 10),
        quality=QualityInputs(
            lint_new_errors=0,
            typecheck_ok=False,
            static_new_findings=0.0,
            security_new=SecurityFindings(),
            lines_added=96,
            reference_lines=40,
        ),
    )
    score = score_run(run)
    assert score.gate_product == 1
    assert score.t_hidden == pytest.approx(0.7, abs=TOL)
    assert score.q == pytest.approx(0.74, abs=TOL)
    assert score.final_score == pytest.approx(0.6727, abs=TOL)
    # multiplier = 0.85 + 0.15*0.74 = 0.961
    assert score.final_score == pytest.approx(0.7 * 0.961, abs=TOL)
    assert score.functional_pass is False  # not all hidden passed
    assert score.voided is False
    assert score.status is RunStatus.VALID


def test_score_run_functional_pass_all_hidden_pass():
    # G=1, all hidden pass -> X=True. With all quality unavailable, Q=1,
    # multiplier=1, S = 1*1*1 = 1.0.
    run = RunInput(
        status=RunStatus.VALID,
        gates=all_pass_gates(),
        hidden=make_hidden(5, 5),
        quality=QualityInputs(),
    )
    score = score_run(run)
    assert score.q == pytest.approx(1.0, abs=1e-12)
    assert score.q_components == {}
    assert score.final_score == pytest.approx(1.0, abs=TOL)
    assert score.functional_pass is True
    assert score.voided is False


def test_score_run_all_quality_unavailable_multiplier_one():
    # All-quality-unavailable anchor: Q=1.0, multiplier=1.0.
    # G=1, T_hidden=0.7 -> S = 0.7 * 1.0 = 0.7.
    run = RunInput(
        status=RunStatus.VALID,
        gates=all_pass_gates(),
        hidden=make_hidden(7, 10),
        quality=QualityInputs(),
    )
    score = score_run(run)
    assert score.q == pytest.approx(1.0, abs=1e-12)
    assert score.final_score == pytest.approx(0.7, abs=TOL)


def test_score_run_gate_failure_zeroes_score():
    # One failed gate -> G=0 -> S=0, even with perfect hidden + quality.
    gates = Gates(
        setup_ok=True,
        diff_exists=True,
        scope_ok=False,  # violated
        regression_pass=True,
        no_timeout=True,
    )
    run = RunInput(
        status=RunStatus.VALID,
        gates=gates,
        hidden=make_hidden(5, 5),
        quality=QualityInputs(lint_new_errors=0),
    )
    score = score_run(run)
    assert score.gate_product == 0
    assert score.final_score == 0.0
    assert score.functional_pass is False  # X requires G==1


def test_score_run_timeout_natural_zero():
    # TIMEOUT: no_timeout gate False -> G=0 -> S=0. Not voided (counts in n).
    gates = Gates(
        setup_ok=True,
        diff_exists=True,
        scope_ok=True,
        regression_pass=True,
        no_timeout=False,  # timed out
    )
    run = RunInput(
        status=RunStatus.TIMEOUT,
        gates=gates,
        hidden=make_hidden(5, 5),
        quality=QualityInputs(),
    )
    score = score_run(run)
    assert score.gate_product == 0
    assert score.final_score == 0.0
    assert score.functional_pass is False
    assert score.voided is False
    assert score.status is RunStatus.TIMEOUT


def test_score_run_infra_failure_voided():
    # INFRA_FAILURE anchor: voided=True, final_score=0.0, functional_pass=False.
    run = RunInput(
        status=RunStatus.INFRA_FAILURE,
        gates=all_pass_gates(),
        hidden=make_hidden(5, 5),
        quality=QualityInputs(lint_new_errors=0),
    )
    score = score_run(run)
    assert score.voided is True
    assert score.final_score == 0.0
    assert score.functional_pass is False
    assert score.status is RunStatus.INFRA_FAILURE


def test_score_run_agent_error_counts_as_failure():
    # AGENT_ERROR with diff_exists False -> G=0 -> S=0, not voided.
    gates = Gates(
        setup_ok=True,
        diff_exists=False,
        scope_ok=True,
        regression_pass=True,
        no_timeout=True,
    )
    run = RunInput(
        status=RunStatus.AGENT_ERROR,
        gates=gates,
        hidden=(),
        quality=QualityInputs(),
    )
    score = score_run(run)
    assert score.final_score == 0.0
    assert score.voided is False
    assert score.functional_pass is False


def test_score_run_no_hidden_tests_not_functional_pass():
    # G=1 but no hidden tests -> T_hidden=0 -> S=0 and X=False (len==0 guard).
    run = RunInput(
        status=RunStatus.VALID,
        gates=all_pass_gates(),
        hidden=(),
        quality=QualityInputs(),
    )
    score = score_run(run)
    assert score.t_hidden == 0.0
    assert score.final_score == 0.0
    assert score.functional_pass is False


def test_score_run_final_score_in_unit_interval():
    # Property: S in [0,1] across a sweep of inputs.
    for n_pass in range(0, 6):
        for errs in (0, 3, 10, 50):
            run = RunInput(
                status=RunStatus.VALID,
                gates=all_pass_gates(),
                hidden=make_hidden(n_pass, 5),
                quality=QualityInputs(lint_new_errors=errs),
            )
            s = score_run(run).final_score
            assert 0.0 <= s <= 1.0


def test_score_run_returns_components_used():
    # q_components should reflect exactly the active components.
    run = RunInput(
        status=RunStatus.VALID,
        gates=all_pass_gates(),
        hidden=make_hidden(5, 5),
        quality=QualityInputs(lint_new_errors=0, typecheck_ok=True),
    )
    score = score_run(run)
    assert set(score.q_components) == {"lint", "typecheck"}
