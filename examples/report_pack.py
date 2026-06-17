"""Generate the visual HTML report for the task pack.

By default this reconstructs the real recorded results of the clean n=5 run
(qwen2.5-coder:7b vs llama3.2, DEVLOG Phase 24) into a store and renders the
report — instant and offline, no model re-run. The leaderboard, per-task matrix,
and domain profile are exact (they only need pass counts); per-run scores are
synthesized as 1.0 (pass) / 0.0 (fail), which is faithful for these binary tasks.

    python examples/report_pack.py          # -> reports/leaderboard.html

To regenerate from a fresh live run instead, run examples/eval_pack.py (and
wire it to render_report) — the renderer takes any RunStore.
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

# Real recorded pass counts (out of N=5) from the clean full pack run, Phase 24.
RESULTS: dict[str, dict[str, int]] = {
    "qwen2.5-coder:7b": {
        "fix-binary-search": 5, "fix-list-dedup": 5, "fix-roman-numerals": 3,
        "implement-lru-cache": 5, "merge-intervals": 4, "async-gather-bounded": 2,
        "fix-path-traversal": 0, "refactor-order-validation": 5, "toposort": 0,
        "expression-evaluator": 0,
    },
    "llama3.2:latest": {
        "fix-binary-search": 1, "fix-list-dedup": 3, "fix-roman-numerals": 0,
        "implement-lru-cache": 1, "merge-intervals": 4, "async-gather-bounded": 0,
        "fix-path-traversal": 0, "refactor-order-validation": 0, "toposort": 0,
        "expression-evaluator": 0,
    },
    "oracle (reference)": {},   # filled below: all pass
    "noop": {},                 # filled below: all fail (no edit)
}


def _score(passed: bool, *, no_edit: bool = False) -> RunScore:
    if passed:
        return RunScore(RunStatus.VALID, 1, 1.0, 1.0, {}, 1.0, True, False)
    # A failure: either a no-edit (gate fails, no diff) or a wrong-fix.
    g = 0 if no_edit else 1
    return RunScore(RunStatus.VALID, g, 0.0, 1.0, {}, 0.0, False, False)


def _records(agent: str, task: str, version: str, c: int, no_edit_fail: bool) -> list[RunRecord]:
    out = []
    for i in range(N):
        passed = i < c
        out.append(RunRecord(
            task_id=task, task_version=version, agent=agent, idx=i,
            status=RunStatus.VALID, score=_score(passed, no_edit=(not passed and no_edit_fail)),
            files_changed=(1 if passed or not no_edit_fail else 0),
            lines_added=(6 if passed else 0), lines_removed=0,
            transcript_hash=f"sha256:recon-{agent}-{task}-{i}", duration_ms=2000,
        ))
    return out


def main() -> None:
    manifest = json.loads((_ROOT / "tasks" / "manifest.json").read_text())
    meta = {m["id"]: m for m in manifest}
    tasks_meta = {
        m["id"]: {"difficulty": m.get("manual_difficulty", 0),
                  "domains": [tuple(d) for d in m.get("domains", [])]}
        for m in manifest
    }
    task_ids = list(meta)

    # Fill the mock baselines across every task.
    RESULTS["oracle (reference)"] = {t: N for t in task_ids}
    RESULTS["noop"] = {t: 0 for t in task_ids}

    store = afa.SqliteRunStore(":memory:")
    for agent, per_task in RESULTS.items():
        no_edit = agent == "noop"
        for task in task_ids:
            c = per_task.get(task, 0)
            version = meta[task].get("version", "1.0.0")
            for rec in _records(agent, task, version, c, no_edit):
                store.save_run(rec)

    html = afa.render_report(
        store, tasks_meta,
        title="AgentForge Arena — Task Pack Report",
        subtitle="qwen2.5-coder:7b vs llama3.2 · 10 tasks · n=5 · reconstructed from the clean Phase-24 run",
    )
    out_dir = _ROOT / "reports"
    out_dir.mkdir(exist_ok=True)
    out_path = out_dir / "leaderboard.html"
    out_path.write_text(html)
    store.close()
    print(f"wrote {out_path}  ({len(html)} bytes)")
    print(f"open it with:  open '{out_path}'")


if __name__ == "__main__":
    main()
