"""Resilient single-model evaluation: run one model across the whole task pack,
saving EACH run to a SQLite file the instant it finishes. Survivable and
resumable — if the job is stopped, re-running it picks up exactly where it left
off (already-completed runs are skipped). Progress is flushed live so you can
watch it work.

    python3 examples/eval_persist.py <model> [n=5] [db=reports/runs.sqlite]

Run it once per model. Then render the combined report with report_combined.py.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(_ROOT / "kernel"), str(_ROOT / "runner")]

import afa_runner as afa  # noqa: E402
from afa_kernel.types import RunStatus  # noqa: E402


def completed_indices(store, *, task_id: str, task_version: str, agent: str) -> set[int]:
    """Resume only runs from the exact immutable task version being evaluated."""
    return {
        record.idx
        for record in store.load_runs(task_id=task_id, agent=agent)
        if record.task_version == task_version
    }


def main() -> None:
    model = sys.argv[1]
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 5
    db = sys.argv[3] if len(sys.argv) > 3 else str(_ROOT / "reports" / "runs.sqlite")
    Path(db).parent.mkdir(parents=True, exist_ok=True)

    manifest = json.loads((_ROOT / "tasks" / "manifest.json").read_text())
    task_ids = [m["id"] for m in manifest]
    # Optional restriction to a comma-separated subset (e.g. only the new tasks).
    import os
    _filter = os.environ.get("AFA_TASK_FILTER", "").strip()
    if _filter:
        keep = {x.strip() for x in _filter.split(",") if x.strip()}
        task_ids = [t for t in task_ids if t in keep]

    store = afa.SqliteRunStore(db)
    agent = afa.OllamaAgent(name=model, model=model, temperature=0.8, base_seed=42)
    sandbox = afa.LocalSandbox()
    tasks = {task_id: afa.load_task(_ROOT / "tasks" / task_id) for task_id in task_ids}

    # Resume: which (task version, idx) are already recorded for this model.
    done: dict[str, set[int]] = {}
    for t in task_ids:
        done[t] = completed_indices(
            store,
            task_id=t,
            task_version=tasks[t].version,
            agent=model,
        )
    total = len(task_ids) * n
    completed = sum(len(s) for s in done.values())
    print(f"{model}: {completed}/{total} runs already saved; resuming", flush=True)

    for t in task_ids:
        task = tasks[t]
        for i in range(n):
            if i in done[t]:
                continue
            rec = afa.run_once(agent, task, sandbox=sandbox, idx=i)
            # Persist the score, full patch, and per-test outcomes atomically.
            store.save_run(rec, report=rec.grade_report)
            completed += 1
            if rec.status is RunStatus.INFRA_FAILURE:
                mark = "VOID(infra)"
            elif rec.score.functional_pass:
                mark = "PASS"
            else:
                mark = "fail"
            print(f"  [{completed}/{total}] {t} run{i}: {mark}", flush=True)

    # Final per-model summary from what's now on disk.
    c = nv = 0
    for t in task_ids:
        for r in store.load_runs(task_id=t, agent=model):
            if r.task_version != tasks[t].version:
                continue
            if r.status is RunStatus.INFRA_FAILURE:
                continue
            nv += 1
            c += int(r.score.functional_pass)
    rate = (c / nv) if nv else 0.0
    print(f"DONE {model}: {c}/{nv} passed  (p_hat={rate:.3f})", flush=True)
    store.close()


if __name__ == "__main__":
    main()
