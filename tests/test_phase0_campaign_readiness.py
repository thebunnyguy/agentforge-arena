"""Campaign-readiness simulation: can current-benchmark evidence be ingested next
to the historical evidence without mixing versions, mistaking synthetic runs for
real evidence, or collapsing the product?

Simulation, not a real campaign: two EXISTING historical model names are
evaluated on two ORACLE-version-bumped tasks, twice each, through the real API,
worker, grader and persistence path, in a temp copy of the historical DB. The
agent factory is an injected test double that reproduces the reference solution
but DECLARES the ``ollama`` backend (what production factories do), so the runs
are provenance-real evidence exactly as a genuine local-model campaign would be.
No model is contacted, and the committed evidence DB is only ever copied.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
import time
import urllib.parse
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from afa_api import db, worker
from afa_api.main import create_app

REPO = Path(__file__).resolve().parents[1]
MODELS = ["qwen3.5:9b", "qwen2.5-coder:7b"]  # existing historical model names
TASKS = ["sanitize-filename", "toposort"]  # ORACLE-bumped: 1.0.1 -> 1.0.2
REPEATS = 2
HISTORICAL_MAX_RUN_ID = 1220
TERMINAL = {"succeeded", "failed", "canceled"}


def _enc(value: str) -> str:
    return urllib.parse.quote(value, safe="")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _declared_ollama_factory(model, task, params):
    """Reference-overlay agent that declares the backend it stands in for."""
    return worker.mock_agent_factory(model, task, params)


_declared_ollama_factory.backend_kind = "ollama"


def _wait(client: TestClient, evaluation_id: str, timeout: float = 120.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        body = client.get(f"/api/v1/jobs/{evaluation_id}").json()
        if body["status"] in TERMINAL:
            return body
        time.sleep(0.02)
    raise AssertionError("evaluation did not finish")


def _historical_fingerprint(path: Path) -> str:
    """Checksum of every historical row (ids <= the evidence maximum) and its
    dependent rows, over the original columns only."""
    conn = sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)
    try:
        h = hashlib.sha256()
        for table, cols in (
            ("runs", "id,task_id,task_version,agent,idx,status,transcript_hash,duration_ms"),
            ("run_scores", "run_id,gate_product,t_hidden,q,final_score,functional_pass,voided"),
            ("diffs", "run_id,files_changed,lines_added,lines_removed,touched_protected"),
        ):
            key = "id" if table == "runs" else "run_id"
            for row in conn.execute(
                f"SELECT {cols} FROM {table} WHERE {key} <= ? ORDER BY {key}",
                (HISTORICAL_MAX_RUN_ID,),
            ):
                h.update(repr(tuple(row)).encode())
        return h.hexdigest()
    finally:
        conn.close()


def _all_views_answer(client: TestClient, models: list[str], tasks: list[str], run_ids: list[int]):
    """Every projection/control-plane surface stays usable (no 503/409)."""
    for path in (
        "/api/v1/healthz", "/api/v1/overview", "/api/v1/leaderboard", "/api/v1/meta",
        "/api/v1/export", "/api/v1/jobs", "/api/v1/leaderboard?task_id=" + tasks[0],
    ):
        assert client.get(path).status_code == 200, path
    for model in models:
        assert client.get(f"/api/v1/domains/{_enc(model)}").status_code == 200
        for task in tasks:
            assert client.get(f"/api/v1/cell/{_enc(model)}/{task}").status_code == 200
    for run_id in run_ids:
        assert client.get(f"/api/v1/runs/{run_id}").status_code == 200
    assert client.get("/api/v1/healthz").json()["status"] == "ok"


@pytest.fixture(scope="module", autouse=True)
def _evidence_db_unchanged():
    before = _sha(db.EVIDENCE_DB_PATH)
    yield
    assert _sha(db.EVIDENCE_DB_PATH) == before


def test_current_campaign_evidence_coexists_with_historical_evidence(tmp_path, monkeypatch):
    import report_combined

    monkeypatch.setattr(report_combined, "OUTPUT", tmp_path / "leaderboard.html", raising=False)
    working = tmp_path / "campaign.sqlite"
    shutil.copy(db.EVIDENCE_DB_PATH, working)
    fingerprint = _historical_fingerprint(working)

    app = create_app()
    app.state.db_path = working
    app.state.agent_factory = _declared_ollama_factory
    manifest = json.loads((REPO / "integrity/pack-audit/remediation-manifest.json").read_text())
    versions = {t["task_id"]: (t["old_version"], t["new_version"]) for t in manifest["tasks"]}

    with TestClient(app) as client:
        before = client.get("/api/v1/overview").json()
        base_n = {m: before["real_counts"][m]["n_runs"] for m in MODELS}
        assert all(n == 30 for n in base_n.values())  # current legacy evidence only
        assert before["current_benchmark"]["tasks_with_current_evidence"] == 6

        new_run_ids: list[int] = []
        for model in MODELS:
            created = client.post(
                "/api/v1/jobs",
                json={"model": model, "backend": {"kind": "ollama"}, "tasks": TASKS,
                      "repeats": REPEATS},
            )
            assert created.status_code == 200, created.text
            assert created.json()["evidence_class"] == "real"
            job = _wait(client, created.json()["id"])
            assert job["status"] == "succeeded", job

            report = client.get(f"/api/v1/jobs/{job['id']}/report.json").json()
            assert len(report["trials"]) == len(TASKS) * REPEATS
            for trial in report["trials"]:
                assert trial["task_version"] == versions[trial["task_id"]][1]
                assert trial["evidence_state"] == "fresh"
                assert trial["comparability"] == "comparable"
                assert trial["backend_kind"] == "ollama" and trial["provenance"] == "consistent"
                new_run_ids.append(trial["run_id"])
            assert client.get(f"/api/v1/jobs/{job['id']}/report.md").status_code == 200

            # The product stays usable after EVERY evaluation, not just the last.
            _all_views_answer(client, MODELS, TASKS, new_run_ids)

        overview = client.get("/api/v1/overview").json()
        assert overview["excluded"]["synthetic_runs"] == 0  # nothing was mock
        assert overview["current_benchmark"]["tasks_with_current_evidence"] == 6 + len(TASKS)
        entries = {e["agent"]: e for e in overview["leaderboard"]}
        for model in MODELS:
            # 30 legacy current runs + 4 new: the 10 historical rows on these two
            # tasks (5 per task) are NOT pooled in.
            assert overview["real_counts"][model] == {
                "n_runs": 30 + len(TASKS) * REPEATS, "n_tasks": 6 + len(TASKS),
            }
            assert entries[model]["n"] == 30 + len(TASKS) * REPEATS
            assert entries[model]["coverage"]["tasks_with_current_evidence"] == 6 + len(TASKS)
            counts = overview["evidence_counts"][model]
            assert counts["current_by_class"] == {"legacy": 30, "real": len(TASKS) * REPEATS}
            # historical evidence is preserved in full: new runs are ADDED beside it
            assert counts["historical_runs"] == 90

            for task in TASKS:
                old, new = versions[task]
                cell = client.get(f"/api/v1/cell/{_enc(model)}/{task}").json()
                assert cell["state"] == "captured" and cell["evidence_status"] == "current"
                assert cell["selected_version"] == new
                assert (cell["current_runs"], cell["historical_runs"]) == (REPEATS, 5)
                assert [(v["version"], v["status"], v["n_runs"]) for v in cell["versions"]] == [
                    (new, "current", REPEATS), (old, "historical", 5),
                ]
                assert {r["evidence_class"] for r in cell["runs"]} == {"real"}
                # the historical version is still inspectable, on its own
                hist = client.get(f"/api/v1/cell/{_enc(model)}/{task}?version={old}").json()
                assert hist["evidence_status"] == "historical" and len(hist["runs"]) == 5
                assert hist["aggregate"]["n_valid"] == 5

        # Other tasks' historical evidence stays historical-only (never promoted).
        untouched = client.get(f"/api/v1/cell/{_enc(MODELS[0])}/async-retry").json()
        assert untouched["state"] == "historical_only" and untouched["current_runs"] == 0

        # Exact runs carry their provenance and version.
        for run_id in new_run_ids:
            assert run_id > HISTORICAL_MAX_RUN_ID
            run = client.get(f"/api/v1/runs/{run_id}").json()
            assert run["backend_kind"] == "ollama" and run["evidence_class"] == "real"
            assert run["version_status"] == "current"

        assert client.post("/api/v1/reports/regenerate").status_code == 200
        exported = client.get("/api/v1/export").json()
        assert exported["current_benchmark"]["tasks_with_current_evidence"] == 6 + len(TASKS)

    # Historical rows are byte-for-byte what they were, and nothing was backfilled.
    assert _historical_fingerprint(working) == fingerprint
    conn = sqlite3.connect(f"{working.as_uri()}?mode=ro", uri=True)
    try:
        assert conn.execute(
            "SELECT COUNT(*) FROM runs WHERE id <= ? AND backend_kind IS NOT NULL",
            (HISTORICAL_MAX_RUN_ID,),
        ).fetchone()[0] == 0
        assert conn.execute(
            "SELECT DISTINCT backend_kind FROM runs WHERE id > ?", (HISTORICAL_MAX_RUN_ID,)
        ).fetchall() == [("ollama",)]
    finally:
        conn.close()
