"""Evidence classification for read projections: provider provenance + scope.

Pure helpers, no scoring math. A raw ``runs`` row is classified by WHO produced
it, so a mock (reference-overlay) run stored under a real model name can never be
mistaken for genuine model evidence:

  real       recorded provider is ollama / openai_compat
  synthetic  recorded provider is mock (dev / test / canary evidence)
  legacy     provider unknown (rows written before provenance existed; the 720
             committed historical rows). NOT assumed to be any provider.
  conflict   provenance cannot be ESTABLISHED consistently: the run's own provider
             disagrees with its evaluation's, is not a known kind, an app-created
             run (it has a job_id) has no attestable provider at all, or it was
             persisted under a name reserved for a synthetic baseline. An
             integrity problem, never resolved silently and never benchmark
             evidence.

Resolution order for one run: its own ``runs.backend_kind``; else, if it belongs
to an evaluation, that evaluation's recorded provider (its snapshot, or for
evaluations created before snapshots existed its ``params_json``); else, for a
run with NO evaluation at all, ``legacy``.

An *evidence scope* names the classes that may enter an aggregate. The default
``benchmark`` scope excludes synthetic and conflicting evidence.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass

BACKEND_KINDS = ("mock", "ollama", "openai_compat")

# Names owned by the two synthetic reference baselines (mirrors
# report_combined.ORACLE / NOOP; guarded by a test). A persisted run under one of
# these names would blend into a bookend, so it is never real evidence.
RESERVED_AGENT_NAMES = frozenset(
    {"oracle (synthetic baseline)", "noop (synthetic baseline)"}
)

# Score formula every projection aggregates (mirrors runner.store.SCORE_FORMULA_VERSION;
# run_scores rows of any other formula are ignored, never double-counted).
SCORE_FORMULA_VERSION = "v0.1"

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

# A run id the provenance map does not contain cannot be attested: it is never
# assumed to be legacy (benchmark) evidence.
UNATTESTED_PROVENANCE = RunProvenance(
    run_id=-1, job_id=None, backend_kind=None, provider_source="none",
    evidence_class=CLASS_CONFLICT,
)


def classify(
    run_id: int,
    job_id: str | None,
    run_backend: str | None,
    snapshot_backend: str | None,
    params_backend: str | None = None,
    agent: str | None = None,
) -> RunProvenance:
    """Classify one run from its own provider value and its evaluation's.

    ``snapshot_backend`` / ``params_backend`` are the evaluation's recorded
    provider (snapshot preferred; params_json for evaluations that predate
    snapshots). Unknown kind strings are integrity conflicts, never exceptions.
    A run persisted under a reserved synthetic-baseline name is always a
    conflict, whatever its provider.
    """
    if agent in RESERVED_AGENT_NAMES:
        resolved = run_backend if run_backend in _CLASS_BY_KIND else (
            snapshot_backend if snapshot_backend in _CLASS_BY_KIND else (
                params_backend if params_backend in _CLASS_BY_KIND else None
            )
        )
        return RunProvenance(
            run_id, job_id, resolved, "run" if run_backend else "none", CLASS_CONFLICT
        )
    if run_backend is not None and run_backend not in _CLASS_BY_KIND:
        return RunProvenance(run_id, job_id, None, "run", CLASS_CONFLICT)
    job_kind = snapshot_backend if snapshot_backend in _CLASS_BY_KIND else (
        params_backend if params_backend in _CLASS_BY_KIND else None
    )
    if run_backend is not None and job_kind is not None and run_backend != job_kind:
        return RunProvenance(run_id, job_id, run_backend, "run", CLASS_CONFLICT)
    if run_backend is not None:
        return RunProvenance(
            run_id, job_id, run_backend, "run", _CLASS_BY_KIND[run_backend]
        )
    if job_kind is not None:
        return RunProvenance(
            run_id, job_id, job_kind, "evaluation", _CLASS_BY_KIND[job_kind]
        )
    if job_id is not None:
        # An app-created run whose provider cannot be established at all (job row
        # gone, corrupt snapshot, unknown kind): unattested, not legacy.
        return RunProvenance(run_id, job_id, None, "none", CLASS_CONFLICT)
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
    except (TypeError, ValueError, RecursionError):
        return None
    if not isinstance(snapshot, dict):
        return None
    backend = snapshot.get("backend")
    kind = backend.get("kind") if isinstance(backend, dict) else None
    return kind if kind in BACKEND_KINDS else None


def params_backend_kind(params_json: str | None) -> str | None:
    """The backend kind an evaluation's persisted params recorded, or None."""
    if not params_json:
        return None
    try:
        params = json.loads(params_json)
    except (TypeError, ValueError, RecursionError):
        return None
    if not isinstance(params, dict):
        return None
    backend = params.get("backend")
    kind = backend.get("kind") if isinstance(backend, dict) else None
    return kind if kind in BACKEND_KINDS else None


def read_provenance(
    raw: sqlite3.Connection, run_ids: list[int] | None = None
) -> dict[int, RunProvenance]:
    """Classify persisted runs. Tolerates databases that predate the provenance
    column or the evaluation tables: job-less runs are then ``legacy``, while a
    run that names a job which cannot be found is unattestable (``conflict``)."""
    run_cols = _columns(raw, "runs")
    if not run_cols:
        return {}
    has_backend = "backend_kind" in run_cols
    has_job = "job_id" in run_cols
    select = "SELECT id"
    select += ", agent" if "agent" in run_cols else ", NULL AS agent"
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
    params_kinds: dict[str, str | None] = {}
    job_ids = {row["job_id"] for row in rows if row["job_id"] is not None}
    job_cols = _columns(raw, "evaluation_jobs")
    if job_ids and "id" in job_cols:
        wanted = [c for c in ("snapshot_json", "params_json") if c in job_cols]
        if wanted:
            for job in raw.execute(f"SELECT id, {', '.join(wanted)} FROM evaluation_jobs"):
                if job["id"] in job_ids:
                    if "snapshot_json" in wanted:
                        snapshot_kinds[job["id"]] = snapshot_backend_kind(job["snapshot_json"])
                    if "params_json" in wanted:
                        params_kinds[job["id"]] = params_backend_kind(job["params_json"])

    return {
        int(row["id"]): classify(
            int(row["id"]),
            row["job_id"],
            row["backend_kind"],
            snapshot_kinds.get(row["job_id"]),
            params_kinds.get(row["job_id"]),
            agent=row["agent"],
        )
        for row in rows
    }


def score_formula_predicate(conn: sqlite3.Connection, alias: str = "s") -> str:
    """Join predicate (leading ``AND``) pinning ``SCORE_FORMULA_VERSION`` on
    ``run_scores``; empty for a database whose run_scores predates the column
    (it is then keyed by run_id alone, so there is nothing to pin)."""
    if "formula_version" not in _columns(conn, "run_scores"):
        return ""
    return f" AND {alias}.formula_version = '{SCORE_FORMULA_VERSION}'"
