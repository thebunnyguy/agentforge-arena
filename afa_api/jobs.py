"""Job control-plane data access: jobs, events, settings.

This module owns the app tables created by ``db.migrate`` (``evaluation_jobs``,
``job_events``, ``app_settings``, ``job_runs``). It never touches the frozen raw
benchmark layer except to APPEND a ``job_runs`` link row (the raw ``runs`` table
stays append-only; we additionally stamp the nullable ``runs.job_id`` column the
hard-constraint asks for, which is set once at insert-association time and never
mutates scoring).

State machine (worker drives the transitions):

    queued --claim--> running --+--> succeeded
                                +--> failed
                                +--> canceled   (cancel_requested honored)

``claim_job`` uses a conditional UPDATE so exactly one worker can move a job out
of ``queued``. Events carry a monotonic per-job ``seq`` (the SSE id); we compute
the next seq inside the same connection so a single-writer worker is race-free.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from typing import Any

from . import db
from .schemas import (
    TERMINAL_STATES,
    Job,
    JobCounters,
    JobCreate,
    JobEvent,
    JobParams,
)

# --------------------------------------------------------------------------- #
# Row -> model projection
# --------------------------------------------------------------------------- #

def _job_from_row(row: sqlite3.Row) -> Job:
    params = JobParams.model_validate(json.loads(row["params_json"]))
    return Job(
        id=row["id"],
        status=row["status"],
        cancel_requested=bool(row["cancel_requested"]),
        params=params,
        counters=JobCounters(
            total_runs=row["total_runs"],
            completed_runs=row["completed_runs"],
            passed_runs=row["passed_runs"],
            voided_runs=row["voided_runs"],
            failed_runs=row["failed_runs"],
            reused_runs=(row["reused_runs"] if "reused_runs" in row.keys() else 0),
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


# --------------------------------------------------------------------------- #
# Create / list / get
# --------------------------------------------------------------------------- #

def create_job(conn: sqlite3.Connection, params: JobCreate) -> Job:
    """Insert a QUEUED job. Does NOT run the worker or create run rows.

    ``total_runs`` is precomputed as len(tasks) * repeats so the monitor can show
    a denominator immediately.
    """
    job_id = uuid.uuid4().hex
    total = len(params.tasks) * params.repeats
    params_json = JobParams.model_validate(params.model_dump()).model_dump_json()
    conn.execute(
        "INSERT INTO evaluation_jobs "
        "(id, status, cancel_requested, params_json, total_runs, "
        " completed_runs, passed_runs, voided_runs, failed_runs, created_at) "
        "VALUES (?, 'queued', 0, ?, ?, 0, 0, 0, 0, datetime('now'))",
        (job_id, params_json, total),
    )
    conn.commit()
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
# State machine
# --------------------------------------------------------------------------- #

def claim_job(conn: sqlite3.Connection, job_id: str) -> bool:
    """Atomically move a job from queued -> running. Returns True iff this
    caller won the claim (affected rows == 1)."""
    cur = conn.execute(
        "UPDATE evaluation_jobs "
        "SET status='running', started_at=datetime('now') "
        "WHERE id=? AND status='queued'",
        (job_id,),
    )
    conn.commit()
    return cur.rowcount == 1


def claim_next_queued(conn: sqlite3.Connection) -> str | None:
    """Find the oldest queued job and try to claim it. Returns the job id on a
    successful claim, else None."""
    row = conn.execute(
        "SELECT id FROM evaluation_jobs WHERE status='queued' "
        "ORDER BY created_at ASC, id ASC LIMIT 1"
    ).fetchone()
    if row is None:
        return None
    job_id = row["id"]
    return job_id if claim_job(conn, job_id) else None


def reclaim_stale_running(conn: sqlite3.Connection) -> list[str]:
    """Requeue jobs stranded in 'running' by a worker that died mid-job.

    When a worker process is killed mid-run, its job is left in ``running`` with
    no worker to finish it. On the next worker startup we move such jobs back to
    ``queued`` so they get re-claimed and resumed (the worker skips
    already-persisted units and only executes the missing ones). Per-run counters
    are reset to 0 so the resume re-tallies cleanly. Returns the reclaimed ids.
    """
    ids = [
        r["id"]
        for r in conn.execute(
            "SELECT id FROM evaluation_jobs WHERE status='running'"
        ).fetchall()
    ]
    for jid in ids:
        conn.execute(
            "UPDATE evaluation_jobs SET status='queued', completed_runs=0, "
            "passed_runs=0, voided_runs=0, failed_runs=0, reused_runs=0, "
            "started_at=NULL WHERE id=? AND status='running'",
            (jid,),
        )
    conn.commit()
    for jid in ids:
        append_event(
            conn, jid, "job_reclaimed",
            {"reason": "worker restarted; resuming remaining runs"},
        )
    return ids


def request_cancel(conn: sqlite3.Connection, job_id: str) -> Job | None:
    """Set the cancel-requested flag. If the job is still queued it is moved
    straight to ``canceled`` (no worker will pick it up). If running, the flag is
    honored by the worker between runs."""
    job = get_job(conn, job_id)
    if job is None:
        return None
    if job.status == "queued":
        conn.execute(
            "UPDATE evaluation_jobs "
            "SET cancel_requested=1, status='canceled', "
            "finished_at=datetime('now') WHERE id=? AND status='queued'",
            (job_id,),
        )
        conn.commit()
    elif job.status == "running":
        conn.execute(
            "UPDATE evaluation_jobs SET cancel_requested=1 WHERE id=?",
            (job_id,),
        )
        conn.commit()
    # terminal -> no-op
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
) -> Job | None:
    """Move a job to a terminal state (succeeded/failed/canceled)."""
    if status not in TERMINAL_STATES:
        raise ValueError(f"not a terminal status: {status}")
    conn.execute(
        "UPDATE evaluation_jobs "
        "SET status=?, finished_at=datetime('now'), error_message=? "
        "WHERE id=?",
        (status, error_message, job_id),
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
    """Increment the per-job run counters (called once per completed unit)."""
    conn.execute(
        "UPDATE evaluation_jobs SET "
        "completed_runs = completed_runs + ?, "
        "passed_runs = passed_runs + ?, "
        "voided_runs = voided_runs + ?, "
        "failed_runs = failed_runs + ?, "
        "reused_runs = reused_runs + ? "
        "WHERE id=?",
        (completed, passed, voided, failed, reused, job_id),
    )
    conn.commit()


def retry_job(conn: sqlite3.Connection, job_id: str) -> Job | None:
    """Create a NEW queued job cloning a terminal job's params. The original is
    left untouched (append-only history). Returns the new job, or None if the
    source job does not exist or is not terminal."""
    job = get_job(conn, job_id)
    if job is None or job.status not in TERMINAL_STATES:
        return None
    return create_job(conn, JobCreate.model_validate(job.params.model_dump()))


# --------------------------------------------------------------------------- #
# Events (monotonic per-job seq)
# --------------------------------------------------------------------------- #

def append_event(
    conn: sqlite3.Connection,
    job_id: str,
    type: str,
    payload: dict[str, Any] | None = None,
) -> int:
    """Append a job event with the next monotonic ``seq`` for this job.

    Returns the seq. The next-seq read + insert happen on the same connection;
    the worker is the single writer, and the UNIQUE(job_id, seq) constraint is a
    backstop against accidental duplication.
    """
    row = conn.execute(
        "SELECT COALESCE(MAX(seq), 0) AS m FROM job_events WHERE job_id=?",
        (job_id,),
    ).fetchone()
    seq = int(row["m"]) + 1
    conn.execute(
        "INSERT INTO job_events (job_id, seq, ts, type, payload_json) "
        "VALUES (?, ?, datetime('now'), ?, ?)",
        (job_id, seq, type, json.dumps(payload) if payload is not None else None),
    )
    conn.commit()
    return seq


def events_since(
    conn: sqlite3.Connection, job_id: str, since: int = 0, limit: int = 1000
) -> list[JobEvent]:
    """Return events with seq > ``since`` in ascending order (cursor read)."""
    rows = conn.execute(
        "SELECT * FROM job_events WHERE job_id=? AND seq > ? "
        "ORDER BY seq ASC LIMIT ?",
        (job_id, since, limit),
    ).fetchall()
    return [_event_from_row(r) for r in rows]


def max_event_seq(conn: sqlite3.Connection, job_id: str) -> int:
    row = conn.execute(
        "SELECT COALESCE(MAX(seq), 0) AS m FROM job_events WHERE job_id=?",
        (job_id,),
    ).fetchone()
    return int(row["m"])


# --------------------------------------------------------------------------- #
# job_runs links (+ stamp nullable runs.job_id)
# --------------------------------------------------------------------------- #

def link_run(conn: sqlite3.Connection, job_id: str, run_id: int) -> None:
    """Append a (job_id, run_id) link and stamp runs.job_id for the new row.

    The raw run row is INSERTed by the frozen store; we only set its previously
    NULL job_id (a product association, not a scoring change) and record the
    append-only join row.
    """
    conn.execute(
        "INSERT OR IGNORE INTO job_runs (job_id, run_id) VALUES (?, ?)",
        (job_id, run_id),
    )
    conn.execute("UPDATE runs SET job_id=? WHERE id=?", (job_id, run_id))
    conn.commit()


def run_ids_for_job(conn: sqlite3.Connection, job_id: str) -> list[int]:
    rows = conn.execute(
        "SELECT run_id FROM job_runs WHERE job_id=? ORDER BY run_id", (job_id,)
    ).fetchall()
    return [r["run_id"] for r in rows]


# --------------------------------------------------------------------------- #
# Settings
# --------------------------------------------------------------------------- #

def get_settings_raw(conn: sqlite3.Connection) -> dict[str, Any]:
    row = conn.execute(
        "SELECT settings_json FROM app_settings WHERE id=1"
    ).fetchone()
    if row is None:
        return {}
    try:
        return json.loads(row["settings_json"]) or {}
    except (json.JSONDecodeError, TypeError):
        return {}


def put_settings(conn: sqlite3.Connection, data: dict[str, Any]) -> dict[str, Any]:
    """Replace the single settings row. Returns the stored (unredacted) dict."""
    conn.execute(
        "INSERT INTO app_settings (id, settings_json, updated_at) "
        "VALUES (1, ?, datetime('now')) "
        "ON CONFLICT(id) DO UPDATE SET "
        "settings_json=excluded.settings_json, updated_at=excluded.updated_at",
        (json.dumps(data),),
    )
    conn.commit()
    return data
