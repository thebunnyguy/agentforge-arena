"""Tests for afa_runner.report (framework §2, §4, §6).

These build RunRecord / RunScore directly and insert them with SqliteRunStore,
so they depend only on the (already-implemented) store and the frozen kernel —
NOT on the pipeline/grader. Expected values are reasoned from the kernel's
documented formulas (Wilson interval, rank_by_lcb tie rule, Kish-effective-n
domain pooling), not echoed from report.py's implementation.
"""

from __future__ import annotations

import pytest

from afa_kernel.confidence import wilson_interval, wilson_lower_bound
from afa_kernel.types import RunScore, RunStatus
from afa_runner.pipeline import RunRecord
from afa_runner.report import (
    domain_profile,
    format_leaderboard,
    leaderboard,
    task_aggregate,
)
from afa_runner.store import SqliteRunStore


# --------------------------------------------------------------------------- #
# Builders (independent of pipeline/grader implementations)
# --------------------------------------------------------------------------- #

def make_score(
    *,
    passed: bool,
    status: RunStatus = RunStatus.VALID,
    final_score: float | None = None,
    voided: bool = False,
) -> RunScore:
    """A RunScore where functional_pass is the only thing the leaderboard cares
    about; final_score defaults to 1.0 on pass / 0.0 on fail unless overridden."""
    if final_score is None:
        final_score = 1.0 if passed else 0.0
    gate_product = 1 if passed else 0
    return RunScore(
        status=status,
        gate_product=gate_product,
        t_hidden=1.0 if passed else 0.0,
        q=1.0,
        q_components={},
        final_score=final_score,
        functional_pass=passed,
        voided=voided,
    )


def make_record(
    *,
    agent: str,
    task_id: str,
    idx: int,
    passed: bool,
    status: RunStatus = RunStatus.VALID,
    final_score: float | None = None,
    voided: bool = False,
    transcript_hash: str = "sha256:run",
    task_version: str = "1.0.0",
) -> RunRecord:
    score = make_score(
        passed=passed, status=status, final_score=final_score, voided=voided
    )
    return RunRecord(
        task_id=task_id,
        task_version=task_version,
        agent=agent,
        idx=idx,
        status=status,
        score=score,
        files_changed=1,
        lines_added=3,
        lines_removed=2,
        transcript_hash=transcript_hash,
        duration_ms=1000,
    )


def seed(store: SqliteRunStore, records) -> None:
    for rec in records:
        store.save_run(rec)


def runs(agent, task_id, pattern, *, voided_extra=0, base_idx=0):
    """Build a list of records for one cell from a pass/fail boolean pattern.

    `pattern` is an iterable of bools (one per valid run). `voided_extra` appends
    that many INFRA_FAILURE (voided) runs after the valid ones.
    """
    out = []
    i = base_idx
    for ok in pattern:
        out.append(make_record(agent=agent, task_id=task_id, idx=i, passed=ok))
        i += 1
    for _ in range(voided_extra):
        out.append(
            make_record(
                agent=agent,
                task_id=task_id,
                idx=i,
                passed=False,
                status=RunStatus.INFRA_FAILURE,
                voided=True,
            )
        )
        i += 1
    return out


# --------------------------------------------------------------------------- #
# task_aggregate
# --------------------------------------------------------------------------- #

def test_task_aggregate_counts_passes_and_excludes_voided():
    store = SqliteRunStore(":memory:")
    try:
        # 5 valid (3 pass) + 2 voided INFRA_FAILUREs in the cell.
        seed(store, runs("a", "t", [True, True, True, False, False], voided_extra=2))
        agg = task_aggregate(store, "a", "t")

        # Voided runs never enter n; n_valid = 5, passes = 3.
        assert agg.n_valid == 5
        assert agg.n_pass == 3
        assert agg.pass_rate == pytest.approx(0.6)
        # Wilson interval is exactly the kernel's for (3, 5).
        lo, hi = wilson_interval(3, 5)
        assert agg.wilson_low == pytest.approx(lo)
        assert agg.wilson_high == pytest.approx(hi)
        # 2 voided of 7 total attempts.
        assert agg.infra_void_rate == pytest.approx(2 / 7)
        # n_valid >= 5 -> not provisional.
        assert agg.provisional is False
    finally:
        store.close()


def test_task_aggregate_determinism_flag_from_aligned_hashes():
    """Determinism requires one hash per VALID run, all equal. A voided run with
    a different hash must not break alignment (it is filtered before aggregation)."""
    store = SqliteRunStore(":memory:")
    try:
        recs = [
            make_record(agent="a", task_id="t", idx=0, passed=True,
                        transcript_hash="sha256:same"),
            make_record(agent="a", task_id="t", idx=1, passed=True,
                        transcript_hash="sha256:same"),
            make_record(agent="a", task_id="t", idx=2, passed=True,
                        transcript_hash="sha256:same"),
            # A voided run carrying a DIFFERENT hash — must be excluded.
            make_record(agent="a", task_id="t", idx=3, passed=False,
                        status=RunStatus.INFRA_FAILURE, voided=True,
                        transcript_hash="sha256:DIFFERENT"),
        ]
        seed(store, recs)
        agg = task_aggregate(store, "a", "t")
        assert agg.n_valid == 3
        # All three valid runs share a hash -> deterministic, despite the voided
        # run's divergent hash.
        assert agg.deterministic is True
    finally:
        store.close()


def test_task_aggregate_not_deterministic_when_valid_hashes_differ():
    store = SqliteRunStore(":memory:")
    try:
        recs = [
            make_record(agent="a", task_id="t", idx=0, passed=True,
                        transcript_hash="sha256:one"),
            make_record(agent="a", task_id="t", idx=1, passed=True,
                        transcript_hash="sha256:two"),
        ]
        seed(store, recs)
        agg = task_aggregate(store, "a", "t")
        assert agg.n_valid == 2
        assert agg.deterministic is False
    finally:
        store.close()


def test_task_aggregate_empty_cell_is_degenerate():
    store = SqliteRunStore(":memory:")
    try:
        agg = task_aggregate(store, "ghost", "nope")
        assert agg.n_valid == 0
        assert agg.pass_rate == 0.0
        # Degenerate cell -> widest interval, provisional.
        assert agg.wilson_low == 0.0
        assert agg.wilson_high == 1.0
        assert agg.provisional is True
    finally:
        store.close()


# --------------------------------------------------------------------------- #
# leaderboard
# --------------------------------------------------------------------------- #

def test_leaderboard_three_agents_reproduces_rank_by_lcb_tie_cluster():
    """5/5, 3/5, 0/5: the 5/5 and 3/5 share a rank cluster because the Wilson
    LCB of a perfect 5/5 (0.566) does NOT exceed the 3/5 point estimate (0.6),
    so neither strictly out-ranks the other (framework §6 v0.1 rule). 0/5 is last.
    """
    store = SqliteRunStore(":memory:")
    try:
        seed(store, runs("good", "t", [True] * 5))
        seed(store, runs("mid", "t", [True, True, True, False, False]))
        seed(store, runs("bad", "t", [False] * 5))

        board = leaderboard(store, task_id="t")
        by_agent = {e.agent: e for e in board}

        # Independently reason the boundary that creates the tie.
        assert wilson_lower_bound(5, 5) < 0.6  # LCB(5/5) below p_hat(3/5)
        assert wilson_lower_bound(3, 5) < 1.0  # LCB(3/5) below p_hat(5/5)

        # good and mid tie in rank range [1, 2]; bad is rank 3.
        assert by_agent["good"].rank_low == 1
        assert by_agent["good"].rank_high == 2
        assert by_agent["mid"].rank_low == 1
        assert by_agent["mid"].rank_high == 2
        assert by_agent["bad"].rank_low == 3
        assert by_agent["bad"].rank_high == 3

        # None are provisional (each has n=5).
        assert all(e.provisional is False for e in board)
        assert by_agent["good"].n == 5 and by_agent["mid"].n == 5

        # Ordered by Wilson LCB desc: good (1.0 p_hat, 0.566 LCB) first.
        assert board[0].agent == "good"
        assert board[-1].agent == "bad"

        # pass_rates are the obvious c/n.
        assert by_agent["good"].pass_rate == pytest.approx(1.0)
        assert by_agent["mid"].pass_rate == pytest.approx(0.6)
        assert by_agent["bad"].pass_rate == pytest.approx(0.0)
    finally:
        store.close()


def test_leaderboard_excludes_voided_runs_from_n():
    """Voided INFRA_FAILUREs must not inflate n or count as failures: an agent
    with 5 passes + 3 voided is still 5/5, not 5/8."""
    store = SqliteRunStore(":memory:")
    try:
        seed(store, runs("a", "t", [True] * 5, voided_extra=3))
        board = leaderboard(store, task_id="t")
        entry = next(e for e in board if e.agent == "a")
        assert entry.n == 5
        assert entry.pass_rate == pytest.approx(1.0)
        # Provisional gate is on valid n (5), not total attempts (8).
        assert entry.provisional is False
    finally:
        store.close()


def test_leaderboard_provisional_when_few_valid_runs():
    store = SqliteRunStore(":memory:")
    try:
        # Only 3 valid runs -> below the n>=5 ranking threshold.
        seed(store, runs("rookie", "t", [True, True, False]))
        board = leaderboard(store, task_id="t")
        entry = next(e for e in board if e.agent == "rookie")
        assert entry.n == 3
        assert entry.provisional is True
        assert entry.rank_low is None
        assert entry.rank_high is None
    finally:
        store.close()


def test_leaderboard_pooled_across_tasks_when_no_task_id():
    """Without task_id, an agent's runs across ALL tasks pool into one (c, n)."""
    store = SqliteRunStore(":memory:")
    try:
        # 3 passes on task t1, 2 passes + 1 fail on task t2 -> pooled 5/6.
        seed(store, runs("a", "t1", [True, True, True]))
        seed(store, runs("a", "t2", [True, True, False]))

        pooled = leaderboard(store)  # no task_id
        entry = next(e for e in pooled if e.agent == "a")
        assert entry.n == 6
        assert entry.pass_rate == pytest.approx(5 / 6)

        # Scoping to a single task sees only that task's runs.
        only_t1 = leaderboard(store, task_id="t1")
        e1 = next(e for e in only_t1 if e.agent == "a")
        assert e1.n == 3
        assert e1.pass_rate == pytest.approx(1.0)
    finally:
        store.close()


# --------------------------------------------------------------------------- #
# domain_profile
# --------------------------------------------------------------------------- #

def test_domain_profile_rolls_backend_task_into_backend_domain():
    """A single backend-tagged task (5 valid, 3 pass) rolls into a 'backend'
    DomainScore. With weight 1.0 the pooled rate is just c/n, and the Wilson
    interval is computed on the Kish effective n (= n here, single task)."""
    store = SqliteRunStore(":memory:")
    try:
        # 3 passes (S=1.0), 2 fails (S=0.4): gives the cell a real std for the
        # domain stability roll-up.
        recs = [
            make_record(agent="a", task_id="be", idx=0, passed=True, final_score=1.0),
            make_record(agent="a", task_id="be", idx=1, passed=True, final_score=1.0),
            make_record(agent="a", task_id="be", idx=2, passed=True, final_score=1.0),
            make_record(agent="a", task_id="be", idx=3, passed=False, final_score=0.4),
            make_record(agent="a", task_id="be", idx=4, passed=False, final_score=0.4),
        ]
        seed(store, recs)

        profiles = domain_profile(store, "a", {"be": [("backend", 1.0)]})
        assert len(profiles) == 1
        ds = profiles[0]
        assert ds.domain == "backend"
        assert ds.n_tasks == 1
        assert ds.n_runs == 5
        assert ds.pooled_pass_rate == pytest.approx(0.6)
        # weight 1.0, single task -> Kish n_eff == n == 5.
        assert ds.n_eff == pytest.approx(5.0)
        lo, hi = wilson_interval(3, 5)
        assert ds.wilson_low == pytest.approx(lo)
        assert ds.wilson_high == pytest.approx(hi)
        # Single task -> not enough tasks/runs to display (needs >=5 tasks, >=25 runs).
        assert ds.displayable is False
    finally:
        store.close()


def test_domain_profile_one_task_two_domains_sorted():
    """A task tagged primary backend (1.0) + secondary api (0.5) contributes to
    both domains. Result is one DomainScore per domain, sorted by name."""
    store = SqliteRunStore(":memory:")
    try:
        seed(store, runs("a", "svc", [True, True, True, False]))  # 3/4
        profiles = domain_profile(
            store, "a", {"svc": [("backend", 1.0), ("api", 0.5)]}
        )
        names = [d.domain for d in profiles]
        assert names == ["api", "backend"]  # sorted by domain name

        # Each domain has one contributing task with the same underlying 3/4 cell;
        # with a single task the per-domain weight cancels in pooled_pass_rate.
        for d in profiles:
            assert d.n_tasks == 1
            assert d.n_runs == 4
            assert d.pooled_pass_rate == pytest.approx(0.75)
    finally:
        store.close()


def test_domain_profile_does_not_count_tagged_zero_run_tasks():
    store = SqliteRunStore(":memory:")
    try:
        seed(store, runs("a", "with-runs", [True, True, False, False, False]))
        profiles = domain_profile(
            store,
            "a",
            {
                "with-runs": [("backend", 1.0)],
                "tagged-but-empty": [("backend", 1.0)],
                "entirely-empty": [("security", 1.0)],
            },
        )
        by_domain = {score.domain: score for score in profiles}
        assert by_domain["backend"].n_tasks == 1
        assert by_domain["backend"].n_runs == 5
        assert by_domain["security"].n_tasks == 0
        assert by_domain["security"].n_runs == 0
        assert by_domain["security"].displayable is False
    finally:
        store.close()


def test_domain_profile_pools_multiple_tasks_with_weights():
    """Pooled rate weights each task's (c, n) by its tag weight. Two backend
    tasks: primary 1.0 with 2/5, tertiary 0.25 with 4/5 ->
    pooled = (1.0*2 + 0.25*4) / (1.0*5 + 0.25*5) = 3.0 / 6.25 = 0.48."""
    store = SqliteRunStore(":memory:")
    try:
        seed(store, runs("a", "t1", [True, True, False, False, False]))   # 2/5
        seed(store, runs("a", "t2", [True, True, True, True, False]))     # 4/5
        profiles = domain_profile(
            store,
            "a",
            {"t1": [("backend", 1.0)], "t2": [("backend", 0.25)]},
        )
        assert len(profiles) == 1
        ds = profiles[0]
        assert ds.domain == "backend"
        assert ds.n_tasks == 2
        assert ds.n_runs == 10
        sum_wc = 1.0 * 2 + 0.25 * 4
        sum_wn = 1.0 * 5 + 0.25 * 5
        assert ds.pooled_pass_rate == pytest.approx(sum_wc / sum_wn)
        assert ds.pooled_pass_rate == pytest.approx(0.48)
        # Kish n_eff = (sum_wn)^2 / sum_w2n.
        sum_w2n = 1.0**2 * 5 + 0.25**2 * 5
        assert ds.n_eff == pytest.approx(sum_wn * sum_wn / sum_w2n)
    finally:
        store.close()


# --------------------------------------------------------------------------- #
# format_leaderboard
# --------------------------------------------------------------------------- #

def test_format_leaderboard_renders_ranks_and_provisional():
    store = SqliteRunStore(":memory:")
    try:
        seed(store, runs("good", "t", [True] * 5))
        seed(store, runs("bad", "t", [False] * 5))
        seed(store, runs("rookie", "t", [True, True]))  # provisional (n=2)

        board = leaderboard(store, task_id="t")
        text = format_leaderboard(board)
        lines = text.splitlines()

        # Header row + separator + one row per agent.
        assert lines[0].split()[:1] == ["rank"]
        assert "agent" in lines[0]
        assert "LCB" in lines[0]
        assert len(lines) == 2 + len(board)  # header, separator, rows

        # The provisional rookie row is labelled 'provisional', not a number.
        rookie_line = next(l for l in lines if "rookie" in l)
        assert "provisional" in rookie_line

        # The good agent (rank 1) renders its name and a numeric rank cell.
        good_line = next(l for l in lines if "good" in l)
        assert "provisional" not in good_line
        assert good_line.lstrip().startswith("1")

        # p_hat / LCB are formatted to 3 decimals for the perfect agent.
        assert "1.000" in good_line  # p_hat = 1.000

        # Columns are fixed-width: every body row has the same length as the
        # header (fixed-width table, padded).
        header_len = len(lines[0])
        for body_line in lines[2:]:
            assert len(body_line) <= header_len  # trailing whitespace stripped
    finally:
        store.close()


def test_format_leaderboard_empty_is_just_header():
    text = format_leaderboard([])
    lines = text.splitlines()
    # Header + separator only; no data rows.
    assert len(lines) == 2
    assert "rank" in lines[0] and "agent" in lines[0]
