"""Tests for afa_kernel.ranking — leaderboard ranking by Wilson lower bound.

Every expected value here is derived independently from the documented formulas
(Wilson interval recomputed from first principles, rank ranges counted by hand),
never echoed back from the implementation. Imports come from the ranking and
confidence submodules only, so this suite does not depend on sibling stubs.
"""

from __future__ import annotations

import math

import pytest

from afa_kernel.confidence import wilson_interval
from afa_kernel.ranking import MIN_RANKED_N, rank_by_lcb
from afa_kernel.types import LeaderboardEntry, RankInput


# --------------------------------------------------------------------------- #
# Independent reference reimplementations
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


def _entry_by_agent(entries: list[LeaderboardEntry]) -> dict[str, LeaderboardEntry]:
    return {e.agent: e for e in entries}


# --------------------------------------------------------------------------- #
# Sanity: the Wilson anchors the ranking key relies on
# --------------------------------------------------------------------------- #

def test_wilson_anchors_hold():
    # These underpin every rank computation below; verify them first-principles.
    lo, hi = _ref_wilson(3, 5)
    assert (lo, hi) == pytest.approx((0.2307, 0.8824), abs=1e-4)
    assert _ref_wilson(3, 3)[0] == pytest.approx(0.4385, abs=1e-4)
    assert _ref_wilson(18, 20)[0] == pytest.approx(0.6990, abs=1e-4)
    # The conservative-LCB property: more evidence at higher rate ranks higher
    # even though 18/20 = 0.9 < 3/3 = 1.0 in raw rate.
    assert _ref_wilson(18, 20)[0] > _ref_wilson(3, 3)[0]


# --------------------------------------------------------------------------- #
# Fully separated field: every agent gets rank k-k
# --------------------------------------------------------------------------- #

def test_fully_separated_field_each_rank_k_to_k():
    # Chosen so that LCB_a > p_hat_b for each adjacent pair (verified by hand):
    #   A=50/50 LCB 0.9286, B=40/50 p 0.80, C=25/50 p 0.50, D=5/50 p 0.10
    #   0.9286 > 0.80, 0.6696 > 0.50, 0.3664 > 0.10  -> total order.
    rows = [
        RankInput("A", 50, 50),
        RankInput("B", 40, 50),
        RankInput("C", 25, 50),
        RankInput("D", 5, 50),
    ]
    out = rank_by_lcb(rows)
    assert [e.agent for e in out] == ["A", "B", "C", "D"]  # wilson_low desc
    assert all(not e.provisional for e in out)

    by = _entry_by_agent(out)
    # Each agent is its own rank: low == high == its position.
    assert (by["A"].rank_low, by["A"].rank_high) == (1, 1)
    assert (by["B"].rank_low, by["B"].rank_high) == (2, 2)
    assert (by["C"].rank_low, by["C"].rank_high) == (3, 3)
    assert (by["D"].rank_low, by["D"].rank_high) == (4, 4)

    # pass_rate and Wilson bounds match the independent reference.
    assert by["A"].pass_rate == pytest.approx(1.0)
    assert by["B"].pass_rate == pytest.approx(0.8)
    for ag, c, n in [("A", 50, 50), ("B", 40, 50), ("C", 25, 50), ("D", 5, 50)]:
        rlo, rhi = _ref_wilson(c, n)
        assert by[ag].wilson_low == pytest.approx(rlo, abs=1e-9)
        assert by[ag].wilson_high == pytest.approx(rhi, abs=1e-9)
        assert by[ag].n == n


def test_separated_top_agent_is_one_one():
    rows = [RankInput("top", 50, 50), RankInput("mid", 25, 50), RankInput("low", 5, 50)]
    out = rank_by_lcb(rows)
    top = _entry_by_agent(out)["top"]
    assert (top.rank_low, top.rank_high) == (1, 1)


# --------------------------------------------------------------------------- #
# Genuine tie cluster: overlapping ranges, nobody strictly out-ranks anybody
# --------------------------------------------------------------------------- #

def test_tie_cluster_overlapping_ranges():
    # P=6/8 (p .75, LCB .4093), Q=5/8 (p .625, LCB .3057), R=4/8 (p .5, LCB .2152).
    # No LCB exceeds any other agent's p_hat -> the strict relation is empty.
    # So for every agent: better = 0, worse = 0 -> rank_low = 1, rank_high = 3.
    rows = [RankInput("P", 6, 8), RankInput("Q", 5, 8), RankInput("R", 4, 8)]
    out = rank_by_lcb(rows)
    by = _entry_by_agent(out)
    for ag in ("P", "Q", "R"):
        assert (by[ag].rank_low, by[ag].rank_high) == (1, 3), ag
        assert not by[ag].provisional

    # Sort order is still by wilson_low desc within the cluster: P > Q > R.
    assert [e.agent for e in out] == ["P", "Q", "R"]

    # Confirm the relation really is empty: no LCB beats another's p_hat.
    stats = {ag: (c / n, _ref_wilson(c, n)[0]) for ag, c, n in
             [("P", 6, 8), ("Q", 5, 8), ("R", 4, 8)]}
    for a in stats:
        for b in stats:
            if a != b:
                assert not (stats[a][1] > stats[b][0]), (a, b)


def test_mixed_clear_tie_clear():
    # T clearly best, M1/M2 form a tie cluster, B clearly worst.
    #   T=50/50 LCB .9286,  M1=30/40 p .75 LCB .5981,  M2=28/40 p .70 LCB .5457,
    #   B=5/50 p .10 LCB .0435.
    # Hand-derived ranks:
    #   T: better=0, worse=3 -> (1,1)
    #   M1: LCB_T(.9286)>p_M1(.75) so better=1; M1 out-ranks only B -> worse=1 -> (2,3)
    #   M2: better=1 (T); worse=1 (B) -> (2,3)   [M1<->M2 do not out-rank each other]
    #   B: better=3 (T,M1,M2 all LCB>.10); worse=0 -> (4,4)
    rows = [
        RankInput("T", 50, 50),
        RankInput("M1", 30, 40),
        RankInput("M2", 28, 40),
        RankInput("B", 5, 50),
    ]
    out = rank_by_lcb(rows)
    by = _entry_by_agent(out)
    assert (by["T"].rank_low, by["T"].rank_high) == (1, 1)
    assert (by["M1"].rank_low, by["M1"].rank_high) == (2, 3)
    assert (by["M2"].rank_low, by["M2"].rank_high) == (2, 3)
    assert (by["B"].rank_low, by["B"].rank_high) == (4, 4)
    # Overall sort by wilson_low desc.
    assert [e.agent for e in out] == ["T", "M1", "M2", "B"]


# --------------------------------------------------------------------------- #
# Provisional exclusion (n < 5)
# --------------------------------------------------------------------------- #

def test_min_ranked_n_is_five():
    assert MIN_RANKED_N == 5


def test_provisional_excluded_and_appended_last():
    rows = [
        RankInput("ranked_hi", 45, 50),   # n >= 5 -> ranked
        RankInput("ranked_lo", 25, 50),   # n >= 5 -> ranked
        RankInput("prov_hi", 3, 4),       # n < 5 -> provisional, p_hat 0.75
        RankInput("prov_lo", 1, 4),       # n < 5 -> provisional, p_hat 0.25
    ]
    out = rank_by_lcb(rows)

    # Ranked agents come first, provisional last.
    assert [e.agent for e in out] == ["ranked_hi", "ranked_lo", "prov_hi", "prov_lo"]

    by = _entry_by_agent(out)
    # Provisional flags and None ranks.
    for ag in ("prov_hi", "prov_lo"):
        assert by[ag].provisional is True
        assert by[ag].rank_low is None
        assert by[ag].rank_high is None
    for ag in ("ranked_hi", "ranked_lo"):
        assert by[ag].provisional is False
        assert by[ag].rank_low is not None
        assert by[ag].rank_high is not None

    # Ranked-set size is 2, so ranks live in {1, 2}; provisional do not consume ranks.
    assert (by["ranked_hi"].rank_low, by["ranked_hi"].rank_high) == (1, 1)
    assert (by["ranked_lo"].rank_low, by["ranked_lo"].rank_high) == (2, 2)

    # Provisional still carry correct pass_rate / Wilson values.
    assert by["prov_hi"].pass_rate == pytest.approx(0.75)
    assert by["prov_lo"].pass_rate == pytest.approx(0.25)
    plo, phi = _ref_wilson(3, 4)
    assert by["prov_hi"].wilson_low == pytest.approx(plo, abs=1e-9)
    assert by["prov_hi"].wilson_high == pytest.approx(phi, abs=1e-9)


def test_provisional_sorted_by_pass_rate_desc():
    rows = [
        RankInput("a", 1, 4),   # p 0.25
        RankInput("b", 3, 4),   # p 0.75
        RankInput("c", 2, 4),   # p 0.50
    ]
    out = rank_by_lcb(rows)
    # All provisional (n < 5); order is pass_rate desc.
    assert all(e.provisional for e in out)
    assert [e.agent for e in out] == ["b", "c", "a"]


def test_n_equals_five_is_ranked_not_provisional():
    # Boundary: n == 5 is the threshold -> ranked.
    out = rank_by_lcb([RankInput("five", 3, 5)])
    assert out[0].provisional is False
    assert out[0].rank_low == 1
    assert out[0].rank_high == 1


def test_n_equals_four_is_provisional():
    out = rank_by_lcb([RankInput("four", 3, 4)])
    assert out[0].provisional is True
    assert out[0].rank_low is None
    assert out[0].rank_high is None


# --------------------------------------------------------------------------- #
# Sort-order tie-breaks and degenerate inputs
# --------------------------------------------------------------------------- #

def test_sort_tiebreak_by_phat_then_name():
    # Two agents with identical Wilson lower bound by construction: same c, n.
    # Then the tie-break falls to pass_rate desc (equal here) then agent asc.
    rows = [
        RankInput("zeta", 30, 50),
        RankInput("alpha", 30, 50),
    ]
    out = rank_by_lcb(rows)
    assert out[0].wilson_low == pytest.approx(out[1].wilson_low)
    # Equal wilson_low and pass_rate -> alphabetical: alpha before zeta.
    assert [e.agent for e in out] == ["alpha", "zeta"]


def test_empty_input_returns_empty_list():
    assert rank_by_lcb([]) == []


def test_single_ranked_agent_is_one_one():
    out = rank_by_lcb([RankInput("solo", 40, 50)])
    assert len(out) == 1
    e = out[0]
    assert e.provisional is False
    assert (e.rank_low, e.rank_high) == (1, 1)
    rlo, rhi = _ref_wilson(40, 50)
    assert e.wilson_low == pytest.approx(rlo, abs=1e-9)
    assert e.wilson_high == pytest.approx(rhi, abs=1e-9)


def test_perfect_score_does_not_out_rank_itself():
    # A single perfect agent: better = 0 (its own LCB is not > its own p_hat=1.0
    # because LCB < 1.0), worse = 0 -> rank 1-1, never out of range.
    out = rank_by_lcb([RankInput("perfect", 50, 50)])
    e = out[0]
    assert e.pass_rate == pytest.approx(1.0)
    assert e.wilson_low < 1.0  # LCB strictly below the point estimate
    assert (e.rank_low, e.rank_high) == (1, 1)


def test_rank_range_invariants():
    # For any field, every ranked agent must satisfy
    #   1 <= rank_low <= rank_high <= n_ranked.
    rows = [
        RankInput("A", 50, 50),
        RankInput("B", 40, 50),
        RankInput("C", 30, 50),
        RankInput("D", 30, 50),
        RankInput("E", 6, 8),
        RankInput("prov", 2, 3),
    ]
    out = rank_by_lcb(rows)
    n_ranked = sum(1 for e in out if not e.provisional)
    for e in out:
        if e.provisional:
            continue
        assert 1 <= e.rank_low <= e.rank_high <= n_ranked, e.agent
