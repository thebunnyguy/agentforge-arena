"""Pack-level audit: run the engine across every task in tasks/manifest.json
and produce an aggregate summary (mission §21).

Grading is subprocess-bound (each grade shells out to `python -m pytest` via
LocalSandbox and waits on it, releasing the GIL) with independent temp
directories per call, so a ThreadPoolExecutor across TASKS is safe and cuts
a full-pack FULL audit's wall clock several-fold without any shared mutable
state between workers — each worker gets its own LocalSandbox instance.
"""

from __future__ import annotations

import json
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

from afa_runner.sandbox import LocalSandbox
from afa_runner.task import load_task

from .audit import run_audit
from .model import (
    ENGINE_VERSION,
    SCHEMA_VERSION,
    AuditMode,
    BenchmarkIntegrityReport,
    Finding,
    PackAuditSummary,
)


def _load_manifest_ids(tasks_root: Path) -> list[str]:
    manifest_path = tasks_root / "manifest.json"
    entries = json.loads(manifest_path.read_text())
    return [e["id"] for e in entries]


def _task_dir_for_id(tasks_root: Path, task_id: str) -> Path:
    return tasks_root / task_id


def audit_pack(
    *,
    tasks_root: str | Path = "tasks",
    task_ids: list[str] | None = None,
    mode: AuditMode = AuditMode.QUICK,
    workers: int = 4,
    force_mutation: bool = False,
    max_mutants: int = 60,
) -> PackAuditSummary:
    start = time.monotonic()
    created_at = datetime.now(timezone.utc).isoformat()
    tasks_root = Path(tasks_root)
    ids = task_ids or _load_manifest_ids(tasks_root)

    def _audit_one(task_id: str) -> BenchmarkIntegrityReport:
        task = load_task(_task_dir_for_id(tasks_root, task_id))
        sandbox = LocalSandbox()
        return run_audit(
            task,
            mode=mode,
            sandbox=sandbox,
            force_mutation=force_mutation,
            max_mutants=max_mutants,
        )

    reports: list[BenchmarkIntegrityReport] = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_audit_one, tid): tid for tid in ids}
        for future in as_completed(futures):
            reports.append(future.result())

    status_counts = Counter(r.status.value for r in reports)

    finding_counts: dict[str, int] = Counter()
    finding_examples: dict[str, Finding] = {}
    for r in reports:
        for f in r.findings:
            finding_counts[f.finding_id] += 1
            finding_examples.setdefault(f.finding_id, f)
    common_findings = tuple(
        finding_examples[fid]
        for fid, count in sorted(finding_counts.items(), key=lambda kv: -kv[1])
        if count >= 2
    )

    duration_ms = int((time.monotonic() - start) * 1000)
    return PackAuditSummary(
        schema_version=SCHEMA_VERSION,
        engine_version=ENGINE_VERSION,
        mode=mode,
        created_at=created_at,
        reports=tuple(sorted(reports, key=lambda r: r.task_id)),
        status_counts=dict(status_counts),
        common_findings=common_findings,
        duration_ms=duration_ms,
    )
