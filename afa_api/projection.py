"""Fresh read projections bound to the app's authoritative working database."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from collections.abc import Iterator

from fastapi import Request

from . import db
from .store_load import LoadedStores, load_stores


class ProjectionUnavailable(RuntimeError):
    """The selected database cannot produce a trustworthy read projection."""


@dataclass
class Projection:
    """One request's disposable aggregate stores and raw read connection."""

    stores: LoadedStores
    raw: sqlite3.Connection


def db_path_for(request: Request):
    """Return the single DB binding selected at the application boundary."""
    return db.resolve_db_path(getattr(request.app.state, "db_path", None))


@contextmanager
def open_projection(request: Request) -> Iterator[Projection]:
    """Open a fresh projection from the current configured DB and close it.

    The source store used by ``load_stores`` is read-only; the returned aggregate
    stores are in-memory derived data. This prevents a startup snapshot from
    becoming a second source of truth after a worker appends a run.
    """
    migration_error = getattr(request.app.state, "migrate_error", None)
    if migration_error:
        raise ProjectionUnavailable(f"database migration failed: {migration_error}")

    path = db_path_for(request)
    stores: LoadedStores | None = None
    raw: sqlite3.Connection | None = None
    try:
        stores = load_stores(db_path=path)
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
