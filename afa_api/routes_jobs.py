"""Job control-plane HTTP router (Phases 4-6, 9).

Endpoints (mounted under ``/api/v1`` to match the read-only router):

    POST   /jobs                      create a queued job
    GET    /jobs                      list jobs
    GET    /jobs/{job_id}             get one job
    POST   /jobs/{job_id}/cancel      request cancel (queued->canceled, running flagged)
    POST   /jobs/{job_id}/retry       clone a terminal job's params into a new queued job
    GET    /jobs/{job_id}/events      SSE live stream (Last-Event-ID resume + heartbeat)
    GET    /jobs/{job_id}/events?since=N   JSON poll fallback
    GET    /settings                  read settings (secrets redacted)
    PUT    /settings                  replace settings
    POST   /backends/verify           probe a local backend
    POST   /reports/regenerate        rebuild leaderboard.html via report_combined.build_report
    GET    /export                    export JSON of the current aggregates

The worker runs jobs in a background thread on a SEPARATE sqlite connection
(WAL + busy_timeout make concurrent read/write safe). A default agent factory is
picked from the job's backend; tests inject a deterministic mock factory via
``app.state.agent_factory``.
"""

from __future__ import annotations

import asyncio
import json
import sys
import threading
from pathlib import Path
from typing import Any

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse

from . import db, jobs, worker
from .db import ROOT
from .schemas import (
    TERMINAL_STATES,
    BackendVerifyRequest,
    BackendVerifyResponse,
    JobCreate,
    Settings,
    redact_settings,
)

for _p in (ROOT / "kernel", ROOT / "runner", ROOT / "examples"):
    _s = str(_p)
    if _s not in sys.path:
        sys.path.insert(0, _s)

router = APIRouter(prefix="/api/v1")

_SSE_HEARTBEAT_S = 15.0
_SSE_POLL_S = 0.5


# --------------------------------------------------------------------------- #
# Background worker dispatch
# --------------------------------------------------------------------------- #

def _dispatch_worker(request: Request, job_id: str) -> None:
    """Run a freshly-created job in a daemon thread with its own connection.

    The agent factory may be overridden on app.state (tests inject a mock); the
    default is chosen from the job's backend kind inside ``run_job``.
    """
    factory = getattr(request.app.state, "agent_factory", None)
    db_path = getattr(request.app.state, "db_path", db.DB_PATH)

    def _work() -> None:
        conn = db.connect(db_path)
        try:
            if jobs.claim_job(conn, job_id):
                worker.run_job(conn, job_id, agent_factory=factory)
        finally:
            conn.close()

    threading.Thread(target=_work, name=f"afa-job-{job_id}", daemon=True).start()


def _conn(request: Request):
    db_path = getattr(request.app.state, "db_path", db.DB_PATH)
    return db.connect(db_path)


# --------------------------------------------------------------------------- #
# Jobs CRUD
# --------------------------------------------------------------------------- #

@router.post("/jobs")
def create_job(request: Request, body: JobCreate):
    conn = _conn(request)
    try:
        job = jobs.create_job(conn, body)
    finally:
        conn.close()
    # Auto-dispatch unless explicitly disabled (tests may want manual control).
    if getattr(request.app.state, "auto_dispatch", True):
        _dispatch_worker(request, job.id)
    return job.model_dump()


@router.get("/jobs")
def list_jobs(request: Request):
    conn = _conn(request)
    try:
        return {"jobs": [j.model_dump() for j in jobs.list_jobs(conn)]}
    finally:
        conn.close()


@router.get("/jobs/{job_id}")
def get_job(request: Request, job_id: str):
    conn = _conn(request)
    try:
        job = jobs.get_job(conn, job_id)
    finally:
        conn.close()
    if job is None:
        return JSONResponse(status_code=404, content={"error": "job not found"})
    return job.model_dump()


@router.post("/jobs/{job_id}/cancel")
def cancel_job(request: Request, job_id: str):
    conn = _conn(request)
    try:
        job = jobs.request_cancel(conn, job_id)
    finally:
        conn.close()
    if job is None:
        return JSONResponse(status_code=404, content={"error": "job not found"})
    return job.model_dump()


@router.post("/jobs/{job_id}/retry")
def retry_job(request: Request, job_id: str):
    conn = _conn(request)
    try:
        new_job = jobs.retry_job(conn, job_id)
    finally:
        conn.close()
    if new_job is None:
        return JSONResponse(
            status_code=409,
            content={"error": "job not found or not terminal"},
        )
    if getattr(request.app.state, "auto_dispatch", True):
        _dispatch_worker(request, new_job.id)
    return new_job.model_dump()


# --------------------------------------------------------------------------- #
# Events: JSON poll fallback + SSE stream
# --------------------------------------------------------------------------- #

@router.get("/jobs/{job_id}/events")
async def job_events(request: Request, job_id: str, since: int | None = None):
    """If ``?since=`` is present -> JSON poll fallback. Otherwise -> SSE stream.

    SSE honors the ``Last-Event-ID`` header (resume after last seen seq), sends
    a heartbeat comment to keep the connection alive, and closes once the job is
    terminal and all its events have been delivered.
    """
    conn = _conn(request)
    try:
        if jobs.get_job(conn, job_id) is None:
            return JSONResponse(status_code=404, content={"error": "job not found"})
        if since is not None:
            evs = jobs.events_since(conn, job_id, since=since)
            return {"job_id": job_id, "events": [e.model_dump() for e in evs]}
    finally:
        conn.close()

    # Resume point: Last-Event-ID header beats nothing; default from 0.
    last_id = request.headers.get("Last-Event-ID")
    try:
        cursor = int(last_id) if last_id is not None else 0
    except ValueError:
        cursor = 0

    db_path = getattr(request.app.state, "db_path", db.DB_PATH)

    def _poll(after: int):
        """Open/query/close a read-only connection on ONE thread (sqlite objects
        are thread-affine). Returns (events, job_status)."""
        c = db.connect_readonly(db_path)
        try:
            evs = jobs.events_since(c, job_id, after)
            job = jobs.get_job(c, job_id)
            return evs, (job.status if job else None)
        finally:
            c.close()

    async def event_stream():
        nonlocal cursor
        loop = asyncio.get_event_loop()
        while True:
            if await request.is_disconnected():
                return
            evs, status = await loop.run_in_executor(None, _poll, cursor)

            for ev in evs:
                cursor = ev.seq
                payload = json.dumps(ev.payload) if ev.payload is not None else "{}"
                yield (
                    f"id: {ev.seq}\n"
                    f"event: {ev.type}\n"
                    f"data: {payload}\n\n"
                )

            # Terminal + fully drained -> close the stream.
            if status in TERMINAL_STATES and not evs:
                yield "event: close\ndata: {}\n\n"
                return

            if not evs:
                yield ": heartbeat\n\n"
            await asyncio.sleep(_SSE_POLL_S)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# --------------------------------------------------------------------------- #
# Settings
# --------------------------------------------------------------------------- #

@router.get("/settings")
def get_settings(request: Request):
    conn = _conn(request)
    try:
        raw = jobs.get_settings_raw(conn)
    finally:
        conn.close()
    # Merge stored values over defaults, then redact secrets on the way out.
    merged = Settings.model_validate(raw).model_dump()
    if isinstance(raw.get("extra"), dict):
        merged["extra"] = {**merged.get("extra", {}), **raw["extra"]}
    return redact_settings(merged)


@router.put("/settings")
def put_settings(request: Request, body: Settings):
    conn = _conn(request)
    try:
        stored = jobs.put_settings(conn, body.model_dump())
    finally:
        conn.close()
    return redact_settings(stored)


# --------------------------------------------------------------------------- #
# Backend verification (local only)
# --------------------------------------------------------------------------- #

@router.post("/backends/verify")
async def verify_backend(request: Request, body: BackendVerifyRequest):
    if body.kind == "mock":
        return BackendVerifyResponse(
            kind="mock", ok=True,
            detail="Deterministic offline mock backend; no server required.",
            models=["mock"],
        ).model_dump()

    base_url = (body.base_url or "http://localhost:11434").rstrip("/")
    # Ollama tags endpoint; OpenAI-compat /v1/models. Local servers only.
    if body.kind == "ollama":
        url = f"{base_url}/api/tags"
        key = "models"
    else:
        url = f"{base_url}/v1/models"
        key = "data"
    try:
        async with httpx.AsyncClient(timeout=5.0) as cx:
            resp = await cx.get(url)
        resp.raise_for_status()
        data = resp.json()
        items = data.get(key, []) if isinstance(data, dict) else []
        models = [
            (m.get("name") or m.get("id") or "")
            for m in items
            if isinstance(m, dict)
        ]
        models = [m for m in models if m]
        return BackendVerifyResponse(
            kind=body.kind, ok=True,
            detail=f"Reached {url}; {len(models)} model(s) available.",
            models=models,
        ).model_dump()
    except Exception as exc:
        return BackendVerifyResponse(
            kind=body.kind, ok=False,
            detail=f"Could not reach {url}: {exc}",
        ).model_dump()


# --------------------------------------------------------------------------- #
# Reports: regenerate + export
# --------------------------------------------------------------------------- #

@router.post("/reports/regenerate")
def regenerate_report(request: Request):
    """Rebuild reports/leaderboard.html via report_combined.build_report.

    Surfaces the mixed-version refusal ValueError as a 409 (never swallowed).
    """
    import report_combined  # type: ignore

    db_path = getattr(request.app.state, "db_path", db.DB_PATH)
    try:
        html, store, real_counts = report_combined.build_report(db_path=db_path)
    except ValueError as exc:
        return JSONResponse(status_code=409, content={"error": str(exc)})
    try:
        out_path = Path(report_combined.OUTPUT)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(html)
    finally:
        store.close()
    return {
        "ok": True,
        "path": str(out_path),
        "bytes": len(html),
        "real_counts": {
            agent: {"n_runs": n_runs, "n_tasks": n_tasks}
            for agent, (n_runs, n_tasks) in real_counts.items()
        },
    }


@router.get("/export")
async def export(request: Request):
    """Export the current aggregates as JSON (read-only projection).

    Reuses the loaded stores + the frozen report fns; no statistics computed
    here. ``format=json`` is the only v1 format.
    """
    stores = getattr(request.app.state, "stores", None)
    if stores is None:
        err = getattr(request.app.state, "load_error", None) or "stores not loaded"
        return JSONResponse(status_code=503, content={"error": err})

    import afa_runner as afa  # noqa: E402

    leaderboard = [
        {
            "agent": e.agent, "pass_rate": e.pass_rate,
            "wilson_low": e.wilson_low, "wilson_high": e.wilson_high,
            "n": e.n, "provisional": e.provisional,
            "rank_low": e.rank_low, "rank_high": e.rank_high,
        }
        for e in afa.leaderboard(stores.real)
    ]
    return {
        "format": "json",
        "snapshot_note": "Snapshot of the current persisted aggregates; "
                         "synthetic baselines excluded.",
        "models": stores.models,
        "task_ids": stores.task_ids,
        "real_counts": {
            agent: {"n_runs": n_runs, "n_tasks": n_tasks}
            for agent, (n_runs, n_tasks) in stores.real_counts.items()
        },
        "leaderboard": leaderboard,
    }
