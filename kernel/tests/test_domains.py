"""Tests for afa_kernel.domains — per-domain pooled capability profiling.

Every expected value here is derived independently from the documented formulas
(recomputed by hand / from first principles), never echoed back from the
implementation. Imports come straight from the domains submodule so the suite
does not depend on sibling stub modules.
"""

from __future__ import annotations

import math

import pytest

from afa_kernel.domains import (
    MIN_RUNS_DISPLAY,
    MIN_TASKS_DISPLAY,
    domain_score,
    macro_overall,
)
from afa_kernel.types import DomainScore, TaskDomainContribution


# --------------------------------------------------------------------------- #
# Independent reference reimplementations (separate from the module under test)
# --------------------------------------------------------------------------- #

def _ref_wilson(c: float, n: float, z: float = 1.96) -> tuple[float, float]:
    """First-principles Wilson interval, written separately from the kernel."""
    if n <= 0:
        return (0.0, 1.0)
    p = c / n
    z2 = z * z
    denom = 1.0 + z2 / n
    centre = (p + z2 / (2.0 * n)) / denom
    half = (z / denom) * math.sqrt(p * (1.0 - p) / n + z2 / (4.0 * n * n))
    return (max(0.0, centre - half), min(1.0, centre + half))


def _ref_stability(std: float) -> float:
    return max(0.0, 1.0 - 2.0 * std)


def _contrib(w: float, n: int, c: int, std: float = 0.0) -> TaskDomainContribution:
    return TaskDomainContribution(weight=w, n=n, c=c, std=std)


# --------------------------------------------------------------------------- #
# Canonical worked anchor (framework §4)
# --------------------------------------------------------------------------- #

def test_domain_worked_anchor():
    """(w,n,c) = (1.0,5,3),(0.5,5,5),(0.25,10,2).

    sum(w*c) = 1*3 + 0.5*5 + 0.25*2 = 3 + 2.5 + 0.5 = 6.0
    sum(w*n) = 1*5 + 0.5*5 + 0.25*10 = 5 + 2.5 + 2.5 = 10.0
    pooled = 6.0 / 10.0 = 0.60
    sum(w^2*n) = 1*5 + 0.25*5 + 0.0625*10 = 5 + 1.25 + 0.625 = 6.875
    n_eff = 10^2 / 6.875 = 100 / 6.875 = 14.5454545...
    wilson(0.60 * 14.5455, 14.5455) -> (0.3542, 0.8040)
    n_tasks = 3, n_runs = 20, displayable = False (needs >=5 tasks AND >=25 runs)
    """
    contribs = [_contrib(1.0, 5, 3), _contrib(0.5, 5, 5), _contrib(0.25, 10, 2)]
    ds = domain_score("backend", contribs)

    assert ds.domain == "backend"
    assert ds.pooled_pass_rate == pytest.approx(0.60, abs=1e-9)
    assert ds.n_eff == pytest.approx(100.0 / 6.875, abs=1e-9)
    assert ds.n_eff == pytest.approx(14.5454545454, abs=1e-4)
    assert ds.wilson_low == pytest.approx(0.3542, abs=1e-4)
    assert ds.wilson_high == pytest.approx(0.8040, abs=1e-4)
    assert ds.n_tasks == 3
    assert ds.n_runs == 20
    assert ds.displayable is False


def test_domain_anchor_wilson_matches_independent_reference():
    """The Wilson endpoints must equal the first-principles computation."""
    contribs = [_contrib(1.0, 5, 3), _contrib(0.5, 5, 5), _contrib(0.25, 10, 2)]
    ds = domain_score("backend", contribs)
    lo, hi = _ref_wilson(ds.pooled_pass_rate * ds.n_eff, ds.n_eff)
    assert ds.wilson_low == pytest.approx(lo, abs=1e-12)
    assert ds.wilson_high == pytest.approx(hi, abs=1e-12)


# --------------------------------------------------------------------------- #
# Pooled pass rate & Kish n_eff properties
# --------------------------------------------------------------------------- #

def test_single_task_unit_weight_reduces_to_plain_wilson():
    """One task, weight 1: pooled = c/n, n_eff = n, Wilson over (c, n)."""
    ds = domain_score("d", [_contrib(1.0, 5, 3)])
    assert ds.pooled_pass_rate == pytest.approx(3.0 / 5.0, abs=1e-12)
    assert ds.n_eff == pytest.approx(5.0, abs=1e-12)
    lo, hi = _ref_wilson(3.0, 5.0)
    # Plain c=3,n=5 anchor is (0.2307, 0.8824).
    assert (ds.wilson_low, ds.wilson_high) == pytest.approx((0.2307, 0.8824), abs=1e-4)
    assert (ds.wilson_low, ds.wilson_high) == pytest.approx((lo, hi), abs=1e-12)


def test_kish_neff_equals_sum_n_when_weights_equal():
    """With all weights equal, Kish n_eff collapses to the plain run count.

    n_eff = (sum w*n)^2 / sum w^2*n. With constant w: (w*N)^2 / (w^2*N) = N.
    """
    contribs = [_contrib(0.5, 4, 2), _contrib(0.5, 6, 3), _contrib(0.5, 10, 7)]
    ds = domain_score("d", contribs)
    assert ds.n_eff == pytest.approx(4 + 6 + 10, abs=1e-9)


def test_kish_neff_is_downweighted_by_unequal_weights():
    """Unequal weights strictly reduce n_eff below the raw run total.

    (1*10 + 0.25*10)^2 / (1*10 + 0.0625*10) = 12.5^2 / 10.625
      = 156.25 / 10.625 = 14.7058823...  < 20 raw runs.
    """
    contribs = [_contrib(1.0, 10, 5), _contrib(0.25, 10, 5)]
    ds = domain_score("d", contribs)
    assert ds.n_eff == pytest.approx(156.25 / 10.625, abs=1e-9)
    assert ds.n_eff < 20.0
    assert ds.n_runs == 20


def test_pooled_pass_rate_weights_passes_proportionally():
    """Weighted pooling: heavy task dominates the pooled rate.

    (w,n,c) = (2.0, 5, 1), (0.5, 5, 5):
      sum(w*c) = 2*1 + 0.5*5 = 2 + 2.5 = 4.5
      sum(w*n) = 2*5 + 0.5*5 = 10 + 2.5 = 12.5
      pooled = 4.5 / 12.5 = 0.36
    """
    contribs = [_contrib(2.0, 5, 1), _contrib(0.5, 5, 5)]
    ds = domain_score("d", contribs)
    assert ds.pooled_pass_rate == pytest.approx(0.36, abs=1e-12)


def test_pooled_all_pass_and_all_fail():
    """Boundary pooled rates of 1.0 and 0.0."""
    all_pass = domain_score("p", [_contrib(1.0, 5, 5), _contrib(0.5, 4, 4)])
    assert all_pass.pooled_pass_rate == pytest.approx(1.0, abs=1e-12)
    all_fail = domain_score("f", [_contrib(1.0, 5, 0), _contrib(0.5, 4, 0)])
    assert all_fail.pooled_pass_rate == pytest.approx(0.0, abs=1e-12)
    # Wilson lower bound at p=1 is below 1; upper bound exactly 1.
    assert all_pass.wilson_high == pytest.approx(1.0, abs=1e-12)
    assert all_fail.wilson_low == pytest.approx(0.0, abs=1e-12)


# --------------------------------------------------------------------------- #
# Run-mass-weighted stability
# --------------------------------------------------------------------------- #

def test_stability_run_mass_weighted_mean():
    """stability = sum(w*n*stab(std)) / sum(w*n).

    (w,n,std): (1.0, 10, 0.0), (0.5, 10, 0.25)
      stab(0.0)  = 1 - 2*0.0  = 1.0
      stab(0.25) = 1 - 2*0.25 = 0.5
      weights w*n: 1*10 = 10, 0.5*10 = 5
      sum(w*n) = 15
      weighted = (10*1.0 + 5*0.5) / 15 = (10 + 2.5) / 15 = 12.5 / 15 = 0.8333...
    """
    contribs = [_contrib(1.0, 10, 5, std=0.0), _contrib(0.5, 10, 5, std=0.25)]
    ds = domain_score("d", contribs)
    assert ds.stability == pytest.approx(12.5 / 15.0, abs=1e-12)


def test_stability_clamps_high_std_to_zero():
    """A task with std >= 0.5 contributes stability 0, dragging the mean down.

    (w,n,std): (1.0, 5, 0.0) -> stab 1.0 ; (1.0, 5, 0.6) -> stab clamped to 0.0
      weights w*n: 5 and 5, sum 10
      weighted = (5*1.0 + 5*0.0) / 10 = 0.5
    """
    contribs = [_contrib(1.0, 5, 3, std=0.0), _contrib(1.0, 5, 3, std=0.6)]
    ds = domain_score("d", contribs)
    assert _ref_stability(0.6) == 0.0
    assert ds.stability == pytest.approx(0.5, abs=1e-12)


def test_stability_uses_run_mass_not_task_count():
    """A high-run task weights stability more than a low-run task.

    (w,n,std): (1.0, 1, 0.5) -> stab 0.0 (tiny mass 1)
               (1.0, 99, 0.0) -> stab 1.0 (mass 99)
      weighted = (1*0.0 + 99*1.0) / 100 = 0.99
    """
    contribs = [_contrib(1.0, 1, 0, std=0.5), _contrib(1.0, 99, 99, std=0.0)]
    ds = domain_score("d", contribs)
    assert ds.stability == pytest.approx(0.99, abs=1e-12)


# --------------------------------------------------------------------------- #
# Displayable threshold (>= 5 tasks AND >= 25 runs)
# --------------------------------------------------------------------------- #

def test_displayable_requires_both_thresholds():
    assert MIN_TASKS_DISPLAY == 5
    assert MIN_RUNS_DISPLAY == 25

    # Exactly 5 tasks and exactly 25 runs -> displayable.
    enough = [_contrib(1.0, 5, 3) for _ in range(5)]  # 5 tasks, 25 runs
    ds = domain_score("d", enough)
    assert ds.n_tasks == 5
    assert ds.n_runs == 25
    assert ds.displayable is True


def test_not_displayable_too_few_tasks():
    # 4 tasks, 40 runs: enough runs but too few tasks.
    contribs = [_contrib(1.0, 10, 5) for _ in range(4)]
    ds = domain_score("d", contribs)
    assert ds.n_tasks == 4
    assert ds.n_runs == 40
    assert ds.displayable is False


def test_not_displayable_too_few_runs():
    # 6 tasks, 24 runs: enough tasks but too few runs.
    contribs = [_contrib(1.0, 4, 2) for _ in range(6)]
    ds = domain_score("d", contribs)
    assert ds.n_tasks == 6
    assert ds.n_runs == 24
    assert ds.displayable is False


def test_displayable_boundary_off_by_one():
    # 5 tasks but only 24 runs (one task has 4 runs) -> not displayable.
    contribs = [_contrib(1.0, 5, 3) for _ in range(4)] + [_contrib(1.0, 4, 2)]
    ds = domain_score("d", contribs)
    assert ds.n_tasks == 5
    assert ds.n_runs == 24
    assert ds.displayable is False


# --------------------------------------------------------------------------- #
# Degenerate sum(w*n) == 0
# --------------------------------------------------------------------------- #

def test_degenerate_empty_contributions():
    ds = domain_score("d", [])
    assert ds.pooled_pass_rate == 0.0
    assert ds.n_eff == 0.0
    assert ds.wilson_low == 0.0
    assert ds.wilson_high == 1.0
    assert ds.stability == 0.0
    assert ds.n_tasks == 0
    assert ds.n_runs == 0
    assert ds.displayable is False


def test_degenerate_all_zero_runs():
    """Tasks present but every n == 0 -> sum(w*n) == 0, no information."""
    contribs = [_contrib(1.0, 0, 0), _contrib(0.5, 0, 0)]
    ds = domain_score("d", contribs)
    assert ds.pooled_pass_rate == 0.0
    assert ds.n_eff == 0.0
    assert ds.wilson_low == 0.0
    assert ds.wilson_high == 1.0
    assert ds.stability == 0.0
    assert ds.n_tasks == 2
    assert ds.n_runs == 0


def test_degenerate_all_zero_weights():
    """All weights zero -> sum(w*n) == 0 even with positive run counts."""
    contribs = [_contrib(0.0, 5, 3), _contrib(0.0, 10, 4)]
    ds = domain_score("d", contribs)
    assert ds.pooled_pass_rate == 0.0
    assert ds.n_eff == 0.0
    assert ds.wilson_low == 0.0
    assert ds.wilson_high == 1.0
    assert ds.n_runs == 15  # raw run total still reported


def test_degenerate_does_not_divide_by_zero():
    """Degenerate path must never raise (no division by zero)."""
    # Should simply return cleanly.
    domain_score("d", [_contrib(0.0, 0, 0)])


# --------------------------------------------------------------------------- #
# macro_overall
# --------------------------------------------------------------------------- #

def _ds(domain: str, pooled: float, displayable: bool) -> DomainScore:
    return DomainScore(
        domain=domain,
        pooled_pass_rate=pooled,
        n_eff=10.0,
        wilson_low=0.0,
        wilson_high=1.0,
        stability=1.0,
        n_tasks=5,
        n_runs=25,
        displayable=displayable,
    )


def test_macro_overall_averages_displayable_only():
    """Macro-average over displayable domains; non-displayable excluded.

    displayable pooled rates: 0.8 and 0.4 -> mean = 0.6.
    The 0.0 domain is non-displayable and must be ignored.
    """
    scores = [
        _ds("a", 0.8, True),
        _ds("b", 0.4, True),
        _ds("c", 0.0, False),  # excluded
    ]
    assert macro_overall(scores) == pytest.approx(0.6, abs=1e-12)


def test_macro_overall_none_when_no_displayable():
    scores = [_ds("a", 0.9, False), _ds("b", 0.5, False)]
    assert macro_overall(scores) is None


def test_macro_overall_none_on_empty():
    assert macro_overall([]) is None


def test_macro_overall_single_displayable():
    scores = [_ds("a", 0.73, True), _ds("b", 0.1, False)]
    assert macro_overall(scores) == pytest.approx(0.73, abs=1e-12)


def test_macro_overall_uses_real_domain_scores():
    """End-to-end: build DomainScores via domain_score, then macro-average."""
    five = [_contrib(1.0, 5, 4) for _ in range(5)]      # 25 runs, displayable, pooled 0.8
    five_b = [_contrib(1.0, 5, 1) for _ in range(5)]    # 25 runs, displayable, pooled 0.2
    too_small = [_contrib(1.0, 5, 5) for _ in range(3)]  # 15 runs, not displayable
    a = domain_score("a", five)
    b = domain_score("b", five_b)
    c = domain_score("c", too_small)
    assert a.displayable and b.displayable and not c.displayable
    # mean of 0.8 and 0.2 -> 0.5
    assert macro_overall([a, b, c]) == pytest.approx(0.5, abs=1e-12)
