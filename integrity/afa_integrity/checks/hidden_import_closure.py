"""Hidden-test import closure (framework §8.2 activation gate 7; documented,
never implemented anywhere in the codebase — mission §1/§14).

Gate 7 catches an "oracle helper": a non-test module the hidden suite imports
to compute expected values, left editable and unprotected, which would let an
agent rewrite the oracle itself to force hidden tests to pass without ever
touching a protected path.

Key structural fact this check surfaces rather than re-deriving from scratch:
every task in the current pack ships a non-empty `editable_paths` allow-list,
and afa_runner.diffing._path_violates_scope treats ANY path outside that
allow-list as a scope violation regardless of protected_paths — allow-list
mode makes gate 7 satisfied *by construction* (nothing outside editable_paths
can be silently touched at all). The check still performs the real static
import analysis so it is meaningful for a future deny-list-only task, and
reports which regime it found rather than assuming.
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


def _local_imports(source: str) -> tuple[set[str], bool]:
    """Top-level dotted module names imported by `source`, plus whether any
    star-import or dynamic import call was seen (a resolution limitation)."""
    names: set[str] = set()
    has_dynamic = False
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return names, True
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                names.add(node.module)
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
    return names, has_dynamic


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
    any_dynamic = False
    unreadable: list[str] = []

    for f in files:
        try:
            source = f.read_text(encoding="utf-8")
        except OSError:
            unreadable.append(str(f))
            continue
        modules, dynamic = _local_imports(source)
        all_modules |= modules
        any_dynamic = any_dynamic or dynamic

    allow_list_mode = bool(task.editable_paths)

    resolved: dict[str, str] = {}
    for m in sorted(all_modules):
        rel = _resolve_local(m, task.snapshot_dir)
        if rel is not None:
            resolved[m] = rel

    if allow_list_mode:
        # Allow-list mode: capture_diff's scope check rejects ANY touched path
        # outside editable_paths, independent of protected_paths, so no
        # resolved local import can be silently rewritten without already
        # failing scope_ok. Gate 7 holds structurally.
        duration_ms = int((time.monotonic() - start) * 1000)
        return IntegrityCheckResult(
            check_id="hidden_import_closure.gate7",
            category="isolation",
            status=CheckStatus.PASS,
            severity=Severity.INFO,
            description=(
                "Task uses an editable_paths allow-list, which makes gate 7 "
                "(no editable, unprotected oracle-helper import) hold "
                "structurally: any local module the hidden/regression suites "
                "import that isn't the editable code-under-test is already "
                "unreachable by any diff without failing the scope gate."
            ),
            evidence={
                "mode": "allow_list",
                "editable_paths": list(task.editable_paths),
                "resolved_local_imports": resolved,
                "dynamic_or_star_import_seen": any_dynamic,
                "unreadable_suite_files": unreadable,
            },
            duration_ms=duration_ms,
        )

    # Deny-list-only mode: intent (code-under-test vs. oracle helper) can't be
    # inferred from imports alone. Flag any resolved local import NOT covered
    # by protected_paths as a limitation-bearing finding for human review,
    # rather than asserting certainty either way (mission §12: "do not pretend
    # to mathematically prove completeness").
    unprotected = {
        m: rel
        for m, rel in resolved.items()
        if not path_is_protected(rel.rstrip("/"), task.protected_paths)
    }
    duration_ms = int((time.monotonic() - start) * 1000)
    evidence = {
        "mode": "deny_list_only",
        "protected_paths": list(task.protected_paths),
        "resolved_local_imports": resolved,
        "unprotected_local_imports": unprotected,
        "dynamic_or_star_import_seen": any_dynamic,
        "unreadable_suite_files": unreadable,
    }

    if unprotected:
        return IntegrityCheckResult(
            check_id="hidden_import_closure.gate7",
            category="isolation",
            status=CheckStatus.WARNING,
            severity=Severity.MEDIUM,
            description=(
                f"Deny-list-only task: the hidden/regression suites import "
                f"{len(unprotected)} local module(s) not covered by "
                "protected_paths: "
                f"{sorted(unprotected)}. Static import analysis cannot tell "
                "apart 'this is the intended code under test' from 'this is "
                "an oracle helper an agent could rewrite' — review manually."
            ),
            evidence=evidence,
            duration_ms=duration_ms,
        )

    return IntegrityCheckResult(
        check_id="hidden_import_closure.gate7",
        category="isolation",
        status=CheckStatus.PASS,
        severity=Severity.INFO,
        description="Every local module imported by the hidden/regression "
        "suites is covered by protected_paths.",
        evidence=evidence,
        duration_ms=duration_ms,
    )
