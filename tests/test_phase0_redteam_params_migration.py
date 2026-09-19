"""Red-team regression tests C: persisted params, execution guard, migration retry, recovery.

Written from the red-team findings F4 / F7 / F11 / F12 and driven only through the public
API, the DB and the worker. F4: non-finite numbers in params_json / snapshot_json never
500 the job endpoints. F11: the listing never shows defaults, coercions or params that
execution refuses as "available". F12: the execution guard cross-checks mode and
source_evaluation_id against the row and rejects extra keys; errors carry only sanitised
FIELD NAMES. F7: a failed startup migration is retried lazily (rate-limited, thread-safe).
REC: startup recovery of corrupt orphans fails closed and never reaches an agent factory.

Tests commented "PRODUCT BUG" assert the CORRECT behaviour and FAIL on the current code.
Every database is a copy in tmp_path; a module guard asserts reports/runs.sqlite is unchanged.
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import math
import re
import shutil
import sqlite3
import threading
import time
import types
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from afa_api import db, jobs, projection, worker
from afa_api.main import create_app
from afa_api.schemas import Backend, JobCreate

TASK = "fix-binary-search"
PREFIX = "invalid persisted evaluation parameters"
HOST = "HOSTILE9f3a"  # marker planted in every attacker-controlled key / value


@pytest.fixture(scope="module", autouse=True)
def _evidence_db_is_byte_identical():
    before = hashlib.sha256(db.EVIDENCE_DB_PATH.read_bytes()).hexdigest()
    yield
    assert hashlib.sha256(db.EVIDENCE_DB_PATH.read_bytes()).hexdigest() == before


# ------------------------------------ helpers ------------------------------------ #


@contextlib.contextmanager
def _client(path: Path, *, factory=None, auto_dispatch: bool = False):
    app = create_app()
    app.state.db_path, app.state.auto_dispatch = path, auto_dispatch
    if factory is not None:
        app.state.agent_factory = factory
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client


class SpyFactory:
    """Records every agent construction request (delegates to the offline mock)."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def __call__(self, model, task, params):
        self.calls.append((model, task.id))
        return worker.mock_agent_factory(model, task, params)


@pytest.fixture()
def run_once_counter(monkeypatch):
    """Independent proof that no agent ever ran: count afa.run_once invocations."""
    counter, original = {"n": 0}, worker.afa.run_once

    def counting(*args, **kwargs):
        counter["n"] += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(worker.afa, "run_once", counting)
    return counter


@pytest.fixture()
def evcopy(tmp_path) -> Path:
    path = tmp_path / "work-copy.sqlite"
    shutil.copy(db.EVIDENCE_DB_PATH, path)
    return path


def _q(path: Path, sql: str, args=()) -> list[tuple]:
    with contextlib.closing(db.connect_readonly(path)) as conn:
        return [tuple(r) for r in conn.execute(sql, args).fetchall()]


def _col(path: Path, job_id: str, column: str):
    return _q(path, f"SELECT {column} FROM evaluation_jobs WHERE id=?", (job_id,))[0][0]


def _update(path: Path, job_id: str, column: str, value) -> None:
    with contextlib.closing(sqlite3.connect(str(path))) as conn:
        conn.execute(f"UPDATE evaluation_jobs SET {column}=? WHERE id=?", (value, job_id))
        conn.commit()


def _make_job(path: Path, *, model="corrupt-model", kind="ollama", repeats=2, status="queued") -> str:
    """A genuine non-legacy evaluation created through the library (never dispatched)."""
    backend = Backend(kind="ollama", base_url="http://localhost:11434") if kind == "ollama" else Backend(kind=kind)
    with contextlib.closing(db.connect(path)) as conn:
        job = jobs.create_job(conn, JobCreate(model=model, backend=backend, tasks=[TASK], repeats=repeats,
                                              base_seed=7, temperature=0.3, request_timeout_s=30))
        if status == "running":
            assert jobs.claim_job_token(conn, job.id, "dead-owner") == "dead-owner"
        return job.id


def _corrupt(path: Path, job_id: str, mutator) -> None:
    _update(path, job_id, "params_json", mutator(json.loads(_col(path, job_id, "params_json"))))


# mutators: valid params dict -> persisted params_json text
def _mut(**over):
    return lambda d: json.dumps({**d, **over})


def _drop(*keys):
    return lambda d: json.dumps({k: v for k, v in d.items() if k not in keys})


def _backend(**over):
    return lambda d: json.dumps({**d, "backend": {**d["backend"], **over}})


def _lit(**fields):
    """Each field becomes a BARE json literal (NaN, Infinity, 1e999): json.dumps cannot emit those."""

    def mutate(d):
        text = json.dumps({**d, **{k: f"@@{k}@@" for k in fields}})
        for key, literal in fields.items():
            text = text.replace(f'"@@{key}@@"', literal)
        return text

    return mutate


def _all_finite(value) -> bool:
    if isinstance(value, dict):
        value = list(value.values())
    if isinstance(value, list):
        return all(_all_finite(v) for v in value)
    return not isinstance(value, float) or math.isfinite(value)


def _job_urls(job_id: str) -> list[str]:
    base = f"/api/v1/jobs/{job_id}"
    return ["/api/v1/jobs", base, *(f"{base}/{s}" for s in ("results", "trials", "report.json", "report.md", "events?since=0"))]


def _error_text(path: Path, job_id: str) -> str:
    """Every persisted error / log string of the job: job error, trial errors, event payloads."""
    return "\n".join(str(r[0]) for r in _q(
        path, "SELECT error_message FROM evaluation_jobs WHERE id=? UNION ALL "
        "SELECT error_message FROM evaluation_trials WHERE evaluation_id=? UNION ALL "
        "SELECT payload_json FROM job_events WHERE job_id=?", (job_id,) * 3))


def _leak_text(client, path: Path, job_id: str, *, listing: bool = True) -> str:
    """Everything an operator can read back: every read surface plus the persisted errors.
    ``listing=False`` omits GET /jobs and /jobs/{id}, which DISPLAY the params of a row they
    consider valid."""
    parts = []
    for url in _job_urls(job_id)[(0 if listing else 2):]:
        resp = client.get(url)
        assert resp.status_code == 200, (url, resp.status_code)
        parts.append(resp.text)
    return "\n".join(parts + [_error_text(path, job_id)])


def _wait_status(client, job_id: str, want: set[str], timeout: float = 20.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        body = client.get(f"/api/v1/jobs/{job_id}").json()
        if body["status"] in want:
            return body
        time.sleep(0.02)
    raise AssertionError(f"job {job_id} never reached {want}")


def _assert_failed_closed(path: Path, job_id: str, spy=None, counter=None, runs_before=None) -> None:
    """The evaluation failed as unverifiable; no agent ran and no evidence was written."""
    assert spy is None or spy.calls == [], "the agent factory was called for an unverifiable evaluation"
    assert counter is None or counter["n"] == 0, "an agent ran for an unverifiable evaluation"
    status, error, owner = _q(path, "SELECT status, error_message, owner_token FROM evaluation_jobs WHERE id=?", (job_id,))[0]
    assert status == "failed" and owner is None and error.startswith(PREFIX), (status, error)
    assert runs_before is None or _q(path, "SELECT COUNT(*) FROM runs")[0][0] == runs_before
    assert _q(path, "SELECT COUNT(*) FROM runs WHERE job_id=?", (job_id,))[0][0] == 0
    assert _q(path, "SELECT COUNT(*) FROM job_runs WHERE job_id=?", (job_id,))[0][0] == 0
    trials = _q(path, "SELECT trial_state, evidence_state, run_id, error_message FROM evaluation_trials WHERE evaluation_id=?", (job_id,))
    assert trials and all(t[:3] == ("blocked", "unverifiable", None) and (t[3] or "").startswith(PREFIX) for t in trials)
    assert not {r[0] for r in _q(path, "SELECT type FROM job_events WHERE job_id=?", (job_id,))} & {"run_started", "run_graded", "run_persisted"}


def _run_worker_once(path: Path, spy: SpyFactory) -> str | None:
    with contextlib.closing(db.connect(path)) as conn:
        return worker.claim_and_run(conn, agent_factory=spy)


def _fail_closed_via_worker(path: Path, job_id: str, counter) -> SpyFactory:
    runs_before = _q(path, "SELECT COUNT(*) FROM runs")[0][0]
    spy = SpyFactory()
    assert _run_worker_once(path, spy) == job_id
    _assert_failed_closed(path, job_id, spy, counter, runs_before)
    return spy


# ------------- F4 / F11: one shared listing (good, non-finite, lenient, contradicting rows) ------------- #

NONFINITE = {  # label -> (mutator, offending field)
    "temperature-NaN": (_lit(temperature="NaN"), "temperature"),
    "temperature-Infinity": (_lit(temperature="Infinity"), "temperature"),
    "temperature--Infinity": (_lit(temperature="-Infinity"), "temperature"),
    "temperature-1e999": (_lit(temperature="1e999"), "temperature"),
    "temperature--1e999": (_lit(temperature="-1e999"), "temperature"),
    "timeout-Infinity": (_lit(request_timeout_s="Infinity"), "request_timeout_s"),
    "seed-NaN": (_lit(base_seed="NaN"), "base_seed"),
}
# Each was displayed as "available" with a fabricated default or a coerced value before the
# display path reused the strict execution parse.
COERCION = {
    "missing-temperature": _drop("temperature"), "missing-model": _drop("model"), "missing-backend": _drop("backend"),
    "repeats-true": _mut(repeats=True), "repeats-string": _mut(repeats="2"),
    "base-seed-false": _mut(base_seed=False), "base-seed-string": _mut(base_seed="7"), "base-seed-float": _mut(base_seed=7.0),
    "temperature-true": _mut(temperature=True), "name-int": _mut(name=5),
    "tasks-empty": _mut(tasks=[]), "model-blank": _mut(model="   "),
}
# Well-formed params that CONTRADICT the creation snapshot or the row columns: execution
# refuses every one of them.
CONTRADICTION = {
    "repeats-1e30": _mut(repeats=10**30), "model-padded": _mut(model=" corrupt-model "),
    "task-path": _mut(tasks=["../tasks/fix-binary-search"]), "backend-url": _backend(base_url="http://localhost:9999"),
    "base-seed": _mut(base_seed=8), "temperature": _mut(temperature=0.9),
    "mode-reuse": _mut(mode="reuse"), "source-id": _mut(source_evaluation_id="abc"),
}


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    """Good rows plus one row per corrupt / contradicting case, listed once by one client."""
    path = tmp_path_factory.mktemp("params-world") / "params-world.sqlite"
    shutil.copy(db.EVIDENCE_DB_PATH, path)
    w = types.SimpleNamespace(path=path, bad={}, coerced={}, contradicting={})
    w.good = {"mock": _make_job(path, model="good-mock", kind="mock", repeats=1), "ollama": _make_job(path, model="good-ollama")}
    w.good_params = {jid: json.loads(_col(path, jid, "params_json")) for jid in w.good.values()}
    for table, store in ((NONFINITE, w.bad), (COERCION, w.coerced), (CONTRADICTION, w.contradicting)):
        for label, entry in table.items():
            store[label] = _make_job(path)  # model "corrupt-model": the model mutators refer to it
            _corrupt(path, store[label], entry[0] if isinstance(entry, tuple) else entry)
    w.all_ids = {*w.good.values(), *w.bad.values(), *w.coerced.values(), *w.contradicting.values()}
    with _client(path) as w.client:
        w.listing = w.client.get("/api/v1/jobs")
        w.rows = {j["id"]: j for j in w.listing.json()["jobs"]} if w.listing.status_code == 200 else {}
        yield w


def _row(world, job_id: str) -> dict:
    assert world.listing.status_code == 200, "GET /jobs failed: one bad row took down the whole listing"
    return world.rows[job_id]


def test_one_listing_with_every_nonfinite_row_is_200_and_keeps_the_good_rows(world):
    """F4: NaN / +-Infinity / +-1e999 must never 500 the whole control-plane listing."""
    assert world.listing.status_code == 200 and set(world.rows) == world.all_ids  # every row listed
    for kind, jid in world.good.items():
        row = world.rows[jid]
        assert row["params_status"] == "available" and row["params_error"] is None
        assert row["params"] == world.good_params[jid], f"good {kind} row was altered by the strict display parse"
    assert "NaN" not in world.listing.text and "Infinity" not in world.listing.text


@pytest.mark.parametrize("label", sorted(NONFINITE))
def test_a_nonfinite_row_is_unverifiable_in_the_listing_and_on_its_own_endpoint(world, label):
    single = world.client.get(f"/api/v1/jobs/{world.bad[label]}")
    assert single.status_code == 200, "GET /jobs/{id} must not 500 for a non-finite params_json"
    for body in (single.json(), _row(world, world.bad[label])):
        assert body["params"] is None and body["params_status"] == "unverifiable"
        assert body["params_error"].startswith(PREFIX) and NONFINITE[label][1] in body["params_error"]
        assert body["backend_kind"] == "ollama"  # still known from the creation snapshot
    assert "NaN" not in single.text and "Infinity" not in single.text


@pytest.mark.parametrize("label", ["temperature-NaN", "temperature-1e999", "timeout-Infinity"])
def test_no_job_surface_returns_a_server_error_for_a_nonfinite_row(world, label):
    jid = world.bad[label]
    for url in _job_urls(jid) + [f"/api/v1/jobs/{jid}/trials/{TASK}/0"]:
        assert world.client.get(url).status_code == 200, url
    assert world.client.post(f"/api/v1/jobs/{jid}/resume").status_code == 409
    assert world.client.post(f"/api/v1/jobs/{jid}/retry").status_code == 409  # queued: not terminal


@pytest.mark.parametrize("label", sorted(COERCION))
def test_lenient_defaults_and_coercions_are_never_shown_as_available(world, label):
    """F11: a missing field must not become a default (temperature 0.6, model "mock", ...)
    and "2" / True / 7.0 must not be coerced into a valid value."""
    jid = world.coerced[label]
    for body in (_row(world, jid), world.client.get(f"/api/v1/jobs/{jid}").json()):
        assert body["params"] is None, f"{label}: shown as {body['params']}"
        assert body["params_status"] == "unverifiable" and body["params_error"].startswith(PREFIX)


@pytest.mark.parametrize("label", sorted(CONTRADICTION))
def test_listing_of_params_that_execution_refuses_is_unverifiable(world, label):
    """F11 (PRODUCT BUG, partially fixed): the listing must agree with execution.

    _job_params_for_display promises that "a listing can never show clean-looking parameters
    for a row that execution refuses", but it never cross-checks the creation snapshot nor
    the mode / source_evaluation_id columns, so these rows are listed as params_status
    "available" although execution_params refuses every one of them."""
    jid = world.contradicting[label]
    with contextlib.closing(db.connect_readonly(world.path)) as conn:
        with pytest.raises(jobs.InvalidPersistedParams):  # precondition: execution refuses it
            jobs.execution_params(conn, jid)
    for body in (_row(world, jid), world.client.get(f"/api/v1/jobs/{jid}").json()):
        assert body["params_status"] == "unverifiable", f"{label}: listed as available params {body['params']}"
        assert body["params"] is None and body["params_error"].startswith(PREFIX)


@pytest.mark.parametrize("literal", ["NaN", "Infinity", "-Infinity", "1e999", "-1e999"])
def test_a_nonfinite_snapshot_never_500s_and_never_breaks_the_listing(evcopy, literal):
    """F4, snapshot side. PRODUCT BUG for 1e999 / -1e999: the snapshot is parsed with
    parse_constant, which intercepts the NaN / Infinity literals but not the legal number
    1e999 (parsed to +inf), so Starlette refuses to render the Job: 500 for GET /jobs
    (every job), GET /jobs/{id}, /results, /trials and /cancel."""
    good = _make_job(evcopy, model="good-mock", kind="mock", repeats=1)
    bad = _make_job(evcopy, model="bad-snapshot")
    snap = json.loads(_col(evcopy, bad, "snapshot_json"))
    snap["generation"]["temperature"] = "@@"
    _update(evcopy, bad, "snapshot_json", json.dumps(snap).replace('"@@"', literal))
    with _client(evcopy) as client:
        listing = client.get("/api/v1/jobs")
        assert listing.status_code == 200, "one bad snapshot took down the whole listing"
        rows = {j["id"]: j for j in listing.json()["jobs"]}
        assert set(rows) == {good, bad}
        assert rows[good]["params_status"] == "available" and rows[good]["snapshot"] is not None
        for url in (f"/api/v1/jobs/{bad}", f"/api/v1/jobs/{bad}/results", f"/api/v1/jobs/{bad}/trials"):
            resp = client.get(url)
            assert resp.status_code == 200 and _all_finite(resp.json()), url
        assert client.post(f"/api/v1/jobs/{bad}/cancel").status_code == 200


# ---------------------------------- F12: execution guard ---------------------------------- #

COLUMN_CASES = {  # id -> (params mutator, {row column: value}, expected disagreeing fields)
    "params-reuse-and-source": (_mut(mode="reuse", source_evaluation_id=f"{HOST}-src"), {}, "mode, source_evaluation_id"),
    "params-fresh-with-source": (_mut(source_evaluation_id=f"{HOST}-src"), {}, "source_evaluation_id"),
    "params-reuse-only": (_mut(mode="reuse"), {}, "mode"),
    "row-reuse-and-source": (_mut(), {"mode": "reuse", "source_evaluation_id": f"{HOST}-row"}, "mode, source_evaluation_id"),
    "row-source-only": (_mut(), {"source_evaluation_id": f"{HOST}-row"}, "source_evaluation_id"),
}


@pytest.mark.parametrize("cid", sorted(COLUMN_CASES))
def test_execution_cross_checks_mode_and_source_against_the_row_columns(evcopy, run_once_counter, cid):
    mutator, columns, fields = COLUMN_CASES[cid]
    job_id = _make_job(evcopy)
    _corrupt(evcopy, job_id, mutator)
    for column, value in columns.items():
        _update(evcopy, job_id, column, value)
    _fail_closed_via_worker(evcopy, job_id, run_once_counter)
    assert _col(evcopy, job_id, "error_message") == f"{PREFIX}: parameters disagree with the evaluation row ({fields})"
    assert HOST not in _error_text(evcopy, job_id)  # field names only, never the offending value


def test_a_genuine_reuse_evaluation_is_not_rejected_by_the_column_cross_check(evcopy):
    """Control: the new guard must not reject a legitimate reuse evaluation."""
    with contextlib.closing(db.connect(evcopy)) as conn:
        mock = Backend(kind="mock")
        src = jobs.create_job(conn, JobCreate(model="reuse-model", backend=mock, tasks=[TASK], repeats=1))
        worker.run_job(conn, src.id, agent_factory=worker.mock_agent_factory, owner_token=jobs.claim_job_token(conn, src.id))
        assert jobs.get_job(conn, src.id).status == "succeeded"
        reuse = jobs.create_job(conn, JobCreate(model="reuse-model", backend=mock, tasks=[TASK], repeats=1,
                                                mode="reuse", source_evaluation_id=src.id))
        params = jobs.execution_params(conn, reuse.id)
        assert (params.mode, params.source_evaluation_id) == ("reuse", src.id)
        spy = SpyFactory()
        assert worker.claim_and_run(conn, agent_factory=spy) == reuse.id
        assert jobs.get_job(conn, reuse.id).status == "succeeded" and spy.calls == []
    with _client(evcopy) as client:
        body = client.get(f"/api/v1/jobs/{reuse.id}").json()
        assert body["params_status"] == "available" and body["params"]["mode"] == "reuse"


EXTRA_KEYS = {
    "api-key": {"api_key": f"sk-{HOST}"},
    "secret-key-name": {f"sk-{HOST}-KEYNAME": 1},
    "newline-key-name": {f"x\n{HOST}: forged log line": 1},
}


@pytest.mark.parametrize("cid", sorted(EXTRA_KEYS))
def test_extra_top_level_keys_in_persisted_params_are_rejected(evcopy, run_once_counter, cid):
    """F12 (PRODUCT BUG): JobParams still ignores unknown keys (only JobCreate has
    extra="forbid"), so a persisted params_json carrying an extra top-level key passes
    execution_params and the evaluation RUNS. It must fail closed instead."""
    job_id = _make_job(evcopy)
    _corrupt(evcopy, job_id, _mut(**EXTRA_KEYS[cid]))
    with contextlib.closing(db.connect_readonly(evcopy)) as conn:
        with pytest.raises(jobs.InvalidPersistedParams):
            jobs.execution_params(conn, job_id)
    _fail_closed_via_worker(evcopy, job_id, run_once_counter)
    with _client(evcopy) as client:
        assert HOST not in _leak_text(client, evcopy, job_id)


HOSTILE_KEYS = {"secret-looking": f"sk-{HOST}", "newline-forged-line": f"line1\n{HOST}: forged",
                "ansi-escape": f"\x1b[31m{HOST}", "very-long": HOST * 60}


@pytest.mark.parametrize("cid", sorted(HOSTILE_KEYS))
def test_hostile_key_names_are_never_echoed_by_any_surface(evcopy, cid):
    """F12: a stray key inside `backend` used to surface as `backend.<key name>` in
    params_error, error_message, trial errors, events and the reports."""
    key, expected = HOSTILE_KEYS[cid], f"{PREFIX}: invalid fields: backend.<unexpected key>"
    job_id = _make_job(evcopy)
    _corrupt(evcopy, job_id, _backend(**{key: 1}))
    with _client(evcopy) as client:
        listed = client.get(f"/api/v1/jobs/{job_id}").json()
        assert listed["params_status"] == "unverifiable" and listed["params_error"] == expected
        assert _run_worker_once(evcopy, SpyFactory()) == job_id
        assert _col(evcopy, job_id, "error_message") == expected
        text = _leak_text(client, evcopy, job_id)
        assert HOST not in text and "forged" not in text and key not in text and expected in text


_FIELD = (r"(?:model|name|params|backend(?:\.(?:kind|base_url|<unexpected key>))?|tasks(?:\.\d+)?|repeats"
          r"|base_seed|temperature|request_timeout_s|mode|source_evaluation_id|<unexpected key>)")
CLOSED_VOCABULARY = re.compile(
    rf"{PREFIX}: (?:params_json is not valid JSON|params_json is not a JSON object"
    rf"|missing fields: [a-z_]+(?:, [a-z_]+)*|invalid fields: {_FIELD}(?:, {_FIELD})*"
    rf"|parameters disagree with the (?:evaluation row|creation snapshot) \([a-z_.]+(?:, [a-z_.]+)*\)"
    rf"|evaluation has no creation snapshot)"
)
HOSTILE_VALUES = {
    "model-list": _mut(model=[HOST]), "repeats": _mut(repeats=HOST), "mode": _mut(mode=HOST),
    "backend-kind": _backend(kind=f"{HOST}\nforged"), "backend-extra-key": _backend(**{f"{HOST}\nforged": 1}),
    "backend-credential-url": _backend(base_url=f"http://user:{HOST}@h"),
    "tasks-mixed": _mut(tasks=[HOST, 5, {HOST: 1}]), "missing-fields": _drop("model", "tasks"),
    "malformed-json": lambda d: '{"model": "x", ' + HOST, "json-list": lambda d: json.dumps([HOST]),
    "duplicate-key-last-wins": lambda d: json.dumps(d)[:-1] + f', "model": "{HOST}"}}',
    "row-disagree": _mut(mode="reuse", source_evaluation_id=HOST),
}


@pytest.mark.parametrize("cid", sorted(HOSTILE_VALUES))
def test_rejection_text_is_a_closed_vocabulary_of_field_names(evcopy, run_once_counter, cid):
    job_id = _make_job(evcopy)
    _corrupt(evcopy, job_id, HOSTILE_VALUES[cid])
    with _client(evcopy) as client:
        listed = client.get(f"/api/v1/jobs/{job_id}").json()
        _fail_closed_via_worker(evcopy, job_id, run_once_counter)
        error = _col(evcopy, job_id, "error_message")
        assert CLOSED_VOCABULARY.fullmatch(error), error
        if listed["params_status"] == "unverifiable":
            assert CLOSED_VOCABULARY.fullmatch(listed["params_error"]), listed["params_error"]
        text = _leak_text(client, evcopy, job_id, listing=False)
        assert HOST not in text and "forged" not in text


# ------------------------- F7: a failed startup migration is retried ------------------------- #


class FlakyMigrate:
    """Stands in for db.migrate: raises ``error()`` while it is set, else delegates."""

    def __init__(self, real):
        self.real, self.error, self.calls, self._lock = real, None, 0, threading.Lock()

    def __call__(self, conn, *args, **kwargs):
        with self._lock:
            self.calls += 1
        if self.error is not None:
            raise self.error()
        return self.real(conn, *args, **kwargs)


class FakeClock:
    """The time source used by afa_api.projection (thread-safe; optional auto-step per read)."""

    def __init__(self, now=1000.0, step=0.0):
        self.now, self.step, self.reads, self._lock = now, step, 0, threading.Lock()

    def __call__(self):
        with self._lock:
            self.reads, self.now = self.reads + 1, self.now + self.step
            return self.now

    def advance(self, seconds):
        with self._lock:
            self.now += seconds


LOCKED = lambda: sqlite3.OperationalError("database is locked")  # noqa: E731
READ_URLS = ["/api/v1/overview", "/api/v1/meta", "/api/v1/leaderboard", "/api/v1/export"]


@pytest.fixture()
def flaky(monkeypatch):
    fake = FlakyMigrate(db.migrate)
    monkeypatch.setattr(db, "migrate", fake)
    return fake


@pytest.fixture()
def clock(monkeypatch):
    fake = FakeClock()  # a fake `time` module for projection only: the real one stays untouched
    monkeypatch.setattr(projection, "time", types.SimpleNamespace(monotonic=fake), raising=False)
    return fake


@pytest.mark.parametrize("first_url", ["/api/v1/overview", "/api/v1/jobs"])  # projection / middleware call site
def test_transient_startup_lock_recovers_without_a_restart(evcopy, flaky, clock, first_url):
    flaky.error = LOCKED
    with _client(evcopy) as client:
        assert client.app.state.migrate_error == "database is locked"
        if first_url == "/api/v1/overview":  # still failing: a clear 503 from BOTH call sites
            overview = client.get("/api/v1/overview")
            assert overview.status_code == 503 and overview.json() == {"error": "database migration failed: database is locked"}
            listing = client.get("/api/v1/jobs")
            assert listing.status_code == 503 and listing.json() == {"error": "control plane unavailable: database is locked"}
            health = client.get("/api/v1/healthz").json()
            assert health["status"] == "degraded" and "database is locked" in health["load_error"]
        flaky.error = None  # the lock clears; the next allowed retry heals the SAME process
        clock.advance(2.0)
        assert client.get(first_url).status_code == 200 and client.app.state.migrate_error is None
        for url in READ_URLS + ["/api/v1/jobs", "/api/v1/settings"]:
            assert client.get(url).status_code == 200, url
        assert client.get("/api/v1/healthz").json()["status"] == "ok"
        created = client.post("/api/v1/jobs", json={"model": "post-recovery", "backend": {"kind": "mock"},
                                                    "tasks": [TASK], "repeats": 1})
        assert created.status_code == 200 and created.json()["params_status"] == "available"


def test_the_retry_is_rate_limited_and_a_permanent_refusal_stays_a_clear_503(evcopy, flaky, clock):
    flaky.error = lambda: ValueError("unsupported evidence schema: refuse-me")
    urls = READ_URLS + ["/api/v1/jobs", "/api/v1/healthz", "/api/v1/settings"]

    def burst(n):
        for i in range(n):
            url = urls[i % len(urls)]
            status = client.get(url).status_code
            assert status == (200 if url == "/api/v1/healthz" else 503), (url, status)  # healthz: 200 "degraded"

    with _client(evcopy) as client:
        startup = flaky.calls
        burst(30)
        first = flaky.calls
        assert first - startup <= 1, "migrate() was retried on (nearly) every request"
        clock.advance(0.5)
        burst(30)
        assert flaky.calls == first, "retried again inside the one-second window"
        clock.advance(0.75)  # 1.25 s since the previous attempt
        burst(30)
        assert flaky.calls == first + 1, "exactly one attempt per elapsed interval"
        assert client.get("/api/v1/overview").json() == {"error": "database migration failed: unsupported evidence schema: refuse-me"}
        flaky.error = lambda: ValueError("a different refusal")  # the LATEST failure is the one reported
        clock.advance(1.25)
        assert client.get("/api/v1/overview").json() == {"error": "database migration failed: a different refusal"}
        assert client.get("/api/v1/jobs").json() == {"error": "control plane unavailable: a different refusal"}
        assert flaky.calls == first + 2 and client.get("/api/v1/healthz").json()["status"] == "degraded"


def test_concurrent_requests_trigger_a_single_retry(evcopy, monkeypatch):
    """Eight simultaneous callers, none rate-limited (the clock jumps 10 s per read): only
    the lock + the re-check under it keep this to ONE migrate() call."""
    real, release, entered, calls = db.migrate, threading.Event(), threading.Event(), []

    def gated(conn, *args, **kwargs):
        calls.append(threading.get_ident())
        entered.set()
        assert release.wait(10), "test gate never released"
        return real(conn, *args, **kwargs)

    clock = FakeClock(now=1000.0, step=10.0)
    monkeypatch.setattr(db, "migrate", gated)
    monkeypatch.setattr(projection, "time", types.SimpleNamespace(monotonic=clock), raising=False)
    app = create_app()
    app.state.db_path, app.state.migrate_error = evcopy, "database is locked"
    barrier, errors = threading.Barrier(8), []

    def caller():
        try:
            barrier.wait(10)
            projection.retry_migration_if_failed(app)
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=caller) for _ in range(8)]
    for t in threads:
        t.start()
    assert entered.wait(5), "no caller reached migrate()"
    deadline = time.monotonic() + 3.0  # bounded: let the other seven reach the lock
    while clock.reads < 9 and time.monotonic() < deadline:
        time.sleep(0.005)
    release.set()
    for t in threads:
        t.join(15)
    assert not errors and not any(t.is_alive() for t in threads)
    assert len(calls) == 1, f"{len(calls)} concurrent migrate() calls for one failure"
    assert app.state.migrate_error is None


def test_a_real_write_lock_held_at_startup_does_not_stick_forever(evcopy, monkeypatch, clock):
    """The red-team repro with no monkeypatched migrate: another connection holds the write
    lock while the lifespan migrates an un-migrated copy."""
    monkeypatch.setattr(db, "_BUSY_TIMEOUT_MS", 50)
    tables = lambda: {r[0] for r in _q(evcopy, "SELECT name FROM sqlite_master WHERE type='table'")}  # noqa: E731
    assert "evaluation_trials" not in tables()
    holder = sqlite3.connect(str(evcopy), isolation_level=None)
    holder.execute("BEGIN IMMEDIATE")
    try:
        with _client(evcopy) as client:
            assert "locked" in client.app.state.migrate_error
            resp = client.get("/api/v1/overview")
            assert resp.status_code == 503 and "locked" in resp.json()["error"]
            holder.close()  # releases the lock (rolls the transaction back)
            clock.advance(2.0)
            assert client.get("/api/v1/overview").status_code == 200 and client.app.state.migrate_error is None
            assert client.get("/api/v1/healthz").json()["status"] == "ok"
    finally:
        holder.close()
    assert "evaluation_trials" in tables()


# ------------------------- REC: startup recovery of corrupt orphans ------------------------- #

RECOVERY = {
    "temperature-NaN": _lit(temperature="NaN"), "temperature-1e999": _lit(temperature="1e999"),
    "mode-mismatch": _mut(mode="reuse", source_evaluation_id="abc"),
    # PRODUCT BUG: reclaim_stale_running does int(json.loads(params)["request_timeout_s"]) and
    # catches TypeError / ValueError / JSONDecodeError / AttributeError, but not the
    # OverflowError raised for an infinite number.
    "timeout-Infinity": _lit(request_timeout_s="Infinity"), "timeout--Infinity": _lit(request_timeout_s="-Infinity"),
    "timeout-1e999": _lit(request_timeout_s="1e999"),
}


@pytest.mark.parametrize("cid", sorted(RECOVERY))
def test_reclaim_fails_a_corrupt_orphan_closed_and_never_raises(evcopy, cid):
    job_id = _make_job(evcopy, status="running")
    _corrupt(evcopy, job_id, RECOVERY[cid])
    with contextlib.closing(db.connect(evcopy)) as conn:
        assert jobs.reclaim_stale_running(conn, recover_unlocked=True) == []
        assert not conn.in_transaction and jobs.claim_next_queued_token(conn) is None
    _assert_failed_closed(evcopy, job_id)


@pytest.mark.parametrize("cid", sorted(RECOVERY))
def test_app_lifespan_recovery_fails_closed_and_never_calls_the_factory(evcopy, run_once_counter, cid):
    job_id = _make_job(evcopy, status="running")
    _corrupt(evcopy, job_id, RECOVERY[cid])
    runs_before = _q(evcopy, "SELECT COUNT(*) FROM runs")[0][0]
    spy = SpyFactory()
    with _client(evcopy, factory=spy, auto_dispatch=True) as client:
        # BEFORE any request: a guarded request triggers the F7 retry, which clears the error
        # and would mask a recovery that crashed at startup.
        assert client.app.state.migrate_error is None, client.app.state.migrate_error
        assert _wait_status(client, job_id, {"failed", "succeeded"})["status"] == "failed"
    _assert_failed_closed(evcopy, job_id, spy, run_once_counter, runs_before)


@pytest.mark.parametrize("cid", ["temperature-NaN", "timeout-Infinity", "timeout-1e999"])
def test_one_corrupt_orphan_does_not_block_recovery_of_a_valid_orphan(evcopy, cid):
    """The raise aborts the recovery loop, so every orphan after the corrupt one is lost."""
    corrupt = _make_job(evcopy, model="corrupt-orphan", status="running")
    valid = _make_job(evcopy, model="valid-orphan", kind="mock", repeats=1, status="running")
    _corrupt(evcopy, corrupt, RECOVERY[cid])
    with contextlib.closing(db.connect(evcopy)) as conn:
        assert jobs.reclaim_stale_running(conn, recover_unlocked=True) == [valid]
        assert jobs.get_job(conn, valid).status == "queued"
    _assert_failed_closed(evcopy, corrupt)
