"""Evaluate one agent on a SUBSET of tasks, resiliently. Reports, per task:
valid runs, functional passes, and INFRA voids (e.g. model-server outages)
SEPARATELY — so a flaky Ollama can never be mistaken for the agent failing.
Among valid non-passing runs it splits "no-edit" (empty diff) from "wrong-fix",
the signal that distinguishes a measurement artifact from a genuine miss.

Usage:
    python examples/eval_subset.py <task_id[,task_id...]> [model] [n]
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(_ROOT / "kernel"), str(_ROOT / "runner")]

import afa_runner as afa  # noqa: E402
from afa_kernel.types import RunStatus  # noqa: E402


def main() -> None:
    ids = [x.strip() for x in (sys.argv[1] if len(sys.argv) > 1 else "").split(",") if x.strip()]
    model = sys.argv[2] if len(sys.argv) > 2 else "qwen2.5-coder:7b"
    n = int(sys.argv[3]) if len(sys.argv) > 3 else 5
    sandbox = afa.LocalSandbox()
    agent = afa.OllamaAgent(name=model, model=model, temperature=0.8, base_seed=42)

    print(f"Subset eval: model={model}  n={n}  tasks={ids}")
    print("=" * 78)
    print(f"{'task':<26} {'valid':>5} {'pass':>4} {'void':>4} {'p_hat':>6} "
          f"{'Wilson95':>15}   failure split")
    print("-" * 90)

    for tid in ids:
        task = afa.load_task(_ROOT / "tasks" / tid)
        records = afa.run_group(agent, task, n, sandbox=sandbox)
        agg = afa.aggregate_group(records)
        void = sum(1 for r in records if r.status is RunStatus.INFRA_FAILURE)
        valid_fail = [r for r in records
                      if r.status is not RunStatus.INFRA_FAILURE
                      and not r.score.functional_pass]
        no_edit = sum(1 for r in valid_fail if r.files_changed == 0)
        wrong_fix = sum(1 for r in valid_fail if r.files_changed > 0)
        wil = f"[{agg.wilson_low:.2f},{agg.wilson_high:.2f}]"
        split = f"{no_edit} no-edit, {wrong_fix} wrong-fix" if valid_fail else "—"
        print(f"{tid:<26} {agg.n_valid:>5} {agg.n_pass:>4} {void:>4} "
              f"{agg.pass_rate:>6.3f} {wil:>15}   {split}")

    print("-" * 90)
    print("void = INFRA_FAILURE (model unreachable) — excluded from n, never an agent loss.")
    print("wrong-fix = the agent produced code that failed hidden tests (a genuine miss).")


if __name__ == "__main__":
    main()
