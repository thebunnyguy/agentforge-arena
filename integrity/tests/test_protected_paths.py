"""Tests for the protected-path tampering probes, in particular the
corrected _pytest shadow-package finding (see docs/agents/ORACLE.md,
"Corrected: the _pytest shadow-package finding was overstated"): a
_pytest/ package NESTED inside an editable_paths subtree is empirically
harmless (python -m pytest never puts the editable package directory
itself on sys.path, so it's only importable as <package>._pytest, never as
the bare top-level _pytest the real pytest package needs) — only a
ROOT-level _pytest/ (only reachable on a deny-list-only task with no
editable_paths allow-list) is exploitable.
"""

from afa_runner.task import DomainTag, Task, TestSuiteSpec

from afa_integrity.checks.protected_paths import run_protected_paths_check
from afa_integrity.model import Severity


def _task(task_dir, *, editable_paths, protected_paths=("tests_visible/**", "**/test_*.py")):
    snapshot = task_dir / "snapshot"
    pkg_dir = snapshot / "pkg"
    pkg_dir.mkdir(parents=True)
    (pkg_dir / "__init__.py").write_text("")
    return Task(
        id="t", version="1.0.0", title="t", description="",
        task_dir=task_dir, snapshot_dir=snapshot, reference_dir=None,
        setup=(), domains=(DomainTag(domain="test", weight=1.0),),
        activity="debugging-bugfix", scale="XS", manual_difficulty=1,
        timeout_s=30, protected_paths=protected_paths, editable_paths=editable_paths,
        visible=TestSuiteSpec(paths=()), hidden=TestSuiteSpec(paths=()),
        regression=TestSuiteSpec(paths=()), scoring_recipe={},
    )


def test_nested_pytest_shadow_is_reported_as_not_exploitable(tmp_path):
    task = _task(tmp_path, editable_paths=("pkg/**",))
    _, findings = run_protected_paths_check(task)
    shadow_findings = [f for f in findings if "pytest_shadow_package" in f.finding_id]
    assert len(shadow_findings) == 1
    f = shadow_findings[0]
    assert f.finding_id == "protected_paths.pytest_shadow_package_nested"
    assert f.severity == Severity.INFO
    assert f.evidence["exploitable_today"] is False


def test_root_level_pytest_shadow_is_reported_as_exploitable(tmp_path):
    """A deny-list-only task (no editable_paths) has nothing stopping a
    ROOT-level _pytest/ package — this variant IS empirically confirmed
    dangerous (a controlled test shows it crashes pytest's own bootstrap)."""
    task = _task(tmp_path, editable_paths=())
    _, findings = run_protected_paths_check(task)
    shadow_findings = [f for f in findings if "pytest_shadow_package" in f.finding_id]
    assert len(shadow_findings) == 1
    f = shadow_findings[0]
    assert f.finding_id == "protected_paths.pytest_shadow_package"
    assert f.severity == Severity.HIGH
    assert f.evidence["probe_path"] == "_pytest/__init__.py"


def test_no_task_in_the_real_pack_is_in_deny_list_only_mode():
    """Every real task ships an editable_paths allow-list — the exploitable
    root-level variant has zero live exposure in the current pack. This is
    a standing invariant this test pins: if it ever breaks, the pack now has
    a genuinely vulnerable task and the finding above becomes live."""
    import json
    from pathlib import Path

    tasks_root = Path(__file__).parent.parent.parent / "tasks"
    manifest = json.loads((tasks_root / "manifest.json").read_text())
    for entry in manifest:
        task_json = json.loads((tasks_root / entry["id"] / "task.json").read_text())
        assert task_json.get("editable_paths"), (
            f"{entry['id']} has no editable_paths allow-list — it is now "
            "exposed to the root-level _pytest shadow-package attack; see "
            "protected_paths.py and docs/agents/ORACLE.md"
        )
