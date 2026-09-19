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
import sqlite3
import sys
from pathlib import Path
from typing import Any

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, PlainTextResponse, StreamingResponse

from . import db, evidence, jobs, serialize, worker
from .evaluation_report import build_evaluation_report, render_markdown
from .db import ROOT
from .projection import ProjectionUnavailable, db_path_for, open_projection
from .schemas import (
    TERMINAL_STATES,
    BackendVerifyRequest,
    BackendVerifyResponse,
    JobCreate,
    Settings,
    redact_settings,
    reject_secret_fields,
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
    """Use the shared token-preserving worker dispatcher."""
    worker.dispatch_job(
        db_path_for(request),
        job_id,
        agent_factory=getattr(request.app.state, "agent_factory", None),
    )


def _conn(request: Request):
    return db.connect(db_path_for(request))


# --------------------------------------------------------------------------- #
# Jobs CRUD
# --------------------------------------------------------------------------- #

@router.post("/jobs")
def create_job(request: Request, body: JobCreate):
    conn = _conn(request)
    try:
        try:
            job = jobs.create_job(conn, body)
        except jobs.JobStateError as exc:
            return JSONResponse(status_code=409, content={"error": str(exc)})
        except RuntimeError as exc:
            return JSONResponse(status_code=503, content={"error": str(exc)})
        except (ValueError, sqlite3.Error) as exc:
            return JSONResponse(status_code=422, content={"error": str(exc)})
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
        try:
            new_job = jobs.retry_job(conn, job_id)
        except RuntimeError as exc:
            return JSONResponse(status_code=503, content={"error": str(exc)})
        except (jobs.JobStateError, ValueError, sqlite3.Error) as exc:
            return JSONResponse(status_code=409, content={"error": str(exc)})
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


@router.post("/jobs/{job_id}/resume")
def resume_job(request: Request, job_id: str):
    """Explicit same-ID continuation of incomplete, snapshotted trials."""
    conn = _conn(request)
    try:
        try:
            resumed = jobs.resume_job(conn, job_id)
        except RuntimeError as exc:
            return JSONResponse(status_code=503, content={"error": str(exc)})
        except jobs.JobStateError as exc:
            return JSONResponse(status_code=409, content={"error": str(exc)})
    finally:
        conn.close()
    if resumed is None:
        return JSONResponse(status_code=404, content={"error": "job not found"})
    if getattr(request.app.state, "auto_dispatch", True):
        _dispatch_worker(request, resumed.id)
    return resumed.model_dump()


@router.get("/jobs/{job_id}/trials")
def get_trials(request: Request, job_id: str):
    conn = _conn(request)
    try:
        result = jobs.evaluation_results(conn, job_id)
    finally:
        conn.close()
    if result is None:
        return JSONResponse(status_code=404, content={"error": "job not found"})
    return result


@router.get("/jobs/{job_id}/results")
def get_results(request: Request, job_id: str):
    """Stable-ID alias for the minimal evaluation-scoped result facts."""
    return get_trials(request, job_id)


@router.get("/jobs/{job_id}/report.json")
def get_evaluation_report(request: Request, job_id: str):
    conn = db.connect_readonly(db_path_for(request))
    try:
        report = build_evaluation_report(conn, job_id)
    finally:
        conn.close()
    if report is None:
        return JSONResponse(status_code=404, content={"error": "job not found"})
    return report


@router.get("/jobs/{job_id}/report.md")
def get_evaluation_report_markdown(request: Request, job_id: str):
    conn = db.connect_readonly(db_path_for(request))
    try:
        report = build_evaluation_report(conn, job_id)
    finally:
        conn.close()
    if report is None:
        return JSONResponse(status_code=404, content={"error": "job not found"})
    return PlainTextResponse(render_markdown(report), media_type="text/markdown")


@router.get("/jobs/{job_id}/trials/{task_id}/{idx}")
def get_trial(request: Request, job_id: str, task_id: str, idx: int):
    conn = _conn(request)
    try:
        result = jobs.trial_detail(conn, job_id, task_id, idx)
    finally:
        conn.close()
    if result is None:
        return JSONResponse(status_code=404, content={"error": "trial not found"})
    return result


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

    db_path = db_path_for(request)

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
    try:
        reject_secret_fields(body.model_dump())
    except ValueError as exc:
        return JSONResponse(status_code=422, content={"error": str(exc)})
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

    default_url = "http://localhost:11434" if body.kind == "ollama" else "http://localhost:1234"
    base_url = (body.base_url or default_url).rstrip("/")
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

    The report is the CURRENT benchmark in the requested evidence scope
    (``?evidence=``, default benchmark). Historical and out-of-scope runs are
    excluded and counted in the HTML subtitle; version coexistence is no longer
    an error. Unexpected ValueErrors (e.g. the structural single-version
    invariant) are still surfaced as a 409, never swallowed.
    """
    import report_combined  # type: ignore

    try:
        scope = evidence.normalize_scope(request.query_params.get("evidence"))
    except evidence.InvalidEvidenceScope as exc:
        return JSONResponse(status_code=400, content={"error": str(exc)})
    db_path = db_path_for(request)
    try:
        html, store, real_counts = report_combined.build_report(
            db_path=db_path, evidence_scope=scope
        )
    except ValueError as exc:
        return JSONResponse(status_code=409, content={"error": str(exc)})
    except (OSError, sqlite3.Error) as exc:
        return JSONResponse(
            status_code=503,
            content={"error": f"report database unavailable: {exc}"},
        )
    try:
        out_path = Path(report_combined.OUTPUT)
        if scope != evidence.DEFAULT_SCOPE:
            # Only the benchmark-scope report may occupy the canonical artifact; a
            # synthetic / real-only / all report goes to a scope-suffixed sibling
            # so it can never replace the benchmark report.
            out_path = out_path.with_name(f"{out_path.stem}-{scope}{out_path.suffix}")
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(html)
    finally:
        store.close()
    return {
        "ok": True,
        "path": str(out_path),
        "bytes": len(html),
        "evidence_scope": scope,
        "real_counts": {
            agent: {"n_runs": n_runs, "n_tasks": n_tasks}
            for agent, (n_runs, n_tasks) in real_counts.items()
        },
    }


@router.get("/export")
async def export(request: Request):
    """Export a fresh aggregate projection from the configured working DB."""
    try:
        scope = evidence.normalize_scope(request.query_params.get("evidence"))
    except evidence.InvalidEvidenceScope as exc:
        return JSONResponse(status_code=400, content={"error": str(exc)})
    try:
        with open_projection(request, scope) as projection:
            return serialize.build_export(projection.stores)
    except ProjectionUnavailable as exc:
        return JSONResponse(status_code=503, content={"error": str(exc)})
