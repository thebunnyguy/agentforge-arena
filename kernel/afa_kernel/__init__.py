"""AgentForge Arena v0.1 evaluation kernel.

Pure-stdlib, offline, deterministic. Public API re-exported here.
"""

from __future__ import annotations

from .types import (
    AggregateResult,
    DomainScore,
    Gates,
    LeaderboardEntry,
    QualityInputs,
    RankInput,
    RunInput,
    RunScore,
    RunStatus,
    SecurityFindings,
    Suite,
    TaskDomainContribution,
    TestResult,
    TestStatus,
)
from .confidence import (
    pass_at_k,
    stability,
    t_critical_one_sided_95,
    wilson_interval,
    wilson_lower_bound,
)
from .scoring import QUALITY_WEIGHTS, baseline_adjusted_t_hidden, score_run
from .aggregate import aggregate_runs
from .domains import domain_score, macro_overall
from .ranking import rank_by_lcb

__all__ = [
    # types
    "RunStatus", "Suite", "TestStatus",
    "Gates", "TestResult", "SecurityFindings", "QualityInputs",
    "RunInput", "RunScore", "AggregateResult",
    "TaskDomainContribution", "DomainScore",
    "RankInput", "LeaderboardEntry",
    # confidence
    "wilson_interval", "wilson_lower_bound", "pass_at_k",
    "t_critical_one_sided_95", "stability",
    # scoring
    "score_run", "baseline_adjusted_t_hidden", "QUALITY_WEIGHTS",
    # aggregate
    "aggregate_runs",
    # domains
    "domain_score", "macro_overall",
    # ranking
    "rank_by_lcb",
]

__version__ = "0.1.0"
