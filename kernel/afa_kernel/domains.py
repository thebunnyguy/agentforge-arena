"""Per-domain capability profiling (framework §4).

Pooled weighted pass rate per domain, with a Wilson interval computed on the
Kish effective sample size. Overall = macro-average over displayable domains
(>= 5 tasks AND >= 25 runs). The overall number is a benchmark-relative
convenience, NEVER a universal ability score.
"""

from __future__ import annotations

from collections.abc import Sequence

from .confidence import stability as _stability
from .confidence import wilson_interval
from .types import DomainScore, TaskDomainContribution

MIN_TASKS_DISPLAY = 5
MIN_RUNS_DISPLAY = 25


def domain_score(
    domain: str, contributions: Sequence[TaskDomainContribution]
) -> DomainScore:
    """Pooled per-domain score with a Kish-effective-n Wilson interval.

    pooled_pass_rate = sum(w·c) / sum(w·n)
    n_eff (Kish)     = (sum(w·n))^2 / sum(w^2·n)
    wilson_low/high  = wilson_interval(pooled_pass_rate · n_eff, n_eff)
    stability        = run-mass-weighted mean of per-task stability(std),
                       weights w·n  (i.e. sum(w·n·stab_t) / sum(w·n))
    n_tasks = len(contributions); n_runs = sum(n)
    displayable = n_tasks >= MIN_TASKS_DISPLAY AND n_runs >= MIN_RUNS_DISPLAY

    Worked anchor (framework §4): contributions (w,n,c) =
      (1.0,5,3), (0.5,5,5), (0.25,10,2) -> pooled 6.0/10.0 = 0.60,
      n_eff = 100/6.875 = 14.5455, Wilson -> (0.3542, 0.8040).
    Degenerate sum(w·n) == 0: pooled 0.0, n_eff 0.0, wilson (0.0, 1.0).
    Implements framework §4.
    """
    n_tasks = len(contributions)
    n_runs = sum(con.n for con in contributions)

    sum_wn = sum(con.weight * con.n for con in contributions)
    sum_wc = sum(con.weight * con.c for con in contributions)
    sum_w2n = sum(con.weight * con.weight * con.n for con in contributions)

    displayable = n_tasks >= MIN_TASKS_DISPLAY and n_runs >= MIN_RUNS_DISPLAY

    if sum_wn <= 0.0:
        # Degenerate: no run mass. No information.
        return DomainScore(
            domain=domain,
            pooled_pass_rate=0.0,
            n_eff=0.0,
            wilson_low=0.0,
            wilson_high=1.0,
            stability=0.0,
            n_tasks=n_tasks,
            n_runs=n_runs,
            displayable=displayable,
        )

    pooled_pass_rate = sum_wc / sum_wn
    # sum_w2n > 0 whenever sum_wn > 0 (weights and n are non-negative).
    n_eff = (sum_wn * sum_wn) / sum_w2n

    wilson_low, wilson_high = wilson_interval(pooled_pass_rate * n_eff, n_eff)

    # Run-mass-weighted mean of per-task stability, weights w·n.
    stability_val = (
        sum(con.weight * con.n * _stability(con.std) for con in contributions)
        / sum_wn
    )

    return DomainScore(
        domain=domain,
        pooled_pass_rate=pooled_pass_rate,
        n_eff=n_eff,
        wilson_low=wilson_low,
        wilson_high=wilson_high,
        stability=stability_val,
        n_tasks=n_tasks,
        n_runs=n_runs,
        displayable=displayable,
    )


def macro_overall(domain_scores: Sequence[DomainScore]) -> float | None:
    """Macro-average of pooled_pass_rate over DISPLAYABLE domains only.

    Returns None when no domain is displayable. This is a sortable convenience
    labelled benchmark-relative; it is not comparable across agents evaluated on
    different domain coverage. Implements framework §4.
    """
    displayed = [ds.pooled_pass_rate for ds in domain_scores if ds.displayable]
    if not displayed:
        return None
    return sum(displayed) / len(displayed)
