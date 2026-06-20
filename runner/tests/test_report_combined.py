"""Integrity tests for the exact combined-report generator."""

from __future__ import annotations

import json

import pytest

from afa_kernel.types import RunScore, RunStatus
from afa_runner import SqliteRunStore
from afa_runner.pipeline import RunRecord
from examples import report_combined


def _persisted_record() -> RunRecord:
    return RunRecord(
        task_id="task-one",
        task_version="1.0.0",
        agent="qwen2.5-coder:7b",
        idx=0,
        status=RunStatus.VALID,
        score=RunScore(RunStatus.VALID, 1, 1.0, 1.0, {}, 1.0, True, False),
        files_changed=1,
        lines_added=1,
        lines_removed=0,
        transcript_hash="sha256:real-persisted-row",
        duration_ms=10,
    )


def test_combined_report_uses_db_rows_and_labels_only_synthetic_baselines(tmp_path):
    db_path = tmp_path / "runs.sqlite"
    disk = SqliteRunStore(db_path)
    disk.save_run(_persisted_record())
    disk.close()

    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            [
                {
                    "id": "task-one",
                    "version": "1.0.1",
                    "manual_difficulty": 2,
                    "domains": [["backend", 1.0]],
                }
            ]
        )
    )

    html, combined, counts = report_combined.build_report(db_path, manifest_path)
    try:
        assert not hasattr(report_combined, "KNOWN_OLD")
        assert counts["qwen2.5-coder:7b"] == (1, 1)
        assert len(combined.load_runs(agent="qwen2.5-coder:7b")) == 1
        assert len(combined.load_runs(agent=report_combined.ORACLE)) == 5
        assert len(combined.load_runs(agent=report_combined.NOOP)) == 5
        assert "oracle (synthetic baseline)" in html
        assert "noop (synthetic baseline)" in html
        assert "Persisted DB data only" in html
        assert "qwen2.5-coder:7b 1 runs/1 tasks" in html
        assert "1</b><span>persisted runs" in html
        assert "artifacts: patches 0/1; test rows on 0/1 runs" in html
        assert "artifacts: not persisted (synthetic/derived baseline)" in html
        assert "task-one evaluated v1.0.0 → current v1.0.1" in html
        assert "Leaderboard values remain frozen to the stored task versions" in html
    finally:
        combined.close()


def test_combined_report_refuses_to_pool_multiple_task_versions(tmp_path):
    db_path = tmp_path / "runs.sqlite"
    disk = SqliteRunStore(db_path)
    disk.save_run(_persisted_record())
    newer = _persisted_record()
    disk.save_run(
        RunRecord(
            task_id=newer.task_id,
            task_version="1.0.1",
            agent=newer.agent,
            idx=1,
            status=newer.status,
            score=newer.score,
            files_changed=newer.files_changed,
            lines_added=newer.lines_added,
            lines_removed=newer.lines_removed,
            transcript_hash="sha256:new-version",
            duration_ms=newer.duration_ms,
        )
    )
    disk.close()
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            [
                {
                    "id": "task-one",
                    "version": "1.0.1",
                    "manual_difficulty": 2,
                    "domains": [["backend", 1.0]],
                }
            ]
        )
    )

    with pytest.raises(ValueError, match="refusing to pool multiple task versions"):
        report_combined.build_report(db_path, manifest_path)
