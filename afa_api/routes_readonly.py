"""Read-only FastAPI router (Phases 1-2).

Endpoints (all GET, all read-only):
  /api/v1/overview
  /api/v1/leaderboard?task_id=...
  /api/v1/domains/{agent}
  /api/v1/cell/{agent}/{task_id}
  /api/v1/run/{agent}/{task_id}/{idx}
  /api/v1/meta
  /api/v1/healthz

Path segments are percent-decoded by FastAPI/Starlette (agents contain a colon,
e.g. ``qwen2.5-coder:7b`` and ``llama3.2:latest``). Run identity is
(agent, task_id, idx) — never runs.id.

Each endpoint builds a fresh projection from the configured working DB and
opens a short-lived read-only connection for raw columns the report layer omits.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from . import db, serialize
from .projection import ProjectionUnavailable, db_path_for, open_projection

router = APIRouter(prefix="/api/v1")


def _project(request: Request, builder: Callable[..., Any]) -> Any:
    """Run one serializer against a fresh, current-DB projection."""
    try:
        with open_projection(request) as projection:
            return builder(projection.stores, projection.raw)
    except ProjectionUnavailable as exc:
        # Mixed task versions and unreadable DBs are explicit unavailable state,
        # never an empty successful projection.
        return JSONResponse(status_code=503, content={"error": str(exc)})


@router.get("/healthz")
def healthz(request: Request) -> dict:
    try:
        with open_projection(request):
            return {
                "status": "ok",
                "stores_loaded": True,
                "load_error": None,
                "db_path": str(db_path_for(request)),
            }
    except ProjectionUnavailable as exc:
        return {
            "status": "degraded",
            "stores_loaded": False,
            "load_error": str(exc),
            "db_path": str(db_path_for(request)),
        }


@router.get("/overview")
async def overview(request: Request):
    return _project(
        request,
        lambda stores, raw: serialize.build_overview(stores, raw),
    )


@router.get("/leaderboard")
async def leaderboard(request: Request, task_id: str | None = None):
    return _project(
        request,
        lambda stores, raw: serialize.build_leaderboard(
            stores, raw, task_id=task_id
        ),
    )


@router.get("/domains/{agent}")
async def domains(request: Request, agent: str):
    return _project(
        request,
        lambda stores, raw: serialize.build_domains(stores, raw, agent),
    )


@router.get("/cell/{agent}/{task_id}")
async def cell(request: Request, agent: str, task_id: str):
    return _project(
        request,
        lambda stores, raw: serialize.build_cell(stores, raw, agent, task_id),
    )


@router.get("/run/{agent}/{task_id}/{idx}")
async def run(request: Request, agent: str, task_id: str, idx: int):
    result = _project(
        request,
        lambda stores, raw: serialize.build_run(stores, raw, agent, task_id, idx),
    )
    if isinstance(result, dict) and result.get("ambiguous"):
        return JSONResponse(status_code=409, content=result)
    return result


@router.get("/runs/{run_id}")
async def run_by_id(request: Request, run_id: int):
    """Exact native raw identity; does not require global aggregate pooling."""
    ro = db.connect_readonly(db_path_for(request))
    try:
        result = serialize.build_run_by_id(ro, run_id)
    finally:
        ro.close()
    if not result.get("found"):
        return JSONResponse(status_code=404, content=result)
    return result


@router.get("/meta")
async def meta(request: Request):
    return _project(
        request,
        lambda stores, raw: serialize.build_meta(stores, raw),
    )
