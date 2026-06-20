"""Small end-to-end matrix across distinct task domains."""

from __future__ import annotations

from pathlib import Path

import pytest

from afa_runner import MockAgent, SqliteRunStore, load_task, run_once, snapshot_tree

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize(
    ("task_id", "primary_domain"),
    [
        ("mask-secrets", "security"),
        ("async-batched", "async-concurrency"),
        ("result-type", "api-design"),
    ],
)
def test_reference_edit_runs_scores_and_persists_across_domains(task_id, primary_domain):
    task = load_task(ROOT / "tasks" / task_id)
    assert task.domains[0].domain == primary_domain
    assert task.reference_dir is not None
    agent = MockAgent(
        name=f"reference-{task_id}",
        writes=snapshot_tree(task.reference_dir),
    )

    record = run_once(agent, task)
    assert record.score.functional_pass is True
    assert record.score.final_score == pytest.approx(1.0)
    assert record.grade_report is not None
    assert record.grade_report.hidden.results

    store = SqliteRunStore(":memory:")
    try:
        store.save_run(record)
        summary = store.summary(agent.name)
        assert summary.total_runs == 1
        assert summary.runs_with_patch == 1
        assert summary.runs_with_test_results == 1
    finally:
        store.close()
