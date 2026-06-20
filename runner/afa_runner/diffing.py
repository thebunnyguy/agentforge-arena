"""Diff capture, scope checking, and clean-room application (framework §1, §9).

v0.1 uses a whole-file diff (dependency-free, deterministic): compare the
agent's workspace against the pristine snapshot, record changed/added/deleted
text files, and "apply" by writing those contents into a fresh clean-room copy.
Line counts come from difflib. (A git-based unified-patch backend is the
production option behind the same Diff interface.)
"""

from __future__ import annotations

import difflib
import fnmatch
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Diff:
    """A captured set of changes between a snapshot and a modified workspace.

    changed          : {relpath: new_text} for added or modified text files.
    deleted          : relpaths present in the snapshot but gone from the workspace.
    files_changed    : len(changed) + len(deleted).
    lines_added      : total inserted lines across changed files (difflib).
    lines_removed    : total deleted lines across changed + deleted files.
    touched_protected: True if any changed/deleted path violates scope — it
                       matches a protected glob, is an always-protected
                       auto-executed config file, or (with an editable
                       allow-list) falls outside it.
    patch_text       : a unified-diff rendering for human/audit (not used to apply).
    """

    changed: dict[str, str]
    deleted: tuple[str, ...]
    files_changed: int
    lines_added: int
    lines_removed: int
    touched_protected: bool
    patch_text: str

    def exists(self) -> bool:
        """True iff the diff changes at least one file (diff_exists gate)."""
        return self.files_changed > 0


# Directories/files never considered part of the source tree for diffing.
IGNORE_DIRS = {"__pycache__", ".git", ".pytest_cache", ".mypy_cache"}
IGNORE_SUFFIXES = {".pyc", ".pyo"}

# Files that Python or pytest auto-load/auto-execute from the project tree before
# (or while) collecting tests. An agent that adds ANY of these into the clean
# room can run arbitrary code inside the grading interpreter — e.g. a root
# conftest.py that monkeypatches the function under test — and thereby win a
# perfect score without fixing the bug (clean-room integrity break, framework
# §9). These are ALWAYS treated as protected, regardless of a task's configured
# protected_paths, so adding/modifying them is a scope violation (scope_ok=False).
ALWAYS_PROTECTED_BASENAMES = frozenset(
    {
        "conftest.py",        # pytest auto-imports this from the rootdir/any dir
        "sitecustomize.py",   # imported by the interpreter at startup
        "usercustomize.py",   # imported by the interpreter at startup
        "pytest.ini",         # pytest config (can set options/plugins)
        "tox.ini",            # may carry a [pytest]/[tool:pytest] section
        "setup.cfg",          # may carry a [tool:pytest] section
        "pyproject.toml",     # may carry [tool.pytest.ini_options]
    }
)
ALWAYS_PROTECTED_SUFFIXES = frozenset({".pth"})  # site-loaded import hooks


def path_is_always_protected(relpath: str) -> bool:
    """True for files Python/pytest auto-execute (conftest.py, *.pth, ...).

    Independent of any task's configured protected globs: these paths are code
    that the grading interpreter would run before/while collecting tests, so an
    agent must never be able to introduce them into the clean room. Matched by
    basename (conftest.py in ANY directory) or suffix (*.pth anywhere).
    """
    # Normalize separators and Unicode-aware casing so the rule is identical on
    # case-sensitive Linux, default macOS, and Windows-style input paths.
    base = relpath.replace("\\", "/").rsplit("/", 1)[-1].casefold()
    if base in ALWAYS_PROTECTED_BASENAMES:
        return True
    dot = base.rfind(".")
    if dot != -1 and base[dot:] in ALWAYS_PROTECTED_SUFFIXES:
        return True
    return False


def snapshot_tree(root: Path) -> dict[str, str]:
    """Map every non-ignored text file under root to its contents.

    Keys are POSIX-style relative paths. Binary/undecodable files are skipped
    (v0.1 grades text repos). Ignore IGNORE_DIRS and IGNORE_SUFFIXES.
    """
    root = Path(root)
    tree: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root)
        # Never dereference a symlink (file or directory). Besides keeping the
        # snapshot hermetic, checking every path component also protects against
        # platform/pathlib differences in whether recursive globs traverse a
        # symlinked directory.
        current = root
        contains_symlink = False
        for part in rel.parts:
            current = current / part
            if current.is_symlink():
                contains_symlink = True
                break
        if contains_symlink:
            continue
        if not path.is_file():
            continue
        # Skip anything inside an ignored directory (at any depth).
        if any(part in IGNORE_DIRS for part in rel.parts):
            continue
        if path.suffix in IGNORE_SUFFIXES:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, ValueError):
            # Binary/undecodable file: skip (v0.1 grades text repos).
            continue
        tree[rel.as_posix()] = text
    return tree


def _glob_matches(relpath: str, pattern: str) -> bool:
    """Match a POSIX relpath against a single glob, honoring '**'.

    fnmatch's '*' already matches path separators, but it cannot express the
    "**/foo" should also match a bare "foo" (zero directories) idiom. We handle
    that explicitly:
      - "**/<rest>" matches both "<rest>" (zero leading dirs) and "<anything>/<rest>".
      - "<prefix>/**" matches "<prefix>" itself and anything beneath it.
    Remaining single '*'/'?' are delegated to fnmatch.
    """
    if pattern == "**":
        return True

    # Trailing "/**": match the directory itself or anything under it.
    if pattern.endswith("/**"):
        prefix = pattern[: -len("/**")]
        if relpath == prefix:
            return True
        return fnmatch.fnmatch(relpath, prefix + "/*")

    # Leading "**/": match with zero or more leading directory components.
    if pattern.startswith("**/"):
        rest = pattern[len("**/") :]
        # Zero leading dirs: the rest applies to the bare path.
        if fnmatch.fnmatch(relpath, rest):
            return True
        # One or more leading dirs.
        return fnmatch.fnmatch(relpath, "*/" + rest)

    return fnmatch.fnmatch(relpath, pattern)


def path_is_protected(relpath: str, protected_globs: tuple[str, ...]) -> bool:
    """True if relpath matches any protected glob (fnmatch, with '**' support).

    Match both the full path and against `**/`-prefixed patterns so that e.g.
    "**/test_*.py" matches "tests_visible/test_visible.py" and "test_x.py".
    """
    return any(_glob_matches(relpath, pattern) for pattern in protected_globs)


def _unified_diff(relpath: str, old_text: str, new_text: str) -> tuple[list[str], int, int]:
    """Return (diff_lines, lines_added, lines_removed) for one file.

    Lines are counted by scanning the unified diff body and excluding the
    '+++'/'---' file headers (which also begin with '+'/'-').
    """
    diff_lines = list(
        difflib.unified_diff(
            old_text.splitlines(keepends=True),
            new_text.splitlines(keepends=True),
            fromfile="a/" + relpath,
            tofile="b/" + relpath,
        )
    )
    added = 0
    removed = 0
    for line in diff_lines:
        if line.startswith("+++") or line.startswith("---"):
            continue
        if line.startswith("+"):
            added += 1
        elif line.startswith("-"):
            removed += 1
    return diff_lines, added, removed


def _path_violates_scope(
    relpath: str,
    protected_globs: tuple[str, ...],
    editable_globs: tuple[str, ...],
) -> bool:
    """True if touching ``relpath`` is a scope violation.

    A path violates scope if ANY of:
      * it matches a task-configured protected glob (deny-list), OR
      * it is an always-protected auto-executed config file (conftest.py, *.pth,
        ...), regardless of task config, OR
      * an editable allow-list is configured and the path matches none of it.

    The editable allow-list (when present) makes the gate an ALLOW-list rather
    than a mere deny-list: only explicitly-editable paths may change. This is the
    structural defense against injecting arbitrary new files into the clean room
    (framework §8/§9 clean-room integrity).
    """
    if path_is_protected(relpath, protected_globs):
        return True
    if path_is_always_protected(relpath):
        return True
    if editable_globs and not any(
        _glob_matches(relpath, g) for g in editable_globs
    ):
        return True
    return False


def capture_diff(
    snapshot_root: Path,
    modified_root: Path,
    protected_globs: tuple[str, ...] = (),
    editable_globs: tuple[str, ...] = (),
) -> Diff:
    """Compute the whole-file diff from snapshot_root to modified_root.

    - changed: files whose content differs (or are new in modified_root).
    - deleted: files in snapshot_root absent from modified_root.
    - lines_added/removed via difflib.unified_diff per file (count '+'/'-' lines,
      excluding the +++/--- headers).
    - touched_protected: any changed or deleted path violates scope, i.e. it
      matches a protected glob, OR is an always-protected auto-executed config
      file (conftest.py, sitecustomize.py, *.pth, ...) regardless of task config,
      OR (when an editable allow-list is given) falls outside that allow-list.
    - patch_text: concatenated unified diffs for audit.
    Implements framework §1 (diff analysis) + §8/§9 (clean-room integrity).
    """
    snap = snapshot_tree(snapshot_root)
    mod = snapshot_tree(modified_root)

    changed: dict[str, str] = {}
    deleted: list[str] = []
    lines_added = 0
    lines_removed = 0
    touched_protected = False
    patch_parts: list[str] = []

    # Added or modified files (deterministic order for reproducible patch_text).
    for rel in sorted(mod):
        new_text = mod[rel]
        old_text = snap.get(rel)
        if old_text == new_text:
            continue  # unchanged
        changed[rel] = new_text
        diff_lines, added, removed = _unified_diff(rel, old_text or "", new_text)
        lines_added += added
        lines_removed += removed
        patch_parts.append("".join(diff_lines))
        if _path_violates_scope(rel, protected_globs, editable_globs):
            touched_protected = True

    # Deleted files: present in snapshot, absent from modified.
    for rel in sorted(snap):
        if rel in mod:
            continue
        deleted.append(rel)
        diff_lines, added, removed = _unified_diff(rel, snap[rel], "")
        lines_added += added
        lines_removed += removed
        patch_parts.append("".join(diff_lines))
        if _path_violates_scope(rel, protected_globs, editable_globs):
            touched_protected = True

    files_changed = len(changed) + len(deleted)
    patch_text = "".join(patch_parts)

    return Diff(
        changed=changed,
        deleted=tuple(deleted),
        files_changed=files_changed,
        lines_added=lines_added,
        lines_removed=lines_removed,
        touched_protected=touched_protected,
        patch_text=patch_text,
    )


def apply_diff(diff: Diff, target_root: Path) -> None:
    """Apply a captured diff into target_root (a fresh pristine snapshot copy).

    Write each changed file (creating parent dirs); remove each deleted file.
    This is the clean-room application step: the agent's environment never
    crosses over — only the diff does (framework §9 clean-room grading).

    Defense in depth: always-protected auto-executed config files (conftest.py,
    sitecustomize.py, usercustomize.py, *.pth, ...) are NEVER carried into the
    clean room, even if a Diff somehow lists them. Such a file is arbitrary code
    that pytest/Python would run inside the grading interpreter, so letting it
    cross over would break clean-room integrity (framework §9). capture_diff
    already marks any such path as a scope violation (scope_ok=False), so the run
    fails its gate; refusing to write it here closes the loophole regardless of
    how the Diff was constructed.
    """
    target_root = Path(target_root)

    for rel, text in diff.changed.items():
        if path_is_always_protected(rel):
            # Never let an auto-executed config file into the grading workspace.
            continue
        dest = target_root / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(text, encoding="utf-8")

    for rel in diff.deleted:
        if path_is_always_protected(rel):
            continue
        dest = target_root / rel
        if dest.exists():
            dest.unlink()
