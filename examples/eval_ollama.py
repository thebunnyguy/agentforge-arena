"""Evaluate a real, offline open-source coding agent (llama3.2 via Ollama)
through the AgentForge Arena pipeline on the fix-list-dedup task.

Requires a running Ollama with the model pulled:
    ollama serve &        # if not already running
    ollama pull llama3.2

Run:
    python examples/eval_ollama.py            # default n=12
    python examples/eval_ollama.py 20         # custom n
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

# Make kernel/ and runner/ importable without an install.
_ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(_ROOT / "kernel"), str(_ROOT / "runner")]

import afa_runner as afa  # noqa: E402

MODEL = "llama3.2:latest"


def _reference_text(task: afa.Task) -> str:
    return (task.reference_dir / "listkit" / "dedup.py").read_text()


def main() -> None:
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 12
    task = afa.load_task(_ROOT / "tasks" / "fix-list-dedup")
    sandbox = afa.LocalSandbox()
    store = afa.SqliteRunStore(":memory:")

    print(f"Evaluating real coding agents on '{task.id}' v{task.version}, n={n}")
    print(f"Real agent: OllamaAgent -> {MODEL} (local, open weights, offline)")
    print("=" * 70)

    # The real agent under test (varied seed per run => genuine variance).
    real = afa.OllamaAgent(name="ollama-llama3.2", model=MODEL,
                           temperature=0.8, base_seed=42)
    # Two deterministic baselines for ranking context.
    good = afa.MockAgent(name="oracle (reference)",
                         writes={"listkit/dedup.py": _reference_text(task)})
    noop = afa.MockAgent(name="noop (does nothing)")

    for agent in (real, good, noop):
        print(f"\n>>> {agent.name}: running {n} runs...")
        t0 = time.time()
        records = afa.run_group(agent, task, n, sandbox=sandbox)
        dt = time.time() - t0
        for rec in records:
            store.save_run(rec)
        if agent is real:
            print(f"    (per-run, {dt:.1f}s total, {dt / n:.1f}s/run)")
            for rec in records:
                s = rec.score
                print(f"      run {rec.idx:>2}  {s.status.value:<11} "
                      f"S={s.final_score:.3f}  X={str(s.functional_pass):<5} "
                      f"G={s.gate_product}  t_hidden={s.t_hidden:.2f}  "
                      f"files={rec.files_changed} +{rec.lines_added}/-{rec.lines_removed}")

    print("\n" + "=" * 70)
    print("Per-agent aggregates (kernel):")
    for agent in (real, good, noop):
        agg = afa.task_aggregate(store, agent.name, task.id)
        print(f"  {agent.name:<20} pass {agg.n_pass}/{agg.n_valid}  "
              f"p_hat={agg.pass_rate:.3f}  "
              f"Wilson=[{agg.wilson_low:.3f}, {agg.wilson_high:.3f}]  "
              f"mean_S={agg.mean_s:.3f}  stability={agg.stability:.3f}  "
              f"deterministic={agg.deterministic}  pass@k={ {k: round(v,3) for k,v in agg.pass_at_k.items()} }")

    print("\nLeaderboard (ranked by Wilson lower bound):")
    print(afa.format_leaderboard(afa.leaderboard(store, task_id=task.id)))
    store.close()


if __name__ == "__main__":
    main()
