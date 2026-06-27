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

Stores are loaded ONCE at app startup and stashed on ``app.state`` (see main.py).
This router only reads them and opens short-lived read-only DB connections for
the raw columns the report layer omits.
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from . import db, serialize
from .store_load import LoadedStores

router = APIRouter(prefix="/api/v1")


def _stores(request: Request) -> LoadedStores | None:
    return getattr(request.app.state, "stores", None)


def _load_error(request: Request) -> str | None:
    return getattr(request.app.state, "load_error", None)


def _unavailable(request: Request) -> JSONResponse | None:
    """If startup refused to load (e.g. mixed-version ValueError), surface it as
    503 with the exact message rather than 500/silent failure."""
    if _stores(request) is None:
        err = _load_error(request) or "stores not loaded"
        return JSONResponse(status_code=503, content={"error": err})
    return None


@router.get("/healthz")
def healthz(request: Request) -> dict:
    stores = _stores(request)
    return {
        "status": "ok" if stores is not None else "degraded",
        "stores_loaded": stores is not None,
        "load_error": _load_error(request),
        "db_path": str(db.DB_PATH),
    }


@router.get("/overview")
async def overview(request: Request):
    if (resp := _unavailable(request)) is not None:
        return resp
    ro = db.connect_readonly()
    try:
        return serialize.build_overview(_stores(request), ro)
    finally:
        ro.close()


@router.get("/leaderboard")
async def leaderboard(request: Request, task_id: str | None = None):
    if (resp := _unavailable(request)) is not None:
        return resp
    ro = db.connect_readonly()
    try:
        return serialize.build_leaderboard(_stores(request), ro, task_id=task_id)
    finally:
        ro.close()


@router.get("/domains/{agent}")
async def domains(request: Request, agent: str):
    if (resp := _unavailable(request)) is not None:
        return resp
    ro = db.connect_readonly()
    try:
        return serialize.build_domains(_stores(request), ro, agent)
    finally:
        ro.close()


@router.get("/cell/{agent}/{task_id}")
async def cell(request: Request, agent: str, task_id: str):
    if (resp := _unavailable(request)) is not None:
        return resp
    ro = db.connect_readonly()
    try:
        return serialize.build_cell(_stores(request), ro, agent, task_id)
    finally:
        ro.close()


@router.get("/run/{agent}/{task_id}/{idx}")
async def run(request: Request, agent: str, task_id: str, idx: int):
    if (resp := _unavailable(request)) is not None:
        return resp
    ro = db.connect_readonly()
    try:
        return serialize.build_run(_stores(request), ro, agent, task_id, idx)
    finally:
        ro.close()


@router.get("/meta")
async def meta(request: Request):
    if (resp := _unavailable(request)) is not None:
        return resp
    ro = db.connect_readonly()
    try:
        return serialize.build_meta(_stores(request), ro)
    finally:
        ro.close()
