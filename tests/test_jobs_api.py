"""FULL job-lifecycle suite, driven OFFLINE with a deterministic mock agent.

No Ollama, no network: the worker's agent factory is the deterministic
``MockAgent`` that overlays each task's ``reference/`` files, yielding a passing
run (status=valid, S=1.0, X=True) using ONLY the frozen pipeline (run_once /
grade / score_run). Every test runs against a TEMP COPY of the live
reports/runs.sqlite, so the benchmark DB is never mutated.

What this proves end-to-end:

  * POST /jobs creates a queued job with a precomputed total = tasks x repeats;
  * the worker, over a tiny (tasks x repeats) set, persists each run into the
    SAME db with the raw row's ``job_id`` stamped and a job_runs link appended;
  * the job reaches a TERMINAL state (succeeded);
  * job_events are present with a strictly monotonic, gap-free per-job ``seq``;
  * the events stream replays from an arbitrary cursor with NO gaps and NO
    duplication — via both the JSON ``?since=`` poll fallback and the SSE
    ``Last-Event-ID`` resume;
  * cancel works (queued -> canceled immediately; running -> honored between
    runs with completed_runs frozen at the cancel point).
"""

from __future__ import annotations

import shutil
import time

import pytest
from fastapi.testclient import TestClient

import afa_runner as afa
from afa_api import db, jobs, worker
from afa_api.main import create_app
from afa_api.schemas import JobCreate

TASK = "fix-binary-search"  # captured anchor task; mock overlays its reference/
TERMINAL = {"succeeded", "failed", "canceled"}


# --------------------------------------------------------------------------- #
# Fixtures: a temp DB copy + an app wired to the deterministic offline factory.
# --------------------------------------------------------------------------- #

@pytest.fixture()
def tmp_db(tmp_path):
    dst = tmp_path / "runs.sqlite"
    shutil.copy(db.DB_PATH, dst)
    # Apply the additive app-table migration to the copy so direct-call tests
    # (which don't go through the app lifespan) have the full control-plane
    # schema, independent of the committed evidence DB's incidental state.
    conn = db.connect(dst)
    try:
        db.migrate(conn)
    finally:
        conn.close()
    return dst


@pytest.fixture()
def client(tmp_db):
    app = create_app()
    app.state.db_path = tmp_db
    # Inject the deterministic, offline, PASSING mock factory (no Ollama).
    app.state.agent_factory = worker.mock_agent_factory
    with TestClient(app) as c:
        yield c


def _wait_terminal(client, job_id, tries: int = 400):
    """Poll the job until it reaches a terminal state (background worker thread)."""
    for _ in range(tries):
        job = client.get(f"/api/v1/jobs/{job_id}").json()
        if job["status"] in TERMINAL:
            return job
        time.sleep(0.02)
    raise AssertionError(f"job {job_id} never reached a terminal state")


def _assert_monotonic_gapfree(events) -> None:
    """seq must be 1,2,3,... with no gaps and no repeats (per-job ordering)."""
    seqs = [e["seq"] for e in events]
    assert seqs == sorted(seqs), f"events out of order: {seqs}"
    assert len(seqs) == len(set(seqs)), f"duplicate seq: {seqs}"
    assert seqs == list(range(seqs[0], seqs[0] + len(seqs))), f"gap in seq: {seqs}"


# --------------------------------------------------------------------------- #
# Full lifecycle: POST /jobs -> worker over tiny tasks x repeats -> persisted.
# --------------------------------------------------------------------------- #

def test_full_job_lifecycle_offline(client, tmp_db):
    """POST /jobs, let the injected mock worker run a tiny 1x2 set, and assert
    every persisted run carries the job_id, the job is succeeded, and counters
    add up."""
    conn = db.connect(tmp_db)
    try:
        before = conn.execute("SELECT COUNT(*) AS c FROM runs").fetchone()["c"]
    finally:
        conn.close()

    body = {"model": "mock-lifecycle", "backend": {"kind": "mock"},
            "tasks": [TASK], "repeats": 2}
    created = client.post("/api/v1/jobs", json=body).json()
    job_id = created["id"]
    assert created["counters"]["total_runs"] == 2  # 1 task x 2 repeats

    done = _wait_terminal(client, job_id)
    assert done["status"] == "succeeded"
    assert done["counters"]["completed_runs"] == 2
    assert done["counters"]["passed_runs"] == 2     # mock overlay passes
    assert done["counters"]["failed_runs"] == 0
    assert done["counters"]["voided_runs"] == 0
    assert done["started_at"] is not None
    assert done["finished_at"] is not None

    # Runs persisted into the SAME temp DB, each stamped with this job_id.
    conn = db.connect(tmp_db)
    try:
        after = conn.execute("SELECT COUNT(*) AS c FROM runs").fetchone()["c"]
        assert after == before + 2
        run_ids = jobs.run_ids_for_job(conn, job_id)
        assert len(run_ids) == 2
        rows = conn.execute(
            "SELECT id, job_id, agent, status FROM runs WHERE job_id=? "
            "ORDER BY id", (job_id,),
        ).fetchall()
        assert len(rows) == 2
        for r in rows:
            assert r["job_id"] == job_id
            assert r["agent"] == "mock-lifecycle"
            assert r["status"] == "valid"
        assert {r["id"] for r in rows} == set(run_ids)
    finally:
        conn.close()


def test_persisted_run_is_a_real_pipeline_run(client, tmp_db):
    """Sanity that the offline mock actually exercised the frozen pipeline:
    the persisted run reconstructs as a valid, passing RunRecord via the store
    (no special-casing in the worker)."""
    body = {"model": "mock-verify", "tasks": [TASK], "repeats": 1}
    job_id = client.post("/api/v1/jobs", json=body).json()["id"]
    _wait_terminal(client, job_id)

    store = afa.SqliteRunStore(str(tmp_db))
    try:
        recs = store.load_runs(agent="mock-verify", task_id=TASK)
    finally:
        store.close()
    assert len(recs) == 1
    rec = recs[0]
    assert rec.status.value == "valid"
    assert rec.score.final_score == 1.0
    assert rec.score.functional_pass is True


# --------------------------------------------------------------------------- #
# job_events: present, monotonic, gap-free; full expected tape.
# --------------------------------------------------------------------------- #

def test_job_events_present_and_monotonic(client, tmp_db):
    body = {"model": "mock-events", "tasks": [TASK], "repeats": 2}
    job_id = client.post("/api/v1/jobs", json=body).json()["id"]
    _wait_terminal(client, job_id)

    events = client.get(f"/api/v1/jobs/{job_id}/events?since=0").json()["events"]
    assert len(events) >= 1
    _assert_monotonic_gapfree(events)
    assert events[0]["seq"] == 1  # per-job seq starts at 1

    types = [e["type"] for e in events]
    # Lifecycle markers must all be on the tape.
    assert types[0] == "job_started"
    for expected in ("run_started", "run_persisted", "progress", "job_done"):
        assert expected in types, f"missing event type: {expected}"
    # Exactly one persisted run per (task x repeat) unit.
    assert types.count("run_persisted") == 2


# --------------------------------------------------------------------------- #
# Gap-free replay from an arbitrary cursor: JSON poll + SSE resume.
# --------------------------------------------------------------------------- #

def test_poll_replay_from_cursor_is_gapfree(client, tmp_db):
    body = {"model": "mock-poll", "tasks": [TASK], "repeats": 2}
    job_id = client.post("/api/v1/jobs", json=body).json()["id"]
    _wait_terminal(client, job_id)

    full = client.get(f"/api/v1/jobs/{job_id}/events?since=0").json()["events"]
    assert len(full) >= 4
    _assert_monotonic_gapfree(full)

    # Resume from a mid-stream cursor; the replay must be the exact suffix with
    # no gaps and no overlap (no event with seq <= cursor).
    cursor = full[len(full) // 2]["seq"]
    tail = client.get(f"/api/v1/jobs/{job_id}/events?since={cursor}").json()["events"]
    assert tail, "expected a non-empty tail after the cursor"
    assert all(e["seq"] > cursor for e in tail)
    _assert_monotonic_gapfree(tail)
    # Concatenation of [<=cursor] + [>cursor] reproduces the full tape exactly.
    head = [e for e in full if e["seq"] <= cursor]
    assert [e["seq"] for e in head + tail] == [e["seq"] for e in full]

    # A cursor at the end yields nothing more.
    last = full[-1]["seq"]
    assert client.get(
        f"/api/v1/jobs/{job_id}/events?since={last}"
    ).json()["events"] == []


def test_sse_stream_replays_all_and_closes(client, tmp_db):
    body = {"model": "mock-sse", "tasks": [TASK], "repeats": 1}
    job_id = client.post("/api/v1/jobs", json=body).json()["id"]
    _wait_terminal(client, job_id)

    with client.stream("GET", f"/api/v1/jobs/{job_id}/events") as resp:
        assert resp.status_code == 200
        body_text = ""
        for chunk in resp.iter_text():
            body_text += chunk
            if "event: close" in body_text:
                break
    assert "event: job_started" in body_text
    assert "event: job_done" in body_text
    assert "event: close" in body_text
    # The SSE ids are the same monotonic seqs (id: 1 must be the first).
    assert "id: 1\n" in body_text


def test_sse_resume_from_last_event_id_is_gapfree(client, tmp_db):
    body = {"model": "mock-resume", "tasks": [TASK], "repeats": 2}
    job_id = client.post("/api/v1/jobs", json=body).json()["id"]
    _wait_terminal(client, job_id)

    events = client.get(f"/api/v1/jobs/{job_id}/events?since=0").json()["events"]
    resume_from = events[len(events) // 2]["seq"]

    with client.stream(
        "GET", f"/api/v1/jobs/{job_id}/events",
        headers={"Last-Event-ID": str(resume_from)},
    ) as resp:
        assert resp.status_code == 200
        body_text = ""
        for chunk in resp.iter_text():
            body_text += chunk
            if "event: close" in body_text:
                break

    # Nothing at/below the cursor is replayed; the very next seq IS present;
    # and the final seq is present too (gap-free suffix).
    assert f"id: {resume_from}\n" not in body_text
    assert f"id: {resume_from + 1}\n" in body_text
    assert f"id: {events[-1]['seq']}\n" in body_text


# --------------------------------------------------------------------------- #
# Cancel: queued -> canceled now; running -> honored between runs.
# --------------------------------------------------------------------------- #

def test_cancel_queued_job_immediately(client):
    """With auto-dispatch off the job stays queued; cancel moves it straight to
    canceled and no worker will pick it up."""
    client.app.state.auto_dispatch = False
    try:
        job = client.post(
            "/api/v1/jobs",
            json={"model": "mock-cancelq", "tasks": [TASK], "repeats": 3},
        ).json()
        assert job["status"] == "queued"
        canceled = client.post(f"/api/v1/jobs/{job['id']}/cancel").json()
        assert canceled["status"] == "canceled"
        assert canceled["cancel_requested"] is True
        assert canceled["counters"]["completed_runs"] == 0
    finally:
        client.app.state.auto_dispatch = True


def test_cancel_running_job_is_honored_between_runs(tmp_db):
    """A cancel requested before the worker starts is honored before the first
    run: the job ends canceled with zero completed runs (no partial scoring)."""
    conn = db.connect(tmp_db)
    try:
        job = jobs.create_job(
            conn, JobCreate(model="mock-cancelr", tasks=[TASK], repeats=3)
        )
        assert jobs.claim_job(conn, job.id)
        jobs.request_cancel(conn, job.id)
        worker.run_job(conn, job.id, agent_factory=worker.mock_agent_factory)
        done = jobs.get_job(conn, job.id)
        assert done.status == "canceled"
        assert done.counters.completed_runs == 0
        # A cancel event is on the tape, monotonic with the rest.
        evs = jobs.events_since(conn, job.id, 0)
        types = [e.type for e in evs]
        assert "job_canceled" in types
        seqs = [e.seq for e in evs]
        assert seqs == list(range(1, len(seqs) + 1))
    finally:
        conn.close()


# --------------------------------------------------------------------------- #
# Bug fixes: orphan reclaim + reused-run accounting.
# --------------------------------------------------------------------------- #

def test_reclaim_stale_running_requeues_orphaned_job(tmp_db):
    """A job stranded in 'running' by a dead worker is requeued (counters reset)
    on the next worker startup, so it resumes instead of hanging forever."""
    conn = db.connect(tmp_db)
    try:
        job = jobs.create_job(
            conn, JobCreate(model="mock-orphan", tasks=[TASK], repeats=2)
        )
        assert jobs.claim_job(conn, job.id)  # -> running
        jobs.bump_counters(conn, job.id, completed=1, passed=1)  # partial progress
        assert jobs.get_job(conn, job.id).status == "running"

        reclaimed = jobs.reclaim_stale_running(conn)
        assert job.id in reclaimed
        back = jobs.get_job(conn, job.id)
        assert back.status == "queued"
        assert back.counters.completed_runs == 0
        assert back.counters.passed_runs == 0
        assert back.started_at is None
        types = [e.type for e in jobs.events_since(conn, job.id, 0)]
        assert "job_reclaimed" in types
    finally:
        conn.close()


def test_reused_runs_are_skipped_not_reexecuted(tmp_db):
    """Re-running the same (model, task, version, idx) REUSES the prior run: it is
    reported as run_skipped + counted in reused_runs, never re-executed, and
    passed/failed reflect only freshly executed runs."""
    conn = db.connect(tmp_db)
    try:
        # First job actually executes + persists 2 runs for this fresh agent.
        j1 = jobs.create_job(
            conn, JobCreate(model="mock-reuse", tasks=[TASK], repeats=2)
        )
        assert jobs.claim_job(conn, j1.id)
        worker.run_job(conn, j1.id, agent_factory=worker.mock_agent_factory)
        assert jobs.get_job(conn, j1.id).status == "succeeded"

        # Second job: same model+task+repeats -> both units already exist.
        j2 = jobs.create_job(
            conn, JobCreate(model="mock-reuse", tasks=[TASK], repeats=2)
        )
        assert jobs.claim_job(conn, j2.id)
        worker.run_job(conn, j2.id, agent_factory=worker.mock_agent_factory)
        done = jobs.get_job(conn, j2.id)
        assert done.status == "succeeded"
        assert done.counters.completed_runs == 2
        assert done.counters.reused_runs == 2   # both reused, none re-run
        assert done.counters.passed_runs == 0   # nothing freshly executed
        types = [e.type for e in jobs.events_since(conn, j2.id, 0)]
        assert types.count("run_skipped") == 2
        assert "run_started" not in types       # never re-executed the model
    finally:
        conn.close()
