"""Compact campaign progress monitor (existing evaluation data only).

Reads the ledger and the campaign database read-only; works whether or not the
app is running. Completed / passed / failed / voided counts come from
campaign-owned evaluations only.
"""

from __future__ import annotations

from . import cohort
from .ledger import FAILED, CANCELED, HALTING, NEEDS_ATTENTION, REJECTED, SUBMITTED, SUBMITTING, SUCCEEDED, SUPERSEDED, Ledger, LedgerError
from .manifest import Manifest


def campaign_status(manifest: Manifest, phase: str = "all") -> dict:
    cells = manifest.cells(phase)
    reps = manifest.repetitions
    try:
        ledger: Ledger | None = Ledger.load(
            manifest.ledger_path(), campaign_id=manifest.campaign_id, manifest_sha256=manifest.sha256
        )
        ledger_error = None
    except LedgerError as exc:
        ledger, ledger_error = None, str(exc)
    from .launcher import reference_digests, reference_ollama_version
    from .validate import assess_cell

    reference = reference_digests(ledger) if ledger else {}
    reference_version = reference_ollama_version(ledger) if ledger else None
    db_path = manifest.db_path()
    conn = cohort.open_readonly(db_path) if db_path.exists() else None

    per_model = {
        m: {"cells": 0, "cells_complete": 0, "planned_runs": 0, "completed_runs": 0, "passed": 0,
            "failed": 0, "voided": 0}
        for m in manifest.models if any(c.model == m for c in cells)
    }
    task_done: dict[str, list[bool]] = {}
    rows = []
    # completed / passed / failed / voided count ONLY evidence the validator would
    # accept (succeeded cells passing every check). Positions of evaluations still
    # in flight or resumable (failed / canceled) are "in progress"; evidence that
    # can never count (rejected, needs-attention, succeeded-but-invalid) is
    # "excluded".
    totals = {"planned_runs": len(cells) * reps, "completed_runs": 0, "passed": 0, "failed": 0,
              "voided": 0, "timeouts": 0, "in_progress_runs": 0, "excluded_runs": 0}
    running, halted, superseded = [], [], 0
    try:
        for cell in cells:
            stats = per_model[cell.model]
            stats["cells"] += 1
            stats["planned_runs"] += reps
            entry = ledger.active_entry(cell.key) if ledger else None
            if ledger:
                superseded += sum(1 for e in ledger.entries_for(cell.key) if e["state"] == SUPERSEDED)
            state = entry["state"] if entry else "not_started"
            completed = passed = failed = voided = timeouts = in_progress = excluded = 0
            if entry is not None and conn is not None and (state == SUCCEEDED or entry.get("evaluation_id")):
                if state == SUCCEEDED:
                    # the validator's own acceptance predicate: the monitor never
                    # counts evidence the validator would refuse
                    verdict = assess_cell(conn, manifest, cell, entry, reference, reference_version)
                    check = verdict["check"]
                    if verdict["accepted"]:
                        completed, passed, voided, timeouts = check.n_runs, check.passed, check.voided, check.timeouts
                        failed = check.valid - check.passed
                    else:
                        state = "succeeded-but-invalid"
                        excluded = check.n_runs
                else:
                    progress = cohort.evaluation_progress(conn, entry["evaluation_id"])
                    if state in (REJECTED, NEEDS_ATTENTION):
                        excluded = progress.get("completed") or 0
                    else:
                        in_progress = progress.get("completed") or 0
                    if state in (SUBMITTED, SUBMITTING):
                        if progress.get("status") in ("succeeded", "failed", "canceled"):
                            # finished, but no launcher has accepted/rejected it yet
                            state = "awaiting_finalize"
                        else:
                            running.append({"cell": cell.key, "evaluation_id": entry["evaluation_id"],
                                            "status": progress.get("status"), "completed": in_progress})
            if state in HALTING or state in ("succeeded-but-invalid", "awaiting_finalize"):
                halted.append({"cell": cell.key, "state": state, "evaluation_id": entry and entry.get("evaluation_id")})
            done = state == SUCCEEDED and conn is not None
            stats["cells_complete"] += int(done)
            stats["completed_runs"] += completed
            stats["passed"] += passed
            stats["failed"] += failed
            stats["voided"] += voided
            totals["completed_runs"] += completed
            totals["passed"] += passed
            totals["failed"] += failed
            totals["voided"] += voided
            totals["timeouts"] += timeouts
            totals["in_progress_runs"] += in_progress
            totals["excluded_runs"] += excluded
            task_done.setdefault(cell.task_id, []).append(done)
            rows.append({"cell": cell.key, "phase": cell.phase, "state": state, "completed": completed,
                         "passed": passed, "voided": voided, "in_progress": in_progress, "excluded": excluded,
                         "evaluation_id": entry.get("evaluation_id") if entry else None})
    finally:
        if conn is not None:
            conn.close()
    totals["remaining_runs"] = totals["planned_runs"] - totals["completed_runs"]
    cells_complete = sum(1 for r in rows if r["state"] == SUCCEEDED and conn is not None)
    return {
        "campaign_id": manifest.campaign_id,
        "scope": phase,
        "ledger_error": ledger_error,
        "database_present": db_path.exists(),
        "totals": totals,
        "cells": {"planned": len(cells), "complete": cells_complete, "incomplete": len(cells) - cells_complete},
        "models_complete": sum(1 for s in per_model.values() if s["cells_complete"] == s["cells"]),
        "models_total": len(per_model),
        "tasks_complete": sum(1 for flags in task_done.values() if all(flags)),
        "tasks_total": len(task_done),
        "evaluations_running": running,
        "evaluations_halted": halted,
        "failed_states": sorted({h["state"] for h in halted if h["state"] in (FAILED, CANCELED, REJECTED, NEEDS_ATTENTION)}),
        "superseded_entries": superseded,
        "per_model": per_model,
        "cells_detail": rows,
    }


def render(status: dict) -> str:
    t = status["totals"]
    lines = [
        f"campaign {status['campaign_id']} - scope {status['scope']}",
        f"  planned runs   {t['planned_runs']}",
        f"  completed      {t['completed_runs']}   remaining {t['remaining_runs']}   "
        f"(in progress {t['in_progress_runs']}, excluded {t['excluded_runs']})",
        f"  passed {t['passed']}   failed {t['failed']} (timeouts {t['timeouts']})   voided/infra {t['voided']}",
        f"  cells complete {status['cells']['complete']}/{status['cells']['planned']}   "
        f"models complete {status['models_complete']}/{status['models_total']}   "
        f"tasks complete {status['tasks_complete']}/{status['tasks_total']}",
        f"  evaluations running {len(status['evaluations_running'])}   halted/failed "
        f"{len(status['evaluations_halted'])}   superseded entries {status['superseded_entries']}",
    ]
    if status["ledger_error"]:
        lines.append(f"  ledger: {status['ledger_error']}")
    if not status["database_present"]:
        lines.append("  campaign database MISSING: nothing can be counted as complete")
    lines.append("  per model:")
    for model, s in status["per_model"].items():
        lines.append(
            f"    {model:22s} cells {s['cells_complete']:3d}/{s['cells']:<3d} runs "
            f"{s['completed_runs']:4d}/{s['planned_runs']:<4d} passed {s['passed']:4d} "
            f"failed {s['failed']:4d} voided {s['voided']}"
        )
    for run in status["evaluations_running"]:
        lines.append(f"  running: {run['cell']} {run['evaluation_id']} {run['status']} ({run['completed']} done)")
    for halt in status["evaluations_halted"]:
        lines.append(f"  HALTED: {halt['cell']} is {halt['state']} ({halt['evaluation_id']})")
    return "\n".join(lines)
