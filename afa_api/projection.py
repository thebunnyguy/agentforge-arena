"""Fresh read projections bound to the app's authoritative working database."""

from __future__ import annotations

import sqlite3
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from collections.abc import Iterator

from fastapi import Request

from . import db
from .store_load import LoadedStores, load_stores


class ProjectionUnavailable(RuntimeError):
    """The selected database cannot produce a trustworthy read projection."""


_MIGRATION_RETRY_INTERVAL_S = 1.0
_migration_retry_lock = threading.Lock()


def retry_migration_if_failed(app) -> None:
    """Re-attempt a FAILED startup migration instead of staying 503 until restart.

    A migration can fail transiently (for example another initializer held the
    write lock longer than busy_timeout while the launcher started the worker and
    the API together). ``migrate_error`` used to be sticky, which took every
    projection down until the process was restarted. Retrying is safe: migrate()
    is idempotent, serialised, and refuses unsupported shapes with the same error
    (so a permanent refusal simply stays a refusal). Rate-limited so a permanent
    failure costs at most one attempt per second.
    """
    if not getattr(app.state, "migrate_error", None):
        return
    if time.monotonic() - getattr(app.state, "migrate_retry_at", 0.0) < _MIGRATION_RETRY_INTERVAL_S:
        return
    with _migration_retry_lock:
        if not getattr(app.state, "migrate_error", None):
            return
        app.state.migrate_retry_at = time.monotonic()
        # Deferred import: startup pulls in the worker, which projections never need.
        from . import startup

        if startup.migrate_control_plane(app):
            # Startup recovery was skipped when the migration failed; do it now.
            startup.recover_stale_jobs(app)


@dataclass
class Projection:
    """One request's disposable aggregate stores and raw read connection."""

    stores: LoadedStores
    raw: sqlite3.Connection


def db_path_for(request: Request):
    """Return the single DB binding selected at the application boundary."""
    return db.resolve_db_path(getattr(request.app.state, "db_path", None))


@contextmanager
def open_projection(
    request: Request, evidence_scope: str | None = None
) -> Iterator[Projection]:
    """Open a fresh projection from the current configured DB and close it.

    The source store used by ``load_stores`` is read-only; the returned aggregate
    stores are in-memory derived data. This prevents a startup snapshot from
    becoming a second source of truth after a worker appends a run.

    ``evidence_scope`` selects which provenance classes may enter the aggregates
    (default: the benchmark scope, which excludes synthetic/mock evidence).
    """
    retry_migration_if_failed(request.app)
    migration_error = getattr(request.app.state, "migrate_error", None)
    if migration_error:
        raise ProjectionUnavailable(f"database migration failed: {migration_error}")

    path = db_path_for(request)
    stores: LoadedStores | None = None
    raw: sqlite3.Connection | None = None
    try:
        stores = load_stores(db_path=path, evidence_scope=evidence_scope)
        raw = db.connect_readonly(path)
    except ValueError as exc:
        if stores is not None:
            stores.close()
        raise ProjectionUnavailable(str(exc)) from exc
    except Exception as exc:
        if stores is not None:
            stores.close()
        raise ProjectionUnavailable(f"failed to load stores: {exc}") from exc

    try:
        yield Projection(stores=stores, raw=raw)
    finally:
        raw.close()
        stores.close()
