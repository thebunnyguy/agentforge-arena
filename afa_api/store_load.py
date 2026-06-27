"""Two-store load + mixed-version refusal + synthetic baselines.

This reuses the exact sequence from ``examples/report_combined.py`` so the app's
aggregation store matches the canonical report:

  1. an in-memory aggregation ``SqliteRunStore`` and an on-disk source store;
  2. copy every model's persisted runs into memory, tracking per-cell task
     versions;
  3. REFUSE (raise ValueError) if any (agent, task) cell pooled more than one
     task version — the caller must surface this, never swallow it;
  4. add the two clearly-labeled synthetic bookends (oracle always-pass, noop
     always-fail), N=5 runs each, with deterministic baseline scores.

The read-only projection API exposes TWO stores:
  * ``real`` — persisted model runs only (no synthetic rows), for the honest
    captured/not-captured views;
  * ``full`` — real runs + synthetic baselines, matching report_combined, used
    only where the report path is being surfaced (rows marked synthetic).

``report_combined`` is imported and its constants/helpers reused verbatim where
possible; no scoring math is reimplemented here.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path

from .db import DB_PATH, MANIFEST_PATH, ROOT

# Ensure kernel + runner are importable (tests run with PYTHONPATH="kernel:runner",
# but the app may be imported with only the repo root on sys.path).
for _p in (ROOT / "kernel", ROOT / "runner", ROOT / "examples"):
    _s = str(_p)
    if _s not in sys.path:
        sys.path.insert(0, _s)

import afa_runner as afa  # noqa: E402

# Reuse the canonical report constants + helpers (do NOT reimplement).
from report_combined import (  # type: ignore  # noqa: E402
    MODELS,
    N,
    NOOP,
    ORACLE,
    _add_synthetic_baseline,
    _current_task_version,
)

SYNTHETIC_AGENTS = frozenset({ORACLE, NOOP})


@dataclass
class LoadedStores:
    """The loaded aggregation stores plus the manifest-derived metadata the
    projection layer needs. All numbers downstream come from the report fns over
    these stores; nothing here computes statistics."""

    real: afa.SqliteRunStore  # persisted model runs only
    full: afa.SqliteRunStore  # real runs + synthetic baselines (report_combined)
    real_counts: dict[str, tuple[int, int]]  # agent -> (n_runs, n_tasks)
    task_ids: list[str]  # manifest order
    tasks_meta: dict[str, dict]  # id -> {difficulty, domains, current_version, ...}
    current_versions: dict[str, str]
    task_domains: dict[str, list]  # id -> [(domain, weight), ...]
    models: list[str]
    synthetic_agents: list[str]

    def close(self) -> None:
        self.real.close()
        self.full.close()


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
    db_path: str | Path = DB_PATH,
    manifest_path: str | Path = MANIFEST_PATH,
) -> LoadedStores:
    """Load both stores following report_combined's sequence exactly.

    Raises ValueError on a mixed-version cell (refusal); the caller MUST surface
    it. The synthetic baselines are added only to ``full``.
    """
    (
        _manifest,
        current_versions,
        task_ids,
        tasks_meta,
        task_domains,
    ) = _build_manifest_meta(manifest_path)

    real = afa.SqliteRunStore(":memory:")
    full = afa.SqliteRunStore(":memory:")
    disk = afa.SqliteRunStore(str(db_path))
    real_counts: dict[str, tuple[int, int]] = {}
    evaluated_versions: dict[str, set[str]] = {tid: set() for tid in task_ids}
    cell_versions: dict[tuple[str, str], set[str]] = {}
    try:
        for agent in MODELS:
            records = disk.load_runs(agent=agent)
            real_counts[agent] = (
                len(records),
                len({record.task_id for record in records}),
            )
            for record in records:
                evaluated_versions.setdefault(record.task_id, set()).add(
                    record.task_version
                )
                cell_versions.setdefault((agent, record.task_id), set()).add(
                    record.task_version
                )
                real.save_run(record)
                full.save_run(record)
    finally:
        disk.close()

    # Mixed-version refusal — surface, never swallow.
    mixed_cells = {
        cell: sorted(versions)
        for cell, versions in cell_versions.items()
        if len(versions) > 1
    }
    if mixed_cells:
        real.close()
        full.close()
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

    # Attach evaluated-version provenance to each task meta (non-fatal notice
    # source used by build_meta).
    for task_id in task_ids:
        stored = evaluated_versions.get(task_id, set())
        tasks_meta[task_id]["evaluated_versions"] = sorted(stored)

    return LoadedStores(
        real=real,
        full=full,
        real_counts=real_counts,
        task_ids=task_ids,
        tasks_meta=tasks_meta,
        current_versions=current_versions,
        task_domains=task_domains,
        models=list(MODELS),
        synthetic_agents=[ORACLE, NOOP],
    )
