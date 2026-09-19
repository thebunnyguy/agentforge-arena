"""Render the combined report from persisted evaluation data.

Every real model result comes directly from the selected working database.
The only generated rows are the two explicitly named synthetic bookends: a
reference oracle that always passes and a no-edit baseline that always fails.

    python3 examples/report_combined.py
"""

from __future__ import annotations

import json
import sys
from contextlib import ExitStack
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [
    str(_ROOT),
    str(_ROOT / "kernel"),
    str(_ROOT / "runner"),
]

import afa_runner as afa  # noqa: E402
from afa_kernel.types import RunScore, RunStatus  # noqa: E402
from afa_runner.pipeline import RunRecord  # noqa: E402

N = 5
# The app-compatible default is a writable working copy; the committed evidence
# database remains an explicit seed/source, not the implicit runtime target.
DB = _ROOT / "reports" / "app.sqlite"
MANIFEST = _ROOT / "tasks" / "manifest.json"
OUTPUT = _ROOT / "reports" / "leaderboard.html"
ORACLE = "oracle (synthetic baseline)"
NOOP = "noop (synthetic baseline)"


def _selected_db_path(db_path: str | Path | None) -> Path:
    """Resolve an existing report DB without creating or substituting one."""
    from afa_api import db as app_db

    selected = app_db.resolve_db_path(db_path)
    if not selected.is_file():
        raise FileNotFoundError(f"report database unavailable: {selected}")
    return selected


def _current_task_version(item: dict, manifest_path: str | Path) -> str:
    """Read the current task version, with a manifest-only test fallback."""
    if "version" in item:
        return str(item["version"])
    task_dir = item.get("dir")
    if task_dir:
        candidate = Path(manifest_path).resolve().parent.parent / task_dir / "task.json"
        if candidate.is_file():
            return str(json.loads(candidate.read_text()).get("version", "1.0.0"))
    return "1.0.0"


def _baseline_score(passed: bool, *, no_edit: bool = False) -> RunScore:
    if passed:
        return RunScore(RunStatus.VALID, 1, 1.0, 1.0, {}, 1.0, True, False)
    return RunScore(
        RunStatus.VALID,
        0 if no_edit else 1,
        0.0,
        1.0,
        {},
        0.0,
        False,
        False,
    )


def _add_synthetic_baseline(
    store: afa.SqliteRunStore,
    agent: str,
    task: str,
    version: str,
    *,
    passed: bool,
) -> None:
    """Add one clearly labeled synthetic baseline cell; never used for models."""
    for idx in range(N):
        no_edit = not passed
        store.save_run(
            RunRecord(
                task_id=task,
                task_version=version,
                agent=agent,
                idx=idx,
                status=RunStatus.VALID,
                score=_baseline_score(passed, no_edit=no_edit),
                files_changed=0 if no_edit else 1,
                lines_added=0 if no_edit else 6,
                lines_removed=0,
                transcript_hash=f"sha256:synthetic-baseline-{agent}-{task}-{idx}",
                duration_ms=0,
            )
        )


def build_report(
    db_path: str | Path | None = None,
    manifest_path: str | Path = MANIFEST,
    evidence_scope: str | None = None,
) -> tuple[str, afa.SqliteRunStore, dict[str, tuple[int, int]]]:
    """Build HTML plus its in-memory aggregate store from persisted DB rows.

    The aggregates are the CURRENT benchmark: only runs at each task's current
    version (and in the requested provenance scope; default excludes synthetic
    mock evidence) enter the store. Historical-version runs are preserved in the
    database, counted in the subtitle, and never pooled. The store can therefore
    never span two versions of one cell; the refusal is kept as an invariant.
    """
    from afa_api import db as app_db
    from afa_api import evidence

    scope = evidence.normalize_scope(evidence_scope)
    in_scope = evidence.SCOPES[scope]
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
            "current_version": current_versions[item["id"]],
        }
        for item in manifest
    }

    selected_db = _selected_db_path(db_path)
    aggregate_scope = ExitStack()
    try:
        # Register the returned in-memory store immediately. pop_all() below
        # transfers it to the successful caller; every failure closes it here.
        store = afa.SqliteRunStore(":memory:")
        aggregate_scope.callback(store.close)
        disk: afa.SqliteRunStore | None = None
        real_counts: dict[str, tuple[int, int]] = {}
        evaluated_versions: dict[str, set[str]] = {
            task_id: set() for task_id in task_ids
        }
        cell_versions: dict[tuple[str, str], set[str]] = {}
        historical_runs = 0
        excluded_runs = 0
        try:
            disk = afa.SqliteRunStore.open_readonly(selected_db)
            # one read snapshot for provenance and runs (see afa_api.store_load)
            disk.begin_read_snapshot()
            provenance = evidence.read_provenance(disk.connection)
            observability = disk.summary()
            models: list[str] = []
            for agent in disk.agents():
                everything = disk.load_runs(agent=agent)
                scoped = [
                    record
                    for record in everything
                    if agent not in evidence.RESERVED_AGENT_NAMES
                    and provenance.get(record.run_id, evidence.UNATTESTED_PROVENANCE)
                    .evidence_class in in_scope
                ]
                excluded_runs += len(everything) - len(scoped)
                if not scoped:
                    continue
                models.append(agent)
                current = [
                    record
                    for record in scoped
                    if record.task_version == current_versions.get(record.task_id)
                ]
                # CURRENT in-scope counts (0/0 for a historical-only model).
                real_counts[agent] = (len(current), len({r.task_id for r in current}))
                for record in scoped:
                    evaluated_versions.setdefault(record.task_id, set()).add(
                        record.task_version
                    )
                    if record.task_version != current_versions.get(record.task_id):
                        historical_runs += 1
                        continue
                    cell_versions.setdefault((agent, record.task_id), set()).add(
                        record.task_version
                    )
                    store.save_run(record)
            agent_observability = {agent: disk.summary(agent) for agent in models}
        finally:
            if disk is not None:
                disk.close()

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

        # These are deterministic comparison bookends, not measured model runs.
        for task_id in task_ids:
            version = current_versions[task_id]
            _add_synthetic_baseline(store, ORACLE, task_id, version, passed=True)
            _add_synthetic_baseline(store, NOOP, task_id, version, passed=False)

        persisted = "; ".join(
            f"{agent} {n_runs} runs/{n_tasks} tasks"
            for agent, (n_runs, n_tasks) in real_counts.items()
        )
        mismatches = []
        for task_id in task_ids:
            stored = evaluated_versions.get(task_id, set())
            tasks_meta[task_id]["evaluated_versions"] = sorted(stored)
            if stored and stored != {current_versions[task_id]}:
                mismatches.append(
                    f"{task_id} evaluated v{','.join(sorted(stored))} → current "
                    f"v{current_versions[task_id]}"
                )
        version_notice = (
            " Current benchmark evidence only: "
            f"{historical_runs} historical-version run(s) are excluded from these "
            "aggregates (never pooled with current versions) and remain in the "
            "database. Awaiting reevaluation: " + "; ".join(mismatches) + "."
            if historical_runs
            else ""
        )
        scope_meaning = {
            "benchmark": "real + legacy evidence; mock/synthetic evaluations excluded",
            "real": "runs with a recorded real provider only",
            "synthetic": "mock/synthetic evaluations only - NOT benchmark evidence",
            "all": "every run including mock/synthetic and unverified provenance - "
                   "NOT benchmark evidence",
        }[scope]
        scope_notice = f" Evidence scope '{scope}' ({scope_meaning})." + (
            f" {excluded_runs} run(s) outside this scope are excluded."
            if excluded_runs
            else ""
        )
        subtitle = (
            f"Persisted DB data only: {persisted}. "
            "Oracle and noop are explicitly synthetic baselines."
            + version_notice
            + scope_notice
        )
        html = afa.render_report(
            store,
            tasks_meta,
            title=f"AgentForge Arena — {len(models)}-Model Report ({len(task_ids)}-task pack)",
            subtitle=subtitle,
            observability=observability,
            agent_observability=agent_observability,
        )
        result = (html, store, real_counts)
        aggregate_scope.pop_all()
        return result
    except Exception:
        aggregate_scope.close()
        raise


def main() -> None:
    # Standalone CLI first use may bootstrap the default working copy. API and
    # library callers must bind an existing DB and never recover by seeding.
    from afa_api import db as app_db

    app_db.ensure_working_db()
    html, store, real_counts = build_report()
    try:
        print("LEADERBOARD (persisted model runs + labeled synthetic baselines):")
        print(afa.format_leaderboard(afa.leaderboard(store)))

        manifest = json.loads(MANIFEST.read_text())
        task_domains = {
            item["id"]: [tuple(domain) for domain in item.get("domains", [])]
            for item in manifest
        }
        domains = sorted({domain for tags in task_domains.values() for domain, _ in tags})
        print("\nPER-MODEL DOMAIN PROFILE (pass rate; '--' = insufficient):")
        print(f"{'model':<22}" + "".join(f"{domain[:9]:>11}" for domain in domains))
        for agent in real_counts:
            profile = {
                score.domain: score
                for score in afa.domain_profile(store, agent, task_domains)
            }
            row = f"{agent:<22}"
            for domain in domains:
                score = profile.get(domain)
                cell = (
                    f"{score.pooled_pass_rate * 100:.0f}%"
                    if score and score.displayable
                    else "--"
                )
                row += f"{cell:>11}"
            print(row)

        OUTPUT.parent.mkdir(parents=True, exist_ok=True)
        OUTPUT.write_text(html)
        print(f"\nwrote {OUTPUT}")
    finally:
        store.close()


if __name__ == "__main__":
    main()
