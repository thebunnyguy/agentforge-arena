"""Local FastAPI app for AgentForge Arena (Phases 1-2, read-only).

ONE local app talking to the SPA in ``web/``. On startup it:
  * runs the idempotent additive migration (WAL + app tables + nullable
    runs.job_id) against reports/runs.sqlite — never breaking the raw layer;
  * loads the two aggregation stores ONCE (real + real+synthetic), following
    report_combined's sequence, and stashes them on ``app.state``.

A mixed-version refusal at load time is captured and surfaced (503 with the
exact ValueError text) instead of crashing the app.

Trusted local single-user tool. CORS is opened for the local Vite dev server
only; no auth, no untrusted-agent claims.
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import db
from .routes_jobs import router as jobs_router
from .routes_readonly import router as readonly_router
from .store_load import load_stores

# Local SPA origins (Vite default ports). Local-only by design.
_LOCAL_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:4173",
    "http://127.0.0.1:4173",
]


@asynccontextmanager
async def lifespan(app: FastAPI):
    # DB selection precedence: explicit app.state (tests) > AFA_DB_PATH env
    # (launcher/Docker) > the evidence DB default. The app works on a copy so the
    # committed evidence DB is never mutated (seeded on first use).
    db_path = (
        getattr(app.state, "db_path", None)
        or os.environ.get("AFA_DB_PATH")
        or db.DB_PATH
    )
    app.state.db_path = db_path
    db.ensure_working_db(db_path)

    # Additive migration first (safe/idempotent against the live DB). Run it
    # against whichever DB this app instance is bound to.
    try:
        conn = db.connect(db_path)
        try:
            db.migrate(conn)
        finally:
            conn.close()
    except Exception as exc:  # pragma: no cover - defensive
        app.state.migrate_error = str(exc)
    else:
        app.state.migrate_error = None

    # Load the aggregation stores once. Surface a mixed-version refusal rather
    # than swallowing it.
    app.state.stores = None
    app.state.load_error = None
    try:
        app.state.stores = load_stores(db_path=db_path)
    except ValueError as exc:
        app.state.load_error = str(exc)
    except Exception as exc:  # pragma: no cover - defensive
        app.state.load_error = f"failed to load stores: {exc}"

    try:
        yield
    finally:
        stores = getattr(app.state, "stores", None)
        if stores is not None:
            stores.close()


def _maybe_mount_spa(app: FastAPI) -> None:
    """Serve the built React SPA from the same origin as the API.

    Off by default so the test suite and the Vite dev-server workflow are
    unchanged; the single-port launcher (``afa_app.py``) sets ``AFA_SERVE_WEB=1``.
    With it on, ``/`` and client-side routes return the SPA's ``index.html`` and
    ``/assets/*`` serves the hashed JS/CSS, so the whole app runs on one port.
    """
    if not os.environ.get("AFA_SERVE_WEB"):
        return
    default_dist = Path(__file__).resolve().parent.parent / "web" / "dist"
    dist = Path(os.environ.get("AFA_WEB_DIST", str(default_dist)))
    index = dist / "index.html"
    if not index.is_file():
        return

    assets = dist / "assets"
    if assets.is_dir():
        app.mount("/assets", StaticFiles(directory=str(assets)), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def _spa(full_path: str):  # noqa: ANN202 - SPA history fallback
        # API routes are registered first and match before this catch-all;
        # any stray /api/* path should 404, not return the SPA shell.
        if full_path.startswith("api"):
            raise HTTPException(status_code=404)
        candidate = dist / full_path
        if full_path and candidate.is_file():
            return FileResponse(str(candidate))
        return FileResponse(str(index))


def create_app() -> FastAPI:
    app = FastAPI(
        title="AgentForge Arena — Local App API",
        version="0.1.0",
        description="Read-only projection of the frozen kernel/runner aggregates.",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_LOCAL_ORIGINS,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT"],
        allow_headers=["*"],
    )
    app.include_router(readonly_router)
    app.include_router(jobs_router)
    _maybe_mount_spa(app)
    return app


app = create_app()
