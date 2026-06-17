"""Diagnose WHY an agent fails a task: run the agent, show the exact code it
produced, and the precise hidden-test assertions that failed. Distinguishes a
genuinely-hard task (agent fix is wrong) from an over-strict/ambiguous task
(agent fix is reasonable but the hidden suite rejects it).

Usage:
    python examples/diagnose_task.py <task_id[,task_id...]> [model] [n]
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(_ROOT / "kernel"), str(_ROOT / "runner")]

import afa_runner as afa  # noqa: E402
from afa_runner.diffing import apply_diff, capture_diff  # noqa: E402


def diagnose(task_id: str, model: str, n: int) -> None:
    task = afa.load_task(_ROOT / "tasks" / task_id)
    agent = afa.OllamaAgent(name=model, model=model, temperature=0.8, base_seed=42)
    sandbox = afa.LocalSandbox()

    print("\n" + "#" * 78)
    print(f"# TASK {task_id}  (diff {task.manual_difficulty})  model={model}")
    print(f"# DESCRIPTION: {task.description}")
    print("#" * 78)

    for i in range(n):
        ws_root = Path(tempfile.mkdtemp(prefix="diag_ws_"))
        cr_root = Path(tempfile.mkdtemp(prefix="diag_cr_"))
        try:
            ws = ws_root / "w"
            shutil.copytree(task.snapshot_dir, ws)
            agent.act(ws, task, sandbox)
            diff = capture_diff(task.snapshot_dir, ws,
                                protected_globs=task.protected_paths,
                                editable_globs=task.editable_paths)

            cr = cr_root / "g"
            shutil.copytree(task.snapshot_dir, cr)
            apply_diff(diff, cr)
            hidden_files = []
            for p in task.hidden.paths:
                src = task.task_dir / (task.hidden.src or ".") / p
                shutil.copy(src, cr / p)
                hidden_files.append(p)

            res = subprocess.run(
                [sys.executable, "-m", "pytest", *hidden_files, "-v", "--no-header", "-rA"],
                cwd=cr, capture_output=True, text=True,
                env={"PYTHONHASHSEED": "0", "PATH": __import__("os").environ.get("PATH", "")},
            )
            summary = res.stdout.strip().splitlines()
            tail = "\n".join(summary[-30:])
            print(f"\n----- attempt {i} -----")
            print(f"files_changed={diff.files_changed} +{diff.lines_added}/-{diff.lines_removed} "
                  f"scope_ok={not diff.touched_protected}")
            print("--- agent-produced code (changed files) ---")
            for rel, content in sorted(diff.changed.items()):
                print(f"### {rel}\n{content.rstrip()}")
            print("--- hidden pytest -v (tail) ---")
            print(tail)
        finally:
            shutil.rmtree(ws_root, ignore_errors=True)
            shutil.rmtree(cr_root, ignore_errors=True)


def main() -> None:
    ids = (sys.argv[1] if len(sys.argv) > 1 else "").split(",")
    model = sys.argv[2] if len(sys.argv) > 2 else "qwen2.5-coder:7b"
    n = int(sys.argv[3]) if len(sys.argv) > 3 else 2
    for tid in [x.strip() for x in ids if x.strip()]:
        diagnose(tid, model, n)


if __name__ == "__main__":
    main()
