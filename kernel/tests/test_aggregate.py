"""Tests for afa_kernel.aggregate — repeated-run aggregation (framework §2).

Every expected value here is derived independently from the documented formulas
(recomputed by hand / from first principles), never echoed back from the
implementation. Fixtures construct RunScore objects directly (score_run is not
exercised), so the suite depends only on aggregate + confidence + types.
"""

from __future__ import annotations

import math
import statistics

import pytest

from afa_kernel.aggregate import DEFAULT_K_VALUES, aggregate_runs
from afa_kernel.types import RunScore, RunStatus


# --------------------------------------------------------------------------- #
# Fixture helpers
# --------------------------------------------------------------------------- #

def make_run(
    final_score: float,
    *,
    functional_pass: bool,
    status: RunStatus = RunStatus.VALID,
) -> RunScore:
    """Build a RunScore with only the fields aggregation reads.

    aggregate_runs consumes status, functional_pass, final_score and voided is
    derived purely from status, so the remaining fields are filled with
    consistent placeholders.
    """
    gate_product = 1 if functional_pass else 0
    return RunScore(
        status=status,
        gate_product=gate_product,
        t_hidden=final_score,           # placeholder; unread by aggregation
        q=1.0,                          # placeholder; unread by aggregation
        q_components={},
        final_score=final_score,
        functional_pass=functional_pass,
        voided=(status is RunStatus.INFRA_FAILURE),
    )


def worked_example_runs() -> list[RunScore]:
    """The framework §2 running example.

    Five VALID-bucket runs with S = [0.94, 0.34, 0.91, 0.00, 0.97]; three are
    functional passes (0.94, 0.91, 0.97), one is a clean wrong answer (0.34),
    one is a TIMEOUT (0.00). One extra attempt is voided as INFRA_FAILURE.
    """
    return [
        make_run(0.94, functional_pass=True),
        make_run(0.34, functional_pass=False),                       # clean miss
        make_run(0.91, functional_pass=True),
        make_run(0.00, functional_pass=False, status=RunStatus.TIMEOUT),
        make_run(0.97, functional_pass=True),
        make_run(0.00, functional_pass=False, status=RunStatus.INFRA_FAILURE),
    ]


# --------------------------------------------------------------------------- #
# The canonical AGGREGATE worked example (framework §2)
# --------------------------------------------------------------------------- #

def test_worked_example_counts_and_rates():
    agg = aggregate_runs(worked_example_runs())
    assert agg.n_valid == 5            # the INFRA_FAILURE is voided out of n
    assert agg.n_pass == 3
    assert agg.pass_rate == pytest.approx(0.6)
    assert agg.timeout_rate == pytest.approx(0.2)           # 1 of 5
    assert agg.reliability == pytest.approx(0.8)            # 4 of 5 not timeout/crash
    assert agg.infra_void_rate == pytest.approx(1.0 / 6.0)  # 1 voided of 6 attempts
    assert agg.provisional is False                         # n_valid == 5


def test_worked_example_wilson():
    agg = aggregate_runs(worked_example_runs())
    # Wilson(3, 5) — the contract anchor.
    assert agg.wilson_low == pytest.approx(0.2307, abs=1e-4)
    assert agg.wilson_high == pytest.approx(0.8824, abs=1e-4)


def test_worked_example_distribution_stats():
    agg = aggregate_runs(worked_example_runs())
    # Recompute from first principles over [0.94, 0.34, 0.91, 0.0, 0.97].
    s_vals = [0.94, 0.34, 0.91, 0.0, 0.97]
    assert agg.mean_s == pytest.approx(0.632)
    assert agg.median_s == pytest.approx(0.91)             # middle of sorted, odd n
    assert agg.min_s == pytest.approx(0.0)
    assert agg.max_s == pytest.approx(0.97)
    # Bessel std: sum of squared deviations / (n-1).
    mean = 0.632
    ss = sum((x - mean) ** 2 for x in s_vals)
    expected_std = math.sqrt(ss / 4)
    assert expected_std == pytest.approx(0.4391, abs=1e-4)
    assert agg.std_s == pytest.approx(expected_std)


def test_worked_example_stability_and_conservative():
    agg = aggregate_runs(worked_example_runs())
    std = math.sqrt(sum((x - 0.632) ** 2 for x in [0.94, 0.34, 0.91, 0.0, 0.97]) / 4)
    # stability = max(0, 1 - 2s).
    assert agg.stability == pytest.approx(max(0.0, 1.0 - 2.0 * std), abs=1e-9)
    assert agg.stability == pytest.approx(0.1219, abs=1e-4)
    # conservative_S = max(0, mean - t_{.95,4} * s / sqrt(n)); t_{.95,4} = 2.132.
    expected_cons = max(0.0, 0.632 - 2.132 * std / math.sqrt(5))
    assert expected_cons == pytest.approx(0.21338, abs=1e-4)
    assert agg.conservative_continuous == pytest.approx(expected_cons, abs=1e-9)


def test_worked_example_pass_at_k():
    agg = aggregate_runs(worked_example_runs())
    # n=5, c=3. pass@1 = c/n. pass@2 = 1 - C(2,2)/C(5,2). pass@3 = 1 (no 3-subset
    # avoids all 3 passes). pass@5 = 1.
    assert agg.pass_at_k[1] == pytest.approx(0.6)
    assert agg.pass_at_k[2] == pytest.approx(1.0 - 1.0 / 10.0)   # 0.9
    assert agg.pass_at_k[3] == pytest.approx(1.0)
    assert agg.pass_at_k[5] == pytest.approx(1.0)
    assert set(agg.pass_at_k) == {1, 2, 3, 5}


def test_worked_example_not_bimodal_not_deterministic():
    agg = aggregate_runs(worked_example_runs())
    # 0.34 is partial progress, not collapse below 0.1 -> not bimodal.
    assert agg.bimodal is False
    # No transcript hashes supplied -> determinism cannot be asserted.
    assert agg.deterministic is False


# --------------------------------------------------------------------------- #
# pass@1 identity and pass@k filtering
# --------------------------------------------------------------------------- #

def test_pass_at_1_equals_pass_rate():
    runs = [
        make_run(0.8, functional_pass=True),
        make_run(0.8, functional_pass=True),
        make_run(0.0, functional_pass=False),
    ]
    agg = aggregate_runs(runs)
    assert agg.pass_at_k[1] == pytest.approx(agg.pass_rate)
    assert agg.pass_at_k[1] == pytest.approx(2.0 / 3.0)


def test_pass_at_k_filters_k_above_n_valid():
    # n_valid = 3 -> only k in {1, 2, 3} are computed from default {1,2,3,5}.
    runs = [make_run(1.0, functional_pass=True) for _ in range(3)]
    agg = aggregate_runs(runs)
    assert set(agg.pass_at_k) == {1, 2, 3}
    assert 5 not in agg.pass_at_k


def test_pass_at_k_custom_k_values():
    runs = [make_run(1.0, functional_pass=True) for _ in range(4)]
    agg = aggregate_runs(runs, k_values=(1, 4, 10))
    # k=10 > n_valid=4 is dropped; k=1 and k=4 survive.
    assert set(agg.pass_at_k) == {1, 4}


# --------------------------------------------------------------------------- #
# Void / valid partition
# --------------------------------------------------------------------------- #

def test_infra_failures_excluded_from_valid():
    runs = [
        make_run(1.0, functional_pass=True),
        make_run(0.0, functional_pass=False, status=RunStatus.INFRA_FAILURE),
        make_run(0.0, functional_pass=False, status=RunStatus.INFRA_FAILURE),
    ]
    agg = aggregate_runs(runs)
    assert agg.n_valid == 1
    assert agg.n_pass == 1
    assert agg.pass_rate == pytest.approx(1.0)
    # 2 voided of 3 total attempts.
    assert agg.infra_void_rate == pytest.approx(2.0 / 3.0)


def test_infra_void_rate_zero_when_no_voids():
    runs = [make_run(1.0, functional_pass=True), make_run(0.0, functional_pass=False)]
    agg = aggregate_runs(runs)
    assert agg.infra_void_rate == pytest.approx(0.0)


def test_timeout_and_agent_error_count_as_valid_failures():
    runs = [
        make_run(0.0, functional_pass=False, status=RunStatus.TIMEOUT),
        make_run(0.0, functional_pass=False, status=RunStatus.AGENT_ERROR),
        make_run(1.0, functional_pass=True),
    ]
    agg = aggregate_runs(runs)
    assert agg.n_valid == 3
    assert agg.timeout_rate == pytest.approx(1.0 / 3.0)
    # reliability excludes both TIMEOUT and AGENT_ERROR -> only 1 of 3 completed.
    assert agg.reliability == pytest.approx(1.0 / 3.0)
    assert agg.infra_void_rate == pytest.approx(0.0)


# --------------------------------------------------------------------------- #
# Degenerate cases
# --------------------------------------------------------------------------- #

def test_empty_input():
    agg = aggregate_runs([])
    assert agg.n_valid == 0
    assert agg.n_pass == 0
    assert agg.pass_rate == pytest.approx(0.0)
    assert (agg.wilson_low, agg.wilson_high) == (0.0, 1.0)   # no information
    assert agg.mean_s == pytest.approx(0.0)
    assert agg.median_s == pytest.approx(0.0)
    assert agg.min_s == pytest.approx(0.0)
    assert agg.max_s == pytest.approx(0.0)
    assert agg.std_s == pytest.approx(0.0)
    assert agg.stability == pytest.approx(1.0)               # stability(0) = 1
    assert agg.conservative_continuous == pytest.approx(0.0)
    assert agg.timeout_rate == pytest.approx(0.0)
    assert agg.infra_void_rate == pytest.approx(0.0)
    assert agg.reliability == pytest.approx(0.0)
    assert agg.pass_at_k == {}
    assert agg.deterministic is False
    assert agg.bimodal is False
    assert agg.provisional is True


def test_all_voided_gives_void_rate_one():
    runs = [make_run(0.0, functional_pass=False, status=RunStatus.INFRA_FAILURE)
            for _ in range(3)]
    agg = aggregate_runs(runs)
    assert agg.n_valid == 0
    assert agg.infra_void_rate == pytest.approx(1.0)   # 3 of 3 attempts voided
    assert agg.provisional is True
    assert (agg.wilson_low, agg.wilson_high) == (0.0, 1.0)


def test_single_valid_run_std_and_conservative():
    # n_valid == 1: Bessel std is undefined -> 0.0; conservative collapses to mean.
    agg = aggregate_runs([make_run(0.7, functional_pass=True)])
    assert agg.n_valid == 1
    assert agg.std_s == pytest.approx(0.0)
    assert agg.stability == pytest.approx(1.0)
    assert agg.conservative_continuous == pytest.approx(0.7)
    assert agg.mean_s == pytest.approx(0.7)
    assert agg.median_s == pytest.approx(0.7)
    assert agg.provisional is True
    # pass@1 only.
    assert set(agg.pass_at_k) == {1}
    assert agg.pass_at_k[1] == pytest.approx(1.0)


def test_std_zero_when_all_scores_equal():
    runs = [make_run(0.5, functional_pass=False) for _ in range(4)]
    agg = aggregate_runs(runs)
    assert agg.std_s == pytest.approx(0.0)
    assert agg.stability == pytest.approx(1.0)
    # mean == every value, so conservative bound equals the mean.
    assert agg.conservative_continuous == pytest.approx(0.5)


# --------------------------------------------------------------------------- #
# Provisional flag boundary
# --------------------------------------------------------------------------- #

def test_provisional_boundary_4_vs_5():
    four = [make_run(1.0, functional_pass=True) for _ in range(4)]
    five = [make_run(1.0, functional_pass=True) for _ in range(5)]
    assert aggregate_runs(four).provisional is True
    assert aggregate_runs(five).provisional is False


def test_provisional_counts_only_valid_runs():
    # 5 attempts but only 4 are valid (1 voided) -> provisional.
    runs = [make_run(1.0, functional_pass=True) for _ in range(4)]
    runs.append(make_run(0.0, functional_pass=False, status=RunStatus.INFRA_FAILURE))
    agg = aggregate_runs(runs)
    assert agg.n_valid == 4
    assert agg.provisional is True


# --------------------------------------------------------------------------- #
# Determinism flag
# --------------------------------------------------------------------------- #

def test_deterministic_all_hashes_equal():
    runs = [make_run(1.0, functional_pass=True) for _ in range(3)]
    agg = aggregate_runs(runs, transcript_hashes=["abc", "abc", "abc"])
    assert agg.deterministic is True


def test_not_deterministic_when_hashes_differ():
    runs = [make_run(1.0, functional_pass=True) for _ in range(3)]
    agg = aggregate_runs(runs, transcript_hashes=["abc", "abc", "xyz"])
    assert agg.deterministic is False


def test_not_deterministic_when_no_hashes():
    runs = [make_run(1.0, functional_pass=True) for _ in range(3)]
    assert aggregate_runs(runs).deterministic is False


def test_not_deterministic_when_hash_count_mismatches_valid():
    # 3 valid runs but only 2 hashes supplied -> length mismatch, flag stays off.
    runs = [make_run(1.0, functional_pass=True) for _ in range(3)]
    agg = aggregate_runs(runs, transcript_hashes=["abc", "abc"])
    assert agg.deterministic is False


def test_determinism_hash_count_must_match_valid_not_total():
    # 3 valid + 1 voided = 4 attempts. Hashes aligned to the 3 valid runs.
    runs = [make_run(1.0, functional_pass=True) for _ in range(3)]
    runs.append(make_run(0.0, functional_pass=False, status=RunStatus.INFRA_FAILURE))
    agg = aggregate_runs(runs, transcript_hashes=["h", "h", "h"])
    assert agg.n_valid == 3
    assert agg.deterministic is True


# --------------------------------------------------------------------------- #
# Bimodality flag
# --------------------------------------------------------------------------- #

def test_bimodal_all_or_nothing():
    # S = [0.0, 0.0, 0.95, 0.97, 0.93], c = 3 -> bimodal True.
    runs = [
        make_run(0.0, functional_pass=False),
        make_run(0.0, functional_pass=False),
        make_run(0.95, functional_pass=True),
        make_run(0.97, functional_pass=True),
        make_run(0.93, functional_pass=True),
    ]
    agg = aggregate_runs(runs)
    assert agg.bimodal is True


def test_not_bimodal_when_partial_failure():
    # A failing run at 0.34 is partial progress (>= 0.1) -> not bimodal.
    runs = [
        make_run(0.34, functional_pass=False),
        make_run(0.95, functional_pass=True),
        make_run(0.97, functional_pass=True),
    ]
    agg = aggregate_runs(runs)
    assert agg.bimodal is False


def test_not_bimodal_when_passing_score_below_floor():
    # A passing run at 0.85 sits below the 0.9 high cluster -> not bimodal.
    runs = [
        make_run(0.0, functional_pass=False),
        make_run(0.85, functional_pass=True),
        make_run(0.95, functional_pass=True),
    ]
    agg = aggregate_runs(runs)
    assert agg.bimodal is False


def test_not_bimodal_when_all_pass():
    # Only one outcome group -> max(c, n-c) == n -> not bimodal.
    runs = [make_run(0.95, functional_pass=True) for _ in range(3)]
    agg = aggregate_runs(runs)
    assert agg.bimodal is False


def test_not_bimodal_when_all_fail():
    runs = [make_run(0.0, functional_pass=False) for _ in range(3)]
    agg = aggregate_runs(runs)
    assert agg.bimodal is False


# --------------------------------------------------------------------------- #
# Property identities
# --------------------------------------------------------------------------- #

def test_mean_within_min_max():
    runs = worked_example_runs()
    agg = aggregate_runs(runs)
    assert agg.min_s <= agg.mean_s <= agg.max_s
    assert agg.min_s <= agg.median_s <= agg.max_s


def test_wilson_low_le_pass_rate_le_wilson_high():
    runs = worked_example_runs()
    agg = aggregate_runs(runs)
    assert agg.wilson_low <= agg.pass_rate <= agg.wilson_high


def test_conservative_le_mean():
    runs = worked_example_runs()
    agg = aggregate_runs(runs)
    assert agg.conservative_continuous <= agg.mean_s + 1e-12


def test_stability_matches_std_formula():
    runs = worked_example_runs()
    agg = aggregate_runs(runs)
    assert agg.stability == pytest.approx(max(0.0, 1.0 - 2.0 * agg.std_s), abs=1e-9)


def test_default_k_values_constant():
    assert DEFAULT_K_VALUES == (1, 2, 3, 5)


def test_std_matches_statistics_stdev():
    runs = worked_example_runs()
    agg = aggregate_runs(runs)
    valid_scores = [r.final_score for r in runs if r.status is not RunStatus.INFRA_FAILURE]
    assert agg.std_s == pytest.approx(statistics.stdev(valid_scores))
