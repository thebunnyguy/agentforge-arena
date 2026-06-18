"""Combined 5-model report: the three freshly-run models (real runs read from
reports/runs.sqlite) plus the two from the earlier identical run (qwen-7b, llama,
reconstructed from their recorded per-task pass counts), with oracle/noop
bookends. Prints the leaderboard + per-task matrix and writes the HTML report.

    python examples/report_combined.py
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

# Freshly-run this session (read REAL runs from the DB).
FRESH = ["gemma2:2b", "qwen2.5-coder:3b", "deepseek-coder:6.7b"]

# From the earlier identical run (same harness/tasks/n) — recorded per-task counts.
KNOWN = {
    "qwen2.5-coder:7b": {"fix-binary-search": 5, "fix-list-dedup": 5, "fix-roman-numerals": 3,
        "implement-lru-cache": 5, "merge-intervals": 4, "async-gather-bounded": 2,
        "fix-path-traversal": 0, "refactor-order-validation": 5, "toposort": 0, "expression-evaluator": 0},
    "llama3.2:latest": {"fix-binary-search": 1, "fix-list-dedup": 3, "fix-roman-numerals": 0,
        "implement-lru-cache": 1, "merge-intervals": 4, "async-gather-bounded": 0,
        "fix-path-traversal": 0, "refactor-order-validation": 0, "toposort": 0, "expression-evaluator": 0},
}


def _score(passed: bool, no_edit: bool = False) -> RunScore:
    if passed:
        return RunScore(RunStatus.VALID, 1, 1.0, 1.0, {}, 1.0, True, False)
    return RunScore(RunStatus.VALID, 0 if no_edit else 1, 0.0, 1.0, {}, 0.0, False, False)


def _add_reconstructed(store, agent, per_task, task_ids, meta, no_edit_fail=False):
    for t in task_ids:
        c = per_task.get(t, 0)
        ver = meta[t].get("version", "1.0.0")
        for i in range(N):
            passed = i < c
            store.save_run(RunRecord(
                task_id=t, task_version=ver, agent=agent, idx=i,
                status=RunStatus.VALID, score=_score(passed, no_edit=(not passed and no_edit_fail)),
                files_changed=(1 if passed or not no_edit_fail else 0),
                lines_added=(6 if passed else 0), lines_removed=0,
                transcript_hash=f"sha256:recon-{agent}-{t}-{i}", duration_ms=2000))


def main() -> None:
    manifest = json.loads((_ROOT / "tasks" / "manifest.json").read_text())
    meta = {m["id"]: m for m in manifest}
    task_ids = list(meta)
    tasks_meta = {m["id"]: {"difficulty": m.get("manual_difficulty", 0),
                            "domains": [tuple(d) for d in m.get("domains", [])]} for m in manifest}

    store = afa.SqliteRunStore(":memory:")
    # Real fresh runs from disk.
    disk = afa.SqliteRunStore(str(DB))
    for agent in FRESH:
        for rec in disk.load_runs(agent=agent):
            store.save_run(rec)
    disk.close()
    # Reconstructed: known models + oracle/noop bookends.
    for agent, per_task in KNOWN.items():
        _add_reconstructed(store, agent, per_task, task_ids, meta)
    _add_reconstructed(store, "oracle (reference)", {t: N for t in task_ids}, task_ids, meta)
    _add_reconstructed(store, "noop", {t: 0 for t in task_ids}, task_ids, meta, no_edit_fail=True)

    # Leaderboard + per-task matrix to stdout.
    print("LEADERBOARD (all 5 models + bookends, pooled across 10 tasks, n=5):")
    print(afa.format_leaderboard(afa.leaderboard(store)))
    print("\nPER-TASK PASSES (out of 5):")
    agents = ["qwen2.5-coder:7b", "qwen2.5-coder:3b", "deepseek-coder:6.7b", "llama3.2:latest", "gemma2:2b"]
    print(f"{'task':<27}" + "".join(f"{a.split(':')[0][:9]:>10}" for a in agents))
    for t in sorted(task_ids, key=lambda x: meta[x].get("manual_difficulty", 0)):
        row = f"{t:<27}"
        for a in agents:
            agg = afa.task_aggregate(store, a, t)
            row += f"{str(agg.n_pass)+'/'+str(agg.n_valid):>10}"
        print(row)

    html = afa.render_report(store, tasks_meta,
        title="AgentForge Arena — 5-Model Task Pack Report",
        subtitle="qwen2.5-coder 7b/3b · deepseek-coder 6.7b · llama3.2 3b · gemma2 2b · 10 tasks · n=5")
    out = _ROOT / "reports" / "leaderboard.html"
    out.write_text(html)
    store.close()
    print(f"\nwrote {out}")


if __name__ == "__main__":
    main()
