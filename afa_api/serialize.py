"""PURE projection layer: dataclasses + raw rows -> JSON-able dicts.

NO statistics live here. Every number is read field-by-field off the frozen
kernel/runner dataclasses (AggregateResult, LeaderboardEntry, DomainScore,
RunScore, RunStoreSummary) or off the raw SQLite columns. The only transforms
are field selection, dict-key stringification (pass_at_k keys), and explicit
state tagging (captured / historical_only / not-captured / synthetic) and
counting of runs/tasks/versions. If you find yourself adding arithmetic, it
belongs in the kernel, not here.

Version semantics: the default views are the CURRENT benchmark (see
``store_load``): only runs whose task_version equals the task's current version
are aggregated. Older-version runs are HISTORICAL: preserved, labelled, exposed
per version, never pooled. Evidence scope: mock (synthetic) runs are excluded
from the default benchmark scope and reported in ``excluded``.

Legacy tuple identity is (agent, task_id, idx); exact forensic access uses native runs.id.
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

from . import evidence
from .db import MANIFEST_PATH
from .store_load import (
    SYNTHETIC_AGENTS,
    LoadedRun,
    LoadedStores,
    _build_manifest_meta,
    version_sort_key,
)


class InvalidQuery(ValueError):
    """A read endpoint was called with an unusable query combination."""


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


def _leaderboard_entry_dict(
    e: LeaderboardEntry, coverage: dict[str, int] | None = None
) -> dict[str, Any]:
    entry = {
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
    if coverage is not None:
        entry["coverage"] = coverage
    return entry


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
# Evidence accounting shared by several builders (counting only; no math)
# --------------------------------------------------------------------------- #

def _real_counts_dict(stores: LoadedStores) -> dict[str, Any]:
    """Per-agent CURRENT in-scope counts, in the long-standing exact shape
    ``{n_runs, n_tasks}`` (never extended: clients and tests compare it whole).
    Every roster model has an entry (0/0 for a historical-only model)."""
    out = {}
    for agent in stores.models:
        ev = stores.agent_evidence[agent]
        out[agent] = {"n_runs": ev.current_runs, "n_tasks": len(ev.current_tasks)}
    return out


def _evidence_counts_dict(stores: LoadedStores) -> dict[str, Any]:
    """Full per-agent current-vs-historical breakdown (a sibling of real_counts)."""
    out = {}
    for agent in stores.models:
        ev = stores.agent_evidence[agent]
        by_class: dict[str, int] = {}
        for run in stores.runs_for(agent=agent):
            if run.is_current:
                by_class[run.provenance.evidence_class] = (
                    by_class.get(run.provenance.evidence_class, 0) + 1
                )
        out[agent] = {
            "current_runs": ev.current_runs,
            "current_tasks": len(ev.current_tasks),
            "current_by_class": by_class,
            "historical_runs": ev.historical_runs,
            "historical_tasks": len(ev.historical_tasks),
            "historical_only_tasks": len(ev.historical_tasks - ev.current_tasks),
            "tasks_total": len(stores.task_ids),
            "coverage_complete": len(ev.current_tasks) == len(stores.task_ids),
        }
    return out


def _current_benchmark_dict(stores: LoadedStores) -> dict[str, Any]:
    """Benchmark-wide currency summary for the selected scope."""
    tasks_with_current = {
        r.record.task_id for r in stores.runs if r.is_current
    }
    return {
        "n_tasks": len(stores.task_ids),
        "tasks_with_current_evidence": len(tasks_with_current),
        "current_runs": sum(ev.current_runs for ev in stores.agent_evidence.values()),
        "historical_runs": sum(ev.historical_runs for ev in stores.agent_evidence.values()),
        "models_with_current_evidence": len(stores.current_models),
        "models_total": len(stores.models),
    }


def _excluded_dict(stores: LoadedStores) -> dict[str, Any]:
    return {
        "synthetic_runs": stores.excluded.get("synthetic_runs", 0),
        "synthetic_models": list(stores.excluded.get("synthetic_models", [])),
        "provenance_conflict_runs": stores.excluded.get("provenance_conflict_runs", 0),
    }


def _coverage(stores: LoadedStores, agent: str) -> dict[str, Any]:
    ev = stores.agent_evidence.get(agent)
    have = len(ev.current_tasks) if ev else 0
    return {
        "tasks_with_current_evidence": have,
        "tasks_total": len(stores.task_ids),
        "complete": have == len(stores.task_ids),
    }


def _run_evidence_fields(
    prov: evidence.RunProvenance, task_version: str, current_version: str | None
) -> dict[str, Any]:
    if current_version is None:
        version_status = None
    else:
        version_status = "current" if task_version == current_version else "historical"
    return {
        "backend_kind": prov.backend_kind,
        "evidence_class": prov.evidence_class,
        "provider_source": prov.provider_source,
        "version_status": version_status,
        "current_version": current_version,
    }


# --------------------------------------------------------------------------- #
# Endpoint builders. `stores` is the loaded LoadedStores; `ro` is a read-only
# sqlite3.Connection used only for raw column reads (patch_text, created_at,
# touched_protected, per-test results) that load_runs does not return.
# --------------------------------------------------------------------------- #

def build_overview(stores: LoadedStores, ro: sqlite3.Connection) -> dict[str, Any]:
    """Top-level dashboard: persisted-run provenance, model/task coverage, and
    the pooled (all-tasks) CURRENT leaderboard. Real store only (no synthetic
    baseline rows)."""
    overall = stores.observability
    per_agent = {
        agent: _summary_dict(stores.agent_observability[agent])
        for agent in stores.models
    }
    entries = afa.leaderboard(stores.real)
    return {
        "evidence_scope": stores.scope,
        "models": stores.models,
        "current_models": stores.current_models,
        "historical_only_models": stores.historical_only_models,
        "task_ids": stores.task_ids,
        "n_tasks": len(stores.task_ids),
        "real_counts": _real_counts_dict(stores),
        "evidence_counts": _evidence_counts_dict(stores),
        "current_benchmark": _current_benchmark_dict(stores),
        "excluded": _excluded_dict(stores),
        "observability": _summary_dict(overall),
        "agent_observability": per_agent,
        "leaderboard": [
            _leaderboard_entry_dict(e, _coverage(stores, e.agent)) for e in entries
        ],
        "synthetic_agents": stores.synthetic_agents,
    }


def build_leaderboard(
    stores: LoadedStores,
    ro: sqlite3.Connection,
    task_id: str | None = None,
    version: str | None = None,
) -> dict[str, Any]:
    """Wilson-LCB leaderboard, optionally scoped to one task (and, for a task,
    to one stored version). Real store only — matches the 3-way anchor (api ==
    raw SQL == report fn) for the default CURRENT view."""
    if version is not None and task_id is None:
        raise InvalidQuery("version requires task_id")
    if task_id is not None and task_id not in stores.task_ids:
        return {
            "task_id": task_id, "found": False, "entries": [],
            "evidence_scope": stores.scope,
        }
    if task_id is None:
        entries = afa.leaderboard(stores.real)
        return {
            "task_id": None,
            "found": True,
            "evidence_scope": stores.scope,
            "current_version": None,
            "version": None,
            "evidence_status": None,
            "entries": [
                _leaderboard_entry_dict(e, _coverage(stores, e.agent)) for e in entries
            ],
            "historical_only_agents": stores.historical_only_models,
        }

    current_version = stores.current_versions.get(task_id)
    selected = version if version is not None else current_version
    task_runs = stores.runs_for(task_id=task_id)
    at_selected = [r for r in task_runs if r.record.task_version == selected]
    if selected == current_version:
        entries = afa.leaderboard(stores.real, task_id=task_id)
        status = "current"
    else:
        status = "historical"
        if at_selected:
            scratch = stores.scratch_store(at_selected)
            try:
                entries = afa.leaderboard(scratch, task_id=task_id)
            finally:
                scratch.close()
        else:
            entries = []
    ranked = {r.record.agent for r in at_selected}
    return {
        "task_id": task_id,
        "found": True,
        "evidence_scope": stores.scope,
        "current_version": current_version,
        "version": selected,
        "evidence_status": status,
        "entries": [_leaderboard_entry_dict(e) for e in entries],
        "historical_only_agents": sorted(
            {r.record.agent for r in task_runs} - ranked
        ),
    }


def build_domains(
    stores: LoadedStores, ro: sqlite3.Connection, agent: str
) -> dict[str, Any]:
    """Per-domain capability profile for one agent (report fn domain_profile),
    computed from CURRENT evidence only."""
    captured = agent in stores.real.agents()
    scores = afa.domain_profile(stores.real, agent, stores.task_domains)
    synthetic = agent in SYNTHETIC_AGENTS
    ev = stores.agent_evidence.get(agent)
    if synthetic:
        status = "synthetic"
    elif captured:
        status = "current"
    elif ev is not None and ev.historical_runs:
        status = "historical_only"
    else:
        status = "none"
    return {
        "agent": agent,
        "captured": captured,
        "synthetic": synthetic,
        "evidence_scope": stores.scope,
        "evidence_status": status,
        "coverage": {
            "current_tasks": len(ev.current_tasks) if ev else 0,
            "historical_only_tasks": (
                len(ev.historical_tasks - ev.current_tasks) if ev else 0
            ),
            "tasks_total": len(stores.task_ids),
        },
        "domains": [_domain_score_dict(d) for d in scores],
    }


def _cell_run_dict(r: LoadedRun) -> dict[str, Any]:
    rec = r.record
    return {
        "agent": rec.agent,
        "task_id": rec.task_id,
        "idx": rec.idx,
        "run_id": rec.run_id,
        "task_version": rec.task_version,
        "status": rec.status.value,
        "score": _run_score_dict(rec.score),
        "backend_kind": r.provenance.backend_kind,
        "evidence_class": r.provenance.evidence_class,
    }


def build_cell(
    stores: LoadedStores,
    ro: sqlite3.Connection,
    agent: str,
    task_id: str,
    version: str | None = None,
) -> dict[str, Any]:
    """One (agent, task) cell: the aggregate of ONE stored version (default: the
    current version) plus a per-version directory of every stored version.

    ``state`` is about CURRENT benchmark evidence and is independent of
    ``version``; ``evidence_status`` describes the selected view. Versions are
    aggregated independently and never pooled.
    """
    synthetic = agent in SYNTHETIC_AGENTS
    known_task = task_id in stores.task_ids
    current_version = stores.current_versions.get(task_id)
    selected = version if version is not None else current_version

    cell_runs = stores.runs_for(agent=agent, task_id=task_id)
    current_runs = [r for r in cell_runs if r.is_current]
    historical_runs = [r for r in cell_runs if not r.is_current]
    historical_versions = sorted(
        {r.record.task_version for r in historical_runs},
        key=version_sort_key,
        reverse=True,
    )
    selected_runs = sorted(
        (r for r in cell_runs if selected is not None and r.record.task_version == selected),
        key=lambda r: (r.record.idx, r.record.run_id or 0),
    )

    if synthetic:
        state = "synthetic"
        evidence_status = "synthetic"
    else:
        if current_runs:
            state = "captured"
        elif historical_runs:
            state = "historical_only"
        else:
            state = "not_captured"
        if selected_runs:
            evidence_status = "current" if selected == current_version else "historical"
        else:
            evidence_status = "none"

    versions = []
    if not synthetic:
        for v in stores.versions_for(agent, task_id):
            v_runs = [r for r in cell_runs if r.record.task_version == v]
            agg = stores.aggregate_for(agent, task_id, v)
            versions.append(
                {
                    "version": v,
                    "status": "current" if v == current_version else "historical",
                    "n_runs": len(v_runs),
                    "run_ids": [r.record.run_id for r in v_runs],
                    "aggregate": _aggregate_dict(agg) if agg is not None else None,
                }
            )

    aggregate = None
    if selected_runs and not synthetic:
        selected_agg = stores.aggregate_for(agent, task_id, selected)
        aggregate = _aggregate_dict(selected_agg) if selected_agg is not None else None

    cell_excluded = stores.excluded_cells.get((agent, task_id), {})
    return {
        "agent": agent,
        "task_id": task_id,
        "known_task": known_task,
        "captured": state == "captured",
        "synthetic": synthetic,
        "state": state,
        "current_version": current_version,
        "selected_version": selected,
        "evidence_status": evidence_status,
        "evidence_scope": stores.scope,
        "current_runs": len(current_runs),
        "historical_runs": len(historical_runs),
        "historical_versions": historical_versions,
        "excluded": {
            "synthetic_runs": cell_excluded.get("synthetic_runs", 0),
            "provenance_conflict_runs": cell_excluded.get("provenance_conflict_runs", 0),
        },
        # Versions STORED for this cell across every evidence class (a persisted
        # fact independent of scope; see LoadedStores.stored_cell_versions).
        "task_versions": sorted(stores.stored_cell_versions.get((agent, task_id), set())),
        "has_current_evidence": bool(current_runs),
        "has_historical_evidence": bool(historical_runs),
        "runs": [_cell_run_dict(r) for r in selected_runs],
        "aggregate": aggregate,
        "versions": versions,
    }


# Raw columns load_runs does not return; fetch directly (plan-allowed).
def _runs_has_job_id(ro: sqlite3.Connection) -> bool:
    return any(
        row["name"] == "job_id"
        for row in ro.execute("PRAGMA table_info(runs)").fetchall()
    )


def _run_raw_sql(*, by_id: bool, has_job_id: bool) -> str:
    job_column = "r.job_id" if has_job_id else "NULL AS job_id"
    where = (
        "WHERE r.id = ?"
        if by_id
        else "WHERE r.agent = ? AND r.task_id = ? AND r.idx = ?"
    )
    return (
        "SELECT r.id, r.task_id, r.task_version, r.agent, r.idx, r.status, "
        "r.transcript_hash, r.duration_ms, r.created_at, "
        "s.gate_product, s.t_hidden, s.q, s.final_score, s.functional_pass, s.voided, "
        "d.files_changed, d.lines_added, d.lines_removed, d.touched_protected, d.patch_text, "
        f"{job_column} "
        "FROM runs r "
        "JOIN run_scores s ON s.run_id = r.id "
        "JOIN diffs d ON d.run_id = r.id "
        f"{where} "
        "ORDER BY r.id"
    )


# Kept as a current-schema inspection aid for existing callers/tests; public
# reads build the statement after checking whether the optional legacy column is
# present.
_RUN_RAW_SQL = _run_raw_sql(by_id=False, has_job_id=True)


def build_run(
    stores: LoadedStores,
    ro: sqlite3.Connection,
    agent: str,
    task_id: str,
    idx: int,
    version: str | None = None,
) -> dict[str, Any]:
    """One run detail by (agent, task_id, idx) within one stored version (default:
    the current version), regardless of evidence class — never by runs.id.

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

    current_version = stores.current_versions.get(task_id)
    selected = version if version is not None else current_version
    all_rows = ro.execute(
        _run_raw_sql(by_id=False, has_job_id=_runs_has_job_id(ro)),
        (agent, task_id, idx),
    ).fetchall()
    provenance = evidence.read_provenance(ro, [row["id"] for row in all_rows])
    # Forensic route: deliberately NOT filtered by evidence class. Mock and
    # legacy rows stay inspectable (each carries its evidence_class label); only
    # the stored version is selected, so (agent, task, idx) never collides across
    # versions. A task outside the pack has no current version to select against.
    rows = (
        all_rows if selected is None
        else [row for row in all_rows if row["task_version"] == selected]
    )
    if not rows:
        other_versions = sorted(
            {row["task_version"] for row in all_rows} - {selected},
            key=version_sort_key,
            reverse=True,
        )
        return {
            "agent": agent, "task_id": task_id, "idx": idx,
            "found": False, "synthetic": False, "captured": False,
            "known_task": known_task,
            "current_version": current_version,
            "selected_version": selected,
            "historical_versions": other_versions,
        }
    if len(rows) > 1:
        return {
            "agent": agent,
            "task_id": task_id,
            "idx": idx,
            "found": False,
            "ambiguous": True,
            "synthetic": False,
            "known_task": known_task,
            "candidate_run_ids": [row["id"] for row in rows],
        }
    return _real_run_dict(
        ro, rows[0], known_task=known_task,
        provenance=provenance[rows[0]["id"]], current_version=current_version,
    )


def _real_run_dict(
    ro: sqlite3.Connection,
    row: sqlite3.Row,
    *,
    known_task: bool = True,
    provenance: evidence.RunProvenance | None = None,
    current_version: str | None = None,
) -> dict[str, Any]:
    """Project one exact raw row, shared by tuple and native-ID routes."""
    run_id = row["id"]
    test_rows = ro.execute(
        "SELECT suite, test_name, passed, weight FROM test_results "
        "WHERE run_id = ? ORDER BY id",
        (run_id,),
    ).fetchall()
    patch_text = row["patch_text"]
    prov = provenance or evidence.UNKNOWN_PROVENANCE
    return {
        "run_id": run_id,
        "job_id": row["job_id"],
        "agent": row["agent"],
        "task_id": row["task_id"],
        "idx": row["idx"],
        "found": True, "synthetic": False, "captured": True,
        "known_task": known_task,
        "task_version": row["task_version"],
        **_run_evidence_fields(prov, row["task_version"], current_version),
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


def _current_version_of(task_id: str) -> str | None:
    """Current version of one task, independent of any aggregate projection."""
    try:
        _m, current_versions, *_rest = _build_manifest_meta(MANIFEST_PATH)
    except Exception:  # noqa: BLE001 - forensic reads must not depend on the manifest
        return None
    return current_versions.get(task_id)


def build_run_by_id(ro: sqlite3.Connection, run_id: int) -> dict[str, Any]:
    """Exact immutable forensic lookup, independent of aggregate projection."""
    row = ro.execute(
        _run_raw_sql(by_id=True, has_job_id=_runs_has_job_id(ro)),
        (run_id,),
    ).fetchone()
    if row is None:
        return {"run_id": run_id, "found": False, "synthetic": False}
    provenance = evidence.read_provenance(ro, [run_id]).get(run_id)
    return _real_run_dict(
        ro, row, known_task=True, provenance=provenance,
        current_version=_current_version_of(row["task_id"]),
    )


def build_meta(stores: LoadedStores, ro: sqlite3.Connection) -> dict[str, Any]:
    """Static metadata: tasks (domains, difficulty, versions, evaluated versions,
    current vs historical run counts), the model roster, synthetic baselines, and
    persisted-run provenance. No math."""
    return {
        "evidence_scope": stores.scope,
        "models": stores.models,
        "current_models": stores.current_models,
        "historical_only_models": stores.historical_only_models,
        "synthetic_agents": stores.synthetic_agents,
        "n_tasks": len(stores.task_ids),
        "tasks": [
            {
                "task_id": tid,
                "current_version": stores.tasks_meta[tid].get("current_version"),
                "evaluated_versions": stores.tasks_meta[tid].get(
                    "evaluated_versions", []
                ),
                "current_runs": stores.tasks_meta[tid].get("current_runs", 0),
                "historical_runs": stores.tasks_meta[tid].get("historical_runs", 0),
                "historical_versions": stores.tasks_meta[tid].get(
                    "historical_versions", []
                ),
                "has_current_evidence": stores.tasks_meta[tid].get("current_runs", 0) > 0,
                "models_with_current_evidence": stores.tasks_meta[tid].get(
                    "models_with_current_evidence", 0
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
        "real_counts": _real_counts_dict(stores),
        "evidence_counts": _evidence_counts_dict(stores),
        "current_benchmark": _current_benchmark_dict(stores),
        "excluded": _excluded_dict(stores),
        "notes": {
            "q_components": "Q components are not persisted in v0.1; always unavailable.",
            "trust": "Trusted local single-user tool; no sandbox-isolation guarantees.",
            "run_identity": "Runs are identified by (agent, task_id, idx), never runs.id.",
            "current_benchmark": (
                "Aggregates use CURRENT task-version evidence only; older-version "
                "evidence is historical and never pooled."
            ),
        },
    }


def build_export(stores: LoadedStores) -> dict[str, Any]:
    """JSON export of the CURRENT-benchmark aggregates in the selected scope."""
    return {
        "format": "json",
        "snapshot_note": (
            "Snapshot of the current persisted aggregates (current task versions "
            "only; historical-version evidence is preserved but never pooled); "
            "synthetic baselines excluded."
        ),
        "evidence_scope": stores.scope,
        "models": stores.models,
        "current_models": stores.current_models,
        "historical_only_models": stores.historical_only_models,
        "task_ids": stores.task_ids,
        "real_counts": _real_counts_dict(stores),
        "evidence_counts": _evidence_counts_dict(stores),
        "current_benchmark": _current_benchmark_dict(stores),
        "excluded": _excluded_dict(stores),
        "leaderboard": [
            {
                "agent": e.agent, "pass_rate": e.pass_rate,
                "wilson_low": e.wilson_low, "wilson_high": e.wilson_high,
                "n": e.n, "provisional": e.provisional,
                "rank_low": e.rank_low, "rank_high": e.rank_high,
                "coverage": _coverage(stores, e.agent),
            }
            for e in afa.leaderboard(stores.real)
        ],
    }
