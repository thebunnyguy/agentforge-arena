"""Hidden-test import closure (framework §8.2 activation gate 7; documented,
never implemented anywhere in the codebase — mission §1/§14).

Gate 7 catches an "oracle helper": a non-test module the hidden suite imports
to compute expected values, left editable and unprotected, which would let an
agent rewrite the oracle itself to force hidden tests to pass without ever
touching a protected path.

Both the allow-list and deny-list regimes reduce to the SAME question: which
local modules the hidden/regression suites import are actually *reachable* by
a diff without failing the scope gate, and among those, can static analysis
tell "this is the code under test" apart from "this is a helper the agent
could rewrite"? It cannot in general (mission §12), so this check never
claims gate 7 holds merely because an allow-list exists — an allow-list only
changes *which* imports are reachable (those matching editable_paths, instead
of those NOT matching protected_paths), not whether reachable-and-ambiguous
imports exist. The one case this check can call PASS with a straight face is
when there is at most one distinct reachable file: every task in the current
pack's hidden suite imports exactly the single file it is testing, which is
unambiguously the code under test, not a separate helper.
"""

from __future__ import annotations

import ast
import time
from pathlib import Path

from afa_runner.diffing import path_is_protected
from afa_runner.task import Task, TestSuiteSpec

from ..model import CheckStatus, IntegrityCheckResult, Severity


def _suite_files(task: Task, suite: TestSuiteSpec) -> list[Path]:
    base = task.task_dir / suite.src if suite.src else task.snapshot_dir
    return [base / p for p in suite.paths]


def _local_imports(source: str) -> tuple[set[str], list[str], bool]:
    """Top-level dotted module names imported by `source`, any unresolvable
    relative imports (``from . import x`` — level > 0, no module name, so
    there is nothing to resolve without knowing the importing file's own
    package location), and whether a star-import or dynamic import call was
    seen. The relative-import and dynamic/star cases are resolution
    limitations, surfaced rather than silently dropped.
    """
    names: set[str] = set()
    unresolved_relative: list[str] = []
    has_dynamic = False
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return names, unresolved_relative, True
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                names.add(node.module)
            elif node.level:
                # `from . import x` / `from .. import x`: no module name, so
                # this can't be resolved to a snapshot relpath without
                # knowing which file is doing the importing.
                unresolved_relative.append(
                    "." * node.level + ",".join(a.name for a in node.names)
                )
            if any(a.name == "*" for a in node.names):
                has_dynamic = True
        elif isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name) and func.id == "__import__":
                has_dynamic = True
            if isinstance(func, ast.Attribute) and func.attr in (
                "import_module",
                "__import__",
            ):
                has_dynamic = True
    return names, unresolved_relative, has_dynamic


def _resolve_local(module_name: str, snapshot_dir: Path) -> str | None:
    """Resolve a dotted module name to a relpath under snapshot_dir, trying
    progressively shorter prefixes (from x.y.z down to x). Returns the
    resolved relpath (posix) or None if it isn't a local snapshot module."""
    parts = module_name.split(".")
    while parts:
        candidate_file = snapshot_dir / Path(*parts[:-1], parts[-1] + ".py") if len(parts) > 1 else snapshot_dir / (parts[0] + ".py")
        candidate_pkg_init = snapshot_dir.joinpath(*parts) / "__init__.py"
        candidate_dir = snapshot_dir.joinpath(*parts)
        if candidate_file.is_file():
            return candidate_file.relative_to(snapshot_dir).as_posix()
        if candidate_pkg_init.is_file():
            return candidate_pkg_init.relative_to(snapshot_dir).as_posix()
        if candidate_dir.is_dir():
            return candidate_dir.relative_to(snapshot_dir).as_posix() + "/"
        parts = parts[:-1]
    return None


def run_hidden_import_closure_check(task: Task) -> IntegrityCheckResult:
    start = time.monotonic()

    files = _suite_files(task, task.hidden) + _suite_files(task, task.regression)
    all_modules: set[str] = set()
    all_unresolved_relative: list[str] = []
    any_dynamic = False
    unreadable: list[str] = []

    for f in files:
        try:
            source = f.read_text(encoding="utf-8")
        except OSError:
            unreadable.append(str(f))
            continue
        modules, unresolved_relative, dynamic = _local_imports(source)
        all_modules |= modules
        all_unresolved_relative.extend(unresolved_relative)
        any_dynamic = any_dynamic or dynamic

    allow_list_mode = bool(task.editable_paths)

    resolved: dict[str, str] = {}
    for m in sorted(all_modules):
        rel = _resolve_local(m, task.snapshot_dir)
        if rel is not None:
            resolved[m] = rel

    # The one thing that differs between the two scope regimes: WHICH
    # resolved imports are reachable by a diff without already failing
    # scope_ok. Allow-list: only paths matching editable_paths are
    # reachable at all. Deny-list-only: everything NOT matching
    # protected_paths is reachable.
    if allow_list_mode:
        reachable = {
            m: rel for m, rel in resolved.items()
            if path_is_protected(rel.rstrip("/"), task.editable_paths)
        }
        mode_label = "allow_list"
        mode_paths_key = "editable_paths"
        mode_paths = task.editable_paths
    else:
        reachable = {
            m: rel for m, rel in resolved.items()
            if not path_is_protected(rel.rstrip("/"), task.protected_paths)
        }
        mode_label = "deny_list_only"
        mode_paths_key = "protected_paths"
        mode_paths = task.protected_paths

    distinct_reachable_files = sorted(set(reachable.values()))
    duration_ms = int((time.monotonic() - start) * 1000)
    evidence = {
        "mode": mode_label,
        mode_paths_key: list(mode_paths),
        "resolved_local_imports": resolved,
        "reachable_local_imports": reachable,
        "distinct_reachable_files": distinct_reachable_files,
        "dynamic_or_star_import_seen": any_dynamic,
        "unresolved_relative_imports": all_unresolved_relative,
        "unreadable_suite_files": unreadable,
    }

    if len(distinct_reachable_files) > 1:
        return IntegrityCheckResult(
            check_id="hidden_import_closure.gate7",
            category="isolation",
            status=CheckStatus.WARNING,
            severity=Severity.MEDIUM,
            description=(
                f"The hidden/regression suites import {len(distinct_reachable_files)} "
                f"distinct reachable local files: {distinct_reachable_files}. "
                "Static import analysis cannot tell 'this is the intended "
                "code under test' apart from 'this is an oracle helper an "
                "agent could rewrite' when more than one file is reachable "
                "— review manually (framework §8.2 gate 7)."
            ),
            evidence=evidence,
            duration_ms=duration_ms,
        )

    if all_unresolved_relative:
        # A single reachable file plus an unresolvable relative import: still
        # PASS on what could be checked, but say plainly that a relative
        # import was not verified rather than silently treating it as absent.
        return IntegrityCheckResult(
            check_id="hidden_import_closure.gate7",
            category="isolation",
            status=CheckStatus.WARNING,
            severity=Severity.LOW,
            description=(
                f"{len(distinct_reachable_files)} distinct reachable local "
                "file(s), consistent with the code under test. However "
                f"{len(all_unresolved_relative)} relative import(s) "
                f"({all_unresolved_relative}) could not be resolved to a "
                "snapshot path by this static check (resolving `from . "
                "import x` requires knowing the importing file's own "
                "package location) — gate 7 is unverified for those."
            ),
            evidence=evidence,
            duration_ms=duration_ms,
        )

    return IntegrityCheckResult(
        check_id="hidden_import_closure.gate7",
        category="isolation",
        status=CheckStatus.PASS,
        severity=Severity.INFO,
        description=(
            f"At most one distinct local file ({distinct_reachable_files or 'none'}) "
            "is reachable by a diff without failing the scope gate and "
            "imported by the hidden/regression suites — unambiguously the "
            "code under test, not a separate oracle-helper module."
        ),
        evidence=evidence,
        duration_ms=duration_ms,
    )
