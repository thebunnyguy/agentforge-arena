"""Evidence classification for read projections: provider provenance + scope.

Pure helpers, no scoring math. A raw ``runs`` row is classified by WHO produced
it, so a mock (reference-overlay) run stored under a real model name can never be
mistaken for genuine model evidence:

  real       recorded provider is ollama / openai_compat
  synthetic  recorded provider is mock (dev / test / canary evidence)
  legacy     provider unknown (rows written before provenance existed; the 720
             committed historical rows). NOT assumed to be any provider.
  conflict   the run's own provider disagrees with its evaluation snapshot's
             provider (or is not a known kind): an integrity error, never
             resolved silently

Resolution order for one run: its own ``runs.backend_kind``; else, if it belongs
to an evaluation, that evaluation snapshot's ``backend.kind``; else ``legacy``.

An *evidence scope* names the classes that may enter an aggregate. The default
``benchmark`` scope excludes synthetic and conflicting evidence.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass

BACKEND_KINDS = ("mock", "ollama", "openai_compat")

CLASS_REAL = "real"
CLASS_SYNTHETIC = "synthetic"
CLASS_LEGACY = "legacy"
CLASS_CONFLICT = "conflict"

SCOPES: dict[str, frozenset[str]] = {
    "benchmark": frozenset({CLASS_REAL, CLASS_LEGACY}),
    "real": frozenset({CLASS_REAL}),
    "synthetic": frozenset({CLASS_SYNTHETIC}),
    "all": frozenset({CLASS_REAL, CLASS_LEGACY, CLASS_SYNTHETIC, CLASS_CONFLICT}),
}
DEFAULT_SCOPE = "benchmark"

_CLASS_BY_KIND = {
    "mock": CLASS_SYNTHETIC,
    "ollama": CLASS_REAL,
    "openai_compat": CLASS_REAL,
}


class InvalidEvidenceScope(ValueError):
    """The requested evidence scope is not one of ``SCOPES``."""


def normalize_scope(value: str | None) -> str:
    scope = DEFAULT_SCOPE if value in (None, "") else value
    if scope not in SCOPES:
        raise InvalidEvidenceScope(
            f"unknown evidence scope {scope!r}; expected one of {sorted(SCOPES)}"
        )
    return scope


@dataclass(frozen=True)
class RunProvenance:
    run_id: int
    job_id: str | None
    backend_kind: str | None  # resolved provider kind; None when unknown
    provider_source: str  # "run" | "evaluation" | "none"
    evidence_class: str


UNKNOWN_PROVENANCE = RunProvenance(
    run_id=-1, job_id=None, backend_kind=None, provider_source="none",
    evidence_class=CLASS_LEGACY,
)


def classify(
    run_id: int,
    job_id: str | None,
    run_backend: str | None,
    snapshot_backend: str | None,
) -> RunProvenance:
    """Classify one run from its own provider value and its evaluation's."""
    if run_backend is not None and run_backend not in BACKEND_KINDS:
        return RunProvenance(run_id, job_id, None, "run", CLASS_CONFLICT)
    if run_backend is not None and snapshot_backend is not None:
        if run_backend != snapshot_backend:
            return RunProvenance(run_id, job_id, run_backend, "run", CLASS_CONFLICT)
    if run_backend is not None:
        return RunProvenance(
            run_id, job_id, run_backend, "run", _CLASS_BY_KIND[run_backend]
        )
    if snapshot_backend is not None:
        return RunProvenance(
            run_id, job_id, snapshot_backend, "evaluation",
            _CLASS_BY_KIND[snapshot_backend],
        )
    return RunProvenance(run_id, job_id, None, "none", CLASS_LEGACY)


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    try:
        return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
    except sqlite3.Error:
        return set()


def snapshot_backend_kind(snapshot_json: str | None) -> str | None:
    """The backend kind an evaluation snapshot recorded, or None if unusable."""
    if not snapshot_json:
        return None
    try:
        snapshot = json.loads(snapshot_json)
    except (TypeError, ValueError):
        return None
    if not isinstance(snapshot, dict):
        return None
    backend = snapshot.get("backend")
    kind = backend.get("kind") if isinstance(backend, dict) else None
    return kind if kind in BACKEND_KINDS else None


def read_provenance(
    raw: sqlite3.Connection, run_ids: list[int] | None = None
) -> dict[int, RunProvenance]:
    """Classify persisted runs. Tolerates databases that predate the provenance
    column or the evaluation tables (everything is then ``legacy``)."""
    run_cols = _columns(raw, "runs")
    if not run_cols:
        return {}
    has_backend = "backend_kind" in run_cols
    has_job = "job_id" in run_cols
    select = "SELECT id"
    select += ", job_id" if has_job else ", NULL AS job_id"
    select += ", backend_kind" if has_backend else ", NULL AS backend_kind"
    sql = select + " FROM runs"
    params: list[object] = []
    if run_ids is not None:
        if not run_ids:
            return {}
        sql += " WHERE id IN (" + ",".join("?" for _ in run_ids) + ")"
        params = list(run_ids)
    rows = raw.execute(sql, params).fetchall()

    snapshot_kinds: dict[str, str | None] = {}
    job_ids = {row["job_id"] for row in rows if row["job_id"] is not None}
    if job_ids and {"id", "snapshot_json"} <= _columns(raw, "evaluation_jobs"):
        for job in raw.execute("SELECT id, snapshot_json FROM evaluation_jobs"):
            if job["id"] in job_ids:
                snapshot_kinds[job["id"]] = snapshot_backend_kind(job["snapshot_json"])

    return {
        int(row["id"]): classify(
            int(row["id"]),
            row["job_id"],
            row["backend_kind"],
            snapshot_kinds.get(row["job_id"]),
        )
        for row in rows
    }
