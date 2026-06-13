"""Confidence and uncertainty primitives (framework §3).

Pure stdlib. The v0.1 workhorse is the Wilson score interval; rankings use its
lower bound. pass@k uses the unbiased estimator. t-critical values come from a
hardcoded one-sided 95% table (no scipy).
"""

from __future__ import annotations

import math

Z_95 = 1.96  # two-sided 95% normal quantile

# One-sided 95% (upper-tail 0.05) Student-t critical values for df = 1..30.
# Beyond df = 30 the normal limit 1.645 is used. Values are the standard
# t-distribution upper 0.05 quantiles (e.g. df=1 -> 6.314, df=inf -> 1.645).
_T_95_ONE_SIDED: dict[int, float] = {
    1: 6.314,
    2: 2.920,
    3: 2.353,
    4: 2.132,
    5: 2.015,
    6: 1.943,
    7: 1.895,
    8: 1.860,
    9: 1.833,
    10: 1.812,
    11: 1.796,
    12: 1.782,
    13: 1.771,
    14: 1.761,
    15: 1.753,
    16: 1.746,
    17: 1.740,
    18: 1.734,
    19: 1.729,
    20: 1.725,
    21: 1.721,
    22: 1.717,
    23: 1.714,
    24: 1.711,
    25: 1.708,
    26: 1.706,
    27: 1.703,
    28: 1.701,
    29: 1.699,
    30: 1.697,
}

# Normal-distribution limit used for df > 30 (and as the t-table's df=inf value).
_T_95_NORMAL_LIMIT = 1.645


def wilson_interval(c: float, n: float, z: float = Z_95) -> tuple[float, float]:
    """Wilson score interval for a binomial proportion.

    Accepts FLOAT c and n so the same function serves both integer run counts
    and the Kish effective sample size used for domain pooling (framework §4).

    p_hat = c / n
    centre = (p_hat + z^2/(2n)) / (1 + z^2/n)
    half   = (z / (1 + z^2/n)) * sqrt( p_hat(1-p_hat)/n + z^2/(4 n^2) )
    return (max(0, centre - half), min(1, centre + half))

    Anchor: c=3, n=5, z=1.96 -> (0.2307, 0.8824).
    Edge: n == 0 -> (0.0, 1.0) (no information).

    Implements framework §3.
    """
    if n <= 0:
        # No information: the widest possible interval.
        return (0.0, 1.0)

    p_hat = c / n
    z2 = z * z
    denom = 1.0 + z2 / n
    centre = (p_hat + z2 / (2.0 * n)) / denom
    # Guard the variance term against tiny negative values from float error.
    variance_term = p_hat * (1.0 - p_hat) / n + z2 / (4.0 * n * n)
    half = (z / denom) * math.sqrt(max(0.0, variance_term))
    # Snap the degenerate endpoints exactly: an all-fail proportion (p_hat <= 0)
    # has no positive evidence, so its lower bound is exactly 0.0; an all-pass
    # proportion (p_hat >= 1) has an upper bound of exactly 1.0. Without this,
    # sub-epsilon float residue (e.g. centre - half == 1.39e-17 for c=0, n=26)
    # leaks through the max(0.0, ...) clamp.
    lo = 0.0 if p_hat <= 0.0 else max(0.0, centre - half)
    hi = 1.0 if p_hat >= 1.0 else min(1.0, centre + half)
    return (lo, hi)


def wilson_lower_bound(c: float, n: float, z: float = Z_95) -> float:
    """Lower endpoint of wilson_interval; the v0.1 ranking key (framework §3, §6)."""
    return wilson_interval(c, n, z)[0]


def pass_at_k(n: int, c: int, k: int) -> float:
    """Unbiased pass@k estimator (Chen et al. 2021): 1 - C(n-c, k) / C(n, k).

    Defined only for 1 <= k <= n. pass@1 == c/n by construction.
    Anchor: n=5, c=2, k=3 -> 0.9.  (C(3,3)/C(5,3) = 1/10.)

    Use math.comb. Raise ValueError for k < 1 or k > n.
    Implements framework §2.
    """
    if k < 1 or k > n:
        raise ValueError(f"pass_at_k requires 1 <= k <= n; got n={n}, k={k}")
    # If there are at least (n - c) + 1 ... i.e. fewer non-passing samples than k,
    # every k-subset must contain a pass; math.comb(n-c, k) == 0 handles this.
    return 1.0 - math.comb(n - c, k) / math.comb(n, k)


def t_critical_one_sided_95(df: int) -> float:
    """One-sided 95% (upper-tail 0.05) Student-t critical value.

    Hardcoded table for df = 1..30; for df > 30 return the normal limit 1.645.
    Anchors: df=4 -> 2.132, df=9 -> 1.833.  Raise ValueError for df < 1.
    Used by the continuous conservative score (framework §2).
    """
    if df < 1:
        raise ValueError(f"t_critical_one_sided_95 requires df >= 1; got df={df}")
    if df > 30:
        return _T_95_NORMAL_LIMIT
    return _T_95_ONE_SIDED[df]


def stability(std: float) -> float:
    """Stability = max(0, 1 - 2·std).

    The maximum std of a [0,1]-bounded variable is 0.5, so this maps to [0,1].
    Implements framework §2.
    """
    return max(0.0, 1.0 - 2.0 * std)
