"""Offline tests for the HTML report renderer. Build a synthetic store and
assert the rendered HTML carries the right numbers and the honesty labels."""

from __future__ import annotations

import pytest

from afa_kernel.confidence import wilson_interval
from afa_kernel.types import RunScore, RunStatus
from afa_runner import SqliteRunStore, domain_profile, render_report
from afa_runner.pipeline import RunRecord


def _score(
    passed: bool,
    voided: bool = False,
    *,
    q: float = 1.0,
    final_score: float | None = None,
) -> RunScore:
    status = RunStatus.INFRA_FAILURE if voided else RunStatus.VALID
    if final_score is None:
        final_score = 1.0 if passed else 0.0
    return RunScore(
        status,
        0 if not passed else 1,
        1.0 if passed else 0.0,
        q,
        {},
        final_score,
        passed,
        voided,
    )


def _rec(agent, task, idx, passed, voided=False, *, q=1.0, final_score=None):
    return RunRecord(
        task_id=task, task_version="1.0.0", agent=agent, idx=idx,
        status=RunStatus.INFRA_FAILURE if voided else RunStatus.VALID,
        score=_score(passed, voided, q=q, final_score=final_score),
        files_changed=1 if passed else 0,
        lines_added=1, lines_removed=0,
        transcript_hash=f"h-{agent}-{task}-{idx}", duration_ms=10,
    )


@pytest.fixture
def store():
    s = SqliteRunStore(":memory:")
    # strong: 5/5 on t1 ; weak: 1/5 on t1 ; provisional: only 3 runs on t1
    for i in range(5):
        s.save_run(_rec("strong", "t1", i, passed=True))
        s.save_run(_rec("weak", "t1", i, passed=(i < 1)))
    for i in range(3):
        s.save_run(_rec("newcomer", "t1", i, passed=True))
    return s


TASKS_META = {"t1": {"difficulty": 2, "domains": [("backend", 1.0)]}}


def test_report_is_standalone_html(store):
    html = render_report(store, TASKS_META, title="T")
    assert html.startswith("<!doctype html>")
    assert html.rstrip().endswith("</html>")
    # Fully self-contained: no external resources to fetch (offline).
    assert "http://" not in html and "https://" not in html and "<script" not in html


def test_leaderboard_orders_and_labels(store):
    html = render_report(store, TASKS_META)
    assert "strong" in html and "weak" in html and "newcomer" in html
    # The 3-run agent is below the ranking threshold -> provisional badge.
    assert "provisional" in html
    # strong (5/5) appears before weak (1/5) in the document (LCB order).
    assert html.index("strong") < html.index("weak")


def test_matrix_shows_pass_counts(store):
    html = render_report(store, TASKS_META)
    assert "5/5" in html      # strong on t1
    assert "1/5" in html      # weak on t1


def test_domain_insufficient_data_below_threshold(store):
    # Only 1 task tags 'backend' (< 5) -> domain must read 'insufficient data'.
    html = render_report(store, TASKS_META)
    assert "insufficient data" in html


def test_renderer_emits_exact_leaderboard_wilson_values(store):
    html = render_report(store, TASKS_META)
    strong_low, _ = wilson_interval(5, 5)
    weak_low, _ = wilson_interval(1, 5)
    assert f'<td class="num">{strong_low:.3f}</td>' in html
    assert f'<td class="num">{weak_low:.3f}</td>' in html
    assert "Wilson 95% [0.566, 1.000]" in html
    assert "Wilson 95% [0.036, 0.624]" in html


def test_renderer_shows_rank_range_when_intervals_overlap():
    store = SqliteRunStore(":memory:")
    try:
        for idx in range(5):
            store.save_run(_rec("perfect", "t1", idx, True))
            store.save_run(_rec("three-of-five", "t1", idx, idx < 3))
        html = render_report(store, TASKS_META)
        assert html.count('<td class="rank">1–2</td>') == 2
    finally:
        store.close()


def test_renderer_domain_profile_uses_numeric_rate_interval_and_real_task_count():
    store = SqliteRunStore(":memory:")
    tasks_meta = {
        f"be-{task}": {"difficulty": 2, "domains": [("backend", 1.0)]}
        for task in range(5)
    }
    try:
        for task_id in tasks_meta:
            for idx in range(5):
                store.save_run(_rec("agent", task_id, idx, idx < 3))
        profile = domain_profile(
            store,
            "agent",
            {task: meta["domains"] for task, meta in tasks_meta.items()},
        )[0]
        html = render_report(store, tasks_meta)
        assert profile.pooled_pass_rate == pytest.approx(0.6)
        assert profile.n_tasks == 5
        assert profile.n_runs == 25
        assert profile.displayable is True
        assert "60%" in html
        assert (
            f"Wilson [{profile.wilson_low:.2f}, {profile.wilson_high:.2f}], "
            "5 tasks"
        ) in html
    finally:
        store.close()


def test_renderer_exposes_q_below_one_and_continuous_score_without_reranking():
    store = SqliteRunStore(":memory:")
    try:
        for idx in range(5):
            store.save_run(
                _rec("quality-limited", "t1", idx, True, q=0.5, final_score=0.925)
            )
        html = render_report(store, TASKS_META)
        assert "5/5 tasks-runs passed" in html
        assert "mean S: 0.925; mean Q: 0.500" in html
        assert '<td class="num">100%</td>' in html
    finally:
        store.close()


def test_renderer_exposes_persisted_time_and_artifact_coverage(store):
    html = render_report(store, TASKS_META)
    assert "Data provenance" in html
    assert "13" in html and "persisted runs" in html
    assert "0/13" in html and "runs with patch artifacts" in html
    assert "Persisted run window:" in html
    assert "artifacts: patches 0/5; test rows on 0/5 runs" in html


def test_renderer_states_backend_heavy_weighting_assumption(store):
    tasks_meta = {
        "t1": {"difficulty": 2, "domains": [("backend", 1.0)]},
        "backend-empty": {"difficulty": 2, "domains": [("backend", 1.0)]},
        "security-empty": {"difficulty": 2, "domains": [("security", 1.0)]},
    }
    html = render_report(store, tasks_meta)
    assert "Benchmark composition" in html
    assert "backend-heavy" in html
    assert "task-tag weights (1.0 primary, 0.5 secondary, 0.25 tertiary)" in html
