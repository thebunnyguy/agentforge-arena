"""SQLite connection helpers for the local app backend.

The frozen ``SqliteRunStore`` (runner) owns the raw append-only layer
(``runs``/``run_scores``/``diffs``/``test_results``) and recreates that schema
idempotently on every open. It does NOT set WAL and it does NOT know about the
app's own tables. This module adds, WITHOUT touching the runner:

  * WAL + a sane ``busy_timeout`` on every app-side connection (the live DB
    ships in ``journal_mode=delete``; the app upgrades it on open);
  * a read-only connection helper for the projection endpoints;
  * an idempotent, additive migration that creates the app tables
    (``evaluation_jobs``, ``job_events``, ``app_settings``) and a nullable
    ``runs.job_id`` column — guarded so re-running against the live 600-run DB
    leaves every existing row untouched.

All DDL here is ``IF NOT EXISTS`` / guarded, mirroring the runner's reopen-safe
discipline. Existing inserts and tests are never broken.
"""

from __future__ import annotations

import os
import shutil
import sqlite3
from pathlib import Path

# Repo root = .../agentforge arena (afa_api/ lives directly under it).
ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "reports" / "runs.sqlite"
MANIFEST_PATH = ROOT / "tasks" / "manifest.json"

# Connection pragmas applied on every open. busy_timeout (ms) lets a reader
# wait out a writer instead of erroring immediately under WAL.
_BUSY_TIMEOUT_MS = 5000


# Additive app tables (plan Phase 4). None of this is read by the frozen runner;
# the legacy raw insert path never writes here. The column shape mirrors the
# plan's recommended control-plane schema (params_json + counters +
# cancel_requested + lifecycle timestamps), so the worker state machine and the
# SSE monitor have a stable home.
_APP_SCHEMA = """
CREATE TABLE IF NOT EXISTS evaluation_jobs (
    id               TEXT    PRIMARY KEY,
    status           TEXT    NOT NULL,
    cancel_requested INTEGER NOT NULL DEFAULT 0,
    params_json      TEXT    NOT NULL,
    total_runs       INTEGER NOT NULL DEFAULT 0,
    completed_runs   INTEGER NOT NULL DEFAULT 0,
    passed_runs      INTEGER NOT NULL DEFAULT 0,
    voided_runs      INTEGER NOT NULL DEFAULT 0,
    failed_runs      INTEGER NOT NULL DEFAULT 0,
    reused_runs      INTEGER NOT NULL DEFAULT 0,
    created_at       TEXT    NOT NULL DEFAULT (datetime('now')),
    started_at       TEXT,
    finished_at      TEXT,
    error_message    TEXT
);

CREATE TABLE IF NOT EXISTS job_events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id      TEXT    NOT NULL REFERENCES evaluation_jobs(id),
    seq         INTEGER NOT NULL,
    ts          TEXT    NOT NULL DEFAULT (datetime('now')),
    type        TEXT    NOT NULL,
    payload_json TEXT,
    UNIQUE (job_id, seq)
);
CREATE INDEX IF NOT EXISTS ix_job_events_job_seq ON job_events(job_id, seq);

CREATE TABLE IF NOT EXISTS app_settings (
    id            INTEGER PRIMARY KEY CHECK (id = 1),
    settings_json TEXT    NOT NULL DEFAULT '{}',
    updated_at    TEXT    NOT NULL DEFAULT (datetime('now'))
);

-- Append-only join table that links a job to the raw runs it produced, so the
-- legacy `runs` table need not be UPDATEd. The hard-constraint also asks for a
-- nullable runs.job_id column (added below); both are kept and stay consistent.
CREATE TABLE IF NOT EXISTS job_runs (
    job_id TEXT    NOT NULL,
    run_id INTEGER NOT NULL,
    PRIMARY KEY (job_id, run_id)
);
"""


def _apply_pragmas(conn: sqlite3.Connection) -> None:
    """WAL + foreign keys + busy timeout. WAL is a db-file/connection setting;
    we set it here because the frozen store leaves the DB in ``delete`` mode."""
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute(f"PRAGMA busy_timeout={_BUSY_TIMEOUT_MS}")


def connect(db_path: str | Path = DB_PATH) -> sqlite3.Connection:
    """Open a read/write app connection with WAL + busy_timeout and Row factory.

    Safe to call repeatedly: WAL/foreign_keys/busy_timeout are idempotent and the
    underlying file's raw schema is created IF NOT EXISTS by the runner store.
    """
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    _apply_pragmas(conn)
    return conn


def connect_readonly(db_path: str | Path = DB_PATH) -> sqlite3.Connection:
    """Open a READ-ONLY connection (SQLite ``mode=ro`` URI) for projection reads.

    The file must already exist (the read-only API never creates the DB). WAL is
    a persistent file attribute, so a prior writer's WAL mode stays in effect;
    we still set foreign_keys/busy_timeout on the connection. Falls back to a
    plain read/write connection only if URI mode is unavailable.
    """
    path = Path(db_path)
    uri = f"file:{path}?mode=ro"
    try:
        conn = sqlite3.connect(uri, uri=True)
    except sqlite3.OperationalError:
        conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute(f"PRAGMA busy_timeout={_BUSY_TIMEOUT_MS}")
    return conn


def ensure_working_db(working_path: str | Path) -> None:
    """Seed a working DB from the read-only evidence DB on first use.

    The committed ``reports/runs.sqlite`` is the immutable EVIDENCE database (the
    600 audited runs). When the app is pointed at a DIFFERENT path (the default
    working copy used by the launcher and Docker), copy the evidence DB there
    once so that neither browsing nor running evaluations ever mutates the
    evidence DB. No-op when the target already exists or IS the evidence DB.
    Race-safe via atomic temp-then-rename, so concurrent api/worker startups are
    fine (both copy identical content; the rename is atomic).
    """
    target = Path(working_path)
    if str(target) == str(DB_PATH) or target.exists() or not DB_PATH.exists():
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(f"{target.name}.seed-{os.getpid()}.tmp")
    shutil.copy(DB_PATH, tmp)
    os.replace(tmp, target)


def _column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return any(r["name"] == column for r in rows)


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone()
    return row is not None


def _heal_stale_app_tables(conn: sqlite3.Connection) -> None:
    """One-time, idempotent reshape of the control-plane tables.

    An earlier build created ``evaluation_jobs`` / ``job_events`` /
    ``app_settings`` with a different column shape. Those tables are app-only
    (NEVER benchmark data) and are dropped + recreated to the current schema
    when the legacy shape is detected. The raw benchmark layer
    (runs/run_scores/diffs/test_results) is never touched. ``CREATE TABLE IF NOT
    EXISTS`` cannot alter an existing table, so this guard is what lets the
    migration converge on an already-initialized DB.
    """
    if _table_exists(conn, "evaluation_jobs") and not _column_exists(
        conn, "evaluation_jobs", "cancel_requested"
    ):
        conn.execute("DROP TABLE IF EXISTS job_events")
        conn.execute("DROP TABLE IF EXISTS evaluation_jobs")
        conn.execute("DROP TABLE IF EXISTS app_settings")
    if _table_exists(conn, "app_settings") and not _column_exists(
        conn, "app_settings", "settings_json"
    ):
        conn.execute("DROP TABLE IF EXISTS app_settings")


def migrate(conn: sqlite3.Connection) -> None:
    """Idempotent, additive migration. Safe to run repeatedly against the live
    600-run DB; never UPDATEs or deletes existing raw rows.

    * sets WAL/foreign_keys/busy_timeout;
    * creates evaluation_jobs / job_events / app_settings (IF NOT EXISTS);
    * adds a NULLABLE ``runs.job_id`` column only if absent (no default, never
      written by the legacy insert path).
    """
    _apply_pragmas(conn)
    _heal_stale_app_tables(conn)
    conn.executescript(_APP_SCHEMA)
    if not _column_exists(conn, "runs", "job_id"):
        # ALTER ADD COLUMN with no default => existing rows get NULL, no rewrite.
        conn.execute("ALTER TABLE runs ADD COLUMN job_id TEXT")
    # reused_runs was added after the first release; backfill it on app DBs that
    # predate it so the counter stays consistent.
    if _table_exists(conn, "evaluation_jobs") and not _column_exists(
        conn, "evaluation_jobs", "reused_runs"
    ):
        conn.execute(
            "ALTER TABLE evaluation_jobs "
            "ADD COLUMN reused_runs INTEGER NOT NULL DEFAULT 0"
        )
    # Seed the single settings row if missing (id=1 enforced by CHECK).
    conn.execute(
        "INSERT OR IGNORE INTO app_settings (id, settings_json, updated_at) "
        "VALUES (1, '{}', datetime('now'))"
    )
    conn.commit()


_ensured = False


def ensure_schema_once(db_path: str | Path = DB_PATH) -> None:
    """Run the additive migration exactly once per process.

    Opens its own read/write connection (creating the raw schema via the runner
    store would be the alternative; here we rely on the live DB already having
    it, and only ADD the app layer). Idempotent across processes too.
    """
    global _ensured
    if _ensured:
        return
    conn = connect(db_path)
    try:
        migrate(conn)
    finally:
        conn.close()
    _ensured = True
