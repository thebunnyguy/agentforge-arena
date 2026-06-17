"""Compare multiple real, offline open-source coding agents through AgentForge
Arena on the fix-list-dedup task: a coder-specialized model (qwen2.5-coder)
versus a general small model (llama3.2), with deterministic baselines for
ranking context.

Requires a running Ollama with the models pulled:
    ollama serve &
    ollama pull qwen2.5-coder:7b
    ollama pull llama3.2

Run:
    python examples/eval_compare.py            # default n=12
    python examples/eval_compare.py 20
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(_ROOT / "kernel"), str(_ROOT / "runner")]

import afa_runner as afa  # noqa: E402

# Real local models to evaluate (label, ollama model id).
MODELS = [
    ("qwen2.5-coder:7b", "qwen2.5-coder:7b"),
    ("llama3.2:3b", "llama3.2:latest"),
]


def _reference_text(task: afa.Task) -> str:
    return (task.reference_dir / "listkit" / "dedup.py").read_text()


def main() -> None:
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 12
    task = afa.load_task(_ROOT / "tasks" / "fix-list-dedup")
    sandbox = afa.LocalSandbox()
    store = afa.SqliteRunStore(":memory:")

    print(f"Comparing real coding agents on '{task.id}' v{task.version}, n={n}")
    print("=" * 72)

    agents = []
    for label, model in MODELS:
        agents.append(afa.OllamaAgent(name=label, model=model,
                                      temperature=0.8, base_seed=42))
    agents.append(afa.MockAgent(name="oracle (reference)",
                                writes={"listkit/dedup.py": _reference_text(task)}))
    agents.append(afa.MockAgent(name="noop"))

    for agent in agents:
        is_real = isinstance(agent, afa.OllamaAgent)
        t0 = time.time()
        records = afa.run_group(agent, task, n, sandbox=sandbox)
        dt = time.time() - t0
        for rec in records:
            store.save_run(rec)
        if is_real:
            passes = sum(1 for r in records if r.score.functional_pass)
            empties = sum(1 for r in records if r.files_changed == 0)
            wrong = sum(1 for r in records
                        if r.files_changed > 0 and not r.score.functional_pass)
            print(f">>> {agent.name:<18} {passes}/{n} pass  "
                  f"({empties} no-edit, {wrong} wrong-fix)  "
                  f"{dt:.0f}s total, {dt / n:.1f}s/run")

    print("\n" + "=" * 72)
    print("Per-agent aggregates (kernel):")
    for agent in agents:
        agg = afa.task_aggregate(store, agent.name, task.id)
        flag = " [BIMODAL]" if agg.bimodal else ""
        print(f"  {agent.name:<20} pass {agg.n_pass}/{agg.n_valid}  "
              f"p_hat={agg.pass_rate:.3f}  "
              f"Wilson=[{agg.wilson_low:.3f},{agg.wilson_high:.3f}]  "
              f"pass@3={agg.pass_at_k.get(3, float('nan')):.3f}  "
              f"stab={agg.stability:.2f}{flag}")

    print("\nLeaderboard (ranked by Wilson lower bound):")
    print(afa.format_leaderboard(afa.leaderboard(store, task_id=task.id)))
    store.close()


if __name__ == "__main__":
    main()
