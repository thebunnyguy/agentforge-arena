"""Task-authored integrity controls: known-bad solutions, task-specific
semantic mutants, and alternative valid solutions.

Convention (mirrors the existing tasks/<id>/reference/ overlay directory, so
task authors already know this shape):

    tasks/<id>/integrity/controls/<kind>/<name>/
        control.json          # {"description": "...", "expect": "reject"|"accept"}
        <files mirroring the snapshot's package layout>

    tasks/<id>/integrity/integrity.json     (optional, task-level config)
        {
          "declared_equivalent_mutants": [
            {"file": "...", "diff_hash": "sha256:...", "reason": "..."}
          ],
          "mutation": {"timeout_s": 20, "exclude_files": ["..."]}
        }

A task author adds a new control by adding a new directory — nothing here
needs to change (mission §7/§10: "without modifying the central engine").
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from afa_runner.task import Task

from .model import ControlKind

_KIND_DIRS = {
    ControlKind.KNOWN_BAD: "known_bad",
    ControlKind.SEMANTIC_MUTANT: "semantic_mutants",
    ControlKind.ALTERNATIVE: "alternatives",
}


CONTROL_SPEC_FILENAME = "control.json"


@dataclass(frozen=True)
class Control:
    """One declared control, resolved and ready to overlay.

    overlay_dir also contains control.json itself (the sidecar spec) — callers
    must overlay via overlay_files() below, never by pointing a directory-walk
    straight at overlay_dir, or control.json would be applied as a stray new
    file at the snapshot root (afa_runner.pipeline.overlay_diff has no reason
    to know this is a control directory and would happily copy it over).
    """

    name: str
    kind: ControlKind
    description: str
    expect_accept: bool
    overlay_dir: Path

    def overlay_files(self) -> dict[str, str]:
        """This control's overlay content as {relpath: text}, with the
        control.json sidecar excluded."""
        from .overlay import read_overlay_files  # local import: avoids a cycle

        files = read_overlay_files(self.overlay_dir)
        files.pop(CONTROL_SPEC_FILENAME, None)
        return files


@dataclass(frozen=True)
class DeclaredEquivalentMutant:
    file: str
    diff_hash: str
    reason: str


@dataclass(frozen=True)
class TaskIntegrityConfig:
    declared_equivalent_mutants: tuple[DeclaredEquivalentMutant, ...] = ()
    mutation_timeout_s: int | None = None
    mutation_exclude_files: tuple[str, ...] = ()


def _controls_root(task: Task) -> Path:
    return task.task_dir / "integrity" / "controls"


def discover_controls(task: Task, kind: ControlKind | None = None) -> list[Control]:
    """Find every declared control for a task, optionally filtered to one kind.

    Missing tasks/<id>/integrity/ entirely is normal (no controls declared
    yet) and returns an empty list, not an error — the mission is explicit
    that lacking controls is a PROVISIONAL signal for health status, not a
    crash.
    """
    controls: list[Control] = []
    kinds = [kind] if kind is not None else list(ControlKind)
    for k in kinds:
        kind_dir = _controls_root(task) / _KIND_DIRS[k]
        if not kind_dir.is_dir():
            continue
        for entry in sorted(kind_dir.iterdir()):
            if not entry.is_dir():
                continue
            spec_path = entry / CONTROL_SPEC_FILENAME
            if not spec_path.is_file():
                continue
            try:
                spec = json.loads(spec_path.read_text())
            except (json.JSONDecodeError, OSError):
                continue
            default_expect = "accept" if k == ControlKind.ALTERNATIVE else "reject"
            raw_expect = spec.get("expect", default_expect)
            expect = raw_expect.strip().lower() if isinstance(raw_expect, str) else raw_expect
            if expect not in ("accept", "reject"):
                raise ValueError(
                    f"{spec_path}: \"expect\" must be \"accept\" or \"reject\", "
                    f"got {raw_expect!r} — a malformed value would silently "
                    "invert this control's expected outcome"
                )
            controls.append(
                Control(
                    name=spec.get("name", entry.name),
                    kind=k,
                    description=spec.get("description", ""),
                    expect_accept=(expect == "accept"),
                    overlay_dir=entry,
                )
            )
    return controls


def load_integrity_config(task: Task) -> TaskIntegrityConfig:
    """Load tasks/<id>/integrity/integrity.json, or defaults if absent/invalid."""
    config_path = task.task_dir / "integrity" / "integrity.json"
    if not config_path.is_file():
        return TaskIntegrityConfig()
    try:
        raw = json.loads(config_path.read_text())
    except (json.JSONDecodeError, OSError):
        return TaskIntegrityConfig()

    equivalents = tuple(
        DeclaredEquivalentMutant(
            file=e.get("file", ""),
            diff_hash=e.get("diff_hash", ""),
            reason=e.get("reason", ""),
        )
        for e in raw.get("declared_equivalent_mutants", [])
    )
    mutation = raw.get("mutation", {})
    return TaskIntegrityConfig(
        declared_equivalent_mutants=equivalents,
        mutation_timeout_s=mutation.get("timeout_s"),
        mutation_exclude_files=tuple(mutation.get("exclude_files", ())),
    )


def is_declared_equivalent(
    config: TaskIntegrityConfig, file: str, diff_hash: str
) -> DeclaredEquivalentMutant | None:
    for entry in config.declared_equivalent_mutants:
        if entry.file == file and entry.diff_hash == diff_hash:
            return entry
    return None
