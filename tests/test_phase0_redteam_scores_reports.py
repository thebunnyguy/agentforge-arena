"""Red-team regression suite A (fixes from commit 3ef58a4): score formula, reports, bad rows.

F1 a second run_scores formula row must not double-count a run (aggregates, ?version= views,
run routes, evaluation counters/reports; a pre-formula_version schema stays readable); F5
regenerate never lets a non-default evidence scope replace the canonical report and every
report states its scope + counts; F9 an unrecognised run status fails closed AND names the
row; F13 runs the loader cannot see are counted in excluded.unaccounted_runs; plus the
score-formula / reserved-name constants must agree. Only COPIES of reports/runs.sqlite are
written (a module guard checks the committed file is byte-identical afterwards). Tests marked
"SUSPECTED PRODUCT BUG" assert the CORRECT behaviour and currently FAIL.
"""
from __future__ import annotations

import contextlib
import hashlib
import html
import json
import re
import shutil
import sqlite3
import urllib.parse
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import afa_runner as afa
from afa_api import db, evidence, jobs, store_load, worker
from afa_api.main import create_app
from afa_api.schemas import Backend, JobCreate, JobParams
from afa_kernel.types import RunScore, RunStatus
from afa_runner import store as runner_store
from afa_runner.pipeline import RunRecord

import report_combined  # noqa: E402  (examples/ is put on sys.path by afa_api.store_load)

REPO = Path(__file__).resolve().parents[1]
EVIDENCE_SHA256 = "42b6dad85ee662d6d5d7f75ffbda5a3b95d50837837f81c875730a8987838ced"
TASK, SANITIZE, MODEL = "fix-binary-search", "sanitize-filename", "gemma2:2b"  # MODEL: committed
PROBE, F9_AGENT, F13_AGENT, F5_MOCK = "f1-probe", "f9-agent", "f13-agent", "f5-mock-only"
SCOPES = ("benchmark", "real", "synthetic", "all")

# The pinned formula (getattr: lets this module also import on pre-3ef58a4 trees, where the
# constants test then fails instead of the whole module erroring at collection).
PINNED = getattr(evidence, "SCORE_FORMULA_VERSION", "v0.1")
# Other formulas sorting BEFORE and AFTER the pinned one: neither "first row wins" nor
# "last row wins" readers can pass by luck.
EARLIER, LATER = f"0-{PINNED}", f"{PINNED}-rescored"
TASK_CURRENT = {
    item["id"]: json.loads((REPO / "tasks" / item["id"] / "task.json").read_text())["version"]
    for item in json.loads((REPO / "tasks" / "manifest.json").read_text())
}


@pytest.fixture(scope="module", autouse=True)
def _committed_evidence_is_byte_identical():
    before = hashlib.sha256(db.EVIDENCE_DB_PATH.read_bytes()).hexdigest()
    assert before == EVIDENCE_SHA256
    yield
    assert hashlib.sha256(db.EVIDENCE_DB_PATH.read_bytes()).hexdigest() == before


# ---- helpers ---------------------------------------------------------------------------
def _enc(value: str) -> str:
    return urllib.parse.quote(value, safe="")


@contextlib.contextmanager
def _client(path: Path):
    app = create_app()
    app.state.db_path = path
    app.state.auto_dispatch = False
    with TestClient(app) as client:
        yield client


def _working_copy(dest: Path) -> Path:
    shutil.copy(db.EVIDENCE_DB_PATH, dest)
    conn = db.connect(dest)
    try:
        db.migrate(conn)  # adds runs.backend_kind so mock provenance can be recorded
    finally:
        conn.close()
    return dest


def _record(agent, idx=0, *, passed=True, task_id=TASK, task_version=None) -> RunRecord:
    score = RunScore(RunStatus.VALID, int(passed), float(passed), 1.0, {}, float(passed), passed, False)
    return RunRecord(
        task_id=task_id, task_version=task_version or TASK_CURRENT[task_id], agent=agent,
        idx=idx, status=RunStatus.VALID, score=score, files_changed=int(passed),
        lines_added=int(passed), lines_removed=0, duration_ms=1,
        transcript_hash=f"sha256:redteam-a-{agent}-{task_id}-{task_version}-{idx}-{passed}",
    )


def _persist(path: Path, record: RunRecord, backend_kind: str | None = None) -> int:
    store = afa.SqliteRunStore(path)
    try:
        return store.save_run(record, backend_kind=backend_kind)
    finally:
        store.close()


def _exec(path: Path, sql: str, args=()) -> None:
    conn = sqlite3.connect(str(path))
    try:
        conn.execute(sql, args)
        conn.commit()
    finally:
        conn.close()


def _rows(path: Path, sql: str, args=()):
    conn = db.connect_readonly(path)
    try:
        return [tuple(r) for r in conn.execute(sql, args).fetchall()]
    finally:
        conn.close()


def _scalar(path: Path, sql: str, args=()):
    return _rows(path, sql, args)[0][0]


def _add_other_formula_rows(path: Path, run_ids=None) -> None:
    """Re-score every (or the given) run under two OTHER formulas that contradict the pinned
    score: EARLIER fails the run, LATER voids it."""
    where = f" AND run_id IN ({','.join('?' for _ in run_ids)})" if run_ids else ""
    conn = sqlite3.connect(str(path))
    try:
        for formula, voided in ((EARLIER, 0), (LATER, 1)):
            conn.execute(
                "INSERT INTO run_scores (run_id, gate_product, t_hidden, q, final_score, "
                "functional_pass, voided, formula_version) SELECT run_id, 0, 0.0, 0.0, 0.0, 0, ?, ? "
                f"FROM run_scores WHERE formula_version=?{where}",
                (voided, formula, PINNED, *(run_ids or ())),
            )
        conn.commit()
    finally:
        conn.close()


def _run_eval(path: Path, model: str, *, repeats: int = 1):
    """Create + claim + run one mock evaluation of TASK to completion through the worker."""
    conn = db.connect(path)
    try:
        job = jobs.create_job(
            conn, JobCreate(model=model, backend=Backend(kind="mock"), tasks=[TASK], repeats=repeats)
        )
        token = jobs.claim_job_token(conn, job.id)
        worker.run_job(conn, job.id, agent_factory=worker.mock_agent_factory, owner_token=token)
        finished = jobs.get_job(conn, job.id)
        assert finished.status == "succeeded", finished.error_message
        return finished
    finally:
        conn.close()


def _historical_version(path: Path, task_id: str) -> str:
    rows = _rows(
        path,
        "SELECT DISTINCT task_version FROM runs WHERE task_id=? AND task_version != ? AND agent=?",
        (task_id, TASK_CURRENT[task_id], MODEL),
    )
    assert rows, "the committed evidence holds an older version of this task"
    return rows[0][0]


# ---- module fixtures -------------------------------------------------------------------
@pytest.fixture(scope="module")
def base_path(tmp_path_factory) -> Path:
    """Evidence copy + a probe agent (two current runs, one historical run)."""
    path = _working_copy(tmp_path_factory.mktemp("base") / "base.sqlite")
    _persist(path, _record(PROBE, 0, passed=True))
    _persist(path, _record(PROBE, 1, passed=False))
    _persist(path, _record(PROBE, 0, task_id=SANITIZE, task_version=_historical_version(path, SANITIZE)))
    return path


@pytest.fixture(scope="module")
def multi_path(base_path, tmp_path_factory) -> Path:
    """The same database, but EVERY run is re-scored under two other formulas."""
    path = tmp_path_factory.mktemp("multi") / "multi.sqlite"
    shutil.copy(base_path, path)
    _add_other_formula_rows(path)
    return path


@pytest.fixture(scope="module")
def legacy_path(base_path, tmp_path_factory) -> Path:
    """The same database with a PRE-formula_version run_scores table (one row per run)."""
    path = tmp_path_factory.mktemp("legacy") / "legacy.sqlite"
    shutil.copy(base_path, path)
    conn = sqlite3.connect(str(path))
    try:
        conn.executescript(
            "CREATE TABLE run_scores_legacy (run_id INTEGER PRIMARY KEY REFERENCES runs(id), "
            "gate_product INTEGER NOT NULL, t_hidden REAL NOT NULL, q REAL NOT NULL, "
            "final_score REAL NOT NULL, functional_pass INTEGER NOT NULL, voided INTEGER NOT NULL);"
            "INSERT INTO run_scores_legacy SELECT run_id, gate_product, t_hidden, q, final_score, "
            "functional_pass, voided FROM run_scores;"
            "DROP TABLE run_scores; ALTER TABLE run_scores_legacy RENAME TO run_scores;"
        )
        conn.commit()
    finally:
        conn.close()
    assert "formula_version" not in {r[1] for r in _rows(path, "PRAGMA table_info(run_scores)")}
    return path


@pytest.fixture(scope="module")
def clients(base_path, multi_path, legacy_path):
    """TestClients over the single-formula (.base), re-scored (.multi) and legacy-schema databases."""
    with contextlib.ExitStack() as stack:
        yield SimpleNamespace(**{
            name: stack.enter_context(_client(path))
            for name, path in (("base", base_path), ("multi", multi_path), ("legacy", legacy_path))
        })


@pytest.fixture(scope="module")
def hist_version(base_path) -> str:
    return _historical_version(base_path, SANITIZE)


@pytest.fixture()
def regen_out(monkeypatch, tmp_path) -> Path:
    out = tmp_path / "out" / "leaderboard.html"
    monkeypatch.setattr(report_combined, "OUTPUT", out, raising=False)
    return out


# ---- constants that must agree ---------------------------------------------------------
def test_score_formula_version_is_defined_once_and_matches_what_the_writer_stamps(base_path):
    default = re.search(
        r"formula_version\s+TEXT\s+NOT\s+NULL\s+DEFAULT\s+'([^']+)'", runner_store.SQLITE_SCHEMA
    )
    assert default, "run_scores.formula_version must declare a DEFAULT in SQLITE_SCHEMA"
    assert runner_store.SCORE_FORMULA_VERSION == evidence.SCORE_FORMULA_VERSION == default.group(1)
    # ... and that value is what a fresh run and the committed rows carry (else the pinned
    # readers would silently see no evidence at all).
    store = afa.SqliteRunStore(":memory:")
    try:
        store.save_run(_record("constants-agent"))
        stamped = store.connection.execute("SELECT DISTINCT formula_version FROM run_scores").fetchall()
        assert [tuple(r) for r in stamped] == [(evidence.SCORE_FORMULA_VERSION,)]
        assert len(store.load_runs()) == 1
    finally:
        store.close()
    assert _rows(base_path, "SELECT DISTINCT formula_version FROM run_scores") == [(PINNED,)]


def test_reserved_agent_names_are_exactly_the_synthetic_baseline_names():
    assert evidence.RESERVED_AGENT_NAMES == frozenset({report_combined.ORACLE, report_combined.NOOP})
    assert store_load.SYNTHETIC_AGENTS == evidence.RESERVED_AGENT_NAMES
    for name in evidence.RESERVED_AGENT_NAMES:
        with pytest.raises(ValueError):
            JobParams(model=name, tasks=[TASK])
    assert JobParams(model="an-ordinary-model", tasks=[TASK]).model == "an-ordinary-model"


# ---- F1: a second run_scores formula row must not double-count a run -------------------
def _projection(store: afa.SqliteRunStore):
    return [
        (r.run_id, r.agent, r.task_id, r.task_version, r.idx, r.score.final_score,
         r.score.functional_pass, r.score.voided)
        for r in store.load_runs()
    ]


def test_runner_store_loads_one_record_per_run_pinned_to_the_declared_formula(base_path, multi_path):
    base, multi = afa.SqliteRunStore.open_readonly(base_path), afa.SqliteRunStore.open_readonly(multi_path)
    try:
        distinct = _scalar(multi_path, "SELECT COUNT(DISTINCT run_id) FROM run_scores")
        assert _scalar(multi_path, "SELECT COUNT(*) FROM run_scores") == 3 * distinct
        records = multi.load_runs()
        assert len(records) == len({r.run_id for r in records}) == distinct
        assert _projection(multi) == _projection(base)  # scores come from the pinned row
        probe = next(r for r in multi.load_runs(agent=PROBE, task_id=TASK) if r.idx == 0)
        assert probe.score.functional_pass is True and probe.score.final_score == 1.0
    finally:
        base.close()
        multi.close()


def _urls(hist: str) -> list[str]:
    m = _enc(MODEL)
    return [
        "/api/v1/overview", "/api/v1/overview?evidence=all", "/api/v1/meta", "/api/v1/export",
        "/api/v1/leaderboard", f"/api/v1/leaderboard?task_id={TASK}",
        f"/api/v1/leaderboard?task_id={SANITIZE}&version={hist}",
        f"/api/v1/domains/{m}", f"/api/v1/domains/{PROBE}",
        f"/api/v1/cell/{m}/{TASK}", f"/api/v1/cell/{m}/{SANITIZE}?version={hist}",
        f"/api/v1/cell/{PROBE}/{TASK}", f"/api/v1/cell/{PROBE}/{SANITIZE}?version={hist}",
        f"/api/v1/run/{m}/{TASK}/0", f"/api/v1/run/{m}/{SANITIZE}/0?version={hist}",
        f"/api/v1/run/{PROBE}/{TASK}/0", f"/api/v1/run/{PROBE}/{SANITIZE}/0?version={hist}",
    ]


def test_projection_of_a_rescored_database_equals_the_single_formula_projection(clients, hist_version):
    """Every aggregate, per-task and ?version= view over a database whose runs all carry two
    extra-formula rows is identical to the one-row-per-run database."""
    for url in _urls(hist_version):
        expected, actual = clients.base.get(url), clients.multi.get(url)
        assert expected.status_code == 200, url
        assert actual.status_code == 200 and actual.json() == expected.json(), url


def test_a_rescored_run_is_counted_once_in_every_view(clients, hist_version):
    multi_client = clients.multi

    def entry(entries, agent):
        return next(e for e in entries if e["agent"] == agent)

    for entries in (
        multi_client.get("/api/v1/overview").json()["leaderboard"],
        multi_client.get("/api/v1/leaderboard").json()["entries"],
        multi_client.get("/api/v1/export").json()["leaderboard"],
    ):
        assert entry(entries, PROBE)["n"] == 2 and entry(entries, PROBE)["pass_rate"] == 0.5
        assert entry(entries, MODEL)["n"] == 30
    per_task = multi_client.get(f"/api/v1/leaderboard?task_id={TASK}").json()["entries"]
    assert entry(per_task, PROBE)["n"] == 2
    hist = multi_client.get(f"/api/v1/leaderboard?task_id={SANITIZE}&version={hist_version}").json()
    assert entry(hist["entries"], PROBE)["n"] == 1

    cell = multi_client.get(f"/api/v1/cell/{PROBE}/{TASK}").json()
    assert cell["current_runs"] == 2 and cell["aggregate"]["n_valid"] == 2
    assert len({r["run_id"] for r in cell["runs"]}) == len(cell["runs"]) == 2
    old = multi_client.get(f"/api/v1/cell/{PROBE}/{SANITIZE}?version={hist_version}").json()
    assert old["historical_runs"] == 1 and old["aggregate"]["n_valid"] == 1
    assert old["versions"][0]["n_runs"] == 1

    overview = multi_client.get("/api/v1/overview").json()
    assert overview["current_benchmark"]["current_runs"] == 180 + 2
    assert overview["current_benchmark"]["historical_runs"] == 540 + 1
    assert overview["real_counts"][PROBE] == {"n_runs": 2, "n_tasks": 1}
    assert overview["excluded"]["unaccounted_runs"] == 0  # every run still has its pinned row
    backend = next(d for d in multi_client.get(f"/api/v1/domains/{PROBE}").json()["domains"]
                   if d["domain"] == "backend")
    assert backend["n_runs"] == 2 and backend["pooled_pass_rate"] == 0.5


def test_exact_and_tuple_run_routes_return_the_pinned_formula_score(clients, multi_path):
    multi_client = clients.multi
    run_id = _scalar(multi_path, "SELECT id FROM runs WHERE agent=? AND task_id=? AND idx=0", (PROBE, TASK))
    by_id, by_tuple = multi_client.get(f"/api/v1/runs/{run_id}"), multi_client.get(f"/api/v1/run/{PROBE}/{TASK}/0")
    assert by_id.status_code == by_tuple.status_code == 200  # tuple route: not 'ambiguous with itself'
    for body in (by_id.json(), by_tuple.json()):
        assert body["run_id"] == run_id
        assert body["score"]["functional_pass"] is True and body["score"]["final_score"] == 1.0
        assert body["score"]["voided"] is False
    for rid, final, passed in _rows(  # sample of committed runs: raw pinned row == forensic route
        multi_path,
        "SELECT run_id, final_score, functional_pass FROM run_scores WHERE formula_version=? "
        "AND run_id % 97 = 0", (PINNED,),
    ):
        score = multi_client.get(f"/api/v1/runs/{rid}").json()["score"]
        assert (score["final_score"], score["functional_pass"]) == (final, bool(passed)), rid


def test_job_counters_and_evaluation_reports_ignore_other_formulas(tmp_path):
    path = _working_copy(tmp_path / "eval.sqlite")
    job = _run_eval(path, "f1-eval-model", repeats=2)
    run_ids = [r[0] for r in _rows(path, "SELECT id FROM runs WHERE job_id=? ORDER BY id", (job.id,))]
    assert len(run_ids) == 2

    def observe(client):
        report = client.get(f"/api/v1/jobs/{job.id}/report.json").json()
        return {
            "counters": client.get(f"/api/v1/jobs/{job.id}").json()["counters"],
            "report_counters": report["counters"],
            "report_outcomes": [t["outcome"] for t in report["trials"]],
            "detail_outcomes": [
                client.get(f"/api/v1/jobs/{job.id}/trials/{TASK}/{i}").json()["outcome"] for i in range(2)
            ],
        }

    with _client(path) as client:
        before = observe(client)
        raw_pass = _scalar(
            path, "SELECT SUM(functional_pass) FROM run_scores WHERE formula_version=? AND run_id IN (?, ?)",
            (PINNED, *run_ids),
        )
        assert before["counters"]["completed_runs"] == 2 and before["counters"]["passed_runs"] == raw_pass
        _add_other_formula_rows(path, run_ids)
        conn = db.connect(path)
        try:
            jobs.refresh_counters(conn, job.id)  # the worker's own counter derivation
        finally:
            conn.close()
        after = observe(client)
    assert after == before  # (a LEFT JOIN over the 3 rows per run would say completed=6)


@pytest.mark.parametrize("keep_pinned_row", [True, False], ids=["pinned-row-present", "only-other-formula"])
def test_reuse_needs_score_evidence_under_the_pinned_formula(tmp_path, keep_pinned_row):
    path = _working_copy(tmp_path / "reuse.sqlite")
    source = _run_eval(path, "f1-reuse-model")
    run_id = _scalar(path, "SELECT id FROM runs WHERE job_id=?", (source.id,))
    _add_other_formula_rows(path, [run_id])
    if not keep_pinned_row:
        _exec(path, "DELETE FROM run_scores WHERE run_id=? AND formula_version=?", (run_id, PINNED))
    params = JobCreate(
        model="f1-reuse-model", backend=Backend(kind="mock"), tasks=[TASK], repeats=1,
        mode="reuse", source_evaluation_id=source.id,
    )
    conn = db.connect(path)
    try:
        before = conn.execute("SELECT COUNT(*) FROM evaluation_jobs").fetchone()[0]
        if keep_pinned_row:
            assert jobs.create_job(conn, params).counters.reused_runs == 1
        else:
            with pytest.raises(jobs.JobStateError):
                jobs.create_job(conn, params)
            assert conn.execute("SELECT COUNT(*) FROM evaluation_jobs").fetchone()[0] == before
    finally:
        conn.close()


def test_pre_formula_version_schema_stays_readable_by_the_runner_store(base_path, legacy_path):
    base, legacy = afa.SqliteRunStore.open_readonly(base_path), afa.SqliteRunStore.open_readonly(legacy_path)
    try:
        assert len(legacy.load_runs()) == _scalar(legacy_path, "SELECT COUNT(*) FROM runs") == 723
        assert _projection(legacy) == _projection(base)
    finally:
        base.close()
        legacy.close()


def test_pre_formula_version_schema_stays_readable_through_the_api(clients, legacy_path, hist_version):
    base_client, legacy_client = clients.base, clients.legacy
    assert legacy_client.get("/api/v1/healthz").json()["status"] == "ok"
    for url in _urls(hist_version):
        assert legacy_client.get(url).json() == base_client.get(url).json(), url
    ids = [r[0] for r in _rows(legacy_path, "SELECT id FROM runs ORDER BY id")]
    for run_id in ids[::100] + ids[-3:]:
        exact = legacy_client.get(f"/api/v1/runs/{run_id}")
        assert exact.status_code == 200 and exact.json() == base_client.get(f"/api/v1/runs/{run_id}").json()
    assert legacy_client.get("/api/v1/overview").json()["excluded"]["unaccounted_runs"] == 0


def test_evaluation_completes_on_a_pre_formula_version_schema(legacy_path, tmp_path):
    """SUSPECTED PRODUCT BUG (regression introduced by the F1 fix; beyond its stated scope):
    jobs.py pins ``s.formula_version`` in refresh_counters / trial_detail / the reuse check
    WITHOUT the column guard the runner store and serialize.py have. On a database whose
    run_scores predates formula_version (readable, see the two tests above) the worker dies in
    its first refresh_counters with ``no such column: s.formula_version`` and, through the API,
    the job stays 'running' forever. Pre-3ef58a4 this completed."""
    path = tmp_path / "legacy-eval.sqlite"
    shutil.copy(legacy_path, path)
    conn = db.connect(path)
    try:
        db.migrate(conn)
        job = jobs.create_job(
            conn, JobCreate(model="legacy-schema-model", backend=Backend(kind="mock"), tasks=[TASK])
        )
        token = jobs.claim_job_token(conn, job.id)
        try:
            worker.run_job(conn, job.id, agent_factory=worker.mock_agent_factory, owner_token=token)
        except sqlite3.OperationalError as exc:
            pytest.fail(f"evaluation crashed on a pre-formula_version run_scores schema: {exc}")
        finished = jobs.get_job(conn, job.id)
        assert finished.status == "succeeded", finished.error_message
        assert finished.counters.completed_runs == 1
    finally:
        conn.close()


# ---- F5: regenerate never lets a non-default scope replace the canonical report --------
_CLASSES_IN_SCOPE = {"benchmark": {"legacy"}, "real": set(), "synthetic": {"synthetic"},
                     "all": {"legacy", "synthetic"}}


@pytest.fixture(scope="module")
def scoped_path(tmp_path_factory) -> Path:
    """Evidence copy + a mock-only model (3 current runs, 1 historical run)."""
    path = _working_copy(tmp_path_factory.mktemp("f5") / "scoped.sqlite")
    for i in range(3):
        _persist(path, _record(F5_MOCK, i), backend_kind="mock")
    _persist(path, _record(F5_MOCK, 5, passed=False, task_version="0.9.0"), backend_kind="mock")
    return path


def _expected_counts(path: Path, scope: str) -> dict[str, int]:
    """Independent oracle from raw rows (no job rows exist: only mock / NULL backend_kind)."""
    rows = _rows(path, "SELECT task_id, task_version, backend_kind FROM runs")
    in_scope = [
        (task, version) for task, version, kind in rows
        if ("synthetic" if kind == "mock" else "legacy") in _CLASSES_IN_SCOPE[scope]
    ]
    return {
        "outside": len(rows) - len(in_scope),
        "historical": sum(1 for task, version in in_scope if version != TASK_CURRENT[task]),
    }


def _regenerate(client, scope_query: str = "") -> dict:
    response = client.post(f"/api/v1/reports/regenerate{scope_query}")
    assert response.status_code == 200, response.text
    return response.json()


def test_default_scope_writes_the_canonical_output_and_nothing_else(scoped_path, regen_out):
    with _client(scoped_path) as client:
        for query in ("", "?evidence=benchmark"):
            regen_out.unlink(missing_ok=True)
            body = _regenerate(client, query)
            assert Path(body["path"]) == regen_out and body["evidence_scope"] == "benchmark"
            assert [p.name for p in regen_out.parent.iterdir()] == [regen_out.name]
            assert F5_MOCK not in regen_out.read_text()


@pytest.mark.parametrize("scope", ["synthetic", "real", "all"])
def test_non_default_scopes_never_touch_the_canonical_output(scoped_path, regen_out, scope):
    with _client(scoped_path) as client:
        # 1) no canonical report yet: a scoped report must not create one
        sibling = Path(_regenerate(client, f"?evidence={scope}")["path"])
        assert sibling != regen_out and sibling.parent == regen_out.parent and scope in sibling.name
        assert sibling.is_file() and not regen_out.exists()
        # 2) an existing canonical artifact (a sentinel) stays byte-identical
        regen_out.write_bytes(b"<!-- canonical benchmark report -->")
        assert Path(_regenerate(client, f"?evidence={scope}")["path"]) == sibling
        assert regen_out.read_bytes() == b"<!-- canonical benchmark report -->"
        assert sorted(p.name for p in regen_out.parent.iterdir()) == sorted([regen_out.name, sibling.name])
        # 3) only the default scope replaces it
        _regenerate(client)
        assert "Evidence scope 'benchmark'" in html.unescape(regen_out.read_text())


@pytest.mark.parametrize("scope", SCOPES)
def test_every_report_states_its_scope_and_the_counts_left_outside_it(scoped_path, regen_out, scope):
    with _client(scoped_path) as client:
        text = html.unescape(Path(_regenerate(client, f"?evidence={scope}")["path"]).read_text())
    expected = _expected_counts(scoped_path, scope)
    assert f"Evidence scope '{scope}'" in text
    assert ("NOT benchmark evidence" in text) == (scope in ("synthetic", "all"))
    outside = re.findall(r"(\d+) run\(s\) outside this scope are excluded", text)
    assert outside == ([str(expected["outside"])] if expected["outside"] else [])
    historical = re.findall(r"(\d+) historical-version run\(s\)", text)
    assert historical == ([str(expected["historical"])] if expected["historical"] else [])
    assert (F5_MOCK in text) == (scope in ("synthetic", "all"))


# ---- F9: a run row with an unrecognised status fails closed AND names the row ----------
@pytest.fixture()
def bogus(tmp_path):
    path = _working_copy(tmp_path / "bogus.sqlite")
    run_id = _persist(path, _record(F9_AGENT, 0))
    _exec(path, "UPDATE runs SET status='bogus_status' WHERE id=?", (run_id,))
    return path, run_id


def _names_the_row(message: str, run_id: int) -> bool:
    return all(
        needle in message
        for needle in (f"run {run_id} ", F9_AGENT, TASK, "unrecognised status", "bogus_status")
    )


def test_runner_store_names_the_unrecognised_row_and_only_fails_for_its_agent(bogus):
    path, run_id = bogus
    store = afa.SqliteRunStore.open_readonly(path)
    try:
        for kwargs in ({}, {"agent": F9_AGENT}):
            with pytest.raises(ValueError) as caught:
                store.load_runs(**kwargs)
            assert _names_the_row(str(caught.value), run_id), str(caught.value)
        assert len(store.load_runs(agent=MODEL)) == 120  # one bad row does not poison others
    finally:
        store.close()


@pytest.mark.parametrize(
    "method, route, status",
    [("GET", route, 503) for route in (
        "/api/v1/overview", "/api/v1/overview?evidence=all", "/api/v1/meta", "/api/v1/export",
        "/api/v1/leaderboard", f"/api/v1/leaderboard?task_id={TASK}", f"/api/v1/domains/{F9_AGENT}",
        f"/api/v1/cell/{F9_AGENT}/{TASK}", f"/api/v1/run/{F9_AGENT}/{TASK}/0",
    )] + [("POST", "/api/v1/reports/regenerate", 409), ("GET", "/api/v1/healthz", 200)],
)
def test_projections_stay_fail_closed_and_name_the_bad_run(bogus, regen_out, method, route, status):
    path, run_id = bogus
    with _client(path) as client:
        response = client.request(method, route)
    body = response.json()
    assert response.status_code == status
    assert _names_the_row(body.get("error") or body["load_error"], run_id), body
    assert route.endswith("healthz") == (body.get("status") == "degraded")
    assert not regen_out.exists()  # a failed regenerate writes nothing


def test_the_bad_row_stays_inspectable_and_repairing_it_restores_service(bogus):
    path, run_id = bogus
    with _client(path) as client:
        forensic = client.get(f"/api/v1/runs/{run_id}")
        assert forensic.status_code == 200 and forensic.json()["status"] == "bogus_status"
        assert client.get("/api/v1/overview").status_code == 503
        _exec(path, "UPDATE runs SET status='valid' WHERE id=?", (run_id,))  # no restart needed
        overview = client.get("/api/v1/overview")
        assert overview.status_code == 200 and F9_AGENT in overview.json()["models"]


# ---- F13: runs the loader cannot see are counted, never silently dropped ---------------
@pytest.fixture(scope="module")
def partial(tmp_path_factory):
    """Legacy evidence + F13_AGENT runs: complete / no diffs / no run_scores / only another
    formula / historical, + a mock run (synthetic) + a run under a reserved baseline name."""
    path = _working_copy(tmp_path_factory.mktemp("f13") / "partial.sqlite")
    ids = {
        name: _persist(path, _record(F13_AGENT, i))
        for i, name in enumerate(("complete", "no_diffs", "no_scores", "other_formula"))
    }
    ids["historical"] = _persist(path, _record(F13_AGENT, 9, task_version="0.9.0"))
    _persist(path, _record("f13-mock", 0), backend_kind="mock")
    _persist(path, _record(report_combined.ORACLE, 0))  # provenance conflict
    _exec(path, "DELETE FROM diffs WHERE run_id=?", (ids["no_diffs"],))
    _exec(path, "DELETE FROM run_scores WHERE run_id=?", (ids["no_scores"],))
    _exec(path, "UPDATE run_scores SET formula_version=? WHERE run_id=?", (LATER, ids["other_formula"]))
    return path, ids


@pytest.fixture(scope="module")
def partial_client(partial):
    with _client(partial[0]) as client:
        yield client


PARTIAL = ("no_diffs", "no_scores", "other_formula")
_UNSEEN_SQL = (
    "SELECT COUNT(*) FROM runs r WHERE NOT EXISTS (SELECT 1 FROM run_scores s WHERE "
    "s.run_id=r.id AND s.formula_version=?) OR NOT EXISTS (SELECT 1 FROM diffs d WHERE d.run_id=r.id)"
)


@pytest.mark.parametrize("scope_query", ["", "?evidence=all", "?evidence=real", "?evidence=synthetic"])
@pytest.mark.parametrize("endpoint", ["overview", "meta", "export"])
def test_unaccounted_runs_are_counted_in_overview_meta_and_export(partial, partial_client, endpoint, scope_query):
    assert _scalar(partial[0], _UNSEEN_SQL, (PINNED,)) == len(PARTIAL)  # independent oracle
    body = partial_client.get(f"/api/v1/{endpoint}{scope_query}").json()
    assert body["excluded"]["unaccounted_runs"] == len(PARTIAL)


def test_unaccounted_runs_never_enter_aggregates(partial_client):
    cell = partial_client.get(f"/api/v1/cell/{F13_AGENT}/{TASK}").json()
    assert cell["current_runs"] == 1 and [r["idx"] for r in cell["runs"]] == [0]
    assert cell["aggregate"]["n_valid"] == 1
    entries = partial_client.get("/api/v1/leaderboard").json()["entries"]
    assert next(e for e in entries if e["agent"] == F13_AGENT)["n"] == 1


@pytest.mark.parametrize("name", PARTIAL)
def test_unaccounted_runs_are_inspectable_or_explicitly_missing(partial, partial_client, name):
    path, ids = partial
    run_id = ids[name]
    assert _scalar(path, "SELECT COUNT(*) FROM runs WHERE id=?", (run_id,)) == 1  # never deleted
    exact = partial_client.get(f"/api/v1/runs/{run_id}")
    assert exact.status_code in (200, 404) and exact.json().get("run_id") == run_id
    assert exact.json()["found"] is (exact.status_code == 200)
    idx = _scalar(path, "SELECT idx FROM runs WHERE id=?", (run_id,))
    by_tuple = partial_client.get(f"/api/v1/run/{F13_AGENT}/{TASK}/{idx}")
    assert by_tuple.status_code == 200  # never 409 ambiguous / 5xx
    assert by_tuple.json()["found"] is False or by_tuple.json()["run_id"] == run_id


@pytest.mark.parametrize("scope", SCOPES)
def test_current_historical_excluded_and_unaccounted_reconcile_to_the_raw_row_count(
    partial, partial_client, scope
):
    """SUSPECTED PRODUCT BUG for scope=real/synthetic (those two fail; pre-existing, low):
    in-database rows outside the requested scope that are neither synthetic nor a provenance
    conflict (e.g. the 720 legacy runs under ?evidence=real) are counted nowhere, although
    store_load's docstring says out-of-scope rows are "counted in excluded ... so nothing is
    hidden silently"."""
    total = _scalar(partial[0], "SELECT COUNT(*) FROM runs")
    overview = partial_client.get(f"/api/v1/overview?evidence={scope}").json()
    excluded = sum(v for v in overview["excluded"].values() if isinstance(v, int))
    benchmark = overview["current_benchmark"]
    accounted = benchmark["current_runs"] + benchmark["historical_runs"] + excluded
    assert accounted == total, (scope, benchmark, overview["excluded"])
