"""Release-hardening suite for the Phase-0 current-benchmark branch.

Written independently FROM THE CONTRACT (API_CONTRACT_v2), not from the
implementation. It pins the behaviours that no earlier test could detect:

  A  current-only filtering (numeric anchors that a version-blind regression fails)
  B  a model whose only evidence is historical is listed, never ranked
  C  historical evidence stays inspectable and labelled (?version=, /runs/{id})
  D  two agents on different versions of one task are never ranked together
  E  version-semantics payload (selected/current version, evidence_status, ...)
  F  malformed / contradictory persisted evaluation parameters fail closed
  G  startup recovery, resume and retry never resurrect unverifiable evaluations
  H  raw backend provenance (runs.backend_kind), factories, loopback transports
  I  mock evidence is excluded from the default ranking but stays inspectable
  J  provenance consistency (mismatch/conflict), legacy labelling
  K  one small concurrent-migration smoke (the exhaustive suite lives elsewhere)

Nothing here writes to reports/runs.sqlite: every database is a differently named
copy, and a module-scoped guard asserts the committed evidence is byte-identical.
"""
from __future__ import annotations

import contextlib
import dataclasses
import hashlib
import json
import shutil
import sqlite3
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import afa_runner as afa
from afa_api import db, evidence, jobs, worker
from afa_api.main import create_app
from afa_api.schemas import Backend, JobCreate, JobParams
from afa_api.store_load import LoadedRun, load_stores
from afa_kernel.types import RunScore, RunStatus
from afa_runner.pipeline import RunRecord

REPO = Path(__file__).resolve().parents[1]
TASK = "fix-binary-search"
SANITIZE = "sanitize-filename"
TERMINAL = {"succeeded", "failed", "canceled"}
INVALID_PREFIX = "invalid persisted evaluation parameters"

MODELS = [
    "deepseek-coder:6.7b",
    "gemma2:2b",
    "llama3.2:latest",
    "qwen2.5-coder:3b",
    "qwen2.5-coder:7b",
    "qwen3.5:9b",
]
CURRENT_TASKS = {
    "async-batched",
    "escape-html",
    "fix-binary-search",
    "fix-roman-numerals",
    "implement-lru-cache",
    "two-sum-indices",
}
_REMEDIATION = json.loads(
    (REPO / "integrity/pack-audit/remediation-manifest.json").read_text()
)
BUMPED: dict[str, dict] = {t["task_id"]: t for t in _REMEDIATION["tasks"]}
OLD = {tid: entry["old_version"] for tid, entry in BUMPED.items()}
NEW = {tid: entry["new_version"] for tid, entry in BUMPED.items()}
ALL_TASKS = [item["id"] for item in json.loads((REPO / "tasks/manifest.json").read_text())]
TASK_CURRENT = {
    tid: json.loads((REPO / "tasks" / tid / "task.json").read_text())["version"]
    for tid in ALL_TASKS
}


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _enc(value: str) -> str:
    return urllib.parse.quote(value, safe="")


@pytest.fixture(scope="module", autouse=True)
def _evidence_db_is_byte_identical_across_this_module():
    before = _sha256(db.EVIDENCE_DB_PATH)
    assert before == "42b6dad85ee662d6d5d7f75ffbda5a3b95d50837837f81c875730a8987838ced"
    yield
    assert _sha256(db.EVIDENCE_DB_PATH) == before, "committed evidence DB changed"


@contextlib.contextmanager
def _client(path: Path, *, factory=None, auto_dispatch: bool = True, raise_exceptions: bool = True):
    app = create_app()
    app.state.db_path = path
    if factory is not None:
        app.state.agent_factory = factory
    app.state.auto_dispatch = auto_dispatch
    with TestClient(app, raise_server_exceptions=raise_exceptions) as client:
        yield client


def _record(
    agent: str,
    idx: int = 0,
    *,
    passed: bool = True,
    task_id: str = TASK,
    task_version: str | None = None,
) -> RunRecord:
    return RunRecord(
        task_id=task_id,
        task_version=task_version or TASK_CURRENT[task_id],
        agent=agent,
        idx=idx,
        status=RunStatus.VALID,
        score=RunScore(
            RunStatus.VALID,
            1 if passed else 0,
            1.0 if passed else 0.0,
            1.0,
            {},
            1.0 if passed else 0.0,
            passed,
            False,
        ),
        files_changed=1 if passed else 0,
        lines_added=1 if passed else 0,
        lines_removed=0,
        transcript_hash=f"sha256:hardening-{agent}-{task_id}-{task_version}-{idx}-{passed}",
        duration_ms=1,
    )


def _persist(path: Path, record: RunRecord) -> int:
    """Job-less, provider-less (LEGACY) row, exactly like the committed evidence."""
    store = afa.SqliteRunStore(path)
    try:
        return store.save_run(record)
    finally:
        store.close()


def _ro(path: Path) -> sqlite3.Connection:
    return db.connect_readonly(path)


def _scalar(path: Path, sql: str, args=()):
    conn = _ro(path)
    try:
        return conn.execute(sql, args).fetchone()[0]
    finally:
        conn.close()


def _rows(path: Path, sql: str, args=()):
    conn = _ro(path)
    try:
        return [tuple(r) for r in conn.execute(sql, args).fetchall()]
    finally:
        conn.close()


def _exec(path: Path, sql: str, args=()) -> None:
    conn = sqlite3.connect(str(path))
    try:
        conn.execute(sql, args)
        conn.commit()
    finally:
        conn.close()


def _wait_terminal(client: TestClient, job_id: str, timeout: float = 90.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        body = client.get(f"/api/v1/jobs/{job_id}").json()
        if body["status"] in TERMINAL:
            return body
        time.sleep(0.02)
    raise AssertionError(f"job {job_id} did not reach a terminal state")


def _join_dispatch_threads(timeout: float = 30.0) -> None:
    deadline = time.monotonic() + timeout
    for thread in threading.enumerate():
        if thread.name.startswith("afa-job-"):
            thread.join(max(0.0, deadline - time.monotonic()))


class SpyFactory:
    """Records every construction request and delegates to the offline mock."""

    def __init__(self, backend_kind: str | None = None) -> None:
        self.calls: list[tuple[str, str]] = []
        if backend_kind is not None:
            self.backend_kind = backend_kind

    def __call__(self, model, task, params):
        self.calls.append((model, task.id))
        return worker.mock_agent_factory(model, task, params)


def _declaring_factory(kind: str | None):
    """A test factory that behaves like the mock but declares which backend it drives."""

    def factory(model, task, params):
        return worker.mock_agent_factory(model, task, params)

    if kind is not None:
        factory.backend_kind = kind  # type: ignore[attr-defined]
    return factory


@pytest.fixture()
def run_once_counter(monkeypatch):
    """Independent proof that no agent ever ran: count afa.run_once invocations."""
    counter = {"n": 0}
    original = worker.afa.run_once

    def counting(*args, **kwargs):
        counter["n"] += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(worker.afa, "run_once", counting)
    return counter


@pytest.fixture()
def regen_out(monkeypatch, tmp_path):
    import report_combined

    out = tmp_path / "leaderboard.html"
    monkeypatch.setattr(report_combined, "OUTPUT", out, raising=False)
    return out


def _run_eval(
    path: Path,
    model: str,
    *,
    kind: str = "mock",
    tasks=(TASK,),
    repeats: int = 1,
    factory="mock",
    base_url: str | None = None,
):
    """Create + claim + run one evaluation to completion through the worker."""
    if factory == "mock":
        factory = worker.mock_agent_factory
    backend = {"kind": kind}
    if base_url is not None:
        backend["base_url"] = base_url
    conn = db.connect(path)
    try:
        job = jobs.create_job(
            conn,
            JobCreate(model=model, backend=Backend(**backend), tasks=list(tasks), repeats=repeats),
        )
        token = jobs.claim_job_token(conn, job.id)
        assert token is not None
        worker.run_job(conn, job.id, agent_factory=factory, owner_token=token)
        finished = jobs.get_job(conn, job.id)
        assert finished.status == "succeeded", finished.error_message
        return finished
    finally:
        conn.close()


def _run_ids(path: Path, job_id: str) -> list[int]:
    return [r[0] for r in _rows(path, "SELECT run_id FROM job_runs WHERE job_id=? ORDER BY run_id", (job_id,))]


def _ranked(entries: list[dict]) -> list[str]:
    """Agents that actually carry evidence in a leaderboard listing."""
    return sorted(e["agent"] for e in entries if e["n"] > 0)


# --------------------------------------------------------------------------- #
# module fixtures
# --------------------------------------------------------------------------- #


@pytest.fixture(scope="module")
def pristine_path(tmp_path_factory) -> Path:
    path = tmp_path_factory.mktemp("pristine") / "pristine-copy.sqlite"
    shutil.copy(db.EVIDENCE_DB_PATH, path)
    return path


@pytest.fixture(scope="module")
def pristine(pristine_path):
    """Read-only client over an untouched copy of the committed evidence."""
    with _client(pristine_path) as client:
        yield client


@pytest.fixture()
def evcopy(tmp_path) -> Path:
    path = tmp_path / "work-copy.sqlite"
    shutil.copy(db.EVIDENCE_DB_PATH, path)
    return path


X_MODEL = "mixed-version-model"
H_MODEL = "historical-only-model"
B_MODEL = "current-only-agent"


@pytest.fixture(scope="module")
def versions_path(tmp_path_factory) -> Path:
    """Evidence copy + hand-written rows at OLD / CURRENT / NEWER task versions."""
    path = tmp_path_factory.mktemp("versions") / "versions-copy.sqlite"
    shutil.copy(db.EVIDENCE_DB_PATH, path)
    # X: one task (fix-binary-search, current 1.0.0) at three versions.
    for i in range(3):
        _persist(path, _record(X_MODEL, i, passed=False, task_version="0.9.0"))
    for i in range(4):
        _persist(path, _record(X_MODEL, i, passed=True))
    for i in range(2):
        _persist(path, _record(X_MODEL, i, passed=False, task_version="2.0.0"))
    # H: evidence ONLY at old versions of two bumped tasks.
    for i in range(5):
        _persist(path, _record(H_MODEL, i, passed=i < 2, task_id=SANITIZE, task_version=OLD[SANITIZE]))
    for i in range(3):
        _persist(path, _record(H_MODEL, i, passed=True, task_id="toposort", task_version=OLD["toposort"]))
    # B: evidence ONLY at the CURRENT version of sanitize-filename, where the six
    # committed models only have the OLD version.
    for i in range(4):
        _persist(path, _record(B_MODEL, i, passed=i < 2, task_id=SANITIZE, task_version=NEW[SANITIZE]))
    return path


@pytest.fixture(scope="module")
def versions(versions_path):
    with _client(versions_path) as client:
        yield client


class World:
    """A database holding real mock evaluations (built once, never mutated)."""

    def __init__(self, path: Path, snapshot: Path, a_job: str, b_job: str):
        self.path = path
        self.snapshot = snapshot  # pristine post-build copy for mutating tests
        self.a_job = a_job  # qwen3.5:9b x [fix-binary-search, sanitize-filename], mock
        self.b_job = b_job  # mock-only-model x fix-binary-search x2, mock
        self.a_runs = {
            r[0]: r[1]
            for r in _rows(path, "SELECT r.task_id, r.id FROM runs r WHERE r.job_id=?", (a_job,))
        }
        self.b_runs = _run_ids(path, b_job)


MOCK_REAL_NAME = "qwen3.5:9b"
MOCK_ONLY = "mock-only-model"


@pytest.fixture(scope="module")
def mock_world(tmp_path_factory) -> World:
    root = tmp_path_factory.mktemp("mockworld")
    path = root / "mock-world.sqlite"
    shutil.copy(db.EVIDENCE_DB_PATH, path)
    a = _run_eval(path, MOCK_REAL_NAME, tasks=[TASK, SANITIZE])
    b = _run_eval(path, MOCK_ONLY, tasks=[TASK], repeats=2)
    snapshot = root / "mock-world-snapshot.sqlite"
    shutil.copy(path, snapshot)
    return World(path, snapshot, a.id, b.id)


@pytest.fixture(scope="module")
def mockc(mock_world):
    with _client(mock_world.path) as client:
        yield client


# --------------------------------------------------------------------------- #
# A. CURRENT FILTERING - anchors on the committed-evidence copy
# --------------------------------------------------------------------------- #


def test_fixture_facts_match_the_shipped_pack():
    """The anchors below rest on these facts about the committed pack."""
    assert len(ALL_TASKS) == 24
    assert set(BUMPED) == set(ALL_TASKS) - CURRENT_TASKS and len(BUMPED) == 18
    for tid, entry in BUMPED.items():
        assert TASK_CURRENT[tid] == NEW[tid] != OLD[tid], tid


def test_overview_current_benchmark_and_real_counts_are_current_only(pristine):
    ov = pristine.get("/api/v1/overview").json()
    assert ov["evidence_scope"] == "benchmark"
    assert ov["current_benchmark"] == {
        "n_tasks": 24,
        "tasks_with_current_evidence": 6,
        "current_runs": 180,
        "historical_runs": 540,
        "models_with_current_evidence": 6,
        "models_total": 6,
    }
    # EXACT legacy shape, current-only (a version-blind build would say 120/24).
    assert ov["real_counts"] == {m: {"n_runs": 30, "n_tasks": 6} for m in MODELS}
    assert ov["models"] == MODELS
    assert ov["current_models"] == MODELS
    assert ov["historical_only_models"] == []
    assert ov["excluded"] == {
        "synthetic_runs": 0,
        "synthetic_models": [],
        "provenance_conflict_runs": 0,
    }
    for model in MODELS:
        assert ov["evidence_counts"][model] == {
            "current_runs": 30,
            "current_tasks": 6,
            "current_by_class": {"legacy": 30},
            "historical_runs": 90,
            "historical_tasks": 18,
            "historical_only_tasks": 18,
            "tasks_total": 24,
            "coverage_complete": False,
        }
    # Whole-DB provenance is unchanged: every persisted run is still reported.
    assert ov["observability"]["total_runs"] == 720


def test_pooled_leaderboard_is_30_runs_per_model_not_120(pristine):
    ov = pristine.get("/api/v1/overview").json()
    lb = pristine.get("/api/v1/leaderboard").json()
    for entries in (ov["leaderboard"], lb["entries"]):
        assert sorted(e["agent"] for e in entries) == MODELS
        assert {e["n"] for e in entries} == {30}
        for e in entries:
            assert e["synthetic"] is False
            assert e["coverage"] == {
                "tasks_with_current_evidence": 6,
                "tasks_total": 24,
                "complete": False,
            }
    assert lb["found"] is True and lb["task_id"] is None
    assert lb["historical_only_agents"] == []


def test_pooled_numbers_match_raw_sql_over_current_versions_only(pristine, pristine_path):
    """Independent oracle: recompute per-model current runs from raw SQL."""
    conn = _ro(pristine_path)
    try:
        for model in MODELS:
            n = 0
            for task_id in sorted(CURRENT_TASKS):
                n += conn.execute(
                    "SELECT COUNT(*) FROM runs WHERE agent=? AND task_id=? AND task_version=?",
                    (model, task_id, TASK_CURRENT[task_id]),
                ).fetchone()[0]
            assert n == 30
            total = conn.execute("SELECT COUNT(*) FROM runs WHERE agent=?", (model,)).fetchone()[0]
            assert total == 120  # the version-blind number must differ from the API's
    finally:
        conn.close()
    lb = pristine.get("/api/v1/leaderboard").json()["entries"]
    assert all(e["n"] == 30 for e in lb)


@pytest.mark.parametrize("task_id", sorted(CURRENT_TASKS))
def test_task_leaderboard_of_a_current_task_ranks_everyone_at_current(pristine, task_id):
    body = pristine.get(f"/api/v1/leaderboard?task_id={task_id}").json()
    assert body["evidence_status"] == "current"
    assert body["version"] == body["current_version"] == TASK_CURRENT[task_id]
    assert sorted(e["agent"] for e in body["entries"]) == MODELS
    assert {e["n"] for e in body["entries"]} == {5}
    assert body["historical_only_agents"] == []


def test_task_leaderboard_of_a_bumped_task_ranks_nobody_and_names_the_historical_models(pristine):
    body = pristine.get(f"/api/v1/leaderboard?task_id={SANITIZE}").json()
    assert body["found"] is True
    assert body["current_version"] == body["version"] == NEW[SANITIZE]
    assert body["evidence_status"] == "current"
    assert _ranked(body["entries"]) == []  # nobody is ranked on evidence that is not current
    assert all(e["rank_low"] is None and e["rank_high"] is None for e in body["entries"])
    assert body["historical_only_agents"] == MODELS


@pytest.mark.parametrize("task_id", [SANITIZE, "toposort"])
def test_task_leaderboard_has_no_zero_run_placeholder_entries(pristine, task_id):
    """CONTRACT s1: task entries are 'from rows of that task at the selected
    version'. An agent with no such rows must not appear as an entry (a fabricated
    n=0 / pass_rate 0.0 / Wilson [0,1] line reads as a measured result); it belongs
    in historical_only_agents. The old-version view already behaves this way."""
    body = pristine.get(f"/api/v1/leaderboard?task_id={task_id}").json()
    assert body["entries"] == []
    assert body["historical_only_agents"] == MODELS


def test_domains_use_current_runs_only(pristine):
    d = pristine.get(f"/api/v1/domains/{_enc('qwen3.5:9b')}").json()
    assert d["captured"] is True and d["evidence_status"] == "current"
    assert d["synthetic"] is False and d["evidence_scope"] == "benchmark"
    assert d["coverage"] == {"current_tasks": 6, "historical_only_tasks": 18, "tasks_total": 24}
    # 6 tasks x 5 runs = 30 run-slots across the domain weights; a pooled 24-task
    # profile would show many more tasks per domain.
    by_domain = {row["domain"]: row for row in d["domains"]}
    assert set(by_domain) == {"api-design", "async-concurrency", "backend", "performance", "security"}
    assert by_domain["backend"]["n_tasks"] == 5 and by_domain["backend"]["n_runs"] == 25
    # 10 (task, domain) slots over the 6 current tasks x 5 runs each
    assert sum(row["n_runs"] for row in d["domains"]) == 50
    assert max(row["n_tasks"] for row in d["domains"]) <= 6


def _assert_no_domain_evidence(d: dict) -> None:
    """The kernel lists every domain; without current evidence each one is empty."""
    for row in d["domains"]:
        assert row["n_runs"] == 0 and row["n_tasks"] == 0 and row["n_eff"] == 0
        assert row["displayable"] is False and row["pooled_pass_rate"] in (0, 0.0, None)


def test_domains_are_scoped_per_agent_even_for_unknown_agents(pristine):
    d = pristine.get("/api/v1/domains/nobody-at-all").json()
    assert d["captured"] is False and d["evidence_status"] == "none"
    assert d["coverage"] == {"current_tasks": 0, "historical_only_tasks": 0, "tasks_total": 24}
    _assert_no_domain_evidence(d)


@pytest.mark.parametrize("task_id", sorted(BUMPED))
def test_every_bumped_cell_is_historical_only_for_every_model(pristine, task_id):
    for model in MODELS:
        cell = pristine.get(f"/api/v1/cell/{_enc(model)}/{task_id}").json()
        where = f"{model} x {task_id}"
        assert cell["state"] == "historical_only", where
        assert cell["captured"] is False, where
        assert cell["has_current_evidence"] is False and cell["has_historical_evidence"] is True, where
        assert cell["evidence_status"] == "none", where
        assert cell["runs"] == [] and cell["aggregate"] is None, where
        assert cell["current_version"] == cell["selected_version"] == NEW[task_id], where
        assert cell["current_runs"] == 0 and cell["historical_runs"] == 5, where
        assert cell["historical_versions"] == [OLD[task_id]], where
        assert cell["task_versions"] == [OLD[task_id]], where
        assert [v["version"] for v in cell["versions"]] == [OLD[task_id]], where
        assert cell["versions"][0]["status"] == "historical", where


@pytest.mark.parametrize("task_id", sorted(CURRENT_TASKS))
def test_every_current_cell_is_captured_with_five_runs(pristine, task_id):
    for model in MODELS:
        cell = pristine.get(f"/api/v1/cell/{_enc(model)}/{task_id}").json()
        assert cell["state"] == "captured" and cell["captured"] is True
        assert cell["evidence_status"] == "current"
        assert cell["current_runs"] == 5 and cell["historical_runs"] == 0
        assert cell["aggregate"]["n_valid"] == 5
        assert [r["idx"] for r in cell["runs"]] == [0, 1, 2, 3, 4]
        assert {r["task_version"] for r in cell["runs"]} == {TASK_CURRENT[task_id]}
        assert cell["versions"][0]["status"] == "current"


def test_meta_reports_current_and_historical_per_task(pristine):
    meta = pristine.get("/api/v1/meta").json()
    by_id = {t["task_id"]: t for t in meta["tasks"]}
    assert set(by_id) == set(ALL_TASKS)
    for task_id, task in by_id.items():
        if task_id in CURRENT_TASKS:
            assert task["has_current_evidence"] is True
            assert task["current_runs"] == 30 and task["historical_runs"] == 0
            assert task["models_with_current_evidence"] == 6
            assert task["historical_versions"] == []
            assert task["evaluated_versions"] == [task["current_version"]]
        else:
            assert task["has_current_evidence"] is False
            assert task["current_runs"] == 0 and task["historical_runs"] == 30
            assert task["models_with_current_evidence"] == 0
            assert task["historical_versions"] == [OLD[task_id]]
            assert task["evaluated_versions"] == [OLD[task_id]]
            assert task["current_version"] == NEW[task_id]
    assert meta["real_counts"] == {m: {"n_runs": 30, "n_tasks": 6} for m in MODELS}
    assert meta["current_benchmark"]["current_runs"] == 180
    assert meta["current_benchmark"]["historical_runs"] == 540


def test_export_is_current_only_with_exact_real_counts_shape(pristine):
    resp = pristine.get("/api/v1/export")
    assert resp.status_code == 200
    body = resp.json()
    assert body["format"] == "json" and body["evidence_scope"] == "benchmark"
    assert body["real_counts"] == {m: {"n_runs": 30, "n_tasks": 6} for m in MODELS}
    assert body["current_models"] == MODELS and body["historical_only_models"] == []
    assert body["current_benchmark"]["current_runs"] == 180
    assert {e["n"] for e in body["leaderboard"]} == {30}
    assert all(e["coverage"]["tasks_with_current_evidence"] == 6 for e in body["leaderboard"])
    assert body["excluded"]["synthetic_runs"] == 0


def test_regenerate_succeeds_on_the_mostly_historical_evidence(pristine, regen_out):
    resp = pristine.post("/api/v1/reports/regenerate")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ok"] is True and body["path"] == str(regen_out)
    assert body["evidence_scope"] == "benchmark"
    assert body["real_counts"] == {m: {"n_runs": 30, "n_tasks": 6} for m in MODELS}
    assert regen_out.is_file() and body["bytes"] == len(regen_out.read_text())
    assert "540 historical-version run(s)" in regen_out.read_text()


def test_report_subtitle_counts_the_excluded_historical_runs(pristine_path):
    import report_combined

    html, store, counts = report_combined.build_report(db_path=pristine_path)
    try:
        assert counts == {m: (30, 6) for m in MODELS}
        assert "540 historical-version run(s) are excluded" in html
        assert "never pooled" in html
        assert f"{SANITIZE} evaluated v{OLD[SANITIZE]}" in html
        assert "Persisted DB data only" in html
    finally:
        store.close()


def test_healthz_is_ok_on_the_evidence_copy(pristine, pristine_path):
    body = pristine.get("/api/v1/healthz").json()
    assert body["status"] == "ok" and body["stores_loaded"] is True and body["load_error"] is None
    assert body["db_path"] == str(pristine_path)


def test_evidence_scopes_on_legacy_only_evidence(pristine):
    real = pristine.get("/api/v1/overview?evidence=real").json()
    # Legacy (provider-unknown) evidence is NOT real evidence.
    assert real["evidence_scope"] == "real" and real["models"] == [] and real["leaderboard"] == []
    assert real["real_counts"] == {} and real["current_benchmark"]["current_runs"] == 0
    synth = pristine.get("/api/v1/overview?evidence=synthetic").json()
    assert synth["models"] == [] and synth["leaderboard"] == []
    allv = pristine.get("/api/v1/overview?evidence=all").json()
    assert allv["current_benchmark"]["current_runs"] == 180
    assert allv["current_benchmark"]["historical_runs"] == 540
    assert allv["real_counts"] == {m: {"n_runs": 30, "n_tasks": 6} for m in MODELS}
    default = pristine.get("/api/v1/overview").json()
    assert default["evidence_scope"] == "benchmark"
    explicit = pristine.get("/api/v1/overview?evidence=benchmark").json()
    assert explicit["leaderboard"] == default["leaderboard"]


@pytest.mark.parametrize(
    "method,url",
    [
        ("get", "/api/v1/overview?evidence=bogus"),
        ("get", "/api/v1/leaderboard?evidence=bogus"),
        ("get", "/api/v1/domains/x?evidence=bogus"),
        ("get", "/api/v1/cell/x/fix-binary-search?evidence=bogus"),
        ("get", "/api/v1/run/x/fix-binary-search/0?evidence=bogus"),
        ("get", "/api/v1/meta?evidence=bogus"),
        ("get", "/api/v1/export?evidence=bogus"),
        ("post", "/api/v1/reports/regenerate?evidence=bogus"),
        ("get", "/api/v1/leaderboard?version=1.0.0"),
    ],
)
def test_invalid_evidence_or_version_without_task_is_a_400(pristine, method, url):
    resp = getattr(pristine, method)(url)
    assert resp.status_code == 400, resp.text
    assert "error" in resp.json()


def test_mixed_versions_in_one_cell_never_produce_503_or_409(versions, versions_path, regen_out):
    """Versions coexist in the stored data (X has 0.9.0, 1.0.0 and 2.0.0 of one cell)."""
    for url in (
        "/api/v1/overview",
        "/api/v1/leaderboard",
        f"/api/v1/leaderboard?task_id={TASK}",
        f"/api/v1/domains/{_enc(X_MODEL)}",
        f"/api/v1/cell/{_enc(X_MODEL)}/{TASK}",
        "/api/v1/meta",
        "/api/v1/export",
        "/api/v1/healthz",
    ):
        resp = versions.get(url)
        assert resp.status_code == 200, (url, resp.text)
    assert versions.get("/api/v1/healthz").json()["status"] == "ok"
    regen = versions.post("/api/v1/reports/regenerate")
    assert regen.status_code == 200, regen.text
    assert regen.json()["real_counts"][X_MODEL] == {"n_runs": 4, "n_tasks": 1}


def test_mixed_version_default_views_use_only_the_current_rows(versions):
    ov = versions.get("/api/v1/overview").json()
    assert ov["real_counts"][X_MODEL] == {"n_runs": 4, "n_tasks": 1}
    entry = next(e for e in ov["leaderboard"] if e["agent"] == X_MODEL)
    assert entry["n"] == 4 and entry["pass_rate"] == 1.0  # the 5 stale failures are not pooled
    ec = ov["evidence_counts"][X_MODEL]
    assert ec["current_runs"] == 4 and ec["historical_runs"] == 5
    assert ec["historical_tasks"] == 1 and ec["historical_only_tasks"] == 0
    dom = versions.get(f"/api/v1/domains/{_enc(X_MODEL)}").json()
    backend = next(row for row in dom["domains"] if row["domain"] == "backend")
    assert backend["n_runs"] == 4 and backend["n_tasks"] == 1
    # The six committed models are unaffected by X's extra versions.
    assert {m: ov["real_counts"][m] for m in MODELS} == {m: {"n_runs": 30, "n_tasks": 6} for m in MODELS}


def test_mixed_version_cell_directory_and_ordering(versions):
    cell = versions.get(f"/api/v1/cell/{_enc(X_MODEL)}/{TASK}").json()
    assert cell["state"] == "captured" and cell["evidence_status"] == "current"
    assert cell["current_version"] == cell["selected_version"] == "1.0.0"
    assert cell["current_runs"] == 4 and cell["historical_runs"] == 5
    # NEWER-than-current counts as historical too (currency = equality, not ordering).
    assert cell["historical_versions"] == ["2.0.0", "0.9.0"]
    assert cell["task_versions"] == ["0.9.0", "1.0.0", "2.0.0"]
    assert cell["aggregate"]["n_valid"] == 4 and cell["aggregate"]["n_pass"] == 4
    assert [r["task_version"] for r in cell["runs"]] == ["1.0.0"] * 4
    assert [v["version"] for v in cell["versions"]] == ["1.0.0", "2.0.0", "0.9.0"]
    assert [v["status"] for v in cell["versions"]] == ["current", "historical", "historical"]
    agg = {v["version"]: v["aggregate"] for v in cell["versions"]}
    assert (agg["1.0.0"]["n_valid"], agg["1.0.0"]["n_pass"]) == (4, 4)
    assert (agg["2.0.0"]["n_valid"], agg["2.0.0"]["n_pass"]) == (2, 0)  # each version alone
    assert (agg["0.9.0"]["n_valid"], agg["0.9.0"]["n_pass"]) == (3, 0)
    ids = [set(v["run_ids"]) for v in cell["versions"]]
    assert all(len(s) for s in ids) and len(set().union(*ids)) == 9  # disjoint runs


def test_run_identity_by_idx_alone_collides_across_versions_unless_version_selected(versions):
    base = f"/api/v1/run/{_enc(X_MODEL)}/{TASK}/0"
    cur = versions.get(base)
    assert cur.status_code == 200  # never a 409 merely because idx 0 exists at 3 versions
    cur = cur.json()
    assert cur["task_version"] == "1.0.0" and cur["version_status"] == "current"
    old = versions.get(base + "?version=0.9.0").json()
    newer = versions.get(base + "?version=2.0.0").json()
    assert (old["task_version"], old["version_status"]) == ("0.9.0", "historical")
    assert (newer["task_version"], newer["version_status"]) == ("2.0.0", "historical")
    assert len({cur["run_id"], old["run_id"], newer["run_id"]}) == 3
    missing = versions.get(base + "?version=7.7.7").json()
    assert missing["found"] is False and missing["selected_version"] == "7.7.7"
    assert missing["historical_versions"] == ["2.0.0", "1.0.0", "0.9.0"]


def test_mixed_version_task_scoped_leaderboards_never_pool(versions):
    cur = versions.get(f"/api/v1/leaderboard?task_id={TASK}").json()
    x = next(e for e in cur["entries"] if e["agent"] == X_MODEL)
    assert x["n"] == 4 and cur["evidence_status"] == "current"
    old = versions.get(f"/api/v1/leaderboard?task_id={TASK}&version=0.9.0").json()
    assert old["evidence_status"] == "historical" and old["version"] == "0.9.0"
    assert old["current_version"] == "1.0.0"
    assert [(e["agent"], e["n"]) for e in old["entries"]] == [(X_MODEL, 3)]
    assert old["historical_only_agents"] == sorted(MODELS)  # they have rows, but none at 0.9.0


# --------------------------------------------------------------------------- #
# B. HISTORICAL-ONLY MODEL
# --------------------------------------------------------------------------- #


def test_historical_only_model_is_listed_but_never_ranked(versions):
    ov = versions.get("/api/v1/overview").json()
    assert H_MODEL in ov["models"]
    assert H_MODEL in ov["historical_only_models"]
    assert H_MODEL not in ov["current_models"]
    assert H_MODEL not in [e["agent"] for e in ov["leaderboard"]]
    assert len(ov["leaderboard"]) < len(ov["models"])  # roster > ranked, by design
    assert ov["real_counts"][H_MODEL] == {"n_runs": 0, "n_tasks": 0}
    ec = ov["evidence_counts"][H_MODEL]
    assert ec["coverage_complete"] is False
    assert ec["current_runs"] == 0 and ec["current_tasks"] == 0
    assert ec["historical_runs"] == 8 and ec["historical_tasks"] == 2
    assert ec["historical_only_tasks"] == 2
    assert ov["current_benchmark"]["models_total"] == ov["current_benchmark"]["models_with_current_evidence"] + 1
    lb = versions.get("/api/v1/leaderboard").json()
    assert H_MODEL not in [e["agent"] for e in lb["entries"]]
    assert H_MODEL in lb["historical_only_agents"]
    exp = versions.get("/api/v1/export").json()
    assert H_MODEL in exp["historical_only_models"] and H_MODEL not in exp["current_models"]
    assert exp["real_counts"][H_MODEL] == {"n_runs": 0, "n_tasks": 0}
    meta = versions.get("/api/v1/meta").json()
    assert H_MODEL in meta["historical_only_models"]


def test_historical_only_model_domains_report_historical_only(versions):
    d = versions.get(f"/api/v1/domains/{_enc(H_MODEL)}").json()
    assert d["captured"] is False and d["evidence_status"] == "historical_only"
    assert d["synthetic"] is False
    assert d["coverage"]["current_tasks"] == 0 and d["coverage"]["historical_only_tasks"] == 2
    _assert_no_domain_evidence(d)  # no domain profile is derived from stale evidence


@pytest.mark.parametrize("task_id,n", [(SANITIZE, 5), ("toposort", 3)])
def test_historical_only_model_cells(versions, task_id, n):
    cell = versions.get(f"/api/v1/cell/{_enc(H_MODEL)}/{task_id}").json()
    assert cell["state"] == "historical_only" and cell["captured"] is False
    assert cell["evidence_status"] == "none"
    assert cell["runs"] == [] and cell["aggregate"] is None
    assert cell["has_current_evidence"] is False and cell["has_historical_evidence"] is True
    assert cell["historical_runs"] == n and cell["current_runs"] == 0
    assert [(v["version"], v["n_runs"], v["status"]) for v in cell["versions"]] == [
        (OLD[task_id], n, "historical")
    ]


def test_historical_only_model_on_an_unevaluated_task_is_not_captured(versions):
    cell = versions.get(f"/api/v1/cell/{_enc(H_MODEL)}/{TASK}").json()
    assert cell["state"] == "not_captured" and cell["versions"] == []
    assert cell["has_current_evidence"] is False and cell["has_historical_evidence"] is False


def test_historical_only_model_old_version_view_is_inspectable(versions):
    cell = versions.get(f"/api/v1/cell/{_enc(H_MODEL)}/{SANITIZE}?version={OLD[SANITIZE]}").json()
    assert cell["state"] == "historical_only"  # about CURRENT evidence, independent of ?version
    assert cell["evidence_status"] == "historical"
    assert cell["selected_version"] == OLD[SANITIZE]
    assert len(cell["runs"]) == 5 and cell["aggregate"]["n_valid"] == 5 and cell["aggregate"]["n_pass"] == 2


# --------------------------------------------------------------------------- #
# C. HISTORICAL ACCESS on the committed evidence
# --------------------------------------------------------------------------- #

Q9 = "qwen3.5:9b"


def test_old_version_cell_returns_the_original_numbers(pristine, pristine_path):
    cell = pristine.get(f"/api/v1/cell/{_enc(Q9)}/{SANITIZE}?version={OLD[SANITIZE]}").json()
    assert cell["evidence_status"] == "historical" and cell["state"] == "historical_only"
    assert cell["selected_version"] == "1.0.1" and cell["current_version"] == "1.0.2"
    assert len(cell["runs"]) == 5
    assert {r["task_version"] for r in cell["runs"]} == {"1.0.1"}
    assert cell["aggregate"]["n_valid"] == 5 and cell["aggregate"]["pass_rate"] == 0.4
    assert cell["aggregate"]["n_pass"] == 2
    # cross-check with raw SQL
    passes = _scalar(
        pristine_path,
        "SELECT COUNT(*) FROM runs r JOIN run_scores s ON s.run_id=r.id "
        "WHERE r.agent=? AND r.task_id=? AND r.task_version=? AND s.functional_pass=1",
        (Q9, SANITIZE, "1.0.1"),
    )
    assert passes == 2
    assert sorted(cell["versions"][0]["run_ids"]) == sorted(r["run_id"] for r in cell["runs"])
    assert cell["versions"][0]["aggregate"] == cell["aggregate"]
    assert {r["evidence_class"] for r in cell["runs"]} == {"legacy"}
    assert {r["backend_kind"] for r in cell["runs"]} == {None}


def test_task_leaderboard_old_version_view_is_labelled_historical(pristine):
    body = pristine.get(f"/api/v1/leaderboard?task_id={SANITIZE}&version={OLD[SANITIZE]}").json()
    assert body["evidence_status"] == "historical"
    assert body["version"] == "1.0.1" and body["current_version"] == "1.0.2"
    assert sorted(e["agent"] for e in body["entries"]) == MODELS
    assert {e["n"] for e in body["entries"]} == {5}
    assert body["historical_only_agents"] == []
    unknown = pristine.get(f"/api/v1/leaderboard?task_id={SANITIZE}&version=9.9.9").json()
    assert unknown["entries"] == [] and unknown["evidence_status"] == "historical"
    assert unknown["historical_only_agents"] == MODELS  # they exist, but not at 9.9.9


def test_tuple_run_route_is_version_aware(pristine):
    base = f"/api/v1/run/{_enc(Q9)}/{SANITIZE}/0"
    default = pristine.get(base).json()
    assert default["found"] is False
    assert default["current_version"] == "1.0.2" and default["selected_version"] == "1.0.2"
    assert default["historical_versions"] == ["1.0.1"]
    old = pristine.get(base + "?version=1.0.1").json()
    assert old["found"] is True and old["task_version"] == "1.0.1"
    assert old["version_status"] == "historical" and old["current_version"] == "1.0.2"
    assert old["evidence_class"] == "legacy" and old["provider_source"] == "none"
    assert old["backend_kind"] is None and old["job_id"] is None
    current = pristine.get(f"/api/v1/run/{_enc(Q9)}/{TASK}/0").json()
    assert current["found"] is True and current["version_status"] == "current"


def test_exact_run_id_carries_version_status_and_is_never_filtered(pristine):
    old_id = pristine.get(f"/api/v1/run/{_enc(Q9)}/{SANITIZE}/0?version=1.0.1").json()["run_id"]
    body = pristine.get(f"/api/v1/runs/{old_id}").json()
    assert body["found"] is True and body["run_id"] == old_id
    assert body["version_status"] == "historical" and body["current_version"] == "1.0.2"
    assert body["task_version"] == "1.0.1"
    assert body["evidence_class"] == "legacy" and body["backend_kind"] is None
    cur_id = pristine.get(f"/api/v1/run/{_enc(Q9)}/{TASK}/0").json()["run_id"]
    assert pristine.get(f"/api/v1/runs/{cur_id}").json()["version_status"] == "current"
    assert pristine.get("/api/v1/runs/99999999").status_code == 404


def test_cell_versions_directory_and_task_versions_are_consistent(pristine):
    cell = pristine.get(f"/api/v1/cell/{_enc(Q9)}/{SANITIZE}").json()
    assert [(v["version"], v["status"], v["n_runs"]) for v in cell["versions"]] == [("1.0.1", "historical", 5)]
    assert cell["versions"][0]["aggregate"]["pass_rate"] == 0.4
    assert cell["task_versions"] == ["1.0.1"]


# --------------------------------------------------------------------------- #
# D. CROSS-AGENT VERSION DIFFERENCES
# --------------------------------------------------------------------------- #


def test_agents_on_different_versions_of_one_task_are_never_in_one_ranking(versions):
    cur = versions.get(f"/api/v1/leaderboard?task_id={SANITIZE}").json()
    old = versions.get(f"/api/v1/leaderboard?task_id={SANITIZE}&version={OLD[SANITIZE]}").json()
    assert cur["evidence_status"] == "current" and old["evidence_status"] == "historical"
    assert _ranked(cur["entries"]) == [B_MODEL]
    b = next(e for e in cur["entries"] if e["agent"] == B_MODEL)
    assert b["n"] == 4 and b["pass_rate"] == 0.5
    assert cur["historical_only_agents"] == sorted(MODELS + [H_MODEL])
    assert _ranked(old["entries"]) == sorted(MODELS + [H_MODEL])
    assert B_MODEL not in [e["agent"] for e in old["entries"]]
    assert {e["n"] for e in old["entries"]} == {5}
    assert old["historical_only_agents"] == [B_MODEL]
    assert set(_ranked(cur["entries"])).isdisjoint(_ranked(old["entries"]))


def test_pooled_leaderboard_never_mixes_the_two_populations(versions):
    lb = versions.get("/api/v1/leaderboard").json()
    counts = {e["agent"]: e["n"] for e in lb["entries"]}
    assert counts[B_MODEL] == 4  # only its current-version rows
    assert all(counts[m] == 30 for m in MODELS)  # their stale sanitize rows are not added
    assert counts[X_MODEL] == 4
    assert H_MODEL not in counts
    assert H_MODEL in lb["historical_only_agents"]
    assert B_MODEL not in lb["historical_only_agents"]


def test_current_only_agent_cell_and_old_cells_do_not_bleed(versions):
    b_cell = versions.get(f"/api/v1/cell/{_enc(B_MODEL)}/{SANITIZE}").json()
    assert b_cell["state"] == "captured" and b_cell["aggregate"]["n_valid"] == 4
    assert b_cell["historical_versions"] == [] and b_cell["task_versions"] == [NEW[SANITIZE]]
    a_cell = versions.get(f"/api/v1/cell/{_enc(Q9)}/{SANITIZE}").json()
    assert a_cell["state"] == "historical_only" and a_cell["aggregate"] is None


# --------------------------------------------------------------------------- #
# E. VERSION SEMANTICS payload (incl. task_versions across ALL evidence classes)
# --------------------------------------------------------------------------- #


def test_task_versions_span_all_evidence_classes_while_views_stay_current_only(mockc):
    """qwen3.5:9b x sanitize-filename has stored 1.0.1 (legacy) and 1.0.2 (mock)."""
    cell = mockc.get(f"/api/v1/cell/{_enc(Q9)}/{SANITIZE}").json()
    assert cell["task_versions"] == ["1.0.1", "1.0.2"]  # a persisted fact, scope-independent
    assert cell["state"] == "historical_only"  # the 1.0.2 row is mock: not benchmark evidence
    assert cell["evidence_status"] == "none" and cell["runs"] == [] and cell["aggregate"] is None
    assert [v["version"] for v in cell["versions"]] == ["1.0.1"]
    assert cell["excluded"] == {"synthetic_runs": 1, "provenance_conflict_runs": 0}
    assert cell["current_runs"] == 0 and cell["historical_runs"] == 5
    meta = mockc.get("/api/v1/meta").json()
    task = next(t for t in meta["tasks"] if t["task_id"] == SANITIZE)
    assert task["evaluated_versions"] == ["1.0.1", "1.0.2"]
    assert task["has_current_evidence"] is False and task["current_runs"] == 0
    assert task["historical_versions"] == ["1.0.1"]


def test_synthetic_scope_shows_the_mock_cell_as_current_evidence(mockc):
    cell = mockc.get(f"/api/v1/cell/{_enc(Q9)}/{SANITIZE}?evidence=synthetic").json()
    assert cell["evidence_scope"] == "synthetic"
    assert cell["state"] == "captured" and cell["evidence_status"] == "current"
    assert cell["current_runs"] == 1 and cell["historical_runs"] == 0
    assert cell["selected_version"] == cell["current_version"] == "1.0.2"
    assert cell["task_versions"] == ["1.0.1", "1.0.2"]
    assert cell["runs"][0]["evidence_class"] == "synthetic" and cell["runs"][0]["backend_kind"] == "mock"
    assert cell["aggregate"]["n_valid"] == 1


def test_selected_view_statuses_are_independent_of_cell_state(pristine):
    cell = pristine.get(f"/api/v1/cell/{_enc(Q9)}/{SANITIZE}?version=1.0.1").json()
    assert (cell["state"], cell["evidence_status"]) == ("historical_only", "historical")
    none = pristine.get(f"/api/v1/cell/{_enc(Q9)}/{SANITIZE}?version=5.5.5").json()
    assert (none["state"], none["evidence_status"]) == ("historical_only", "none")
    assert none["selected_version"] == "5.5.5" and none["runs"] == [] and none["aggregate"] is None
    cur = pristine.get(f"/api/v1/cell/{_enc(Q9)}/{TASK}").json()
    assert (cur["state"], cur["evidence_status"]) == ("captured", "current")
    assert cur["selected_version"] == cur["current_version"] == "1.0.0"
    empty = pristine.get(f"/api/v1/cell/{_enc(Q9)}/no-such-task").json()
    assert empty["known_task"] is False and empty["state"] == "not_captured"


def test_synthetic_baseline_cells_keep_priority_over_version_states(pristine):
    cell = pristine.get(f"/api/v1/cell/{_enc('oracle (synthetic baseline)')}/{SANITIZE}").json()
    assert cell["state"] == "synthetic" and cell["evidence_status"] == "synthetic"
    assert cell["synthetic"] is True


def test_mixed_version_scratch_store_is_refused_structurally(pristine_path):
    """The mixed-version invariant survives as a structural guard."""
    stores = load_stores(pristine_path)
    try:
        base = next(r for r in stores.runs if r.is_current)
        alien = LoadedRun(
            dataclasses.replace(base.record, task_version="9.9.9"), base.provenance, False
        )
        with pytest.raises(ValueError, match="refusing to pool multiple task versions"):
            stores.scratch_store([base, alien])
        ok = stores.scratch_store([base])  # one version is fine
        try:
            assert ok.agents() == [base.record.agent]
        finally:
            ok.close()
        # per-version aggregation never pools
        assert stores.aggregate_for(Q9, SANITIZE, "1.0.1").n_valid == 5
        assert stores.aggregate_for(Q9, SANITIZE, "1.0.2") is None
        with pytest.raises(evidence.InvalidEvidenceScope):
            load_stores(pristine_path, evidence_scope="nonsense")
    finally:
        stores.close()


def test_load_stores_never_holds_two_versions_of_a_cell(versions_path):
    stores = load_stores(versions_path)
    try:
        seen: dict[tuple[str, str], set[str]] = {}
        for rec in stores.real.load_runs():
            seen.setdefault((rec.agent, rec.task_id), set()).add(rec.task_version)
        assert all(len(v) == 1 for v in seen.values())
        assert seen[(X_MODEL, TASK)] == {"1.0.0"}
        for rec in stores.full.load_runs():
            assert rec.task_version == TASK_CURRENT[rec.task_id]
    finally:
        stores.close()


# --------------------------------------------------------------------------- #
# F. MALFORMED PARAMETERS FAIL CLOSED
# --------------------------------------------------------------------------- #

SECRET_KEY = "sk-SUPERSECRET-9f3a"
SECRET_PW = "PWSECRET7731"
GARBAGE = "GARBAGE_VALUE_ZZ"


def _dumps(d) -> str:
    return json.dumps(d)  # allow_nan=True: emits the bare NaN literal


def _mut(**over):
    return lambda d: _dumps({**d, **over})


def _drop(key):
    return lambda d: _dumps({k: v for k, v in d.items() if k != key})


def _backend(**over):
    return lambda d: _dumps({**d, "backend": {**d["backend"], **over}})


# id, mutator(valid params dict) -> params_json text, secret markers that must never leak
CORRUPT_CASES = [
    ("malformed-json", lambda d: '{"model": "x", oops ' + GARBAGE, [GARBAGE]),
    ("json-list", lambda d: "[" + f'"{GARBAGE}"' + "]", [GARBAGE]),
    ("json-string", lambda d: f'"{GARBAGE}"', [GARBAGE]),
    ("json-number", lambda d: "424242", []),
    ("json-null", lambda d: "null", []),
    ("missing-model", _drop("model"), []),
    ("model-wrong-type", _mut(model=[GARBAGE]), [GARBAGE]),
    ("invalid-backend-kind", _backend(kind=f"{GARBAGE}-kind"), [GARBAGE]),
    ("backend-string", _mut(backend=GARBAGE), [GARBAGE]),
    ("backend-list", _mut(backend=[GARBAGE]), [GARBAGE]),
    ("backend-null", _mut(backend=None), []),
    ("missing-backend", _drop("backend"), []),
    ("repeats-zero", _mut(repeats=0), []),
    ("repeats-negative", _mut(repeats=-1), []),
    ("repeats-string", _mut(repeats="2"), []),
    ("temperature-string", _mut(temperature=GARBAGE), [GARBAGE]),
    ("temperature-nan", lambda d: _dumps({**d, "temperature": float("nan")}), []),
    ("temperature-null", _mut(temperature=None), []),
    ("timeout-zero", _mut(request_timeout_s=0), []),
    ("missing-tasks", _drop("tasks"), []),
    ("empty-tasks", _mut(tasks=[]), []),
    ("duplicate-tasks", _mut(tasks=[TASK, TASK]), []),
    ("credential-url", _backend(base_url=f"http://user:{SECRET_PW}@host"), [SECRET_PW]),
    ("credential-extra-key", _backend(api_key=SECRET_KEY), [SECRET_KEY]),
    ("query-secret-url", _backend(base_url=f"http://localhost:11434/?token={SECRET_KEY}"), [SECRET_KEY]),
]

# Individually VALID params that contradict the creation snapshot.
CONTRADICTION_CASES = [
    ("model-changed", _mut(model="a-different-model"), []),
    ("backend-kind-changed-to-mock", _backend(kind="mock"), []),
    ("backend-kind-changed-to-openai", _backend(kind="openai_compat"), []),
    ("backend-url-changed", _backend(base_url="http://localhost:9999"), []),
    ("base-seed-changed", _mut(base_seed=8), []),
    ("temperature-changed", _mut(temperature=0.9), []),
    ("timeout-changed", _mut(request_timeout_s=31), []),
    ("repeats-changed", _mut(repeats=3), []),
    ("tasks-changed", _mut(tasks=["escape-html"]), []),
]

ALL_FAIL_CASES = CORRUPT_CASES + CONTRADICTION_CASES
_CASE_IDS = [c[0] for c in ALL_FAIL_CASES]


def _case(cid):
    return next(c for c in ALL_FAIL_CASES if c[0] == cid)


def _make_valid_job(path: Path, *, kind: str = "ollama", repeats: int = 2, status: str = "queued") -> str:
    """A genuine non-legacy evaluation created through the public API (no dispatch)."""
    conn = db.connect(path)
    try:
        backend = (
            Backend(kind="ollama", base_url="http://localhost:11434") if kind == "ollama" else Backend(kind=kind)
        )
        job = jobs.create_job(
            conn,
            JobCreate(
                model="corrupt-model",
                backend=backend,
                tasks=[TASK],
                repeats=repeats,
                base_seed=7,
                temperature=0.3,
                request_timeout_s=30,
            ),
        )
        if status == "running":
            assert jobs.claim_job_token(conn, job.id, "dead-owner") == "dead-owner"
        return job.id
    finally:
        conn.close()


def _corrupt(path: Path, job_id: str, mutator) -> str:
    conn = sqlite3.connect(str(path))
    try:
        raw = conn.execute("SELECT params_json FROM evaluation_jobs WHERE id=?", (job_id,)).fetchone()[0]
        text = mutator(json.loads(raw))
        conn.execute("UPDATE evaluation_jobs SET params_json=? WHERE id=?", (text, job_id))
        conn.commit()
        return text
    finally:
        conn.close()


def _dump(path: Path) -> dict:
    conn = _ro(path)
    try:
        return {
            "jobs": [tuple(r) for r in conn.execute("SELECT * FROM evaluation_jobs ORDER BY id")],
            "trials": [tuple(r) for r in conn.execute("SELECT * FROM evaluation_trials ORDER BY rowid")],
            "events": [tuple(r) for r in conn.execute("SELECT * FROM job_events ORDER BY rowid")],
            "job_runs": [tuple(r) for r in conn.execute("SELECT * FROM job_runs ORDER BY rowid")],
            "runs": conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0],
        }
    finally:
        conn.close()


def _job_text(path: Path, job_id: str) -> str:
    """Everything persisted about the job that a client or operator could read back."""
    conn = _ro(path)
    try:
        parts = [
            str(conn.execute("SELECT error_message FROM evaluation_jobs WHERE id=?", (job_id,)).fetchone()[0]),
            *[str(r[0]) for r in conn.execute("SELECT error_message FROM evaluation_trials WHERE evaluation_id=?", (job_id,))],
            *[str(r[0]) for r in conn.execute("SELECT payload_json FROM job_events WHERE job_id=?", (job_id,))],
        ]
        return "\n".join(parts)
    finally:
        conn.close()


def _assert_failed_closed(path: Path, job_id: str, spy: SpyFactory, counter, runs_before: int, secrets):
    assert spy.calls == [], "the agent factory was called for an unverifiable evaluation"
    assert counter["n"] == 0, "an agent ran for an unverifiable evaluation"
    conn = _ro(path)
    try:
        row = conn.execute("SELECT status, error_message, owner_token FROM evaluation_jobs WHERE id=?", (job_id,)).fetchone()
        assert row["status"] == "failed"
        assert row["error_message"].startswith(INVALID_PREFIX), row["error_message"]
        assert row["owner_token"] is None
        assert conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == runs_before
        assert conn.execute("SELECT COUNT(*) FROM job_runs WHERE job_id=?", (job_id,)).fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM runs WHERE job_id=?", (job_id,)).fetchone()[0] == 0
        trials = conn.execute("SELECT * FROM evaluation_trials WHERE evaluation_id=?", (job_id,)).fetchall()
        assert trials
        for trial in trials:
            assert trial["trial_state"] == "blocked", dict(trial)
            assert trial["evidence_state"] == "unverifiable", dict(trial)
            assert trial["run_id"] is None
            assert (trial["error_message"] or "").startswith(INVALID_PREFIX)
        types = {r[0] for r in conn.execute("SELECT type FROM job_events WHERE job_id=?", (job_id,))}
        assert "run_started" not in types and "run_persisted" not in types and "run_graded" not in types
        job = jobs.get_job(conn, job_id)
        assert job.counters.completed_runs == 0
    finally:
        conn.close()
    text = _job_text(path, job_id)
    for secret in secrets:
        assert secret not in text, f"secret/garbage {secret!r} leaked into persisted error text"


@pytest.mark.parametrize("cid,mutator,secrets", ALL_FAIL_CASES, ids=_CASE_IDS)
def test_corrupt_or_contradictory_params_never_reach_an_agent(
    evcopy, run_once_counter, cid, mutator, secrets
):
    job_id = _make_valid_job(evcopy)
    _corrupt(evcopy, job_id, mutator)
    runs_before = _scalar(evcopy, "SELECT COUNT(*) FROM runs")
    spy = SpyFactory()
    conn = db.connect(evcopy)
    try:
        assert worker.claim_and_run(conn, agent_factory=spy) == job_id
    finally:
        conn.close()
    _assert_failed_closed(evcopy, job_id, spy, run_once_counter, runs_before, secrets)


@pytest.mark.parametrize(
    "cid", ["malformed-json", "missing-model", "invalid-backend-kind", "credential-url", "model-changed", "backend-kind-changed-to-mock"]
)
def test_default_factory_selection_is_never_reached_for_unverifiable_params(evcopy, monkeypatch, run_once_counter, cid):
    """With NO injected factory the worker would call factory_for(params); a corrupt
    row must not even get that far (it must never degrade to the mock factory)."""
    _, mutator, secrets = _case(cid)
    reached: list[object] = []
    monkeypatch.setattr(worker, "factory_for", lambda params: reached.append(params) or worker.mock_agent_factory)
    job_id = _make_valid_job(evcopy)
    _corrupt(evcopy, job_id, mutator)
    runs_before = _scalar(evcopy, "SELECT COUNT(*) FROM runs")
    conn = db.connect(evcopy)
    try:
        assert worker.claim_and_run(conn) == job_id
    finally:
        conn.close()
    assert reached == []
    _assert_failed_closed(evcopy, job_id, SpyFactory(), run_once_counter, runs_before, secrets)


@pytest.mark.parametrize("cid,mutator,secrets", CORRUPT_CASES, ids=[c[0] for c in CORRUPT_CASES])
def test_corrupt_job_stays_listable_and_never_echoes_secrets(evcopy, cid, mutator, secrets):
    """One corrupt row must not break the listing of every job (no 500), and none
    of its garbage or credentials may be echoed by the control-plane API."""
    job_id = _make_valid_job(evcopy)
    _corrupt(evcopy, job_id, mutator)
    with _client(evcopy, auto_dispatch=False, raise_exceptions=False) as client:
        listing = client.get("/api/v1/jobs")
        assert listing.status_code == 200, "one corrupt row must not break the listing of every job"
        one = client.get(f"/api/v1/jobs/{job_id}")
        assert one.status_code == 200
        assert any(j["id"] == job_id for j in listing.json()["jobs"])
        assert one.json()["backend_kind"] == "ollama"  # from the creation snapshot, not params
        for secret in secrets:
            assert secret not in listing.text and secret not in one.text
        assert "NaN" not in one.text and "NaN" not in listing.text


@pytest.mark.parametrize("cid,mutator,secrets", CORRUPT_CASES, ids=[c[0] for c in CORRUPT_CASES])
def test_corrupt_params_are_reported_unverifiable_never_defaulted_or_laundered(evcopy, cid, mutator, secrets):
    """Job.params must be null / params_status 'unverifiable' whenever the persisted
    parameters could not be executed. A lenient display parse (coercing '2' to 2,
    accepting NaN, dropping an unknown 'api_key' key, tolerating empty tasks) would
    present an unexecutable evaluation as ordinary and available."""
    job_id = _make_valid_job(evcopy)
    _corrupt(evcopy, job_id, mutator)
    with _client(evcopy, auto_dispatch=False, raise_exceptions=False) as client:
        listing = client.get("/api/v1/jobs")
        one = client.get(f"/api/v1/jobs/{job_id}")
        assert listing.status_code == 200 and one.status_code == 200
        for body in (next(j for j in listing.json()["jobs"] if j["id"] == job_id), one.json()):
            assert body["params"] is None, "unexecutable params were shown as a parsed/available object"
            assert body["params_status"] == "unverifiable"
            assert body["params_error"].startswith(INVALID_PREFIX)
            for secret in secrets:
                assert secret not in body["params_error"]


@pytest.mark.parametrize("cid", ["credential-url", "credential-extra-key", "malformed-json"])
def test_reports_of_a_failed_unverifiable_job_do_not_leak(evcopy, cid):
    _, mutator, secrets = _case(cid)
    job_id = _make_valid_job(evcopy)
    _corrupt(evcopy, job_id, mutator)
    conn = db.connect(evcopy)
    try:
        assert worker.claim_and_run(conn, agent_factory=SpyFactory()) == job_id
    finally:
        conn.close()
    with _client(evcopy, auto_dispatch=False) as client:
        for url in (
            f"/api/v1/jobs/{job_id}/report.json",
            f"/api/v1/jobs/{job_id}/report.md",
            f"/api/v1/jobs/{job_id}/results",
            f"/api/v1/jobs/{job_id}/events?since=0",
            f"/api/v1/jobs/{job_id}",
        ):
            resp = client.get(url)
            assert resp.status_code == 200, url
            for secret in secrets:
                assert secret not in resp.text, url
    report = None
    with _client(evcopy, auto_dispatch=False) as client:
        report = client.get(f"/api/v1/jobs/{job_id}/report.json").json()
    assert report["status"] == "failed"
    assert report["counters"]["completed"] == 0 and report["counters"]["incomplete"] == 2
    assert all(t["outcome"] is None and t["trial_state"] == "blocked" for t in report["trials"])


def test_a_valid_job_still_runs_after_the_strict_parse(evcopy, run_once_counter):
    """Control: strictness must not reject genuine parameters (no false positives)."""
    for kind, backend in (("mock", Backend(kind="mock")), ("ollama", Backend(kind="ollama", base_url="http://localhost:11434")),
                          ("openai_compat", Backend(kind="openai_compat"))):
        conn = db.connect(evcopy)
        try:
            job = jobs.create_job(conn, JobCreate(model=f"ctl-{kind}", backend=backend, tasks=[TASK], repeats=1))
            params = jobs.execution_params(conn, job.id)
            assert params.model == f"ctl-{kind}" and params.backend.kind == kind
        finally:
            conn.close()
    spy = SpyFactory()
    conn = db.connect(evcopy)
    try:
        while worker.claim_and_run(conn, agent_factory=spy) is not None:
            pass
    finally:
        conn.close()
    assert sorted(m for m, _ in spy.calls) == ["ctl-mock", "ctl-ollama", "ctl-openai_compat"]
    assert run_once_counter["n"] == 3


# --------------------------------------------------------------------------- #
# G. STARTUP RECOVERY / RESUME / RETRY
# --------------------------------------------------------------------------- #

G_IDS = ["malformed-json", "missing-model", "invalid-backend-kind", "repeats-zero", "credential-url", "model-changed", "tasks-changed"]


def _assert_recovered_as_unverifiable(path: Path, job_id: str):
    conn = _ro(path)
    try:
        job = jobs.get_job(conn, job_id)
        assert job.status == "failed", job.status
        assert job.error_message.startswith(INVALID_PREFIX)
        rows = jobs.trial_rows(conn, job_id)
        assert rows and all(r["trial_state"] == "blocked" and r["evidence_state"] == "unverifiable" for r in rows)
        assert conn.execute("SELECT owner_token FROM evaluation_jobs WHERE id=?", (job_id,)).fetchone()[0] is None
        assert conn.execute("SELECT COUNT(*) FROM runs WHERE job_id=?", (job_id,)).fetchone()[0] == 0
        assert "job_failed" in {e.type for e in jobs.events_since(conn, job_id)}
    finally:
        conn.close()


@pytest.mark.parametrize("cid", G_IDS)
def test_reclaim_never_requeues_an_orphan_with_unverifiable_params(evcopy, cid):
    _, mutator, secrets = _case(cid)
    job_id = _make_valid_job(evcopy, status="running")
    _corrupt(evcopy, job_id, mutator)
    conn = db.connect(evcopy)
    try:
        reclaimed = jobs.reclaim_stale_running(conn, recover_unlocked=True)
        assert job_id not in reclaimed and reclaimed == []
        assert not conn.in_transaction
        # a second pass is stable: nothing to reclaim, nothing dispatchable
        assert jobs.reclaim_stale_running(conn, recover_unlocked=True) == []
        assert jobs.claim_next_queued_token(conn) is None
    finally:
        conn.close()
    _assert_recovered_as_unverifiable(evcopy, job_id)
    for secret in secrets:
        assert secret not in _job_text(evcopy, job_id)


def test_reclaim_by_age_alone_also_fails_closed(evcopy):
    """Not only the startup 'recover_unlocked' path: a stale lease is guarded too."""
    job_id = _make_valid_job(evcopy, status="running")
    _exec(evcopy, "UPDATE evaluation_jobs SET owner_started_at=datetime('now','-1 hour') WHERE id=?", (job_id,))
    _corrupt(evcopy, job_id, _case("missing-model")[1])
    conn = db.connect(evcopy)
    try:
        assert jobs.reclaim_stale_running(conn) == []
    finally:
        conn.close()
    _assert_recovered_as_unverifiable(evcopy, job_id)


@pytest.mark.parametrize("cid", ["malformed-json", "invalid-backend-kind", "model-changed"])
def test_app_lifespan_does_not_dispatch_an_unverifiable_orphan(evcopy, run_once_counter, cid):
    _, mutator, _ = _case(cid)
    job_id = _make_valid_job(evcopy, status="running")
    _corrupt(evcopy, job_id, mutator)
    runs_before = _scalar(evcopy, "SELECT COUNT(*) FROM runs")
    spy = SpyFactory()
    with _client(evcopy, factory=spy) as client:  # auto_dispatch stays at its default (True)
        _join_dispatch_threads()
        time.sleep(0.3)
        _join_dispatch_threads()
        body = client.get(f"/api/v1/jobs/{job_id}").json()
        assert body["status"] == "failed"
        assert body["error_message"].startswith(INVALID_PREFIX)
        assert client.get("/api/v1/healthz").json()["status"] == "ok"
    assert spy.calls == [] and run_once_counter["n"] == 0
    assert _scalar(evcopy, "SELECT COUNT(*) FROM runs") == runs_before
    _assert_recovered_as_unverifiable(evcopy, job_id)


@pytest.mark.parametrize("cid", G_IDS)
def test_resume_and_retry_of_an_unverifiable_job_are_409_and_mutate_nothing(evcopy, cid):
    _, mutator, _ = _case(cid)
    job_id = _make_valid_job(evcopy, status="running")
    _corrupt(evcopy, job_id, mutator)
    conn = db.connect(evcopy)
    try:
        jobs.reclaim_stale_running(conn, recover_unlocked=True)
    finally:
        conn.close()
    before = _dump(evcopy)
    spy = SpyFactory()
    with _client(evcopy, factory=spy) as client:
        assert client.post(f"/api/v1/jobs/{job_id}/resume").status_code == 409
        assert client.post(f"/api/v1/jobs/{job_id}/retry").status_code == 409
        assert client.post(f"/api/v1/jobs/{job_id}/cancel").status_code == 200  # cancel of a terminal job is inert
        _join_dispatch_threads()
    assert spy.calls == []
    after = _dump(evcopy)
    assert after["jobs"] == before["jobs"] and after["trials"] == before["trials"]
    assert after["events"] == before["events"] and after["runs"] == before["runs"]
    assert len(after["jobs"]) == len(before["jobs"])  # retry did not clone a job


@pytest.mark.parametrize("cid", G_IDS)
def test_library_resume_and_retry_raise_before_mutating(evcopy, cid):
    _, mutator, _ = _case(cid)
    job_id = _make_valid_job(evcopy, status="running")
    _corrupt(evcopy, job_id, mutator)
    before = _dump(evcopy)
    conn = db.connect(evcopy)
    try:
        with pytest.raises(jobs.JobStateError):
            jobs.resume_job(conn, job_id)  # still 'running': must fail before reclaiming
        assert not conn.in_transaction
    finally:
        conn.close()
    assert _dump(evcopy) == before
    conn = db.connect(evcopy)
    try:
        jobs.reclaim_stale_running(conn, recover_unlocked=True)
        with pytest.raises(jobs.InvalidPersistedParams):
            jobs.retry_job(conn, job_id)
        with pytest.raises(jobs.InvalidPersistedParams):
            jobs.resume_job(conn, job_id)
    finally:
        conn.close()
    assert _scalar(evcopy, "SELECT COUNT(*) FROM evaluation_jobs WHERE status='queued'") == 0


def test_http_resume_of_a_running_unverifiable_job_is_409_and_inert(evcopy):
    spy = SpyFactory()
    with _client(evcopy, factory=spy, auto_dispatch=False) as client:
        created = client.post(
            "/api/v1/jobs",
            json={"model": "later-corrupted", "backend": {"kind": "ollama", "base_url": "http://localhost:11434"},
                  "tasks": [TASK], "repeats": 1},
        ).json()
        conn = db.connect(evcopy)
        try:
            assert jobs.claim_job_token(conn, created["id"], "dead-owner") == "dead-owner"
        finally:
            conn.close()
        _corrupt(evcopy, created["id"], _case("missing-model")[1])
        before = _dump(evcopy)
        resp = client.post(f"/api/v1/jobs/{created['id']}/resume")
        assert resp.status_code == 409 and INVALID_PREFIX in resp.json()["error"]
        assert _dump(evcopy) == before
        assert client.get(f"/api/v1/jobs/{created['id']}").json()["status"] == "running"
    assert spy.calls == []


def test_control_valid_interrupted_job_is_still_recovered_and_dispatched(evcopy, run_once_counter):
    """Recovery must keep working for a job whose parameters are intact."""
    job_id = _make_valid_job(evcopy, kind="mock", repeats=1, status="running")
    conn = db.connect(evcopy)
    try:
        assert jobs.reclaim_stale_running(conn, recover_unlocked=True) == [job_id]
        assert jobs.get_job(conn, job_id).status == "queued"
        assert {r["trial_state"] for r in jobs.trial_rows(conn, job_id)} == {"pending"}
    finally:
        conn.close()


def test_control_valid_interrupted_job_runs_through_the_app_lifespan(tmp_path, run_once_counter):
    path = tmp_path / "control.sqlite"
    shutil.copy(db.EVIDENCE_DB_PATH, path)
    conn = db.connect(path)
    try:
        job = jobs.create_job(conn, JobCreate(model="control-model", backend=Backend(kind="mock"), tasks=[TASK], repeats=1))
        assert jobs.claim_job_token(conn, job.id, "dead-owner") == "dead-owner"
    finally:
        conn.close()
    spy = SpyFactory()
    with _client(path, factory=spy) as client:
        body = _wait_terminal(client, job.id)
        assert body["status"] == "succeeded", body["error_message"]
        _join_dispatch_threads()
    assert spy.calls == [("control-model", TASK)]
    assert run_once_counter["n"] == 1
    kinds = _rows(path, "SELECT backend_kind FROM runs WHERE job_id=?", (job.id,))
    assert kinds == [("mock",)]


# --------------------------------------------------------------------------- #
# H. RAW BACKEND PROVENANCE
# --------------------------------------------------------------------------- #


class _Loopback:
    """A local fake model server speaking both OpenAI-compatible and Ollama APIs."""

    def __init__(self) -> None:
        self.requests: list[tuple[str, dict]] = []
        reference = (REPO / "tasks" / TASK / "reference" / "searchkit" / "search.py").read_text()
        text = f"# FILE: searchkit/search.py\n```python\n{reference}\n```"
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):  # noqa: N802
                length = int(self.headers["Content-Length"])
                payload = json.loads(self.rfile.read(length))
                outer.requests.append((self.path, payload))
                if self.path == "/v1/chat/completions":
                    body = {"choices": [{"message": {"content": text}}]}
                elif self.path == "/api/generate":
                    body = {"response": text}
                else:
                    self.send_response(404)
                    self.end_headers()
                    return
                raw = json.dumps(body).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def log_message(self, *_args):
                return

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.server.server_port}"

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(5)


class ProvenanceWorld:
    def __init__(self):
        self.path: Path
        self.snapshot: Path
        self.jobs: dict[str, str] = {}
        self.models: dict[str, str] = {}
        self.loopback_requests: list[tuple[str, dict]] = []


@pytest.fixture(scope="module")
def provenance_world(tmp_path_factory):
    root = tmp_path_factory.mktemp("provworld")
    path = root / "prov-world.sqlite"
    shutil.copy(db.EVIDENCE_DB_PATH, path)
    world = ProvenanceWorld()
    world.path = path
    loop = _Loopback()
    try:
        plan = [
            # key, model, requested kind, factory ("real" = worker.factory_for), base_url
            ("declared-ollama", "sim-ollama-model", "ollama", _declaring_factory("ollama"), None),
            ("declared-openai", "sim-openai-model", "openai_compat", _declaring_factory("openai_compat"), None),
            ("undeclared", "sim-undeclared-model", "ollama", _declaring_factory(None), None),
            ("liar", "sim-liar-model", "ollama", _declaring_factory("mock"), None),
            ("loop-openai", "loopback-openai-model", "openai_compat", None, loop.url),
            ("loop-ollama", "loopback-ollama-model", "ollama", None, loop.url),
        ]
        for key, model, kind, factory, base_url in plan:
            job = _run_eval(path, model, kind=kind, factory=factory, base_url=base_url)
            world.jobs[key] = job.id
            world.models[key] = model
        world.loopback_requests = list(loop.requests)
    finally:
        loop.close()
    world.snapshot = root / "prov-world-snapshot.sqlite"
    shutil.copy(path, world.snapshot)
    return world


@pytest.fixture(scope="module")
def provc(provenance_world):
    with _client(provenance_world.path) as client:
        yield client


def _backend_of(path: Path, job_id: str) -> list[str | None]:
    return [r[0] for r in _rows(path, "SELECT backend_kind FROM runs WHERE job_id=? ORDER BY id", (job_id,))]


def test_new_mock_evaluations_persist_backend_kind_mock(mock_world):
    assert set(mock_world.a_runs) == {TASK, SANITIZE}
    assert _backend_of(mock_world.path, mock_world.a_job) == ["mock", "mock"]
    assert _backend_of(mock_world.path, mock_world.b_job) == ["mock", "mock"]
    trials = _rows(
        mock_world.path,
        "SELECT t.evidence_state FROM evaluation_trials t WHERE t.evaluation_id=?",
        (mock_world.a_job,),
    )
    assert trials == [("fresh",), ("fresh",)]


def test_mock_evaluation_report_trials_are_consistent_and_comparable(mockc, mock_world):
    report = mockc.get(f"/api/v1/jobs/{mock_world.a_job}/report.json").json()
    assert report["provider"] == "mock" and report["status"] == "succeeded"
    for trial in report["trials"]:
        assert trial["backend_kind"] == "mock" and trial["provenance"] == "consistent"
        assert trial["comparability"] == "comparable" and "integrity_error" not in trial
    md = mockc.get(f"/api/v1/jobs/{mock_world.a_job}/report.md").text
    assert "Provenance: `consistent`" in md and "Backend: `mock`" in md
    job = mockc.get(f"/api/v1/jobs/{mock_world.a_job}").json()
    assert job["backend_kind"] == "mock" and job["evidence_class"] == "synthetic"
    assert job["params_status"] == "available" and job["params"]["model"] == MOCK_REAL_NAME


@pytest.mark.parametrize(
    "key,kind",
    [("declared-ollama", "ollama"), ("declared-openai", "openai_compat"), ("undeclared", "ollama")],
)
def test_declared_or_requested_backend_kind_is_persisted(provenance_world, provc, key, kind):
    job_id = provenance_world.jobs[key]
    assert _backend_of(provenance_world.path, job_id) == [kind]
    trial = provc.get(f"/api/v1/jobs/{job_id}/report.json").json()["trials"][0]
    assert trial["backend_kind"] == kind and trial["provenance"] == "consistent"
    assert trial["comparability"] == "comparable"
    job = provc.get(f"/api/v1/jobs/{job_id}").json()
    assert job["backend_kind"] == kind and job["evidence_class"] == "real"


def test_a_factory_that_really_drives_mock_is_recorded_as_mock_and_flagged(provenance_world, provc):
    """Requested ollama, but the factory that ran is the mock: the run must say so
    (never be persisted as ollama evidence) and the disagreement must surface."""
    job_id = provenance_world.jobs["liar"]
    assert _backend_of(provenance_world.path, job_id) == ["mock"]
    trial = provc.get(f"/api/v1/jobs/{job_id}/report.json").json()["trials"][0]
    assert trial["backend_kind"] == "mock" and trial["provenance"] == "mismatch"
    assert trial.get("comparability") is None and trial["integrity_error"]
    run_id = _rows(provenance_world.path, "SELECT id FROM runs WHERE job_id=?", (job_id,))[0][0]
    run = provc.get(f"/api/v1/runs/{run_id}").json()
    assert run["evidence_class"] == "conflict" and run["backend_kind"] == "mock"


def test_real_backend_evidence_enters_the_benchmark_scope(provenance_world, provc):
    ov = provc.get("/api/v1/overview").json()
    for key in ("declared-ollama", "declared-openai", "undeclared", "loop-openai", "loop-ollama"):
        model = provenance_world.models[key]
        assert ov["real_counts"][model] == {"n_runs": 1, "n_tasks": 1}, model
        assert ov["evidence_counts"][model]["current_by_class"] == {"real": 1}, model
    assert provenance_world.models["liar"] not in ov["models"]  # conflict: excluded
    assert ov["excluded"]["provenance_conflict_runs"] == 1
    assert ov["excluded"]["synthetic_runs"] == 0
    # legacy evidence is unchanged next to the real runs
    assert all(ov["real_counts"][m] == {"n_runs": 30, "n_tasks": 6} for m in MODELS)
    real = provc.get("/api/v1/overview?evidence=real").json()
    assert real["models"] == sorted(
        provenance_world.models[k]
        for k in ("declared-ollama", "declared-openai", "undeclared", "loop-openai", "loop-ollama")
    )
    assert set(m for m in real["models"]).isdisjoint(MODELS)
    assert real["current_benchmark"]["current_runs"] == 5
    assert real["excluded"]["provenance_conflict_runs"] == 1


def test_openai_and_ollama_loopback_use_the_real_factories(provenance_world):
    assert sorted(p for p, _ in provenance_world.loopback_requests) == ["/api/generate", "/v1/chat/completions"]
    by_path = {p: payload for p, payload in provenance_world.loopback_requests}
    assert by_path["/v1/chat/completions"]["model"] == "loopback-openai-model"
    assert by_path["/api/generate"]["model"] == "loopback-ollama-model"
    for key, kind in (("loop-openai", "openai_compat"), ("loop-ollama", "ollama")):
        job_id = provenance_world.jobs[key]
        assert _backend_of(provenance_world.path, job_id) == [kind]
        rows = _rows(
            provenance_world.path,
            "SELECT r.status, s.functional_pass FROM runs r JOIN run_scores s ON s.run_id=r.id WHERE r.job_id=?",
            (job_id,),
        )
        assert rows == [("valid", 1)]  # the reference answer really went through the transport


@pytest.mark.parametrize(
    "kind,attr,agent_cls",
    [("mock", "mock_agent_factory", "MockAgent"),
     ("ollama", "ollama_agent_factory", "OllamaAgent"),
     ("openai_compat", "openai_compat_agent_factory", "OpenAICompatAgent")],
)
def test_factory_for_returns_factories_that_declare_their_backend(kind, attr, agent_cls):
    params = JobParams(model="m", backend=Backend(kind=kind), tasks=[TASK])
    factory = worker.factory_for(params)
    assert factory is getattr(worker, attr)
    assert factory.backend_kind == kind
    task = afa.load_task(REPO / "tasks" / TASK)
    agent = factory("m", task, params)
    assert type(agent).__name__ == agent_cls


def test_legacy_rows_keep_null_backend_kind_forever(mock_world, provenance_world, evcopy):
    for path in (mock_world.path, provenance_world.path):
        assert _scalar(path, "SELECT COUNT(*) FROM runs WHERE backend_kind IS NULL") == 720
        assert _scalar(path, "SELECT COUNT(*) FROM runs WHERE job_id IS NULL") == 720
        assert _scalar(path, "SELECT COUNT(*) FROM runs WHERE job_id IS NOT NULL AND backend_kind IS NULL") == 0
    conn = db.connect(evcopy)
    try:
        db.migrate(conn)
        db.migrate(conn)
    finally:
        conn.close()
    assert _scalar(evcopy, "SELECT COUNT(*) FROM runs WHERE backend_kind IS NOT NULL") == 0
    assert _scalar(evcopy, "SELECT COUNT(*) FROM runs") == 720
    ev = sqlite3.connect(f"file:{db.EVIDENCE_DB_PATH}?mode=ro&immutable=1", uri=True)
    try:
        assert "backend_kind" not in [r[1] for r in ev.execute("PRAGMA table_info(runs)")]
    finally:
        ev.close()


def test_save_run_rejects_an_unknown_backend_kind(evcopy):
    conn = db.connect(evcopy)
    try:
        db.migrate(conn)
    finally:
        conn.close()
    store = afa.SqliteRunStore(evcopy)
    try:
        with pytest.raises(ValueError):
            store.save_run(_record("bad-kind-model"), backend_kind="hosted-api")
    finally:
        store.close()
    assert _scalar(evcopy, "SELECT COUNT(*) FROM runs WHERE agent='bad-kind-model'") == 0


# --------------------------------------------------------------------------- #
# I. MOCK EXCLUDED FROM THE DEFAULT RANKING
# --------------------------------------------------------------------------- #


def test_mock_evaluation_under_a_real_name_does_not_move_the_default_views(mockc, pristine):
    base = pristine.get("/api/v1/overview").json()
    now = mockc.get("/api/v1/overview").json()
    for key in ("leaderboard", "real_counts", "evidence_counts", "current_benchmark", "models",
                "current_models", "historical_only_models"):
        assert now[key] == base[key], key
    assert now["excluded"] == {
        "synthetic_runs": 4,  # 2 (qwen3.5:9b: fbs + sanitize) + 2 (mock-only-model)
        "synthetic_models": sorted([MOCK_REAL_NAME, MOCK_ONLY]),
        "provenance_conflict_runs": 0,
    }
    assert MOCK_ONLY not in now["models"] and MOCK_ONLY not in now["real_counts"]
    assert MOCK_ONLY not in [e["agent"] for e in now["leaderboard"]]
    # only the whole-DB persisted provenance sees the extra rows
    assert now["observability"]["total_runs"] == 724 and base["observability"]["total_runs"] == 720


def test_mock_evaluation_does_not_move_leaderboard_domains_cell_export(mockc, pristine):
    for url in (
        "/api/v1/leaderboard",
        f"/api/v1/leaderboard?task_id={TASK}",
        f"/api/v1/domains/{_enc(MOCK_REAL_NAME)}",
        f"/api/v1/cell/{_enc(MOCK_REAL_NAME)}/{TASK}",
    ):
        a, b = pristine.get(url), mockc.get(url)
        assert a.status_code == b.status_code == 200, url
        assert a.json() == b.json() or _only_excluded_differs(a.json(), b.json()), url
    cell = mockc.get(f"/api/v1/cell/{_enc(MOCK_REAL_NAME)}/{TASK}").json()
    assert cell["aggregate"]["n_valid"] == 5 and cell["current_runs"] == 5
    assert cell["excluded"] == {"synthetic_runs": 1, "provenance_conflict_runs": 0}
    assert {r["evidence_class"] for r in cell["runs"]} == {"legacy"}
    export = mockc.get("/api/v1/export").json()
    assert MOCK_ONLY not in export["models"]
    assert {e["n"] for e in export["leaderboard"]} == {30}
    assert export["excluded"]["synthetic_runs"] == 4


def _only_excluded_differs(a: dict, b: dict) -> bool:
    strip = lambda d: {k: v for k, v in d.items() if k != "excluded"}  # noqa: E731
    return strip(a) == strip(b)


def test_mock_only_model_is_absent_from_default_reads_but_counted_as_excluded(mockc):
    meta = mockc.get("/api/v1/meta").json()
    assert MOCK_ONLY not in meta["models"] and MOCK_ONLY not in meta["current_models"]
    assert meta["excluded"]["synthetic_models"] == sorted([MOCK_REAL_NAME, MOCK_ONLY])
    dom = mockc.get(f"/api/v1/domains/{_enc(MOCK_ONLY)}").json()
    assert dom["captured"] is False and dom["evidence_status"] == "none"
    cell = mockc.get(f"/api/v1/cell/{_enc(MOCK_ONLY)}/{TASK}").json()
    assert cell["state"] == "not_captured" and cell["runs"] == [] and cell["aggregate"] is None
    assert cell["excluded"]["synthetic_runs"] == 2
    assert cell["task_versions"] == [TASK_CURRENT[TASK]]  # still a persisted fact
    lb = mockc.get(f"/api/v1/leaderboard?task_id={TASK}").json()
    assert MOCK_ONLY not in [e["agent"] for e in lb["entries"]]


def test_synthetic_and_all_scopes_expose_the_mock_evidence(mockc):
    syn = mockc.get("/api/v1/overview?evidence=synthetic").json()
    assert syn["evidence_scope"] == "synthetic"
    assert syn["models"] == sorted([MOCK_REAL_NAME, MOCK_ONLY])
    assert syn["real_counts"][MOCK_REAL_NAME] == {"n_runs": 2, "n_tasks": 2}
    assert syn["real_counts"][MOCK_ONLY] == {"n_runs": 2, "n_tasks": 1}
    assert syn["current_benchmark"]["current_runs"] == 4
    assert syn["excluded"]["synthetic_runs"] == 0  # they ARE the scope
    assert {e["agent"]: e["n"] for e in syn["leaderboard"]} == {MOCK_REAL_NAME: 2, MOCK_ONLY: 2}
    everything = mockc.get("/api/v1/overview?evidence=all").json()
    assert everything["real_counts"][MOCK_REAL_NAME] == {"n_runs": 32, "n_tasks": 7}
    assert everything["real_counts"][MOCK_ONLY] == {"n_runs": 2, "n_tasks": 1}
    assert everything["current_benchmark"]["current_runs"] == 184
    entry = next(e for e in everything["leaderboard"] if e["agent"] == MOCK_REAL_NAME)
    assert entry["n"] == 32
    assert everything["excluded"] == {"synthetic_runs": 0, "synthetic_models": [], "provenance_conflict_runs": 0}
    cell = mockc.get(f"/api/v1/cell/{_enc(MOCK_ONLY)}/{TASK}?evidence=synthetic").json()
    assert cell["state"] == "captured" and cell["current_runs"] == 2
    assert {r["evidence_class"] for r in cell["runs"]} == {"synthetic"}
    assert cell["excluded"]["synthetic_runs"] == 0
    dom = mockc.get(f"/api/v1/domains/{_enc(MOCK_ONLY)}?evidence=synthetic").json()
    assert dom["captured"] is True and dom["evidence_scope"] == "synthetic"
    assert mockc.get("/api/v1/meta?evidence=synthetic").json()["current_models"] == sorted([MOCK_REAL_NAME, MOCK_ONLY])
    assert mockc.get("/api/v1/export?evidence=synthetic").json()["models"] == sorted([MOCK_REAL_NAME, MOCK_ONLY])
    lb = mockc.get(f"/api/v1/leaderboard?task_id={TASK}&evidence=synthetic").json()
    assert _ranked(lb["entries"]) == sorted([MOCK_REAL_NAME, MOCK_ONLY])
    assert mockc.get("/api/v1/overview?evidence=real").json()["models"] == []


def test_mock_runs_stay_inspectable_through_forensic_and_evaluation_routes(mockc, mock_world):
    run_id = mock_world.a_runs[TASK]
    body = mockc.get(f"/api/v1/runs/{run_id}").json()
    assert body["found"] is True and body["job_id"] == mock_world.a_job
    assert body["evidence_class"] == "synthetic" and body["backend_kind"] == "mock"
    assert body["provider_source"] == "run" and body["version_status"] == "current"
    assert body["agent"] == MOCK_REAL_NAME
    # The tuple route is a FORENSIC route: it is never filtered by evidence class,
    # so mock rows stay inspectable (each labelled) without any scope parameter.
    tuple_url = f"/api/v1/run/{_enc(MOCK_ONLY)}/{TASK}/0"
    found = mockc.get(tuple_url).json()
    assert found["found"] is True and found["evidence_class"] == "synthetic"
    assert found["backend_kind"] == "mock" and found["run_id"] in mock_world.b_runs
    report = mockc.get(f"/api/v1/jobs/{mock_world.a_job}/report.json").json()
    assert {t["run_id"] for t in report["trials"]} == set(mock_world.a_runs.values())
    results = mockc.get(f"/api/v1/jobs/{mock_world.a_job}/results").json()
    assert all(t["outcome"]["functional_pass"] for t in results["trials"])


def test_mock_rows_take_part_in_the_forensic_tuple_identity_and_ambiguity_is_labelled(mockc):
    """qwen3.5:9b has a legacy AND a mock run at (fbs, idx 0, current version).

    The tuple route is forensic and never class-filtered, so the pair is honestly
    ambiguous (409). The response says WHAT each candidate is, so a caller can
    pick the exact native /runs/{id}; that route (which the UI uses) is exact.
    """
    url = f"/api/v1/run/{_enc(MOCK_REAL_NAME)}/{TASK}/0"
    both = mockc.get(url)
    assert both.status_code == 409 and both.json()["ambiguous"] is True
    body = both.json()
    assert len(body["candidate_run_ids"]) == 2
    assert {c["evidence_class"] for c in body["candidates"]} == {"legacy", "synthetic"}
    assert {c["backend_kind"] for c in body["candidates"]} == {None, "mock"}
    for candidate in body["candidates"]:
        exact = mockc.get(f"/api/v1/runs/{candidate['run_id']}").json()
        assert exact["found"] is True
        assert exact["evidence_class"] == candidate["evidence_class"]


def test_regenerate_default_excludes_mock_but_synthetic_scope_includes_it(mockc, regen_out):
    default = mockc.post("/api/v1/reports/regenerate")
    assert default.status_code == 200
    assert default.json()["real_counts"][MOCK_REAL_NAME] == {"n_runs": 30, "n_tasks": 6}
    assert MOCK_ONLY not in default.json()["real_counts"]
    html = regen_out.read_text()
    assert MOCK_ONLY not in html
    assert "outside this scope" in html
    syn = mockc.post("/api/v1/reports/regenerate?evidence=synthetic")
    assert syn.status_code == 200 and syn.json()["evidence_scope"] == "synthetic"
    assert syn.json()["real_counts"][MOCK_ONLY] == {"n_runs": 2, "n_tasks": 1}
    assert MOCK_ONLY in regen_out.read_text()


# --------------------------------------------------------------------------- #
# J. PROVENANCE CONSISTENCY
# --------------------------------------------------------------------------- #


@pytest.fixture()
def mock_copy(mock_world, tmp_path) -> Path:
    path = tmp_path / "mock-copy.sqlite"
    shutil.copy(mock_world.snapshot, path)
    return path


def test_a_run_that_contradicts_its_evaluation_snapshot_is_a_conflict(mock_world, mock_copy):
    run_id = mock_world.b_runs[0]
    _exec(mock_copy, "UPDATE runs SET backend_kind='ollama' WHERE id=?", (run_id,))
    with _client(mock_copy, auto_dispatch=False) as client:
        report = client.get(f"/api/v1/jobs/{mock_world.b_job}/report.json").json()
        bad = next(t for t in report["trials"] if t["run_id"] == run_id)
        good = next(t for t in report["trials"] if t["run_id"] != run_id)
        assert bad["provenance"] == "mismatch" and bad["backend_kind"] == "ollama"
        assert bad.get("comparability") is None
        assert bad["integrity_error"]
        assert good["provenance"] == "consistent" and good["comparability"] == "comparable"
        assert any("provenance" in item.lower() for item in report["limitations"])
        md = client.get(f"/api/v1/jobs/{mock_world.b_job}/report.md").text
        assert "Provenance: `mismatch`" in md
        detail = client.get(f"/api/v1/jobs/{mock_world.b_job}/trials/{TASK}/0").json()
        assert detail["provenance"] == "mismatch" and "comparability" not in detail
        run = client.get(f"/api/v1/runs/{run_id}").json()
        assert run["evidence_class"] == "conflict" and run["backend_kind"] == "ollama"
        assert run["provider_source"] == "run"
        # projections
        ov = client.get("/api/v1/overview").json()
        assert ov["excluded"]["provenance_conflict_runs"] == 1
        assert ov["excluded"]["synthetic_runs"] == 3  # 4 mock rows minus the conflicting one
        assert MOCK_ONLY not in ov["models"]
        real = client.get("/api/v1/overview?evidence=real").json()
        assert real["models"] == [] and real["excluded"]["provenance_conflict_runs"] == 1
        syn = client.get("/api/v1/overview?evidence=synthetic").json()
        assert syn["real_counts"][MOCK_ONLY] == {"n_runs": 1, "n_tasks": 1}  # the conflict is not "synthetic"
        allv = client.get("/api/v1/overview?evidence=all").json()
        assert allv["real_counts"][MOCK_ONLY] == {"n_runs": 2, "n_tasks": 1}
        assert allv["excluded"]["provenance_conflict_runs"] == 0
        cell = client.get(f"/api/v1/cell/{_enc(MOCK_ONLY)}/{TASK}").json()
        assert cell["excluded"] == {"synthetic_runs": 1, "provenance_conflict_runs": 1}
        cell_all = client.get(f"/api/v1/cell/{_enc(MOCK_ONLY)}/{TASK}?evidence=all").json()
        assert {r["evidence_class"] for r in cell_all["runs"]} == {"conflict", "synthetic"}
        assert client.get("/api/v1/export").json()["excluded"]["provenance_conflict_runs"] == 1
        assert client.get("/api/v1/meta").json()["excluded"]["provenance_conflict_runs"] == 1


def test_a_run_row_with_a_job_but_no_own_backend_is_classified_from_the_snapshot(mock_world, mock_copy):
    """Legacy row that HAS a job_id whose evaluation snapshot says mock: excluded by
    default (provider derived from the snapshot), visible under evidence=synthetic."""
    run_id = mock_world.b_runs[0]
    _exec(mock_copy, "UPDATE runs SET backend_kind=NULL WHERE id=?", (run_id,))
    with _client(mock_copy, auto_dispatch=False) as client:
        run = client.get(f"/api/v1/runs/{run_id}").json()
        assert run["evidence_class"] == "synthetic" and run["provider_source"] == "evaluation"
        assert run["backend_kind"] == "mock"  # resolved from the snapshot
        ov = client.get("/api/v1/overview").json()
        assert ov["excluded"]["synthetic_runs"] == 4
        assert MOCK_ONLY not in ov["models"]
        syn = client.get("/api/v1/overview?evidence=synthetic").json()
        assert syn["real_counts"][MOCK_ONLY] == {"n_runs": 2, "n_tasks": 1}
        report = client.get(f"/api/v1/jobs/{mock_world.b_job}/report.json").json()
        bad = next(t for t in report["trials"] if t["run_id"] == run_id)
        assert bad["provenance"] == "unknown" and bad["backend_kind"] is None


def test_legacy_rows_are_included_by_default_and_labelled_legacy(pristine, pristine_path):
    cell = pristine.get(f"/api/v1/cell/{_enc(Q9)}/{TASK}").json()
    assert len(cell["runs"]) == 5 and cell["current_runs"] == 5
    assert {r["evidence_class"] for r in cell["runs"]} == {"legacy"}
    assert {r["backend_kind"] for r in cell["runs"]} == {None}
    run = pristine.get(f"/api/v1/run/{_enc(Q9)}/{TASK}/0").json()
    assert run["evidence_class"] == "legacy" and run["provider_source"] == "none"
    assert run["backend_kind"] is None
    # legacy is not "real": the real scope is empty on the committed evidence
    assert pristine.get(f"/api/v1/cell/{_enc(Q9)}/{TASK}?evidence=real").json()["state"] == "not_captured"
    # a legacy row that predates provenance does not need the column to exist at all
    conn = _ro(pristine_path)
    try:
        assert conn.execute("SELECT COUNT(*) FROM runs WHERE job_id IS NOT NULL").fetchone()[0] == 0
    finally:
        conn.close()


def test_read_provenance_tolerates_a_database_without_the_provenance_column():
    raw = sqlite3.connect(f"file:{db.EVIDENCE_DB_PATH}?mode=ro&immutable=1", uri=True)
    raw.row_factory = sqlite3.Row
    try:
        assert "backend_kind" not in [r[1] for r in raw.execute("PRAGMA table_info(runs)")]
        found = evidence.read_provenance(raw)
    finally:
        raw.close()
    assert len(found) == 720
    assert {p.evidence_class for p in found.values()} == {"legacy"}
    assert {p.provider_source for p in found.values()} == {"none"}


@pytest.mark.parametrize(
    "run_kind,snap_kind,cls,src",
    [
        (None, None, "legacy", "none"),
        ("mock", None, "synthetic", "run"),
        ("ollama", None, "real", "run"),
        ("openai_compat", "openai_compat", "real", "run"),
        (None, "mock", "synthetic", "evaluation"),
        (None, "ollama", "real", "evaluation"),
        ("mock", "ollama", "conflict", "run"),
        ("ollama", "mock", "conflict", "run"),
        ("hosted", None, "conflict", "run"),
    ],
)
def test_classification_table(run_kind, snap_kind, cls, src):
    prov = evidence.classify(1, "job" if snap_kind else None, run_kind, snap_kind)
    assert (prov.evidence_class, prov.provider_source) == (cls, src)
    scopes = {name: cls in members for name, members in evidence.SCOPES.items()}
    assert scopes["all"] is True
    assert scopes["benchmark"] is (cls in ("real", "legacy"))
    assert scopes["real"] is (cls == "real")
    assert scopes["synthetic"] is (cls == "synthetic")


# --------------------------------------------------------------------------- #
# K. MIGRATION smoke (exhaustive coverage: tests/test_phase0_migration_concurrency.py)
# --------------------------------------------------------------------------- #


def test_six_concurrent_migrations_of_a_fresh_evidence_copy_all_succeed(evcopy):
    ro = _ro(evcopy)
    try:
        assert "backend_kind" not in [r[1] for r in ro.execute("PRAGMA table_info(runs)")]
    finally:
        ro.close()
    n = 6
    barrier = threading.Barrier(n)
    errors: list[str] = []

    def migrate_once() -> None:
        conn = db.connect(evcopy)
        try:
            barrier.wait(30)
            db.migrate(conn)
        except BaseException as exc:  # noqa: BLE001
            errors.append(repr(exc))
        finally:
            conn.close()

    threads = [threading.Thread(target=migrate_once) for _ in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(60)
    assert not any(t.is_alive() for t in threads)
    assert errors == []
    assert not any("duplicate column name" in e for e in errors)
    conn = _ro(evcopy)
    try:
        cols = [r[1] for r in conn.execute("PRAGMA table_info(runs)")]
        assert "job_id" in cols and "backend_kind" in cols
        assert cols.count("backend_kind") == 1
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert {"evaluation_jobs", "evaluation_trials", "job_events", "job_runs", "app_settings"} <= tables
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 720
        assert conn.execute("SELECT COUNT(*) FROM runs WHERE backend_kind IS NOT NULL").fetchone()[0] == 0
    finally:
        conn.close()
    # and the migrated copy is immediately usable for a new-provenance write
    store = afa.SqliteRunStore(evcopy)
    try:
        run_id = store.save_run(_record("post-migration-model"), backend_kind="ollama")
    finally:
        store.close()
    assert _scalar(evcopy, "SELECT backend_kind FROM runs WHERE id=?", (run_id,)) == "ollama"
