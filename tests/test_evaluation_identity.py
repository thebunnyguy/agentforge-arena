from __future__ import annotations

import shutil
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from afa_api import db, jobs, worker
from afa_api.main import create_app
from afa_api.schemas import Backend, JobCreate, JobParams

TASK = "fix-binary-search"


@pytest.fixture()
def temp_db(tmp_path: Path) -> Path:
    path = tmp_path / "evaluation.sqlite"
    shutil.copy(db.DB_PATH, path)
    return path


def _run(conn, params: JobCreate):
    job = jobs.create_job(conn, params)
    assert jobs.claim_job(conn, job.id)
    token = jobs.owner_token(conn, job.id)
    assert token is not None
    worker.run_job(
        conn, job.id, agent_factory=worker.mock_agent_factory, owner_token=token
    )
    return jobs.get_job(conn, job.id)


def test_default_evaluations_are_fresh_and_raw_ids_are_distinct(temp_db: Path):
    conn = db.connect(temp_db)
    try:
        first = _run(conn, JobCreate(model="identity-fresh", tasks=[TASK], repeats=2))
        second = _run(conn, JobCreate(model="identity-fresh", tasks=[TASK], repeats=2))
        assert first.id != second.id
        assert first.mode == second.mode == "fresh"
        first_ids = jobs.run_ids_for_job(conn, first.id)
        second_ids = jobs.run_ids_for_job(conn, second.id)
        assert len(first_ids) == len(second_ids) == 2
        assert set(first_ids).isdisjoint(second_ids)
        assert jobs.get_job(conn, second.id).counters.reused_runs == 0
    finally:
        conn.close()


def test_resume_keeps_committed_trial_and_runs_only_pending(
    temp_db: Path, monkeypatch: pytest.MonkeyPatch
):
    conn = db.connect(temp_db)
    try:
        created = jobs.create_job(conn, JobCreate(model="identity-resume", tasks=[TASK], repeats=2))
        assert jobs.claim_job(conn, created.id)
        first_owner = jobs.owner_token(conn, created.id)
        assert first_owner is not None
        original_run_once = worker.afa.run_once
        calls = 0

        def interrupt_after_first(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise RuntimeError("simulated worker interruption")
            return original_run_once(*args, **kwargs)

        monkeypatch.setattr(worker.afa, "run_once", interrupt_after_first)
        worker.run_job(
            conn, created.id, agent_factory=worker.mock_agent_factory,
            owner_token=first_owner,
        )
        failed = jobs.get_job(conn, created.id)
        assert failed.status == "failed"
        first_ids = jobs.run_ids_for_job(conn, created.id)
        assert len(first_ids) == 1

        resumed = jobs.resume_job(conn, created.id)
        assert resumed.status == "queued"
        assert jobs.claim_job(conn, created.id)
        resumed_owner = jobs.owner_token(conn, created.id)
        assert resumed_owner is not None
        monkeypatch.setattr(worker.afa, "run_once", original_run_once)
        worker.run_job(
            conn, created.id, agent_factory=worker.mock_agent_factory,
            owner_token=resumed_owner,
        )
        done = jobs.get_job(conn, created.id)
        assert done.status == "succeeded"
        all_ids = jobs.run_ids_for_job(conn, created.id)
        assert all_ids[0] == first_ids[0]
        assert len(all_ids) == 2
        assert conn.execute(
            "SELECT COUNT(*) AS n FROM evaluation_trials WHERE evaluation_id=? AND trial_state='completed'",
            (created.id,),
        ).fetchone()["n"] == 2
    finally:
        conn.close()


def test_raw_trial_transaction_rolls_back_together(temp_db: Path):
    conn = db.connect(temp_db)
    try:
        created = jobs.create_job(conn, JobCreate(model="identity-rollback", tasks=[TASK], repeats=1))
        assert jobs.claim_job(conn, created.id)
        rollback_owner = jobs.owner_token(conn, created.id)
        assert rollback_owner is not None
        before = conn.execute("SELECT COUNT(*) AS n FROM runs").fetchone()["n"]
        real_store = worker.afa.SqliteRunStore(connection=conn)

        class FailAfterRawInsert:
            _conn = conn

            def save_run(self, *args, **kwargs):
                real_store.save_run(*args, **kwargs)
                raise RuntimeError("simulated trial association failure")

        worker.run_job(
            conn,
            created.id,
            agent_factory=worker.mock_agent_factory,
            store=FailAfterRawInsert(),
            owner_token=rollback_owner,
        )
        assert jobs.get_job(conn, created.id).status == "failed"
        assert conn.execute("SELECT COUNT(*) AS n FROM runs").fetchone()["n"] == before
        trial = jobs.trial_rows(conn, created.id)[0]
        assert trial["trial_state"] == "pending"
        assert jobs.run_ids_for_job(conn, created.id) == []
    finally:
        conn.close()


def test_post_commit_event_failure_recovers_without_duplicate_raw_run(
    temp_db: Path, monkeypatch: pytest.MonkeyPatch
):
    conn = db.connect(temp_db)
    try:
        created = jobs.create_job(conn, JobCreate(model="identity-post-commit", tasks=[TASK], repeats=1))
        assert jobs.claim_job(conn, created.id)
        post_commit_owner = jobs.owner_token(conn, created.id)
        assert post_commit_owner is not None
        original_append = jobs.append_event

        def fail_persist_event(conn_, job_id, event_type, payload=None):
            if event_type == "run_persisted":
                raise RuntimeError("simulated event recorder failure")
            return original_append(conn_, job_id, event_type, payload)

        monkeypatch.setattr(jobs, "append_event", fail_persist_event)
        worker.run_job(
            conn, created.id, agent_factory=worker.mock_agent_factory,
            owner_token=post_commit_owner,
        )
        assert jobs.get_job(conn, created.id).status == "failed"
        run_ids = jobs.run_ids_for_job(conn, created.id)
        assert len(run_ids) == 1

        monkeypatch.setattr(jobs, "append_event", original_append)
        assert jobs.resume_job(conn, created.id).status == "queued"
        assert jobs.claim_job(conn, created.id)
        resumed_owner = jobs.owner_token(conn, created.id)
        assert resumed_owner is not None
        worker.run_job(
            conn, created.id, agent_factory=worker.mock_agent_factory,
            owner_token=resumed_owner,
        )
        assert jobs.get_job(conn, created.id).status == "succeeded"
        assert jobs.run_ids_for_job(conn, created.id) == run_ids
    finally:
        conn.close()


def test_changed_task_snapshot_is_unverifiable_not_drifted(
    temp_db: Path, monkeypatch: pytest.MonkeyPatch
):
    conn = db.connect(temp_db)
    try:
        created = jobs.create_job(conn, JobCreate(model="identity-drift", tasks=[TASK], repeats=1))
        assert jobs.claim_job(conn, created.id)
        drift_owner = jobs.owner_token(conn, created.id)
        assert drift_owner is not None
        original_snapshot = jobs.task_snapshot

        def changed_snapshot(task_id: str):
            value = original_snapshot(task_id)
            value["task_digest"] = "sha256:changed"
            return value

        monkeypatch.setattr(jobs, "task_snapshot", changed_snapshot)
        worker.run_job(
            conn, created.id, agent_factory=worker.mock_agent_factory,
            owner_token=drift_owner,
        )
        done = jobs.get_job(conn, created.id)
        assert done.status == "failed"
        trial = jobs.trial_rows(conn, created.id)[0]
        assert trial["trial_state"] == "blocked"
        assert trial["evidence_state"] == "unverifiable"
        assert jobs.run_ids_for_job(conn, created.id) == []
    finally:
        conn.close()


def test_explicit_reuse_has_source_and_origin_without_new_raw_rows(temp_db: Path):
    conn = db.connect(temp_db)
    try:
        source = _run(conn, JobCreate(model="identity-reuse", tasks=[TASK], repeats=1))
        source_run_id = jobs.run_ids_for_job(conn, source.id)[0]
        before = conn.execute("SELECT COUNT(*) AS n FROM runs").fetchone()["n"]
        reused = jobs.create_job(
            conn,
            JobCreate(
                model="identity-reuse",
                tasks=[TASK],
                repeats=1,
                mode="reuse",
                source_evaluation_id=source.id,
            ),
        )
        assert reused.counters.completed_runs == 1
        assert reused.counters.reused_runs == 1
        assert jobs.claim_job(conn, reused.id)
        reused_owner = jobs.owner_token(conn, reused.id)
        assert reused_owner is not None
        worker.run_job(
            conn, reused.id, agent_factory=worker.mock_agent_factory,
            owner_token=reused_owner,
        )
        detail = jobs.trial_detail(conn, reused.id, TASK, 0)
        assert detail["run_id"] == source_run_id
        assert detail["source_run_id"] == source_run_id
        assert detail["origin_evaluation_id"] == source.id
        assert conn.execute("SELECT COUNT(*) AS n FROM runs").fetchone()["n"] == before
    finally:
        conn.close()


def test_competing_connections_have_one_evaluation_owner(temp_db: Path):
    conn = db.connect(temp_db)
    try:
        created = jobs.create_job(conn, JobCreate(model="identity-claim", tasks=[TASK], repeats=1))
    finally:
        conn.close()

    def compete(_):
        candidate = db.connect(temp_db)
        try:
            return jobs.claim_job(candidate, created.id)
        finally:
            candidate.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(compete, [0, 1]))
    assert sorted(results) == [False, True]


def test_stale_owner_cannot_complete_successor_claim(temp_db: Path):
    conn = db.connect(temp_db)
    try:
        created = jobs.create_job(conn, JobCreate(model="identity-fence", tasks=[TASK], repeats=1))
        assert jobs.claim_job(conn, created.id, owner_token="owner-a")
        first_owner_claim = jobs.claim_trial(conn, created.id, TASK, 0, "owner-a")
        assert first_owner_claim
        conn.execute(
            "UPDATE evaluation_jobs SET owner_started_at=datetime('now', '-1 hour') WHERE id=?",
            (created.id,),
        )
        conn.commit()
        assert created.id in jobs.reclaim_stale_running(conn)
        assert jobs.claim_job(conn, created.id, owner_token="owner-b")
        successor_claim = jobs.claim_trial(conn, created.id, TASK, 0, "owner-b")
        assert successor_claim and successor_claim != first_owner_claim
        with pytest.raises(jobs.TrialClaimError):
            jobs.complete_trial(
                conn, created.id, TASK, 0, first_owner_claim, run_id=1,
                owner_token="owner-a",
            )
        trial = jobs.trial_rows(conn, created.id)[0]
        assert trial["claim_token"] == successor_claim
        assert trial["trial_state"] == "claimed"
    finally:
        conn.close()


def test_live_owner_is_not_reclaimed_but_stale_owner_is(temp_db: Path):
    conn = db.connect(temp_db)
    try:
        created = jobs.create_job(conn, JobCreate(model="identity-owner", tasks=[TASK], repeats=1))
        assert jobs.claim_job(conn, created.id)
        assert created.id not in jobs.reclaim_stale_running(conn)
        conn.execute(
            "UPDATE evaluation_jobs SET owner_started_at=datetime('now', '-1 hour') WHERE id=?",
            (created.id,),
        )
        conn.commit()
        assert created.id in jobs.reclaim_stale_running(conn)
        assert jobs.get_job(conn, created.id).status == "queued"
    finally:
        conn.close()


def test_empty_migration_and_malformed_app_schema_fail_closed(tmp_path: Path):
    empty = tmp_path / "empty.sqlite"
    conn = db.connect(empty)
    try:
        db.migrate(conn)
        assert conn.execute("SELECT 1 FROM evaluation_trials").fetchone() is None
    finally:
        conn.close()

    malformed = tmp_path / "malformed.sqlite"
    raw = sqlite3.connect(malformed)
    raw.execute("CREATE TABLE evaluation_jobs (id TEXT PRIMARY KEY)")
    raw.execute("INSERT INTO evaluation_jobs VALUES ('keep-me')")
    raw.commit()
    raw.close()
    conn = db.connect(malformed)
    try:
        with pytest.raises(RuntimeError, match="unsupported existing evaluation_jobs schema"):
            db.migrate(conn)
        assert conn.execute(
            "SELECT id FROM evaluation_jobs"
        ).fetchone()["id"] == "keep-me"
    finally:
        conn.close()


def test_exact_run_route_and_ambiguous_tuple_route(temp_db: Path):
    conn = db.connect(temp_db)
    try:
        model = f"identity-api-{uuid4().hex}"
        first = _run(conn, JobCreate(model=model, tasks=[TASK], repeats=1))
        second = _run(conn, JobCreate(model=model, tasks=[TASK], repeats=1))
        first_id = jobs.run_ids_for_job(conn, first.id)[0]
        second_id = jobs.run_ids_for_job(conn, second.id)[0]
    finally:
        conn.close()

    app = create_app()
    app.state.db_path = temp_db
    app.state.auto_dispatch = False
    with TestClient(app) as client:
        exact = client.get(f"/api/v1/runs/{first_id}")
        assert exact.status_code == 200
        assert exact.json()["run_id"] == first_id
        assert exact.json()["job_id"] == first.id
        ambiguous = client.get(f"/api/v1/run/{model}/{TASK}/0")
        assert ambiguous.status_code == 409
        assert set(ambiguous.json()["candidate_run_ids"]) == {first_id, second_id}

        mixed = db.connect(temp_db)
        try:
            mixed.execute(
                "UPDATE runs SET task_version='unrelated-version' WHERE id=?",
                (first_id,),
            )
            mixed.commit()
        finally:
            mixed.close()
        exact_after_mixed = client.get(f"/api/v1/runs/{first_id}")
        assert exact_after_mixed.status_code == 200
        assert exact_after_mixed.json()["run_id"] == first_id
        aggregate = client.get("/api/v1/overview")
        assert aggregate.status_code == 503


def test_resume_api_preserves_id_and_rejects_live_owner(temp_db: Path):
    app = create_app()
    app.state.db_path = temp_db
    app.state.auto_dispatch = False
    with TestClient(app) as client:
        created = client.post(
            "/api/v1/jobs",
            json={"model": "identity-resume-api", "tasks": [TASK], "repeats": 1},
        ).json()
        canceled = client.post(f"/api/v1/jobs/{created['id']}/cancel").json()
        assert canceled["status"] == "canceled"
        resumed = client.post(f"/api/v1/jobs/{created['id']}/resume")
        assert resumed.status_code == 200
        assert resumed.json()["id"] == created["id"]
        assert resumed.json()["status"] == "queued"

        conn = db.connect(temp_db)
        try:
            assert jobs.claim_job(conn, created["id"])
        finally:
            conn.close()
        live = client.post(f"/api/v1/jobs/{created['id']}/resume")
        assert live.status_code == 409


def test_provider_factory_selection_timeout_and_stable_seed():
    ollama = JobParams(
        model="local-ollama",
        backend=Backend(kind="ollama", base_url="http://127.0.0.1:11434"),
        request_timeout_s=17,
        base_seed=100,
    )
    openai = JobParams(
        model="local-openai",
        backend=Backend(kind="openai_compat", base_url="http://127.0.0.1:1234"),
        request_timeout_s=19,
        base_seed=200,
    )
    ollama_agent = worker.factory_for(ollama)(ollama.model, None, ollama)
    openai_agent = worker.factory_for(openai)(openai.model, None, openai)
    assert type(ollama_agent).__name__ == "OllamaAgent"
    assert type(openai_agent).__name__ == "OpenAICompatAgent"
    assert ollama_agent.request_timeout == 17
    assert openai_agent.request_timeout == 19
    worker._set_effective_seed(openai_agent, 207)
    assert openai_agent.base_seed == 207
    assert openai_agent._call == 0


def test_secret_bearing_backend_configuration_is_rejected():
    with pytest.raises(ValueError, match="credentials"):
        Backend(kind="ollama", base_url="http://user:password@localhost:11434")
    with pytest.raises(ValueError, match="query"):
        Backend(kind="openai_compat", base_url="http://localhost:1234?api_key=x")
