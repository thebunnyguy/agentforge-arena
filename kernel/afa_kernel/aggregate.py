"""Repeated-run aggregation for one (agent, task) cell (framework §2).

Consumes a sequence of RunScore (one per attempt) and produces a single
AggregateResult. INFRA_FAILURE runs are voided: excluded from n_valid and from
the S distribution, but counted for infra_void_rate.
"""

from __future__ import annotations

import math
import statistics
from collections.abc import Sequence

from .confidence import pass_at_k, stability, t_critical_one_sided_95, wilson_interval
from .types import AggregateResult, RunScore, RunStatus

DEFAULT_K_VALUES: tuple[int, ...] = (1, 2, 3, 5)

# Bimodality thresholds (framework §2.8): a passing cluster sits above 0.9,
# a failing cluster sits below 0.1.
_BIMODAL_PASS_FLOOR = 0.9
_BIMODAL_FAIL_CEIL = 0.1

# A cell with fewer than this many valid runs is provisional (framework §6).
_PROVISIONAL_MIN_N = 5


def aggregate_runs(
    scores: Sequence[RunScore],
    *,
    k_values: Sequence[int] = DEFAULT_K_VALUES,
    transcript_hashes: Sequence[str] | None = None,
) -> AggregateResult:
    """Aggregate the runs of one (agent, task) cell.

    Partition by status:
      voided   = runs with status INFRA_FAILURE
      valid    = all others (VALID, TIMEOUT, AGENT_ERROR)
    n_valid = len(valid); c = number of valid runs with functional_pass True.

    Compute over the valid runs' S values:
      pass_rate = c / n_valid                       (0.0 if n_valid == 0)
      wilson_low/high = wilson_interval(c, n_valid)
      mean_s, median_s, min_s, max_s
      std_s = sample (Bessel, n-1) std; 0.0 when n_valid < 2
      stability = stability(std_s)
      conservative_continuous = max(0, mean_s - t_{.95,n-1} · std_s / sqrt(n_valid))
                                (= mean_s when n_valid < 2)
      timeout_rate = (# TIMEOUT) / n_valid
      reliability  = (# valid not in {TIMEOUT, AGENT_ERROR}) / n_valid
      infra_void_rate = len(voided) / (n_valid + len(voided))   (0.0 if total 0)
      pass_at_k = {k: pass_at_k(n_valid, c, k) for k in k_values if 1 <= k <= n_valid}
      deterministic = transcript_hashes given, len matches valid runs, all equal
      bimodal = max(c, n_valid - c) < n_valid AND every passing S > 0.9 AND
                every failing S < 0.1
      provisional = n_valid < 5

    Degenerate n_valid == 0: return zeros with wilson (0.0, 1.0), provisional True.
    Implements framework §2.
    """
    voided = [s for s in scores if s.status is RunStatus.INFRA_FAILURE]
    valid = [s for s in scores if s.status is not RunStatus.INFRA_FAILURE]

    n_valid = len(valid)
    n_void = len(voided)

    # infra_void_rate is defined even when there are no valid runs; it never
    # divides by zero because the denominator is the total attempt count.
    total_attempts = n_valid + n_void
    infra_void_rate = (n_void / total_attempts) if total_attempts > 0 else 0.0

    # Degenerate cell: no scorable evidence.
    if n_valid == 0:
        return AggregateResult(
            n_valid=0,
            n_pass=0,
            pass_rate=0.0,
            wilson_low=0.0,
            wilson_high=1.0,
            mean_s=0.0,
            median_s=0.0,
            min_s=0.0,
            max_s=0.0,
            std_s=0.0,
            stability=stability(0.0),
            conservative_continuous=0.0,
            timeout_rate=0.0,
            infra_void_rate=infra_void_rate,
            reliability=0.0,
            pass_at_k={},
            deterministic=False,
            bimodal=False,
            provisional=True,
        )

    passes = [s for s in valid if s.functional_pass]
    n_pass = len(passes)
    pass_rate = n_pass / n_valid

    wilson_low, wilson_high = wilson_interval(n_pass, n_valid)

    s_values = [s.final_score for s in valid]
    mean_s = statistics.fmean(s_values)
    median_s = statistics.median(s_values)
    min_s = min(s_values)
    max_s = max(s_values)

    # Bessel-corrected (sample, n-1) std; undefined for a single point.
    if n_valid >= 2:
        std_s = statistics.stdev(s_values)
    else:
        std_s = 0.0

    stability_value = stability(std_s)

    # One-sided Student-t lower bound on the mean of S. With a single run the
    # bound collapses to the mean (no spread information, df undefined).
    if n_valid >= 2:
        t_crit = t_critical_one_sided_95(n_valid - 1)
        conservative_continuous = max(
            0.0, mean_s - t_crit * std_s / math.sqrt(n_valid)
        )
    else:
        conservative_continuous = max(0.0, mean_s)

    n_timeout = sum(1 for s in valid if s.status is RunStatus.TIMEOUT)
    timeout_rate = n_timeout / n_valid

    n_completed = sum(
        1
        for s in valid
        if s.status not in (RunStatus.TIMEOUT, RunStatus.AGENT_ERROR)
    )
    reliability = n_completed / n_valid

    pass_at_k_map: dict[int, float] = {
        k: pass_at_k(n_valid, n_pass, k)
        for k in k_values
        if 1 <= k <= n_valid
    }

    # Determinism: all valid runs carry the same transcript hash. The hash
    # sequence must be supplied and aligned 1:1 with the valid runs.
    deterministic = False
    if transcript_hashes is not None and len(transcript_hashes) == n_valid:
        hashes = list(transcript_hashes)
        if hashes and all(h == hashes[0] for h in hashes):
            deterministic = True

    # Bimodality (framework §2.8): both outcome groups non-empty, every pass
    # in the high cluster, every fail in the low cluster.
    both_groups_nonempty = max(n_pass, n_valid - n_pass) < n_valid
    if both_groups_nonempty:
        fail_scores = [s.final_score for s in valid if not s.functional_pass]
        bimodal = (
            all(score > _BIMODAL_PASS_FLOOR for score in (p.final_score for p in passes))
            and all(score < _BIMODAL_FAIL_CEIL for score in fail_scores)
        )
    else:
        bimodal = False

    provisional = n_valid < _PROVISIONAL_MIN_N

    return AggregateResult(
        n_valid=n_valid,
        n_pass=n_pass,
        pass_rate=pass_rate,
        wilson_low=wilson_low,
        wilson_high=wilson_high,
        mean_s=mean_s,
        median_s=median_s,
        min_s=min_s,
        max_s=max_s,
        std_s=std_s,
        stability=stability_value,
        conservative_continuous=conservative_continuous,
        timeout_rate=timeout_rate,
        infra_void_rate=infra_void_rate,
        reliability=reliability,
        pass_at_k=pass_at_k_map,
        deterministic=deterministic,
        bimodal=bimodal,
        provisional=provisional,
    )
