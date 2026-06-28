"""PURE projection layer: dataclasses + raw rows -> JSON-able dicts.

NO statistics live here. Every number is read field-by-field off the frozen
kernel/runner dataclasses (AggregateResult, LeaderboardEntry, DomainScore,
RunScore, RunStoreSummary) or off the raw SQLite columns. The only transforms
are field selection, dict-key stringification (pass_at_k keys), and explicit
state tagging (captured / not-captured / synthetic). If you find yourself adding
arithmetic, it belongs in the kernel, not here.

Run identity is always (agent, task_id, idx) — never runs.id.
"""

from __future__ import annotations

import sqlite3
from typing import Any

import afa_runner as afa
from afa_kernel.types import (
    AggregateResult,
    DomainScore,
    LeaderboardEntry,
    RunScore,
    RunStatus,
)
from afa_runner.store import RunStoreSummary

from .store_load import SYNTHETIC_AGENTS, LoadedStores


# --------------------------------------------------------------------------- #
# Leaf projections (field-by-field; no math)
# --------------------------------------------------------------------------- #

def _summary_dict(s: RunStoreSummary) -> dict[str, Any]:
    return {
        "total_runs": s.total_runs,
        "first_created_at": s.first_created_at,
        "last_created_at": s.last_created_at,
        "runs_with_patch": s.runs_with_patch,
        "runs_with_test_results": s.runs_with_test_results,
        "test_result_rows": s.test_result_rows,
    }


def _aggregate_dict(a: AggregateResult) -> dict[str, Any]:
    return {
        "n_valid": a.n_valid,
        "n_pass": a.n_pass,
        "pass_rate": a.pass_rate,
        "wilson_low": a.wilson_low,
        "wilson_high": a.wilson_high,
        "mean_s": a.mean_s,
        "median_s": a.median_s,
        "min_s": a.min_s,
        "max_s": a.max_s,
        "std_s": a.std_s,
        "stability": a.stability,
        "conservative_continuous": a.conservative_continuous,
        "timeout_rate": a.timeout_rate,
        "infra_void_rate": a.infra_void_rate,
        "reliability": a.reliability,
        # JSON object keys must be strings; values are the frozen pass@k floats.
        "pass_at_k": {str(k): v for k, v in a.pass_at_k.items()},
        "deterministic": a.deterministic,
        "bimodal": a.bimodal,
        "provisional": a.provisional,
    }


def _leaderboard_entry_dict(e: LeaderboardEntry) -> dict[str, Any]:
    return {
        "agent": e.agent,
        "pass_rate": e.pass_rate,
        "wilson_low": e.wilson_low,
        "wilson_high": e.wilson_high,
        "n": e.n,
        "provisional": e.provisional,
        "rank_low": e.rank_low,
        "rank_high": e.rank_high,
        "synthetic": e.agent in SYNTHETIC_AGENTS,
    }


def _domain_score_dict(d: DomainScore) -> dict[str, Any]:
    return {
        "domain": d.domain,
        "pooled_pass_rate": d.pooled_pass_rate,
        "n_eff": d.n_eff,
        "wilson_low": d.wilson_low,
        "wilson_high": d.wilson_high,
        "stability": d.stability,
        "n_tasks": d.n_tasks,
        "n_runs": d.n_runs,
        "displayable": d.displayable,
    }


def _run_score_dict(s: RunScore) -> dict[str, Any]:
    return {
        "status": s.status.value,
        "gate_product": s.gate_product,
        "t_hidden": s.t_hidden,
        "q": s.q,
        # q_components is never persisted in v0.1 (always {} from SQLite). The UI
        # must say "Q components unavailable" rather than implying empty.
        "q_components": s.q_components,
        "q_components_available": bool(s.q_components),
        "final_score": s.final_score,
        "functional_pass": s.functional_pass,
        "voided": s.voided,
    }


# --------------------------------------------------------------------------- #
# Endpoint builders. `stores` is the loaded LoadedStores; `ro` is a read-only
# sqlite3.Connection used only for raw column reads (patch_text, created_at,
# touched_protected, per-test results) that load_runs does not return.
# --------------------------------------------------------------------------- #

def build_overview(stores: LoadedStores, ro: sqlite3.Connection) -> dict[str, Any]:
    """Top-level dashboard: persisted-run provenance, model/task coverage, and
    the pooled (all-tasks) leaderboard. Real store only (no synthetic rows)."""
    overall = stores.observability
    per_agent = {
        agent: _summary_dict(stores.agent_observability[agent])
        for agent in stores.models
    }
    entries = afa.leaderboard(stores.real)
    return {
        "models": stores.models,
        "task_ids": stores.task_ids,
        "n_tasks": len(stores.task_ids),
        "real_counts": {
            agent: {"n_runs": n_runs, "n_tasks": n_tasks}
            for agent, (n_runs, n_tasks) in stores.real_counts.items()
        },
        "observability": _summary_dict(overall),
        "agent_observability": per_agent,
        "leaderboard": [_leaderboard_entry_dict(e) for e in entries],
        "synthetic_agents": stores.synthetic_agents,
    }


def build_leaderboard(
    stores: LoadedStores, ro: sqlite3.Connection, task_id: str | None = None
) -> dict[str, Any]:
    """Wilson-LCB leaderboard, optionally scoped to one task. Real store only —
    matches the 3-way anchor (api == raw SQL == report fn)."""
    if task_id is not None and task_id not in stores.task_ids:
        return {"task_id": task_id, "found": False, "entries": []}
    entries = afa.leaderboard(stores.real, task_id=task_id)
    return {
        "task_id": task_id,
        "found": True,
        "entries": [_leaderboard_entry_dict(e) for e in entries],
    }


def build_domains(
    stores: LoadedStores, ro: sqlite3.Connection, agent: str
) -> dict[str, Any]:
    """Per-domain capability profile for one agent (report fn domain_profile)."""
    captured = agent in stores.real.agents()
    scores = afa.domain_profile(stores.real, agent, stores.task_domains)
    return {
        "agent": agent,
        "captured": captured,
        "synthetic": agent in SYNTHETIC_AGENTS,
        "domains": [_domain_score_dict(d) for d in scores],
    }


def build_cell(
    stores: LoadedStores, ro: sqlite3.Connection, agent: str, task_id: str
) -> dict[str, Any]:
    """One (agent, task) cell aggregate + the captured/not-captured/synthetic
    state, plus the per-run index list (identity = (agent, task_id, idx))."""
    synthetic = agent in SYNTHETIC_AGENTS
    known_task = task_id in stores.task_ids
    records = stores.real.load_runs(task_id=task_id, agent=agent)
    captured = len(records) > 0

    state = "captured"
    if synthetic:
        state = "synthetic"
    elif not captured:
        state = "not_captured"

    result: dict[str, Any] = {
        "agent": agent,
        "task_id": task_id,
        "known_task": known_task,
        "captured": captured,
        "synthetic": synthetic,
        "state": state,
        "current_version": stores.current_versions.get(task_id),
        "task_versions": sorted({r.task_version for r in records}),
        "runs": [
            {"agent": r.agent, "task_id": r.task_id, "idx": r.idx,
             "status": r.status.value, "score": _run_score_dict(r.score)}
            for r in records
        ],
    }
    if captured:
        agg: AggregateResult = afa.task_aggregate(stores.real, agent, task_id)
        result["aggregate"] = _aggregate_dict(agg)
    else:
        result["aggregate"] = None
    return result


# Raw columns load_runs does not return; fetch directly (plan-allowed).
_RUN_RAW_SQL = (
    "SELECT r.id, r.task_id, r.task_version, r.agent, r.idx, r.status, "
    "r.transcript_hash, r.duration_ms, r.created_at, "
    "s.gate_product, s.t_hidden, s.q, s.final_score, s.functional_pass, s.voided, "
    "d.files_changed, d.lines_added, d.lines_removed, d.touched_protected, d.patch_text "
    "FROM runs r "
    "JOIN run_scores s ON s.run_id = r.id "
    "JOIN diffs d ON d.run_id = r.id "
    "WHERE r.agent = ? AND r.task_id = ? AND r.idx = ? "
    "ORDER BY r.id"
)


def build_run(
    stores: LoadedStores,
    ro: sqlite3.Connection,
    agent: str,
    task_id: str,
    idx: int,
) -> dict[str, Any]:
    """One run detail by (agent, task_id, idx) — never by runs.id.

    Reads raw columns load_runs omits (patch_text, created_at, touched_protected,
    per-test results) directly from the read-only DB. Synthetic baselines are not
    persisted in the DB, so a synthetic (agent, task, idx) is reconstructed from
    the in-memory full store and clearly marked.
    """
    synthetic = agent in SYNTHETIC_AGENTS
    known_task = task_id in stores.task_ids

    if synthetic:
        recs = stores.full.load_runs(task_id=task_id, agent=agent)
        match = next((r for r in recs if r.idx == idx), None)
        if match is None:
            return {
                "agent": agent, "task_id": task_id, "idx": idx,
                "found": False, "synthetic": True, "known_task": known_task,
            }
        return {
            "agent": agent, "task_id": task_id, "idx": idx,
            "found": True, "synthetic": True, "captured": False,
            "known_task": known_task,
            "task_version": match.task_version,
            "status": match.status.value,
            "score": _run_score_dict(match.score),
            "files_changed": match.files_changed,
            "lines_added": match.lines_added,
            "lines_removed": match.lines_removed,
            "transcript_hash": match.transcript_hash,
            "duration_ms": match.duration_ms,
            "created_at": None,
            "touched_protected": False,
            "patch_text": None,
            "patch_available": False,
            "test_results": [],
        }

    row = ro.execute(_RUN_RAW_SQL, (agent, task_id, idx)).fetchone()
    if row is None:
        return {
            "agent": agent, "task_id": task_id, "idx": idx,
            "found": False, "synthetic": False, "captured": False,
            "known_task": known_task,
        }

    run_id = row["id"]
    test_rows = ro.execute(
        "SELECT suite, test_name, passed, weight FROM test_results "
        "WHERE run_id = ? ORDER BY id",
        (run_id,),
    ).fetchall()
    patch_text = row["patch_text"]
    return {
        "agent": agent, "task_id": task_id, "idx": idx,
        "found": True, "synthetic": False, "captured": True,
        "known_task": known_task,
        "task_version": row["task_version"],
        "status": row["status"],
        # RunScore field-by-field from raw columns (q_components never persisted).
        "score": {
            "status": row["status"],
            "gate_product": int(row["gate_product"]),
            "t_hidden": float(row["t_hidden"]),
            "q": float(row["q"]),
            "q_components": {},
            "q_components_available": False,
            "final_score": float(row["final_score"]),
            "functional_pass": bool(row["functional_pass"]),
            "voided": bool(row["voided"]),
        },
        "files_changed": int(row["files_changed"]),
        "lines_added": int(row["lines_added"]),
        "lines_removed": int(row["lines_removed"]),
        "transcript_hash": row["transcript_hash"],
        "duration_ms": int(row["duration_ms"]),
        "created_at": row["created_at"],
        "touched_protected": bool(row["touched_protected"]),
        "patch_text": patch_text,
        "patch_available": patch_text is not None,
        "test_results": [
            {
                "suite": tr["suite"],
                "test_name": tr["test_name"],
                "passed": bool(tr["passed"]),
                "weight": float(tr["weight"]),
            }
            for tr in test_rows
        ],
    }


def build_meta(stores: LoadedStores, ro: sqlite3.Connection) -> dict[str, Any]:
    """Static metadata: tasks (domains, difficulty, versions, evaluated versions),
    the model roster, synthetic baselines, and persisted-run provenance. No math."""
    return {
        "models": stores.models,
        "synthetic_agents": stores.synthetic_agents,
        "n_tasks": len(stores.task_ids),
        "tasks": [
            {
                "task_id": tid,
                "current_version": stores.tasks_meta[tid].get("current_version"),
                "evaluated_versions": stores.tasks_meta[tid].get(
                    "evaluated_versions", []
                ),
                "difficulty": stores.tasks_meta[tid].get("difficulty"),
                "activity": stores.tasks_meta[tid].get("activity"),
                "scale": stores.tasks_meta[tid].get("scale"),
                "dir": stores.tasks_meta[tid].get("dir"),
                "domains": [
                    {"domain": d, "weight": w}
                    for d, w in stores.tasks_meta[tid].get("domains", [])
                ],
            }
            for tid in stores.task_ids
        ],
        "observability": _summary_dict(stores.observability),
        "real_counts": {
            agent: {"n_runs": n_runs, "n_tasks": n_tasks}
            for agent, (n_runs, n_tasks) in stores.real_counts.items()
        },
        "notes": {
            "q_components": "Q components are not persisted in v0.1; always unavailable.",
            "trust": "Trusted local single-user tool; no sandbox-isolation guarantees.",
            "run_identity": "Runs are identified by (agent, task_id, idx), never runs.id.",
        },
    }
