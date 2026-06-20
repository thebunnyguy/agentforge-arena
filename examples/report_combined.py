"""Render the combined report from persisted evaluation data.

Every model result comes directly from ``reports/runs.sqlite``. The only
generated rows are the two explicitly named synthetic bookends: a reference
oracle that always passes and a no-edit baseline that always fails.

    python3 examples/report_combined.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(_ROOT / "kernel"), str(_ROOT / "runner")]

import afa_runner as afa  # noqa: E402
from afa_kernel.types import RunScore, RunStatus  # noqa: E402
from afa_runner.pipeline import RunRecord  # noqa: E402

N = 5
DB = _ROOT / "reports" / "runs.sqlite"
MANIFEST = _ROOT / "tasks" / "manifest.json"
OUTPUT = _ROOT / "reports" / "leaderboard.html"
MODELS = [
    "qwen2.5-coder:7b",
    "qwen2.5-coder:3b",
    "deepseek-coder:6.7b",
    "llama3.2:latest",
    "gemma2:2b",
]
ORACLE = "oracle (synthetic baseline)"
NOOP = "noop (synthetic baseline)"


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
    db_path: str | Path = DB,
    manifest_path: str | Path = MANIFEST,
) -> tuple[str, afa.SqliteRunStore, dict[str, tuple[int, int]]]:
    """Build HTML plus its in-memory aggregate store from persisted DB rows."""
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

    store = afa.SqliteRunStore(":memory:")
    disk = afa.SqliteRunStore(str(db_path))
    real_counts: dict[str, tuple[int, int]] = {}
    evaluated_versions: dict[str, set[str]] = {task_id: set() for task_id in task_ids}
    cell_versions: dict[tuple[str, str], set[str]] = {}
    try:
        observability = disk.summary()
        agent_observability = {agent: disk.summary(agent) for agent in MODELS}
        for agent in MODELS:
            records = disk.load_runs(agent=agent)
            real_counts[agent] = (len(records), len({record.task_id for record in records}))
            for record in records:
                evaluated_versions.setdefault(record.task_id, set()).add(record.task_version)
                cell_versions.setdefault((agent, record.task_id), set()).add(
                    record.task_version
                )
                store.save_run(record)
    finally:
        disk.close()

    mixed_cells = {
        cell: sorted(versions)
        for cell, versions in cell_versions.items()
        if len(versions) > 1
    }
    if mixed_cells:
        store.close()
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
        " Strengthened task versions awaiting reevaluation: "
        + "; ".join(mismatches)
        + ". Leaderboard values remain frozen to the stored task versions."
        if mismatches
        else ""
    )
    subtitle = (
        f"Persisted DB data only: {persisted}. "
        "Oracle and noop are explicitly synthetic baselines."
        + version_notice
    )
    html = afa.render_report(
        store,
        tasks_meta,
        title=f"AgentForge Arena — 5-Model Report ({len(task_ids)}-task pack)",
        subtitle=subtitle,
        observability=observability,
        agent_observability=agent_observability,
    )
    return html, store, real_counts


def main() -> None:
    html, store, _real_counts = build_report()
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
        for agent in MODELS:
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
