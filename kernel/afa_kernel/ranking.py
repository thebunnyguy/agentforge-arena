"""Leaderboard ranking by Wilson lower bound, with tie clustering (framework §6).

The conservative lower bound is the ranking key: it automatically penalises
small samples. Strict ordering is only asserted when the evidence supports it;
otherwise agents share a rank range.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from .confidence import wilson_interval
from .types import LeaderboardEntry, RankInput

# Minimum valid-run count for an agent to be ranked; below this an agent is
# provisional and excluded from the ranked set (framework §6).
MIN_RANKED_N = 5


@dataclass
class _Stats:
    """Internal per-agent statistics computed once and reused for the relation."""

    agent: str
    p_hat: float
    wilson_low: float
    wilson_high: float
    n: int


def rank_by_lcb(rows: Sequence[RankInput]) -> list[LeaderboardEntry]:
    """Rank agents by Wilson lower bound with tie clusters.

    1. Provisional split: agents with n < 5 are EXCLUDED from ranking. They are
       returned at the end, sorted by pass_rate desc, with provisional True and
       rank_low = rank_high = None.
    2. Ranked agents (n >= 5): compute p_hat = c/n and the Wilson interval.
       Strict out-ranking (framework §6 v0.1 rule): agent a strictly out-ranks
       agent b iff  LCB_a > p_hat_b.  This relation need not be a total order,
       so express results as rank RANGES:
         rank_low(x)  = 1 + |{a : LCB_a > p_hat_x}|
         rank_high(x) = n_ranked - |{b : LCB_x > p_hat_b}|
       (A fully separated field gives rank_low == rank_high for everyone; the
       top agent is 1-1.)
    3. Return ranked agents sorted by wilson_low desc (ties broken by p_hat
       desc, then agent name asc), followed by the provisional agents.

    Implements framework §6.
    """
    ranked_stats: list[_Stats] = []
    provisional_stats: list[_Stats] = []

    for row in rows:
        # p_hat = c / n; n == 0 is degenerate -> treat as 0.0 pass rate.
        p_hat = row.c / row.n if row.n > 0 else 0.0
        low, high = wilson_interval(row.c, row.n)
        stats = _Stats(
            agent=row.agent,
            p_hat=p_hat,
            wilson_low=low,
            wilson_high=high,
            n=row.n,
        )
        if row.n < MIN_RANKED_N:
            provisional_stats.append(stats)
        else:
            ranked_stats.append(stats)

    n_ranked = len(ranked_stats)

    ranked_entries: list[LeaderboardEntry] = []
    for x in ranked_stats:
        # rank_low(x) = 1 + |{a : LCB_a > p_hat_x}|  (agents that strictly out-rank x)
        # Exclude x itself: an agent can never out-rank itself, even if a residual
        # LCB float artifact makes LCB_x > p_hat_x. This keeps the relation
        # irreflexive and guarantees 1 <= rank_low <= rank_high <= n_ranked.
        better = sum(1 for a in ranked_stats if a is not x and a.wilson_low > x.p_hat)
        # rank_high(x) = n_ranked - |{b : LCB_x > p_hat_b}|  (agents x strictly out-ranks)
        worse = sum(1 for b in ranked_stats if b is not x and x.wilson_low > b.p_hat)
        ranked_entries.append(
            LeaderboardEntry(
                agent=x.agent,
                pass_rate=x.p_hat,
                wilson_low=x.wilson_low,
                wilson_high=x.wilson_high,
                n=x.n,
                provisional=False,
                rank_low=1 + better,
                rank_high=n_ranked - worse,
            )
        )

    # Ranked: wilson_low desc, then p_hat desc, then agent name asc.
    ranked_entries.sort(key=lambda e: (-e.wilson_low, -e.pass_rate, e.agent))

    provisional_entries: list[LeaderboardEntry] = [
        LeaderboardEntry(
            agent=s.agent,
            pass_rate=s.p_hat,
            wilson_low=s.wilson_low,
            wilson_high=s.wilson_high,
            n=s.n,
            provisional=True,
            rank_low=None,
            rank_high=None,
        )
        for s in provisional_stats
    ]
    # Provisional: pass_rate desc, then agent name asc for determinism.
    provisional_entries.sort(key=lambda e: (-e.pass_rate, e.agent))

    return ranked_entries + provisional_entries
