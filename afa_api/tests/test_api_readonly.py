"""Read-only API tests + the 3-way verification anchor (api == raw SQL == report fn).

These exercise the live reports/runs.sqlite via the FastAPI app. The app loads
the stores once at startup (lifespan); TestClient as a context manager triggers
that lifespan.
"""

from __future__ import annotations

import sqlite3
import urllib.parse

import pytest
from fastapi.testclient import TestClient

import afa_runner as afa
from afa_api import db
from afa_api.main import app

ANCHOR_AGENT = "qwen2.5-coder:7b"
ANCHOR_TASK = "fix-binary-search"
ANCHOR_WILSON_LOW = 0.5655085052479191


def _enc(agent: str) -> str:
    return urllib.parse.quote(agent, safe="")


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def test_healthz_stores_loaded(client):
    body = client.get("/api/v1/healthz").json()
    assert body["status"] == "ok"
    assert body["stores_loaded"] is True
    assert body["load_error"] is None


def test_overview_shape(client):
    ov = client.get("/api/v1/overview").json()
    assert ov["n_tasks"] == 24
    assert ANCHOR_AGENT in ov["models"]
    assert len(ov["leaderboard"]) == len(ov["models"])
    assert ov["observability"]["total_runs"] == 600


def test_meta_shape(client):
    mt = client.get("/api/v1/meta").json()
    assert mt["n_tasks"] == 24
    assert len(mt["tasks"]) == 24
    assert all("current_version" in t for t in mt["tasks"])
    # Q components are documented as unavailable.
    assert "q_components" in mt["notes"]


def test_anchor_cell_matches_report_fn_and_raw_sql(client):
    # API
    cell = client.get(f"/api/v1/cell/{_enc(ANCHOR_AGENT)}/{ANCHOR_TASK}").json()
    assert cell["state"] == "captured"
    agg = cell["aggregate"]
    assert agg["n_valid"] == 5
    assert agg["n_pass"] == 5
    assert agg["pass_rate"] == 1.0
    assert agg["provisional"] is False

    # report fn (independent computation over the live DB)
    disk = afa.SqliteRunStore(str(db.DB_PATH))
    mem = afa.SqliteRunStore(":memory:")
    try:
        for rec in disk.load_runs(agent=ANCHOR_AGENT, task_id=ANCHOR_TASK):
            mem.save_run(rec)
        ref = afa.task_aggregate(mem, ANCHOR_AGENT, ANCHOR_TASK)
    finally:
        disk.close()
        mem.close()
    assert ref.n_valid == agg["n_valid"]
    assert ref.n_pass == agg["n_pass"]
    assert ref.pass_rate == agg["pass_rate"]

    # raw SQL
    conn = sqlite3.connect(str(db.DB_PATH))
    try:
        n, c = conn.execute(
            "SELECT COUNT(*), SUM(functional_pass) FROM runs r "
            "JOIN run_scores s ON s.run_id=r.id "
            "WHERE r.agent=? AND r.task_id=? AND r.status!='infra_failure'",
            (ANCHOR_AGENT, ANCHOR_TASK),
        ).fetchone()
    finally:
        conn.close()
    assert (n, c) == (5, 5)


def test_anchor_leaderboard_wilson_low(client):
    lb = client.get(
        f"/api/v1/leaderboard?task_id={ANCHOR_TASK}"
    ).json()
    assert lb["found"] is True
    entry = next(e for e in lb["entries"] if e["agent"] == ANCHOR_AGENT)
    assert entry["n"] == 5
    assert entry["pass_rate"] == 1.0
    assert entry["wilson_low"] == ANCHOR_WILSON_LOW
    assert entry["rank_low"] == 1
    assert entry["rank_high"] == 1


def test_run_detail_identity_and_raw_columns(client):
    run = client.get(
        f"/api/v1/run/{_enc(ANCHOR_AGENT)}/{ANCHOR_TASK}/0"
    ).json()
    assert run["found"] is True
    assert run["synthetic"] is False
    assert run["status"] == "valid"
    assert run["score"]["final_score"] == 1.0
    assert run["score"]["functional_pass"] is True
    # Q components never persisted in v0.1.
    assert run["score"]["q_components"] == {}
    assert run["score"]["q_components_available"] is False
    # raw columns load_runs omits
    assert run["patch_available"] is True
    assert run["created_at"] is not None
    assert len(run["test_results"]) > 0


def test_not_captured_cell(client):
    cell = client.get(
        f"/api/v1/cell/{_enc('nonexistent:model')}/{ANCHOR_TASK}"
    ).json()
    assert cell["state"] == "not_captured"
    assert cell["captured"] is False
    assert cell["aggregate"] is None


def test_synthetic_baseline_states(client):
    cell = client.get(
        f"/api/v1/cell/{_enc('oracle (synthetic baseline)')}/{ANCHOR_TASK}"
    ).json()
    assert cell["state"] == "synthetic"
    assert cell["synthetic"] is True

    run = client.get(
        f"/api/v1/run/{_enc('oracle (synthetic baseline)')}/{ANCHOR_TASK}/0"
    ).json()
    assert run["found"] is True
    assert run["synthetic"] is True
    assert run["captured"] is False
    assert run["patch_available"] is False


def test_domains_profile(client):
    dm = client.get(f"/api/v1/domains/{_enc(ANCHOR_AGENT)}").json()
    assert dm["captured"] is True
    assert isinstance(dm["domains"], list)
    # domain_profile returns one DomainScore per domain, sorted by name.
    names = [d["domain"] for d in dm["domains"]]
    assert names == sorted(names)
