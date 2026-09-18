from __future__ import annotations

import json
import os
import select
import shutil
import sqlite3
import subprocess
import sys
import textwrap
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import afa_runner as afa
from afa_api import db, jobs, worker
from afa_api.main import create_app
from afa_api.schemas import Backend, JobCreate
from afa_kernel.types import RunScore, RunStatus
from afa_runner.pipeline import RunRecord

TASK = "fix-binary-search"


@pytest.fixture()
def temp_db(tmp_path: Path) -> Path:
    path = tmp_path / "a3.sqlite"
    shutil.copy(db.DB_PATH, path)
    conn = db.connect(path)
    try:
        db.migrate(conn)
    finally:
        conn.close()
    return path


def _run(conn: sqlite3.Connection, params: JobCreate):
    job = jobs.create_job(conn, params)
    assert jobs.claim_job(conn, job.id)
    token = jobs.owner_token(conn, job.id)
    assert token is not None
    worker.run_job(conn, job.id, agent_factory=worker.mock_agent_factory, owner_token=token)
    return jobs.get_job(conn, job.id)


_LOGICAL_EVIDENCE_TABLES = (
    "evaluation_jobs",
    "evaluation_trials",
    "job_runs",
    "runs",
    "run_scores",
    "diffs",
    "test_results",
)


def _logical_evidence_rows(conn: sqlite3.Connection) -> dict[str, list[tuple]]:
    """Capture logical persisted rows without relying on a WAL file hash."""
    return {
        table: [tuple(row) for row in conn.execute(
            f"SELECT * FROM {table} ORDER BY rowid"
        ).fetchall()]
        for table in _LOGICAL_EVIDENCE_TABLES
    }


def _report_with_test_artifact():
    return SimpleNamespace(
        diff=SimpleNamespace(patch_text="a3-late-patch", touched_protected=False),
        regression=SimpleNamespace(
            results=(SimpleNamespace(name="a3-late-test", passed=True, weight=1.0),)
        ),
        hidden=SimpleNamespace(results=()),
    )


def _job_logical_evidence_rows(
    conn: sqlite3.Connection, evaluation_id: str
) -> dict[str, list[tuple]]:
    """Capture one evaluation's trial/raw/link facts, including claim fields."""
    trials = [
        tuple(row)
        for row in conn.execute(
            "SELECT * FROM evaluation_trials WHERE evaluation_id=? ORDER BY task_id, idx",
            (evaluation_id,),
        ).fetchall()
    ]
    run_ids = [
        int(row["run_id"])
        for row in conn.execute(
            "SELECT run_id FROM job_runs WHERE job_id=? ORDER BY run_id",
            (evaluation_id,),
        ).fetchall()
    ]
    snapshot: dict[str, list[tuple]] = {
        "trials": trials,
        "job_runs": [
            tuple(row)
            for row in conn.execute(
                "SELECT * FROM job_runs WHERE job_id=? ORDER BY run_id",
                (evaluation_id,),
            ).fetchall()
        ],
        "runs": [
            tuple(row)
            for row in conn.execute(
                "SELECT * FROM runs WHERE job_id=? ORDER BY id",
                (evaluation_id,),
            ).fetchall()
        ],
        "run_scores": [],
        "diffs": [],
        "test_results": [],
    }
    if run_ids:
        marks = ",".join("?" for _ in run_ids)
        params = tuple(run_ids)
        for table in ("run_scores", "diffs"):
            snapshot[table] = [
                tuple(row)
                for row in conn.execute(
                    f"SELECT * FROM {table} WHERE run_id IN ({marks}) ORDER BY run_id",
                    params,
                ).fetchall()
            ]
        snapshot["test_results"] = [
            tuple(row)
            for row in conn.execute(
                f"SELECT * FROM test_results WHERE run_id IN ({marks}) ORDER BY id",
                params,
            ).fetchall()
        ]
    return snapshot


class _CancelGateConnection(sqlite3.Connection):
    """Pause exactly before the cancellation UPDATE reaches SQLite."""

    def execute(self, sql, parameters=()):  # type: ignore[override]
        if (
            getattr(self, "gate", None) is not None
            and not getattr(self, "gate_used", False)
            and "UPDATE evaluation_jobs SET cancel_requested=1" in sql
        ):
            self.gate_used = True
            self.gate[0].set()
            assert self.gate[1].wait(5)
        return super().execute(sql, parameters)


def _cross_thread_conn(path: Path, *, factory=sqlite3.Connection):
    conn = sqlite3.connect(str(path), factory=factory, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    db._apply_pragmas(conn)
    return conn


def test_cancel_claim_race_flags_the_actual_running_state(temp_db: Path):
    setup = db.connect(temp_db)
    try:
        created = jobs.create_job(setup, JobCreate(model="cancel-race", tasks=[TASK]))
    finally:
        setup.close()

    reached = threading.Event()
    release = threading.Event()
    cancel_conn = _cross_thread_conn(temp_db, factory=_CancelGateConnection)
    cancel_conn.gate = (reached, release)
    claim_conn = db.connect(temp_db)
    result: list = []
    errors: list[BaseException] = []

    def cancel():
        try:
            result.append(jobs.request_cancel(cancel_conn, created.id))
        except BaseException as exc:  # pragma: no cover - diagnostic propagation
            errors.append(exc)

    thread = threading.Thread(target=cancel)
    thread.start()
    try:
        assert reached.wait(5)
        claimed = jobs.claim_job_token(claim_conn, created.id, "claimer")
        assert claimed == "claimer"
        release.set()
        thread.join(5)
        assert not thread.is_alive()
        assert not errors
        assert result[0].status == "running"
        assert result[0].cancel_requested is True
        stored = jobs.get_job(claim_conn, created.id)
        assert stored.status == "running"
        assert stored.cancel_requested is True
    finally:
        release.set()
        thread.join(5)
        cancel_conn.close()
        claim_conn.close()


def test_reclaim_race_does_not_leave_dirty_connection_or_touch_successor(
    temp_db: Path, monkeypatch: pytest.MonkeyPatch
):
    setup = db.connect(temp_db)
    try:
        created = jobs.create_job(setup, JobCreate(model="reclaim-race", tasks=[TASK]))
        assert jobs.claim_job_token(setup, created.id, "owner") == "owner"
    finally:
        setup.close()

    owner_conn = db.connect(temp_db)
    recover_conn = db.connect(temp_db)
    lock = jobs.try_acquire_owner_lock(owner_conn, created.id)
    assert lock is not None
    original_acquire = jobs.try_acquire_owner_lock

    def finish_then_release(conn, job_id):
        if conn is recover_conn and job_id == created.id:
            jobs.mark_terminal(owner_conn, created.id, "failed", owner_token="owner")
            lock.release()
        return original_acquire(conn, job_id)

    monkeypatch.setattr(jobs, "try_acquire_owner_lock", finish_then_release)
    try:
        assert jobs.reclaim_stale_running(recover_conn, recover_unlocked=True) == []
        assert not recover_conn.in_transaction
        assert jobs.get_job(recover_conn, created.id).status == "failed"
        assert jobs.trial_rows(recover_conn, created.id)[0]["trial_state"] == "pending"
        assert jobs.claim_job_token(recover_conn, created.id, "successor") is None
        # The next standalone poll/migration must remain usable after the
        # obsolete conditional UPDATE observed the finished owner.
        db.migrate(recover_conn)
        assert worker.claim_and_run(recover_conn) is None
    finally:
        if not lock._released:  # pragma: no cover - cleanup after assertion failure
            lock.release()
        recover_conn.close()
        owner_conn.close()


def test_reclaim_preserves_an_unrelated_caller_transaction(temp_db: Path):
    setup = db.connect(temp_db)
    try:
        created = jobs.create_job(setup, JobCreate(model="reclaim-caller", tasks=[TASK]))
        assert jobs.claim_job_token(setup, created.id, "owner") == "owner"
        setup.execute(
            "UPDATE evaluation_jobs SET owner_started_at=datetime('now','-1 hour') WHERE id=?",
            (created.id,),
        )
        setup.commit()
    finally:
        setup.close()

    recover_conn = db.connect(temp_db)
    recover_conn.execute("CREATE TABLE caller_marker (value TEXT)")
    recover_conn.execute("INSERT INTO caller_marker VALUES ('pending')")
    try:
        assert jobs.reclaim_stale_running(recover_conn) == [created.id]
        assert recover_conn.in_transaction
        assert recover_conn.execute("SELECT value FROM caller_marker").fetchone()["value"] == "pending"
        assert jobs.get_job(recover_conn, created.id).status == "queued"
        recover_conn.rollback()
    finally:
        recover_conn.close()

    check = db.connect(temp_db)
    try:
        assert check.execute("SELECT COUNT(*) AS n FROM caller_marker").fetchone()["n"] == 0
        assert jobs.get_job(check, created.id).status == "running"
    finally:
        check.close()


def test_restored_snapshot_resume_reopens_only_blocked_positions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    root = tmp_path / "root"
    task_root = root / "tasks"
    shutil.copytree(Path(db.ROOT) / "tasks" / TASK, task_root / TASK)
    monkeypatch.setattr(db, "ROOT", root)
    monkeypatch.setattr(worker, "TASKS_DIR", task_root)
    path = tmp_path / "restore.sqlite"
    shutil.copy(db.DB_PATH, path)

    task_json = task_root / TASK / "task.json"
    original_task = task_json.read_bytes()
    conn = db.connect(path)
    try:
        db.migrate(conn)
        created = jobs.create_job(
            conn, JobCreate(model="restore-snapshot", tasks=[TASK], repeats=2)
        )
        assert jobs.claim_job(conn, created.id)
        owner = jobs.owner_token(conn, created.id)
        assert owner is not None

        base_factory = worker.mock_agent_factory
        mutated = False

        def mutating_factory(model, task, params):
            base = base_factory(model, task, params)

            class MutatingAgent:
                name = base.name

                def act(self, workspace, task, sandbox):
                    nonlocal mutated
                    result = base.act(workspace, task, sandbox)
                    if not mutated:
                        mutated = True
                        changed = json.loads(task_json.read_text())
                        changed["version"] = "drifted"
                        task_json.write_text(json.dumps(changed))
                    return result

            return MutatingAgent()

        worker.run_job(conn, created.id, agent_factory=mutating_factory, owner_token=owner)
        failed = jobs.get_job(conn, created.id)
        assert failed.status == "failed"
        first_run = jobs.run_ids_for_job(conn, created.id)[0]
        trials = jobs.trial_rows(conn, created.id)
        assert [trial["trial_state"] for trial in trials] == ["completed", "blocked"]

        # Restore byte-for-byte, not merely to an equivalent version string.
        task_json.write_bytes(original_task)
        resumed = jobs.resume_job(conn, created.id)
        assert resumed.id == created.id
        assert resumed.status == "queued"
        trials = jobs.trial_rows(conn, created.id)
        assert [trial["trial_state"] for trial in trials] == ["completed", "pending"]
        assert jobs.run_ids_for_job(conn, created.id) == [first_run]

        assert jobs.claim_job(conn, created.id)
        resumed_owner = jobs.owner_token(conn, created.id)
        assert resumed_owner is not None
        worker.run_job(
            conn, created.id, agent_factory=worker.mock_agent_factory,
            owner_token=resumed_owner,
        )
        done = jobs.get_job(conn, created.id)
        assert done.status == "succeeded"
        assert len(jobs.run_ids_for_job(conn, created.id)) == 2
    finally:
        conn.close()


def test_registered_api_dispatch_and_startup_protect_an_aged_owner(temp_db: Path):
    started = threading.Event()
    release = threading.Event()

    def slow_factory(model, task, params):
        base = worker.mock_agent_factory(model, task, params)

        class SlowAgent:
            name = base.name

            def act(self, workspace, task, sandbox):
                started.set()
                assert release.wait(10)
                return base.act(workspace, task, sandbox)

        return SlowAgent()

    app = create_app()
    app.state.db_path = temp_db
    app.state.agent_factory = slow_factory
    try:
        with TestClient(app) as client:
            created_response = client.post(
                "/api/v1/jobs",
                json={"model": "registered-slow", "tasks": [TASK], "repeats": 1},
            )
            assert created_response.status_code == 200
            job_id = created_response.json()["id"]
            assert started.wait(5)

            conn = db.connect(temp_db)
            try:
                token = jobs.owner_token(conn, job_id)
                conn.execute(
                    "UPDATE evaluation_jobs SET owner_started_at=datetime('now','-1 hour') "
                    "WHERE id=?",
                    (job_id,),
                )
                conn.commit()
            finally:
                conn.close()

            competing = create_app()
            competing.state.db_path = temp_db
            competing.state.agent_factory = slow_factory
            with TestClient(competing) as contender:
                observed = contender.get(f"/api/v1/jobs/{job_id}")
                assert observed.status_code == 200
                assert observed.json()["status"] == "running"
                token_conn = db.connect(temp_db)
                try:
                    assert jobs.owner_token(token_conn, job_id) == token
                finally:
                    token_conn.close()

            release.set()
            for _ in range(200):
                done = client.get(f"/api/v1/jobs/{job_id}").json()
                if done["status"] in {"succeeded", "failed", "canceled"}:
                    break
                time.sleep(0.02)
            assert done["status"] == "succeeded"

            conn = db.connect(temp_db)
            try:
                assert len(jobs.run_ids_for_job(conn, job_id)) == 1
            finally:
                conn.close()
    finally:
        release.set()


_IDENTITY_TABLES = {
    "evaluation_jobs": (
        "CREATE TABLE evaluation_jobs ("
        "id TEXT, status TEXT, cancel_requested INTEGER, params_json TEXT, "
        "total_runs INTEGER, completed_runs INTEGER, passed_runs INTEGER, "
        "voided_runs INTEGER, failed_runs INTEGER, reused_runs INTEGER, "
        "mode TEXT, source_evaluation_id TEXT, snapshot_json TEXT, owner_token TEXT, "
        "owner_started_at TEXT, created_at TEXT, started_at TEXT, finished_at TEXT, "
        "error_message TEXT)",
        "CREATE UNIQUE INDEX bad_identity ON evaluation_jobs(id) WHERE id IS NOT NULL",
        "INSERT INTO evaluation_jobs VALUES ('keep', 'queued', 0, '{}', 0, 0, 0, 0, 0, 0, 'fresh', NULL, NULL, NULL, NULL, datetime('now'), NULL, NULL, NULL)",
    ),
    "app_settings": (
        "CREATE TABLE app_settings (id INTEGER, settings_json TEXT, updated_at TEXT)",
        "CREATE UNIQUE INDEX bad_identity ON app_settings(id) WHERE id IS NOT NULL",
        "INSERT INTO app_settings VALUES (1, '{}', datetime('now'))",
    ),
    "job_events": (
        "CREATE TABLE job_events (id INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT, seq INTEGER, ts TEXT, type TEXT, payload_json TEXT)",
        "CREATE UNIQUE INDEX bad_identity ON job_events(job_id, seq) WHERE job_id IS NOT NULL",
        "INSERT INTO job_events(job_id, seq, ts, type) VALUES ('keep', 1, datetime('now'), 'keep')",
    ),
    "job_runs": (
        "CREATE TABLE job_runs (job_id TEXT, run_id INTEGER)",
        "CREATE UNIQUE INDEX bad_identity ON job_runs(job_id, run_id) WHERE job_id IS NOT NULL",
        "INSERT INTO job_runs VALUES ('keep', 1)",
    ),
    "evaluation_trials": (
        "CREATE TABLE evaluation_trials (evaluation_id TEXT, task_id TEXT, idx INTEGER, "
        "task_version TEXT, task_digest TEXT, trial_state TEXT, evidence_state TEXT, "
        "run_id INTEGER, source_evaluation_id TEXT, source_run_id INTEGER, "
        "origin_evaluation_id TEXT, claim_token TEXT, claimed_at TEXT, completed_at TEXT, "
        "error_message TEXT)",
        "CREATE UNIQUE INDEX bad_identity ON evaluation_trials(evaluation_id, task_id, idx) WHERE trial_state='completed'",
        "INSERT INTO evaluation_trials VALUES ('keep', 'task', 0, '1', 'sha256:x', 'pending', 'missing', NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL)",
    ),
}


@pytest.mark.parametrize("table", sorted(_IDENTITY_TABLES))
def test_migration_rejects_partial_or_missing_app_identity_before_mutation(
    tmp_path: Path, table: str
):
    path = tmp_path / f"bad-{table}.sqlite"
    store = afa.SqliteRunStore(path)
    store.close()
    conn = db.connect(path)
    try:
        db.migrate(conn)
        conn.execute("PRAGMA foreign_keys=OFF")
        conn.execute(f"DROP TABLE {table}")
        create_sql, index_sql, insert_sql = _IDENTITY_TABLES[table]
        conn.execute(create_sql)
        conn.execute(index_sql)
        conn.execute(insert_sql)
        conn.commit()
        conn.execute("PRAGMA foreign_keys=ON")
        before = conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"]
        with pytest.raises(RuntimeError, match=rf"unsupported existing {table} schema.*missing unique"):
            db.migrate(conn)
        assert conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"] == before
    finally:
        conn.close()


def test_dirty_migration_does_not_commit_caller_work(temp_db: Path):
    conn = db.connect(temp_db)
    try:
        conn.execute("CREATE TABLE caller_marker (value TEXT)")
        conn.execute("INSERT INTO caller_marker VALUES ('pending')")
        assert conn.in_transaction
        with pytest.raises(RuntimeError, match="clean connection"):
            db.migrate(conn)
        assert conn.execute("SELECT value FROM caller_marker").fetchone()["value"] == "pending"
        conn.rollback()
    finally:
        conn.close()
    check = db.connect(temp_db)
    try:
        assert check.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='caller_marker'"
        ).fetchone() is not None
        assert check.execute("SELECT COUNT(*) AS n FROM caller_marker").fetchone()["n"] == 0
    finally:
        check.close()


def _transaction_record() -> RunRecord:
    return RunRecord(
        task_id=TASK,
        task_version="1.0.0",
        agent="a3-transaction",
        idx=0,
        status=RunStatus.VALID,
        score=RunScore(RunStatus.VALID, 1, 1.0, 1.0, {}, 1.0, True, False),
        files_changed=1,
        lines_added=1,
        lines_removed=0,
        transcript_hash="sha256:a3-transaction",
        duration_ms=1,
    )


def test_commit_false_failed_raw_save_preserves_caller_work_and_rolls_back_all_raw_parts(
    temp_db: Path,
):
    conn = db.connect(temp_db)
    try:
        conn.execute("CREATE TABLE caller_marker (value TEXT)")
        conn.execute("INSERT INTO caller_marker VALUES ('pending')")
        conn.execute(
            "CREATE TRIGGER fail_a3_score BEFORE INSERT ON run_scores "
            "BEGIN SELECT RAISE(ABORT, 'injected score failure'); END"
        )
        before = {
            table: conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"]
            for table in ("runs", "run_scores", "diffs", "test_results")
        }
        store = afa.SqliteRunStore(connection=conn)
        with pytest.raises(sqlite3.IntegrityError, match="injected score failure"):
            store.save_run(_transaction_record(), commit=False, job_id="a3-job")
        assert conn.in_transaction
        assert conn.execute("SELECT value FROM caller_marker").fetchone()["value"] == "pending"
        after = {
            table: conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"]
            for table in before
        }
        assert after == before
        conn.commit()
    finally:
        conn.close()


@pytest.mark.parametrize("caller_action", ["commit", "rollback"])
def test_commit_false_late_raw_save_rolls_back_every_component_and_preserves_caller_work(
    temp_db: Path, caller_action: str
):
    conn = db.connect(temp_db)
    seen_test_rows: list[int] = []
    try:
        conn.execute("CREATE TABLE caller_marker (value TEXT)")
        conn.execute("INSERT INTO caller_marker VALUES ('pending')")
        conn.create_function(
            "observe_a3_test_insert",
            1,
            lambda run_id: seen_test_rows.append(int(run_id)) or 0,
        )
        conn.execute(
            "CREATE TRIGGER fail_a3_after_test AFTER INSERT ON test_results "
            "BEGIN SELECT observe_a3_test_insert(NEW.run_id); "
            "SELECT RAISE(ABORT, 'injected late test failure'); END"
        )
        before = _logical_evidence_rows(conn)
        store = afa.SqliteRunStore(connection=conn)
        with pytest.raises(sqlite3.IntegrityError, match="injected late test failure"):
            store.save_run(
                _transaction_record(),
                report=_report_with_test_artifact(),
                commit=False,
                job_id="a3-late-job",
            )
        assert seen_test_rows, "the failure must occur after a test row is attempted"
        assert conn.in_transaction
        assert conn.execute("SELECT value FROM caller_marker").fetchone()["value"] == "pending"
        assert _logical_evidence_rows(conn) == before
        if caller_action == "commit":
            conn.commit()
            assert conn.execute("SELECT value FROM caller_marker").fetchone()["value"] == "pending"
        else:
            conn.rollback()
    finally:
        conn.close()

    check = db.connect(temp_db)
    try:
        assert _logical_evidence_rows(check) == before
        if caller_action == "commit":
            assert check.execute("SELECT value FROM caller_marker").fetchone()["value"] == "pending"
        else:
            assert check.execute("SELECT value FROM caller_marker").fetchone() is None
    finally:
        check.close()


def test_worker_failure_rolls_back_raw_score_diff_test_link_and_trial(temp_db: Path):
    conn = db.connect(temp_db)
    try:
        created = jobs.create_job(conn, JobCreate(model="all-or-nothing", tasks=[TASK]))
        assert jobs.claim_job(conn, created.id)
        token = jobs.owner_token(conn, created.id)
        assert token is not None
        conn.execute(
            "CREATE TRIGGER fail_a3_score_worker BEFORE INSERT ON run_scores "
            "BEGIN SELECT RAISE(ABORT, 'worker score failure'); END"
        )
        before = {
            table: conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"]
            for table in ("runs", "run_scores", "diffs", "test_results", "job_runs")
        }
        worker.run_job(conn, created.id, agent_factory=worker.mock_agent_factory, owner_token=token)
        after = {
            table: conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"]
            for table in before
        }
        assert after == before
        assert jobs.trial_rows(conn, created.id)[0]["trial_state"] == "pending"
        assert jobs.get_job(conn, created.id).status == "failed"
    finally:
        conn.close()


def test_worker_association_failure_rolls_back_all_evidence_components(
    temp_db: Path, monkeypatch: pytest.MonkeyPatch
):
    conn = db.connect(temp_db)
    try:
        created = jobs.create_job(conn, JobCreate(model="association-failure", tasks=[TASK]))
        assert jobs.claim_job(conn, created.id)
        token = jobs.owner_token(conn, created.id)
        assert token is not None
        before = _logical_evidence_rows(conn)
        original_complete = jobs.complete_trial
        attempted: dict[str, object] = {}

        def fail_after_association(
            conn_, job_id, task_id, idx, claim_token, run_id, **kwargs
        ):
            original_complete(
                conn_, job_id, task_id, idx, claim_token, run_id, **kwargs
            )
            attempted.update(
                {
                    "runs": conn_.execute(
                        "SELECT COUNT(*) FROM runs WHERE id=?", (run_id,)
                    ).fetchone()[0],
                    "scores": conn_.execute(
                        "SELECT COUNT(*) FROM run_scores WHERE run_id=?", (run_id,)
                    ).fetchone()[0],
                    "diffs": conn_.execute(
                        "SELECT COUNT(*) FROM diffs WHERE run_id=?", (run_id,)
                    ).fetchone()[0],
                    "tests": conn_.execute(
                        "SELECT COUNT(*) FROM test_results WHERE run_id=?", (run_id,)
                    ).fetchone()[0],
                    "links": conn_.execute(
                        "SELECT COUNT(*) FROM job_runs WHERE job_id=? AND run_id=?",
                        (job_id, run_id),
                    ).fetchone()[0],
                    "trial": conn_.execute(
                        "SELECT trial_state FROM evaluation_trials "
                        "WHERE evaluation_id=? AND task_id=? AND idx=?",
                        (job_id, task_id, idx),
                    ).fetchone()[0],
                }
            )
            raise RuntimeError("injected trial publication failure")

        monkeypatch.setattr(jobs, "complete_trial", fail_after_association)
        worker.run_job(
            conn, created.id, agent_factory=worker.mock_agent_factory, owner_token=token
        )
        assert attempted["runs"] == 1
        assert attempted["scores"] == 1
        assert attempted["diffs"] == 1
        assert int(attempted["tests"]) >= 1
        assert attempted["links"] == 1
        assert attempted["trial"] == "completed"
        after = _logical_evidence_rows(conn)
        assert {
            key: value for key, value in after.items() if key != "evaluation_jobs"
        } == {
            key: value for key, value in before.items() if key != "evaluation_jobs"
        }
        assert jobs.trial_rows(conn, created.id)[0]["trial_state"] == "pending"
        assert jobs.trial_rows(conn, created.id)[0]["claim_token"] is None
        assert jobs.get_job(conn, created.id).status == "failed"
    finally:
        conn.close()


def test_post_commit_event_failure_preserves_all_evidence_through_resume(
    temp_db: Path, monkeypatch: pytest.MonkeyPatch
):
    conn = db.connect(temp_db)
    try:
        created = jobs.create_job(conn, JobCreate(model="post-event-components", tasks=[TASK]))
        assert jobs.claim_job(conn, created.id)
        token = jobs.owner_token(conn, created.id)
        assert token is not None
        original_append = jobs.append_event

        def fail_persisted_event(conn_, job_id, event_type, payload=None, **kwargs):
            if event_type == "run_persisted":
                raise RuntimeError("injected post-commit event failure")
            return original_append(conn_, job_id, event_type, payload, **kwargs)

        monkeypatch.setattr(jobs, "append_event", fail_persisted_event)
        worker.run_job(
            conn, created.id, agent_factory=worker.mock_agent_factory, owner_token=token
        )
        persisted = {
            key: value
            for key, value in _logical_evidence_rows(conn).items()
            if key != "evaluation_jobs"
        }
        assert jobs.get_job(conn, created.id).status == "failed"
        run_ids = jobs.run_ids_for_job(conn, created.id)
        assert len(run_ids) == 1

        monkeypatch.setattr(jobs, "append_event", original_append)
        assert jobs.resume_job(conn, created.id).status == "queued"
        assert jobs.claim_job(conn, created.id)
        resumed_owner = jobs.owner_token(conn, created.id)
        assert resumed_owner is not None

        def should_not_execute(*_args, **_kwargs):
            raise AssertionError("resume executed an already completed trial")

        worker.run_job(
            conn, created.id, agent_factory=should_not_execute, owner_token=resumed_owner
        )
        assert jobs.get_job(conn, created.id).status == "succeeded"
        assert jobs.run_ids_for_job(conn, created.id) == run_ids
        final_evidence = {
            key: value
            for key, value in _logical_evidence_rows(conn).items()
            if key != "evaluation_jobs"
        }
        assert final_evidence == persisted
    finally:
        conn.close()


def test_reuse_rejection_covers_incompatible_task_identity_and_unverifiable_evidence(
    temp_db: Path,
):
    conn = db.connect(temp_db)
    try:
        source = _run(conn, JobCreate(model="reuse-source", tasks=[TASK]))
        baseline = _logical_evidence_rows(conn)
        with pytest.raises(jobs.JobStateError, match="incompatible"):
            jobs.create_job(
                conn,
                JobCreate(
                    model="different-model", tasks=[TASK], mode="reuse",
                    source_evaluation_id=source.id,
                ),
            )
        assert _logical_evidence_rows(conn) == baseline

        source_run = jobs.run_ids_for_job(conn, source.id)[0]
        conn.execute("DELETE FROM run_scores WHERE run_id=?", (source_run,))
        conn.commit()
        before_unverifiable = _logical_evidence_rows(conn)
        with pytest.raises(jobs.JobStateError, match="unverifiable"):
            jobs.create_job(
                conn,
                JobCreate(
                    model="reuse-source", tasks=[TASK], mode="reuse",
                    source_evaluation_id=source.id,
                ),
            )
        assert _logical_evidence_rows(conn) == before_unverifiable
    finally:
        conn.close()


@pytest.mark.parametrize(
    "mutation", ["unverifiable", "missing_patch", "missing_test", "unknown_origin"]
)
def test_reuse_rejects_new_eligibility_gates_without_logical_changes(
    temp_db: Path, mutation: str
):
    conn = db.connect(temp_db)
    try:
        source = _run(conn, JobCreate(model="eligibility-source", tasks=[TASK]))
        run_id = jobs.run_ids_for_job(conn, source.id)[0]
        if mutation == "unverifiable":
            conn.execute(
                "UPDATE evaluation_trials SET evidence_state='unverifiable' "
                "WHERE evaluation_id=? AND task_id=? AND idx=0",
                (source.id, TASK),
            )
        elif mutation == "missing_patch":
            conn.execute("DELETE FROM diffs WHERE run_id=?", (run_id,))
        elif mutation == "missing_test":
            conn.execute("DELETE FROM test_results WHERE run_id=?", (run_id,))
        else:
            conn.execute("UPDATE runs SET job_id=NULL WHERE id=?", (run_id,))
        conn.commit()
        before = _logical_evidence_rows(conn)
        with pytest.raises(jobs.JobStateError, match="unverifiable|incomplete|unknown"):
            jobs.create_job(
                conn,
                JobCreate(
                    model="eligibility-source", tasks=[TASK], mode="reuse",
                    source_evaluation_id=source.id,
                ),
            )
        assert _logical_evidence_rows(conn) == before
    finally:
        conn.close()


@pytest.mark.parametrize("mutation", ["model", "backend", "generation", "task_version", "task_digest"])
def test_reuse_rejects_each_incompatible_snapshot_identity_atomically(
    temp_db: Path, mutation: str
):
    conn = db.connect(temp_db)
    try:
        source = _run(conn, JobCreate(model="identity-source", tasks=[TASK]))
        if mutation == "model":
            target = JobCreate(
                model="different-model", tasks=[TASK], mode="reuse",
                source_evaluation_id=source.id,
            )
        elif mutation == "backend":
            target = JobCreate(
                model="identity-source",
                backend=Backend(kind="ollama", base_url="http://localhost:11434"),
                tasks=[TASK], mode="reuse", source_evaluation_id=source.id,
            )
        elif mutation == "generation":
            target = JobCreate(
                model="identity-source", tasks=[TASK], base_seed=999,
                mode="reuse", source_evaluation_id=source.id,
            )
        else:
            snapshot = jobs.get_snapshot(conn, source.id)
            key = "task_version" if mutation == "task_version" else "task_digest"
            snapshot["tasks"][0][key] = "changed-by-fixture"
            conn.execute(
                "UPDATE evaluation_jobs SET snapshot_json=? WHERE id=?",
                (json.dumps(snapshot, sort_keys=True), source.id),
            )
            conn.commit()
            target = JobCreate(
                model="identity-source", tasks=[TASK], mode="reuse",
                source_evaluation_id=source.id,
            )
        before = _logical_evidence_rows(conn)
        with pytest.raises(jobs.JobStateError, match="incompatible"):
            jobs.create_job(conn, target)
        assert _logical_evidence_rows(conn) == before
    finally:
        conn.close()


def test_reuse_rejects_legacy_source_without_creating_any_rows(temp_db: Path):
    conn = db.connect(temp_db)
    try:
        conn.execute(
            "INSERT INTO evaluation_jobs "
            "(id, status, cancel_requested, params_json, total_runs, created_at) "
            "VALUES ('legacy-source', 'failed', 0, '{}', 0, datetime('now'))"
        )
        conn.commit()
        before = _logical_evidence_rows(conn)
        with pytest.raises(jobs.JobStateError, match="unavailable or legacy"):
            jobs.create_job(
                conn,
                JobCreate(
                    model="legacy-source", tasks=[TASK], mode="reuse",
                    source_evaluation_id="legacy-source",
                ),
            )
        assert _logical_evidence_rows(conn) == before
    finally:
        conn.close()


def test_reuse_chain_keeps_immediate_source_and_original_origin_without_execution(
    temp_db: Path,
):
    conn = db.connect(temp_db)
    try:
        source = _run(conn, JobCreate(model="reuse-chain", tasks=[TASK]))
        first_reuse = jobs.create_job(
            conn,
            JobCreate(
                model="reuse-chain", tasks=[TASK], mode="reuse",
                source_evaluation_id=source.id,
            ),
        )
        second_reuse = jobs.create_job(
            conn,
            JobCreate(
                model="reuse-chain", tasks=[TASK], mode="reuse",
                source_evaluation_id=first_reuse.id,
            ),
        )
        raw_count = conn.execute("SELECT COUNT(*) AS n FROM runs").fetchone()["n"]
        assert jobs.claim_job(conn, second_reuse.id)
        owner = jobs.owner_token(conn, second_reuse.id)
        assert owner is not None

        def should_not_execute(*_args):
            raise AssertionError("reuse executed a completed source trial")

        worker.run_job(
            conn, second_reuse.id, agent_factory=should_not_execute, owner_token=owner
        )
        assert jobs.get_job(conn, second_reuse.id).status == "succeeded"
        assert conn.execute("SELECT COUNT(*) AS n FROM runs").fetchone()["n"] == raw_count
        detail = jobs.trial_detail(conn, second_reuse.id, TASK, 0)
        assert detail["source_evaluation_id"] == first_reuse.id
        assert detail["source_run_id"] == jobs.run_ids_for_job(conn, source.id)[0]
        assert detail["origin_evaluation_id"] == source.id
    finally:
        conn.close()


def test_exact_native_runs_keep_distinct_patch_and_test_content(temp_db: Path):
    conn = db.connect(temp_db)
    try:
        first = _run(conn, JobCreate(model="duplicate-content", tasks=[TASK]))
        second = _run(conn, JobCreate(model="duplicate-content", tasks=[TASK]))
        first_id, second_id = jobs.run_ids_for_job(conn, first.id)[0], jobs.run_ids_for_job(conn, second.id)[0]
        for run_id, patch, test_name in (
            (first_id, "patch-first", "test-first"),
            (second_id, "patch-second", "test-second"),
        ):
            conn.execute("UPDATE diffs SET patch_text=? WHERE run_id=?", (patch, run_id))
            conn.execute(
                "UPDATE test_results SET test_name=? WHERE run_id=?",
                (test_name, run_id),
            )
        conn.execute("UPDATE runs SET task_version='unrelated-version' WHERE id=?", (first_id,))
        conn.commit()
    finally:
        conn.close()

    app = create_app()
    app.state.db_path = temp_db
    app.state.auto_dispatch = False
    with TestClient(app) as client:
        first_body = client.get(f"/api/v1/runs/{first_id}")
        second_body = client.get(f"/api/v1/runs/{second_id}")
        assert first_body.status_code == second_body.status_code == 200
        assert first_body.json()["patch_text"] == "patch-first"
        assert second_body.json()["patch_text"] == "patch-second"
        assert first_body.json()["test_results"][0]["test_name"] == "test-first"
        assert second_body.json()["test_results"][0]["test_name"] == "test-second"


def test_trial_detail_does_not_claim_complete_or_comparable_without_test_artifacts(
    temp_db: Path,
):
    conn = db.connect(temp_db)
    try:
        created = _run(conn, JobCreate(model="artifact-state", tasks=[TASK]))
        run_id = jobs.run_ids_for_job(conn, created.id)[0]
        conn.execute("DELETE FROM test_results WHERE run_id=?", (run_id,))
        conn.commit()
        detail = jobs.trial_detail(conn, created.id, TASK, 0)
        assert detail["outcome"]["final_score"] == 1.0
        assert detail["artifact_state"] == "partial"
        assert "comparability" not in detail

        # An unverifiable evidence state cannot regain comparability merely
        # because the raw artifacts happen to remain present.
        conn.execute(
            "INSERT INTO test_results(run_id, suite, test_name, passed, weight) "
            "VALUES (?, 'regression', 'restored-test', 1, 1.0)",
            (run_id,),
        )
        conn.execute(
            "UPDATE evaluation_trials SET evidence_state='unverifiable' "
            "WHERE evaluation_id=? AND task_id=? AND idx=0",
            (created.id, TASK),
        )
        conn.commit()
        unverifiable = jobs.trial_detail(conn, created.id, TASK, 0)
        assert unverifiable["artifact_state"] == "complete"
        assert "comparability" not in unverifiable

        pending = jobs.create_job(conn, JobCreate(model="artifact-pending", tasks=[TASK]))
        pending_detail = jobs.trial_detail(conn, pending.id, TASK, 0)
        assert pending_detail["artifact_state"] == "absent"
        assert pending_detail["outcome"] is None
        assert "comparability" not in pending_detail
    finally:
        conn.close()


def test_legacy_raw_forensics_survive_control_plane_migration_refusal(tmp_path: Path):
    # Build the known pre-A2 raw shape explicitly: runs has no optional job_id,
    # while the control-plane table is full-column but lacks identity.
    source = sqlite3.connect(db.DB_PATH)
    source.row_factory = sqlite3.Row
    run = source.execute(
        "SELECT id, task_id, task_version, agent, idx, status, transcript_hash, "
        "duration_ms, created_at FROM runs ORDER BY id LIMIT 1"
    ).fetchone()
    score = source.execute(
        "SELECT run_id, gate_product, t_hidden, q, final_score, functional_pass, voided "
        "FROM run_scores WHERE run_id=?", (run["id"],)
    ).fetchone()
    diff = source.execute(
        "SELECT run_id, files_changed, lines_added, lines_removed, touched_protected, patch_text "
        "FROM diffs WHERE run_id=?", (run["id"],)
    ).fetchone()
    test_rows = source.execute(
        "SELECT run_id, suite, test_name, passed, weight FROM test_results WHERE run_id=?",
        (run["id"],),
    ).fetchall()
    source.close()

    path = tmp_path / "legacy-raw.sqlite"
    raw = sqlite3.connect(path)
    raw.execute(
        "CREATE TABLE runs (id INTEGER PRIMARY KEY, task_id TEXT NOT NULL, "
        "task_version TEXT NOT NULL, agent TEXT NOT NULL, idx INTEGER NOT NULL, "
        "status TEXT NOT NULL, transcript_hash TEXT NOT NULL, duration_ms INTEGER NOT NULL, "
        "created_at TEXT NOT NULL)"
    )
    raw.execute(
        "CREATE TABLE run_scores (run_id INTEGER, gate_product INTEGER, t_hidden REAL, q REAL, "
        "final_score REAL, functional_pass INTEGER, voided INTEGER, PRIMARY KEY (run_id))"
    )
    raw.execute(
        "CREATE TABLE diffs (run_id INTEGER PRIMARY KEY, files_changed INTEGER, lines_added INTEGER, "
        "lines_removed INTEGER, touched_protected INTEGER, patch_text TEXT)"
    )
    raw.execute(
        "CREATE TABLE test_results (id INTEGER PRIMARY KEY AUTOINCREMENT, run_id INTEGER, "
        "suite TEXT, test_name TEXT, passed INTEGER, weight REAL)"
    )
    raw.execute(
        "INSERT INTO runs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", tuple(run)
    )
    raw.execute("INSERT INTO run_scores VALUES (?, ?, ?, ?, ?, ?, ?)", tuple(score))
    raw.execute("INSERT INTO diffs VALUES (?, ?, ?, ?, ?, ?)", tuple(diff))
    raw.executemany(
        "INSERT INTO test_results(run_id, suite, test_name, passed, weight) VALUES (?, ?, ?, ?, ?)",
        [tuple(row) for row in test_rows],
    )
    raw.execute(
        "CREATE TABLE evaluation_jobs ("
        "id TEXT, status TEXT, cancel_requested INTEGER, params_json TEXT, "
        "total_runs INTEGER, completed_runs INTEGER, passed_runs INTEGER, "
        "voided_runs INTEGER, failed_runs INTEGER, created_at TEXT)"
    )
    raw.execute(
        "INSERT INTO evaluation_jobs VALUES ('keep', 'queued', 0, '{}', 0, 0, 0, 0, 0, datetime('now'))"
    )
    raw.commit()
    run_id = run["id"]
    raw.close()

    app = create_app()
    app.state.db_path = path
    app.state.auto_dispatch = False
    with TestClient(app) as client:
        assert client.get("/api/v1/jobs").status_code == 503
        assert client.post(
            "/api/v1/jobs", json={"model": "blocked", "tasks": [TASK]}
        ).status_code == 503
        assert client.get("/api/v1/settings").status_code == 503
        assert client.put("/api/v1/settings", json={}).status_code == 503
        exact = client.get(f"/api/v1/runs/{run_id}")
        assert exact.status_code == 200
        assert exact.json()["run_id"] == run_id
        assert exact.json()["job_id"] is None

    check = sqlite3.connect(path)
    try:
        assert check.execute("SELECT COUNT(*) FROM evaluation_jobs").fetchone()[0] == 1
        assert check.execute("SELECT id FROM evaluation_jobs").fetchone()[0] == "keep"
    finally:
        check.close()


def _standalone_interruption_script() -> str:
    return textwrap.dedent(
        """
        import sys
        import time
        from pathlib import Path
        from afa_api import worker

        db_path = sys.argv[1]
        ipc = Path(sys.argv[2])
        role = sys.argv[3]

        def factory(model, task, params):
            base = worker.mock_agent_factory(model, task, params)
            if role != "initial":
                return base

            class SlowAgent:
                name = base.name
                calls = 0

                def act(self, workspace, task, sandbox):
                    self.calls += 1
                    (ipc / f"initial-{self.calls}").write_text("started")
                    if self.calls == 2:
                        while not (ipc / "release").exists():
                            time.sleep(0.01)
                    return base.act(workspace, task, sandbox)

            return SlowAgent()

        worker.factory_for = lambda params: factory
        worker.serve(poll_interval=0.03, db_path=db_path)
        """
    )


def test_standalone_process_restart_preserves_completed_trial_and_cancel_state(
    temp_db: Path, tmp_path: Path
):
    ipc = tmp_path / "ipc"
    ipc.mkdir()
    script = _standalone_interruption_script()
    env = dict(os.environ)
    repo = str(Path(__file__).resolve().parents[1])
    env["PYTHONPATH"] = ":".join((repo, f"{repo}/runner", f"{repo}/kernel", f"{repo}/examples"))

    conn = db.connect(temp_db)
    try:
        created = jobs.create_job(
            conn, JobCreate(model="standalone-restart", tasks=[TASK], repeats=2)
        )
    finally:
        conn.close()

    processes: list[subprocess.Popen] = []

    def start(role: str):
        process = subprocess.Popen(
            [sys.executable, "-c", script, str(temp_db), str(ipc), role],
            cwd=repo,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            start_new_session=True,
        )
        processes.append(process)
        return process

    def wait_for_polling(process, timeout=10):
        assert process.stdout is not None
        output: list[str] = []
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if process.poll() is not None:
                output.append(process.stdout.read())
                raise AssertionError(
                    "standalone process exited before polling acknowledgement: "
                    + "".join(output)
                )
            ready, _, _ = select.select(
                [process.stdout], [], [], min(0.1, max(0.0, deadline - time.monotonic()))
            )
            if ready:
                line = process.stdout.readline()
                if line:
                    output.append(line)
                    if line.startswith("[afa-worker] polling "):
                        return "".join(output)
        raise AssertionError(
            "standalone process did not acknowledge worker polling: " + "".join(output)
        )

    def wait_for(predicate, timeout=10):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if predicate():
                return
            time.sleep(0.03)
        raise AssertionError("standalone observer timed out")

    def state():
        conn = db.connect(temp_db)
        try:
            return jobs.get_job(conn, created.id), jobs.run_ids_for_job(conn, created.id)
        finally:
            conn.close()

    def evidence_state():
        conn = db.connect(temp_db)
        try:
            return _job_logical_evidence_rows(conn, created.id)
        finally:
            conn.close()

    initial = start("initial")
    competitor = None
    restart = None
    try:
        wait_for(lambda: (ipc / "initial-2").exists() and state()[0].counters.completed_runs == 1)
        job, run_ids = state()
        assert job.status == "running"
        assert len(run_ids) == 1
        old_token = job_snapshot_token(temp_db, created.id)
        assert initial.poll() is None
        # Age only the diagnostic lease while the real first process still
        # holds the OS lock; startup must observe liveness from that lock.
        conn = db.connect(temp_db)
        try:
            conn.execute(
                "UPDATE evaluation_jobs SET owner_started_at=datetime('now', '-1 hour') "
                "WHERE id=?",
                (created.id,),
            )
            conn.commit()
        finally:
            conn.close()
        before_competitor = evidence_state()

        # A second real standalone startup sees the acquired OS owner, even
        # though it is a competing poller.
        competitor = start("fast")
        startup_output = wait_for_polling(competitor)
        assert "[afa-worker] polling " in startup_output
        assert competitor.poll() is None
        assert initial.poll() is None
        competing_job, competing_ids = state()
        assert competing_job.status == "running"
        assert competing_ids == run_ids
        assert evidence_state() == before_competitor
        assert job_snapshot_token(temp_db, created.id) == old_token
        competitor.kill()
        competitor.wait(timeout=5)

        # Request cancellation while model work is blocked, then interrupt the
        # process before nominal lease expiry. The OS lock is released by kill.
        conn = db.connect(temp_db)
        try:
            canceled = jobs.request_cancel(conn, created.id)
            assert canceled.cancel_requested is True
        finally:
            conn.close()
        initial.kill()
        initial.wait(timeout=5)
        assert initial.returncode is not None

        restart = start("fast")
        wait_for(lambda: state()[0].status == "canceled")
        canceled_job, canceled_ids = state()
        assert canceled_job.cancel_requested is True
        assert canceled_job.counters.completed_runs == 1
        assert canceled_ids == run_ids
        restart.kill()
        restart.wait(timeout=5)

        # Only explicit same-ID resume clears cancellation and allows the hole
        # to execute; automatic recovery above did not clear it.
        conn = db.connect(temp_db)
        try:
            resumed = jobs.resume_job(conn, created.id)
            assert resumed.status == "queued"
            assert resumed.cancel_requested is False
        finally:
            conn.close()
        start("fast")
        wait_for(lambda: state()[0].status == "succeeded")
        done, final_ids = state()
        assert done.counters.completed_runs == 2
        assert final_ids[0] == run_ids[0]
        assert len(final_ids) == 2

        # A stale pre-interruption token cannot mutate the completed successor.
        conn = db.connect(temp_db)
        try:
            old_terminal = jobs.mark_terminal(conn, created.id, "failed", owner_token=old_token)
            assert old_terminal.status == "succeeded"
            assert jobs.get_job(conn, created.id).status == "succeeded"
        finally:
            conn.close()
    finally:
        for process in processes:
            if process.poll() is None:
                process.kill()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:  # pragma: no cover - bounded cleanup
                    process.terminate()
        (ipc / "release").write_text("cleanup")


def test_registered_api_lifespan_dispatches_an_interrupted_trial(
    temp_db: Path, tmp_path: Path
):
    ipc = tmp_path / "api-ipc"
    ipc.mkdir()
    repo = str(Path(__file__).resolve().parents[1])
    env = dict(os.environ)
    env["PYTHONPATH"] = ":".join((repo, f"{repo}/runner", f"{repo}/kernel", f"{repo}/examples"))
    conn = db.connect(temp_db)
    try:
        created = jobs.create_job(
            conn, JobCreate(model="registered-api-restart", tasks=[TASK], repeats=2)
        )
    finally:
        conn.close()

    process = subprocess.Popen(
        [
            sys.executable,
            "-c",
            _standalone_interruption_script(),
            str(temp_db),
            str(ipc),
            "initial",
        ],
        cwd=repo,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )

    def state():
        state_conn = db.connect(temp_db)
        try:
            return jobs.get_job(state_conn, created.id), jobs.run_ids_for_job(state_conn, created.id)
        finally:
            state_conn.close()

    def wait_for(predicate, timeout=10):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if predicate():
                return
            time.sleep(0.03)
        raise AssertionError("registered API interruption observer timed out")

    try:
        wait_for(lambda: (ipc / "initial-2").exists() and state()[0].counters.completed_runs == 1)
        running, run_ids = state()
        assert running.status == "running"
        assert len(run_ids) == 1
        initial_token = job_snapshot_token(temp_db, created.id)
        assert initial_token is not None
        first_run_id = run_ids[0]
        def artifacts(artifact_conn):
            return {
                "runs": [tuple(row) for row in artifact_conn.execute(
                    "SELECT * FROM runs WHERE id=?", (first_run_id,)
                ).fetchall()],
                **{
                    table: [tuple(row) for row in artifact_conn.execute(
                        f"SELECT * FROM {table} WHERE run_id=? ORDER BY rowid",
                        (first_run_id,),
                    ).fetchall()]
                    for table in ("run_scores", "diffs", "test_results", "job_runs")
                },
            }

        first_conn = db.connect(temp_db)
        try:
            first_artifacts = artifacts(first_conn)
            first_trial = tuple(first_conn.execute(
                "SELECT * FROM evaluation_trials WHERE evaluation_id=? AND task_id=? AND idx=0",
                (created.id, TASK),
            ).fetchone())
        finally:
            first_conn.close()

        # The child owns the real OS lock while its second model call is
        # blocked. Kill it before lease expiry, then let registered lifespan
        # recovery/auto-dispatch replace ownership and execute only the hole.
        process.kill()
        process.wait(timeout=5)
        assert process.returncode is not None

        successor_started = threading.Event()
        successor_release = threading.Event()

        def successor_factory(model, task, params):
            base = worker.mock_agent_factory(model, task, params)

            class SuccessorAgent:
                name = base.name

                def act(self, workspace, task, sandbox):
                    successor_started.set()
                    if not successor_release.wait(10):
                        raise AssertionError("registered successor did not release")
                    return base.act(workspace, task, sandbox)

            return SuccessorAgent()

        app = create_app()
        app.state.db_path = temp_db
        app.state.agent_factory = successor_factory
        try:
            with TestClient(app) as client:
                def api_done():
                    response = client.get(f"/api/v1/jobs/{created.id}")
                    assert response.status_code == 200
                    return response.json()["status"] == "succeeded"

                wait_for(lambda: successor_started.is_set())
                successor_token = job_snapshot_token(temp_db, created.id)
                assert successor_token is not None
                assert successor_token != initial_token
                successor_release.set()
                wait_for(api_done)
                done_body = client.get(f"/api/v1/jobs/{created.id}").json()
                assert done_body["status"] == "succeeded"
        finally:
            successor_release.set()

        done, final_ids = state()
        assert done.status == "succeeded"
        assert done.counters.completed_runs == 2
        assert final_ids[0] == first_run_id
        assert len(final_ids) == 2
        final_conn = db.connect(temp_db)
        try:
            final_artifacts = artifacts(final_conn)
            assert final_artifacts == first_artifacts
            assert tuple(final_conn.execute(
                "SELECT * FROM evaluation_trials WHERE evaluation_id=? AND task_id=? AND idx=0",
                (created.id, TASK),
            ).fetchone()) == first_trial
        finally:
            final_conn.close()
    finally:
        if process.poll() is None:
            process.kill()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:  # pragma: no cover - bounded cleanup
                process.terminate()
        (ipc / "release").write_text("cleanup")


def job_snapshot_token(path: Path, job_id: str) -> str | None:
    conn = db.connect(path)
    try:
        return jobs.owner_token(conn, job_id)
    finally:
        conn.close()
