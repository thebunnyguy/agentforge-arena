"""JOBS backend tests (Phases 4-6, 9).

These run against a TEMP copy of the live reports/runs.sqlite so they never
mutate the benchmark DB. A deterministic offline mock agent factory is injected
on app.state, so no Ollama / network is touched. The mock overlays each task's
reference files, yielding a passing run (status=valid, S=1.0, X=True).
"""

from __future__ import annotations

import shutil

import pytest
from fastapi.testclient import TestClient

import afa_runner as afa
from afa_api import db, jobs, worker
from afa_api.main import create_app
from afa_api.schemas import Backend, JobCreate


@pytest.fixture()
def tmp_db(tmp_path):
    src = db.DB_PATH
    dst = tmp_path / "runs.sqlite"
    shutil.copy(src, dst)
    return dst


@pytest.fixture()
def client(tmp_db):
    app = create_app()
    app.state.db_path = tmp_db
    # Inject deterministic offline mock factory; runs use it via the worker.
    app.state.agent_factory = worker.mock_agent_factory
    with TestClient(app) as c:
        yield c


# --------------------------------------------------------------------------- #
# Phase 4: create / list / get / cancel / retry / settings
# --------------------------------------------------------------------------- #

def test_create_and_get_job(client):
    body = {"model": "mock", "backend": {"kind": "mock"},
            "tasks": ["fix-binary-search"], "repeats": 2}
    job = client.post("/api/v1/jobs", json=body).json()
    assert job["status"] in ("queued", "running", "succeeded")
    assert job["counters"]["total_runs"] == 2
    got = client.get(f"/api/v1/jobs/{job['id']}").json()
    assert got["id"] == job["id"]


def test_list_jobs(client):
    client.post("/api/v1/jobs", json={"model": "mock",
                "tasks": ["fix-binary-search"], "repeats": 1})
    listing = client.get("/api/v1/jobs").json()
    assert "jobs" in listing
    assert len(listing["jobs"]) >= 1


def test_cancel_queued_job(client, tmp_db):
    # Disable auto-dispatch so the job stays queued.
    client.app.state.auto_dispatch = False
    job = client.post("/api/v1/jobs", json={"model": "mock",
                      "tasks": ["fix-binary-search"], "repeats": 1}).json()
    canceled = client.post(f"/api/v1/jobs/{job['id']}/cancel").json()
    assert canceled["status"] == "canceled"
    assert canceled["cancel_requested"] is True
    client.app.state.auto_dispatch = True


def test_retry_terminal_job_creates_new_job(client, tmp_db):
    conn = db.connect(tmp_db)
    try:
        src = jobs.create_job(conn, JobCreate(model="mock",
                              tasks=["fix-binary-search"], repeats=1))
        jobs.claim_job(conn, src.id)
        jobs.mark_terminal(conn, src.id, "succeeded")
    finally:
        conn.close()
    new = client.post(f"/api/v1/jobs/{src.id}/retry").json()
    assert new["id"] != src.id
    assert new["status"] in ("queued", "running", "succeeded")
    assert new["params"]["tasks"] == ["fix-binary-search"]


def test_settings_redacts_secret_fields(client):
    body = {"ollama_base_url": "http://localhost:11434",
            "extra": {"api_key": "supersecret", "note": "keep"}}
    put = client.put("/api/v1/settings", json=body).json()
    assert put["extra"]["api_key"] == "***"
    assert put["extra"]["note"] == "keep"
    got = client.get("/api/v1/settings").json()
    assert got["extra"]["api_key"] == "***"


def test_backend_verify_mock(client):
    resp = client.post("/api/v1/backends/verify",
                       json={"kind": "mock"}).json()
    assert resp["ok"] is True
    assert resp["kind"] == "mock"


# --------------------------------------------------------------------------- #
# Phase 5: worker end-to-end (mock, no Ollama)
# --------------------------------------------------------------------------- #

def test_worker_runs_mock_job_end_to_end(tmp_db):
    conn = db.connect(tmp_db)
    try:
        before = conn.execute("SELECT COUNT(*) AS c FROM runs").fetchone()["c"]
        job = jobs.create_job(conn, JobCreate(model="mock-e2e",
                              tasks=["fix-binary-search"], repeats=1))
        assert jobs.claim_job(conn, job.id)
        worker.run_job(conn, job.id, agent_factory=worker.mock_agent_factory)
        done = jobs.get_job(conn, job.id)
        assert done.status == "succeeded"
        assert done.counters.completed_runs == 1
        assert done.counters.passed_runs == 1
        # run linked + raw run row written into the SAME temp db
        run_ids = jobs.run_ids_for_job(conn, job.id)
        assert len(run_ids) == 1
        after = conn.execute("SELECT COUNT(*) AS c FROM runs").fetchone()["c"]
        assert after == before + 1
        row = conn.execute("SELECT job_id, status FROM runs WHERE id=?",
                           (run_ids[0],)).fetchone()
        assert row["job_id"] == job.id
        assert row["status"] == "valid"
        # event tape
        types = [e.type for e in jobs.events_since(conn, job.id, 0)]
        assert "job_started" in types
        assert "run_persisted" in types
        assert "progress" in types
        assert "job_done" in types
    finally:
        conn.close()


def test_cancel_between_runs(tmp_db):
    conn = db.connect(tmp_db)
    try:
        job = jobs.create_job(conn, JobCreate(model="mock-cancel",
                              tasks=["fix-binary-search"], repeats=3))
        assert jobs.claim_job(conn, job.id)
        # Request cancel before the worker starts; honored before the first run.
        jobs.request_cancel(conn, job.id)
        worker.run_job(conn, job.id, agent_factory=worker.mock_agent_factory)
        done = jobs.get_job(conn, job.id)
        assert done.status == "canceled"
        assert done.counters.completed_runs == 0
    finally:
        conn.close()


# --------------------------------------------------------------------------- #
# Phase 6: events poll fallback + SSE
# --------------------------------------------------------------------------- #

def test_poll_fallback_returns_events_since_seq(client):
    job = client.post("/api/v1/jobs", json={"model": "mock",
                      "tasks": ["fix-binary-search"], "repeats": 1}).json()
    # Wait for the background worker to finish (it dispatched on create).
    _wait_terminal(client, job["id"])
    all_events = client.get(f"/api/v1/jobs/{job['id']}/events?since=0").json()
    assert all_events["job_id"] == job["id"]
    assert len(all_events["events"]) >= 1
    first_seq = all_events["events"][0]["seq"]
    after = client.get(
        f"/api/v1/jobs/{job['id']}/events?since={first_seq}"
    ).json()
    assert all(e["seq"] > first_seq for e in after["events"])


def test_sse_stream_replays_and_closes(client):
    job = client.post("/api/v1/jobs", json={"model": "mock",
                      "tasks": ["fix-binary-search"], "repeats": 1}).json()
    _wait_terminal(client, job["id"])
    # Stream from the start; terminal job should replay all + close.
    with client.stream("GET", f"/api/v1/jobs/{job['id']}/events") as resp:
        assert resp.status_code == 200
        body = ""
        for chunk in resp.iter_text():
            body += chunk
            if "event: close" in body:
                break
    assert "event: job_started" in body
    assert "event: job_done" in body
    assert "event: close" in body


def test_sse_resumes_after_last_event_id(client):
    job = client.post("/api/v1/jobs", json={"model": "mock",
                      "tasks": ["fix-binary-search"], "repeats": 1}).json()
    _wait_terminal(client, job["id"])
    events = client.get(f"/api/v1/jobs/{job['id']}/events?since=0").json()["events"]
    resume_from = events[0]["seq"]
    with client.stream(
        "GET", f"/api/v1/jobs/{job['id']}/events",
        headers={"Last-Event-ID": str(resume_from)},
    ) as resp:
        body = ""
        for chunk in resp.iter_text():
            body += chunk
            if "event: close" in body:
                break
    # The first event (seq == resume_from) must NOT be replayed.
    assert f"id: {resume_from}\n" not in body
    assert f"id: {resume_from + 1}\n" in body


# --------------------------------------------------------------------------- #
# Phase 9: regenerate + export
# --------------------------------------------------------------------------- #

def test_regenerate_report(client, tmp_path, monkeypatch):
    # Point report_combined OUTPUT at a temp file so we don't touch repo reports.
    out = tmp_path / "leaderboard.html"
    import report_combined
    monkeypatch.setattr(report_combined, "OUTPUT", out, raising=False)
    resp = client.post("/api/v1/reports/regenerate").json()
    assert resp["ok"] is True
    assert out.exists()


def test_export_json(client):
    exp = client.get("/api/v1/export").json()
    assert exp["format"] == "json"
    assert len(exp["leaderboard"]) >= 1


# --------------------------------------------------------------------------- #

def _wait_terminal(client, job_id, tries: int = 200):
    import time
    for _ in range(tries):
        job = client.get(f"/api/v1/jobs/{job_id}").json()
        if job["status"] in ("succeeded", "failed", "canceled"):
            return job
        time.sleep(0.05)
    raise AssertionError(f"job {job_id} did not reach a terminal state")
