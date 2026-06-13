"""Single source-of-truth regression test for EVERY canonical numeric anchor.

This module is deliberately independent of the per-module test files: it imports
exclusively through the public package API (``afa_kernel``) so it also exercises
the ``__init__`` re-export wiring, and it asserts the exact contract values from
the v0.1 build spec / EVALUATION_FRAMEWORK.md.

Conventions (per the build spec):
  * floats: ``pytest.approx(abs=1e-4)``
  * rationals (pass@k, pass_rate, pooled rate): exact equality

Every expected value is the contract anchor, recomputed independently from the
documented formula — never echoed back from an implementation.
"""

from __future__ import annotations

import math

import pytest

import afa_kernel as afa
from afa_kernel import (
    Gates,
    QualityInputs,
    RankInput,
    RunInput,
    RunStatus,
    SecurityFindings,
    TaskDomainContribution,
    TestResult,
    aggregate_runs,
    domain_score,
    pass_at_k,
    rank_by_lcb,
    score_run,
    stability,
    t_critical_one_sided_95,
    wilson_interval,
    wilson_lower_bound,
)

ABS = 1e-4


# --------------------------------------------------------------------------- #
# Local helpers (independent of the kernel)
# --------------------------------------------------------------------------- #

def _all_pass_gates() -> Gates:
    return Gates(
        setup_ok=True,
        diff_exists=True,
        scope_ok=True,
        regression_pass=True,
        no_timeout=True,
    )


def _hidden(n_pass: int, n_total: int) -> tuple[TestResult, ...]:
    return tuple(
        TestResult(name=f"t{i}", passed=(i < n_pass)) for i in range(n_total)
    )


def _runscore(
    final_score: float,
    *,
    functional_pass: bool,
    status: RunStatus = RunStatus.VALID,
):
    """A minimal RunScore carrying only the fields aggregation reads."""
    return afa.RunScore(
        status=status,
        gate_product=1 if functional_pass else 0,
        t_hidden=final_score,
        q=1.0,
        q_components={},
        final_score=final_score,
        functional_pass=functional_pass,
        voided=(status is RunStatus.INFRA_FAILURE),
    )


# --------------------------------------------------------------------------- #
# CONFIDENCE anchors (framework §3)
# --------------------------------------------------------------------------- #

def test_anchor_wilson_interval_3_of_5():
    low, high = wilson_interval(3, 5)
    assert low == pytest.approx(0.2307, abs=ABS)
    assert high == pytest.approx(0.8824, abs=ABS)


def test_anchor_wilson_lower_bound_3_of_3():
    assert wilson_lower_bound(3, 3) == pytest.approx(0.4385, abs=ABS)


def test_anchor_wilson_lower_bound_18_of_20():
    assert wilson_lower_bound(18, 20) == pytest.approx(0.6990, abs=ABS)


def test_anchor_more_evidence_outranks_thin_perfect():
    # 18/20 (p=0.9) must out-rank a thin 3/3 (p=1.0): 0.6990 > 0.4385.
    assert wilson_lower_bound(18, 20) > wilson_lower_bound(3, 3)


def test_anchor_wilson_n_zero_full_interval():
    assert wilson_interval(0, 0) == (0.0, 1.0)


def test_anchor_pass_at_k_5_2_3_exact():
    # Exact: 1 - C(3,3)/C(5,3) = 1 - 1/10 = 9/10. Rational -> exact equality.
    assert pass_at_k(5, 2, 3) == 0.9
    assert pass_at_k(5, 2, 3) == 1.0 - math.comb(3, 3) / math.comb(5, 3)


def test_anchor_pass_at_1_identity():
    # pass@1 == c/n by construction. The estimator computes 1 - C(n-c,1)/C(n,1)
    # = 1 - (n-c)/n, whose subtraction can leave a sub-ULP rounding residue
    # (e.g. 0.19999999999999996 for c=1,n=5), so the identity is asserted to
    # float tolerance rather than bit-exact equality.
    for n in (1, 2, 5, 10):
        for c in range(0, n + 1):
            assert pass_at_k(n, c, 1) == pytest.approx(c / n, abs=1e-12)


def test_anchor_t_critical_table():
    assert t_critical_one_sided_95(4) == pytest.approx(2.132, abs=ABS)
    assert t_critical_one_sided_95(9) == pytest.approx(1.833, abs=ABS)
    # df > 30 collapses to the normal limit.
    assert t_critical_one_sided_95(31) == pytest.approx(1.645, abs=ABS)
    assert t_critical_one_sided_95(100) == pytest.approx(1.645, abs=ABS)


def test_anchor_stability_curve():
    assert stability(0.0) == pytest.approx(1.0, abs=ABS)
    assert stability(0.25) == pytest.approx(0.5, abs=ABS)
    assert stability(0.5) == pytest.approx(0.0, abs=ABS)
    assert stability(0.6) == pytest.approx(0.0, abs=ABS)  # clamped


# --------------------------------------------------------------------------- #
# SCORING anchors (framework §1)
# --------------------------------------------------------------------------- #

def test_anchor_scoring_worked_example():
    # 7/10 hidden equal weights -> T_hidden=0.7; all gates pass -> G=1.
    # lint=0 (q_lint=1), typecheck False (q_type=0), static=0 (q_static=1),
    # security none (q_sec=1), lines_added=96 reference_lines=40 -> rho=2.4,
    # q_pars=(8-2.4)/6=0.93333.
    # Q = .20*1 + .25*0 + .20*1 + .20*1 + .15*0.93333 = 0.74.
    # multiplier = 0.85 + 0.15*0.74 = 0.961 ; S = 1*0.7*0.961 = 0.6727 ; X False.
    run = RunInput(
        status=RunStatus.VALID,
        gates=_all_pass_gates(),
        hidden=_hidden(7, 10),
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
    assert score.t_hidden == pytest.approx(0.7, abs=ABS)
    assert score.q == pytest.approx(0.74, abs=ABS)
    assert score.q_components["parsimony"] == pytest.approx((8 - 2.4) / 6, abs=ABS)
    assert score.final_score == pytest.approx(0.6727, abs=ABS)
    assert score.functional_pass is False
    assert score.voided is False


def test_anchor_all_quality_unavailable_q_one_multiplier_one():
    # Every QualityInputs field None -> Q=1.0, multiplier=1.0.
    run = RunInput(
        status=RunStatus.VALID,
        gates=_all_pass_gates(),
        hidden=_hidden(7, 10),
        quality=QualityInputs(),
    )
    score = score_run(run)
    assert score.q == pytest.approx(1.0, abs=ABS)
    assert score.q_components == {}
    # multiplier 1.0 -> S = G * T_hidden * 1 = 0.7.
    assert score.final_score == pytest.approx(0.7, abs=ABS)


def test_anchor_infra_failure_voided():
    # INFRA_FAILURE -> voided=True, final_score=0.0, functional_pass=False.
    run = RunInput(
        status=RunStatus.INFRA_FAILURE,
        gates=_all_pass_gates(),
        hidden=_hidden(5, 5),
        quality=QualityInputs(lint_new_errors=0),
    )
    score = score_run(run)
    assert score.voided is True
    assert score.final_score == 0.0
    assert score.functional_pass is False


# --------------------------------------------------------------------------- #
# AGGREGATE anchors (framework §2)
# --------------------------------------------------------------------------- #

def _aggregate_worked_runs():
    # Five VALID-bucket runs S=[0.94,0.34,0.91,0.00,0.97]; three functional
    # passes; the 0.00 is a TIMEOUT; plus one voided INFRA_FAILURE attempt.
    return [
        _runscore(0.94, functional_pass=True),
        _runscore(0.34, functional_pass=False),
        _runscore(0.91, functional_pass=True),
        _runscore(0.00, functional_pass=False, status=RunStatus.TIMEOUT),
        _runscore(0.97, functional_pass=True),
        _runscore(0.00, functional_pass=False, status=RunStatus.INFRA_FAILURE),
    ]


def test_anchor_aggregate_worked_example():
    agg = aggregate_runs(_aggregate_worked_runs())
    assert agg.n_valid == 5
    assert agg.n_pass == 3
    assert agg.pass_rate == 0.6                       # exact rational c/n
    assert agg.wilson_low == pytest.approx(0.2307, abs=ABS)
    assert agg.wilson_high == pytest.approx(0.8824, abs=ABS)
    assert agg.mean_s == pytest.approx(0.632, abs=ABS)
    assert agg.median_s == pytest.approx(0.91, abs=ABS)
    assert agg.min_s == pytest.approx(0.0, abs=ABS)
    assert agg.max_s == pytest.approx(0.97, abs=ABS)
    assert agg.std_s == pytest.approx(0.4391, abs=ABS)   # Bessel
    assert agg.stability == pytest.approx(0.1219, abs=ABS)
    # = 0.632 - 2.132 * 0.4391 / sqrt(5)
    assert agg.conservative_continuous == pytest.approx(0.21338, abs=ABS)
    assert agg.timeout_rate == pytest.approx(0.2, abs=ABS)
    assert agg.infra_void_rate == pytest.approx(1.0 / 6.0, abs=ABS)  # 0.1667
    assert agg.reliability == pytest.approx(0.8, abs=ABS)
    assert agg.pass_at_k[1] == pytest.approx(0.6, abs=ABS)


def test_anchor_aggregate_worked_example_not_bimodal_not_deterministic():
    agg = aggregate_runs(_aggregate_worked_runs())
    assert agg.bimodal is False


def test_anchor_aggregate_bimodal_true():
    # S=[0.0,0.0,0.95,0.97,0.93], c=3 -> bimodal True.
    runs = [
        _runscore(0.0, functional_pass=False),
        _runscore(0.0, functional_pass=False),
        _runscore(0.95, functional_pass=True),
        _runscore(0.97, functional_pass=True),
        _runscore(0.93, functional_pass=True),
    ]
    assert aggregate_runs(runs).bimodal is True


def test_anchor_aggregate_determinism():
    # Identical transcript hashes across all valid runs -> deterministic True.
    runs = [_runscore(0.9, functional_pass=True) for _ in range(3)]
    agg = aggregate_runs(runs, transcript_hashes=["h", "h", "h"])
    assert agg.deterministic is True


# --------------------------------------------------------------------------- #
# DOMAIN anchors (framework §4)
# --------------------------------------------------------------------------- #

def test_anchor_domain_worked_example():
    # (w,n,c) = (1.0,5,3),(0.5,5,5),(0.25,10,2).
    contribs = [
        TaskDomainContribution(weight=1.0, n=5, c=3),
        TaskDomainContribution(weight=0.5, n=5, c=5),
        TaskDomainContribution(weight=0.25, n=10, c=2),
    ]
    ds = domain_score("backend", contribs)
    # pooled = 6.0/10.0 = 0.60 (exact rational).
    assert ds.pooled_pass_rate == 0.6
    # n_eff = 100/6.875 = 14.5455.
    assert ds.n_eff == pytest.approx(100.0 / 6.875, abs=ABS)
    assert ds.n_eff == pytest.approx(14.5455, abs=ABS)
    assert ds.wilson_low == pytest.approx(0.3542, abs=ABS)
    assert ds.wilson_high == pytest.approx(0.8040, abs=ABS)
    assert ds.n_tasks == 3
    assert ds.n_runs == 20
    assert ds.displayable is False  # needs >=5 tasks AND >=25 runs


# --------------------------------------------------------------------------- #
# RANKING anchor (framework §6)
# --------------------------------------------------------------------------- #

def test_anchor_ranking_provisional_excluded_and_appended():
    # n < 5 -> provisional, rank_low == rank_high == None, excluded from the
    # ranked set and returned after the ranked agents.
    rows = [
        RankInput("ranked", 45, 50),   # n >= 5 -> ranked
        RankInput("prov", 3, 4),       # n < 5 -> provisional
    ]
    out = rank_by_lcb(rows)
    by = {e.agent: e for e in out}
    # Ranked first, provisional last.
    assert [e.agent for e in out] == ["ranked", "prov"]
    assert by["prov"].provisional is True
    assert by["prov"].rank_low is None
    assert by["prov"].rank_high is None
    assert by["ranked"].provisional is False
    assert (by["ranked"].rank_low, by["ranked"].rank_high) == (1, 1)
