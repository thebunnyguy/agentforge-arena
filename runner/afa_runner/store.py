"""Persistence (framework §10).

v0.1 ships SqliteRunStore (stdlib sqlite3, offline, no server): the raw,
append-only layer mirroring the Postgres DDL in db/schema.sql (runs,
test_results, diffs, run_scores + minimal task/agent/run-group refs). The
production Postgres store implements the same RunStore Protocol.
"""

from __future__ import annotations

import math
import sqlite3
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable

from afa_kernel.types import RunScore, RunStatus

from .grader import GradeReport
from .pipeline import RunRecord


@dataclass(frozen=True)
class RunStoreSummary:
    """Persisted-run provenance for static report observability."""

    total_runs: int
    first_created_at: str | None
    last_created_at: str | None
    runs_with_patch: int
    runs_with_test_results: int
    test_result_rows: int


@runtime_checkable
class RunStore(Protocol):
    def save_run(self, record: RunRecord, report: GradeReport | None = None) -> int: ...
    def load_runs(
        self, task_id: str | None = None, agent: str | None = None
    ) -> list[RunRecord]: ...
    def agents(self) -> list[str]: ...
    def task_ids(self) -> list[str]: ...
    def summary(self, agent: str | None = None) -> RunStoreSummary: ...
    def close(self) -> None: ...


# Closed set of values runs.backend_kind may hold (NULL = legacy/unknown is not
# a member: it is expressed by omitting the argument). Mirrored by the CHECK in
# SQLITE_SCHEMA and by the guarded ALTER in afa_api.db.
BACKEND_KINDS: tuple[str, ...] = ("mock", "ollama", "openai_compat")


# The scoring formula this store's readers aggregate. run_scores is keyed by
# (run_id, formula_version) so a re-score APPENDS a row; readers must pin one
# formula or a re-scored run would be counted once per formula. Mirrors the
# column default in SQLITE_SCHEMA below (guarded by a test).
SCORE_FORMULA_VERSION = "v0.1"

# DDL for the SQLite raw layer. Mirrors db/schema.sql (Postgres) at the column
# level; types are SQLite-flavored. Append-only by discipline (no UPDATE paths).
SQLITE_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id         TEXT    NOT NULL,
    task_version    TEXT    NOT NULL,
    agent           TEXT    NOT NULL,
    idx             INTEGER NOT NULL,
    status          TEXT    NOT NULL,
    transcript_hash TEXT    NOT NULL,
    duration_ms     INTEGER NOT NULL,
    created_at      TEXT    NOT NULL DEFAULT (datetime('now')),
    job_id          TEXT,
    -- Provenance of the agent backend that produced this run. NULL means a
    -- legacy row / unknown provider (never a guess). Kept in lock-step with
    -- afa_api.db.migrate(), which ADDs the same column to pre-existing DBs.
    backend_kind    TEXT
        CHECK (backend_kind IS NULL
               OR backend_kind IN ('mock', 'ollama', 'openai_compat'))
);
CREATE INDEX IF NOT EXISTS ix_runs_task_agent ON runs(task_id, agent);

CREATE TABLE IF NOT EXISTS run_scores (
    run_id         INTEGER NOT NULL REFERENCES runs(id),
    gate_product   INTEGER NOT NULL,
    t_hidden       REAL    NOT NULL,
    q              REAL    NOT NULL,
    final_score    REAL    NOT NULL,
    functional_pass INTEGER NOT NULL,
    voided         INTEGER NOT NULL,
    formula_version TEXT   NOT NULL DEFAULT 'v0.1',
    PRIMARY KEY (run_id, formula_version)
);

CREATE TABLE IF NOT EXISTS diffs (
    run_id          INTEGER PRIMARY KEY REFERENCES runs(id),
    files_changed   INTEGER NOT NULL,
    lines_added     INTEGER NOT NULL,
    lines_removed   INTEGER NOT NULL,
    touched_protected INTEGER NOT NULL,
    patch_text      TEXT
);

CREATE TABLE IF NOT EXISTS test_results (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id    INTEGER NOT NULL REFERENCES runs(id),
    suite     TEXT    NOT NULL,   -- 'hidden' | 'regression'
    test_name TEXT    NOT NULL,
    passed    INTEGER NOT NULL,
    weight    REAL    NOT NULL DEFAULT 1.0
);
CREATE INDEX IF NOT EXISTS ix_test_results_run ON test_results(run_id);
"""


class SqliteRunStore:
    """SQLite-backed raw store. Append-only by discipline.

    __init__(path): open (or create) the DB at path (":memory:" allowed for
    tests) and execute SQLITE_SCHEMA.
    """

    def __init__(
        self,
        path: str | Path = ":memory:",
        *,
        read_only: bool = False,
        connection: sqlite3.Connection | None = None,
    ) -> None:
        """Open a raw store or borrow an existing SQLite connection.

        A borrowed connection is not closed by this store. The app evaluation
        persistence path uses it so raw evidence and its evaluation-trial link
        share one transaction; standalone callers retain the old path-owned
        behavior.
        """
        if connection is not None and read_only:
            raise ValueError("a borrowed raw connection cannot be read-only")
        self._read_only = read_only
        self._owns_conn = connection is None
        if connection is not None:
            self._conn = connection
        elif read_only:
            if str(path) == ":memory:":
                raise ValueError("a read-only store requires an on-disk database")
            uri = Path(path).expanduser().resolve().as_uri() + "?mode=ro"
            self._conn = sqlite3.connect(uri, uri=True)
            self._conn.execute("PRAGMA busy_timeout=5000")
        else:
            self._conn = sqlite3.connect(str(path))
        if connection is None:
            # undecodable TEXT must not fail every read that touches its row
            self._conn.text_factory = lambda raw: raw.decode("utf-8", "replace")
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        if not read_only and connection is None:
            self._conn.executescript(SQLITE_SCHEMA)
            self._conn.commit()

    @classmethod
    def open_readonly(cls, path: str | Path) -> "SqliteRunStore":
        """Open an existing raw DB without creating or altering its schema."""
        return cls(path, read_only=True)

    @property
    def connection(self) -> sqlite3.Connection:
        """The underlying connection (for read-side callers that must share one
        snapshot with this store's reads)."""
        return self._conn

    def begin_read_snapshot(self) -> None:
        """Start one deferred read transaction: every later read through this
        store or ``connection`` then sees a single consistent snapshot, even while
        another connection commits (WAL). Ended by close()/rollback."""
        if not self._conn.in_transaction:
            self._conn.execute("BEGIN")

    def save_run(
        self,
        record: RunRecord,
        report: GradeReport | None = None,
        *,
        commit: bool = True,
        job_id: str | None = None,
        backend_kind: str | None = None,
    ) -> int:
        """Insert raw evidence and return its native ``runs.id``.

        ``commit=False`` is the explicit transaction seam used by the app when
        it must publish the raw row and evaluation-trial association together.
        Existing standalone callers keep the default committed behavior.

        ``backend_kind`` records the provenance of the agent backend
        (``mock`` | ``ollama`` | ``openai_compat``). ``None`` (the default)
        leaves ``runs.backend_kind`` NULL, meaning legacy/unknown provider; the
        column is then omitted from the INSERT, so legacy callers keep working
        even against an old file that predates the column. Any other value is
        validated BEFORE the database is touched (``ValueError``). A non-None
        value is written in both insert branches (with and without ``job_id``);
        if the file's ``runs`` table lacks the column (a pre-existing DB that
        ``afa_api.db.migrate`` has not upgraded, since ``SQLITE_SCHEMA`` is
        ``CREATE TABLE IF NOT EXISTS`` and cannot alter a table) the save fails
        closed with ``RuntimeError`` rather than silently dropping provenance.
        """
        if self._read_only:
            raise sqlite3.ProgrammingError("cannot save a run to a read-only store")
        if backend_kind is not None and (
            not isinstance(backend_kind, str) or backend_kind not in BACKEND_KINDS
        ):
            raise ValueError(
                f"invalid backend_kind {backend_kind!r}; expected one of "
                f"{list(BACKEND_KINDS)} or None (legacy/unknown provider)"
            )
        conn = self._conn
        if backend_kind is not None and not any(
            row[1] == "backend_kind" for row in conn.execute("PRAGMA table_info(runs)")
        ):
            raise RuntimeError(
                "runs.backend_kind column is missing from this database; run "
                "afa_api.db.migrate() to add it (refusing to drop provenance)"
            )
        score = record.score
        # Every record produced by run_once/run_group carries its GradeReport.
        # Keep the explicit argument for callers that construct RunRecords
        # themselves and for backwards compatibility with the public API.
        report = report if report is not None else record.grade_report
        savepoint = f"afa_raw_{uuid.uuid4().hex}"
        started_transaction = not conn.in_transaction
        if started_transaction:
            conn.execute("BEGIN")
        conn.execute(f"SAVEPOINT {savepoint}")
        try:
            base = (
                record.task_id,
                record.task_version,
                record.agent,
                record.idx,
                record.status.value,
                record.transcript_hash,
                record.duration_ms,
            )
            if job_id is None and backend_kind is None:
                cur = conn.execute(
                    "INSERT INTO runs "
                    "(task_id, task_version, agent, idx, status, transcript_hash, duration_ms) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    base,
                )
            elif job_id is None:
                cur = conn.execute(
                    "INSERT INTO runs "
                    "(task_id, task_version, agent, idx, status, transcript_hash, "
                    "duration_ms, backend_kind) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (*base, backend_kind),
                )
            elif backend_kind is None:
                cur = conn.execute(
                    "INSERT INTO runs "
                    "(task_id, task_version, agent, idx, status, transcript_hash, "
                    "duration_ms, job_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (*base, job_id),
                )
            else:
                cur = conn.execute(
                    "INSERT INTO runs "
                    "(task_id, task_version, agent, idx, status, transcript_hash, "
                    "duration_ms, job_id, backend_kind) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (*base, job_id, backend_kind),
                )
            run_id = cur.lastrowid

            conn.execute(
                "INSERT INTO run_scores "
                "(run_id, gate_product, t_hidden, q, final_score, "
                "functional_pass, voided) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    run_id,
                    int(score.gate_product),
                    float(score.t_hidden),
                    float(score.q),
                    float(score.final_score),
                    int(bool(score.functional_pass)),
                    int(bool(score.voided)),
                ),
            )

            # The diff's audit patch text is only available from a GradeReport;
            # the structural counts always come from the record itself.
            patch_text = report.diff.patch_text if report is not None else None
            touched_protected = (
                report.diff.touched_protected if report is not None else False
            )
            conn.execute(
                "INSERT INTO diffs "
                "(run_id, files_changed, lines_added, lines_removed, "
                "touched_protected, patch_text) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    run_id,
                    record.files_changed,
                    record.lines_added,
                    record.lines_removed,
                    int(bool(touched_protected)),
                    patch_text,
                ),
            )

            if report is not None:
                rows = []
                for suite_name, outcome in (
                    ("regression", report.regression),
                    ("hidden", report.hidden),
                ):
                    for tr in outcome.results:
                        rows.append(
                            (
                                run_id,
                                suite_name,
                                tr.name,
                                int(bool(tr.passed)),
                                float(tr.weight),
                            )
                        )
                if rows:
                    conn.executemany(
                        "INSERT INTO test_results "
                        "(run_id, suite, test_name, passed, weight) "
                        "VALUES (?, ?, ?, ?, ?)",
                        rows,
                    )
        except Exception:
            conn.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
            conn.execute(f"RELEASE SAVEPOINT {savepoint}")
            if started_transaction:
                conn.rollback()
            raise
        else:
            conn.execute(f"RELEASE SAVEPOINT {savepoint}")
            if commit:
                conn.commit()
        return int(run_id)

    def _score_formula_clause(self) -> str:
        """Join predicate pinning ``SCORE_FORMULA_VERSION``. A database that predates
        the formula_version column keys run_scores by run_id alone (one row per run),
        so there is nothing to pin."""
        columns = {row[1] for row in self._conn.execute("PRAGMA table_info(run_scores)")}
        if "formula_version" not in columns:
            return ""
        return f"AND s.formula_version = '{SCORE_FORMULA_VERSION}' "

    def load_runs(
        self, task_id: str | None = None, agent: str | None = None
    ) -> list[RunRecord]:
        """Return RunRecords (joined with run_scores) filtered by task_id/agent,
        ordered by (agent, task_id, idx). Reconstruct RunScore from stored
        columns (q_components is not persisted in v0.1 -> {})."""
        sql = (
            "SELECT r.id, r.task_id, r.task_version, r.agent, r.idx, r.status, "
            "r.transcript_hash, r.duration_ms, "
            "s.gate_product, s.t_hidden, s.q, s.final_score, "
            "s.functional_pass, s.voided, "
            "d.files_changed, d.lines_added, d.lines_removed "
            "FROM runs r "
            "JOIN run_scores s ON s.run_id = r.id "
            f"{self._score_formula_clause()}"
            "JOIN diffs d ON d.run_id = r.id"
        )
        clauses = []
        params: list[object] = []
        if task_id is not None:
            clauses.append("r.task_id = ?")
            params.append(task_id)
        if agent is not None:
            clauses.append("r.agent = ?")
            params.append(agent)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY r.agent, r.task_id, r.idx"

        records: list[RunRecord] = []
        for row in self._conn.execute(sql, params):
            try:
                status = RunStatus(row["status"])
            except ValueError:
                # Fail closed, but name the row so it can be found and repaired.
                raise ValueError(
                    f"run {row['id']} ({row['agent']}/{row['task_id']}) has an "
                    f"unrecognised status {row['status']!r}"
                ) from None
            try:
                score = RunScore(
                    status=status,
                    gate_product=int(row["gate_product"]),
                    t_hidden=float(row["t_hidden"]),
                    q=float(row["q"]),
                    q_components={},
                    final_score=float(row["final_score"]),
                    functional_pass=bool(row["functional_pass"]),
                    voided=bool(row["voided"]),
                )
                for value in (score.t_hidden, score.q, score.final_score):
                    if not math.isfinite(value):
                        raise ValueError("non-finite score")
                for number in (
                    score.gate_product, int(row["idx"]), int(row["files_changed"]),
                    int(row["lines_added"]), int(row["lines_removed"]),
                    int(row["duration_ms"]), int(row["id"]),
                ):
                    if not -(2**63) <= number < 2**63:
                        raise ValueError("integer outside the SQLite range")
                records.append(
                    RunRecord(
                        task_id=row["task_id"],
                        task_version=row["task_version"],
                        agent=row["agent"],
                        idx=int(row["idx"]),
                        status=status,
                        score=score,
                        files_changed=int(row["files_changed"]),
                        lines_added=int(row["lines_added"]),
                        lines_removed=int(row["lines_removed"]),
                        transcript_hash=row["transcript_hash"],
                        duration_ms=int(row["duration_ms"]),
                        run_id=int(row["id"]),
                    )
                )
            except (TypeError, ValueError, OverflowError):
                # Fail closed, but name the row so it can be found and repaired.
                raise ValueError(
                    f"run {row['id']} ({row['agent']}/{row['task_id']}) has an "
                    "unreadable score or artifact column"
                ) from None
        return records

    def agents(self) -> list[str]:
        """Distinct agent names, sorted."""
        rows = self._conn.execute(
            "SELECT DISTINCT agent FROM runs ORDER BY agent"
        ).fetchall()
        return [row["agent"] for row in rows]

    def task_ids(self) -> list[str]:
        """Distinct task ids, sorted."""
        rows = self._conn.execute(
            "SELECT DISTINCT task_id FROM runs ORDER BY task_id"
        ).fetchall()
        return [row["task_id"] for row in rows]

    def summary(self, agent: str | None = None) -> RunStoreSummary:
        """Return timestamp and artifact coverage, optionally for one agent."""
        where = ""
        params: list[object] = []
        if agent is not None:
            where = "WHERE r.agent = ?"
            params.append(agent)
        row = self._conn.execute(
            "SELECT COUNT(*) AS total_runs, "
            "MIN(r.created_at) AS first_created_at, "
            "MAX(r.created_at) AS last_created_at, "
            "COALESCE(SUM(CASE WHEN d.patch_text IS NOT NULL THEN 1 ELSE 0 END), 0) "
            "AS runs_with_patch, "
            "COALESCE(SUM(CASE WHEN EXISTS ("
            "SELECT 1 FROM test_results tr WHERE tr.run_id = r.id"
            ") THEN 1 ELSE 0 END), 0) AS runs_with_test_results, "
            "COALESCE(SUM((SELECT COUNT(*) FROM test_results tr2 "
            "WHERE tr2.run_id = r.id)), 0) AS test_result_rows "
            "FROM runs r JOIN diffs d ON d.run_id = r.id " + where,
            params,
        ).fetchone()
        return RunStoreSummary(
            total_runs=int(row["total_runs"]),
            first_created_at=row["first_created_at"],
            last_created_at=row["last_created_at"],
            runs_with_patch=int(row["runs_with_patch"]),
            runs_with_test_results=int(row["runs_with_test_results"]),
            test_result_rows=int(row["test_result_rows"]),
        )

    def close(self) -> None:
        if self._owns_conn:
            self._conn.close()
