"""Version-safe resumability for the persisted evaluator."""

from __future__ import annotations

from afa_kernel.types import RunScore, RunStatus
from afa_runner import SqliteRunStore
from afa_runner.pipeline import RunRecord
from examples.eval_persist import completed_indices


def _record(version: str, idx: int) -> RunRecord:
    return RunRecord(
        task_id="versioned-task",
        task_version=version,
        agent="agent",
        idx=idx,
        status=RunStatus.VALID,
        score=RunScore(RunStatus.VALID, 1, 1.0, 1.0, {}, 1.0, True, False),
        files_changed=1,
        lines_added=1,
        lines_removed=0,
        transcript_hash=f"sha256:{version}:{idx}",
        duration_ms=1,
    )


def test_completed_indices_are_scoped_to_exact_task_version():
    store = SqliteRunStore(":memory:")
    try:
        for idx in range(5):
            store.save_run(_record("1.0.0", idx))
        store.save_run(_record("1.0.1", 0))
        store.save_run(_record("1.0.1", 3))

        assert completed_indices(
            store,
            task_id="versioned-task",
            task_version="1.0.1",
            agent="agent",
        ) == {0, 3}
    finally:
        store.close()
