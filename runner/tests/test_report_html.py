"""Offline tests for the HTML report renderer. Build a synthetic store and
assert the rendered HTML carries the right numbers and the honesty labels."""

from __future__ import annotations

import pytest

from afa_kernel.types import RunScore, RunStatus
from afa_runner import SqliteRunStore, render_report
from afa_runner.pipeline import RunRecord


def _score(passed: bool, voided: bool = False) -> RunScore:
    status = RunStatus.INFRA_FAILURE if voided else RunStatus.VALID
    return RunScore(status, 0 if (not passed) else 1, 1.0 if passed else 0.0, 1.0,
                    {}, 1.0 if passed else 0.0, passed, voided)


def _rec(agent, task, idx, passed, voided=False):
    return RunRecord(
        task_id=task, task_version="1.0.0", agent=agent, idx=idx,
        status=RunStatus.INFRA_FAILURE if voided else RunStatus.VALID,
        score=_score(passed, voided), files_changed=1 if passed else 0,
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
