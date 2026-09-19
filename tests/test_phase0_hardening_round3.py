"""Round-3 hardening regressions: recovery bookkeeping isolation, undecodable / deeply
nested / non-finite persisted state, settings poisoning, the unreadable-job placeholder
vs the worker, dispatch failures, event-seq collisions, reuse from unverifiable sources
and the SPA fallback route's containment.

Every database is a copy in tmp_path; a module guard asserts reports/runs.sqlite is
byte-identical afterwards.
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import shutil
import sqlite3
import threading
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from afa_api import db, jobs, projection, startup, worker
from afa_api.main import create_app
from afa_api.schemas import Backend, JobCreate

TASK = "fix-binary-search"


@pytest.fixture(scope="module", autouse=True)
def _evidence_db_is_byte_identical():
    before = hashlib.sha256(db.EVIDENCE_DB_PATH.read_bytes()).hexdigest()
    yield
    assert hashlib.sha256(db.EVIDENCE_DB_PATH.read_bytes()).hexdigest() == before


@pytest.fixture()
def evcopy(tmp_path) -> Path:
    path = tmp_path / "work.sqlite"
    shutil.copy(db.EVIDENCE_DB_PATH, path)
    with contextlib.closing(db.connect(path)) as conn:
        db.migrate(conn)
    return path


@contextlib.contextmanager
def _client(path: Path, *, factory=None):
    app = create_app()
    app.state.db_path, app.state.auto_dispatch = path, False
    if factory is not None:
        app.state.agent_factory = factory
    with TestClient(app, raise_server_exceptions=False) as client:
        client.app_ = app
        yield client


def _q(path: Path, sql: str, args=()) -> list[tuple]:
    with contextlib.closing(db.connect_readonly(path)) as conn:
        return [tuple(r) for r in conn.execute(sql, args).fetchall()]


def _x(path: Path, sql: str, args=()) -> None:
    with contextlib.closing(sqlite3.connect(str(path))) as conn:
        conn.execute(sql, args)
        conn.commit()


def _make_job(path: Path, *, model="r3-model", kind="ollama", repeats=2, status="queued", tasks=(TASK,)) -> str:
    backend = Backend(kind="ollama", base_url="http://localhost:11434") if kind == "ollama" else Backend(kind=kind)
    with contextlib.closing(db.connect(path)) as conn:
        job = jobs.create_job(conn, JobCreate(model=model, backend=backend, tasks=list(tasks), repeats=repeats,
                                              base_seed=7, temperature=0.3, request_timeout_s=30))
        if status == "running":
            assert jobs.claim_job_token(conn, job.id, "dead-owner") == "dead-owner"
        return job.id


class SpyFactory:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def __call__(self, model, task, params):
        self.calls.append((model, task.id))
        return worker.mock_agent_factory(model, task, params)


# --------------------------------------------------------------------------- #
# 1. Recovery bookkeeping is isolated too: requeued ids are never lost
# --------------------------------------------------------------------------- #


def test_a_failing_event_log_never_loses_the_requeued_jobs(evcopy, monkeypatch):
    first = _make_job(evcopy, model="ev-first", status="running")
    poisoned = _make_job(evcopy, model="ev-poisoned", status="running")
    # a corrupt event row: MAX(seq) is text, so append_event's int() raises after the requeue committed
    _x(evcopy, "INSERT INTO job_events (job_id, seq, ts, type, payload_json) VALUES (?, 'zzz', 'now', 'x', NULL)", (poisoned,))
    with contextlib.closing(db.connect(evcopy)) as conn:
        with pytest.raises(jobs.RecoveryIncomplete) as caught:
            jobs.reclaim_stale_running(conn, recover_unlocked=True)
    assert sorted(caught.value.recovered) == sorted([first, poisoned])  # both committed as queued
    assert "zzz" not in str(caught.value)  # row content is never echoed
    statuses = dict(_q(evcopy, "SELECT id, status FROM evaluation_jobs"))
    assert statuses[first] == statuses[poisoned] == "queued"

    dispatched: list[str] = []
    monkeypatch.setattr(worker, "dispatch_job", lambda db_path, job_id, **kw: dispatched.append(job_id))
    _x(evcopy, "UPDATE evaluation_jobs SET status='running', owner_token='dead-owner' WHERE id IN (?, ?)", (first, poisoned))
    app = create_app()
    app.state.db_path = evcopy
    startup.recover_stale_jobs(app)
    assert sorted(dispatched) == sorted([first, poisoned])  # dispatched despite the bookkeeping failure
    assert app.state.recovery_error and "zzz" not in app.state.recovery_error


def test_worker_serve_startup_survives_incomplete_recovery(evcopy, monkeypatch):
    _make_job(evcopy, model="serve-orphan", status="running")

    def broken(conn, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(jobs, "reclaim_stale_running", broken)

    class Stop(BaseException):
        pass

    def stop_after_start(conn, **kwargs):
        raise Stop()

    monkeypatch.setattr(worker, "claim_and_run", stop_after_start)
    with pytest.raises(Stop):  # reached the polling loop instead of dying at startup
        worker.serve(poll_interval=0, db_path=evcopy)


# --------------------------------------------------------------------------- #
# 2. Undecodable, deeply nested and non-finite persisted state
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("column", ["params_json", "snapshot_json", "error_message", "created_at", "owner_token"])
def test_undecodable_text_in_one_job_row_takes_nothing_else_down(evcopy, column):
    good = _make_job(evcopy, model="utf-good")
    orphan = _make_job(evcopy, model="utf-orphan", status="running")
    bad = _make_job(evcopy, model="utf-bad", status="running")
    _x(evcopy, f"UPDATE evaluation_jobs SET {column}=CAST(x'80ff' AS TEXT) WHERE id=?", (bad,))
    with _client(evcopy) as client:
        for path in (f"/api/v1/jobs", f"/api/v1/jobs/{bad}", f"/api/v1/jobs/{bad}/report.json",
                     f"/api/v1/jobs/{bad}/events?since=0", "/api/v1/overview", "/api/v1/healthz"):
            assert client.get(path).status_code == 200, path
        rows = {j["id"]: j for j in client.get("/api/v1/jobs").json()["jobs"]}
        assert rows[good]["params_status"] == "available"
        assert client.get("/api/v1/healthz").json()["status"] == "ok"
    # startup recovery was not aborted by the bad row: the healthy orphan was recovered
    assert dict(_q(evcopy, "SELECT id, status FROM evaluation_jobs"))[orphan] == "queued"


@pytest.mark.parametrize("depth", [200, 985, 3000])
def test_a_snapshot_parseable_but_too_deep_never_reaches_the_encoder(evcopy, depth):
    good, bad = _make_job(evcopy, model="deep-good"), _make_job(evcopy, model="deep-bad")
    snap = json.loads(_q(evcopy, "SELECT snapshot_json FROM evaluation_jobs WHERE id=?", (bad,))[0][0])
    junk: object = {}
    for _ in range(depth):
        junk = {"n": junk}
    snap["junk"] = junk
    _x(evcopy, "UPDATE evaluation_jobs SET snapshot_json=? WHERE id=?", (json.dumps(snap), bad))
    with _client(evcopy) as client:
        listing = client.get("/api/v1/jobs")
        assert listing.status_code == 200
        rows = {j["id"]: j for j in listing.json()["jobs"]}
        assert rows[good]["params_status"] == "available"
        assert rows[bad]["params_status"] == "unverifiable"
        for path in (f"/api/v1/jobs/{bad}", f"/api/v1/jobs/{bad}/trials", f"/api/v1/jobs/{bad}/results"):
            assert client.get(path).status_code == 200, path
        assert client.post(f"/api/v1/jobs/{bad}/cancel").status_code in (200, 409)


@pytest.mark.parametrize("payload", ["[1,2]", "5", '"str"', "true", "NaN", "1e999", "{"])
def test_event_rows_with_odd_payloads_render_without_a_500(evcopy, payload):
    job = _make_job(evcopy)
    _x(evcopy, "INSERT INTO job_events (job_id, seq, ts, type, payload_json) VALUES (?, 90, 'now', 'x', ?)", (job, payload))
    with _client(evcopy) as client:
        response = client.get(f"/api/v1/jobs/{job}/events?since=0")
        assert response.status_code == 200
        assert "NaN" not in response.text and "Infinity" not in response.text


def test_event_rows_with_a_text_seq_or_control_characters_render(evcopy):
    job = _make_job(evcopy)
    _x(evcopy, "INSERT INTO job_events (job_id, seq, ts, type, payload_json) VALUES (?, 'abc', 'now', 'x', NULL)", (job,))
    _x(evcopy, "INSERT INTO job_events (job_id, seq, ts, type, payload_json) VALUES (?, 91, 'now', 'a' || char(10) || 'event: forged', NULL)", (job,))
    with _client(evcopy) as client:
        response = client.get(f"/api/v1/jobs/{job}/events?since=0")
        assert response.status_code == 200
        assert all("\n" not in event["type"] for event in response.json()["events"])


def test_sse_last_event_id_is_bounded_like_since(evcopy):
    job = _make_job(evcopy)
    with contextlib.closing(db.connect(evcopy)) as conn:
        jobs.mark_terminal(conn, job, "failed", error_message="done")
    with _client(evcopy) as client:
        response = client.get(f"/api/v1/jobs/{job}/events", headers={"Last-Event-ID": "99999999999999999999"})
        assert response.status_code == 200


def test_junk_items_in_snapshot_tasks_are_unverifiable_and_recovery_fails_closed(evcopy):
    orphan = _make_job(evcopy, model="junk-tasks", status="running")
    snap = json.loads(_q(evcopy, "SELECT snapshot_json FROM evaluation_jobs WHERE id=?", (orphan,))[0][0])
    snap["tasks"] = [snap["tasks"][0], 7, None]
    _x(evcopy, "UPDATE evaluation_jobs SET snapshot_json=? WHERE id=?", (json.dumps(snap), orphan))
    with contextlib.closing(db.connect(evcopy)) as conn:
        with pytest.raises(jobs.InvalidPersistedParams):
            jobs.execution_params(conn, orphan)
        assert jobs.reclaim_stale_running(conn, recover_unlocked=True) == []
    assert dict(_q(evcopy, "SELECT id, status FROM evaluation_jobs"))[orphan] == "failed"


# --------------------------------------------------------------------------- #
# 3. Settings can no longer be poisoned
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("body", [
    '{"default_temperature": NaN}', '{"default_temperature": 1e999}', '{"extra": {"a": NaN}}',
    '{"extra": {"a": -Infinity}}', '{"extra": {"a": "\\ud800"}}',
    '{"extra": ' + '{"n":' * 40 + "1" + "}" * 40 + "}", '{"default_request_timeout_s": 999999999}',
])
def test_settings_that_cannot_be_rendered_again_are_refused_up_front(evcopy, body):
    with _client(evcopy) as client:
        before = client.get("/api/v1/settings").json()
        put = client.put("/api/v1/settings", content=body, headers={"content-type": "application/json"})
        assert put.status_code == 422, put.text
        assert client.get("/api/v1/settings").json() == before  # nothing was persisted


def test_an_already_poisoned_settings_blob_no_longer_takes_get_settings_down(evcopy):
    _x(evcopy, "UPDATE app_settings SET settings_json='{\"default_temperature\": NaN}' WHERE id=1")
    with _client(evcopy) as client:
        response = client.get("/api/v1/settings")
        assert response.status_code == 200 and "NaN" not in response.text
        assert client.put("/api/v1/settings", json={"default_temperature": 0.5}).status_code == 200
        assert client.get("/api/v1/settings").json()["default_temperature"] == 0.5


# --------------------------------------------------------------------------- #
# 4. Worker / dispatch consistency
# --------------------------------------------------------------------------- #


def test_an_unreadable_queued_row_is_failed_not_abandoned_as_a_phantom_running_row(evcopy):
    job = _make_job(evcopy, model="unreadable-queued")
    _x(evcopy, "UPDATE evaluation_jobs SET total_runs='many' WHERE id=?", (job,))
    spy = SpyFactory()
    with contextlib.closing(db.connect(evcopy)) as conn:
        assert worker.claim_and_run(conn, agent_factory=spy) == job
    status, message, owner = _q(evcopy, "SELECT status, error_message, owner_token FROM evaluation_jobs WHERE id=?", (job,))[0]
    assert status == "failed" and message == jobs.UNREADABLE_JOB_MESSAGE and owner is None
    assert spy.calls == [] and _q(evcopy, "SELECT COUNT(*) FROM runs WHERE job_id=?", (job,)) == [(0,)]


def test_a_dispatch_failure_before_a_claim_is_not_swallowed(evcopy, monkeypatch):
    job = _make_job(evcopy, model="dispatch-preclaim")
    seen: list[BaseException] = []
    monkeypatch.setattr(threading, "excepthook", lambda args: seen.append(args.exc_value))

    def locked(conn):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(worker.db, "migrate", locked)
    worker.dispatch_job(evcopy, job).join(timeout=30)
    assert seen and isinstance(seen[0], sqlite3.OperationalError)  # surfaced, not silently dropped
    assert _q(evcopy, "SELECT status FROM evaluation_jobs WHERE id=?", (job,)) == [("queued",)]


def test_concurrent_event_appends_get_unique_sequence_numbers(evcopy):
    job = _make_job(evcopy)
    errors: list[BaseException] = []

    def hammer():
        try:
            with contextlib.closing(db.connect(evcopy)) as conn:
                for _ in range(15):
                    jobs.append_event(conn, job, "tick", {"n": 1})
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=hammer) for _ in range(6)]
    [t.start() for t in threads]
    [t.join(timeout=120) for t in threads]
    assert errors == []
    seqs = [r[0] for r in _q(evcopy, "SELECT seq FROM job_events WHERE job_id=? AND type='tick' ORDER BY seq", (job,))]
    assert len(seqs) == len(set(seqs)) == 90


def test_the_retry_never_queues_behind_a_running_attempt(evcopy, monkeypatch):
    app = create_app()
    app.state.db_path = evcopy
    app.state.migrate_error = "locked"
    calls: list[int] = []
    monkeypatch.setattr(startup, "migrate_control_plane", lambda a: calls.append(1) or False)
    monkeypatch.setattr(projection, "time", type("T", (), {"monotonic": staticmethod(lambda: 1000.0)}))
    assert projection._migration_retry_lock.acquire(blocking=False)
    try:
        projection.retry_migration_if_failed(app)  # another attempt holds the lock: return at once
    finally:
        projection._migration_retry_lock.release()
    assert calls == []
    projection.retry_migration_if_failed(app)
    assert calls == [1]


# --------------------------------------------------------------------------- #
# 5. Creation / reuse
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("task", ["a" * 256, "a" * 5000, "é" * 200])
def test_an_unstatable_task_id_is_a_client_error_not_a_500(evcopy, task):
    with _client(evcopy) as client:
        response = client.post("/api/v1/jobs", json={"model": "m", "backend": {"kind": "mock"}, "tasks": [task], "repeats": 1})
        assert response.status_code in (409, 422), response.text
    assert _q(evcopy, "SELECT COUNT(*) FROM evaluation_jobs") == [(0,)]


@pytest.mark.parametrize("over", [{"request_timeout_s": 10**30}, {"request_timeout_s": 86_401}, {"base_seed": 10**30}])
def test_absurd_timeouts_and_seeds_are_refused_up_front(evcopy, over):
    with _client(evcopy) as client:
        body = {"model": "m", "backend": {"kind": "mock"}, "tasks": [TASK], "repeats": 1, **over}
        assert client.post("/api/v1/jobs", json=body).status_code == 422


def test_reuse_from_a_source_whose_parameters_do_not_verify_is_refused(evcopy):
    with contextlib.closing(db.connect(evcopy)) as conn:
        source = jobs.create_job(conn, JobCreate(model="reuse-src", backend=Backend(kind="mock"), tasks=[TASK], repeats=1))
        worker.claim_and_run(conn, agent_factory=worker.mock_agent_factory)
        assert jobs.get_job(conn, source.id).status == "succeeded"
    body = {"model": "reuse-src", "backend": {"kind": "mock"}, "tasks": [TASK], "repeats": 1,
            "mode": "reuse", "source_evaluation_id": source.id}
    with _client(evcopy) as client:
        assert client.post("/api/v1/jobs", json=body).status_code == 200  # a verifiable source may be reused
        params = json.loads(_q(evcopy, "SELECT params_json FROM evaluation_jobs WHERE id=?", (source.id,))[0][0])
        params["model"] = "tampered"
        _x(evcopy, "UPDATE evaluation_jobs SET params_json=? WHERE id=?", (json.dumps(params), source.id))
        refused = client.post("/api/v1/jobs", json=body)
        assert refused.status_code == 409 and "unverifiable" in refused.text


# --------------------------------------------------------------------------- #
# 6. Raw stored values that JSON cannot represent name the run
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("column,value", [("final_score", "9e999"), ("t_hidden", "9e999"), ("q", "-9e999")])
def test_infinite_stored_scores_fail_closed_and_name_the_run(evcopy, column, value):
    rid = _q(evcopy, "SELECT id FROM runs ORDER BY id LIMIT 1")[0][0]
    _x(evcopy, f"UPDATE run_scores SET {column}={value} WHERE run_id=?", (rid,))
    with _client(evcopy) as client:
        overview = client.get("/api/v1/overview")
        assert overview.status_code == 503 and f"run {rid} " in overview.json()["error"]
        exact = client.get(f"/api/v1/runs/{rid}")
        assert exact.status_code == 503  # a clear 503, not an encoder crash


def test_integers_beyond_the_sqlite_range_fail_closed_and_name_the_run(evcopy):
    rid = _q(evcopy, "SELECT id FROM runs ORDER BY id LIMIT 1")[0][0]
    _x(evcopy, "UPDATE runs SET duration_ms=1e30 WHERE id=?", (rid,))
    with _client(evcopy) as client:
        overview = client.get("/api/v1/overview")
        assert overview.status_code == 503 and f"run {rid} " in overview.json()["error"]


# --------------------------------------------------------------------------- #
# 7. The SPA fallback route cannot leave the built directory
# --------------------------------------------------------------------------- #


def test_spa_fallback_never_serves_files_outside_dist(tmp_path, monkeypatch):
    dist = tmp_path / "site" / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<html>SPA</html>")
    (dist / "app.txt").write_text("inside")
    (tmp_path / "site" / "secret.txt").write_text("TOP-SECRET-OUTSIDE-DIST")
    monkeypatch.setenv("AFA_SERVE_WEB", "1")
    monkeypatch.setenv("AFA_WEB_DIST", str(dist))
    with TestClient(create_app(), raise_server_exceptions=False) as client:
        assert client.get("/app.txt").text == "inside"
        for path in ("/%2e%2e/secret.txt", "/..%2fsecret.txt", "/%2e%2e%2fsecret.txt", "/assets/../../secret.txt"):
            response = client.get(path)
            assert "TOP-SECRET" not in response.text, path
