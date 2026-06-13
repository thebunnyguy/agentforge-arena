"""Persistence (framework §10).

v0.1 ships SqliteRunStore (stdlib sqlite3, offline, no server): the raw,
append-only layer mirroring the Postgres DDL in db/schema.sql (runs,
test_results, diffs, run_scores + minimal task/agent/run-group refs). The
production Postgres store implements the same RunStore Protocol.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Protocol, runtime_checkable

from afa_kernel.types import RunScore, RunStatus

from .grader import GradeReport
from .pipeline import RunRecord


@runtime_checkable
class RunStore(Protocol):
    def save_run(self, record: RunRecord, report: GradeReport | None = None) -> int: ...
    def load_runs(
        self, task_id: str | None = None, agent: str | None = None
    ) -> list[RunRecord]: ...
    def agents(self) -> list[str]: ...
    def task_ids(self) -> list[str]: ...
    def close(self) -> None: ...


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
    created_at      TEXT    NOT NULL DEFAULT (datetime('now'))
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

    def __init__(self, path: str | Path = ":memory:") -> None:
        """Open the connection and create tables. Use sqlite3 with
        check_same_thread=False off by default; store rows via parameterized
        SQL only."""
        # str(path) handles both ":memory:" and a Path to an on-disk DB file.
        self._conn = sqlite3.connect(str(path))
        self._conn.row_factory = sqlite3.Row
        # Enforce the declared foreign keys so an orphaned score/diff/result
        # row can never be written (the raw layer is append-only by discipline).
        self._conn.execute("PRAGMA foreign_keys = ON")
        # executescript runs the multi-statement DDL (CREATE TABLE/INDEX ...).
        self._conn.executescript(SQLITE_SCHEMA)
        self._conn.commit()

    def save_run(self, record: RunRecord, report: GradeReport | None = None) -> int:
        """Insert one run + its score + diff (+ test_results from report if given)
        in a single transaction. Return the new runs.id. Implements §10 raw layer."""
        conn = self._conn
        score = record.score
        try:
            cur = conn.execute(
                "INSERT INTO runs "
                "(task_id, task_version, agent, idx, status, transcript_hash, duration_ms) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    record.task_id,
                    record.task_version,
                    record.agent,
                    record.idx,
                    record.status.value,
                    record.transcript_hash,
                    record.duration_ms,
                ),
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
            conn.rollback()
            raise
        else:
            conn.commit()
        return int(run_id)

    def load_runs(
        self, task_id: str | None = None, agent: str | None = None
    ) -> list[RunRecord]:
        """Return RunRecords (joined with run_scores) filtered by task_id/agent,
        ordered by (agent, task_id, idx). Reconstruct RunScore from stored
        columns (q_components is not persisted in v0.1 -> {})."""
        sql = (
            "SELECT r.task_id, r.task_version, r.agent, r.idx, r.status, "
            "r.transcript_hash, r.duration_ms, "
            "s.gate_product, s.t_hidden, s.q, s.final_score, "
            "s.functional_pass, s.voided, "
            "d.files_changed, d.lines_added, d.lines_removed "
            "FROM runs r "
            "JOIN run_scores s ON s.run_id = r.id "
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
            status = RunStatus(row["status"])
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
                )
            )
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

    def close(self) -> None:
        self._conn.close()
