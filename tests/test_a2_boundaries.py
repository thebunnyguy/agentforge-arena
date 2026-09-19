from __future__ import annotations

import json
import shutil
import sqlite3
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import afa_runner as afa
from afa_api import db, jobs, worker
from afa_api.main import create_app
from afa_api.schemas import Backend, JobCreate
from afa_runner.pipeline import RunRecord
from afa_kernel.types import RunScore, RunStatus

TASK = "fix-binary-search"


@pytest.fixture()
def temp_db(tmp_path: Path) -> Path:
    path = tmp_path / "a2.sqlite"
    shutil.copy(db.DB_PATH, path)
    conn = db.connect(path)
    try:
        db.migrate(conn)
    finally:
        conn.close()
    return path


def _claim(path: Path, *, token: str | None = None) -> tuple[str, str]:
    conn = db.connect(path)
    try:
        job = jobs.create_job(conn, JobCreate(model="a2", tasks=[TASK], repeats=1))
        claimed = jobs.claim_job_token(conn, job.id, token)
        assert claimed is not None
        return job.id, claimed
    finally:
        conn.close()


def test_live_owner_lock_protects_and_startup_recovers_before_lease_expiry(
    temp_db: Path,
):
    job_id, token = _claim(temp_db, token="owner-a")
    owner_conn = db.connect(temp_db)
    contender = db.connect(temp_db)
    lock = jobs.try_acquire_owner_lock(owner_conn, job_id)
    assert lock is not None
    try:
        # Recovery uses the real local owner guard, not the lease timestamp.
        assert jobs.reclaim_stale_running(contender, recover_unlocked=True) == []
    finally:
        lock.release()
    try:
        recovered = jobs.reclaim_stale_running(contender, recover_unlocked=True)
        assert recovered == [job_id]
        assert jobs.get_job(contender, job_id).status == "queued"
        assert jobs.claim_job_token(contender, job_id) not in (None, token)
    finally:
        contender.close()
        owner_conn.close()


def test_two_run_contenders_share_exclusive_publication_boundary(temp_db: Path):
    job_id, token = _claim(temp_db, token="owner-shared")
    started = threading.Event()
    release = threading.Event()

    def slow_factory(model, task, params):
        base = worker.mock_agent_factory(model, task, params)

        class SlowAgent:
            name = base.name

            def act(self, workspace, task, sandbox):
                started.set()
                assert release.wait(5)
                return base.act(workspace, task, sandbox)

        return SlowAgent()

    result: list[BaseException] = []

    def execute_first():
        conn = db.connect(temp_db)
        try:
            worker.run_job(conn, job_id, agent_factory=slow_factory, owner_token=token)
        except BaseException as exc:  # pragma: no cover - diagnostic propagation
            result.append(exc)
        finally:
            conn.close()

    thread = threading.Thread(target=execute_first)
    thread.start()
    assert started.wait(5)
    contender = db.connect(temp_db)
    try:
        # The second dispatcher has the same durable token but cannot acquire
        # the local lock, so it cannot invoke the agent or publish another run.
        worker.run_job(contender, job_id, agent_factory=slow_factory, owner_token=token)
    finally:
        contender.close()
    release.set()
    thread.join(10)
    assert not thread.is_alive()
    assert not result

    conn = db.connect(temp_db)
    try:
        assert jobs.get_job(conn, job_id).status == "succeeded"
        assert len(jobs.run_ids_for_job(conn, job_id)) == 1
        assert conn.execute(
            "SELECT COUNT(*) AS n FROM runs WHERE job_id=?", (job_id,)
        ).fetchone()["n"] == 1
    finally:
        conn.close()


def test_successor_fences_old_trial_and_terminal_mutations(temp_db: Path):
    job_id, old_owner = _claim(temp_db, token="old-owner")
    first = db.connect(temp_db)
    try:
        first_claim = jobs.claim_trial(first, job_id, TASK, 0, old_owner)
        assert first_claim
    finally:
        first.close()

    successor = db.connect(temp_db)
    try:
        assert jobs.reclaim_stale_running(successor, recover_unlocked=True) == [job_id]
        new_owner = jobs.claim_job_token(successor, job_id, "new-owner")
        assert new_owner == "new-owner"
        new_claim = jobs.claim_trial(successor, job_id, TASK, 0, new_owner)
        assert new_claim and new_claim != first_claim
        with pytest.raises(jobs.TrialClaimError):
            jobs.complete_trial(
                successor,
                job_id,
                TASK,
                0,
                first_claim,
                run_id=1,
                owner_token=old_owner,
            )
        old_terminal = jobs.mark_terminal(
            successor, job_id, "failed", owner_token=old_owner
        )
        assert old_terminal is not None
        assert old_terminal.status == "running"
        assert jobs.get_job(successor, job_id).status == "running"
    finally:
        successor.close()


def test_api_startup_does_not_reclaim_live_owner(temp_db: Path):
    job_id, _ = _claim(temp_db, token="live-api-owner")
    conn = db.connect(temp_db)
    lock = jobs.try_acquire_owner_lock(conn, job_id)
    assert lock is not None
    try:
        app = create_app()
        app.state.db_path = temp_db
        app.state.auto_dispatch = False
        with TestClient(app) as client:
            assert client.get(f"/api/v1/jobs/{job_id}").json()["status"] == "running"
    finally:
        lock.release()
        conn.close()


def test_api_startup_reclaims_unlocked_running_work(temp_db: Path):
    job_id, _ = _claim(temp_db, token="interrupted")
    app = create_app()
    app.state.db_path = temp_db
    app.state.auto_dispatch = False
    with TestClient(app) as client:
        response = client.get(f"/api/v1/jobs/{job_id}")
        assert response.status_code == 200
        assert response.json()["status"] == "queued"
    conn = db.connect(temp_db)
    try:
        trial = jobs.trial_rows(conn, job_id)[0]
        assert trial["trial_state"] == "pending"
    finally:
        conn.close()


def test_http_resume_preserves_completed_evidence_and_id(
    temp_db: Path, monkeypatch: pytest.MonkeyPatch
):
    app = create_app()
    app.state.db_path = temp_db
    app.state.auto_dispatch = False
    original_run_once = worker.afa.run_once
    calls = 0
    with TestClient(app) as client:
        created = client.post(
            "/api/v1/jobs",
            json={"model": "http-resume", "tasks": [TASK], "repeats": 2},
        ).json()
        conn = db.connect(temp_db)
        try:
            assert jobs.claim_job(conn, created["id"])
            first_owner = jobs.owner_token(conn, created["id"])
            assert first_owner is not None

            def interrupt_after_first(*args, **kwargs):
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise RuntimeError("interrupt before second position")
                return original_run_once(*args, **kwargs)

            monkeypatch.setattr(worker.afa, "run_once", interrupt_after_first)
            worker.run_job(conn, created["id"], owner_token=first_owner)
            first_id = jobs.run_ids_for_job(conn, created["id"])[0]
            resumed = client.post(f"/api/v1/jobs/{created['id']}/resume")
            assert resumed.status_code == 200
            assert resumed.json()["id"] == created["id"]
            assert resumed.json()["status"] == "queued"
            assert jobs.claim_job(conn, created["id"])
            second_owner = jobs.owner_token(conn, created["id"])
            assert second_owner is not None
            monkeypatch.setattr(worker.afa, "run_once", original_run_once)
            worker.run_job(conn, created["id"], owner_token=second_owner)
        finally:
            conn.close()
        result = client.get(f"/api/v1/jobs/{created['id']}/results")
        assert result.status_code == 200
        body = result.json()
        assert body["status"] == "succeeded"
        run_ids = [trial["run_id"] for trial in body["trials"]]
        assert first_id in run_ids
        assert len(run_ids) == 2
        events = client.get(f"/api/v1/jobs/{created['id']}/events?since=0").json()["events"]
        assert sum(event["type"] == "run_persisted" for event in events) == 2


def test_migration_refusal_preserves_data_and_guards_control_routes(tmp_path: Path):
    path = tmp_path / "bad-events.sqlite"
    store = afa.SqliteRunStore(path)
    store.close()
    conn = db.connect(path)
    try:
        db.migrate(conn)
        conn.execute(
            "INSERT INTO evaluation_jobs (id, status, cancel_requested, params_json, "
            "total_runs, created_at) VALUES ('keep', 'queued', 0, '{}', 0, datetime('now'))"
        )
        conn.execute(
            "INSERT INTO job_events (job_id, seq, type) VALUES ('keep', 1, 'keep')"
        )
        conn.commit()
        conn.execute("DROP TABLE job_events")
        conn.execute(
            "CREATE TABLE job_events (id INTEGER PRIMARY KEY, job_id TEXT, seq INTEGER, type TEXT)"
        )
        conn.execute(
            "INSERT INTO job_events (id, job_id, seq, type) VALUES (7, 'keep', 1, 'keep')"
        )
        conn.commit()
        with pytest.raises(RuntimeError, match="unsupported existing job_events schema"):
            db.migrate(conn)
        assert conn.execute("SELECT type FROM job_events WHERE id=7").fetchone()[0] == "keep"
    finally:
        conn.close()

    app = create_app()
    app.state.db_path = path
    app.state.auto_dispatch = False
    with TestClient(app) as client:
        assert client.get("/api/v1/jobs").status_code == 503
        # Exact raw forensic reads remain available even while the control
        # plane refuses to list or mutate app state.
        assert client.get("/api/v1/runs/999999").status_code == 404


def test_migration_rejects_trial_identity_without_rewriting_rows(temp_db: Path):
    conn = db.connect(temp_db)
    try:
        created = jobs.create_job(conn, JobCreate(model="identity-shape", tasks=[TASK], repeats=1))
        before = conn.execute(
            "SELECT task_id, idx, task_version, task_digest FROM evaluation_trials "
            "WHERE evaluation_id=?", (created.id,)
        ).fetchone()
        conn.execute("ALTER TABLE evaluation_trials RENAME TO evaluation_trials_old")
        conn.execute(
            "CREATE TABLE evaluation_trials ("
            "evaluation_id TEXT, task_id TEXT, idx INTEGER, task_version TEXT, "
            "task_digest TEXT, trial_state TEXT, evidence_state TEXT, run_id INTEGER, "
            "source_evaluation_id TEXT, source_run_id INTEGER, origin_evaluation_id TEXT, "
            "claim_token TEXT, claimed_at TEXT, completed_at TEXT, error_message TEXT)"
        )
        conn.execute(
            "INSERT INTO evaluation_trials SELECT * FROM evaluation_trials_old"
        )
        conn.execute("DROP TABLE evaluation_trials_old")
        conn.commit()
        with pytest.raises(RuntimeError, match="missing unique"):
            db.migrate(conn)
        after = conn.execute(
            "SELECT task_id, idx, task_version, task_digest FROM evaluation_trials "
            "WHERE evaluation_id=?", (created.id,)
        ).fetchone()
        assert tuple(after) == tuple(before)
    finally:
        conn.close()


def test_resume_rejects_real_task_pack_drift(tmp_path: Path, monkeypatch):
    root = tmp_path / "root"
    task_root = root / "tasks"
    shutil.copytree(Path(db.ROOT) / "tasks" / TASK, task_root / TASK)
    monkeypatch.setattr(db, "ROOT", root)
    monkeypatch.setattr(worker, "TASKS_DIR", task_root)
    path = tmp_path / "drift.sqlite"
    shutil.copy(db.DB_PATH, path)
    conn = db.connect(path)
    try:
        db.migrate(conn)
        created = jobs.create_job(conn, JobCreate(model="drift-real", tasks=[TASK], repeats=1))
        jobs.request_cancel(conn, created.id)
        spec_path = task_root / TASK / "task.json"
        spec = json.loads(spec_path.read_text())
        spec["version"] = "9.9.9"
        spec_path.write_text(json.dumps(spec))
        with pytest.raises(jobs.JobStateError, match="changed"):
            jobs.resume_job(conn, created.id)
        assert jobs.get_job(conn, created.id).status == "canceled"
        assert jobs.get_snapshot(conn, created.id)["tasks"][0]["task_version"] == "1.0.0"
    finally:
        conn.close()


def test_legacy_bad_params_remain_listable_without_secret_echo(temp_db: Path):
    conn = db.connect(temp_db)
    try:
        conn.execute(
            "INSERT INTO evaluation_jobs (id, status, cancel_requested, params_json, "
            "total_runs, created_at) VALUES (?, 'failed', 0, ?, 0, datetime('now'))",
            (
                "legacy-secret",
                json.dumps({
                    "model": "old",
                    "backend": {
                        "kind": "ollama",
                        "base_url": "http://user:password@localhost:11434",
                    },
                }),
            ),
        )
        conn.commit()
        listed = jobs.list_jobs(conn)
        legacy = next(job for job in listed if job.id == "legacy-secret")
        # A malformed row is listable, but its parameters are reported as
        # unverifiable: they are never replaced by JobParams() defaults (which
        # would claim backend=mock, model="mock") and never echo the secret.
        assert legacy.params is None
        assert legacy.params_status == "unverifiable"
        assert legacy.params_error.startswith("invalid persisted evaluation parameters")
        assert "password" not in legacy.model_dump_json()
        assert legacy.backend_kind is None and legacy.evidence_class == "unknown"
    finally:
        conn.close()


def test_reuse_rejection_is_all_or_nothing(temp_db: Path):
    conn = db.connect(temp_db)
    logical_tables = (
        "evaluation_jobs", "evaluation_trials", "job_runs", "runs",
        "run_scores", "diffs", "test_results",
    )

    def logical_rows():
        return {
            table: [tuple(row) for row in conn.execute(
                f"SELECT * FROM {table} ORDER BY rowid"
            ).fetchall()]
            for table in logical_tables
        }

    try:
        missing_before = logical_rows()
        with pytest.raises(jobs.JobStateError, match="unavailable"):
            jobs.create_job(
                conn,
                JobCreate(
                    model="reuse-missing", tasks=[TASK], repeats=1,
                    mode="reuse", source_evaluation_id="does-not-exist",
                ),
            )
        assert logical_rows() == missing_before

        incomplete = jobs.create_job(
            conn, JobCreate(model="reuse-incomplete", tasks=[TASK], repeats=1)
        )
        before_incomplete = logical_rows()
        with pytest.raises(jobs.JobStateError, match="incomplete"):
            jobs.create_job(
                conn,
                JobCreate(
                    model="reuse-incomplete", tasks=[TASK], repeats=1,
                    mode="reuse", source_evaluation_id=incomplete.id,
                ),
            )
        assert logical_rows() == before_incomplete
    finally:
        conn.close()


def test_repeated_populated_migration_preserves_app_facts(temp_db: Path):
    conn = db.connect(temp_db)
    try:
        created = jobs.create_job(conn, JobCreate(model="migration-populated", tasks=[TASK], repeats=1))
        jobs.append_event(conn, created.id, "fixture", {"keep": True})
        jobs.put_settings(conn, {"default_backend": "mock", "extra": {"keep": "yes"}})
        before = {
            "job": tuple(conn.execute(
                "SELECT id, status, params_json, snapshot_json FROM evaluation_jobs WHERE id=?",
                (created.id,),
            ).fetchone()),
            "events": [tuple(row) for row in conn.execute(
                "SELECT job_id, seq, type, payload_json FROM job_events WHERE job_id=?",
                (created.id,),
            )],
            "settings": tuple(conn.execute(
                "SELECT id, settings_json FROM app_settings WHERE id=1"
            ).fetchone()),
        }
        db.migrate(conn)
        db.migrate(conn)
        after = {
            "job": tuple(conn.execute(
                "SELECT id, status, params_json, snapshot_json FROM evaluation_jobs WHERE id=?",
                (created.id,),
            ).fetchone()),
            "events": [tuple(row) for row in conn.execute(
                "SELECT job_id, seq, type, payload_json FROM job_events WHERE job_id=?",
                (created.id,),
            )],
            "settings": tuple(conn.execute(
                "SELECT id, settings_json FROM app_settings WHERE id=1"
            ).fetchone()),
        }
        assert after == before
    finally:
        conn.close()


def _record() -> RunRecord:
    return RunRecord(
        task_id=TASK,
        task_version="1.0.0",
        agent="transaction-test",
        idx=0,
        status=RunStatus.VALID,
        score=RunScore(RunStatus.VALID, 1, 1.0, 1.0, {}, 1.0, True, False),
        files_changed=1,
        lines_added=1,
        lines_removed=0,
        transcript_hash="sha256:transaction-test",
        duration_ms=1,
    )


def test_commit_false_store_seam_does_not_commit_caller_work(temp_db: Path):
    conn = db.connect(temp_db)
    try:
        conn.execute("CREATE TABLE caller_marker (value TEXT)")
        conn.execute("INSERT INTO caller_marker VALUES ('uncommitted')")
        store = afa.SqliteRunStore(connection=conn)
        store.save_run(_record(), commit=False)
        assert conn.in_transaction
        conn.rollback()
        assert conn.execute("SELECT COUNT(*) FROM caller_marker").fetchone()[0] == 0
        assert conn.execute(
            "SELECT COUNT(*) FROM runs WHERE agent='transaction-test'"
        ).fetchone()[0] == 0
    finally:
        conn.close()


def test_default_openai_factory_uses_real_resumed_transport(temp_db: Path, monkeypatch):
    reference = (Path(db.ROOT) / "tasks" / TASK / "reference" / "searchkit" / "search.py").read_text()
    response = f"# FILE: searchkit/search.py\n```python\n{reference}\n```"
    requests: list[tuple[str, dict, float | None]] = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802
            length = int(self.headers["Content-Length"])
            payload = json.loads(self.rfile.read(length))
            requests.append((self.path, payload, None))
            body = json.dumps({"choices": [{"message": {"content": response}}]}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args):
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    import afa_runner.agents_openai as openai_adapter

    original_urlopen = openai_adapter.urllib.request.urlopen

    def recording_urlopen(request, timeout=None):
        result = original_urlopen(request, timeout=timeout)
        requests[-1] = (requests[-1][0], requests[-1][1], timeout)
        return result

    monkeypatch.setattr(openai_adapter.urllib.request, "urlopen", recording_urlopen)
    original_run_once = worker.afa.run_once
    calls = 0

    def interrupt_after_first(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("interrupt before nonzero position")
        return original_run_once(*args, **kwargs)

    try:
        conn = db.connect(temp_db)
        try:
            job = jobs.create_job(
                conn,
                JobCreate(
                    model="transport-model",
                    backend=Backend(
                        kind="openai_compat",
                        base_url=f"http://127.0.0.1:{server.server_port}",
                    ),
                    tasks=[TASK],
                    repeats=2,
                    base_seed=700,
                    temperature=0.23,
                    request_timeout_s=7,
                ),
            )
            assert jobs.claim_job(conn, job.id)
            first_owner = jobs.owner_token(conn, job.id)
            assert first_owner is not None
            monkeypatch.setattr(worker.afa, "run_once", interrupt_after_first)
            worker.run_job(conn, job.id, owner_token=first_owner)
            assert jobs.get_job(conn, job.id).status == "failed"
            assert len(jobs.run_ids_for_job(conn, job.id)) == 1
            assert jobs.resume_job(conn, job.id).status == "queued"
            assert jobs.claim_job(conn, job.id)
            resumed_owner = jobs.owner_token(conn, job.id)
            assert resumed_owner is not None
            monkeypatch.setattr(worker.afa, "run_once", original_run_once)
            worker.run_job(conn, job.id, owner_token=resumed_owner)
            assert jobs.get_job(conn, job.id).status == "succeeded"
        finally:
            conn.close()
    finally:
        server.shutdown()
        server.server_close()
        server_thread.join(5)

    assert [item[0] for item in requests] == ["/v1/chat/completions"] * 2
    assert [item[1]["model"] for item in requests] == ["transport-model"] * 2
    assert [item[1]["seed"] for item in requests] == [700, 701]
    assert [item[1]["temperature"] for item in requests] == [0.23, 0.23]
    assert [item[2] for item in requests] == [7, 7]
