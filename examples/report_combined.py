"""Combined report across all 5 models and all 24 tasks.

DB-first: read every real run from reports/runs.sqlite (all 5 models on the new
tasks; gemma2/qwen-3b/deepseek also have the original 10). Then gap-fill only
what isn't in the DB: qwen-7b/llama's original-10 results (from the earlier
identical run, recorded per-task counts) and the oracle/noop bookends. Prints
the leaderboard, per-task matrix, and per-model domain profile; writes the HTML.

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
MODELS = ["qwen2.5-coder:7b", "qwen2.5-coder:3b", "deepseek-coder:6.7b",
          "llama3.2:latest", "gemma2:2b"]

# qwen-7b / llama original-10 results (earlier identical run) — used ONLY to
# gap-fill tasks those two models have no real DB runs for.
KNOWN_OLD = {
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


def _add(store, agent, task, ver, c, no_edit_fail=False):
    for i in range(N):
        passed = i < c
        store.save_run(RunRecord(
            task_id=task, task_version=ver, agent=agent, idx=i,
            status=RunStatus.VALID, score=_score(passed, no_edit=(not passed and no_edit_fail)),
            files_changed=(1 if passed or not no_edit_fail else 0),
            lines_added=(6 if passed else 0), lines_removed=0,
            transcript_hash=f"sha256:recon-{agent}-{task}-{i}", duration_ms=2000))


def main() -> None:
    manifest = json.loads((_ROOT / "tasks" / "manifest.json").read_text())
    meta = {m["id"]: m for m in manifest}
    task_ids = list(meta)
    tasks_meta = {m["id"]: {"difficulty": m.get("manual_difficulty", 0),
                            "domains": [tuple(d) for d in m.get("domains", [])]} for m in manifest}

    store = afa.SqliteRunStore(":memory:")
    disk = afa.SqliteRunStore(str(DB))
    present: dict[str, set[str]] = {}
    for agent in MODELS:
        recs = disk.load_runs(agent=agent)
        for rec in recs:
            store.save_run(rec)
        present[agent] = {r.task_id for r in recs}
    disk.close()

    # Gap-fill qwen-7b / llama original-10 where the DB has no real runs.
    for agent, per_task in KNOWN_OLD.items():
        for t, c in per_task.items():
            if t not in present.get(agent, set()):
                _add(store, agent, t, meta[t].get("version", "1.0.0"), c)

    # Oracle / noop bookends across all tasks.
    for t in task_ids:
        ver = meta[t].get("version", "1.0.0")
        _add(store, "oracle (reference)", t, ver, N)
        _add(store, "noop", t, ver, 0, no_edit_fail=True)

    print("LEADERBOARD (all 24 tasks, pooled, ranked by Wilson LCB):")
    print(afa.format_leaderboard(afa.leaderboard(store)))

    print("\nPER-MODEL DOMAIN PROFILE (pass rate; '--' = insufficient):")
    task_domains = {t: tasks_meta[t]["domains"] for t in tasks_meta}
    domains = sorted({d for tags in task_domains.values() for d, _w in tags})
    print(f"{'model':<22}" + "".join(f"{d[:9]:>11}" for d in domains))
    for agent in MODELS:
        prof = {ds.domain: ds for ds in afa.domain_profile(store, agent, task_domains)}
        row = f"{agent:<22}"
        for d in domains:
            ds = prof.get(d)
            cell = f"{ds.pooled_pass_rate*100:.0f}%" if (ds and ds.displayable) else "--"
            row += f"{cell:>11}"
        print(row)

    html = afa.render_report(store, tasks_meta,
        title="AgentForge Arena — 5-Model Report (24 tasks, all domains)",
        subtitle="qwen2.5-coder 7b/3b · deepseek-coder 6.7b · llama3.2 3b · gemma2 2b · 24 tasks · n=5")
    out = _ROOT / "reports" / "leaderboard.html"
    out.write_text(html)
    store.close()
    print(f"\nwrote {out}")


if __name__ == "__main__":
    main()
