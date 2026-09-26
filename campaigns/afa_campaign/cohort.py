"""Read-only checks of campaign evidence in the campaign database.

This is the single definition of "a valid campaign cell", shared by the launcher
(after each evaluation), the completeness validator, the monitor and the
analysis. A cell's evaluation counts only if EVERY check passes:

* the evaluation exists, SUCCEEDED, is ``fresh`` (no source evaluation), and its
  persisted parameters verify against its own creation snapshot (the runtime's
  ``verify_persisted_params``) and match the campaign manifest exactly (model,
  single task, repetitions, backend kind + URL, temperature, base seed, timeout,
  evaluation name);
* its snapshot pins the manifest's task version AND digest;
* it has exactly the expected trial positions, all completed with FRESH evidence
  originating in this evaluation;
* every trial's raw run exists, is owned by this evaluation (``runs.job_id``),
  matches the model / task / version / position, carries the manifest backend in
  ``runs.backend_kind`` and classifies as ``real`` provenance (never synthetic,
  legacy or conflict), has a score row of the pinned formula and a diff row;
* the evaluation owns no raw run beyond its trial positions.

Infrastructure-voided positions are not a check failure (they are never counted
against a model) but are reported, and the launcher halts on them.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import paths  # noqa: F401  (import bootstrap)
from .manifest import Cell, Manifest

from afa_api import db as app_db  # noqa: E402
from afa_api import evidence, jobs  # noqa: E402


@dataclass
class CellCheck:
    cell: str
    evaluation_id: str | None
    ok: bool = False
    job_status: str | None = None
    problems: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    positions: dict[int, dict] = field(default_factory=dict)
    run_ids: list[int] = field(default_factory=list)
    n_runs: int = 0
    valid: int = 0
    passed: int = 0
    voided: int = 0
    timeouts: int = 0
    agent_errors: int = 0
    request_timeout_hits: int = 0
    classes: dict[str, int] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "cell": self.cell,
            "evaluation_id": self.evaluation_id,
            "ok": self.ok,
            "job_status": self.job_status,
            "problems": list(self.problems),
            "warnings": list(self.warnings),
            "run_ids": list(self.run_ids),
            "n_runs": self.n_runs,
            "valid": self.valid,
            "passed": self.passed,
            "voided": self.voided,
            "timeouts": self.timeouts,
            "agent_errors": self.agent_errors,
            "request_timeout_hits": self.request_timeout_hits,
            "classes": dict(self.classes),
        }


def open_readonly(db_path: str | Path) -> sqlite3.Connection:
    path = Path(db_path)
    if not path.exists():
        raise FileNotFoundError(f"campaign database not found: {path}")
    return app_db.connect_readonly(path)


def _params_name(params_json: Any) -> str | None:
    try:
        value = json.loads(params_json)
    except (TypeError, ValueError, RecursionError):
        return None
    name = value.get("name") if isinstance(value, dict) else None
    return name if isinstance(name, str) else None


def _has_table(conn: sqlite3.Connection, name: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone() is not None


def evaluations_named(conn: sqlite3.Connection, prefix: str) -> list[dict]:
    """Every evaluation whose persisted name starts with the campaign prefix."""
    if not _has_table(conn, "evaluation_jobs"):
        return []
    out = []
    for row in conn.execute("SELECT id, status, params_json, created_at FROM evaluation_jobs"):
        name = _params_name(row["params_json"])
        if name is not None and name.startswith(prefix + ":"):
            out.append({"id": row["id"], "name": name, "status": row["status"], "created_at": row["created_at"]})
    return sorted(out, key=lambda r: (r["created_at"] or "", r["id"]))


def all_evaluations(conn: sqlite3.Connection) -> list[dict]:
    if not _has_table(conn, "evaluation_jobs"):
        return []
    return [
        {"id": row["id"], "status": row["status"], "name": _params_name(row["params_json"])}
        for row in conn.execute("SELECT id, status, params_json FROM evaluation_jobs")
    ]


def active_evaluations(conn: sqlite3.Connection) -> list[str]:
    """Every queued/running evaluation in the database (the API's list is capped
    at the newest 200, so one-at-a-time checks also ask the database)."""
    if not _has_table(conn, "evaluation_jobs"):
        return []
    return [r["id"] for r in conn.execute(
        "SELECT id FROM evaluation_jobs WHERE status IN ('queued', 'running') ORDER BY created_at")]


def running_evaluations(conn: sqlite3.Connection) -> list[str]:
    """Evaluations executing trials right now (status 'running')."""
    if not _has_table(conn, "evaluation_jobs"):
        return []
    return [r["id"] for r in conn.execute(
        "SELECT id FROM evaluation_jobs WHERE status = 'running' ORDER BY created_at")]


def overlapping_evaluations(conn: sqlite3.Connection, evaluation_id: str) -> list[str]:
    """Other evaluations whose trials shared the model server with this
    evaluation's completed trials (the app runs every evaluation in its own
    thread): a completed trial whose [claimed_at, completed_at] interval
    overlaps one of ours, or a trial still in flight (claimed, its evaluation
    queued/running) that was claimed before one of ours completed. Timestamps
    are the runtime's second-resolution UTC ``datetime('now')`` values, compared
    strictly (overlaps shorter than a second are invisible)."""
    if not _has_table(conn, "evaluation_trials"):
        return []
    rows = conn.execute(
        "SELECT DISTINCT o.evaluation_id FROM evaluation_trials t "
        "JOIN evaluation_trials o ON o.evaluation_id <> t.evaluation_id "
        "JOIN evaluation_jobs j ON j.id = o.evaluation_id "
        "WHERE t.evaluation_id = ? AND t.claimed_at IS NOT NULL AND t.completed_at IS NOT NULL "
        "AND o.claimed_at IS NOT NULL AND o.claimed_at < t.completed_at "
        "AND ((o.completed_at IS NOT NULL AND o.completed_at > t.claimed_at) "
        "  OR (o.completed_at IS NULL AND o.trial_state = 'claimed' AND j.status IN ('queued', 'running'))) "
        "ORDER BY o.evaluation_id",
        (evaluation_id,),
    )
    return [r[0] for r in rows]


def resume_event_count(conn: sqlite3.Connection, evaluation_id: str) -> int:
    """How many times the app resumed this evaluation (only the runtime's
    resume_job emits 'job_resumed'; startup recovery emits 'job_reclaimed')."""
    if not _has_table(conn, "job_events"):
        return 0
    return conn.execute(
        "SELECT COUNT(*) FROM job_events WHERE job_id=? AND type='job_resumed'", (evaluation_id,)
    ).fetchone()[0]


def resume_event_times(conn: sqlite3.Connection, evaluation_id: str) -> list[str]:
    """UTC times ('YYYY-MM-DD HH:MM:SS') of the app's 'job_resumed' events, in order."""
    if not _has_table(conn, "job_events"):
        return []
    return [r[0] for r in conn.execute(
        "SELECT ts FROM job_events WHERE job_id=? AND type='job_resumed' ORDER BY seq", (evaluation_id,))]


def halt_snapshot(conn: sqlite3.Connection, evaluation_id: str) -> dict | None:
    """What a failed/canceled evaluation looked like when the campaign halted on
    it. Any later difference (another finish time, more completed trials, a
    resume event) means it was resumed outside the campaign tooling."""
    row = conn.execute(
        "SELECT status, finished_at FROM evaluation_jobs WHERE id=?", (evaluation_id,)
    ).fetchone()
    if row is None:
        return None
    completed = conn.execute(
        "SELECT COUNT(*) FROM evaluation_trials WHERE evaluation_id=? AND trial_state='completed'",
        (evaluation_id,),
    ).fetchone()[0]
    return {"status": row["status"], "finished_at": row["finished_at"], "completed_trials": completed,
            "resume_events": resume_event_count(conn, evaluation_id)}


def jobless_run_count(conn: sqlite3.Connection) -> int:
    """Raw runs not created by any evaluation (e.g. rows seeded from the
    historical evidence). A clean campaign database has none."""
    cols = {r[1] for r in conn.execute("PRAGMA table_info(runs)")}
    if "job_id" not in cols:
        return conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
    return conn.execute("SELECT COUNT(*) FROM runs WHERE job_id IS NULL").fetchone()[0]


def evaluation_progress(conn: sqlite3.Connection, evaluation_id: str) -> dict:
    """Trial-state counts of one evaluation (in-flight monitoring)."""
    row = conn.execute(
        "SELECT status, total_runs, completed_runs, passed_runs, failed_runs, voided_runs "
        "FROM evaluation_jobs WHERE id=?",
        (evaluation_id,),
    ).fetchone()
    if row is None:
        return {"status": None}
    states: dict[str, int] = {}
    for trial in conn.execute(
        "SELECT trial_state, COUNT(*) AS n FROM evaluation_trials WHERE evaluation_id=? GROUP BY trial_state",
        (evaluation_id,),
    ):
        states[trial["trial_state"]] = trial["n"]
    return {
        "status": row["status"],
        "total": row["total_runs"],
        "completed": row["completed_runs"],
        "passed": row["passed_runs"],
        "failed": row["failed_runs"],
        "voided": row["voided_runs"],
        "trial_states": states,
    }


def check_cell_evaluation(
    conn: sqlite3.Connection, manifest: Manifest, cell: Cell, evaluation_id: str | None
) -> CellCheck:
    check = CellCheck(cell=cell.key, evaluation_id=evaluation_id)
    problems = check.problems
    if not evaluation_id:
        problems.append("no evaluation recorded for this cell")
        return check
    task = manifest.task_by_id.get(cell.task_id)
    if task is None:
        problems.append(f"task {cell.task_id} is not in the manifest")
        return check
    reps = manifest.repetitions
    backend = manifest.backend
    gen = manifest.generation

    row = conn.execute("SELECT * FROM evaluation_jobs WHERE id=?", (evaluation_id,)).fetchone()
    if row is None:
        problems.append("evaluation is missing from the campaign database")
        return check
    keys = row.keys()
    check.job_status = row["status"]
    if row["status"] != "succeeded":
        problems.append(f"evaluation status is {row['status']!r}, not 'succeeded'")
    mode = row["mode"] if "mode" in keys else None
    source = row["source_evaluation_id"] if "source_evaluation_id" in keys else None
    if mode != "fresh" or source is not None:
        problems.append(f"evaluation mode is {mode!r} (source {source!r}); campaign evidence must be fresh")

    snapshot_json = row["snapshot_json"] if "snapshot_json" in keys else None
    try:
        params = jobs.verify_persisted_params(row["params_json"], snapshot_json, mode, source)
    except jobs.InvalidPersistedParams as exc:
        problems.append(f"persisted parameters do not verify: {exc}")
        params = None
    if params is not None:
        expected = {
            "model": cell.model,
            "tasks": [cell.task_id],
            "repeats": reps,
            "backend.kind": backend["kind"],
            "backend.base_url": backend["base_url"],
            "temperature": float(gen["temperature"]),
            "base_seed": gen["base_seed"],
            "request_timeout_s": gen["request_timeout_s"],
            "name": manifest.evaluation_name(cell),
        }
        actual = {
            "model": params.model,
            "tasks": list(params.tasks),
            "repeats": params.repeats,
            "backend.kind": params.backend.kind,
            "backend.base_url": jobs.effective_backend_url(params),
            "temperature": float(params.temperature),
            "base_seed": params.base_seed,
            "request_timeout_s": params.request_timeout_s,
            "name": params.name,
        }
        for key, want in expected.items():
            if actual[key] != want:
                problems.append(f"parameter {key} is {actual[key]!r}, manifest requires {want!r}")

    snapshot = jobs._loads_finite(snapshot_json) if snapshot_json else None
    snap_tasks = snapshot.get("tasks") if isinstance(snapshot, dict) else None
    if not (isinstance(snap_tasks, list) and len(snap_tasks) == 1 and isinstance(snap_tasks[0], dict)):
        problems.append("evaluation snapshot does not pin exactly one task")
    else:
        pinned = snap_tasks[0]
        if pinned.get("task_id") != cell.task_id:
            problems.append(f"snapshot task is {pinned.get('task_id')!r}")
        if pinned.get("task_version") != task["task_version"]:
            problems.append(
                f"snapshot task version {pinned.get('task_version')!r} != manifest {task['task_version']!r}"
            )
        if pinned.get("task_digest") != task["task_digest"]:
            problems.append("snapshot task digest differs from the campaign's frozen digest")

    trials = conn.execute(
        "SELECT * FROM evaluation_trials WHERE evaluation_id=? ORDER BY task_id, idx", (evaluation_id,)
    ).fetchall()
    positions = sorted(int(t["idx"]) for t in trials)
    if positions != list(range(reps)) or any(t["task_id"] != cell.task_id for t in trials):
        problems.append(f"trial positions {positions} (tasks {sorted({t['task_id'] for t in trials})}) "
                        f"!= expected 0..{reps - 1} of {cell.task_id}")
    run_ids: list[int] = []
    trial_by_run: dict[int, Any] = {}
    for trial in trials:
        idx = int(trial["idx"])
        where = f"position {idx}"
        if trial["trial_state"] != "completed":
            problems.append(f"{where}: trial is {trial['trial_state']!r}")
        if trial["evidence_state"] != "fresh":
            problems.append(f"{where}: evidence is {trial['evidence_state']!r}, not fresh")
        if trial["origin_evaluation_id"] != evaluation_id or trial["source_evaluation_id"] is not None:
            problems.append(f"{where}: evidence does not originate in this evaluation")
        if trial["task_version"] != task["task_version"] or trial["task_digest"] != task["task_digest"]:
            problems.append(f"{where}: trial version/digest differ from the manifest")
        if trial["run_id"] is None:
            problems.append(f"{where}: no raw run")
            continue
        run_ids.append(int(trial["run_id"]))
        trial_by_run[int(trial["run_id"])] = trial
    check.run_ids = sorted(run_ids)
    check.n_runs = len(run_ids)

    if run_ids:
        marks = ",".join("?" for _ in run_ids)
        run_rows = {
            int(r["id"]): r
            for r in conn.execute(
                "SELECT r.id, r.agent, r.task_id, r.task_version, r.idx, r.status, r.job_id, r.backend_kind, "
                "r.duration_ms, "
                "s.functional_pass, s.voided, s.final_score, "
                "(SELECT COUNT(*) FROM diffs d WHERE d.run_id = r.id) AS diff_rows "
                "FROM runs r LEFT JOIN run_scores s ON s.run_id = r.id"
                f"{evidence.score_formula_predicate(conn)} "
                f"WHERE r.id IN ({marks})",
                run_ids,
            )
        }
        provenance = evidence.read_provenance(conn, run_ids)
        for run_id in run_ids:
            trial = trial_by_run[run_id]
            where = f"position {int(trial['idx'])} (run {run_id})"
            run = run_rows.get(run_id)
            if run is None:
                problems.append(f"{where}: raw run row is missing")
                continue
            if run["job_id"] != evaluation_id:
                problems.append(f"{where}: raw run is owned by evaluation {run['job_id']!r}")
            if (run["agent"], run["task_id"], int(run["idx"])) != (cell.model, cell.task_id, int(trial["idx"])):
                problems.append(f"{where}: raw run identity {run['agent']}/{run['task_id']}/{run['idx']} "
                                "does not match its trial")
            if run["task_version"] != task["task_version"]:
                problems.append(f"{where}: raw run version {run['task_version']!r} is not the current version")
            if run["backend_kind"] != backend["kind"]:
                problems.append(f"{where}: runs.backend_kind is {run['backend_kind']!r}, "
                                f"campaign requires {backend['kind']!r}")
            cls = provenance.get(run_id, evidence.UNATTESTED_PROVENANCE).evidence_class
            check.classes[cls] = check.classes.get(cls, 0) + 1
            if cls != evidence.CLASS_REAL:
                problems.append(f"{where}: provenance class is {cls!r}, not 'real'")
            if run["functional_pass"] is None:
                problems.append(f"{where}: no score row of formula {evidence.SCORE_FORMULA_VERSION}")
            if not run["diff_rows"]:
                problems.append(f"{where}: no diff row")
            status = run["status"]
            voided = bool(run["voided"]) or status == "infra_failure"
            check.positions[int(trial["idx"])] = {
                "run_id": run_id,
                "status": status,
                "functional_pass": bool(run["functional_pass"]),
                "voided": voided,
                "final_score": run["final_score"],
                "duration_ms": run["duration_ms"],
            }
            # A TIMEOUT that lasted the whole model-request timeout means the model
            # server never answered: a slow model and a stalled server look alike
            # here (the runtime checks the task's wall clock before infra failure).
            if status == "timeout" and run["duration_ms"] is not None and (
                    int(run["duration_ms"]) >= int(gen["request_timeout_s"]) * 1000 - 2000):
                check.request_timeout_hits += 1
            if voided:
                check.voided += 1
            else:
                check.valid += 1
                check.passed += int(bool(run["functional_pass"]))
                check.timeouts += int(status == "timeout")
                check.agent_errors += int(status == "agent_error")

    extra = [
        int(r["id"])
        for r in conn.execute("SELECT id FROM runs WHERE job_id=?", (evaluation_id,))
        if int(r["id"]) not in set(run_ids)
    ]
    if extra:
        problems.append(f"evaluation owns raw runs outside its trial positions: {extra}")
    if check.voided:
        check.warnings.append(
            f"{check.voided} infrastructure-voided position(s): excluded from n, never counted "
            "against the model; the launcher halts so the backend can be investigated"
        )
    check.ok = not problems
    return check


def load_cell_records(db_path: Path, check: CellCheck) -> list:
    """The RunRecords (kernel scoring inputs) of one VALID campaign cell."""
    import afa_runner as afa

    if not check.ok:
        raise ValueError(f"cell {check.cell} is not valid campaign evidence")
    model, task_id = check.cell.split("|", 1)
    wanted = set(check.run_ids)
    store = afa.SqliteRunStore.open_readonly(db_path)
    try:
        records = [r for r in store.load_runs(task_id=task_id, agent=model) if r.run_id in wanted]
    finally:
        store.close()
    if len(records) != len(wanted):
        raise ValueError(f"cell {check.cell}: loaded {len(records)} of {len(wanted)} runs")
    return records
