"""Evaluate one or more real, offline Ollama coding agents across the ENTIRE
AgentForge Arena task pack (tasks/manifest.json), with deterministic baselines
for ranking context.

For every task in the manifest this runs, at n attempts each:
  * each requested real OllamaAgent,
  * a per-task ORACLE (a MockAgent that overlays that task's reference solution),
  * a NOOP MockAgent (writes nothing — the empty-diff floor),
into a single in-memory SqliteRunStore, then prints:
  (a) a per-task pass-rate matrix (rows = tasks by manifest difficulty, cols =
      agents, cells = "c/n"),
  (b) the pooled leaderboard (afa_runner.leaderboard with no task_id => pooled
      across all tasks) rendered with format_leaderboard, and
  (c) the per-agent backend domain profile (afa_runner.domain_profile, with the
      task->domains map built from the manifest).

The oracle reads each task's reference/ directory generically (walking it and
mapping every file to its snapshot-relative path), so it works for any task in
the pack — not just fix-list-dedup.

Requires a running Ollama with the requested models pulled for the real agents:
    ollama serve &
    ollama pull llama3.2
(The oracle and noop are deterministic and need no Ollama.)

Run:
    python examples/eval_pack.py                       # n=5, model llama3.2:latest
    python examples/eval_pack.py 8                     # n=8
    python examples/eval_pack.py 8 qwen2.5-coder:7b,llama3.2:latest
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(_ROOT / "kernel"), str(_ROOT / "runner")]

import json  # noqa: E402

import afa_runner as afa  # noqa: E402

MANIFEST_PATH = _ROOT / "tasks" / "manifest.json"

# Default real model(s) to evaluate when none are given on argv.
DEFAULT_MODELS = "llama3.2:latest"


def _load_manifest() -> list[dict]:
    """Read the task pack manifest (JSON list of task entries)."""
    return json.loads(MANIFEST_PATH.read_text())


def _reference_writes(task: afa.Task) -> dict[str, str]:
    """Map every file in the task's reference/ dir to its snapshot-relative path
    and contents, so an oracle MockAgent reproduces the canonical fix for ANY
    task (the reference tree mirrors the snapshot layout, e.g.
    reference/listkit/dedup.py -> "listkit/dedup.py"). Generic: NOT hardcoded to
    any one module."""
    ref_root = task.reference_dir
    if ref_root is None:
        raise ValueError(f"task {task.id} has no reference_dir")
    writes: dict[str, str] = {}
    for src in sorted(Path(ref_root).rglob("*")):
        if not src.is_file():
            continue
        rel = src.relative_to(ref_root).as_posix()
        # Skip compiled/cached artifacts (e.g. __pycache__/*.pyc) — only the
        # source files belong in the reference overlay.
        if "__pycache__" in src.parts or src.suffix in (".pyc", ".pyo"):
            continue
        writes[rel] = src.read_text()
    return writes


def main() -> None:
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 5
    models_arg = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_MODELS
    model_ids = [m.strip() for m in models_arg.split(",") if m.strip()]

    manifest = _load_manifest()
    # Tasks in difficulty order (then id) for stable, readable matrix rows.
    manifest_sorted = sorted(
        manifest, key=lambda e: (e["manual_difficulty"], e["id"])
    )
    tasks = {e["id"]: afa.load_task(_ROOT / e["dir"]) for e in manifest}

    # task_id -> [(domain, weight), ...] for the domain profile (from manifest).
    task_domains = {
        e["id"]: [(dom, float(w)) for dom, w in e["domains"]] for e in manifest
    }

    sandbox = afa.LocalSandbox()
    store = afa.SqliteRunStore(":memory:")

    # Real agents (one per model id) + the deterministic baselines. The oracle is
    # PER TASK (its writes differ per task), so it is constructed inside the loop;
    # its agent name is shared ("oracle (reference)") so all its runs pool into a
    # single leaderboard/profile column.
    real_agents = [
        afa.OllamaAgent(name=mid, model=mid, temperature=0.8, base_seed=42)
        for mid in model_ids
    ]
    noop = afa.MockAgent(name="noop")
    ORACLE_NAME = "oracle (reference)"

    # Column order for the matrix/leaderboard display.
    agent_names = [a.name for a in real_agents] + [ORACLE_NAME, noop.name]

    print(
        f"Evaluating {len(model_ids)} real agent(s) across "
        f"{len(manifest)} tasks, n={n} each"
    )
    print("=" * 78)

    # pass_counts[task_id][agent_name] = number of functional passes.
    pass_counts: dict[str, dict[str, int]] = {
        tid: {name: 0 for name in agent_names} for tid in tasks
    }

    for entry in manifest_sorted:
        tid = entry["id"]
        task = tasks[tid]
        oracle = afa.MockAgent(name=ORACLE_NAME, writes=_reference_writes(task))
        # All agents (real + oracle + noop) attempt this task n times.
        for agent in [*real_agents, oracle, noop]:
            records = afa.run_group(agent, task, n, sandbox=sandbox)
            for rec in records:
                store.save_run(rec)
            pass_counts[tid][agent.name] = sum(
                1 for r in records if r.score.functional_pass
            )

    # ---- (a) Per-task pass-rate matrix (rows by difficulty, cells "c/n"). ----
    print("\n(a) Per-task pass-rate matrix (cells = passes/n):")
    id_w = max([len("task")] + [len(tid) for tid in tasks])
    col_w = {name: max(len(name), len(f"{n}/{n}")) for name in agent_names}
    header = "task".ljust(id_w) + "  " + "  ".join(
        name.rjust(col_w[name]) for name in agent_names
    )
    print("  " + header)
    print("  " + "-" * len(header))
    for entry in manifest_sorted:
        tid = entry["id"]
        cells = "  ".join(
            f"{pass_counts[tid][name]}/{n}".rjust(col_w[name])
            for name in agent_names
        )
        print("  " + tid.ljust(id_w) + "  " + cells)

    # ---- (b) Pooled leaderboard (no task_id => pooled across all tasks). ----
    print("\n(b) Pooled leaderboard (across all tasks, ranked by Wilson LCB):")
    print(afa.format_leaderboard(afa.leaderboard(store)))

    # ---- (c) Backend domain profile for each REAL agent. ----
    print("\n(c) Backend domain profile (real agents):")
    for agent in real_agents:
        profile = afa.domain_profile(store, agent.name, task_domains)
        backend = next((d for d in profile if d.domain == "backend"), None)
        if backend is None:
            print(f"  {agent.name}: (no backend domain)")
            continue
        flag = "" if backend.displayable else "  (provisional)"
        print(
            f"  {agent.name:<22} backend "
            f"pass_rate={backend.pooled_pass_rate:.3f}  "
            f"Wilson=[{backend.wilson_low:.3f},{backend.wilson_high:.3f}]  "
            f"tasks={backend.n_tasks}  runs={backend.n_runs}{flag}"
        )

    store.close()


if __name__ == "__main__":
    main()
