"""Red-team regression tests: provenance and evidence classification (F2, F3, F6, F10, F16, F19).

Guards the fixes of commit 3ef58a4 through evidence.classify / read_provenance, the loaders, the
HTTP API, the database and report_combined. Tests marked ``PRODUCT BUG`` assert the CORRECT
behaviour and currently FAIL. Every database is a tmp_path copy; a module guard asserts that
reports/runs.sqlite is byte-identical at the end.
"""
from __future__ import annotations

import contextlib
import functools
import hashlib
import itertools
import json
import shutil
import sqlite3
import threading
import time
import urllib.parse
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

import afa_runner as afa
from afa_api import db, evidence, jobs, worker
from afa_api.main import create_app
from afa_api.schemas import Backend, JobCreate, JobParams
from afa_api.store_load import load_stores
from afa_kernel.types import RunScore, RunStatus
from afa_runner.pipeline import RunRecord

TASK = "fix-binary-search"
ORACLE, NOOP = "oracle (synthetic baseline)", "noop (synthetic baseline)"
LEGACY_MODELS = {"deepseek-coder:6.7b", "gemma2:2b", "llama3.2:latest",
                 "qwen2.5-coder:3b", "qwen2.5-coder:7b", "qwen3.5:9b"}
EVIDENCE_SHA = "42b6dad85ee662d6d5d7f75ffbda5a3b95d50837837f81c875730a8987838ced"
NO_EXCLUSIONS = {"synthetic_runs": 0, "synthetic_models": [],
                 "provenance_conflict_runs": 0, "unaccounted_runs": 0}


@pytest.fixture(scope="module", autouse=True)
def _evidence_db_is_byte_identical_across_this_module():
    sha = lambda: hashlib.sha256(db.EVIDENCE_DB_PATH.read_bytes()).hexdigest()  # noqa: E731
    assert sha() == EVIDENCE_SHA
    yield
    assert sha() == EVIDENCE_SHA, "committed evidence DB changed"


# ---- helpers ---------------------------------------------------------------- #


def _enc(value: str) -> str:
    return urllib.parse.quote(value, safe="")


def _fresh_copy(path: Path) -> Path:
    """A migrated (hence WAL) working copy of the committed evidence."""
    shutil.copy(db.EVIDENCE_DB_PATH, path)
    with contextlib.closing(db.connect(path)) as conn:
        db.migrate(conn)
    return path


def _rec(agent: str, idx: int = 0, *, passed: bool = True) -> RunRecord:
    score = RunScore(RunStatus.VALID, int(passed), float(passed), 1.0, {}, float(passed), passed, False)
    return RunRecord(task_id=TASK, task_version="1.0.0", agent=agent, idx=idx, status=RunStatus.VALID,
                     score=score, files_changed=1, lines_added=1, lines_removed=0,
                     transcript_hash=f"sha256:redteam-{agent}-{idx}-{passed}", duration_ms=1)


def _save(path: Path, record: RunRecord, **kw) -> int:
    with contextlib.closing(afa.SqliteRunStore(path)) as store:
        return store.save_run(record, **kw)


def _new_job(path: Path, model: str, kind: str = "mock") -> str:
    params = JobCreate(model=model, backend=Backend(kind=kind), tasks=[TASK], repeats=1)
    with contextlib.closing(db.connect(path)) as conn:
        return jobs.create_job(conn, params).id


def _rows(path: Path, sql: str, args=()):
    with contextlib.closing(sqlite3.connect(f"file:{path}?mode=ro", uri=True)) as conn:
        return [tuple(r) for r in conn.execute(sql, args).fetchall()]


def _exec(path: Path, sql: str, args=()) -> None:
    with contextlib.closing(sqlite3.connect(str(path))) as conn, conn:  # `with conn` commits
        conn.execute(sql, args)


@contextlib.contextmanager
def _client(path: Path, *, factory=None, auto_dispatch: bool = False):
    app = create_app()
    app.state.db_path = path
    if factory is not None:
        app.state.agent_factory = factory
    app.state.auto_dispatch = auto_dispatch
    with TestClient(app) as client:
        yield client


def _wait_terminal(client: TestClient, job_id: str, timeout: float = 90.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        body = client.get(f"/api/v1/jobs/{job_id}").json()
        if body["status"] in ("succeeded", "failed", "canceled"):
            return body
        time.sleep(0.02)
    raise AssertionError(f"job {job_id} did not reach a terminal state")


def _bookends(store) -> dict[str, tuple]:
    return {e.agent: (e.n, e.pass_rate, e.wilson_low, e.wilson_high)
            for e in afa.leaderboard(store) if e.agent in evidence.RESERVED_AGENT_NAMES}


def _report(path: Path, scope: str | None = None):
    import report_combined

    html, store, real_counts = report_combined.build_report(path, evidence_scope=scope)
    with contextlib.closing(store):
        return html, real_counts, _bookends(store)


@pytest.fixture(scope="module")
def pristine_bookends(tmp_path_factory) -> dict[str, tuple]:
    """The oracle/noop bookend numbers on untouched committed evidence."""
    path = tmp_path_factory.mktemp("pristine") / "pristine.sqlite"
    shutil.copy(db.EVIDENCE_DB_PATH, path)
    bookends = _report(path)[2]
    assert bookends[ORACLE][:2] == (120, 1.0) and bookends[NOOP][:2] == (120, 0.0)
    return bookends


# ---- 1. evidence.classify as a truth table (F3, F19) ------------------------ #

_KNOWN = ("mock", "ollama", "openai_compat")
_CLASS = {"mock": "synthetic", "ollama": "real", "openai_compat": "real"}


def _contract(run, snap, params, job_id):
    """(class, provider_source, backend_kind) from the DOCUMENTED resolution order
    (evidence.py module docstring), written independently of ``classify``."""
    if run is not None and run not in _KNOWN:
        return "conflict", "run", None  # unknown provider string
    job_kind = snap if snap in _KNOWN else (params if params in _KNOWN else None)
    if run is not None and job_kind is not None and run != job_kind:
        return "conflict", "run", run  # own provider contradicts its evaluation
    if run is not None:
        return _CLASS[run], "run", run
    if job_kind is not None:
        return _CLASS[job_kind], "evaluation", job_kind
    if job_id is not None:
        return "conflict", "none", None  # app-created run, nothing attestable
    return "legacy", "none", None


NAMED_ROWS = [  # id, (run, snapshot, params, job_id), (class, provider_source, backend_kind)
    ("legacy-no-job", (None, None, None, None), ("legacy", "none", None)),
    ("F3-job-with-nothing-attestable", (None, None, None, "j"), ("conflict", "none", None)),
    ("F3-params-mock", (None, None, "mock", "j"), ("synthetic", "evaluation", "mock")),
    ("F3-params-ollama", (None, None, "ollama", "j"), ("real", "evaluation", "ollama")),
    ("snapshot-beats-params", (None, "ollama", "mock", "j"), ("real", "evaluation", "ollama")),
    ("junk-snapshot-falls-through-to-params", (None, "bogus", "mock", "j"), ("synthetic", "evaluation", "mock")),
    ("F19-unknown-snapshot-kind-does-not-raise", (None, "OLLAMA", None, "j"), ("conflict", "none", None)),
    ("run-mock", ("mock", None, None, "j"), ("synthetic", "run", "mock")),
    ("run-contradicts-snapshot", ("mock", "ollama", None, "j"), ("conflict", "run", "mock")),
    ("run-contradicts-params-when-snapshot-junk", ("ollama", "bogus", "mock", "j"), ("conflict", "run", "ollama")),
    ("run-provider-unknown", ("hosted", None, None, None), ("conflict", "run", None)),
]


@pytest.mark.parametrize("args,expected", [pytest.param(a, e, id=i) for i, a, e in NAMED_ROWS])
def test_classify_named_rows(args, expected):
    run, snap, params, job_id = args
    prov = evidence.classify(7, job_id, run, snap, params)
    assert (prov.evidence_class, prov.provider_source, prov.backend_kind) == expected
    assert (prov.run_id, prov.job_id) == (7, job_id)
    assert expected == _contract(*args)  # the independent oracle agrees with the table


def test_classify_full_product_matches_the_documented_contract_and_never_raises():
    kinds = (None, *_KNOWN, "bogus")
    bad = []
    for run, snap, params, job_id in itertools.product(kinds, kinds, (None, "mock", "ollama", "bogus"), (None, "j")):
        prov = evidence.classify(1, job_id, run, snap, params)  # F19: must not raise
        got, want = (prov.evidence_class, prov.provider_source, prov.backend_kind), _contract(run, snap, params, job_id)
        # the safety property: the benchmark scope never holds a mock run, a contradiction,
        # or an app-created run whose provider cannot be attested
        if got != want or (prov.evidence_class in evidence.SCOPES["benchmark"]) != (want[0] in ("real", "legacy")):
            bad.append((run, snap, params, job_id, got, want))
    assert not bad, bad[:5]
    assert evidence.UNATTESTED_PROVENANCE.evidence_class == "conflict"  # a run missing from a map


# ---- 2. read_provenance on databases of every shape (F3) -------------------- #

P = lambda kind: json.dumps({"model": "m", "backend": {"kind": kind}})  # noqa: E731
S = lambda kind: json.dumps({"backend": {"kind": kind}})  # noqa: E731
LEGACY, UNATT = ("legacy", "none"), ("conflict", "none")

PROVENANCE_DBS = [  # id, runs extra columns, runs, jobs extra columns (None: no table), jobs, expected
    ("no-runs-table", None, [], None, [], {}),
    ("runner-only-db-without-evaluation-tables", ("job_id", "backend_kind"),
     [(1, "j", None), (2, None, None), (3, "j", "mock"), (4, None, "ollama")], None, [],
     {1: UNATT, 2: LEGACY, 3: ("synthetic", "run"), 4: ("real", "run")}),
    ("master-era-params-json-only", ("job_id",),
     [(1, "m"), (2, "o"), (3, "corrupt"), (4, "array"), (5, "ghost"), (6, None), (7, "wrongtype")], ("params_json",),
     [("m", P("mock")), ("o", P("ollama")), ("corrupt", "{corrupt"), ("array", "[]"),
      ("wrongtype", json.dumps({"backend": "mock"}))],
     {1: ("synthetic", "evaluation"), 2: ("real", "evaluation"), 3: UNATT, 4: UNATT, 5: UNATT, 6: LEGACY, 7: UNATT}),
    ("snapshot-json-only", ("job_id",), [(1, "m"), (2, "o"), (3, "junk"), (4, "unk")], ("snapshot_json",),
     [("m", S("mock")), ("o", S("openai_compat")), ("junk", "{nope"), ("unk", S("Mock??"))],
     {1: ("synthetic", "evaluation"), 2: ("real", "evaluation"), 3: UNATT, 4: UNATT}),
    ("jobs-table-with-only-an-id", ("job_id",), [(1, "j"), (2, None)], (), [("j",)], {1: UNATT, 2: LEGACY}),
    ("snapshot-wins-junk-snapshot-falls-back-to-params", ("job_id",), [(1, "a"), (2, "b"), (3, "c")],
     ("snapshot_json", "params_json"), [("a", S("ollama"), P("mock")), ("b", "{nope", P("mock")), ("c", None, None)],
     {1: ("real", "evaluation"), 2: ("synthetic", "evaluation"), 3: UNATT}),
]


def _provenance_db(runs_cols, runs, jobs_cols, job_rows) -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    for table, key, cols, rows in (("runs", "id INTEGER PRIMARY KEY", runs_cols, runs),
                                   ("evaluation_jobs", "id TEXT PRIMARY KEY", jobs_cols, job_rows)):
        if cols is not None:
            conn.execute(f"CREATE TABLE {table} ({', '.join([key, *cols])})")
            conn.executemany(f"INSERT INTO {table} VALUES ({','.join('?' * (1 + len(cols)))})", rows)
    return conn


@pytest.mark.parametrize("case", [pytest.param(c[1:], id=c[0]) for c in PROVENANCE_DBS])
def test_read_provenance_across_database_shapes(case):
    runs_cols, runs, jobs_cols, job_rows, expected = case
    first = [runs[0][0]] if runs else []
    with contextlib.closing(_provenance_db(runs_cols, runs, jobs_cols, job_rows)) as conn:
        found = evidence.read_provenance(conn)
        narrowed = evidence.read_provenance(conn, first)  # the run_ids filter narrows, never drops
        assert evidence.read_provenance(conn, []) == {}
    assert {rid: (p.evidence_class, p.provider_source) for rid, p in found.items()} == expected
    assert {rid: found[rid] for rid in first} == narrowed


# ---- 3. F3 end to end: master-era jobs (params_json, no snapshot, no run kind) #

F3 = {"mock": ("synthetic", "evaluation"), "ollama": ("real", "evaluation"),
      "corrupt": ("conflict", "none"), "ghost": ("conflict", "none")}


@pytest.fixture(scope="module")
def master_era(tmp_path_factory):
    """Runs written by the pre-snapshot code: job_id set, backend_kind NULL, and a job
    row that has only params_json (snapshot_json NULL, mode 'legacy')."""
    path = _fresh_copy(tmp_path_factory.mktemp("f3") / "master-era.sqlite")
    world = {"path": path, "runs": {}, "models": {k: f"f3-{k}-model" for k in F3}}
    for key, kind in (("mock", "mock"), ("ollama", "ollama"), ("corrupt", "mock")):
        job_id = _new_job(path, world["models"][key], kind)
        _exec(path, "UPDATE evaluation_jobs SET snapshot_json=NULL, mode='legacy', status='succeeded' WHERE id=?", (job_id,))
        if key == "corrupt":
            _exec(path, "UPDATE evaluation_jobs SET params_json='{corrupt' WHERE id=?", (job_id,))
        world["runs"][key] = _save(path, _rec(world["models"][key]), job_id=job_id)
    world["runs"]["ghost"] = _save(path, _rec(world["models"]["ghost"]), job_id="no-such-job")
    assert _rows(path, "SELECT COUNT(*) FROM runs WHERE job_id IS NOT NULL AND backend_kind IS NULL") == [(4,)]
    assert _rows(path, "SELECT COUNT(*) FROM evaluation_jobs WHERE snapshot_json IS NOT NULL") == [(0,)]
    return world


@pytest.mark.parametrize("key", list(F3))
def test_f3_master_era_runs_are_classified_from_params_never_legacy(master_era, key):
    run_id = master_era["runs"][key]
    with contextlib.closing(db.connect_readonly(master_era["path"])) as conn:
        prov = evidence.read_provenance(conn, [run_id])[run_id]
    assert (prov.evidence_class, prov.provider_source) == F3[key]
    with _client(master_era["path"]) as client:
        body = client.get(f"/api/v1/runs/{run_id}").json()
    assert (body["evidence_class"], body["provider_source"]) == F3[key]


def test_f3_master_era_mock_runs_stay_out_of_the_default_scope_and_the_report(master_era):
    path, models = master_era["path"], master_era["models"]
    with _client(path) as client:
        ov = client.get("/api/v1/overview").json()
        real = client.get("/api/v1/overview?evidence=real").json()
        syn = client.get("/api/v1/overview?evidence=synthetic").json()
    assert set(ov["models"]) == LEGACY_MODELS | {models["ollama"]}
    assert ov["evidence_counts"][models["ollama"]]["current_by_class"] == {"real": 1}
    assert ov["excluded"] == {"synthetic_runs": 1, "synthetic_models": [models["mock"]],
                              "provenance_conflict_runs": 2, "unaccounted_runs": 0}
    assert real["models"] == [models["ollama"]] and syn["models"] == [models["mock"]]
    html, real_counts, _ = _report(path)
    assert set(real_counts) == LEGACY_MODELS | {models["ollama"]}
    assert not any(models[k] in html for k in ("mock", "corrupt", "ghost"))
    assert "3 run(s) outside this scope are excluded" in html
    assert set(_report(path, "synthetic")[1]) == {models["mock"]}


# ---- 4. F2: provenance and runs are read in ONE snapshot -------------------- #

# a fresh model name / an existing legacy model (its CURRENT (n_runs, n_tasks) must not move)
RACE_MODELS = {"race-model": None, "qwen3.5:9b": (30, 6)}


def _consume_load_stores(path, model):
    with contextlib.closing(load_stores(path)) as stores:
        # no run carries the fallback provenance used for "not in the provenance map"
        assert all(r.provenance.run_id == r.record.run_id for r in stores.runs)
        return stores.excluded, stores.real_counts.get(model)


def _consume_report(path, model):
    html, real_counts, _ = _report(path)
    assert (model != "race-model" or model not in html) and "outside this scope" not in html
    return NO_EXCLUSIONS, real_counts.get(model)


@pytest.mark.parametrize("consume", [_consume_load_stores, _consume_report], ids=["load_stores", "report_combined"])
@pytest.mark.parametrize("model,point", [  # (fresh name, before-first-run-load) is vacuous: agents() is listed first
    ("race-model", "after-provenance-read"), ("qwen3.5:9b", "after-provenance-read"),
    ("qwen3.5:9b", "before-first-run-load")])
def test_f2_run_committed_mid_load_never_enters_the_default_scope(tmp_path, monkeypatch, model, point, consume):
    path = _fresh_copy(tmp_path / "race.sqlite")  # WAL: a writer may commit under a held read snapshot
    job_id, fired = _new_job(path, model), []

    def inject():  # a worker-style commit of a mock run on a second connection, exactly once
        if not fired:
            fired.append(_save(path, _rec(model, 99), job_id=job_id, backend_kind="mock"))

    if point == "after-provenance-read":
        original = evidence.read_provenance

        def hooked(raw, run_ids=None):
            out = original(raw, run_ids)
            inject()
            return out

        monkeypatch.setattr(evidence, "read_provenance", hooked)
    else:
        original = afa.SqliteRunStore.load_runs

        def hooked(self, *args, **kwargs):
            inject()
            return original(self, *args, **kwargs)

        monkeypatch.setattr(afa.SqliteRunStore, "load_runs", hooked)

    excluded, counts = consume(path, model)
    monkeypatch.undo()
    assert len(fired) == 1, "the mid-load commit never happened (test would be vacuous)"
    assert counts == RACE_MODELS[model]  # the mock run did not enter the benchmark aggregate as legacy
    # never classified from a stale snapshot: not conflict/legacy; invisible or, at worst, synthetic
    assert excluded["provenance_conflict_runs"] == 0 and excluded["unaccounted_runs"] == 0
    assert excluded["synthetic_runs"] in (0, 1)
    with contextlib.closing(load_stores(path)) as fresh:  # the run is real committed evidence: a fresh load excludes it
        assert fresh.real_counts.get(model) == RACE_MODELS[model]
        assert fresh.excluded["provenance_conflict_runs"] == 0
        assert fresh.excluded["synthetic_runs"] == 1 and fresh.excluded["synthetic_models"] == [model]
    assert _report(path)[1].get(model) == RACE_MODELS[model]


@pytest.mark.parametrize("consumer", ["load_stores", "report_combined"])
def test_f2_a_run_missing_from_the_provenance_map_is_unattested_not_legacy(tmp_path, monkeypatch, consumer):
    path = _fresh_copy(tmp_path / "missing.sqlite")
    victim = "gemma2:2b"
    victim_ids = {r[0] for r in _rows(path, "SELECT id FROM runs WHERE agent=?", (victim,))}
    assert len(victim_ids) == 120
    original = evidence.read_provenance

    def hooked(raw, run_ids=None):
        out = original(raw, run_ids)
        for run_id in victim_ids:
            out.pop(run_id, None)
        return out

    monkeypatch.setattr(evidence, "read_provenance", hooked)
    if consumer == "load_stores":
        with contextlib.closing(load_stores(path)) as stores:
            assert set(stores.models) == set(stores.real_counts) == LEGACY_MODELS - {victim}
            assert stores.excluded["provenance_conflict_runs"] == 120
            assert stores.excluded_cells[(victim, TASK)]["provenance_conflict_runs"] > 0
    else:
        html, real_counts, _ = _report(path)
        assert set(real_counts) == LEGACY_MODELS - {victim} and victim not in html
        assert "120 run(s) outside this scope are excluded" in html


# ---- 5. F6 / F16: factories that declare nothing (or lie), driven via POST /jobs #


def _plain(model, task, params):  # a wrapper that lost the .backend_kind attribute
    return worker.mock_agent_factory(model, task, params)


def _declaring(kind):
    def factory(model, task, params):
        return worker.mock_agent_factory(model, task, params)

    factory.backend_kind = kind
    return factory


FACTORY_PLAN = {  # key -> (requested backend kind, factory that actually runs)
    "plain": ("ollama", _plain),
    "partial": ("openai_compat", functools.partial(worker.mock_agent_factory)),
    "hosted": ("ollama", _declaring("hosted")),  # declared kind outside BACKEND_KINDS
    "liar": ("ollama", _declaring("mock")),  # runs the mock, asked for ollama
    "cross": ("openai_compat", _declaring("ollama")),
    "honest": ("ollama", _declaring("ollama")),
}
UNDECLARED, DECLARED_WRONG = ["plain", "partial", "hosted"], ["liar", "cross"]


def _post_job(client, model, kind, **extra) -> str:
    body = {"model": model, "backend": {"kind": kind}, "tasks": [TASK], "repeats": 1, **extra}
    response = client.post("/api/v1/jobs", json=body)
    assert response.status_code == 200, response.text
    return response.json()["id"]


@pytest.fixture(scope="module")
def factory_world(tmp_path_factory):
    path = _fresh_copy(tmp_path_factory.mktemp("f6") / "factory-world.sqlite")
    world = {"path": path, "jobs": {}, "models": {k: f"f6-{k}-model" for k in FACTORY_PLAN}}
    for key, (kind, factory) in FACTORY_PLAN.items():
        with _client(path, factory=factory, auto_dispatch=True) as client:
            world["jobs"][key] = _post_job(client, world["models"][key], kind)
            assert _wait_terminal(client, world["jobs"][key])["status"] == "succeeded"
    with _client(path, factory=_plain, auto_dispatch=True) as client:  # F16: reuse the liar's evidence
        world["reuse"] = _post_job(client, world["models"]["liar"], "ollama", mode="reuse",
                                   source_evaluation_id=world["jobs"]["liar"])
        assert _wait_terminal(client, world["reuse"])["status"] == "succeeded"
    for thread in threading.enumerate():
        if thread.name.startswith("afa-job-"):
            thread.join(30)
    return world


@pytest.fixture(scope="module")
def fclient(factory_world):
    with _client(factory_world["path"]) as client:
        yield client


def _only_run(world, key) -> int:
    return _rows(world["path"], "SELECT id FROM runs WHERE job_id=?", (world["jobs"][key],))[0][0]


def _trial(client, job_id) -> dict:
    return client.get(f"/api/v1/jobs/{job_id}/report.json").json()["trials"][0]


@pytest.mark.parametrize("key", UNDECLARED)
def test_f6_an_undeclared_factory_stores_no_provider_and_is_never_attested(factory_world, fclient, key):
    """Red-team vector: an injected factory that omits .backend_kind. The requested kind is never stamped."""
    job_id = factory_world["jobs"][key]
    assert _rows(factory_world["path"], "SELECT backend_kind FROM runs WHERE job_id=?", (job_id,)) == [(None,)]
    trial = _trial(fclient, job_id)
    assert trial["backend_kind"] is None and trial["provenance"] == "unknown"  # never "consistent"
    assert "integrity_error" not in trial
    run = fclient.get(f"/api/v1/runs/{_only_run(factory_world, key)}").json()
    assert run["provider_source"] == "evaluation"  # derived from the request, NOT attested by the run


@pytest.mark.parametrize("key,stored,snapshot", [("liar", "mock", "ollama"), ("cross", "ollama", "openai_compat")])
def test_f6_a_declared_kind_that_contradicts_the_snapshot_is_a_conflict(factory_world, fclient, key, stored, snapshot):
    job_id = factory_world["jobs"][key]
    assert _rows(factory_world["path"], "SELECT backend_kind FROM runs WHERE job_id=?", (job_id,)) == [(stored,)]
    trial = _trial(fclient, job_id)
    assert trial["backend_kind"] == stored and trial["provenance"] == "mismatch"
    assert snapshot in trial["integrity_error"] and trial.get("comparability") is None
    run = fclient.get(f"/api/v1/runs/{_only_run(factory_world, key)}").json()
    assert (run["evidence_class"], run["provider_source"], run["backend_kind"]) == ("conflict", "run", stored)
    assert factory_world["models"][key] not in fclient.get("/api/v1/overview").json()["models"]


def test_f6_control_a_truthful_declaration_is_consistent_comparable_and_ranked(factory_world, fclient):
    trial = _trial(fclient, factory_world["jobs"]["honest"])
    assert (trial["backend_kind"], trial["provenance"], trial["comparability"]) == ("ollama", "consistent", "comparable")
    ov = fclient.get("/api/v1/overview").json()
    assert ov["real_counts"][factory_world["models"]["honest"]] == {"n_runs": 1, "n_tasks": 1}
    assert ov["excluded"]["provenance_conflict_runs"] == len(DECLARED_WRONG) and ov["excluded"]["synthetic_runs"] == 0


def test_f16_reuse_of_a_conflicting_source_keeps_the_conflict_visible_per_trial(factory_world, fclient):
    """Job-level evidence_class comes from the snapshot's REQUESTED backend, not from the trials'
    run provenance (pinned as currently implemented); the per-trial surfaces carry the conflict."""
    source, reuse = factory_world["jobs"]["liar"], factory_world["reuse"]
    for job_id in (source, reuse):
        job = fclient.get(f"/api/v1/jobs/{job_id}").json()
        assert (job["status"], job["evidence_class"], job["backend_kind"]) == ("succeeded", "real", "ollama")
    reused = fclient.get(f"/api/v1/jobs/{reuse}").json()
    assert reused["mode"] == "reuse" and reused["counters"]["reused_runs"] == 1
    report = fclient.get(f"/api/v1/jobs/{reuse}/report.json").json()
    trial = report["trials"][0]
    assert trial["evidence_state"] == "reused" and trial["run_id"] == _only_run(factory_world, "liar")
    assert trial["provenance"] == "mismatch" and trial["backend_kind"] == "mock"
    assert trial.get("comparability") is None and trial["integrity_error"]
    limitations = " ".join(report["limitations"]).lower()
    assert "provenance integrity error" in limitations and "reuses evidence" in limitations
    assert "Provenance: `mismatch`" in fclient.get(f"/api/v1/jobs/{reuse}/report.md").text
    # reuse creates no second run: the conflict is counted once, neither laundered nor doubled
    assert _rows(factory_world["path"], "SELECT COUNT(*) FROM runs WHERE agent=?", (factory_world["models"]["liar"],)) == [(1,)]
    assert fclient.get("/api/v1/overview").json()["excluded"]["provenance_conflict_runs"] == len(DECLARED_WRONG)


@pytest.mark.parametrize("snapshot,params,expected", [
    (None, None, ("ollama", "real")),  # snapshot and params both usable
    (None, "mock", ("ollama", "real")),  # the snapshot wins over params
    ("{nope", "mock", ("mock", "synthetic")),  # junk snapshot falls back to params
    ('{"backend": {"kind": "Mock??"}}', "{nope", (None, "unknown")),  # nothing usable
])
def test_f16_job_level_evidence_class_comes_from_snapshot_then_params(tmp_path, snapshot, params, expected):
    path = _fresh_copy(tmp_path / "jobclass.sqlite")
    job_id = _new_job(path, "job-class-model", "ollama")
    if snapshot is not None:
        _exec(path, "UPDATE evaluation_jobs SET snapshot_json=? WHERE id=?", (snapshot, job_id))
    if params is not None:
        stored = json.loads(_rows(path, "SELECT params_json FROM evaluation_jobs WHERE id=?", (job_id,))[0][0])
        text = json.dumps({**stored, "backend": {"kind": "mock"}}) if params == "mock" else params
        _exec(path, "UPDATE evaluation_jobs SET params_json=? WHERE id=?", (text, job_id))
    with contextlib.closing(db.connect(path)) as conn:
        job = jobs.get_job(conn, job_id)
    assert (job.backend_kind, job.evidence_class) == expected


# ---- 6. F10: names reserved for the synthetic baselines --------------------- #


@pytest.mark.parametrize("name", [ORACLE, NOOP])
def test_f10_reserved_baseline_names_are_refused_at_job_creation(tmp_path, name):
    path = _fresh_copy(tmp_path / "reserved-create.sqlite")
    with _client(path) as client:
        for kind in ("mock", "ollama"):
            body = {"model": name, "backend": {"kind": kind}, "tasks": [TASK], "repeats": 1}
            response = client.post("/api/v1/jobs", json=body)
            assert 400 <= response.status_code < 500 and "reserved" in response.text
        assert _post_job(client, "oracle", "mock")  # only the exact reserved names are refused
    assert _rows(path, "SELECT COUNT(*) FROM evaluation_jobs WHERE params_json LIKE '%synthetic baseline%'") == [(0,)]
    assert _rows(path, "SELECT COUNT(*) FROM runs WHERE agent=?", (name,)) == [(0,)]
    with pytest.raises(ValidationError):
        JobCreate(model=name, backend=Backend(kind="ollama"), tasks=[TASK], repeats=1)
    with pytest.raises(ValidationError):
        JobParams(model=name, tasks=[TASK])


@pytest.fixture(scope="module")
def reserved_db(tmp_path_factory):
    """Runs persisted under the bookend names by a writer that bypassed job creation."""
    path = _fresh_copy(tmp_path_factory.mktemp("f10") / "reserved.sqlite")
    plan = [(ORACLE, 0, False, None), (ORACLE, 1, False, "mock"), (ORACLE, 2, False, "ollama"),
            (NOOP, 0, True, None), (NOOP, 1, True, "openai_compat")]
    return {"path": path, "ids": {(agent, idx): _save(path, _rec(agent, idx, passed=passed), backend_kind=kind)
                                  for agent, idx, passed, kind in plan}}


def test_f10_persisted_reserved_name_runs_are_conflicts_excluded_and_counted(reserved_db):
    with _client(reserved_db["path"]) as client:
        ov, meta = client.get("/api/v1/overview").json(), client.get("/api/v1/meta").json()
        cell = client.get(f"/api/v1/cell/{_enc(ORACLE)}/{TASK}").json()
        cell_all = client.get(f"/api/v1/cell/{_enc(ORACLE)}/{TASK}?evidence=all").json()
    assert ov["excluded"] == {"synthetic_runs": 0, "synthetic_models": [], "provenance_conflict_runs": 5,
                              "unaccounted_runs": 0}  # every reserved-name run is a conflict, whatever its provider
    assert meta["excluded"]["provenance_conflict_runs"] == 5
    assert set(ov["models"]) == LEGACY_MODELS and not {ORACLE, NOOP} & set(ov["real_counts"])
    assert not [e for e in ov["leaderboard"] if e["agent"] in (ORACLE, NOOP)]
    assert all(v == {"n_runs": 30, "n_tasks": 6} for v in ov["real_counts"].values())
    assert cell["state"] == "synthetic" and cell["runs"] == [] and cell["excluded"]["provenance_conflict_runs"] == 3
    assert {r["evidence_class"] for r in cell_all["runs"]} == {"conflict"}  # visible on request, labelled


@pytest.mark.parametrize("scope", sorted(evidence.SCOPES))
def test_f10_report_bookends_are_unaffected_in_every_scope(reserved_db, pristine_bookends, scope):
    _html, real_counts, bookends = _report(reserved_db["path"], scope)
    assert bookends == pristine_bookends and not {ORACLE, NOOP} & set(real_counts)


@pytest.mark.parametrize("scope", sorted(evidence.SCOPES))
def test_f10_app_loader_matches_the_canonical_report_in_every_scope(reserved_db, pristine_bookends, scope):
    """PRODUCT BUG (scope 'all' only): store_load reclassifies a reserved-name run as CONFLICT, but
    CONFLICT is inside SCOPES['all'], so the rows are loaded and blend into the bookends (oracle 123
    runs @ 0.976 instead of 120 @ 1.0; the name shows in models/real_counts). report_combined
    excludes them in every scope and store_load's docstring promises to match it."""
    with contextlib.closing(load_stores(reserved_db["path"], evidence_scope=scope)) as stores:
        assert not {ORACLE, NOOP} & set(stores.models) and not {ORACLE, NOOP} & set(stores.real_counts)
        assert _bookends(stores.full) == pristine_bookends


@pytest.mark.parametrize("scope", sorted(evidence.SCOPES))
@pytest.mark.parametrize("agent,functional_pass", [(ORACLE, True), (NOOP, False)])
def test_f10_tuple_route_serves_the_bookend_never_a_persisted_impostor(reserved_db, scope, agent, functional_pass):
    """PRODUCT BUG (scope 'all' only): /run/{bookend}/{task}/0?evidence=all serves the persisted
    reserved-name run (a failing 'oracle', a passing 'noop') as if it were the synthetic bookend."""
    with _client(reserved_db["path"]) as client:
        body = client.get(f"/api/v1/run/{_enc(agent)}/{TASK}/0?evidence={scope}").json()
    assert body["found"] and body["synthetic"] and body["score"]["functional_pass"] is functional_pass


@pytest.mark.parametrize("agent,idx", [(ORACLE, 0), (ORACLE, 1), (ORACLE, 2), (NOOP, 0), (NOOP, 1)])
def test_f10_forensic_route_labels_a_reserved_name_run_as_a_conflict(reserved_db, agent, idx):
    """PRODUCT BUG (low): evidence.py documents a run persisted under a reserved name as a CONFLICT and
    the aggregate/cell views comply, but /runs/{id} labels it from its own provider alone ('real' /
    'legacy'), because read_provenance never selects runs.agent."""
    with _client(reserved_db["path"]) as client:
        body = client.get(f"/api/v1/runs/{reserved_db['ids'][(agent, idx)]}").json()
    assert body["evidence_class"] == "conflict"


# ---- 7. F19: unknown kinds and scopes on the read routes -------------------- #


def test_f19_tuple_route_rejects_an_unknown_scope_but_the_forensic_id_route_ignores_it(factory_world, fclient):
    """As implemented: /run/... validates ?evidence= (400) whereas /runs/{id} is scope-independent (200)."""
    model, run_id = factory_world["models"]["honest"], _only_run(factory_world, "honest")
    bad = fclient.get(f"/api/v1/run/{_enc(model)}/{TASK}/0?evidence=bogus")
    assert bad.status_code == 400 and all(scope in bad.json()["error"] for scope in evidence.SCOPES)
    for scope in evidence.SCOPES:
        assert fclient.get(f"/api/v1/run/{_enc(model)}/{TASK}/0?evidence={scope}").status_code == 200
    ok = fclient.get(f"/api/v1/runs/{run_id}?evidence=bogus")
    assert ok.status_code == 200 and ok.json()["run_id"] == run_id
