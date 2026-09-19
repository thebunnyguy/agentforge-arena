"""Phase 0 regression coverage for current-DB, live read projections."""

from __future__ import annotations

import hashlib
import os
import shutil
import sqlite3
import time
import urllib.parse
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import afa_runner as afa
from afa_api import db, store_load, worker
from afa_api.main import create_app
from afa_api.store_load import load_stores
from afa_kernel.types import RunScore, RunStatus
from afa_runner.pipeline import RunRecord

TASK = "fix-binary-search"
SENTINEL = "phase0-fallback-sentinel"


def _enc(value: str) -> str:
    return urllib.parse.quote(value, safe="")


def _hash_file(path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _db_file_state(path) -> dict[str, bytes]:
    # SQLite may update the transient -shm index when a read-only connection
    # opens a WAL database; durable main/WAL contents are the preservation claim.
    candidates = (
        path,
        path.with_name(path.name + "-wal"),
    )
    return {
        str(candidate): candidate.read_bytes()
        for candidate in candidates
        if candidate.exists()
    }


def _record(
    agent: str,
    idx: int = 0,
    *,
    passed: bool = True,
    task_id: str = TASK,
    task_version: str = "1.0.0",
) -> RunRecord:
    return RunRecord(
        task_id=task_id,
        task_version=task_version,
        agent=agent,
        idx=idx,
        status=RunStatus.VALID,
        score=RunScore(
            RunStatus.VALID,
            1 if passed else 0,
            1.0 if passed else 0.0,
            1.0,
            {},
            1.0 if passed else 0.0,
            passed,
            False,
        ),
        files_changed=1 if passed else 0,
        lines_added=1 if passed else 0,
        lines_removed=0,
        transcript_hash=f"sha256:phase0-{agent}-{idx}-{passed}",
        duration_ms=1,
    )


def _wait_terminal(client: TestClient, job_id: str) -> dict:
    for _ in range(400):
        job = client.get(f"/api/v1/jobs/{job_id}").json()
        if job["status"] in {"succeeded", "failed", "canceled"}:
            return job
        time.sleep(0.02)
    raise AssertionError(f"job {job_id} did not reach a terminal state")


def _persist_record(path, record: RunRecord) -> None:
    store = afa.SqliteRunStore(path)
    try:
        store.save_run(record)
    finally:
        store.close()


def _persist_sentinel(path) -> None:
    _persist_record(path, _record(SENTINEL))


def test_same_running_app_discovers_new_model_and_stays_on_bound_db(
    tmp_path, monkeypatch
):
    """A real post-startup write is visible through every global projection.

    The worker-created run comes from the MOCK backend, i.e. synthetic evidence:
    it is invisible to the default benchmark view (and reported as excluded) and
    discoverable at once through the explicit synthetic view. A second, job-less
    row with no recorded provider is LEGACY evidence: it appears in the default
    view immediately, and ``evidence=all`` sees both. No restart, cache
    invalidation or reload is involved anywhere.
    """
    working = tmp_path / "working.sqlite"
    fallback = tmp_path / "fallback.sqlite"
    target = f"phase0-live-projection-target-{uuid.uuid4().hex}"
    shutil.copyfile(db.DB_PATH, working)
    shutil.copyfile(db.DB_PATH, fallback)
    _persist_sentinel(fallback)
    monkeypatch.setenv("AFA_DB_PATH", str(fallback))

    app = create_app()
    app.state.db_path = working
    app.state.agent_factory = worker.mock_agent_factory

    import report_combined

    report_output = tmp_path / "leaderboard.html"
    monkeypatch.setattr(report_combined, "OUTPUT", report_output, raising=False)

    syn = "evidence=synthetic"
    allv = "evidence=all"

    with TestClient(app) as client:
        before = client.get("/api/v1/overview").json()
        assert target not in before["models"]
        assert SENTINEL not in before["models"]

        created = client.post(
            "/api/v1/jobs",
            json={
                "model": target,
                "backend": {"kind": "mock"},
                "tasks": [TASK],
                "repeats": 1,
            },
        ).json()
        done = _wait_terminal(client, created["id"])
        assert done["status"] == "succeeded"
        assert done["counters"]["completed_runs"] == 1

        # No reload/restart/cache invalidation: all reads are from the same
        # running TestClient application after the worker persisted the run.
        health = client.get("/api/v1/healthz").json()
        assert health["status"] == "ok"
        assert health["db_path"] == str(working.resolve())

        # The mock run is EXCLUDED from the default benchmark view, and said so.
        default_overview = client.get("/api/v1/overview").json()
        assert target not in default_overview["models"]
        assert target in default_overview["excluded"]["synthetic_models"]
        assert SENTINEL not in default_overview["models"]
        assert target not in client.get("/api/v1/export").json()["models"]

        overview = client.get(f"/api/v1/overview?{syn}").json()
        assert target in overview["models"]
        assert SENTINEL not in overview["models"]
        assert overview["real_counts"][target] == {"n_runs": 1, "n_tasks": 1}
        assert overview["agent_observability"][target]["total_runs"] == 1
        assert any(e["agent"] == target for e in overview["leaderboard"])

        meta = client.get(f"/api/v1/meta?{syn}").json()
        assert target in meta["models"]
        assert SENTINEL not in meta["models"]

        leaderboard = client.get(f"/api/v1/leaderboard?task_id={TASK}&{syn}").json()
        target_entry = next(
            e for e in leaderboard["entries"] if e["agent"] == target
        )
        assert target_entry["n"] == 1
        assert target_entry["pass_rate"] == 1.0

        cell = client.get(f"/api/v1/cell/{_enc(target)}/{TASK}?{syn}").json()
        assert cell["state"] == "captured"
        assert cell["captured"] is True
        assert len(cell["runs"]) == 1
        assert cell["runs"][0]["evidence_class"] == "synthetic"

        domains = client.get(f"/api/v1/domains/{_enc(target)}?{syn}").json()
        assert domains["captured"] is True

        # The tuple route is a forensic route: never filtered by evidence class.
        run = client.get(f"/api/v1/run/{_enc(target)}/{TASK}/0").json()
        assert run["found"] is True
        assert run["patch_available"] is True
        assert run["evidence_class"] == "synthetic"
        # Assert the selected DB's actual forensic values, not only the
        # availability flag. This guards the raw artifact/provenance path.
        assert isinstance(run["patch_text"], str)
        assert run["patch_text"]
        assert run["created_at"]
        assert run["task_version"] == "1.0.0"

        exported = client.get(f"/api/v1/export?{syn}").json()
        assert target in exported["models"]
        assert SENTINEL not in exported["models"]
        assert exported["real_counts"][target] == {"n_runs": 1, "n_tasks": 1}
        export_entry = next(
            e for e in exported["leaderboard"] if e["agent"] == target
        )
        assert export_entry["n"] == 1

        regenerated = client.post(f"/api/v1/reports/regenerate?{syn}")
        assert regenerated.status_code == 200
        assert regenerated.json()["real_counts"][target] == {
            "n_runs": 1,
            "n_tasks": 1,
        }
        synthetic_report = report_output.with_name("leaderboard-synthetic.html")
        assert Path(regenerated.json()["path"]) == synthetic_report
        assert target in synthetic_report.read_text()
        assert SENTINEL not in synthetic_report.read_text()
        assert not report_output.exists()  # the canonical report is never overwritten

        # A second post-startup persistence: a job-less row with NO recorded
        # provider is LEGACY evidence, so the DEFAULT view discovers the model
        # at once while the synthetic view still counts only the mock run.
        _persist_record(working, _record(target, idx=1, passed=False))

        overview_default = client.get("/api/v1/overview").json()
        assert target in overview_default["models"]
        assert overview_default["real_counts"][target] == {"n_runs": 1, "n_tasks": 1}
        assert target in overview_default["excluded"]["synthetic_models"]
        default_entry = next(
            e for e in client.get(f"/api/v1/leaderboard?task_id={TASK}").json()["entries"]
            if e["agent"] == target
        )
        assert default_entry["n"] == 1 and default_entry["pass_rate"] == 0.0
        legacy_run = client.get(f"/api/v1/run/{_enc(target)}/{TASK}/1").json()
        assert legacy_run["evidence_class"] == "legacy" and legacy_run["backend_kind"] is None
        assert client.get(f"/api/v1/overview?{syn}").json()["real_counts"][target] == {
            "n_runs": 1, "n_tasks": 1,
        }

        # ``evidence=all`` sees mock + legacy: numerator and denominator change
        # without restarting the app.
        overview_after = client.get(f"/api/v1/overview?{allv}").json()
        assert overview_after["real_counts"][target] == {"n_runs": 2, "n_tasks": 1}
        leaderboard_after = client.get(f"/api/v1/leaderboard?task_id={TASK}&{allv}").json()
        target_entry_after = next(
            e for e in leaderboard_after["entries"] if e["agent"] == target
        )
        assert target_entry_after["n"] == 2
        assert target_entry_after["pass_rate"] == 0.5

        cell_after = client.get(f"/api/v1/cell/{_enc(target)}/{TASK}?{allv}").json()
        assert len(cell_after["runs"]) == 2

        exported_after = client.get(f"/api/v1/export?{allv}").json()
        assert exported_after["real_counts"][target] == {
            "n_runs": 2,
            "n_tasks": 1,
        }
        export_entry_after = next(
            e for e in exported_after["leaderboard"] if e["agent"] == target
        )
        assert export_entry_after["n"] == 2
        assert export_entry_after["pass_rate"] == 0.5

        regenerated_after = client.post(f"/api/v1/reports/regenerate?{allv}")
        assert regenerated_after.status_code == 200
        assert regenerated_after.json()["real_counts"][target] == {
            "n_runs": 2,
            "n_tasks": 1,
        }
        all_report = report_output.with_name("leaderboard-all.html")
        assert Path(regenerated_after.json()["path"]) == all_report
        report_text = all_report.read_text()
        assert target in report_text
        assert SENTINEL not in report_text
        assert not report_output.exists()

    working_store = afa.SqliteRunStore.open_readonly(working)
    fallback_store = afa.SqliteRunStore.open_readonly(fallback)
    try:
        assert len(working_store.load_runs(agent=target, task_id=TASK)) == 2
        assert not fallback_store.load_runs(agent=target, task_id=TASK)
        assert len(fallback_store.load_runs(agent=SENTINEL, task_id=TASK)) == 1
    finally:
        working_store.close()
        fallback_store.close()


def test_seed_snapshot_is_coherent_and_never_clobbers_a_winner(tmp_path, monkeypatch):
    seed = tmp_path / "seed.sqlite"
    target = tmp_path / "target.sqlite"
    monkeypatch.setattr(db, "EVIDENCE_DB_PATH", seed)
    _persist_record(seed, _record("seed-agent"))

    marker_conn = sqlite3.connect(str(seed))
    try:
        marker_conn.execute("PRAGMA journal_mode=WAL")
        marker_conn.execute("CREATE TABLE seed_marker (value TEXT NOT NULL)")
        marker_conn.execute("INSERT INTO seed_marker VALUES ('copied')")
        marker_conn.commit()
        seed_state = _db_file_state(seed)

        db.ensure_working_db(target)
        copied = afa.SqliteRunStore.open_readonly(target)
        try:
            assert copied.agents() == ["seed-agent"]
            assert len(copied.load_runs(agent="seed-agent")) == 1
        finally:
            copied.close()
        copied_conn = sqlite3.connect(str(target))
        try:
            assert copied_conn.execute(
                "SELECT value FROM seed_marker"
            ).fetchone()[0] == "copied"
        finally:
            copied_conn.close()
        assert _db_file_state(seed) == seed_state
    finally:
        marker_conn.close()

    existing = tmp_path / "existing.sqlite"
    _persist_record(existing, _record("existing-winner"))
    db.ensure_working_db(existing)
    existing_store = afa.SqliteRunStore.open_readonly(existing)
    try:
        assert existing_store.agents() == ["existing-winner"]
    finally:
        existing_store.close()

    raced = tmp_path / "raced.sqlite"
    real_link = os.link

    def create_winner_then_link(source, destination, **kwargs):
        conn = sqlite3.connect(str(raced))
        try:
            conn.execute("CREATE TABLE winner_marker (value TEXT NOT NULL)")
            conn.execute("INSERT INTO winner_marker VALUES ('winner')")
            conn.commit()
        finally:
            conn.close()
        return real_link(source, destination, **kwargs)

    monkeypatch.setattr(db.os, "link", create_winner_then_link)
    db.ensure_working_db(raced)
    raced_conn = sqlite3.connect(str(raced))
    try:
        assert raced_conn.execute(
            "SELECT value FROM winner_marker"
        ).fetchone()[0] == "winner"
    finally:
        raced_conn.close()
    assert not list(tmp_path.glob(f".{raced.name}.seed-*.tmp"))


def test_load_stores_closes_first_aggregate_if_second_acquisition_fails(
    tmp_path, monkeypatch
):
    selected = tmp_path / "selected.sqlite"
    shutil.copyfile(db.DB_PATH, selected)

    store_cls = store_load.afa.SqliteRunStore
    original_init = store_cls.__init__
    original_close = store_cls.close
    memory_acquired = []
    closed = []
    memory_calls = 0

    def fail_second_memory_init(instance, path=":memory:", *args, **kwargs):
        nonlocal memory_calls
        if str(path) == ":memory:":
            memory_calls += 1
            if memory_calls == 2:
                raise RuntimeError("second aggregate acquisition failed")
        original_init(instance, path, *args, **kwargs)
        if str(path) == ":memory:":
            memory_acquired.append(instance)

    def track_close(instance):
        closed.append(instance)
        original_close(instance)

    monkeypatch.setattr(store_cls, "__init__", fail_second_memory_init)
    monkeypatch.setattr(store_cls, "close", track_close)

    with pytest.raises(RuntimeError, match="second aggregate acquisition"):
        load_stores(db_path=selected)

    assert memory_calls == 2
    assert len(memory_acquired) == 1
    assert closed == memory_acquired
    with pytest.raises(sqlite3.ProgrammingError):
        memory_acquired[0].agents()


def test_runtime_rejects_evidence_aliases_but_offline_report_reads_them(
    tmp_path, monkeypatch
):
    evidence = tmp_path / "evidence.sqlite"
    _persist_record(evidence, _record("offline-target"))
    monkeypatch.setattr(db, "EVIDENCE_DB_PATH", evidence)

    alias = tmp_path / "evidence-alias.sqlite"
    alias.symlink_to(evidence)
    with pytest.raises(ValueError, match="immutable evidence database"):
        db.connect(evidence)
    with pytest.raises(ValueError, match="immutable evidence database"):
        db.connect(alias)
    with pytest.raises(ValueError, match="immutable evidence database"):
        db.ensure_working_db(alias)

    raw = sqlite3.connect(str(evidence))
    try:
        with pytest.raises(ValueError, match="immutable evidence database"):
            db.migrate(raw)
    finally:
        raw.close()

    import report_combined

    html, store, counts = report_combined.build_report(db_path=evidence)
    try:
        assert counts["offline-target"] == (1, 1)
        assert "offline-target" in html
    finally:
        store.close()


def test_combined_report_uses_explicit_db_and_discovers_unknown_model(
    tmp_path, monkeypatch
):
    selected = tmp_path / "selected.sqlite"
    fallback = tmp_path / "fallback.sqlite"
    target = f"report-unknown-{uuid.uuid4().hex}"
    shutil.copyfile(db.DB_PATH, selected)
    shutil.copyfile(db.DB_PATH, fallback)
    _persist_record(selected, _record(target))
    _persist_sentinel(fallback)
    monkeypatch.setenv("AFA_DB_PATH", str(fallback))

    import report_combined

    html, store, counts = report_combined.build_report(db_path=selected)
    try:
        assert counts[target] == (1, 1)
        assert SENTINEL not in counts
        assert target in html
        assert SENTINEL not in html
    finally:
        store.close()


def test_missing_or_invalid_report_db_is_unavailable_without_fallback(
    tmp_path, monkeypatch
):
    import report_combined

    missing = tmp_path / "missing.sqlite"
    with pytest.raises(FileNotFoundError, match="report database unavailable"):
        report_combined.build_report(db_path=missing)
    assert not missing.exists()

    invalid = tmp_path / "invalid.sqlite"
    invalid.write_bytes(b"not a sqlite database")
    invalid_bytes = invalid.read_bytes()
    with pytest.raises(sqlite3.DatabaseError):
        load_stores(db_path=invalid)
    with pytest.raises(sqlite3.DatabaseError):
        report_combined.build_report(db_path=invalid)
    assert invalid.read_bytes() == invalid_bytes

    working = tmp_path / "working.sqlite"
    shutil.copyfile(db.DB_PATH, working)
    app = create_app()
    app.state.db_path = working
    with TestClient(app) as client:
        # Change only the app's explicit binding after startup to exercise the
        # API report boundary without allowing lifespan bootstrap to create it.
        app.state.db_path = missing
        response = client.post("/api/v1/reports/regenerate")
        assert response.status_code == 503
        assert "report database unavailable" in response.json()["error"]
    assert not missing.exists()


def test_readonly_sources_cannot_create_or_write_databases(tmp_path):
    missing = tmp_path / "missing-readonly.sqlite"
    with pytest.raises(sqlite3.OperationalError):
        db.connect_readonly(missing)
    assert not missing.exists()

    selected = tmp_path / "selected.sqlite"
    shutil.copyfile(db.DB_PATH, selected)
    before = _hash_file(selected)
    conn = db.connect_readonly(selected)
    try:
        with pytest.raises(sqlite3.OperationalError):
            conn.execute("CREATE TABLE should_not_exist (value TEXT)")
        with pytest.raises(sqlite3.OperationalError):
            conn.execute(
                "INSERT INTO runs "
                "(task_id, task_version, agent, idx, status, transcript_hash, duration_ms) "
                "VALUES ('x', '1.0.0', 'x', 0, 'valid', 'x', 0)"
            )
    finally:
        conn.close()
    assert _hash_file(selected) == before


def test_worker_rejects_opaque_control_plane_connections():
    conn = sqlite3.connect(":memory:")
    try:
        with pytest.raises(RuntimeError, match="cannot determine"):
            worker._conn_db_path(conn)
    finally:
        conn.close()
