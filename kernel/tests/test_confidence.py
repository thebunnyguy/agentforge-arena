"""Tests for afa_kernel.confidence — the pure-statistics primitives.

Every expected value here is derived independently from the documented
formulas (recomputed by hand / from first principles), never echoed back from
the implementation. Imports come straight from the confidence submodule so the
suite does not depend on sibling stub modules.
"""

from __future__ import annotations

import math

import pytest

from afa_kernel.confidence import (
    Z_95,
    pass_at_k,
    stability,
    t_critical_one_sided_95,
    wilson_interval,
    wilson_lower_bound,
)


# --------------------------------------------------------------------------- #
# Reference reimplementations (independent of the module under test)
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


# --------------------------------------------------------------------------- #
# Wilson interval — canonical anchors
# --------------------------------------------------------------------------- #

def test_wilson_anchor_3_of_5():
    low, high = wilson_interval(3, 5)
    assert low == pytest.approx(0.2307, abs=1e-4)
    assert high == pytest.approx(0.8824, abs=1e-4)


def test_wilson_lower_bound_3_of_3():
    # Independently: p=1, centre=(1+1.96^2/6)/(1+1.96^2/3),
    # half=(1.96/denom)*sqrt(0 + 1.96^2/(4*9)). Computed by hand -> 0.4385.
    assert wilson_lower_bound(3, 3) == pytest.approx(0.4385, abs=1e-4)


def test_wilson_lower_bound_18_of_20():
    assert wilson_lower_bound(18, 20) == pytest.approx(0.6990, abs=1e-4)


def test_wilson_lower_bound_orders_more_evidence_higher():
    # 18/20 (p=0.9) must out-rank a perfect-but-thin 3/3 (p=1.0): the LCB
    # rewards evidence, not raw rate. 0.6990 > 0.4385.
    assert wilson_lower_bound(18, 20) > wilson_lower_bound(3, 3)


def test_wilson_n_zero_is_full_interval():
    assert wilson_interval(0, 0) == (0.0, 1.0)


def test_wilson_negative_n_is_full_interval():
    # Defensive: any non-positive n carries no information.
    assert wilson_interval(2, 0) == (0.0, 1.0)


def test_wilson_lower_bound_n_zero():
    assert wilson_lower_bound(0, 0) == 0.0


# --------------------------------------------------------------------------- #
# Wilson interval — structural properties
# --------------------------------------------------------------------------- #

def test_wilson_endpoints_clamped_to_unit_interval():
    for c, n in [(0, 1), (1, 1), (0, 7), (7, 7), (1, 2), (50, 100)]:
        low, high = wilson_interval(c, n)
        assert 0.0 <= low <= high <= 1.0


def test_wilson_all_pass_lower_bound_below_one_upper_is_one():
    # p_hat = 1: the upper endpoint clamps to 1, the lower endpoint is < 1.
    low, high = wilson_interval(10, 10)
    assert high == pytest.approx(1.0, abs=1e-12)
    assert low < 1.0


def test_wilson_all_fail_upper_bound_above_zero_lower_is_zero():
    low, high = wilson_interval(0, 10)
    assert low == pytest.approx(0.0, abs=1e-12)
    assert high > 0.0


def test_wilson_centre_pulled_toward_half():
    # The Wilson centre sits between p_hat and 0.5 (regularisation toward 0.5).
    low, high = wilson_interval(8, 10)  # p_hat = 0.8
    centre = (low + high) / 2.0
    assert 0.5 < centre < 0.8


def test_wilson_more_data_narrows_interval():
    # Same proportion, more samples -> strictly tighter interval.
    low_small, high_small = wilson_interval(6, 10)
    low_big, high_big = wilson_interval(60, 100)
    assert (high_big - low_big) < (high_small - low_small)


def test_wilson_matches_independent_reference_across_grid():
    for n in (1, 2, 5, 10, 25, 100):
        for c in range(0, n + 1):
            got = wilson_interval(c, n)
            exp = _ref_wilson(c, n)
            assert got[0] == pytest.approx(exp[0], abs=1e-12)
            assert got[1] == pytest.approx(exp[1], abs=1e-12)


def test_wilson_accepts_float_effective_sample_size():
    # Domain pooling passes a Kish effective n. Worked example (framework §4):
    # n_eff = 100/6.875 = 14.5455..., c = 0.60 * n_eff.
    n_eff = 100.0 / 6.875
    low, high = wilson_interval(0.60 * n_eff, n_eff)
    assert low == pytest.approx(0.3542, abs=1e-4)
    assert high == pytest.approx(0.8040, abs=1e-4)


def test_wilson_custom_z_widens_with_larger_z():
    # A larger z (higher confidence) yields a wider interval.
    low99, high99 = wilson_interval(7, 10, z=2.576)
    low95, high95 = wilson_interval(7, 10, z=1.96)
    assert (high99 - low99) > (high95 - low95)


def test_wilson_default_z_is_1_96():
    assert Z_95 == pytest.approx(1.96)
    assert wilson_interval(3, 5) == wilson_interval(3, 5, z=Z_95)


# --------------------------------------------------------------------------- #
# pass@k — anchors and identities
# --------------------------------------------------------------------------- #

def test_pass_at_k_anchor():
    # 1 - C(3,3)/C(5,3) = 1 - 1/10 = 0.9
    assert pass_at_k(5, 2, 3) == pytest.approx(0.9, abs=1e-12)


def test_pass_at_1_identity():
    # pass@1 == c/n for every n, c.
    for n in (1, 2, 5, 10):
        for c in range(0, n + 1):
            assert pass_at_k(n, c, 1) == pytest.approx(c / n, abs=1e-12)


def test_pass_at_k_all_pass_is_one():
    # c == n: every k-subset contains a pass, C(0,k)=0 -> 1.0.
    assert pass_at_k(5, 5, 3) == pytest.approx(1.0, abs=1e-12)


def test_pass_at_k_no_pass_is_zero():
    # c == 0: C(n,k)/C(n,k) = 1 -> 0.0.
    assert pass_at_k(5, 0, 3) == pytest.approx(0.0, abs=1e-12)


def test_pass_at_k_forced_pass_when_failures_below_k():
    # n=5, c=3 -> only 2 failures; any 3-subset must include a pass.
    # 1 - C(2,3)/C(5,3) = 1 - 0/10 = 1.0.
    assert pass_at_k(5, 3, 3) == pytest.approx(1.0, abs=1e-12)


def test_pass_at_k_hand_value():
    # n=4, c=1, k=2: 1 - C(3,2)/C(4,2) = 1 - 3/6 = 0.5.
    assert pass_at_k(4, 1, 2) == pytest.approx(0.5, abs=1e-12)


def test_pass_at_k_monotone_in_k():
    # For fixed (n, c) with 0 < c < n, pass@k is non-decreasing in k.
    n, c = 8, 3
    vals = [pass_at_k(n, c, k) for k in range(1, n + 1)]
    assert all(b >= a - 1e-12 for a, b in zip(vals, vals[1:]))


def test_pass_at_k_rejects_k_too_small():
    with pytest.raises(ValueError):
        pass_at_k(5, 2, 0)


def test_pass_at_k_rejects_k_too_large():
    with pytest.raises(ValueError):
        pass_at_k(5, 2, 6)


def test_pass_at_k_in_unit_interval():
    for n in (1, 3, 6):
        for c in range(0, n + 1):
            for k in range(1, n + 1):
                v = pass_at_k(n, c, k)
                assert 0.0 <= v <= 1.0


# --------------------------------------------------------------------------- #
# One-sided 95% t table
# --------------------------------------------------------------------------- #

def test_t_critical_anchor_df4():
    assert t_critical_one_sided_95(4) == pytest.approx(2.132, abs=1e-3)


def test_t_critical_anchor_df9():
    assert t_critical_one_sided_95(9) == pytest.approx(1.833, abs=1e-3)


def test_t_critical_df1():
    # Smallest df has the heaviest tail.
    assert t_critical_one_sided_95(1) == pytest.approx(6.314, abs=1e-3)


def test_t_critical_normal_limit_beyond_30():
    for df in (31, 40, 100, 10_000):
        assert t_critical_one_sided_95(df) == pytest.approx(1.645, abs=1e-12)


def test_t_critical_df30_boundary():
    # df=30 is still table-driven, and strictly above the normal limit.
    assert t_critical_one_sided_95(30) == pytest.approx(1.697, abs=1e-3)
    assert t_critical_one_sided_95(30) > 1.645


def test_t_critical_monotonically_decreasing():
    # As df grows, the critical value shrinks toward the normal limit.
    vals = [t_critical_one_sided_95(df) for df in range(1, 31)]
    assert all(b < a for a, b in zip(vals, vals[1:]))
    assert all(v >= 1.645 for v in vals)


def test_t_critical_full_table_present_df_1_to_30():
    for df in range(1, 31):
        v = t_critical_one_sided_95(df)
        assert isinstance(v, float)
        assert v > 0.0


def test_t_critical_rejects_df_below_1():
    with pytest.raises(ValueError):
        t_critical_one_sided_95(0)
    with pytest.raises(ValueError):
        t_critical_one_sided_95(-3)


# --------------------------------------------------------------------------- #
# stability
# --------------------------------------------------------------------------- #

def test_stability_anchors():
    assert stability(0.0) == pytest.approx(1.0)
    assert stability(0.25) == pytest.approx(0.5)
    assert stability(0.5) == pytest.approx(0.0)


def test_stability_clamped_at_zero():
    # std beyond 0.5 cannot push stability negative.
    assert stability(0.6) == pytest.approx(0.0)
    assert stability(10.0) == pytest.approx(0.0)


def test_stability_aggregate_worked_example():
    # Framework §2 example: std_s = 0.4391 (Bessel) -> 1 - 2*0.4391 = 0.1219.
    assert stability(0.4391) == pytest.approx(0.1219, abs=1e-4)


def test_stability_is_linear_and_decreasing_in_range():
    assert stability(0.1) == pytest.approx(0.8)
    assert stability(0.2) == pytest.approx(0.6)
    assert stability(0.1) > stability(0.2)


def test_stability_within_unit_interval():
    for s in (0.0, 0.05, 0.25, 0.4391, 0.5, 0.75, 1.0):
        assert 0.0 <= stability(s) <= 1.0
