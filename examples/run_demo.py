#!/usr/bin/env python3
"""End-to-end AgentForge Arena demo (framework §1, §2, §6, §9, §10).

Runs three deterministic agents against the real ``fix-list-dedup`` benchmark
task with a LocalSandbox, persists every run to a SQLite store, then prints the
Wilson-LCB leaderboard plus each agent's aggregate (p-hat, Wilson interval,
stability). No network, no wall-clock dependence, no third-party imports.

The three agents demonstrate the scoring spectrum:
  good : writes the reference dedup            -> 5/5 pass, S=1.0, X=True
  bad  : writes a still-buggy sorted(set(...)) -> 0/5 pass, gates hold (0<S<1)
  seq  : cycles good/good/wrong/good/wrong     -> exactly 3/5 pass

Run from the project root:
    PYTHONPATH="kernel:runner" python examples/run_demo.py
or simply:
    python examples/run_demo.py            (it inserts the paths itself)
"""

from __future__ import annotations

import sys
from pathlib import Path

# Make kernel/ and runner/ importable regardless of how this script is invoked.
# This file lives at <root>/examples/run_demo.py.
ROOT = Path(__file__).resolve().parents[1]
for sub in ("kernel", "runner"):
    p = str(ROOT / sub)
    if p not in sys.path:
        sys.path.insert(0, p)

from afa_runner import (  # noqa: E402  (after sys.path setup)
    LocalSandbox,
    MockAgent,
    SequenceAgent,
    SqliteRunStore,
    format_leaderboard,
    leaderboard,
    load_task,
    run_group,
    task_aggregate,
)

N_RUNS = 5
TASK_DIR = ROOT / "tasks" / "fix-list-dedup"

# The still-buggy "fix": removes duplicates (regression passes) but sorts, so
# first-occurrence order is lost (the hidden order tests fail).
BUGGY_DEDUP = "def dedup(items):\n    return sorted(set(items))\n"


def _build_agents(task):
    """Construct the three demo agents. The reference text is read from the
    task so the 'good' agent writes exactly the canonical fix."""
    ref_text = (task.reference_dir / "listkit" / "dedup.py").read_text(
        encoding="utf-8"
    )

    good = MockAgent(name="good", writes={"listkit/dedup.py": ref_text})
    bad = MockAgent(name="bad", writes={"listkit/dedup.py": BUGGY_DEDUP})

    # SequenceAgent cycles its members across the 5 runs in this exact order:
    #   good, good, wrong, good, wrong  -> 3 passes out of 5 (c=3/5).
    good_member = MockAgent(name="good", writes={"listkit/dedup.py": ref_text})
    wrong_member = MockAgent(name="wrong", writes={"listkit/dedup.py": BUGGY_DEDUP})
    seq = SequenceAgent(
        name="seq",
        members=[good_member, good_member, wrong_member, good_member, wrong_member],
    )
    return good, bad, seq


def main() -> None:
    task = load_task(TASK_DIR)
    sandbox = LocalSandbox()
    store = SqliteRunStore(":memory:")

    good, bad, seq = _build_agents(task)

    # Run each agent n=5 times (fresh workspaces each, same agent instance reused
    # so the stateful SequenceAgent varies its output) and persist every run.
    for agent in (good, bad, seq):
        records = run_group(agent, task, N_RUNS, sandbox=sandbox)
        for record in records:
            store.save_run(record)

    print(f"AgentForge Arena demo — task '{task.id}' v{task.version}, n={N_RUNS}")
    print("=" * 64)

    # Per-agent aggregate over the (agent, task) cell.
    print("\nPer-agent aggregates (over valid runs):")
    for agent_name in store.agents():
        agg = task_aggregate(store, agent_name, task.id)
        print(
            f"  {agent_name:<5}  "
            f"pass {agg.n_pass}/{agg.n_valid}  "
            f"p_hat={agg.pass_rate:.3f}  "
            f"Wilson=[{agg.wilson_low:.3f}, {agg.wilson_high:.3f}]  "
            f"mean_S={agg.mean_s:.3f}  "
            f"stability={agg.stability:.3f}  "
            f"deterministic={agg.deterministic}"
        )

    # The Wilson-LCB leaderboard over the single-task scope.
    print("\nLeaderboard (ranked by Wilson lower bound):")
    entries = leaderboard(store, task_id=task.id)
    print(format_leaderboard(entries))

    store.close()


if __name__ == "__main__":
    main()
