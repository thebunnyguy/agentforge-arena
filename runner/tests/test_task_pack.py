"""Benchmark-pack integration test (framework §8 CI gate, applied to the whole
task pack).

Discovers every task listed in tasks/manifest.json and, parametrized per task
id, runs the §8 anti-gaming validator (validate_task over the loaded Task):

  * the unmodified snapshot passes regression but NOT hidden (a real bug exists,
    nothing is trivially solved), and
  * the reference overlay scores 1.0 / functional_pass and grades identically
    3x.

It also asserts pack-level invariants the leaderboard/domain reports rely on:
the manifest has at least 8 tasks, and "backend" is a PRIMARY (weight 1.0)
domain on at least 5 tasks so a backend domain score is always displayable.

Imports resolve via pyproject's `pythonpath = ["kernel", "runner"]`.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from afa_runner import load_task, validate_task

# This file lives at <root>/runner/tests/test_task_pack.py.
ROOT = Path(__file__).resolve().parents[2]
MANIFEST_PATH = ROOT / "tasks" / "manifest.json"


def _load_manifest() -> list[dict]:
    """Read and parse the task pack manifest (a JSON list of task entries)."""
    return json.loads(MANIFEST_PATH.read_text())


MANIFEST = _load_manifest()
TASK_IDS = [entry["id"] for entry in MANIFEST]


def _entry(task_id: str) -> dict:
    """The manifest entry for a given task id."""
    return next(e for e in MANIFEST if e["id"] == task_id)


def _is_primary_backend(entry: dict) -> bool:
    """True if the entry tags `backend` as a primary domain (weight 1.0)."""
    return any(
        domain == "backend" and float(weight) == 1.0
        for domain, weight in entry["domains"]
    )


# --------------------------------------------------------------------------- #
# Pack-level invariants (the reports/leaderboard depend on these).
# --------------------------------------------------------------------------- #

def test_manifest_has_at_least_8_tasks():
    assert len(MANIFEST) >= 8, (
        f"task pack must contain at least 8 tasks; got {len(MANIFEST)}"
    )


def test_manifest_task_ids_are_unique():
    assert len(TASK_IDS) == len(set(TASK_IDS)), (
        f"duplicate task ids in manifest: {TASK_IDS}"
    )


def test_backend_is_primary_on_at_least_5_tasks():
    backend_primary = [e["id"] for e in MANIFEST if _is_primary_backend(e)]
    assert len(backend_primary) >= 5, (
        "backend must be a primary (weight 1.0) domain on at least 5 tasks so a "
        f"backend domain score is displayable; got {len(backend_primary)}: "
        f"{backend_primary}"
    )


# --------------------------------------------------------------------------- #
# Per-task §8 validation: every manifest task must be a well-formed benchmark.
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("task_id", TASK_IDS)
def test_manifest_dir_exists_and_matches_id(task_id):
    entry = _entry(task_id)
    task_dir = ROOT / entry["dir"]
    assert task_dir.is_dir(), f"manifest dir missing: {task_dir}"
    task = load_task(task_dir)
    assert task.id == task_id, (
        f"task.json id {task.id!r} != manifest id {task_id!r} in {task_dir}"
    )


@pytest.mark.parametrize("task_id", TASK_IDS)
def test_task_passes_section8_validation(task_id):
    entry = _entry(task_id)
    task = load_task(ROOT / entry["dir"])
    result = validate_task(task)
    assert result["valid"] is True, (
        f"task {task_id} failed §8 validation: {result}"
    )
