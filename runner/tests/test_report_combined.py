"""Integrity tests for the exact combined-report generator."""

from __future__ import annotations

import json
import sqlite3

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


def _report_fixture(tmp_path):
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
                    "version": "1.0.0",
                    "manual_difficulty": 2,
                    "domains": [["backend", 1.0]],
                }
            ]
        )
    )
    return db_path, manifest_path


def _track_report_store_closes(monkeypatch):
    store_cls = report_combined.afa.SqliteRunStore
    original_close = store_cls.close
    closed = []

    def track_close(store):
        closed.append(store)
        original_close(store)

    monkeypatch.setattr(store_cls, "close", track_close)
    return closed


def _assert_report_stores_closed(closed):
    # One source store and one aggregate store must both be closed on a
    # post-load failure; checking the actual connection catches leaked owners.
    assert len(closed) == 2
    for store in closed:
        with pytest.raises(sqlite3.ProgrammingError):
            store.load_runs()


def test_combined_report_closes_aggregate_on_synthetic_failure(tmp_path, monkeypatch):
    db_path, manifest_path = _report_fixture(tmp_path)
    closed = _track_report_store_closes(monkeypatch)

    def fail_synthetic(*args, **kwargs):
        raise RuntimeError("synthetic baseline failure")

    monkeypatch.setattr(report_combined, "_add_synthetic_baseline", fail_synthetic)
    with pytest.raises(RuntimeError, match="synthetic baseline failure"):
        report_combined.build_report(db_path, manifest_path)

    _assert_report_stores_closed(closed)


def test_combined_report_closes_aggregate_on_render_failure(tmp_path, monkeypatch):
    db_path, manifest_path = _report_fixture(tmp_path)
    closed = _track_report_store_closes(monkeypatch)

    def fail_render(*args, **kwargs):
        raise RuntimeError("render failure")

    monkeypatch.setattr(report_combined.afa, "render_report", fail_render)
    with pytest.raises(RuntimeError, match="render failure"):
        report_combined.build_report(db_path, manifest_path)

    _assert_report_stores_closed(closed)


def test_combined_report_uses_db_rows_and_labels_only_synthetic_baselines(tmp_path):
    db_path, manifest_path = _report_fixture(tmp_path)  # stored 1.0.0 == current 1.0.0

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
        # current evidence only: nothing to warn about when versions agree
        assert "Current benchmark evidence only" not in html
    finally:
        combined.close()


def test_combined_report_excludes_historical_version_rows_and_says_so(tmp_path):
    """Stored 1.0.0, current 1.0.1: the row is HISTORICAL. It is preserved in the
    DB (still counted as persisted), excluded from the current aggregates, and the
    report states that instead of presenting old-version numbers as current."""
    db_path = tmp_path / "runs.sqlite"
    disk = SqliteRunStore(db_path)
    disk.save_run(_persisted_record())
    disk.close()
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            [{"id": "task-one", "version": "1.0.1", "manual_difficulty": 2,
              "domains": [["backend", 1.0]]}]
        )
    )

    html, combined, counts = report_combined.build_report(db_path, manifest_path)
    try:
        assert counts["qwen2.5-coder:7b"] == (0, 0)  # CURRENT in-scope evidence
        assert combined.load_runs(agent="qwen2.5-coder:7b") == []
        assert len(combined.load_runs(agent=report_combined.ORACLE)) == 5
        assert "1</b><span>persisted runs" in html  # persisted evidence is still shown
        assert "task-one evaluated v1.0.0 → current v1.0.1" in html
        assert "Current benchmark evidence only: 1 historical-version run(s)" in html
        assert "never pooled with current versions" in html
    finally:
        combined.close()


def test_combined_report_separates_multiple_task_versions_instead_of_pooling(tmp_path):
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

    # Same cell holds 1.0.0 and 1.0.1 rows: the report no longer refuses. Only the
    # CURRENT (1.0.1) row is aggregated; the 1.0.0 row is excluded and reported.
    html, combined, counts = report_combined.build_report(db_path, manifest_path)
    try:
        assert counts["qwen2.5-coder:7b"] == (1, 1)
        rows = combined.load_runs(agent="qwen2.5-coder:7b")
        assert [(r.task_version, r.idx) for r in rows] == [("1.0.1", 1)]
        assert "Current benchmark evidence only: 1 historical-version run(s)" in html
    finally:
        combined.close()
