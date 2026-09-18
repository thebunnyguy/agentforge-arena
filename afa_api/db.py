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
    ``runs.job_id`` column — guarded so re-running against the selected working
    DB leaves every existing row untouched.

All DDL here is ``IF NOT EXISTS`` / guarded, mirroring the runner's reopen-safe
discipline. Existing inserts and tests are never broken.
"""

from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
from pathlib import Path

# Repo root = .../agentforge arena (afa_api/ lives directly under it).
ROOT = Path(__file__).resolve().parent.parent
# ``runs.sqlite`` is the committed historical evidence seed. It remains a
# compatibility constant for offline callers/tests, but is never the implicit
# writable application database.
EVIDENCE_DB_PATH = ROOT / "reports" / "runs.sqlite"
DEFAULT_WORKING_DB_PATH = ROOT / "reports" / "app.sqlite"
DB_PATH = EVIDENCE_DB_PATH  # legacy name: explicit evidence source
MANIFEST_PATH = ROOT / "tasks" / "manifest.json"


def resolve_db_path(explicit: str | Path | None = None) -> Path:
    """Resolve one application database path to its canonical absolute path.

    An explicitly bound app/worker path wins over ``AFA_DB_PATH``; otherwise
    the launcher-compatible working copy is selected. The committed evidence
    path is available only when callers explicitly request it.
    """
    if explicit is not None and str(explicit):
        raw = explicit
    else:
        raw = os.environ.get("AFA_DB_PATH") or DEFAULT_WORKING_DB_PATH
    return Path(raw).expanduser().resolve()


def _is_evidence_path(path: str | Path) -> bool:
    """Return whether ``path`` names the immutable built-in evidence file."""
    candidate = Path(path).expanduser().resolve()
    evidence = Path(EVIDENCE_DB_PATH).expanduser().resolve()
    if candidate == evidence:
        return True
    try:
        return candidate.is_file() and evidence.is_file() and candidate.samefile(evidence)
    except OSError:
        return False


def assert_writable_runtime_path(path: str | Path) -> Path:
    """Reject the built-in evidence DB at writable application boundaries."""
    selected = Path(path).expanduser().resolve()
    if _is_evidence_path(selected):
        raise ValueError(
            "refusing to open the immutable evidence database as a writable "
            f"runtime database: {selected}"
        )
    return selected

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
    mode             TEXT    NOT NULL DEFAULT 'legacy',
    source_evaluation_id TEXT,
    snapshot_json    TEXT,
    owner_token      TEXT,
    owner_started_at TEXT,
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

-- Compatibility association used by existing callers. Evaluation trials are
-- the canonical per-position state; this table remains a convenient raw link.
CREATE TABLE IF NOT EXISTS job_runs (
    job_id TEXT    NOT NULL,
    run_id INTEGER NOT NULL,
    PRIMARY KEY (job_id, run_id)
);

-- One durable row per requested position. A primary key here, rather than a
-- global raw uniqueness constraint, permits independent fresh evaluations while
-- making duplicate completion within one evaluation impossible.
CREATE TABLE IF NOT EXISTS evaluation_trials (
    evaluation_id          TEXT NOT NULL REFERENCES evaluation_jobs(id),
    task_id                TEXT NOT NULL,
    idx                    INTEGER NOT NULL,
    task_version           TEXT NOT NULL,
    task_digest            TEXT NOT NULL,
    trial_state            TEXT NOT NULL DEFAULT 'pending',
    evidence_state         TEXT NOT NULL DEFAULT 'missing',
    run_id                 INTEGER REFERENCES runs(id),
    source_evaluation_id   TEXT,
    source_run_id          INTEGER,
    origin_evaluation_id   TEXT,
    claim_token            TEXT,
    claimed_at             TEXT,
    completed_at           TEXT,
    error_message          TEXT,
    PRIMARY KEY (evaluation_id, task_id, idx)
);
CREATE INDEX IF NOT EXISTS ix_evaluation_trials_run
    ON evaluation_trials(run_id);
CREATE INDEX IF NOT EXISTS ix_evaluation_trials_state
    ON evaluation_trials(evaluation_id, trial_state);
"""


def _apply_pragmas(conn: sqlite3.Connection) -> None:
    """WAL + foreign keys + busy timeout. WAL is a db-file/connection setting;
    we set it here because the frozen store leaves the DB in ``delete`` mode."""
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute(f"PRAGMA busy_timeout={_BUSY_TIMEOUT_MS}")


def connect(db_path: str | Path | None = None) -> sqlite3.Connection:
    """Open a read/write app connection with WAL + busy_timeout and Row factory.

    The default is the launcher-compatible working DB, never the committed
    evidence DB. Safe to call repeatedly: connection pragmas are idempotent
    and the raw schema is created by the runner store when needed.
    """
    path = assert_writable_runtime_path(resolve_db_path(db_path))
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    _apply_pragmas(conn)
    return conn


def connect_readonly(db_path: str | Path | None = None) -> sqlite3.Connection:
    """Open a genuinely READ-ONLY SQLite connection for projection reads.

    The file must already exist; unlike the old fallback this function never
    silently opens a writable connection when URI read-only mode fails.
    """
    path = resolve_db_path(db_path).resolve()
    uri = path.as_uri() + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute(f"PRAGMA busy_timeout={_BUSY_TIMEOUT_MS}")
    return conn


def ensure_working_db(working_path: str | Path | None = None) -> None:
    """Seed an absent working DB without ever clobbering a concurrent winner.

    ``reports/runs.sqlite`` is immutable historical evidence. When the selected
    working path is absent, SQLite's backup API copies a coherent read-only
    snapshot (including WAL state) into a unique same-directory temporary file.
    A hard link publishes that closed snapshot with no-clobber semantics; if
    another initializer wins the race, its database is preserved.
    """
    target = assert_writable_runtime_path(resolve_db_path(working_path))
    evidence = Path(EVIDENCE_DB_PATH).expanduser().resolve()
    if target.exists() or not evidence.exists():
        return

    target.parent.mkdir(parents=True, exist_ok=True)
    tmp: Path | None = None
    source: sqlite3.Connection | None = None
    dest: sqlite3.Connection | None = None
    try:
        fd, tmp_name = tempfile.mkstemp(
            prefix=f".{target.name}.seed-",
            suffix=".tmp",
            dir=str(target.parent),
        )
        tmp = Path(tmp_name)
        os.close(fd)
        try:
            source = connect_readonly(evidence)
            dest = sqlite3.connect(str(tmp))
            source.backup(dest)
            dest.commit()
        finally:
            if dest is not None:
                dest.close()
            if source is not None:
                source.close()

        try:
            # Same-directory hard-link creation is atomic and refuses to
            # replace an existing target, unlike os.replace/os.rename.
            os.link(tmp, target)
        except FileExistsError:
            # Another initializer created (and may have modified) the winner.
            pass
    finally:
        if tmp is not None:
            try:
                tmp.unlink()
            except FileNotFoundError:
                pass


def _column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return any(r["name"] == column for r in rows)


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone()
    return row is not None


def _has_unique_key(
    conn: sqlite3.Connection, table: str, columns: tuple[str, ...]
) -> bool:
    """Check for an unconditional identity constraint, not just column names."""
    info = conn.execute(f"PRAGMA table_info({table})").fetchall()
    primary = tuple(
        row["name"] for row in sorted(info, key=lambda row: row["pk"]) if row["pk"]
    )
    if primary == columns:
        return True
    for index in conn.execute(f"PRAGMA index_list({table})").fetchall():
        if not index["unique"]:
            continue
        # A partial unique index protects only the rows matching its WHERE
        # clause; it cannot establish identity for the complete table.
        if "partial" in index.keys() and index["partial"]:
            continue
        names = tuple(
            row["name"]
            for row in conn.execute(f"PRAGMA index_info({index['name']})").fetchall()
        )
        if names == columns:
            return True
    return False


def _require_identity_key(
    conn: sqlite3.Connection, table: str, columns: tuple[str, ...]
) -> None:
    if not _has_unique_key(conn, table, columns):
        raise RuntimeError(
            f"unsupported existing {table} schema; missing unique identity key "
            "(must be unconditional); no app tables were dropped"
        )


def _validate_identity_keys(conn: sqlite3.Connection) -> None:
    """Validate every app-table identity used by control-plane writes."""
    for table, columns in (
        ("evaluation_jobs", ("id",)),
        ("app_settings", ("id",)),
        ("job_events", ("job_id", "seq")),
        ("job_runs", ("job_id", "run_id")),
        ("evaluation_trials", ("evaluation_id", "task_id", "idx")),
    ):
        if _table_exists(conn, table):
            _require_identity_key(conn, table, columns)


def _ensure_raw_schema(conn: sqlite3.Connection) -> None:
    """Create the frozen raw schema only when a fresh runtime DB has none.

    The runner remains the raw-schema owner; importing its DDL here avoids a
    fresh API volume failing before the additive app migration can run.
    Existing raw tables are never reshaped or rewritten.
    """
    if _table_exists(conn, "runs"):
        return
    runner_root = ROOT / "runner"
    kernel_root = ROOT / "kernel"
    for path in (kernel_root, runner_root):
        if str(path) not in sys.path:
            sys.path.insert(0, str(path))
    from afa_runner.store import SQLITE_SCHEMA  # type: ignore

    conn.executescript(SQLITE_SCHEMA)


def _require_columns(
    conn: sqlite3.Connection, table: str, required: tuple[str, ...]
) -> None:
    """Fail closed on an unrecognized populated app-table shape.

    The old implementation dropped such tables. Preserving them and refusing
    the migration keeps job/event/settings history recoverable for a deliberate
    compatibility migration instead of silently destroying it.
    """
    if not _table_exists(conn, table):
        return
    present = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
    missing = sorted(set(required) - present)
    if missing:
        raise RuntimeError(
            f"unsupported existing {table} schema; missing columns {missing}; "
            """no app tables were dropped"""
        )


def _heal_stale_app_tables(conn: sqlite3.Connection) -> None:
    """Validate existing app tables without destructive healing."""
    _require_columns(
        conn,
        "evaluation_jobs",
        (
            "id", "status", "cancel_requested", "params_json", "total_runs",
            "completed_runs", "passed_runs", "voided_runs", "failed_runs",
            "created_at",
        ),
    )
    _require_columns(
        conn, "job_events", ("id", "job_id", "seq", "ts", "type", "payload_json")
    )
    _require_columns(conn, "app_settings", ("id", "settings_json", "updated_at"))
    _require_columns(conn, "job_runs", ("job_id", "run_id"))
    _require_columns(
        conn,
        "evaluation_trials",
        (
            "evaluation_id", "task_id", "idx", "task_version", "task_digest",
            "trial_state", "evidence_state", "run_id", "source_evaluation_id",
            "source_run_id", "origin_evaluation_id", "claim_token", "claimed_at",
            "completed_at", "error_message",
        ),
    )
    _validate_identity_keys(conn)


def _guard_migration_target(conn: sqlite3.Connection) -> None:
    """Reject migration connections bound to the immutable evidence file."""
    try:
        rows = conn.execute("PRAGMA database_list").fetchall()
    except sqlite3.Error:
        return
    for row in rows:
        if row[1] == "main" and row[2]:
            assert_writable_runtime_path(row[2])
            return


def migrate(conn: sqlite3.Connection) -> None:
    """Idempotent, additive migration. Safe to run repeatedly against the live
    600-run DB; never UPDATEs or deletes existing raw rows.

    * sets WAL/foreign_keys/busy_timeout;
    * creates evaluation_jobs / job_events / app_settings (IF NOT EXISTS);
    * adds a NULLABLE ``runs.job_id`` column only if absent (no default, never
      written by the legacy insert path).
    """
    _guard_migration_target(conn)
    if conn.in_transaction:
        raise RuntimeError(
            "migration requires a clean connection; refusing to commit caller work"
        )
    _apply_pragmas(conn)
    # Validate any existing control-plane tables before creating or altering
    # other schema objects; unsupported shapes are refused without app repair.
    _heal_stale_app_tables(conn)
    _ensure_raw_schema(conn)
    conn.executescript(_APP_SCHEMA)
    # Validate both pre-existing and newly created tables before seeding or
    # altering any remaining control-plane state.
    _validate_identity_keys(conn)

    # Existing app tables are expanded only with additive nullable/defaulted
    # columns. An unrecognized core shape was rejected above, never dropped.
    for column, definition in (
        ("reused_runs", "INTEGER NOT NULL DEFAULT 0"),
        ("mode", "TEXT NOT NULL DEFAULT 'legacy'"),
        ("source_evaluation_id", "TEXT"),
        ("snapshot_json", "TEXT"),
        ("owner_token", "TEXT"),
        ("owner_started_at", "TEXT"),
        ("started_at", "TEXT"),
        ("finished_at", "TEXT"),
        ("error_message", "TEXT"),
    ):
        if not _column_exists(conn, "evaluation_jobs", column):
            conn.execute(
                f"ALTER TABLE evaluation_jobs ADD COLUMN {column} {definition}"
            )

    if not _column_exists(conn, "runs", "job_id"):
        # ALTER ADD COLUMN with no default => existing rows get NULL, no rewrite.
        conn.execute("ALTER TABLE runs ADD COLUMN job_id TEXT")

    _require_columns(
        conn,
        "evaluation_trials",
        (
            "evaluation_id", "task_id", "idx", "task_version", "task_digest",
            "trial_state", "evidence_state", "run_id", "source_evaluation_id",
            "source_run_id", "origin_evaluation_id", "claim_token", "claimed_at",
            "completed_at", "error_message",
        ),
    )
    _validate_identity_keys(conn)
    # Seed the single settings row if missing (id=1 enforced by CHECK).
    conn.execute(
        "INSERT OR IGNORE INTO app_settings (id, settings_json, updated_at) "
        "VALUES (1, '{}', datetime('now'))"
    )
    conn.commit()


_ensured_paths: set[Path] = set()


def ensure_schema_once(db_path: str | Path | None = None) -> None:
    """Run the additive migration once per selected database in this process."""
    selected = resolve_db_path(db_path).resolve()
    if selected in _ensured_paths:
        return
    conn = connect(selected)
    try:
        migrate(conn)
    finally:
        conn.close()
    _ensured_paths.add(selected)
