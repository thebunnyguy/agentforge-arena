"""Repository locations and the import bootstrap for the campaign tooling.

The tooling reuses the runtime's own code (task snapshots, persisted-parameter
verification, provenance classification, the kernel's aggregation) instead of
re-implementing any of it, so the repository root, ``kernel`` and ``runner`` must
be importable even when invoked as ``python3 -m afa_campaign`` from any cwd.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

for _path in (REPO, REPO / "kernel", REPO / "runner"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

TASKS_DIR = REPO / "tasks"
TASK_MANIFEST = TASKS_DIR / "manifest.json"
REMEDIATION_MANIFEST = REPO / "integrity" / "pack-audit" / "remediation-manifest.json"
EVIDENCE_DB = REPO / "reports" / "runs.sqlite"
DEFAULT_MANIFEST = REPO / "campaigns" / "phase0-post-integrity" / "manifest.json"

# Paths whose content IS the executed benchmark runtime. The launcher refuses to
# run when they differ from the campaign's pinned release.
RUNTIME_PATHS = ("afa_api", "runner", "kernel", "tasks")


def resolve(path: str | Path) -> Path:
    """Resolve a manifest-relative path (relative paths are repo-relative)."""
    candidate = Path(path).expanduser()
    return (candidate if candidate.is_absolute() else REPO / candidate).resolve()


def display(path: str | Path) -> str:
    """Repo-relative spelling when possible (manifests never hold user paths)."""
    resolved = Path(path).expanduser().resolve()
    try:
        return resolved.relative_to(REPO).as_posix()
    except ValueError:
        return str(resolved)
