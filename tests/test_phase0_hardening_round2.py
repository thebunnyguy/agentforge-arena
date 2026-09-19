"""Round-2 hardening regressions: the verification boundary, recovery isolation,
startup retry, job-row resilience, creation-time validation and small robustness gaps
found by the independent code review / black-box attack of the red-team fixes.

Every database is a copy in tmp_path; a module guard asserts reports/runs.sqlite is
byte-identical afterwards.
"""
from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import shutil
import sqlite3
import subprocess
import sys
import threading
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import afa_runner as afa
from afa_api import db, jobs, projection, startup, store_load, worker
from afa_api.main import create_app
from afa_api.schemas import Backend, JobCreate
from afa_kernel.types import RunScore, RunStatus
from afa_runner.pipeline import RunRecord

REPO = Path(__file__).resolve().parents[1]
TASK = "fix-binary-search"
DEEP = "[" * 100_000 + "]" * 100_000  # nests far beyond the interpreter's recursion limit


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
        db.migrate(conn)  # adds runs.backend_kind / control-plane tables to the copy
    return path


@contextlib.contextmanager
def _client(path: Path, *, auto_dispatch: bool = False, factory=None):
    app = create_app()
    app.state.db_path, app.state.auto_dispatch = path, auto_dispatch
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


def _make_job(path: Path, *, model="r2-model", kind="ollama", repeats=2, status="queued") -> str:
    backend = (
        Backend(kind="ollama", base_url="http://localhost:11434")
        if kind == "ollama"
        else Backend(kind=kind)
    )
    with contextlib.closing(db.connect(path)) as conn:
        job = jobs.create_job(
            conn,
            JobCreate(model=model, backend=backend, tasks=[TASK], repeats=repeats,
                      base_seed=7, temperature=0.3, request_timeout_s=30),
        )
        if status == "running":
            assert jobs.claim_job_token(conn, job.id, "dead-owner") == "dead-owner"
        return job.id


def _snapshot_with(path: Path, job_id: str, **over) -> None:
    snap = json.loads(_q(path, "SELECT snapshot_json FROM evaluation_jobs WHERE id=?", (job_id,))[0][0])
    snap.update(over)
    _x(path, "UPDATE evaluation_jobs SET snapshot_json=? WHERE id=?", (json.dumps(snap), job_id))


class SpyFactory:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def __call__(self, model, task, params):
        self.calls.append((model, task.id))
        return worker.mock_agent_factory(model, task, params)


# --------------------------------------------------------------------------- #
# 1. verify_persisted_params only ever fails with InvalidPersistedParams
# --------------------------------------------------------------------------- #


def _params_json() -> str:
    return json.dumps({
        "backend": {"kind": "ollama", "base_url": "http://localhost:11434"}, "model": "m",
        "name": None, "tasks": [TASK], "repeats": 2, "base_seed": 7, "temperature": 0.3,
        "request_timeout_s": 30, "mode": "fresh", "source_evaluation_id": None,
    })


@pytest.mark.parametrize("snapshot", [
    json.dumps({"tasks": 5}), json.dumps({"tasks": True}), json.dumps({"tasks": 1.5}),
    json.dumps({"tasks": "abc"}), json.dumps({"tasks": {"a": 1}}), json.dumps({"tasks": [1, 2]}),
    json.dumps({"tasks": [None]}), json.dumps({"backend": 5, "generation": 7, "tasks": None}),
    DEEP, "{" * 5000 + "}" * 5000, "[1e999]", "not json", "", None, "5", "null",
], ids=["tasks-int", "tasks-bool", "tasks-float", "tasks-str", "tasks-dict", "tasks-ints", "tasks-null-item",
        "scalar-sections", "deep-array", "deep-object", "overflow-float", "not-json", "empty", "none",
        "scalar", "null"])
def test_snapshot_garbage_is_unverifiable_never_an_exception(snapshot):
    with pytest.raises(jobs.InvalidPersistedParams):
        jobs.verify_persisted_params(_params_json(), snapshot, "fresh", None)


@pytest.mark.parametrize("params", [DEEP, '{"a":' * 3000, "", "null", "[]", "1e999"],
                         ids=["deep-array", "deep-object", "empty", "null", "array", "overflow-float"])
def test_params_garbage_is_unverifiable_never_an_exception(params):
    with pytest.raises(jobs.InvalidPersistedParams):
        jobs.verify_persisted_params(params, "{}", "fresh", None)


def test_evidence_json_helpers_survive_deeply_nested_input():
    from afa_api import evidence

    assert evidence.snapshot_backend_kind(DEEP) is None
    assert evidence.params_backend_kind(DEEP) is None


# --------------------------------------------------------------------------- #
# 2. One corrupt evaluation row never takes anything else down
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("hostile", [
    lambda p, j: _snapshot_with(p, j, tasks=5),
    lambda p, j: _x(p, "UPDATE evaluation_jobs SET snapshot_json=? WHERE id=?", (DEEP, j)),
    lambda p, j: _x(p, "UPDATE evaluation_jobs SET params_json=? WHERE id=?", (DEEP, j)),
], ids=["tasks-scalar", "deep-snapshot", "deep-params"])
def test_listing_survives_one_hostile_row(evcopy, hostile):
    good, bad = _make_job(evcopy, model="good"), _make_job(evcopy, model="bad")
    hostile(evcopy, bad)
    with _client(evcopy) as client:
        listing = client.get("/api/v1/jobs")
        assert listing.status_code == 200
        rows = {j["id"]: j for j in listing.json()["jobs"]}
        assert rows[good]["params_status"] == "available"
        assert rows[bad]["params_status"] == "unverifiable" and rows[bad]["params"] is None
        assert client.get(f"/api/v1/jobs/{bad}").status_code == 200
        assert client.get(f"/api/v1/jobs/{good}").status_code == 200
        report = client.get(f"/api/v1/jobs/{bad}/report.json")
        assert report.status_code == 200
        assert any("could not be verified" in lim for lim in report.json()["limitations"])


def test_deep_json_on_a_run_owning_job_does_not_take_down_the_read_side(evcopy):
    with contextlib.closing(db.connect(evcopy)) as conn:
        job = jobs.create_job(conn, JobCreate(model="deep-owner", backend=Backend(kind="mock"),
                                              tasks=[TASK], repeats=1))
        # an undeclared factory attests no provider: the run's class then depends on its
        # evaluation's (soon corrupt) snapshot, which is the case that used to 503
        worker.claim_and_run(conn, agent_factory=SpyFactory())
    assert _q(evcopy, "SELECT COUNT(*) FROM runs WHERE job_id=?", (job.id,)) == [(1,)]
    _x(evcopy, "UPDATE evaluation_jobs SET snapshot_json=?, params_json=? WHERE id=?", (DEEP, DEEP, job.id))
    with _client(evcopy) as client:
        for path in ("/api/v1/overview", "/api/v1/leaderboard", "/api/v1/meta", "/api/v1/export",
                     "/api/v1/jobs", f"/api/v1/jobs/{job.id}", "/api/v1/healthz"):
            assert client.get(path).status_code == 200, path
        body = client.get("/api/v1/overview").json()
        # the run cannot be attested any more: a conflict, excluded from the benchmark
        assert body["excluded"]["provenance_conflict_runs"] == 1
        assert "deep-owner" not in body["models"]


@pytest.mark.parametrize("setter", [
    ("status", "zzz"), ("mode", "weird"), ("total_runs", "many"), ("completed_runs", 1.5),
], ids=lambda t: t[0])
def test_corrupt_control_columns_render_as_an_unreadable_job_not_a_500(evcopy, setter):
    good, bad = _make_job(evcopy, model="good"), _make_job(evcopy, model="bad")
    column, value = setter
    with contextlib.closing(sqlite3.connect(str(evcopy))) as conn:
        conn.execute("PRAGMA ignore_check_constraints=ON")
        conn.execute(f"UPDATE evaluation_jobs SET {column}=? WHERE id=?", (value, bad))
        conn.commit()
    with _client(evcopy) as client:
        listing = client.get("/api/v1/jobs")
        assert listing.status_code == 200
        rows = {j["id"]: j for j in listing.json()["jobs"]}
        assert rows[good]["params_status"] == "available"
        assert bad in rows and rows[bad]["params_status"] == "unverifiable"
        assert rows[bad]["status"] == "failed"  # terminal: never resumable / retryable
        for verb in ("resume", "retry"):
            assert client.post(f"/api/v1/jobs/{bad}/{verb}").status_code in (404, 409), verb
        assert client.post(f"/api/v1/jobs/{bad}/cancel").status_code in (200, 404, 409)
        assert client.get(f"/api/v1/jobs/{bad}").status_code == 200


def test_event_payloads_with_non_finite_numbers_never_500(evcopy):
    job = _make_job(evcopy)
    _x(evcopy, "INSERT INTO job_events (job_id, seq, ts, type, payload_json) VALUES (?, 99, 'now', 'x', 'NaN')", (job,))
    _x(evcopy, "INSERT INTO job_events (job_id, seq, ts, type, payload_json) VALUES (?, 100, 'now', 'x', '1e999')", (job,))
    with _client(evcopy) as client:
        response = client.get(f"/api/v1/jobs/{job}/events?since=0")
        assert response.status_code == 200 and "NaN" not in response.text


# --------------------------------------------------------------------------- #
# 3. Recovery: row isolation, nothing lost, nothing silent
# --------------------------------------------------------------------------- #


def _three_orphans(path: Path) -> tuple[str, str, str]:
    first = _make_job(path, model="orphan-first", status="running")
    bad = _make_job(path, model="orphan-bad", status="running")
    last = _make_job(path, model="orphan-last", status="running")
    _snapshot_with(path, bad, tasks=5)
    return first, bad, last


def test_recovery_fails_the_corrupt_orphan_closed_and_recovers_the_others(evcopy):
    first, bad, last = _three_orphans(evcopy)
    with contextlib.closing(db.connect(evcopy)) as conn:
        recovered = jobs.reclaim_stale_running(conn, recover_unlocked=True)
    assert sorted(recovered) == sorted([first, last])
    statuses = dict(_q(evcopy, "SELECT id, status FROM evaluation_jobs"))
    assert (statuses[first], statuses[bad], statuses[last]) == ("queued", "failed", "queued")
    assert _q(evcopy, "SELECT COUNT(*) FROM runs WHERE job_id=?", (bad,)) == [(0,)]


def test_an_unexpected_row_error_never_costs_the_other_rows(evcopy, monkeypatch):
    first, bad, last = _three_orphans(evcopy)
    real = jobs._reclaim_one

    def flaky(conn, row, *args):
        if row["id"] == bad:
            raise RuntimeError("boom with a secret value")
        return real(conn, row, *args)

    monkeypatch.setattr(jobs, "_reclaim_one", flaky)
    with contextlib.closing(db.connect(evcopy)) as conn:
        with pytest.raises(jobs.RecoveryIncomplete) as caught:
            jobs.reclaim_stale_running(conn, recover_unlocked=True)
    assert sorted(caught.value.recovered) == sorted([first, last])
    assert "secret" not in str(caught.value) and "RuntimeError" in str(caught.value)
    statuses = dict(_q(evcopy, "SELECT id, status FROM evaluation_jobs"))
    assert (statuses[first], statuses[bad], statuses[last]) == ("queued", "running", "queued")
    # ... and the requeued ones are evented (nothing is left half-recovered)
    for jid in (first, last):
        assert _q(evcopy, "SELECT COUNT(*) FROM job_events WHERE job_id=? AND type='job_reclaimed'", (jid,)) == [(1,)]


def test_startup_dispatches_what_was_recovered_and_reports_what_was_not(evcopy, monkeypatch):
    first, bad, last = _three_orphans(evcopy)
    real = jobs._reclaim_one
    monkeypatch.setattr(jobs, "_reclaim_one", lambda conn, row, *a: (_ for _ in ()).throw(RuntimeError("x"))
                        if row["id"] == bad else real(conn, row, *a))
    dispatched: list[str] = []
    monkeypatch.setattr(worker, "dispatch_job", lambda db_path, job_id, **kw: dispatched.append(job_id))
    app = create_app()
    app.state.db_path = evcopy
    startup.recover_stale_jobs(app)
    assert sorted(dispatched) == sorted([first, last])
    assert "RuntimeError" in app.state.recovery_error
    with TestClient(app, raise_server_exceptions=False) as client:  # lifespan re-runs recovery too
        pass
    with _client(evcopy) as client:
        client.app_.state.recovery_error = "still broken"
        health = client.get("/api/v1/healthz").json()
        assert health["status"] == "degraded" and "recovery_error" in health


def test_recovery_is_retried_lazily_and_the_error_clears(evcopy, monkeypatch):
    _make_job(evcopy, model="late-orphan", status="running")
    app = create_app()
    app.state.db_path = evcopy
    app.state.auto_dispatch = False
    app.state.migrate_error = None
    app.state.recovery_error = "transient"
    clock = {"now": 100.0}
    monkeypatch.setattr(projection, "time", type("T", (), {"monotonic": staticmethod(lambda: clock["now"])}))
    projection.retry_migration_if_failed(app)
    assert app.state.recovery_error is None
    assert _q(evcopy, "SELECT COUNT(*) FROM evaluation_jobs WHERE status='queued'") == [(1,)]


def test_the_retry_runs_in_a_worker_thread_and_only_once_per_request(evcopy, monkeypatch):
    calls: list[bool] = []

    def spy(app):
        try:
            asyncio.get_running_loop()
            calls.append(True)  # on an event loop: would block the whole server
        except RuntimeError:
            calls.append(False)

    monkeypatch.setattr("afa_api.main.retry_migration_if_failed", spy)
    monkeypatch.setattr(projection, "retry_migration_if_failed", spy)
    with _client(evcopy) as client:
        client.app_.state.migrate_error = "locked"
        client.app_.state.recovery_error = None
        assert client.get("/api/v1/overview").status_code == 503
    assert calls == [False]  # once (the middleware), off the event loop; projections never retry


def test_resume_reclaims_only_its_own_evaluation(evcopy):
    target = _make_job(evcopy, model="resume-target", status="running")
    other = _make_job(evcopy, model="resume-other", status="running")
    _x(evcopy, "UPDATE evaluation_jobs SET owner_started_at=datetime('now', '-1 day') WHERE status='running'")
    with contextlib.closing(db.connect(evcopy)) as conn:
        jobs.resume_job(conn, target)
    statuses = dict(_q(evcopy, "SELECT id, status FROM evaluation_jobs"))
    assert statuses[target] == "queued"
    assert statuses[other] == "running"  # untouched: nothing here would dispatch it


def test_a_dying_dispatch_thread_fails_its_job_instead_of_leaving_it_running(evcopy, monkeypatch):
    job = _make_job(evcopy, model="dispatch-victim")

    def explode(*args, **kwargs):
        raise RuntimeError("worker blew up")

    monkeypatch.setattr(worker, "run_job", explode)
    worker.dispatch_job(evcopy, job).join(timeout=30)
    status, message = _q(evcopy, "SELECT status, error_message FROM evaluation_jobs WHERE id=?", (job,))[0]
    assert status == "failed" and message == "dispatch failed: RuntimeError"


# --------------------------------------------------------------------------- #
# 4. Creation-time validation and numeric bounds
# --------------------------------------------------------------------------- #


def _post(client, raw=None, **over):
    body = {"model": "m", "backend": {"kind": "mock"}, "tasks": [TASK], "repeats": 1}
    body.update(over)
    text = json.dumps(body)
    if raw is not None:
        text = text.replace('"@@"', raw)  # a BARE json literal (NaN, Infinity, 1e999)
    return client.post("/api/v1/jobs", content=text, headers={"content-type": "application/json"})


@pytest.mark.parametrize("over", [{"model": ""}, {"model": "   "}, {"repeats": 10_001}, {"repeats": 10**30}])
def test_doomed_job_creations_are_refused_up_front(evcopy, over):
    with _client(evcopy) as client:
        assert _post(client, **over).status_code == 422
    assert _q(evcopy, "SELECT COUNT(*) FROM evaluation_jobs") == [(0,)]


@pytest.mark.parametrize("literal", ["NaN", "Infinity", "-Infinity", "1e999"])
def test_non_finite_temperature_is_refused_up_front(evcopy, literal):
    with _client(evcopy) as client:
        response = _post(client, raw=literal, temperature="@@")
        assert response.status_code == 422
        assert "NaN" not in response.text and "Infinity" not in response.text and "inf" not in response.text.lower().replace("info", "")
    assert _q(evcopy, "SELECT COUNT(*) FROM evaluation_jobs") == [(0,)]


@pytest.mark.parametrize("path", [
    "/api/v1/runs/99999999999999999999", "/api/v1/runs/-1",
    "/api/v1/run/a/b/99999999999999999999",
])
def test_out_of_range_integers_are_a_client_error_not_a_500(evcopy, path):
    with _client(evcopy) as client:
        assert client.get(path).status_code == 422


def test_out_of_range_integers_on_job_routes(evcopy):
    job = _make_job(evcopy)
    with _client(evcopy) as client:
        assert client.get(f"/api/v1/jobs/{job}/events?since=99999999999999999999").status_code == 422
        assert client.get(f"/api/v1/jobs/{job}/trials/{TASK}/99999999999999999999").status_code == 422
        assert client.get(f"/api/v1/jobs/{job}/trials/{TASK}/0").status_code in (200, 404)


# --------------------------------------------------------------------------- #
# 5. Projection robustness
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "version",
    ["1.²", "①", "9" * 5000, "1..2", "", "１.０"],
    ids=["superscript", "circled-digit", "5000-digits", "double-dot", "empty", "fullwidth"],
)
def test_crafted_version_strings_never_crash_ordering_or_a_projection(evcopy, version):
    store_load.version_sort_key(version)  # must not raise
    store = afa.SqliteRunStore(evcopy)
    try:
        record = RunRecord(
            task_id=TASK, task_version=version, agent="odd-version-model", idx=0,
            status=RunStatus.VALID, score=RunScore(RunStatus.VALID, 1, 1.0, 1.0, {}, 1.0, True, False),
            files_changed=1, lines_added=1, lines_removed=0, transcript_hash="sha256:odd", duration_ms=1,
        )
        store.save_run(record)
    finally:
        store.close()
    with _client(evcopy) as client:
        for path in ("/api/v1/overview", "/api/v1/meta", "/api/v1/export",
                     f"/api/v1/cell/odd-version-model/{TASK}", f"/api/v1/cell/odd-version-model/{TASK}?version={version}"):
            assert client.get(path).status_code in (200, 404), path


def test_a_corrupt_score_column_names_the_run(evcopy):
    rid = _q(evcopy, "SELECT id FROM runs ORDER BY id LIMIT 1")[0][0]
    _x(evcopy, "UPDATE run_scores SET gate_product='abc' WHERE run_id=?", (rid,))
    with _client(evcopy) as client:
        response = client.get("/api/v1/overview")
        assert response.status_code == 503 and f"run {rid} " in response.json()["error"]


def test_cell_view_counts_runs_hidden_only_by_the_selected_scope(evcopy):
    with _client(evcopy) as client:
        cell = client.get("/api/v1/cell/qwen3.5%3A9b/fix-binary-search?evidence=real").json()
    assert cell["state"] == "not_captured"
    assert cell["excluded"]["out_of_scope_runs"] == 5  # the 5 legacy runs are counted, not hidden


def test_reserved_name_runs_never_enter_any_scope(evcopy):
    store = afa.SqliteRunStore(evcopy)
    try:
        record = RunRecord(
            task_id=TASK, task_version=json.loads((REPO / "tasks" / TASK / "task.json").read_text())["version"],
            agent="oracle (synthetic baseline)", idx=7, status=RunStatus.VALID,
            score=RunScore(RunStatus.VALID, 0, 0.0, 1.0, {}, 0.0, False, False),
            files_changed=0, lines_added=0, lines_removed=0, transcript_hash="sha256:imp", duration_ms=1,
        )
        run_id = store.save_run(record, backend_kind="ollama")
    finally:
        store.close()
    with _client(evcopy) as client:
        for scope in ("benchmark", "real", "synthetic", "all"):
            body = client.get(f"/api/v1/overview?evidence={scope}").json()
            assert "oracle (synthetic baseline)" not in body["models"], scope
            assert not [e for e in body["leaderboard"] if "baseline" in e["agent"]], scope
        exact = client.get(f"/api/v1/runs/{run_id}").json()
        assert exact["evidence_class"] == "conflict"  # inspectable by exact id, labelled


# --------------------------------------------------------------------------- #
# 6. Campaign entry points and report labels
# --------------------------------------------------------------------------- #


def _eval_persist():
    sys.path.insert(0, str(REPO / "examples"))
    try:
        import eval_persist
    finally:
        sys.path.pop(0)
    return eval_persist


def test_eval_persist_resume_ignores_mock_and_conflicting_runs(evcopy):
    module = _eval_persist()
    version = json.loads((REPO / "tasks" / TASK / "task.json").read_text())["version"]
    store = afa.SqliteRunStore(evcopy)
    try:
        def rec(agent, idx):
            return RunRecord(
                task_id=TASK, task_version=version, agent=agent, idx=idx, status=RunStatus.VALID,
                score=RunScore(RunStatus.VALID, 1, 1.0, 1.0, {}, 1.0, True, False),
                files_changed=1, lines_added=1, lines_removed=0, transcript_hash=f"sha256:{agent}{idx}", duration_ms=1,
            )
        store.save_run(rec("resume-model", 0), backend_kind="ollama")   # real: counts
        store.save_run(rec("resume-model", 1), backend_kind="mock")     # synthetic: must NOT count
        store.save_run(rec("resume-model", 2))                          # job-less, no provider: legacy, counts
        done = module.completed_indices(store, task_id=TASK, task_version=version, agent="resume-model")
    finally:
        store.close()
    assert done == {0, 2}


def test_eval_persist_refuses_the_immutable_evidence_database():
    before = hashlib.sha256(db.EVIDENCE_DB_PATH.read_bytes()).hexdigest()
    result = subprocess.run(
        [sys.executable, "-B", str(REPO / "examples" / "eval_persist.py"), "no-such-model", "1",
         str(db.EVIDENCE_DB_PATH)],
        capture_output=True, text=True, timeout=60, cwd=REPO,
    )
    assert result.returncode != 0 and "immutable" in (result.stderr + result.stdout).lower()
    assert hashlib.sha256(db.EVIDENCE_DB_PATH.read_bytes()).hexdigest() == before


def test_report_provenance_panel_says_it_counts_every_persisted_run():
    from afa_runner.store import RunStoreSummary
    from afa_runner import report_html

    html = report_html._observability_html(RunStoreSummary(
        total_runs=3, first_created_at="a", last_created_at="b", runs_with_patch=1,
        runs_with_test_results=1, test_result_rows=2,
    ))
    assert "persisted runs (all versions and evidence classes)" in html
