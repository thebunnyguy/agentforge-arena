"""Unit tests for the gate-7 import-closure check's static analysis, isolated
from grading. Covers the two bugs an independent code review of this engine
found: bare relative imports silently dropped, and allow-list mode never
checking whether a resolved import falls WITHIN editable_paths.
"""

from afa_runner.task import DomainTag, Task, TestSuiteSpec

from afa_integrity.checks.hidden_import_closure import (
    _local_imports,
    run_hidden_import_closure_check,
)


def test_local_imports_captures_absolute_and_star_and_dynamic():
    source = (
        "import os\n"
        "from pkg.sub import thing\n"
        "from pkg import *\n"
        "import importlib\n"
        "importlib.import_module('pkg.other')\n"
    )
    names, unresolved_relative, dynamic = _local_imports(source)
    assert names == {"os", "pkg.sub", "pkg", "importlib"}
    assert unresolved_relative == []
    assert dynamic is True


def test_local_imports_surfaces_bare_relative_imports_instead_of_dropping_them():
    """`from . import x` has module=None — before the fix this silently
    vanished from the analysis instead of being reported as unresolvable."""
    source = "from . import helper\nfrom .. import other_helper\n"
    names, unresolved_relative, dynamic = _local_imports(source)
    assert names == set()
    assert len(unresolved_relative) == 2
    assert any(u.startswith(".") and "helper" in u for u in unresolved_relative)
    assert any(u.startswith("..") and "other_helper" in u for u in unresolved_relative)


def _task(task_dir, snapshot_dir, *, editable_paths=(), protected_paths=()):
    suite = TestSuiteSpec(paths=("test_hidden.py",), src="grading")
    return Task(
        id="t", version="1.0.0", title="t", description="",
        task_dir=task_dir, snapshot_dir=snapshot_dir, reference_dir=None,
        setup=(), domains=(DomainTag(domain="test", weight=1.0),),
        activity="debugging-bugfix", scale="XS", manual_difficulty=1,
        timeout_s=30, protected_paths=protected_paths, editable_paths=editable_paths,
        visible=TestSuiteSpec(paths=()), hidden=suite,
        regression=TestSuiteSpec(paths=()), scoring_recipe={},
    )


def test_allow_list_mode_warns_on_multiple_reachable_files(tmp_path):
    """The exact gap the code review found: a hidden-test import resolving to
    a SECOND file inside editable_paths (not just outside it) must not be
    silently passed as "gate 7 holds structurally"."""
    snapshot = tmp_path / "snapshot"
    (snapshot / "pkg").mkdir(parents=True)
    (snapshot / "pkg" / "__init__.py").write_text("")
    (snapshot / "pkg" / "core.py").write_text("def f(): pass\n")
    (snapshot / "pkg" / "expected.py").write_text("EXPECTED = 1\n")
    (tmp_path / "grading").mkdir()
    (tmp_path / "grading" / "test_hidden.py").write_text(
        "from pkg.core import f\nfrom pkg.expected import EXPECTED\n"
    )
    task = _task(tmp_path, snapshot, editable_paths=("pkg/**",))
    result = run_hidden_import_closure_check(task)
    assert result.status.value == "warning"
    assert set(result.evidence["distinct_reachable_files"]) == {
        "pkg/core.py", "pkg/expected.py",
    }


def test_allow_list_mode_passes_with_single_reachable_file(tmp_path):
    snapshot = tmp_path / "snapshot"
    (snapshot / "pkg").mkdir(parents=True)
    (snapshot / "pkg" / "__init__.py").write_text("")
    (snapshot / "pkg" / "core.py").write_text("def f(): pass\n")
    (tmp_path / "grading").mkdir()
    (tmp_path / "grading" / "test_hidden.py").write_text("from pkg.core import f\n")
    task = _task(tmp_path, snapshot, editable_paths=("pkg/**",))
    result = run_hidden_import_closure_check(task)
    assert result.status.value == "pass"
    assert result.evidence["distinct_reachable_files"] == ["pkg/core.py"]


def test_allow_list_mode_passes_when_import_is_outside_editable_paths(tmp_path):
    """An import OUTSIDE editable_paths is safe by construction (any touch to
    it already fails the scope gate) — the allow-list guarantee this check
    still validly relies on for this half of the analysis."""
    snapshot = tmp_path / "snapshot"
    (snapshot / "pkg").mkdir(parents=True)
    (snapshot / "pkg" / "__init__.py").write_text("")
    (snapshot / "helpers").mkdir()
    (snapshot / "helpers" / "util.py").write_text("X = 1\n")
    (tmp_path / "grading").mkdir()
    (tmp_path / "grading" / "test_hidden.py").write_text("from helpers.util import X\n")
    task = _task(tmp_path, snapshot, editable_paths=("pkg/**",))
    result = run_hidden_import_closure_check(task)
    assert result.status.value == "pass"
    assert result.evidence["distinct_reachable_files"] == []
