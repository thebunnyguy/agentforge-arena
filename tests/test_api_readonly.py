"""Read-only API suite + the THREE-WAY ground-contract anchor.

The single source of truth for every number the read-only API returns is the
frozen kernel/runner. This module proves that, for the captured anchor cell
(``qwen2.5-coder:7b`` x ``fix-binary-search``), three independent paths agree
to the digit:

    1. the API JSON  (FastAPI TestClient over the live reports/runs.sqlite),
    2. raw SQL       (COUNT/SUM straight off runs ⋈ run_scores),
    3. the report fn (afa.task_aggregate / afa.leaderboard over a freshly
       reloaded store) — NOT the same store the API holds, so a coincidental
       in-memory bug cannot make all three lie together.

It also covers the overview/leaderboard/domains/cell/run/meta response shapes,
the captured / not-captured / synthetic state tags, and that the mixed-version
refusal raised by the load path is SURFACED (503 + exact ValueError text) rather
than swallowed.

The app loads its stores once in the FastAPI lifespan; using ``TestClient`` as a
context manager triggers that lifespan. The default app is bound to the live DB
and is read-only here — these tests never write to it.
"""

from __future__ import annotations

import shutil
import sqlite3
import urllib.parse

import pytest
from fastapi.testclient import TestClient

import afa_runner as afa
from afa_api import db
from afa_api.main import app, create_app

# --------------------------------------------------------------------------- #
# Ground-contract anchor (verified against the real DB).
# --------------------------------------------------------------------------- #
ANCHOR_AGENT = "qwen2.5-coder:7b"
ANCHOR_TASK = "fix-binary-search"
ANCHOR_WILSON_LOW = 0.5655085052479191  # exact frozen value from rank_by_lcb
EXPECTED_TOTAL_RUNS = 600
EXPECTED_N_TASKS = 24
MODELS = [
    "qwen2.5-coder:7b",
    "qwen2.5-coder:3b",
    "deepseek-coder:6.7b",
    "llama3.2:latest",
    "gemma2:2b",
]
ORACLE = "oracle (synthetic baseline)"
NOOP = "noop (synthetic baseline)"


def _enc(agent: str) -> str:
    """Percent-encode an agent name so the colon in e.g. ``qwen2.5-coder:7b``
    survives as a single path segment."""
    return urllib.parse.quote(agent, safe="")


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    # Run against a COPY of the evidence DB so the lifespan migration never
    # mutates the committed reports/runs.sqlite. The copy has identical run data,
    # so the three-way anchor (API == raw SQL == report fn) still holds exactly.
    dst = tmp_path_factory.mktemp("ro_db") / "runs.sqlite"
    shutil.copy(db.DB_PATH, dst)
    app = create_app()
    app.state.db_path = dst
    with TestClient(app) as c:
        yield c


# --------------------------------------------------------------------------- #
# THREE-WAY anchor: API == raw SQL == report fn
# --------------------------------------------------------------------------- #

def _raw_sql_counts(db_path) -> tuple[int, int]:
    """(n_valid, n_pass) for the anchor cell straight off the raw tables.

    Mirrors the contract query: INFRA_FAILURE rows are voided (excluded from n).
    """
    conn = sqlite3.connect(str(db_path))
    try:
        n, c = conn.execute(
            "SELECT COUNT(*), SUM(functional_pass) FROM runs r "
            "JOIN run_scores s ON s.run_id = r.id "
            "WHERE r.agent = ? AND r.task_id = ? AND r.status != 'infra_failure'",
            (ANCHOR_AGENT, ANCHOR_TASK),
        ).fetchone()
    finally:
        conn.close()
    return int(n), int(c)


def _report_fn_aggregate():
    """Independently reload ONLY the anchor cell into a fresh memory store and
    run the frozen report fns over it. This deliberately does not reuse the
    app's store, so agreement is meaningful."""
    disk = afa.SqliteRunStore(str(db.DB_PATH))
    mem = afa.SqliteRunStore(":memory:")
    try:
        for rec in disk.load_runs(agent=ANCHOR_AGENT, task_id=ANCHOR_TASK):
            mem.save_run(rec)
        agg = afa.task_aggregate(mem, ANCHOR_AGENT, ANCHOR_TASK)
        lb = afa.leaderboard(mem, task_id=ANCHOR_TASK)
    finally:
        disk.close()
        mem.close()
    entry = next(e for e in lb if e.agent == ANCHOR_AGENT)
    return agg, entry


def test_three_way_anchor_cell(client):
    """API JSON == raw SQL == report-fn output for the captured anchor cell."""
    # --- 1. API ---
    cell = client.get(f"/api/v1/cell/{_enc(ANCHOR_AGENT)}/{ANCHOR_TASK}").json()
    assert cell["state"] == "captured"
    assert cell["captured"] is True
    assert cell["synthetic"] is False
    api_agg = cell["aggregate"]

    lb_resp = client.get(f"/api/v1/leaderboard?task_id={ANCHOR_TASK}").json()
    assert lb_resp["found"] is True
    api_entry = next(e for e in lb_resp["entries"] if e["agent"] == ANCHOR_AGENT)

    # --- 2. raw SQL ---
    sql_n, sql_c = _raw_sql_counts(db.DB_PATH)
    assert (sql_n, sql_c) == (5, 5)

    # --- 3. report fn (independent reload) ---
    rep_agg, rep_entry = _report_fn_aggregate()

    # All three agree on n / pass / pass_rate.
    assert api_agg["n_valid"] == sql_n == rep_agg.n_valid == 5
    assert api_agg["n_pass"] == sql_c == rep_agg.n_pass == 5
    assert api_agg["pass_rate"] == rep_agg.pass_rate == 1.0
    assert api_agg["mean_s"] == rep_agg.mean_s == 1.0
    assert api_agg["provisional"] is False
    assert rep_agg.provisional is False

    # Leaderboard (LCB ranking) agreement — wilson_low is the load-bearing digit.
    assert api_entry["n"] == rep_entry.n == 5
    assert api_entry["pass_rate"] == rep_entry.pass_rate == 1.0
    assert api_entry["wilson_low"] == rep_entry.wilson_low == ANCHOR_WILSON_LOW
    assert api_entry["rank_low"] == rep_entry.rank_low == 1
    assert api_entry["rank_high"] == rep_entry.rank_high == 1
    assert api_entry["provisional"] is False


# --------------------------------------------------------------------------- #
# Endpoint shapes: overview / leaderboard / domains / cell / run / meta
# --------------------------------------------------------------------------- #

def test_healthz_shape(client):
    body = client.get("/api/v1/healthz").json()
    assert body["status"] == "ok"
    assert body["stores_loaded"] is True
    assert body["load_error"] is None
    assert "db_path" in body


def test_overview_shape(client):
    ov = client.get("/api/v1/overview").json()
    assert ov["n_tasks"] == EXPECTED_N_TASKS
    assert sorted(ov["models"]) == sorted(MODELS)
    assert ov["observability"]["total_runs"] == EXPECTED_TOTAL_RUNS
    # Coverage must reflect the DISK store (real patch / test_results artifacts),
    # not the in-memory re-saved store (which reports 0). Regression for the
    # build_overview/build_meta summary-source bug.
    assert ov["observability"]["runs_with_patch"] > 0
    assert ov["observability"]["test_result_rows"] > 0
    # one pooled leaderboard entry per real model (no synthetic rows here)
    assert len(ov["leaderboard"]) == len(ov["models"])
    assert all(not e["synthetic"] for e in ov["leaderboard"])
    # provenance is present per agent
    for agent in MODELS:
        assert agent in ov["agent_observability"]
        assert agent in ov["real_counts"]
    assert ov["synthetic_agents"] == [ORACLE, NOOP]


def test_leaderboard_pooled_and_scoped_shape(client):
    pooled = client.get("/api/v1/leaderboard").json()
    assert pooled["task_id"] is None
    assert pooled["found"] is True
    assert len(pooled["entries"]) == len(MODELS)
    keys = {"agent", "pass_rate", "wilson_low", "wilson_high", "n",
            "provisional", "rank_low", "rank_high", "synthetic"}
    assert keys <= set(pooled["entries"][0])

    scoped = client.get(f"/api/v1/leaderboard?task_id={ANCHOR_TASK}").json()
    assert scoped["task_id"] == ANCHOR_TASK
    assert scoped["found"] is True

    missing = client.get("/api/v1/leaderboard?task_id=no-such-task").json()
    assert missing["found"] is False
    assert missing["entries"] == []


def test_domains_shape_and_sorted(client):
    dm = client.get(f"/api/v1/domains/{_enc(ANCHOR_AGENT)}").json()
    assert dm["agent"] == ANCHOR_AGENT
    assert dm["captured"] is True
    assert dm["synthetic"] is False
    assert isinstance(dm["domains"], list) and dm["domains"]
    names = [d["domain"] for d in dm["domains"]]
    assert names == sorted(names)  # domain_profile sorts by domain name
    dkeys = {"domain", "pooled_pass_rate", "n_eff", "wilson_low", "wilson_high",
             "stability", "n_tasks", "n_runs", "displayable"}
    assert dkeys <= set(dm["domains"][0])


def test_cell_shape(client):
    cell = client.get(f"/api/v1/cell/{_enc(ANCHOR_AGENT)}/{ANCHOR_TASK}").json()
    assert cell["agent"] == ANCHOR_AGENT
    assert cell["task_id"] == ANCHOR_TASK
    assert cell["known_task"] is True
    assert cell["current_version"] == "1.0.0"
    assert cell["task_versions"] == ["1.0.0"]
    assert len(cell["runs"]) == 5
    for r in cell["runs"]:
        assert r["agent"] == ANCHOR_AGENT
        assert r["task_id"] == ANCHOR_TASK
        assert r["status"] == "valid"
        # Q components are never persisted in v0.1.
        assert r["score"]["q_components"] == {}
        assert r["score"]["q_components_available"] is False


def test_run_detail_identity_and_raw_columns(client):
    run = client.get(f"/api/v1/run/{_enc(ANCHOR_AGENT)}/{ANCHOR_TASK}/0").json()
    assert run["found"] is True
    assert run["synthetic"] is False
    assert run["captured"] is True
    assert run["task_version"] == "1.0.0"
    assert run["status"] == "valid"
    assert run["score"]["final_score"] == 1.0
    assert run["score"]["functional_pass"] is True
    assert run["score"]["q_components"] == {}
    assert run["score"]["q_components_available"] is False
    # raw columns that load_runs does NOT return, fetched via direct SQL
    assert run["patch_available"] is True
    assert run["patch_text"] is not None
    assert run["created_at"] is not None
    assert run["touched_protected"] in (True, False)
    assert len(run["test_results"]) > 0
    tr = run["test_results"][0]
    assert {"suite", "test_name", "passed", "weight"} <= set(tr)


def test_run_missing_idx_is_not_found(client):
    run = client.get(f"/api/v1/run/{_enc(ANCHOR_AGENT)}/{ANCHOR_TASK}/999").json()
    assert run["found"] is False
    assert run["captured"] is False


def test_meta_shape(client):
    mt = client.get("/api/v1/meta").json()
    assert mt["n_tasks"] == EXPECTED_N_TASKS
    assert len(mt["tasks"]) == EXPECTED_N_TASKS
    assert sorted(mt["models"]) == sorted(MODELS)
    assert mt["synthetic_agents"] == [ORACLE, NOOP]
    assert mt["observability"]["total_runs"] == EXPECTED_TOTAL_RUNS
    anchor = next(t for t in mt["tasks"] if t["task_id"] == ANCHOR_TASK)
    assert anchor["current_version"] == "1.0.0"
    assert "1.0.0" in anchor["evaluated_versions"]
    assert isinstance(anchor["domains"], list) and anchor["domains"]
    assert {"domain", "weight"} <= set(anchor["domains"][0])
    # honesty notes the contract requires the UI to surface
    assert "q_components" in mt["notes"]
    assert "trust" in mt["notes"]
    assert "run_identity" in mt["notes"]


# --------------------------------------------------------------------------- #
# State tags: legacy 'not captured' vs synthetic bookend
# --------------------------------------------------------------------------- #

def test_legacy_uncaptured_cell_shows_not_captured(client):
    """A real-looking but never-evaluated (agent, task) cell must be honestly
    reported as not captured — no aggregate, no synthetic injection."""
    cell = client.get(
        f"/api/v1/cell/{_enc('llama3.2:latest')}/this-task-was-never-run"
    ).json()
    assert cell["state"] == "not_captured"
    assert cell["captured"] is False
    assert cell["synthetic"] is False
    assert cell["aggregate"] is None
    assert cell["runs"] == []


def test_synthetic_bookend_state_cell(client):
    """The oracle/noop synthetic baselines are tagged synthetic, never mixed
    into the captured/real views."""
    for agent in (ORACLE, NOOP):
        cell = client.get(f"/api/v1/cell/{_enc(agent)}/{ANCHOR_TASK}").json()
        assert cell["state"] == "synthetic"
        assert cell["synthetic"] is True

    # And a synthetic run is reconstructed from the full store, clearly marked,
    # with no persisted patch.
    run = client.get(f"/api/v1/run/{_enc(ORACLE)}/{ANCHOR_TASK}/0").json()
    assert run["found"] is True
    assert run["synthetic"] is True
    assert run["captured"] is False
    assert run["patch_available"] is False
    assert run["score"]["functional_pass"] is True  # oracle always passes

    noop = client.get(f"/api/v1/run/{_enc(NOOP)}/{ANCHOR_TASK}/0").json()
    assert noop["synthetic"] is True
    assert noop["score"]["functional_pass"] is False  # noop always fails


# --------------------------------------------------------------------------- #
# Mixed-version refusal is SURFACED, not swallowed.
# --------------------------------------------------------------------------- #

def _make_mixed_version_db(src, dst) -> None:
    """Copy the live DB and inject a second task_version into the anchor cell so
    load_stores must refuse to pool it."""
    shutil.copy(src, dst)
    conn = sqlite3.connect(str(dst))
    conn.row_factory = sqlite3.Row
    try:
        seed = conn.execute(
            "SELECT * FROM runs WHERE agent=? AND task_id=? LIMIT 1",
            (ANCHOR_AGENT, ANCHOR_TASK),
        ).fetchone()
        cur = conn.execute(
            "INSERT INTO runs(task_id, task_version, agent, idx, status, "
            "transcript_hash, duration_ms) VALUES (?,?,?,?,?,?,?)",
            (seed["task_id"], "2.0.0", seed["agent"], 99, seed["status"],
             seed["transcript_hash"], seed["duration_ms"]),
        )
        new_id = cur.lastrowid
        conn.execute(
            "INSERT INTO run_scores(run_id, gate_product, t_hidden, q, "
            "final_score, functional_pass, voided) VALUES (?,?,?,?,?,?,?)",
            (new_id, 1, 1.0, 1.0, 1.0, 1, 0),
        )
        conn.execute(
            "INSERT INTO diffs(run_id, files_changed, lines_added, "
            "lines_removed, touched_protected, patch_text) VALUES (?,?,?,?,?,?)",
            (new_id, 1, 1, 0, 0, "x"),
        )
        conn.commit()
    finally:
        conn.close()


def test_mixed_version_refusal_surfaces_as_503(tmp_path):
    """When the load path raises the mixed-version ValueError, the app captures
    it and the read-only endpoints return 503 with the EXACT message — never a
    500 and never a silent empty success."""
    mixed = tmp_path / "mixed.sqlite"
    _make_mixed_version_db(db.DB_PATH, mixed)

    app2 = create_app()
    app2.state.db_path = mixed
    with TestClient(app2) as c:
        health = c.get("/api/v1/healthz").json()
        assert health["stores_loaded"] is False
        assert "refusing to pool multiple task versions" in health["load_error"]
        assert f"{ANCHOR_AGENT}/{ANCHOR_TASK}" in health["load_error"]

        resp = c.get("/api/v1/overview")
        assert resp.status_code == 503
        body = resp.json()
        assert "refusing to pool multiple task versions" in body["error"]

        # Every read-only projection endpoint refuses, not just overview.
        for path in (
            "/api/v1/leaderboard",
            f"/api/v1/domains/{_enc(ANCHOR_AGENT)}",
            f"/api/v1/cell/{_enc(ANCHOR_AGENT)}/{ANCHOR_TASK}",
            f"/api/v1/run/{_enc(ANCHOR_AGENT)}/{ANCHOR_TASK}/0",
            "/api/v1/meta",
        ):
            r = c.get(path)
            assert r.status_code == 503, path
            assert "refusing to pool" in r.json()["error"], path
