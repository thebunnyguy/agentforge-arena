"""Version-aware, provenance-aware two-store load + synthetic baselines.

This reuses the exact sequence from ``examples/report_combined.py`` so the app's
aggregation store matches the canonical report, with one deliberate change: the
aggregates represent the CURRENT benchmark.

  1. an in-memory aggregation ``SqliteRunStore`` and a read-only on-disk source;
  2. every persisted run is classified twice: by provenance (real / synthetic /
     legacy / conflict, see ``evidence``) and by version (CURRENT if its
     ``task_version`` equals ``tasks/<id>/task.json`` version, else HISTORICAL);
  3. only CURRENT runs whose class is in the requested evidence scope enter the
     aggregation stores, so the (version-blind) kernel functions can never pool
     versions. Historical and out-of-scope rows are not discarded: they are kept
     as plain records for the per-version history views and are counted in
     ``excluded`` / ``agent_evidence`` so nothing is hidden silently;
  4. the mixed-version refusal is retained as a structural invariant: if an
     aggregation store were ever to hold two versions of one (agent, task) cell,
     ``ValueError`` is raised;
  5. the two clearly-labeled synthetic bookends (oracle always-pass, noop
     always-fail), N=5 runs each, are added to the ``full`` store only.

The read-only projection API exposes TWO stores:
  * ``real`` — persisted CURRENT model runs in scope (no synthetic baselines);
  * ``full`` — ``real`` + synthetic baselines, matching report_combined.

No scoring math is reimplemented here.
"""

from __future__ import annotations

import json
import sys
from contextlib import ExitStack
from dataclasses import dataclass, field
from pathlib import Path

from . import evidence
from .db import MANIFEST_PATH, ROOT, resolve_db_path

# Ensure kernel + runner are importable (tests run with PYTHONPATH="kernel:runner",
# but the app may be imported with only the repo root on sys.path).
for _p in (ROOT / "kernel", ROOT / "runner", ROOT / "examples"):
    _s = str(_p)
    if _s not in sys.path:
        sys.path.insert(0, _s)

import afa_runner as afa  # noqa: E402
from afa_runner.pipeline import RunRecord  # noqa: E402

# Reuse the canonical report constants + helpers (do NOT reimplement).
from report_combined import (  # type: ignore  # noqa: E402
    N,
    NOOP,
    ORACLE,
    _add_synthetic_baseline,
    _current_task_version,
)

SYNTHETIC_AGENTS = frozenset({ORACLE, NOOP})


def version_sort_key(version: str) -> tuple:
    """Newest-first ordering helper for opaque version strings.

    Dotted numeric versions sort numerically; anything else sorts lexically
    before them. Only used to order the history list, never to decide currency.
    """
    parts = version.split(".")
    if all(part.isdigit() for part in parts):
        return (1, tuple(int(part) for part in parts), version)
    return (0, (), version)


@dataclass(frozen=True)
class LoadedRun:
    """One persisted run: the raw record, its provenance, and where it sits."""

    record: RunRecord
    provenance: evidence.RunProvenance
    is_current: bool  # record.task_version == the task's current version


@dataclass
class AgentEvidence:
    """Per-agent evidence accounting, restricted to the requested scope."""

    n_runs: int = 0
    tasks: set[str] = field(default_factory=set)
    current_runs: int = 0
    current_tasks: set[str] = field(default_factory=set)
    historical_runs: int = 0
    historical_tasks: set[str] = field(default_factory=set)


@dataclass
class LoadedStores:
    """The loaded aggregation stores plus the manifest-derived metadata the
    projection layer needs. All numbers downstream come from the report fns over
    these stores; nothing here computes statistics."""

    real: afa.SqliteRunStore  # persisted CURRENT model runs in scope only
    full: afa.SqliteRunStore  # real + synthetic baselines (report_combined)
    real_counts: dict[str, tuple[int, int]]  # agent -> (n_runs, n_tasks): CURRENT, in scope
    task_ids: list[str]  # manifest order
    tasks_meta: dict[str, dict]  # id -> {difficulty, domains, current_version, ...}
    current_versions: dict[str, str]
    task_domains: dict[str, list]  # id -> [(domain, weight), ...]
    models: list[str]  # agents with >=1 in-scope run of any version
    synthetic_agents: list[str]
    observability: object  # disk RunStoreSummary: real patch/test/created_at coverage
    agent_observability: dict  # agent -> disk RunStoreSummary (real per-agent coverage)
    scope: str = evidence.DEFAULT_SCOPE
    runs: list[LoadedRun] = field(default_factory=list)  # in-scope, any version
    agent_evidence: dict[str, AgentEvidence] = field(default_factory=dict)
    excluded: dict = field(default_factory=dict)  # out-of-scope accounting
    excluded_cells: dict[tuple[str, str], dict[str, int]] = field(default_factory=dict)
    # Versions STORED for a cell / task across every evidence class (a persisted
    # fact, independent of the requested scope), e.g. to show that a task was
    # evaluated at 1.0.1 and 1.0.2 even when the newer runs are mock-only.
    stored_cell_versions: dict[tuple[str, str], set[str]] = field(default_factory=dict)
    stored_task_versions: dict[str, set[str]] = field(default_factory=dict)
    current_models: list[str] = field(default_factory=list)
    historical_only_models: list[str] = field(default_factory=list)

    def close(self) -> None:
        try:
            self.real.close()
        finally:
            self.full.close()

    # ---- in-scope run access (any version) -------------------------------- #

    def runs_for(
        self,
        *,
        agent: str | None = None,
        task_id: str | None = None,
        version: str | None = None,
    ) -> list[LoadedRun]:
        return [
            run
            for run in self.runs
            if (agent is None or run.record.agent == agent)
            and (task_id is None or run.record.task_id == task_id)
            and (version is None or run.record.task_version == version)
        ]

    def versions_for(self, agent: str, task_id: str) -> list[str]:
        """In-scope versions present for one cell: current first, then newest first."""
        present = {
            r.record.task_version for r in self.runs_for(agent=agent, task_id=task_id)
        }
        current = self.current_versions.get(task_id)
        ordered = sorted(present - {current}, key=version_sort_key, reverse=True)
        return ([current] if current in present else []) + ordered

    def scratch_store(self, runs: list[LoadedRun]) -> afa.SqliteRunStore:
        """A throwaway in-memory kernel store over the given runs (caller closes).

        Used for per-version views. Callers must pass runs of ONE task version so
        the version-blind kernel functions still never pool versions.
        """
        per_task: dict[str, set[str]] = {}
        for run in runs:
            per_task.setdefault(run.record.task_id, set()).add(run.record.task_version)
        if any(len(versions) > 1 for versions in per_task.values()):
            raise ValueError("refusing to pool multiple task versions in a scratch store")
        store = afa.SqliteRunStore(":memory:")
        try:
            for run in runs:
                store.save_run(run.record)
        except Exception:
            store.close()
            raise
        return store

    def aggregate_for(self, agent: str, task_id: str, version: str):
        """Kernel ``task_aggregate`` for one (agent, task, version), or None."""
        runs = self.runs_for(agent=agent, task_id=task_id, version=version)
        if not runs:
            return None
        store = self.scratch_store(runs)
        try:
            return afa.task_aggregate(store, agent, task_id)
        finally:
            store.close()


def _build_manifest_meta(manifest_path: str | Path):
    manifest = json.loads(Path(manifest_path).read_text())
    meta = {item["id"]: item for item in manifest}
    current_versions = {
        item["id"]: _current_task_version(item, manifest_path) for item in manifest
    }
    task_ids = list(meta)
    tasks_meta = {
        item["id"]: {
            "difficulty": item.get("manual_difficulty", 0),
            "domains": [tuple(domain) for domain in item.get("domains", [])],
            "activity": item.get("activity"),
            "scale": item.get("scale"),
            "dir": item.get("dir"),
            "current_version": current_versions[item["id"]],
        }
        for item in manifest
    }
    task_domains = {
        item["id"]: [tuple(domain) for domain in item.get("domains", [])]
        for item in manifest
    }
    return manifest, current_versions, task_ids, tasks_meta, task_domains


def load_stores(
    db_path: str | Path | None = None,
    manifest_path: str | Path = MANIFEST_PATH,
    evidence_scope: str | None = None,
) -> LoadedStores:
    """Load both stores: CURRENT, in-scope evidence only (see module docstring).

    Raises ``ValueError`` if an aggregation store would pool two versions of one
    cell (structurally unreachable; kept as an invariant), and
    ``evidence.InvalidEvidenceScope`` (a ValueError) for an unknown scope. The
    synthetic baselines are added only to ``full``. Every acquired source and
    in-memory store is closed if any loading or baseline step fails; successful
    aggregate stores transfer to the returned owner.
    """
    scope = evidence.normalize_scope(evidence_scope)
    in_scope_classes = evidence.SCOPES[scope]
    (
        _manifest,
        current_versions,
        task_ids,
        tasks_meta,
        task_domains,
    ) = _build_manifest_meta(manifest_path)

    db_path = resolve_db_path(db_path)
    aggregate_scope = ExitStack()
    try:
        # Register each successful acquisition immediately. pop_all() below
        # transfers the two aggregate stores to the successful caller.
        real = afa.SqliteRunStore(":memory:")
        aggregate_scope.callback(real.close)
        full = afa.SqliteRunStore(":memory:")
        aggregate_scope.callback(full.close)

        agent_evidence: dict[str, AgentEvidence] = {}
        loaded_runs: list[LoadedRun] = []
        cell_versions: dict[tuple[str, str], set[str]] = {}
        excluded_synthetic_runs = 0
        excluded_synthetic_models: set[str] = set()
        excluded_conflict_runs = 0
        excluded_out_of_scope_runs = 0
        excluded_cells: dict[tuple[str, str], dict[str, int]] = {}
        stored_cell_versions: dict[tuple[str, str], set[str]] = {}
        stored_task_versions: dict[str, set[str]] = {}
        disk: afa.SqliteRunStore | None = None
        try:
            # This source store is explicitly read-only: projections must never
            # create schema or mutate the selected DB just to read it.
            disk = afa.SqliteRunStore.open_readonly(db_path)
            # ONE read snapshot for provenance, runs and summaries: a run
            # committed by a live worker mid-load can never be seen by one read
            # and missed by the other (which used to classify a fresh mock run
            # as benchmark evidence for one request).
            disk.begin_read_snapshot()
            provenance = evidence.read_provenance(disk.connection)
            total_runs_in_db = disk.connection.execute(
                "SELECT COUNT(*) FROM runs"
            ).fetchone()[0]
            projected_runs = 0

            for agent in disk.agents():
                for record in disk.load_runs(agent=agent):
                    projected_runs += 1
                    prov = provenance.get(record.run_id, evidence.UNATTESTED_PROVENANCE)
                    # Persisted under a synthetic baseline's name: a conflict (set by
                    # read_provenance) that is NEVER aggregated, in any scope
                    # (examples/report_combined does the same).
                    reserved = agent in evidence.RESERVED_AGENT_NAMES
                    stored_cell_versions.setdefault((agent, record.task_id), set()).add(
                        record.task_version
                    )
                    stored_task_versions.setdefault(record.task_id, set()).add(
                        record.task_version
                    )
                    if reserved or prov.evidence_class not in in_scope_classes:
                        cell_ex = excluded_cells.setdefault(
                            (agent, record.task_id),
                            {"synthetic_runs": 0, "provenance_conflict_runs": 0},
                        )
                        if prov.evidence_class == evidence.CLASS_SYNTHETIC:
                            excluded_synthetic_runs += 1
                            excluded_synthetic_models.add(agent)
                            cell_ex["synthetic_runs"] += 1
                        elif prov.evidence_class == evidence.CLASS_CONFLICT:
                            excluded_conflict_runs += 1
                            cell_ex["provenance_conflict_runs"] += 1
                        else:
                            # e.g. legacy runs under the real / synthetic scope
                            excluded_out_of_scope_runs += 1
                        continue
                    is_current = (
                        current_versions.get(record.task_id) == record.task_version
                    )
                    loaded_runs.append(LoadedRun(record, prov, is_current))
                    ev = agent_evidence.setdefault(agent, AgentEvidence())
                    ev.n_runs += 1
                    ev.tasks.add(record.task_id)
                    if is_current:
                        ev.current_runs += 1
                        ev.current_tasks.add(record.task_id)
                        cell_versions.setdefault((agent, record.task_id), set()).add(
                            record.task_version
                        )
                        real.save_run(record)
                        full.save_run(record)
                    else:
                        ev.historical_runs += 1
                        ev.historical_tasks.add(record.task_id)
            models = sorted(agent_evidence)
            # Capture the DISK summary (real patch / test_results / created_at
            # coverage) before closing. The in-memory stores re-save aggregate
            # records without those artifacts, so their summary would report 0
            # patches and a fake created_at (= load time).
            disk_summary = disk.summary()
            disk_agent_summaries = {agent: disk.summary(agent) for agent in models}
        finally:
            if disk is not None:
                disk.close()

        # Structural invariant (this was the runtime refusal): the aggregation
        # stores hold CURRENT rows only, so a cell can never span two versions.
        mixed_cells = {
            cell: sorted(versions)
            for cell, versions in cell_versions.items()
            if len(versions) > 1
        }
        if mixed_cells:
            details = "; ".join(
                f"{agent}/{task}: {','.join(versions)}"
                for (agent, task), versions in sorted(mixed_cells.items())
            )
            raise ValueError(f"refusing to pool multiple task versions: {details}")

        # Synthetic bookends only in the full store (report_combined parity).
        for task_id in task_ids:
            version = current_versions[task_id]
            _add_synthetic_baseline(full, ORACLE, task_id, version, passed=True)
            _add_synthetic_baseline(full, NOOP, task_id, version, passed=False)

        # Per-task version accounting (in scope): evaluated versions keep their
        # meaning, plus how much of it is current vs historical.
        for task_id in task_ids:
            task_runs = [r for r in loaded_runs if r.record.task_id == task_id]
            stored = {r.record.task_version for r in task_runs}
            tasks_meta[task_id]["evaluated_versions"] = sorted(
                stored_task_versions.get(task_id, set())
            )
            tasks_meta[task_id]["models_with_current_evidence"] = len(
                {r.record.agent for r in task_runs if r.is_current}
            )
            tasks_meta[task_id]["current_runs"] = sum(1 for r in task_runs if r.is_current)
            tasks_meta[task_id]["historical_runs"] = sum(
                1 for r in task_runs if not r.is_current
            )
            tasks_meta[task_id]["historical_versions"] = sorted(
                stored - {current_versions[task_id]},
                key=version_sort_key,
                reverse=True,
            )

        current_models = sorted(a for a, ev in agent_evidence.items() if ev.current_runs)
        loaded = LoadedStores(
            real=real,
            full=full,
            real_counts={
                agent: (ev.current_runs, len(ev.current_tasks))
                for agent, ev in agent_evidence.items()
            },
            task_ids=task_ids,
            tasks_meta=tasks_meta,
            current_versions=current_versions,
            task_domains=task_domains,
            models=models,
            synthetic_agents=[ORACLE, NOOP],
            observability=disk_summary,
            agent_observability=disk_agent_summaries,
            scope=scope,
            runs=loaded_runs,
            agent_evidence=agent_evidence,
            excluded={
                "synthetic_runs": excluded_synthetic_runs,
                "synthetic_models": sorted(excluded_synthetic_models),
                "provenance_conflict_runs": excluded_conflict_runs,
                # runs of a class the selected scope does not include (and that
                # are neither synthetic nor a conflict): counted, never hidden
                "out_of_scope_runs": excluded_out_of_scope_runs,
                # runs rows the loader cannot see (no run_scores row of the
                # pinned formula, or no diffs row): visible, never silently lost
                "unaccounted_runs": max(0, total_runs_in_db - projected_runs),
            },
            excluded_cells=excluded_cells,
            stored_cell_versions=stored_cell_versions,
            stored_task_versions=stored_task_versions,
            current_models=current_models,
            historical_only_models=sorted(set(models) - set(current_models)),
        )
        aggregate_scope.pop_all()
        return loaded
    except Exception:
        aggregate_scope.close()
        raise
