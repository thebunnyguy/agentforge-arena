"""Concurrent, additive, fail-closed schema migration (afa_api.db.migrate).

Before the fix ``migrate`` was check-then-ALTER with no lock: several
initializers racing on a freshly seeded copy of the evidence DB all saw a column
missing, and all but one died with ``sqlite3.OperationalError: duplicate column
name: ...`` (and, on delete-mode files, ``database is locked`` from the WAL
switch). These tests reproduce that with real threads and real subprocesses
released together, and pin the fix: serialised via ``BEGIN IMMEDIATE``, a
lock-free fast path when the schema is current, additive and idempotent, with
the historical rows byte-for-byte unchanged and ``runs.backend_kind`` added.

The committed evidence DB is only ever read (via the SQLite backup API in
``ensure_working_db``); a module fixture proves its sha256 never changes.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from afa_api import db
from afa_kernel.types import RunScore, RunStatus
from afa_runner.pipeline import RunRecord
from afa_runner.store import BACKEND_KINDS, SQLITE_SCHEMA, SqliteRunStore

REPO = Path(__file__).resolve().parents[1]
RAW_TABLES = ("runs", "run_scores", "diffs", "test_results")
EXPECTED_TABLES = {
    *RAW_TABLES, "evaluation_jobs", "job_events", "app_settings", "job_runs",
    "evaluation_trials",
}

OLD_RUNS_DDL = """
CREATE TABLE runs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id         TEXT    NOT NULL,
    task_version    TEXT    NOT NULL,
    agent           TEXT    NOT NULL,
    idx             INTEGER NOT NULL,
    status          TEXT    NOT NULL,
    transcript_hash TEXT    NOT NULL,
    duration_ms     INTEGER NOT NULL,
    created_at      TEXT    NOT NULL DEFAULT (datetime('now'))
);
"""

# Real-subprocess initializer. It imports, reports "ready", then blocks on stdin
# for a wall-clock start time and spin-waits for it, so every child leaves the
# starting line within microseconds of the others (a pipe wake-up alone skews
# them by milliseconds, enough to serialise them and hide the race).
CHILD = r"""
import json, sys, time
from afa_api import db
path = sys.argv[1]
print("ready", flush=True)
start = float(sys.stdin.readline())
while time.time() < start:
    pass
err = None
try:
    conn = db.connect(path)
    try:
        db.migrate(conn)
    finally:
        conn.close()
except Exception as exc:
    err = "%s: %s" % (type(exc).__name__, exc)
print(json.dumps(err), flush=True)
"""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


@pytest.fixture(scope="module", autouse=True)
def evidence_db_is_never_modified():
    before = _sha256(db.EVIDENCE_DB_PATH)
    yield
    assert _sha256(db.EVIDENCE_DB_PATH) == before, "evidence DB was modified"


def _seed(tmp_path: Path, name: str = "x.sqlite", *, journal: str = "wal") -> Path:
    """Fresh runtime copy of the evidence DB (backup API), optionally delete-mode."""
    path = tmp_path / name
    db.ensure_working_db(path)
    assert path.exists()
    if journal == "delete":
        raw = sqlite3.connect(path)
        try:
            raw.execute("PRAGMA journal_mode=DELETE")
        finally:
            raw.close()
    return path


def _raw_checksums(path: Path, columns: dict[str, list[str]] | None = None):
    """Per-table (row count, sha256) over the ORIGINAL columns only.

    ``SELECT *`` would grow a NULL ``backend_kind`` column after the migration,
    so the column list is captured beforehand and reused.
    """
    conn = sqlite3.connect(path)
    try:
        if columns is None:
            columns = {
                t: [r[1] for r in conn.execute(f"PRAGMA table_info({t})")]
                for t in RAW_TABLES
            }
        out = {}
        for table in RAW_TABLES:
            digest = hashlib.sha256()
            count = 0
            cols = ", ".join(columns[table])
            for row in conn.execute(f"SELECT {cols} FROM {table} ORDER BY rowid"):
                digest.update(repr(tuple(row)).encode())
                count += 1
            out[table] = (count, digest.hexdigest())
        return columns, out
    finally:
        conn.close()


def _assert_schema_complete(path: Path) -> None:
    conn = sqlite3.connect(path)
    try:
        tables = {
            r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        assert EXPECTED_TABLES <= tables
        cols = lambda t: {r[1] for r in conn.execute(f"PRAGMA table_info({t})")}  # noqa: E731
        assert {"job_id", "backend_kind"} <= cols("runs")
        assert {
            "reused_runs", "mode", "source_evaluation_id", "snapshot_json",
            "owner_token", "owner_started_at", "started_at", "finished_at",
            "error_message", "cancel_requested", "params_json",
        } <= cols("evaluation_jobs")
        indexes = {
            r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='index'")
        }
        assert {
            "ix_job_events_job_seq", "ix_evaluation_trials_run",
            "ix_evaluation_trials_state",
        } <= indexes

        def pk(table: str) -> tuple[str, ...]:
            info = sorted(conn.execute(f"PRAGMA table_info({table})"), key=lambda r: r[5])
            return tuple(r[1] for r in info if r[5])

        assert pk("evaluation_jobs") == ("id",)
        assert pk("job_runs") == ("job_id", "run_id")
        assert pk("evaluation_trials") == ("evaluation_id", "task_id", "idx")
        unique = [
            tuple(i[2] for i in conn.execute(f"PRAGMA index_info({idx[1]})"))
            for idx in conn.execute("PRAGMA index_list(job_events)")
            if idx[2]
        ]
        assert ("job_id", "seq") in unique
        assert conn.execute("SELECT COUNT(*) FROM app_settings WHERE id=1").fetchone()[0] == 1
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    finally:
        conn.close()


# --------------------------------------------------------------------------- #
# Concurrent initializers: threads and real processes
# --------------------------------------------------------------------------- #

def _thread_initializers(path: Path, n: int) -> list[str | None]:
    barrier = threading.Barrier(n)
    errors: list[str | None] = [None] * n

    def work(i: int) -> None:
        try:
            barrier.wait()
            conn = db.connect(path)  # each initializer owns its connection
            try:
                db.migrate(conn)
            finally:
                conn.close()
        except Exception as exc:  # recorded, asserted empty by the caller
            errors[i] = f"{type(exc).__name__}: {exc}"

    threads = [threading.Thread(target=work, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(60)
    return errors


def _process_initializers(path: Path, n: int) -> list[str | None]:
    root = str(REPO)
    env = dict(
        os.environ,
        PYTHONPATH=os.pathsep.join(
            [root, f"{root}/kernel", f"{root}/runner", f"{root}/integrity"]
        ),
        PYTHONDONTWRITEBYTECODE="1",
    )
    procs = [
        subprocess.Popen(
            [sys.executable, "-c", CHILD, str(path)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, env=env, cwd=root,
        )
        for _ in range(n)
    ]
    for p in procs:
        assert p.stdout.readline().strip() == "ready", p.stderr.read()
    start = time.time() + 0.25
    for p in procs:  # release together
        p.stdin.write(f"{start!r}\n")
        p.stdin.flush()
    errors: list[str | None] = []
    for p in procs:
        out, err = p.communicate(timeout=60)
        try:
            errors.append(json.loads(out.strip().splitlines()[-1]))
        except Exception:
            errors.append(f"child crashed: {err[-300:]}")
    return errors


@pytest.mark.parametrize(
    "runner, n, reps, journal",
    [
        (_thread_initializers, 8, 20, "wal"),
        (_thread_initializers, 8, 10, "delete"),
        (_process_initializers, 8, 12, "wal"),
        (_process_initializers, 8, 10, "delete"),
    ],
    ids=["threads-wal", "threads-delete", "procs-wal", "procs-delete"],
)
def test_concurrent_initializers_on_seeded_evidence_copy(
    tmp_path: Path, runner, n: int, reps: int, journal: str
):
    for rep in range(reps):
        path = _seed(tmp_path, f"seed-{rep}.sqlite", journal=journal)
        columns, before = _raw_checksums(path)
        assert before["runs"][0] > 0  # the historical rows are really there
        errors = runner(path, n)
        assert [e for e in errors if e] == [], f"rep {rep}: {errors}"
        _assert_schema_complete(path)
        _, after = _raw_checksums(path, columns)
        assert after == before, "historical rows changed"
        conn = sqlite3.connect(path)
        try:
            assert conn.execute(
                "SELECT COUNT(*) FROM runs WHERE backend_kind IS NOT NULL"
            ).fetchone()[0] == 0
        finally:
            conn.close()


def test_no_rival_can_interleave_between_the_column_check_and_the_alter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Deterministic version of the original race.

    Old code: ``_column_exists`` said "missing", a rival initializer then ADDed
    the column, and our own ALTER died with ``duplicate column name``. Here a
    rival tries exactly that in the gap right after the check. Serialised by
    ``BEGIN IMMEDIATE`` it cannot get the write lock (so it is refused), and the
    migration completes with the column added exactly once.
    """
    path = _seed(tmp_path)
    real = db._column_exists
    outcomes: list[str] = []

    def hooked(conn, table, column):
        result = real(conn, table, column)
        if (table, column) == ("evaluation_jobs", "owner_token") and not outcomes:
            assert result is False  # the seed really lacks it: this is the race window
            rival = sqlite3.connect(path, timeout=0.2)
            try:
                rival.execute("ALTER TABLE evaluation_jobs ADD COLUMN owner_token TEXT")
                rival.commit()
                outcomes.append("rival-won")
            except sqlite3.OperationalError as exc:
                outcomes.append(str(exc))
            finally:
                rival.close()
        return result

    monkeypatch.setattr(db, "_column_exists", hooked)
    conn = db.connect(path)
    try:
        db.migrate(conn)  # would raise "duplicate column name" without the lock
    finally:
        conn.close()
    assert outcomes and "locked" in outcomes[0], outcomes
    _assert_schema_complete(path)


def test_concurrent_initializers_on_a_brand_new_empty_file(tmp_path: Path):
    """Racing ``_ensure_raw_schema`` + app schema creation on a file with no tables."""
    for rep in range(3):
        path = tmp_path / f"empty-{rep}.sqlite"
        errors = _thread_initializers(path, 6)
        assert [e for e in errors if e] == [], errors
        _assert_schema_complete(path)
        conn = sqlite3.connect(path)
        try:
            assert conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 0
        finally:
            conn.close()


# --------------------------------------------------------------------------- #
# Fast path: an already-current schema takes no write lock
# --------------------------------------------------------------------------- #

def _statements(path: Path, action) -> list[str]:
    conn = db.connect(path)
    seen: list[str] = []
    try:
        conn.set_trace_callback(seen.append)
        action(conn)
    finally:
        conn.close()
    return seen


def test_fast_path_issues_no_write_statements_when_current(tmp_path: Path):
    path = _seed(tmp_path)
    conn = db.connect(path)
    try:
        db.migrate(conn)
    finally:
        conn.close()

    seen = _statements(path, db.migrate)
    assert seen, "trace callback saw nothing"
    writes = ("BEGIN", "ALTER", "CREATE", "INSERT", "UPDATE", "DELETE", "DROP", "COMMIT")
    assert [s for s in seen if s.lstrip().upper().startswith(writes)] == []

    # Control: a stale DB does take the write lock (so the assertion above is
    # not vacuous).
    stale = _seed(tmp_path, "stale.sqlite")
    stale_seen = _statements(stale, db.migrate)
    assert any(s.strip().upper() == "BEGIN IMMEDIATE" for s in stale_seen)
    assert any(s.lstrip().upper().startswith("ALTER TABLE RUNS") for s in stale_seen)


def test_fast_path_is_not_blocked_by_a_held_write_lock_but_slow_path_is(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(db, "_BUSY_TIMEOUT_MS", 200)
    current = _seed(tmp_path, "current.sqlite")
    setup = db.connect(current)
    try:
        db.migrate(setup)
    finally:
        setup.close()
    stale = _seed(tmp_path, "stale.sqlite")

    for path, must_wait in ((current, False), (stale, True)):
        holder = db.connect(path)
        holder.execute("BEGIN IMMEDIATE")  # some other writer owns the write lock
        try:
            conn = db.connect(path)
            try:
                started = time.monotonic()
                if must_wait:
                    with pytest.raises(sqlite3.OperationalError, match="locked"):
                        db.migrate(conn)  # waits busy_timeout, then raises: NOT swallowed
                    assert time.monotonic() - started >= 0.15
                    assert not conn.in_transaction
                else:
                    db.migrate(conn)
                    assert time.monotonic() - started < 0.15
            finally:
                conn.close()
        finally:
            holder.rollback()
            holder.close()

    # Once the lock is released the stale DB migrates.
    conn = db.connect(stale)
    try:
        db.migrate(conn)
    finally:
        conn.close()
    _assert_schema_complete(stale)


# --------------------------------------------------------------------------- #
# Fail-closed, atomic, idempotent, additive
# --------------------------------------------------------------------------- #

def _schema_dump(path: Path) -> list[tuple]:
    conn = sqlite3.connect(path)
    try:
        return sorted(
            conn.execute("SELECT type, name, sql FROM sqlite_master").fetchall()
        )
    finally:
        conn.close()


def test_migrate_is_idempotent(tmp_path: Path):
    path = _seed(tmp_path)
    columns, before = _raw_checksums(path)
    dumps = []
    for _ in range(3):
        conn = db.connect(path)
        try:
            db.migrate(conn)
            assert not conn.in_transaction
        finally:
            conn.close()
        dumps.append(_schema_dump(path))
    assert dumps[0] == dumps[1] == dumps[2]
    assert _raw_checksums(path, columns)[1] == before
    conn = sqlite3.connect(path)
    try:
        assert conn.execute("SELECT COUNT(*) FROM app_settings").fetchone()[0] == 1
    finally:
        conn.close()


def test_unsupported_shape_still_fails_closed_and_preserves_data(tmp_path: Path):
    path = _seed(tmp_path)
    raw = sqlite3.connect(path)
    try:
        # A legacy control-plane shape the migration must NOT repair or drop.
        raw.execute("DROP TABLE evaluation_jobs")
        raw.execute(
            "CREATE TABLE evaluation_jobs (id TEXT PRIMARY KEY, status TEXT, params_json TEXT)"
        )
        raw.execute("INSERT INTO evaluation_jobs VALUES ('keep', 'done', '{}')")
        raw.commit()
    finally:
        raw.close()
    columns, before = _raw_checksums(path)
    dump = _schema_dump(path)

    conn = db.connect(path)
    try:
        assert db._schema_is_current(conn) is False  # the fast path never masks it
        with pytest.raises(
            RuntimeError, match=r"unsupported existing evaluation_jobs schema.*missing columns"
        ):
            db.migrate(conn)
        assert not conn.in_transaction
        assert conn.execute("SELECT id, status FROM evaluation_jobs").fetchall()[0][:] == (
            "keep", "done",
        )
    finally:
        conn.close()
    assert _schema_dump(path) == dump  # not a single DDL survived
    assert _raw_checksums(path, columns)[1] == before

    # A missing unconditional identity key is also refused, with the same text.
    path2 = _seed(tmp_path, "y.sqlite")
    raw = sqlite3.connect(path2)
    try:
        raw.execute("DROP TABLE job_runs")
        raw.execute("CREATE TABLE job_runs (job_id TEXT NOT NULL, run_id INTEGER NOT NULL)")
        raw.commit()
    finally:
        raw.close()
    conn = db.connect(path2)
    try:
        with pytest.raises(
            RuntimeError, match=r"unsupported existing job_runs schema.*missing unique"
        ):
            db.migrate(conn)
    finally:
        conn.close()


def test_failure_mid_migration_rolls_back_every_ddl(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    path = _seed(tmp_path)
    dump = _schema_dump(path)
    # A valid table followed by a statement that fails: all-or-nothing.
    monkeypatch.setattr(
        db,
        "_APP_SCHEMA",
        db._APP_SCHEMA + "\nCREATE TABLE zz_partial (x INTEGER);\n"
        "CREATE INDEX ix_zz_bad ON no_such_table(y);\n",
    )
    conn = db.connect(path)
    try:
        with pytest.raises(sqlite3.OperationalError, match="no_such_table"):
            db.migrate(conn)
        assert not conn.in_transaction
    finally:
        conn.close()
    assert _schema_dump(path) == dump


def test_migration_refuses_a_dirty_connection_and_the_evidence_db(tmp_path: Path):
    path = _seed(tmp_path)
    conn = db.connect(path)
    try:
        conn.execute("CREATE TABLE caller_marker (v TEXT)")
        conn.execute("INSERT INTO caller_marker VALUES ('pending')")
        with pytest.raises(RuntimeError, match="clean connection"):
            db.migrate(conn)
        assert conn.in_transaction  # the caller's work was neither committed nor lost
        conn.rollback()
    finally:
        conn.close()
    raw = sqlite3.connect(db.EVIDENCE_DB_PATH)
    try:
        with pytest.raises(ValueError, match="immutable evidence database"):
            db.migrate(raw)
    finally:
        raw.close()


# --------------------------------------------------------------------------- #
# Statement splitter (executescript cannot run inside a transaction)
# --------------------------------------------------------------------------- #

def _objects(conn: sqlite3.Connection) -> dict[str, list[tuple]]:
    return {
        r[0]: [tuple(c[1:]) for c in conn.execute(f"PRAGMA table_info({r[0]})")]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
    } | {
        "#indexes": sorted(
            r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='index'")
        )
    }


@pytest.mark.parametrize(
    "script, expected",
    [
        (db._APP_SCHEMA, db._APP_SCHEMA.count("CREATE ")),
        (SQLITE_SCHEMA, SQLITE_SCHEMA.count("CREATE ")),
    ],
    ids=["app-schema", "raw-schema"],
)
def test_statement_splitter_matches_executescript(script: str, expected: int):
    statements = db._split_statements(script)
    assert len(statements) == expected
    assert all(sqlite3.complete_statement(s) for s in statements)
    via_split = sqlite3.connect(":memory:")
    via_script = sqlite3.connect(":memory:")
    try:
        # The app schema references runs(id); create the raw layer first.
        prelude = SQLITE_SCHEMA if script is db._APP_SCHEMA else ""
        if prelude:
            via_script.executescript(prelude)
            db._execute_script(via_split, prelude)
        via_script.executescript(script)
        db._execute_script(via_split, script)
        assert _objects(via_split) == _objects(via_script)
    finally:
        via_split.close()
        via_script.close()


def test_statement_splitter_edge_cases():
    assert db._split_statements("-- only a comment\n") == []
    assert db._split_statements("SELECT 1; -- trailing\n-- more\nSELECT ';';") == [
        "SELECT 1; -- trailing",
        "-- more\nSELECT ';';",
    ]
    with pytest.raises(ValueError, match="unterminated"):
        db._split_statements("SELECT 1; SELECT 2")


# --------------------------------------------------------------------------- #
# runs.backend_kind provenance column
# --------------------------------------------------------------------------- #

def _record(idx: int = 0) -> RunRecord:
    return RunRecord(
        task_id="fix-binary-search",
        task_version="9.9.9",
        agent="prov-agent",
        idx=idx,
        status=RunStatus.VALID,
        score=RunScore(
            status=RunStatus.VALID, gate_product=1, t_hidden=1.0, q=1.0,
            q_components={}, final_score=1.0, functional_pass=True, voided=False,
        ),
        files_changed=1,
        lines_added=1,
        lines_removed=0,
        transcript_hash="sha256:x",
        duration_ms=1,
    )


def _backend_col(path: Path) -> list[tuple]:
    conn = sqlite3.connect(path)
    try:
        return [
            r for r in conn.execute("PRAGMA table_xinfo(runs)") if r[1] == "backend_kind"
        ]
    finally:
        conn.close()


def test_backend_kind_is_added_to_the_evidence_copy_without_touching_rows(tmp_path: Path):
    path = _seed(tmp_path)
    assert _backend_col(path) == []  # the committed evidence lacks the column
    columns, before = _raw_checksums(path)
    conn = db.connect(path)
    try:
        db.migrate(conn)
    finally:
        conn.close()
    col = _backend_col(path)
    assert len(col) == 1 and col[0][2] == "TEXT" and col[0][3] == 0  # nullable
    assert col[0][4] is None  # no default: ADD COLUMN never rewrites rows
    assert _raw_checksums(path, columns)[1] == before
    raw = sqlite3.connect(path)
    try:
        n = raw.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
        assert n == before["runs"][0]
        assert raw.execute("SELECT COUNT(*) FROM runs WHERE backend_kind IS NULL").fetchone()[0] == n
        # The CHECK constraint really is attached to the ALTERed column.
        for good in BACKEND_KINDS:
            raw.execute(
                "UPDATE runs SET backend_kind=? WHERE id=(SELECT MIN(id) FROM runs)", (good,)
            )
        with pytest.raises(sqlite3.IntegrityError):
            raw.execute("UPDATE runs SET backend_kind='gpt-5' WHERE id=(SELECT MIN(id) FROM runs)")
    finally:
        raw.close()


def _old_raw_schema() -> str:
    """The raw layer as it shipped before runs.job_id / runs.backend_kind."""
    others = db._split_statements(SQLITE_SCHEMA)[1:]  # everything after CREATE TABLE runs
    return OLD_RUNS_DDL + "\n".join(others)


def test_backend_kind_ddl_is_identical_in_schema_and_migration():
    assert BACKEND_KINDS == ("mock", "ollama", "openai_compat")
    fresh = sqlite3.connect(":memory:")
    altered = sqlite3.connect(":memory:")
    try:
        fresh.executescript(SQLITE_SCHEMA)
        altered.executescript(_old_raw_schema())
        for column, definition in db._RUNS_ADDITIVE:  # what migrate() runs
            altered.execute(f"ALTER TABLE runs ADD COLUMN {column} {definition}")
        insert = (
            "INSERT INTO runs (task_id, task_version, agent, idx, status,"
            " transcript_hash, duration_ms, backend_kind)"
            " VALUES ('t','1','a',0,'valid','h',1,?)"
        )
        for conn in (fresh, altered):
            for bad in ("gpt", "", "MOCK"):
                with pytest.raises(sqlite3.IntegrityError):
                    conn.execute(insert, (bad,))
            for good in (None, *BACKEND_KINDS):
                conn.execute(insert, (good,))
    finally:
        fresh.close()
        altered.close()


def test_pre_existing_app_sqlite_without_the_column_gets_it_on_migrate(tmp_path: Path):
    """An old app.sqlite: raw tables from before job_id/backend_kind existed."""
    path = tmp_path / "app.sqlite"
    raw = sqlite3.connect(path)
    try:
        raw.executescript(_old_raw_schema())
        raw.execute(
            "INSERT INTO runs (task_id, task_version, agent, idx, status, transcript_hash,"
            " duration_ms) VALUES ('t', '1.0.0', 'old', 0, 'valid', 'h', 5)"
        )
        raw.commit()
        assert [r[1] for r in raw.execute("PRAGMA table_info(runs)")] == [
            "id", "task_id", "task_version", "agent", "idx", "status",
            "transcript_hash", "duration_ms", "created_at",
        ]
    finally:
        raw.close()
    conn = db.connect(path)
    try:
        db.migrate(conn)
        row = conn.execute("SELECT task_id, agent, job_id, backend_kind FROM runs").fetchone()
        assert tuple(row) == ("t", "old", None, None)
    finally:
        conn.close()
    _assert_schema_complete(path)


def test_run_store_on_an_old_file_reads_and_fails_closed_on_provenance(tmp_path: Path):
    path = _seed(tmp_path)  # evidence copy: has job_id, lacks backend_kind
    store = SqliteRunStore(path)  # CREATE TABLE IF NOT EXISTS: must not choke
    try:
        assert _backend_col(path) == []  # ...and it cannot add the column
        assert len(store.load_runs()) > 0
        before = store._conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0]

        # Legacy callers (no provenance) keep working on the old file.
        store.save_run(_record(0))
        store.save_run(_record(1), job_id="legacy-job")
        # Provenance cannot be recorded: fail closed, write NOTHING.
        for kwargs in ({"backend_kind": "ollama"}, {"backend_kind": "mock", "job_id": "j"}):
            with pytest.raises(RuntimeError, match="backend_kind column is missing"):
                store.save_run(_record(2), **kwargs)
        assert store._conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == before + 2
    finally:
        store.close()

    conn = db.connect(path)
    try:
        db.migrate(conn)
    finally:
        conn.close()
    store = SqliteRunStore(path)
    try:
        run_id = store.save_run(_record(2), backend_kind="ollama")
        row = store._conn.execute(
            "SELECT backend_kind FROM runs WHERE id=?", (run_id,)
        ).fetchone()
        assert row["backend_kind"] == "ollama"
        assert len(store.load_runs()) >= 720  # load_runs is unchanged
    finally:
        store.close()


@pytest.mark.parametrize("job_id", [None, "job-1"])
def test_save_run_writes_backend_kind_in_both_insert_branches(job_id):
    store = SqliteRunStore(":memory:")
    try:
        ids = {
            kind: store.save_run(_record(i), job_id=job_id, backend_kind=kind)
            for i, kind in enumerate((*BACKEND_KINDS, None))
        }
        for kind, run_id in ids.items():
            row = store._conn.execute(
                "SELECT backend_kind, job_id FROM runs WHERE id=?", (run_id,)
            ).fetchone()
            assert row["backend_kind"] == kind
            assert row["job_id"] == job_id
    finally:
        store.close()


@pytest.mark.parametrize(
    "bad", ["", "MOCK", "gpt", "Mock", " mock", "mock ", "unknown", 1, True, b"mock", ["mock"]]
)
@pytest.mark.parametrize("job_id", [None, "job-1"])
def test_save_run_rejects_invalid_backend_kind_before_touching_the_db(bad, job_id):
    store = SqliteRunStore(":memory:")
    try:
        with pytest.raises(ValueError, match="invalid backend_kind"):
            store.save_run(_record(), job_id=job_id, backend_kind=bad)
        assert not store._conn.in_transaction  # no BEGIN / SAVEPOINT was issued
        assert store._conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 0
    finally:
        store.close()


def test_fresh_run_store_schema_has_the_checked_column(tmp_path: Path):
    path = tmp_path / "fresh.sqlite"
    SqliteRunStore(path).close()
    col = _backend_col(path)
    assert len(col) == 1 and col[0][3] == 0 and col[0][4] is None
    conn = db.connect(path)
    try:
        db.migrate(conn)
    finally:
        conn.close()
    _assert_schema_complete(path)
