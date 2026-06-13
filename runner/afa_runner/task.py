"""Task format and loader (framework §8).

A task is a versioned directory: a pristine repo snapshot, a hidden/regression
grading suite kept OUT of the agent's workspace, a reference solution, and a
JSON spec. Specs are JSON (stdlib, offline) rather than YAML to avoid any
third-party dependency.

Layout of a task directory:
    task.json
    snapshot/                 # what the agent sees and edits
        <repo files...>
        tests_visible/...     # weak feedback tests the agent may run
    grading/                  # NEVER mounted in the agent workspace
        test_hidden.py
        test_regression.py
    reference/                # canonical fix; used to validate the task
        <files that overlay snapshot...>
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class DomainTag:
    """A domain tag with its weight (1.0 primary, 0.5 secondary, 0.25 tertiary)."""

    domain: str
    weight: float


@dataclass(frozen=True)
class TestSuiteSpec:
    """One pytest suite within a task.

    paths   : test file names (relative to `src`, or to the snapshot if src None).
    src     : subdirectory holding the files (e.g. "grading"); None => the files
              already live in the snapshot (visible suite).
    weights : optional per-test weight overrides, keyed by pytest node name
              (e.g. "test_hidden.py::test_preserves_order"). Default weight 1.0.
    """

    paths: tuple[str, ...]
    src: str | None = None
    weights: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class Task:
    """A fully-resolved benchmark task (all paths absolute).

    protected_paths : deny-list globs the agent must never touch (e.g. test
                      files). Touching one is a scope violation (scope_ok=False).
    editable_paths  : optional allow-list globs of paths the agent MAY change.
                      When non-empty, EVERY changed/deleted path must match one
                      of these globs or the run is a scope violation — turning
                      the scope gate into an allow-list (framework §8/§9
                      clean-room integrity). Empty => no allow-list restriction
                      (deny-list-only behavior, back-compatible).
    """

    id: str
    version: str
    title: str
    description: str
    task_dir: Path
    snapshot_dir: Path
    reference_dir: Path | None
    setup: tuple[str, ...]
    domains: tuple[DomainTag, ...]
    activity: str
    scale: str
    manual_difficulty: int
    timeout_s: int
    protected_paths: tuple[str, ...]
    editable_paths: tuple[str, ...]
    visible: TestSuiteSpec
    hidden: TestSuiteSpec
    regression: TestSuiteSpec
    scoring_recipe: dict


def _suite(d: dict | None) -> TestSuiteSpec:
    d = d or {}
    return TestSuiteSpec(
        paths=tuple(d.get("paths", ())),
        src=d.get("src"),
        weights=dict(d.get("weights", {})),
    )


def load_task(task_dir: str | Path) -> Task:
    """Load and resolve a task from its directory.

    Reads task.json, resolves snapshot/reference/grading paths to absolute
    Paths, and validates that required directories exist. Raises FileNotFoundError
    if the snapshot directory is missing and ValueError for a malformed spec.
    """
    task_dir = Path(task_dir).resolve()
    spec_path = task_dir / "task.json"
    if not spec_path.is_file():
        raise FileNotFoundError(f"no task.json in {task_dir}")
    spec = json.loads(spec_path.read_text())

    snapshot_dir = task_dir / spec.get("snapshot_dir", "snapshot")
    if not snapshot_dir.is_dir():
        raise FileNotFoundError(f"snapshot dir missing: {snapshot_dir}")

    ref = spec.get("reference_dir")
    reference_dir = (task_dir / ref) if ref else None

    domains = tuple(
        DomainTag(domain=d["domain"], weight=float(d["weight"]))
        for d in spec.get("domains", [])
    )
    if not domains:
        raise ValueError(f"task {spec.get('id')} has no domain tags")

    return Task(
        id=spec["id"],
        version=spec["version"],
        title=spec.get("title", spec["id"]),
        description=spec.get("description", ""),
        task_dir=task_dir,
        snapshot_dir=snapshot_dir,
        reference_dir=reference_dir,
        setup=tuple(spec.get("setup", ())),
        domains=domains,
        activity=spec.get("activity", "feature-implementation"),
        scale=spec.get("scale", "S"),
        manual_difficulty=int(spec.get("manual_difficulty", 3)),
        timeout_s=int(spec.get("timeout_s", 300)),
        protected_paths=tuple(spec.get("protected_paths", ())),
        editable_paths=tuple(spec.get("editable_paths", ())),
        visible=_suite(spec.get("visible")),
        hidden=_suite(spec.get("hidden")),
        regression=_suite(spec.get("regression")),
        scoring_recipe=dict(spec.get("scoring_recipe", {})),
    )
