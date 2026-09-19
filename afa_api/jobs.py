"""Durable evaluation control-plane state and trial associations.

``evaluation_jobs.id`` is the public evaluation identity. ``evaluation_trials``
owns requested positions and is the canonical completion source; raw ``runs.id``
remains the immutable forensic identity. Events and counters are projections and
may lag a committed trial without changing completion truth.
"""

from __future__ import annotations

import errno
import fcntl
import hashlib
import json
import math
import sqlite3
import tempfile
import threading
import uuid
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from . import db, evidence
from .schemas import (
    DEFAULT_BACKEND_URLS,
    TERMINAL_STATES,
    Job,
    JobCounters,
    JobCreate,
    JobEvent,
    JobParams,
)


class JobStateError(ValueError):
    """The requested lifecycle operation is not safe for this evaluation."""


class InvalidPersistedParams(JobStateError):
    """Persisted evaluation parameters cannot be trusted for execution.

    Raised by the strict execution parse. The message never echoes persisted
    values (they may be corrupt or credential-bearing): only field names.
    """


class TrialClaimError(RuntimeError):
    """A worker lost its conditional trial claim before publishing evidence."""


class EvaluationOwnerLock:
    """A same-host lock held for the complete model/grading execution."""

    def __init__(self, path: Path, handle) -> None:
        self.path = path
        self._handle = handle
        self._released = False

    def release(self) -> None:
        if self._released:
            return
        try:
            fcntl.flock(self._handle.fileno(), fcntl.LOCK_UN)
        finally:
            self._handle.close()
            with _OWNER_LOCKS_GUARD:
                _ACTIVE_OWNER_LOCKS.discard(self.path)
            self._released = True

    def __enter__(self) -> "EvaluationOwnerLock":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.release()


_OWNER_LOCKS_GUARD = threading.Lock()
_ACTIVE_OWNER_LOCKS: set[Path] = set()


def _owner_lock_path(conn: sqlite3.Connection, evaluation_id: str) -> Path:
    rows = conn.execute("PRAGMA database_list").fetchall()
    db_name = next((row[2] for row in rows if row[1] == "main" and row[2]), "")
    identity = str(Path(db_name).expanduser().resolve()) if db_name else f"memory:{id(conn)}"
    db_key = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]
    job_key = hashlib.sha256(evaluation_id.encode("utf-8")).hexdigest()
    root = Path(tempfile.gettempdir()) / "agentforge-arena-evaluation-locks" / db_key
    root.mkdir(parents=True, exist_ok=True)
    return root / f"{job_key}.lock"


def try_acquire_owner_lock(
    conn: sqlite3.Connection, evaluation_id: str
) -> EvaluationOwnerLock | None:
    """Acquire the local owner guard without treating lease age as liveness."""
    path = _owner_lock_path(conn, evaluation_id)
    with _OWNER_LOCKS_GUARD:
        if path in _ACTIVE_OWNER_LOCKS:
            return None
        handle = path.open("a+")
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            handle.close()
            if exc.errno in (errno.EACCES, errno.EAGAIN):
                return None
            raise
        _ACTIVE_OWNER_LOCKS.add(path)
        return EvaluationOwnerLock(path, handle)


# --------------------------------------------------------------------------- #
# Snapshots and row projections
# --------------------------------------------------------------------------- #


def _row_value(row: sqlite3.Row, key: str, default: Any = None) -> Any:
    return row[key] if key in row.keys() else default


_INVALID_PREFIX = "invalid persisted evaluation parameters"

# Every field an EXECUTABLE evaluation must carry explicitly. JobParams supplies
# defaults (model "mock", backend mock, ...) for convenience when CREATING a job;
# a persisted row is never allowed to fall back on them.
_EXECUTION_REQUIRED_KEYS = (
    "model", "backend", "tasks", "repeats", "base_seed", "temperature",
    "request_timeout_s",
)


def _validation_field_names(exc: ValidationError) -> str:
    """Field names only; pydantic messages/inputs may echo secrets or garbage."""
    names = {
        ".".join(str(part) for part in err["loc"]) or "params" for err in exc.errors()
    }
    return ", ".join(sorted(names))


def strict_params_from_json(raw_json: str) -> JobParams:
    """Parse persisted params for EXECUTION: no defaults, no coercion, no repair.

    Anything malformed raises InvalidPersistedParams. In particular a corrupt row
    can never degrade to ``JobParams()`` (mock backend / model "mock"), which
    would run the reference-overlay mock agent under a job that claims something
    else.
    """
    try:
        raw = json.loads(raw_json)
    except (TypeError, ValueError):
        raise InvalidPersistedParams(
            f"{_INVALID_PREFIX}: params_json is not valid JSON"
        ) from None
    if not isinstance(raw, dict):
        raise InvalidPersistedParams(
            f"{_INVALID_PREFIX}: params_json is not a JSON object"
        )
    missing = [key for key in _EXECUTION_REQUIRED_KEYS if key not in raw]
    if missing:
        raise InvalidPersistedParams(
            f"{_INVALID_PREFIX}: missing fields: {', '.join(missing)}"
        )
    try:
        params = JobParams.model_validate(raw, strict=True)
    except ValidationError as exc:
        raise InvalidPersistedParams(
            f"{_INVALID_PREFIX}: invalid fields: {_validation_field_names(exc)}"
        ) from None
    problems = []
    if not params.model.strip():
        problems.append("model")
    if not math.isfinite(params.temperature):
        problems.append("temperature")
    if (
        not params.tasks
        or len(set(params.tasks)) != len(params.tasks)
        or any(not task.strip() for task in params.tasks)
    ):
        problems.append("tasks")
    if problems:
        raise InvalidPersistedParams(
            f"{_INVALID_PREFIX}: invalid fields: {', '.join(problems)}"
        )
    return params


def _snapshot_disagreements(params: JobParams, snapshot: dict[str, Any]) -> list[str]:
    """Fields where the persisted params contradict the creation snapshot."""
    backend = snapshot.get("backend")
    backend = backend if isinstance(backend, dict) else {}
    generation = snapshot.get("generation")
    generation = generation if isinstance(generation, dict) else {}
    snapshot_tasks = [
        item.get("task_id")
        for item in (snapshot.get("tasks") or [])
        if isinstance(item, dict)
    ]
    checks = {
        "model": snapshot.get("model") == params.model,
        "backend.kind": backend.get("kind") == params.backend.kind,
        "backend.base_url": backend.get("base_url") == effective_backend_url(params),
        "base_seed": generation.get("base_seed") == params.base_seed,
        "temperature": generation.get("temperature") == params.temperature,
        "request_timeout_s": generation.get("request_timeout_s")
        == params.request_timeout_s,
        "repeats": snapshot.get("repeats") == params.repeats,
        "tasks": snapshot_tasks == list(params.tasks),
    }
    return [name for name, agrees in checks.items() if not agrees]


def execution_params(conn: sqlite3.Connection, evaluation_id: str) -> JobParams:
    """The ONLY parameters an evaluation may be executed, resumed, retried or
    recovered with: strictly parsed and in agreement with the creation snapshot.

    Raises InvalidPersistedParams (a JobStateError) otherwise. Callers must not
    execute, create a fresh clone of, or requeue an evaluation on failure.
    """
    row = conn.execute(
        "SELECT params_json FROM evaluation_jobs WHERE id=?", (evaluation_id,)
    ).fetchone()
    if row is None:
        raise JobStateError(f"evaluation not found: {evaluation_id}")
    params = strict_params_from_json(row["params_json"])
    snapshot = get_snapshot(conn, evaluation_id)
    if snapshot is None:
        raise InvalidPersistedParams(
            f"{_INVALID_PREFIX}: evaluation has no creation snapshot"
        )
    disagreements = _snapshot_disagreements(params, snapshot)
    if disagreements:
        raise InvalidPersistedParams(
            f"{_INVALID_PREFIX}: parameters disagree with the creation snapshot "
            f"({', '.join(disagreements)})"
        )
    return params


def _job_params_for_display(raw_json: str) -> tuple[JobParams | None, str | None]:
    """Params for LISTING/inspection: exactly what execution would accept.

    Uses the SAME strict parse as ``execution_params`` (minus the snapshot
    agreement check), so a listing can never show clean-looking parameters for a
    row that execution refuses (no coercion of "2" to 2, no defaulted or empty
    ``tasks``, no silently dropped credential-bearing keys), and a non-finite
    number can never reach the JSON response. A row that fails returns
    ``(None, sanitised_reason)``: display data only, never a substitute.
    """
    try:
        return strict_params_from_json(raw_json), None
    except InvalidPersistedParams as exc:
        return None, str(exc).removeprefix(f"{_INVALID_PREFIX}: ")


def _loads_finite(text: str | None):
    """json.loads that refuses NaN/Infinity (they are not valid JSON and would
    make the response renderer raise, turning one corrupt row into a 500 for the
    whole listing). Returns None for anything unusable."""

    def _refuse(constant: str):
        raise ValueError(constant)

    if not text:
        return None
    try:
        return json.loads(text, parse_constant=_refuse)
    except (TypeError, ValueError):
        return None


def _job_from_row(row: sqlite3.Row) -> Job:
    params, params_problem = _job_params_for_display(row["params_json"])
    mode = _row_value(row, "mode", "legacy") or "legacy"
    raw_snapshot = _row_value(row, "snapshot_json")
    snapshot = _loads_finite(raw_snapshot)
    if not isinstance(snapshot, dict):
        snapshot = None
    backend_kind = evidence.snapshot_backend_kind(raw_snapshot) or (
        params.backend.kind if params is not None else None
    )
    evidence_class = {
        "mock": "synthetic",
        "ollama": "real",
        "openai_compat": "real",
    }.get(backend_kind, "unknown")
    return Job(
        id=row["id"],
        status=row["status"],
        mode=mode,
        source_evaluation_id=_row_value(row, "source_evaluation_id"),
        snapshot=snapshot,
        cancel_requested=bool(row["cancel_requested"]),
        backend_kind=backend_kind,
        evidence_class=evidence_class,
        params=params,
        params_status="available" if params is not None else "unverifiable",
        params_error=(
            None if params is not None else f"{_INVALID_PREFIX}: {params_problem}"
        ),
        counters=JobCounters(
            total_runs=row["total_runs"],
            completed_runs=row["completed_runs"],
            passed_runs=row["passed_runs"],
            voided_runs=row["voided_runs"],
            failed_runs=row["failed_runs"],
            reused_runs=_row_value(row, "reused_runs", 0),
        ),
        created_at=row["created_at"],
        started_at=row["started_at"],
        finished_at=row["finished_at"],
        error_message=row["error_message"],
    )


def _event_from_row(row: sqlite3.Row) -> JobEvent:
    payload = json.loads(row["payload_json"]) if row["payload_json"] else None
    return JobEvent(
        job_id=row["job_id"],
        seq=row["seq"],
        ts=row["ts"],
        type=row["type"],
        payload=payload,
    )


_BYTECODE_SUFFIXES = frozenset({".pyc", ".pyo"})


def _is_compiled_bytecode(rel: Path) -> bool:
    """Compiled bytecode is never task content: afa_runner.grader strips
    __pycache__ / *.pyc / *.pyo from everything it copies into the clean room.
    Hashing it made identical committed content produce different digests
    depending on which untracked caches a checkout happened to hold."""
    return "__pycache__" in rel.parts or rel.suffix in _BYTECODE_SUFFIXES


def _task_digest(task_dir: Path) -> str:
    """Hash the task pack the runner can read (everything except compiled
    bytecode) without text decoding."""
    digest = hashlib.sha256()
    for path in sorted(p for p in task_dir.rglob("*") if p.is_file()):
        if _is_compiled_bytecode(path.relative_to(task_dir)):
            continue
        rel = path.relative_to(task_dir).as_posix().encode("utf-8")
        digest.update(rel)
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return "sha256:" + digest.hexdigest()


def task_snapshot(task_id: str) -> dict[str, str]:
    """Resolve and snapshot a task before an evaluation is dispatchable."""
    task_dir = (db.ROOT / "tasks" / task_id).resolve()
    spec_path = task_dir / "task.json"
    if not spec_path.is_file():
        raise JobStateError(f"task is unavailable: {task_id}")
    try:
        spec = json.loads(spec_path.read_text())
        version = str(spec["version"])
        resolved_id = str(spec["id"])
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise JobStateError(f"task snapshot is invalid: {task_id}: {exc}") from exc
    if resolved_id != task_id:
        raise JobStateError(
            f"task directory/id mismatch: requested {task_id}, spec says {resolved_id}"
        )
    return {
        "task_id": task_id,
        "task_version": version,
        "task_digest": _task_digest(task_dir),
    }


def validate_snapshot_tasks(snapshot: dict[str, Any]) -> None:
    """Refuse resume when recorded task content/version is unavailable or drifted."""
    expected_tasks = snapshot.get("tasks")
    if not isinstance(expected_tasks, list):
        raise JobStateError("evaluation snapshot has an invalid task list")
    for expected in expected_tasks:
        task_id = expected.get("task_id") if isinstance(expected, dict) else None
        if not task_id:
            raise JobStateError("evaluation snapshot has an invalid task entry")
        actual = task_snapshot(str(task_id))
        if (
            actual.get("task_version") != expected.get("task_version")
            or actual.get("task_digest") != expected.get("task_digest")
        ):
            raise JobStateError(
                f"task {task_id} changed since evaluation creation; refusing snapshot drift"
            )


def effective_backend_url(params: JobParams) -> str | None:
    if params.backend.kind == "mock":
        return None
    return params.backend.base_url or DEFAULT_BACKEND_URLS[params.backend.kind]


def build_snapshot(params: JobParams) -> dict[str, Any]:
    if params.mode == "reuse" and not params.source_evaluation_id:
        raise JobStateError("reuse mode requires source_evaluation_id")
    if params.mode == "fresh" and params.source_evaluation_id:
        raise JobStateError("fresh mode cannot name source_evaluation_id")
    task_ids = list(params.tasks)
    if not task_ids:
        raise JobStateError("at least one task is required")
    if len(set(task_ids)) != len(task_ids):
        raise JobStateError("tasks must be unique within an evaluation")
    tasks = [task_snapshot(task_id) for task_id in task_ids]
    return {
        "schema_version": 1,
        "model": params.model,
        "backend": {
            "kind": params.backend.kind,
            "base_url": effective_backend_url(params),
        },
        "generation": {
            "base_seed": params.base_seed,
            "temperature": params.temperature,
            "request_timeout_s": params.request_timeout_s,
            "seed_provenance": "unavailable" if params.backend.kind == "mock" else "requested",
            "timeout_provenance": "not_applicable" if params.backend.kind == "mock" else "requested",
        },
        "tasks": tasks,
        "repeats": params.repeats,
    }


def get_snapshot(conn: sqlite3.Connection, evaluation_id: str) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT snapshot_json FROM evaluation_jobs WHERE id=?", (evaluation_id,)
    ).fetchone()
    if row is None or not row["snapshot_json"]:
        return None
    try:
        value = json.loads(row["snapshot_json"])
    except (TypeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _snapshot_identity(snapshot: dict[str, Any]) -> dict[str, Any]:
    return {
        "model": snapshot.get("model"),
        "backend": snapshot.get("backend"),
        "generation": snapshot.get("generation"),
        "tasks": snapshot.get("tasks"),
        "repeats": snapshot.get("repeats"),
    }



# --------------------------------------------------------------------------- #
# Create / list / get
# --------------------------------------------------------------------------- #


def create_job(conn: sqlite3.Connection, params: JobCreate) -> Job:
    """Create an immutable evaluation snapshot and all requested trial rows."""
    # Direct/library callers may open a copied historical DB without going
    # through the FastAPI lifespan; make this control-plane boundary additive
    # and fail closed before inserting a job.
    db.migrate(conn)
    snapshot = build_snapshot(params)
    job_id = uuid.uuid4().hex
    total = len(params.tasks) * params.repeats
    params_json = JobParams.model_validate(params.model_dump()).model_dump_json()

    try:
        source_origins: dict[tuple[str, int], str] = {}
        if params.mode == "reuse":
            source_id = params.source_evaluation_id
            source_snapshot = get_snapshot(conn, source_id or "")
            source_job = get_job(conn, source_id or "")
            if source_job is None or source_snapshot is None or source_job.mode == "legacy":
                raise JobStateError("reuse source evaluation is unavailable or legacy")
            if _snapshot_identity(source_snapshot) != _snapshot_identity(snapshot):
                raise JobStateError("reuse source snapshot is incompatible")
            source_tasks = source_snapshot.get("tasks")
            if not isinstance(source_tasks, list):
                raise JobStateError("reuse source snapshot is unverifiable")
            source_task_by_id: dict[str, dict[str, Any]] = {}
            for item in source_tasks:
                if not isinstance(item, dict):
                    raise JobStateError("reuse source snapshot is unverifiable")
                task_id = item.get("task_id")
                if not isinstance(task_id, str) or not item.get("task_version") or not item.get("task_digest"):
                    raise JobStateError("reuse source snapshot is unverifiable")
                source_task_by_id[task_id] = item
            source_rows = trial_rows(conn, source_id or "")
            expected = {(t["task_id"], int(t["idx"])) for t in source_rows}
            requested = {
                (task_id, idx)
                for task_id in params.tasks
                for idx in range(params.repeats)
            }
            if expected != requested or len(source_rows) != len(requested):
                raise JobStateError("reuse source has missing or incomplete trials")
            for source_row in source_rows:
                key = (source_row["task_id"], int(source_row["idx"]))
                expected_task = source_task_by_id.get(source_row["task_id"])
                if (
                    expected_task is None
                    or source_row["task_version"] != expected_task["task_version"]
                    or source_row["task_digest"] != expected_task["task_digest"]
                    or source_row["trial_state"] != "completed"
                    or source_row["evidence_state"] not in ("fresh", "reused")
                    or source_row["run_id"] is None
                ):
                    raise JobStateError("reuse source has missing or incomplete trials")
                raw = conn.execute(
                    "SELECT r.id, r.job_id, d.patch_text, "
                    "(SELECT COUNT(*) FROM test_results tr WHERE tr.run_id=r.id) AS test_count "
                    "FROM runs r "
                    "JOIN run_scores s ON s.run_id=r.id "
                    "JOIN diffs d ON d.run_id=r.id WHERE r.id=?",
                    (source_row["run_id"],),
                ).fetchone()
                if raw is None or raw["job_id"] is None:
                    raise JobStateError("reuse source has unknown or unverifiable evidence")
                if raw["patch_text"] is None or int(raw["test_count"]) == 0:
                    raise JobStateError("reuse source has missing or incomplete trials")
                origin = conn.execute(
                    "SELECT mode FROM evaluation_jobs WHERE id=?",
                    (raw["job_id"],),
                ).fetchone()
                if origin is None or origin["mode"] == "legacy":
                    raise JobStateError("reuse source has unknown or unverifiable origin")
                source_origins[key] = raw["job_id"]

        conn.execute(
            "INSERT INTO evaluation_jobs "
            "(id, status, cancel_requested, params_json, total_runs, "
            "completed_runs, passed_runs, voided_runs, failed_runs, reused_runs, "
            "mode, source_evaluation_id, snapshot_json, created_at) "
            "VALUES (?, 'queued', 0, ?, ?, ?, 0, 0, 0, ?, ?, ?, ?, datetime('now'))",
            (
                job_id,
                params_json,
                total,
                total if params.mode == "reuse" else 0,
                total if params.mode == "reuse" else 0,
                params.mode,
                params.source_evaluation_id,
                json.dumps(snapshot, sort_keys=True),
            ),
        )

        source_by_key: dict[tuple[str, int], sqlite3.Row] = {}
        if params.mode == "reuse":
            source_by_key = {
                (r["task_id"], int(r["idx"])): r
                for r in trial_rows(conn, params.source_evaluation_id or "")
            }
        task_by_id = {t["task_id"]: t for t in snapshot["tasks"]}
        for task_id in params.tasks:
            task = task_by_id[task_id]
            for idx in range(params.repeats):
                source = source_by_key.get((task_id, idx))
                reused = source is not None
                origin_id = None
                if reused:
                    origin_id = source_origins[(task_id, idx)]
                conn.execute(
                    "INSERT INTO evaluation_trials "
                    "(evaluation_id, task_id, idx, task_version, task_digest, "
                    "trial_state, evidence_state, run_id, source_evaluation_id, "
                    "source_run_id, origin_evaluation_id, completed_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, "
                    "CASE WHEN ? THEN datetime('now') ELSE NULL END)",
                    (
                        job_id,
                        task_id,
                        idx,
                        task["task_version"],
                        task["task_digest"],
                        "completed" if reused else "pending",
                        "reused" if reused else "missing",
                        source["run_id"] if reused else None,
                        params.source_evaluation_id if reused else None,
                        source["run_id"] if reused else None,
                        origin_id,
                        1 if reused else 0,
                    ),
                )
                if reused:
                    conn.execute(
                        "INSERT OR IGNORE INTO job_runs (job_id, run_id) VALUES (?, ?)",
                        (job_id, source["run_id"]),
                    )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return get_job(conn, job_id)  # type: ignore[return-value]


def list_jobs(conn: sqlite3.Connection, limit: int = 200) -> list[Job]:
    rows = conn.execute(
        "SELECT * FROM evaluation_jobs ORDER BY created_at DESC, id DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return [_job_from_row(r) for r in rows]


def get_job(conn: sqlite3.Connection, job_id: str) -> Job | None:
    row = conn.execute(
        "SELECT * FROM evaluation_jobs WHERE id = ?", (job_id,)
    ).fetchone()
    return _job_from_row(row) if row else None


# --------------------------------------------------------------------------- #
# Evaluation trials and canonical counters
# --------------------------------------------------------------------------- #


def trial_rows(conn: sqlite3.Connection, evaluation_id: str) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM evaluation_trials WHERE evaluation_id=? "
        "ORDER BY task_id, idx",
        (evaluation_id,),
    ).fetchall()


def claim_trial(
    conn: sqlite3.Connection,
    evaluation_id: str,
    task_id: str,
    idx: int,
    owner_token: str,
) -> str | None:
    claim_token = uuid.uuid4().hex
    cur = conn.execute(
        "UPDATE evaluation_trials SET trial_state='claimed', claim_token=?, "
        "claimed_at=datetime('now'), error_message=NULL "
        "WHERE evaluation_id=? AND task_id=? AND idx=? "
        "AND trial_state='pending' AND EXISTS ("
        "SELECT 1 FROM evaluation_jobs WHERE id=? AND status='running' "
        "AND owner_token=?)",
        (claim_token, evaluation_id, task_id, idx, evaluation_id, owner_token),
    )
    conn.commit()
    return claim_token if cur.rowcount == 1 else None


def complete_trial(
    conn: sqlite3.Connection,
    evaluation_id: str,
    task_id: str,
    idx: int,
    claim_token: str,
    run_id: int,
    *,
    owner_token: str,
    evidence_state: str = "fresh",
    source_evaluation_id: str | None = None,
    source_run_id: int | None = None,
    origin_evaluation_id: str | None = None,
) -> None:
    cur = conn.execute(
        "UPDATE evaluation_trials SET trial_state='completed', "
        "evidence_state=?, run_id=?, source_evaluation_id=?, source_run_id=?, "
        "origin_evaluation_id=?, completed_at=datetime('now'), claim_token=NULL "
        "WHERE evaluation_id=? AND task_id=? AND idx=? "
        "AND trial_state='claimed' AND claim_token=? AND EXISTS ("
        "SELECT 1 FROM evaluation_jobs WHERE id=? AND status='running' "
        "AND owner_token=?)",
        (
            evidence_state,
            run_id,
            source_evaluation_id,
            source_run_id,
            origin_evaluation_id,
            evaluation_id,
            task_id,
            idx,
            claim_token,
            evaluation_id,
            owner_token,
        ),
    )
    if cur.rowcount != 1:
        raise TrialClaimError(
            f"lost trial claim for {evaluation_id}/{task_id}/{idx}"
        )
    conn.execute(
        "INSERT OR IGNORE INTO job_runs (job_id, run_id) VALUES (?, ?)",
        (evaluation_id, run_id),
    )


def mark_trial_unverifiable(
    conn: sqlite3.Connection,
    evaluation_id: str,
    task_id: str,
    *,
    error_message: str,
    owner_token: str | None = None,
) -> bool:
    if owner_token is None:
        raise JobStateError("owner token is required to block evaluation trials")
    cur = conn.execute(
        "UPDATE evaluation_trials SET trial_state='blocked', "
        "evidence_state='unverifiable', error_message=? "
        "WHERE evaluation_id=? AND task_id=? AND trial_state != 'completed' "
        "AND EXISTS (SELECT 1 FROM evaluation_jobs WHERE id=? "
        "AND status='running' AND owner_token=?)",
        (error_message, evaluation_id, task_id, evaluation_id, owner_token),
    )
    conn.commit()
    return cur.rowcount > 0


def refresh_counters(
    conn: sqlite3.Connection, evaluation_id: str, *, commit: bool = True
) -> None:
    """Derive monitor counters from committed trial/raw associations."""
    row = conn.execute(
        "SELECT COUNT(*) AS completed, "
        "COALESCE(SUM(CASE WHEN t.evidence_state='reused' THEN 1 ELSE 0 END),0) AS reused, "
        "COALESCE(SUM(CASE WHEN t.evidence_state='fresh' AND s.functional_pass=1 THEN 1 ELSE 0 END),0) AS passed, "
        "COALESCE(SUM(CASE WHEN t.evidence_state='fresh' AND s.voided=1 THEN 1 ELSE 0 END),0) AS voided, "
        "COALESCE(SUM(CASE WHEN t.evidence_state='fresh' AND s.functional_pass=0 AND s.voided=0 THEN 1 ELSE 0 END),0) AS failed "
        "FROM evaluation_trials t LEFT JOIN run_scores s ON s.run_id=t.run_id "
        "WHERE t.evaluation_id=? AND t.trial_state='completed'",
        (evaluation_id,),
    ).fetchone()
    conn.execute(
        "UPDATE evaluation_jobs SET completed_runs=?, passed_runs=?, "
        "voided_runs=?, failed_runs=?, reused_runs=? WHERE id=?",
        (
            int(row["completed"]),
            int(row["passed"]),
            int(row["voided"]),
            int(row["failed"]),
            int(row["reused"]),
            evaluation_id,
        ),
    )
    if commit:
        conn.commit()


def all_trials_completed(conn: sqlite3.Connection, evaluation_id: str) -> bool:
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM evaluation_trials "
        "WHERE evaluation_id=? AND trial_state != 'completed'",
        (evaluation_id,),
    ).fetchone()
    return bool(row and row["n"] == 0)


def _run_provenance(
    conn: sqlite3.Connection, evaluation_id: str, run_kind: str | None
) -> tuple[str, str | None]:
    """Compare a raw run's own backend with its evaluation snapshot's backend.

    Returns (state, snapshot_kind): "consistent", "mismatch" or "unknown" (the run
    predates provenance, or the snapshot recorded no usable backend). A mismatch
    is surfaced, never silently resolved.
    """
    snap = conn.execute(
        "SELECT snapshot_json FROM evaluation_jobs WHERE id=?", (evaluation_id,)
    ).fetchone()
    snapshot_kind = evidence.snapshot_backend_kind(snap["snapshot_json"] if snap else None)
    if run_kind is None or snapshot_kind is None:
        return "unknown", snapshot_kind
    return ("consistent" if run_kind == snapshot_kind else "mismatch"), snapshot_kind


def trial_detail(
    conn: sqlite3.Connection, evaluation_id: str, task_id: str, idx: int
) -> dict[str, Any] | None:
    has_backend_kind = any(
        col[1] == "backend_kind" for col in conn.execute("PRAGMA table_info(runs)")
    )
    backend_column = "r.backend_kind AS backend_kind, " if has_backend_kind else "NULL AS backend_kind, "
    row = conn.execute(
        "SELECT t.*, r.agent, r.status, r.task_version AS run_task_version, "
        + backend_column +
        "r.transcript_hash, r.duration_ms, r.created_at, s.final_score, "
        "s.functional_pass, s.voided, d.patch_text "
        "FROM evaluation_trials t LEFT JOIN runs r ON r.id=t.run_id "
        "LEFT JOIN run_scores s ON s.run_id=t.run_id "
        "LEFT JOIN diffs d ON d.run_id=t.run_id "
        "WHERE t.evaluation_id=? AND t.task_id=? AND t.idx=?",
        (evaluation_id, task_id, idx),
    ).fetchone()
    if row is None:
        return None
    result = {
        "evaluation_id": evaluation_id,
        "task_id": row["task_id"],
        "idx": row["idx"],
        "task_version": row["task_version"],
        "trial_state": row["trial_state"],
        "evidence_state": row["evidence_state"],
        "run_id": row["run_id"],
        "source_evaluation_id": row["source_evaluation_id"],
        "source_run_id": row["source_run_id"],
        "origin_evaluation_id": row["origin_evaluation_id"],
        "error_message": row["error_message"],
        "backend_kind": None,
        "provenance": "unknown",
    }
    run_id = row["run_id"]
    if run_id is None:
        result["outcome"] = None
        result["artifact_state"] = "absent"
        return result
    provenance_state, snapshot_kind = _run_provenance(
        conn, evaluation_id, row["backend_kind"]
    )
    result["backend_kind"] = row["backend_kind"]
    result["provenance"] = provenance_state
    if provenance_state == "mismatch":
        result["integrity_error"] = (
            f"run backend {row['backend_kind']!r} disagrees with the evaluation "
            f"snapshot backend {snapshot_kind!r}"
        )

    # A trial link alone is not enough to call the outcome or artifacts
    # available: a failed/legacy partial write may leave no raw or score row.
    outcome_available = (
        row["status"] is not None
        and row["final_score"] is not None
        and row["functional_pass"] is not None
        and row["voided"] is not None
    )
    if not outcome_available:
        result["outcome"] = None
        result["artifact_state"] = "unavailable"
        return result

    result["outcome"] = {
        "status": row["status"],
        "functional_pass": bool(row["functional_pass"]),
        "voided": bool(row["voided"]),
        "final_score": float(row["final_score"]),
    }
    test_count = conn.execute(
        "SELECT COUNT(*) AS n FROM test_results WHERE run_id=?", (run_id,)
    ).fetchone()["n"]
    artifacts_complete = row["patch_text"] is not None and int(test_count) > 0
    result["artifact_state"] = "complete" if artifacts_complete else "partial"

    # Comparability is deliberately omitted when persisted evidence is
    # incomplete; outcome and provenance remain useful without inventing a
    # statistical claim from missing patch/test artifacts.
    # A run whose own backend contradicts its evaluation snapshot is an integrity
    # error: it is never presented as comparable evidence.
    if artifacts_complete and provenance_state != "mismatch":
        if row["evidence_state"] == "reused":
            result["comparability"] = "provisional"
        elif row["evidence_state"] == "fresh":
            result["comparability"] = "comparable"
    return result


def evaluation_results(conn: sqlite3.Connection, evaluation_id: str) -> dict[str, Any] | None:
    job = get_job(conn, evaluation_id)
    if job is None:
        return None
    return {
        "evaluation_id": evaluation_id,
        "status": job.status,
        "mode": job.mode,
        "snapshot": job.snapshot,
        "counters": job.counters.model_dump(),
        "trials": [
            trial_detail(conn, evaluation_id, row["task_id"], int(row["idx"]))
            for row in trial_rows(conn, evaluation_id)
        ],
    }


# --------------------------------------------------------------------------- #
# Job state machine and ownership
# --------------------------------------------------------------------------- #


def claim_job_token(
    conn: sqlite3.Connection, job_id: str, owner_token: str | None = None
) -> str | None:
    """Claim a queued evaluation and return the exact fencing token."""
    token = owner_token or uuid.uuid4().hex
    cur = conn.execute(
        "UPDATE evaluation_jobs SET status='running', started_at=COALESCE(started_at, datetime('now')), "
        "owner_token=?, owner_started_at=datetime('now') "
        "WHERE id=? AND status='queued' AND owner_token IS NULL",
        (token, job_id),
    )
    conn.commit()
    return token if cur.rowcount == 1 else None


def claim_job(
    conn: sqlite3.Connection, job_id: str, owner_token: str | None = None
) -> bool:
    """Compatibility boolean wrapper around the token-preserving claim."""
    return claim_job_token(conn, job_id, owner_token) is not None


def owner_token(conn: sqlite3.Connection, job_id: str) -> str | None:
    row = conn.execute(
        "SELECT owner_token FROM evaluation_jobs WHERE id=?", (job_id,)
    ).fetchone()
    return row["owner_token"] if row else None


def touch_owner(conn: sqlite3.Connection, job_id: str, token: str) -> bool:
    """Renew the diagnostic lease between model calls, with fencing."""
    cur = conn.execute(
        "UPDATE evaluation_jobs SET owner_started_at=datetime('now') "
        "WHERE id=? AND status='running' AND owner_token=?",
        (job_id, token),
    )
    conn.commit()
    return cur.rowcount == 1


def claim_next_queued_token(conn: sqlite3.Connection) -> tuple[str, str] | None:
    row = conn.execute(
        "SELECT id FROM evaluation_jobs WHERE status='queued' "
        "ORDER BY created_at ASC, id ASC LIMIT 1"
    ).fetchone()
    if row is None:
        return None
    job_id = row["id"]
    token = claim_job_token(conn, job_id)
    return (job_id, token) if token is not None else None


def claim_next_queued(conn: sqlite3.Connection) -> str | None:
    claim = claim_next_queued_token(conn)
    return claim[0] if claim else None


def _fail_unverifiable_running_job(
    conn: sqlite3.Connection,
    row: sqlite3.Row,
    reason: str,
    caller_owned_transaction: bool,
) -> bool:
    """Terminalise an unowned running evaluation whose parameters are unverifiable.

    Its non-completed trials become blocked/unverifiable; no evidence is created
    and nothing is queued. Guarded exactly like the requeue transition so a
    live owner that finishes concurrently is never overwritten.
    """
    savepoint = f"afa_unverifiable_{uuid.uuid4().hex}"
    conn.execute(f"SAVEPOINT {savepoint}")
    try:
        cur = conn.execute(
            "UPDATE evaluation_jobs SET status='failed', error_message=?, "
            "finished_at=datetime('now'), owner_token=NULL, owner_started_at=NULL "
            "WHERE id=? AND status='running' AND owner_token IS ? "
            "AND owner_started_at IS ?",
            (reason, row["id"], row["owner_token"], row["owner_started_at"]),
        )
        if cur.rowcount != 1:
            conn.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
            conn.execute(f"RELEASE SAVEPOINT {savepoint}")
            if not caller_owned_transaction and conn.in_transaction:
                conn.rollback()
            return False
        conn.execute(
            "UPDATE evaluation_trials SET trial_state='blocked', "
            "evidence_state='unverifiable', error_message=?, claim_token=NULL, "
            "claimed_at=NULL WHERE evaluation_id=? "
            "AND trial_state IN ('pending', 'claimed')",
            (reason, row["id"]),
        )
        conn.execute(f"RELEASE SAVEPOINT {savepoint}")
    except Exception:
        conn.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
        conn.execute(f"RELEASE SAVEPOINT {savepoint}")
        if not caller_owned_transaction and conn.in_transaction:
            conn.rollback()
        raise
    if not caller_owned_transaction:
        conn.commit()
    return True


def reclaim_stale_running(
    conn: sqlite3.Connection, *, stale_after_s: int = 300,
    recover_unlocked: bool = False,
) -> list[str]:
    """Recover only evaluations whose same-host owner lock is free.

    Lease age is a diagnostic fallback for old owners; current owners hold the
    OS lock for model/grading work, so a live owner is never reclaimed merely
    because a request took longer than the lease.
    """
    caller_owned_transaction = conn.in_transaction
    rows = conn.execute(
        "SELECT id, owner_token, owner_started_at, params_json FROM evaluation_jobs "
        "WHERE status='running'"
    ).fetchall()
    ids: list[str] = []
    unverifiable: list[tuple[str, str]] = []
    base_threshold = max(0, int(stale_after_s))
    for row in rows:
        lock = try_acquire_owner_lock(conn, row["id"])
        if lock is None:
            continue
        try:
            stale = row["owner_started_at"] is None
            if not stale:
                request_timeout = 0
                try:
                    request_timeout = int(
                        json.loads(row["params_json"]).get("request_timeout_s", 0)
                    )
                except (TypeError, ValueError, json.JSONDecodeError, AttributeError):
                    pass
                threshold = max(base_threshold, request_timeout + 60)
                stale = conn.execute(
                    "SELECT 1 FROM evaluation_jobs WHERE id=? AND owner_started_at < "
                    "datetime('now', ?)",
                    (row["id"], f"-{threshold} seconds"),
                ).fetchone() is not None
            if not stale and not recover_unlocked:
                continue

            # Fail closed: an evaluation whose persisted parameters or creation
            # snapshot cannot be trusted must never be requeued (and therefore
            # never auto-dispatched) with defaults. It becomes an explicit
            # failed / unverifiable evaluation instead.
            try:
                execution_params(conn, row["id"])
            except InvalidPersistedParams as exc:
                if _fail_unverifiable_running_job(
                    conn, row, str(exc), caller_owned_transaction
                ):
                    unverifiable.append((row["id"], str(exc)))
                continue

            # The owner may finish between the stale observation and this
            # conditional update. Keep this small state transition inside a
            # savepoint and clean up a no-op DML transaction; never commit a
            # caller transaction that happened to be open on this connection.
            savepoint = f"afa_reclaim_{uuid.uuid4().hex}"
            conn.execute(f"SAVEPOINT {savepoint}")
            try:
                cur = conn.execute(
                    "UPDATE evaluation_jobs SET status='queued', owner_token=NULL, "
                    "owner_started_at=NULL, started_at=NULL "
                    "WHERE id=? AND status='running' AND owner_token IS ? "
                    "AND owner_started_at IS ?",
                    (row["id"], row["owner_token"], row["owner_started_at"]),
                )
                if cur.rowcount != 1:
                    conn.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
                    conn.execute(f"RELEASE SAVEPOINT {savepoint}")
                    if not caller_owned_transaction and conn.in_transaction:
                        conn.rollback()
                    continue
                conn.execute(
                    "UPDATE evaluation_trials SET trial_state='pending', claim_token=NULL, "
                    "claimed_at=NULL WHERE evaluation_id=? AND trial_state='claimed'",
                    (row["id"],),
                )
                conn.execute(f"RELEASE SAVEPOINT {savepoint}")
            except Exception:
                conn.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
                conn.execute(f"RELEASE SAVEPOINT {savepoint}")
                if not caller_owned_transaction and conn.in_transaction:
                    conn.rollback()
                raise
            if not caller_owned_transaction:
                conn.commit()
            ids.append(row["id"])
        finally:
            lock.release()
    for jid, reason in unverifiable:
        refresh_counters(conn, jid, commit=not caller_owned_transaction)
        append_event(
            conn, jid, "job_failed",
            {"reason": reason, "recovery": "not resumed: parameters are unverifiable"},
            commit=not caller_owned_transaction,
        )
    for jid in ids:
        refresh_counters(conn, jid, commit=not caller_owned_transaction)
        append_event(
            conn, jid, "job_reclaimed",
            {"reason": "owner lock was released; resuming remaining trials"},
            commit=not caller_owned_transaction,
        )
    return ids


def resume_job(conn: sqlite3.Connection, job_id: str) -> Job | None:
    """Explicitly resume an incomplete evaluation without changing its ID."""
    job = get_job(conn, job_id)
    if job is None:
        return None
    snapshot = get_snapshot(conn, job_id)
    if job.mode == "legacy" or snapshot is None:
        raise JobStateError("evaluation has no verifiable creation snapshot")
    # Fail closed on corrupt persisted parameters before touching any state.
    execution_params(conn, job_id)
    validate_snapshot_tasks(snapshot)
    if job.status == "succeeded":
        raise JobStateError("succeeded evaluations are not resumable")
    if job.status == "running":
        reclaimed = reclaim_stale_running(conn, stale_after_s=300)
        if job_id not in reclaimed:
            raise JobStateError("evaluation is owned by a live worker")
    cur = conn.execute(
        "UPDATE evaluation_jobs SET status='queued', cancel_requested=0, "
        "finished_at=NULL, error_message=NULL, owner_token=NULL, "
        "owner_started_at=NULL WHERE id=? AND status IN ('failed','canceled','queued') "
        "AND owner_token IS NULL",
        (job_id,),
    )
    if cur.rowcount != 1:
        raise JobStateError("evaluation changed before resume could be claimed")
    # An earlier task-pack verification failure blocks every uncompleted
    # position for that task. Once the exact snapshot validates again, explicit
    # resume makes those positions executable without touching completed trials.
    conn.execute(
        "UPDATE evaluation_trials SET trial_state='pending', evidence_state='missing', "
        "claim_token=NULL, claimed_at=NULL, error_message=NULL "
        "WHERE evaluation_id=? AND trial_state='blocked' "
        "AND evidence_state='unverifiable'",
        (job_id,),
    )
    conn.commit()
    append_event(conn, job_id, "job_resumed", {"evaluation_id": job_id})
    refresh_counters(conn, job_id)
    return get_job(conn, job_id)


def request_cancel(conn: sqlite3.Connection, job_id: str) -> Job | None:
    """Atomically cancel queued work or flag the current running owner."""
    caller_owned_transaction = conn.in_transaction
    cur = conn.execute(
        "UPDATE evaluation_jobs SET cancel_requested=1, "
        "status=CASE WHEN status='queued' THEN 'canceled' ELSE status END, "
        "finished_at=CASE WHEN status='queued' THEN datetime('now') ELSE finished_at END "
        "WHERE id=? AND status IN ('queued', 'running')",
        (job_id,),
    )
    if cur.rowcount:
        if not caller_owned_transaction:
            conn.commit()
    elif not caller_owned_transaction and conn.in_transaction:
        # SQLite versions may open an implicit transaction even for a zero-row
        # UPDATE; discard only work created by this call.
        conn.rollback()
    return get_job(conn, job_id)


def is_cancel_requested(conn: sqlite3.Connection, job_id: str) -> bool:
    row = conn.execute(
        "SELECT cancel_requested FROM evaluation_jobs WHERE id=?", (job_id,)
    ).fetchone()
    return bool(row and row["cancel_requested"])


def mark_terminal(
    conn: sqlite3.Connection,
    job_id: str,
    status: str,
    *,
    error_message: str | None = None,
    owner_token: str | None = None,
) -> Job | None:
    if status not in TERMINAL_STATES:
        raise ValueError(f"not a terminal status: {status}")
    if owner_token is None:
        row = conn.execute(
            "SELECT status FROM evaluation_jobs WHERE id=?", (job_id,)
        ).fetchone()
        if row is not None and row["status"] == "running":
            raise JobStateError("owner token is required to finish a running evaluation")
        conn.execute(
            "UPDATE evaluation_jobs SET status=?, finished_at=datetime('now'), "
            "error_message=?, owner_token=NULL, owner_started_at=NULL "
            "WHERE id=? AND status != 'running'",
            (status, error_message, job_id),
        )
    else:
        # Fencing: a worker replaced after recovery cannot finish or fail the
        # successor's evaluation, even if it retained a stale pre-read.
        conn.execute(
            "UPDATE evaluation_jobs SET status=?, finished_at=datetime('now'), "
            "error_message=?, owner_token=NULL, owner_started_at=NULL "
            "WHERE id=? AND owner_token=? AND status='running'",
            (status, error_message, job_id, owner_token),
        )
    conn.commit()
    return get_job(conn, job_id)


def bump_counters(
    conn: sqlite3.Connection,
    job_id: str,
    *,
    completed: int = 0,
    passed: int = 0,
    voided: int = 0,
    failed: int = 0,
    reused: int = 0,
) -> None:
    """Compatibility helper for old callers; new worker derives counters."""
    conn.execute(
        "UPDATE evaluation_jobs SET completed_runs=completed_runs+?, "
        "passed_runs=passed_runs+?, voided_runs=voided_runs+?, "
        "failed_runs=failed_runs+?, reused_runs=reused_runs+? WHERE id=?",
        (completed, passed, voided, failed, reused, job_id),
    )
    conn.commit()


def retry_job(conn: sqlite3.Connection, job_id: str) -> Job | None:
    """Create a new independent FRESH evaluation from a terminal job."""
    job = get_job(conn, job_id)
    if job is None or job.status not in TERMINAL_STATES or job.mode == "legacy":
        return None
    # Never clone defaults: a malformed row raises InvalidPersistedParams (409).
    params = execution_params(conn, job_id).model_copy(
        update={"mode": "fresh", "source_evaluation_id": None}
    )
    return create_job(conn, JobCreate.model_validate(params.model_dump()))


# --------------------------------------------------------------------------- #
# Events (monotonic per-job seq)
# --------------------------------------------------------------------------- #


def append_event(
    conn: sqlite3.Connection,
    job_id: str,
    type: str,
    payload: dict[str, Any] | None = None,
    *,
    commit: bool = True,
) -> int:
    row = conn.execute(
        "SELECT COALESCE(MAX(seq), 0) AS m FROM job_events WHERE job_id=?", (job_id,)
    ).fetchone()
    seq = int(row["m"]) + 1
    conn.execute(
        "INSERT INTO job_events (job_id, seq, ts, type, payload_json) "
        "VALUES (?, ?, datetime('now'), ?, ?)",
        (job_id, seq, type, json.dumps(payload) if payload is not None else None),
    )
    if commit:
        conn.commit()
    return seq


def events_since(
    conn: sqlite3.Connection, job_id: str, since: int = 0, limit: int = 1000
) -> list[JobEvent]:
    rows = conn.execute(
        "SELECT * FROM job_events WHERE job_id=? AND seq>? "
        "ORDER BY seq ASC LIMIT ?",
        (job_id, since, limit),
    ).fetchall()
    return [_event_from_row(r) for r in rows]


def max_event_seq(conn: sqlite3.Connection, job_id: str) -> int:
    row = conn.execute(
        "SELECT COALESCE(MAX(seq), 0) AS m FROM job_events WHERE job_id=?", (job_id,)
    ).fetchone()
    return int(row["m"])


# --------------------------------------------------------------------------- #
# Compatibility raw links and settings
# --------------------------------------------------------------------------- #


def link_run(conn: sqlite3.Connection, job_id: str, run_id: int) -> None:
    """Compatibility association; never overwrite an existing raw origin."""
    conn.execute(
        "INSERT OR IGNORE INTO job_runs (job_id, run_id) VALUES (?, ?)",
        (job_id, run_id),
    )
    conn.execute(
        "UPDATE runs SET job_id=? WHERE id=? AND job_id IS NULL", (job_id, run_id)
    )
    conn.commit()


def run_ids_for_job(conn: sqlite3.Connection, job_id: str) -> list[int]:
    rows = conn.execute(
        "SELECT run_id FROM job_runs WHERE job_id=? ORDER BY run_id", (job_id,)
    ).fetchall()
    return [r["run_id"] for r in rows]


def get_settings_raw(conn: sqlite3.Connection) -> dict[str, Any]:
    row = conn.execute("SELECT settings_json FROM app_settings WHERE id=1").fetchone()
    if row is None:
        return {}
    try:
        return json.loads(row["settings_json"]) or {}
    except (json.JSONDecodeError, TypeError):
        return {}


def put_settings(conn: sqlite3.Connection, data: dict[str, Any]) -> dict[str, Any]:
    conn.execute(
        "INSERT INTO app_settings (id, settings_json, updated_at) VALUES (1, ?, datetime('now')) "
        "ON CONFLICT(id) DO UPDATE SET settings_json=excluded.settings_json, "
        "updated_at=excluded.updated_at",
        (json.dumps(data),),
    )
    conn.commit()
    return data
