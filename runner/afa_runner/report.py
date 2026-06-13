"""Reporting (framework §2, §4, §6).

Turns stored raw runs into the kernel's aggregates, domain profiles, and
leaderboards. No new statistics live here — this module only groups stored runs
and calls the kernel.
"""

from __future__ import annotations

from afa_kernel.aggregate import aggregate_runs
from afa_kernel.domains import domain_score
from afa_kernel.ranking import rank_by_lcb
from afa_kernel.types import (
    AggregateResult,
    DomainScore,
    LeaderboardEntry,
    RankInput,
    RunStatus,
    TaskDomainContribution,
)

from .pipeline import RunRecord
from .store import RunStore


def task_aggregate(store: RunStore, agent: str, task_id: str) -> AggregateResult:
    """Aggregate one (agent, task) cell from stored runs via the kernel
    (aggregate_runs over the cell's RunScores + transcript hashes)."""
    # load_runs returns the cell's runs ordered by (agent, task_id, idx); with
    # both filters set this is exactly the (agent, task) cell in idx order.
    records = store.load_runs(task_id=task_id, agent=agent)
    scores = [r.score for r in records]

    # The kernel aligns transcript_hashes 1:1 with the VALID (non-voided) runs,
    # in order. INFRA_FAILURE runs are voided and excluded from n, so their
    # hashes must NOT be supplied — otherwise the length check (len == n_valid)
    # fails and determinism detection is silently skipped. Filter to non-voided
    # records, preserving idx order, before extracting hashes.
    hashes = [
        r.transcript_hash
        for r in records
        if r.status is not RunStatus.INFRA_FAILURE
    ]
    return aggregate_runs(scores, transcript_hashes=hashes)


def leaderboard(store: RunStore, *, task_id: str | None = None) -> list[LeaderboardEntry]:
    """Rank all agents by Wilson LCB over the chosen scope.

    Scope = a single task (task_id given) or all tasks pooled. For each agent
    compute c = functional passes and n = valid (non-voided) runs in scope, then
    afa_kernel.rank_by_lcb. Implements framework §6.
    """
    rows: list[RankInput] = []
    for agent in store.agents():
        records = store.load_runs(task_id=task_id, agent=agent)
        # n counts only valid (non-voided) runs; voided INFRA_FAILUREs are never
        # held against an agent (framework §1 run-status taxonomy / §6).
        valid = [r for r in records if r.status is not RunStatus.INFRA_FAILURE]
        # An agent with no valid runs in scope still appears (n=0 -> degenerate
        # LCB 0.0, provisional), so the leaderboard is complete over store.agents().
        n = len(valid)
        c = sum(1 for r in valid if r.score.functional_pass)
        rows.append(RankInput(agent=agent, c=c, n=n))
    return rank_by_lcb(rows)


def domain_profile(store: RunStore, agent: str, task_domains: dict[str, list]) -> list[DomainScore]:
    """Per-domain capability for one agent (framework §4).

    task_domains maps task_id -> list of (domain, weight). For each domain,
    build TaskDomainContribution(weight, n, c, std) per task touching it (n/c/std
    from that task's aggregate) and call afa_kernel.domain_score. Return one
    DomainScore per domain, sorted by domain name.
    """
    # Invert task_domains into domain -> [(task_id, weight), ...]. Each task may
    # tag several domains (primary/secondary/tertiary), so one task aggregate can
    # contribute to multiple domains.
    by_domain: dict[str, list[tuple[str, float]]] = {}
    for task_id, tags in task_domains.items():
        for domain, weight in tags:
            by_domain.setdefault(domain, []).append((task_id, float(weight)))

    # Cache aggregates so a task tagged in several domains is aggregated once.
    agg_cache: dict[str, AggregateResult] = {}

    def _agg(task_id: str) -> AggregateResult:
        if task_id not in agg_cache:
            agg_cache[task_id] = task_aggregate(store, agent, task_id)
        return agg_cache[task_id]

    scores: list[DomainScore] = []
    for domain in sorted(by_domain):
        contributions: list[TaskDomainContribution] = []
        for task_id, weight in by_domain[domain]:
            agg = _agg(task_id)
            contributions.append(
                TaskDomainContribution(
                    weight=weight,
                    n=agg.n_valid,
                    c=agg.n_pass,
                    std=agg.std_s,
                )
            )
        scores.append(domain_score(domain, contributions))
    return scores


def format_leaderboard(entries: list[LeaderboardEntry]) -> str:
    """Render a leaderboard as a fixed-width text table (agent, n, p_hat, LCB,
    rank or 'provisional'). Pure formatting, for the demo/CLI."""
    headers = ("rank", "agent", "n", "p_hat", "LCB")

    def _rank_cell(e: LeaderboardEntry) -> str:
        if e.provisional or e.rank_low is None or e.rank_high is None:
            return "provisional"
        if e.rank_low == e.rank_high:
            return str(e.rank_low)
        return f"{e.rank_low}-{e.rank_high}"

    # Build the body rows first so column widths can size to the actual content.
    body: list[tuple[str, str, str, str, str]] = []
    for e in entries:
        body.append(
            (
                _rank_cell(e),
                e.agent,
                str(e.n),
                f"{e.pass_rate:.3f}",
                f"{e.wilson_low:.3f}",
            )
        )

    # Column widths: max of header and every cell in that column.
    widths = [len(h) for h in headers]
    for row in body:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(cell))

    # Left-align the agent column (column index 1); right-align the rest so the
    # numeric columns line up on their last digit.
    def _fmt_row(cells: tuple[str, ...]) -> str:
        out = []
        for i, cell in enumerate(cells):
            if i == 1:
                out.append(cell.ljust(widths[i]))
            else:
                out.append(cell.rjust(widths[i]))
        return "  ".join(out).rstrip()

    lines = [_fmt_row(headers)]
    lines.append("  ".join("-" * w for w in widths))
    for row in body:
        lines.append(_fmt_row(row))
    return "\n".join(lines)
