"""Resilient single-model evaluation: run one model across the whole task pack,
saving EACH run to a SQLite file the instant it finishes. Survivable and
resumable — if the job is stopped, re-running it picks up exactly where it left
off (already-completed runs are skipped). Progress is flushed live so you can
watch it work.

    python3 examples/eval_persist.py <model> [n=5] [db=<working DB>]

Run it once per model. Then render the combined report with report_combined.py.

The target is a WORKING database (default: the app's runtime DB, reports/app.sqlite,
seeded from the committed evidence on first use). The committed evidence database
reports/runs.sqlite is immutable and is refused. Every run is stamped
backend_kind="ollama" (this script always drives an OllamaAgent), so it is
recorded as real, provider-attested evidence.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(_ROOT), str(_ROOT / "kernel"), str(_ROOT / "runner")]

import afa_runner as afa  # noqa: E402
from afa_kernel.types import RunStatus  # noqa: E402


def benchmark_runs(store, *, task_id: str, agent: str):
    """The agent's runs that count as benchmark evidence: real or legacy
    provenance. Mock (synthetic) and provenance-conflicting runs stored under the
    same model name are ignored, so they can never make a resume skip real work or
    inflate the final summary."""
    from afa_api import evidence  # local: keeps the script importable standalone

    provenance = evidence.read_provenance(store.connection)
    allowed = evidence.SCOPES["benchmark"]
    return [
        record
        for record in store.load_runs(task_id=task_id, agent=agent)
        if provenance.get(record.run_id, evidence.UNATTESTED_PROVENANCE).evidence_class
        in allowed
    ]


def completed_indices(store, *, task_id: str, task_version: str, agent: str) -> set[int]:
    """Resume only benchmark-evidence runs from the exact immutable task version
    being evaluated."""
    return {
        record.idx
        for record in benchmark_runs(store, task_id=task_id, agent=agent)
        if record.task_version == task_version
    }


def main() -> None:
    model = sys.argv[1]
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 5
    from afa_api import db as app_db

    # Refuses the immutable evidence DB (and any alias of it); bootstraps a
    # missing working DB from the evidence the same way the app does.
    target = app_db.assert_writable_runtime_path(
        app_db.resolve_db_path(sys.argv[3] if len(sys.argv) > 3 else None)
    )
    app_db.ensure_working_db(target)
    Path(target).parent.mkdir(parents=True, exist_ok=True)
    _conn = app_db.connect(target)
    try:
        app_db.migrate(_conn)  # adds runs.backend_kind etc. to an older working DB
    finally:
        _conn.close()
    db = str(target)

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
            store.save_run(rec, report=rec.grade_report, backend_kind="ollama")
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
        for r in benchmark_runs(store, task_id=t, agent=model):
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
