"""Provenance evidence for a report (mission §17): what was actually graded,
with what engine, against what task content, when.

Deliberately does not attempt cross-version score comparability logic (that is
the existing task_version / pack_version / harness_version discipline already
described in docs/EVALUATION_FRAMEWORK.md §8.5 and enforced at the storage
layer) — it only records the facts a later comparison would need, and states
plainly what it has not established (mission §17: "do not silently label
historical evaluations as invalid").
"""

from __future__ import annotations

import hashlib
import platform
import sys
from pathlib import Path

import afa_kernel
import afa_runner

from .model import ENGINE_VERSION


def _hash_tree(root: Path) -> str | None:
    if not root.is_dir():
        return None
    h = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if "__pycache__" in path.parts or path.suffix in (".pyc", ".pyo"):
            continue
        rel = path.relative_to(root).as_posix()
        h.update(rel.encode("utf-8"))
        h.update(b"\0")
        try:
            h.update(path.read_bytes())
        except OSError:
            continue
        h.update(b"\0")
    return "sha256:" + h.hexdigest()


def collect_provenance(task) -> dict:
    """Hashes of a task's grading-relevant content, plus engine/kernel/runner/
    interpreter versions. Two audits with identical provenance graded exactly
    the same bytes with exactly the same code; a mismatch in any hash is the
    first thing to check before comparing two reports for the same task_id.
    """
    return {
        "task_id": task.id,
        "task_version": task.version,
        "task_json_hash": _hash_single_file(task.task_dir / "task.json"),
        "snapshot_hash": _hash_tree(task.snapshot_dir),
        "reference_hash": _hash_tree(task.reference_dir) if task.reference_dir else None,
        "grading_hash": _hash_tree(task.task_dir / "grading"),
        "controls_hash": _hash_tree(task.task_dir / "integrity" / "controls"),
        "engine_version": ENGINE_VERSION,
        "afa_kernel_version": getattr(afa_kernel, "__version__", "unknown"),
        "afa_runner_version": getattr(afa_runner, "__version__", "unknown"),
        "python_version": sys.version.split()[0],
        "platform": platform.platform(),
    }


def _hash_single_file(path: Path) -> str | None:
    if not path.is_file():
        return None
    try:
        return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None
