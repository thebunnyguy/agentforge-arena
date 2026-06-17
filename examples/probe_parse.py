"""Probe: for a task, show the editable targets the agent sees, the RAW model
response, and exactly what the parser wrote. Reveals parse/format mismatches."""

from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(_ROOT / "kernel"), str(_ROOT / "runner")]

import afa_runner as afa  # noqa: E402
from afa_runner.diffing import capture_diff  # noqa: E402

task_id = sys.argv[1]
model = sys.argv[2] if len(sys.argv) > 2 else "qwen2.5-coder:7b"

task = afa.load_task(_ROOT / "tasks" / task_id)
agent = afa.OllamaAgent(name=model, model=model, temperature=0.8, base_seed=42)

ws_root = Path(tempfile.mkdtemp())
ws = ws_root / "w"
shutil.copytree(task.snapshot_dir, ws)
targets = agent._editable_files(ws, task)
print(f"=== {task_id}: editable targets the agent sees ===")
for t in targets:
    print("   ", t)
outcome = agent.act(ws, task, sandbox=afa.LocalSandbox())
resp = outcome.transcript.split("--- RESPONSE ---\n", 1)[-1]
print(f"\n=== RAW MODEL RESPONSE ({len(resp)} chars) ===")
print(resp[:2500])
diff = capture_diff(task.snapshot_dir, ws, protected_globs=task.protected_paths,
                    editable_globs=task.editable_paths)
print(f"\n=== PARSER RESULT: files_changed={diff.files_changed} changed={sorted(diff.changed)} ===")
shutil.rmtree(ws_root, ignore_errors=True)
