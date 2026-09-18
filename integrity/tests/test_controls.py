import json

import pytest
from afa_runner.task import DomainTag, Task, TestSuiteSpec, load_task

from afa_integrity.controls import discover_controls, load_integrity_config
from afa_integrity.model import ControlKind


def _bare_task(task_dir) -> Task:
    """A minimal Task whose only field discover_controls reads is task_dir —
    everything else is a placeholder, deliberately not routed through
    load_task/a real task.json since this is only testing control discovery.
    """
    suite = TestSuiteSpec(paths=())
    return Task(
        id="t", version="1.0.0", title="t", description="",
        task_dir=task_dir, snapshot_dir=task_dir, reference_dir=None,
        setup=(), domains=(DomainTag(domain="test", weight=1.0),),
        activity="debugging-bugfix", scale="XS", manual_difficulty=1,
        timeout_s=30, protected_paths=(), editable_paths=(),
        visible=suite, hidden=suite, regression=suite, scoring_recipe={},
    )


def test_discover_controls_finds_known_bad_and_alternative(fixtures_root):
    task = load_task(fixtures_root / "healthy")
    controls = discover_controls(task)
    kinds = {c.kind for c in controls}
    assert ControlKind.KNOWN_BAD in kinds
    assert ControlKind.ALTERNATIVE in kinds
    names = {c.name for c in controls}
    assert "off_by_one_boundary" in names
    assert "flipped_branch_order" in names


def test_discover_controls_filtered_by_kind(fixtures_root):
    task = load_task(fixtures_root / "healthy")
    known_bad = discover_controls(task, ControlKind.KNOWN_BAD)
    assert len(known_bad) == 1
    assert known_bad[0].kind == ControlKind.KNOWN_BAD


def test_discover_controls_empty_when_none_declared(fixtures_root):
    task = load_task(fixtures_root / "impossible_task")
    assert discover_controls(task) == []


def test_control_overlay_files_excludes_control_json(fixtures_root):
    task = load_task(fixtures_root / "healthy")
    known_bad = discover_controls(task, ControlKind.KNOWN_BAD)[0]
    files = known_bad.overlay_files()
    assert "control.json" not in files
    assert any(rel.endswith("core.py") for rel in files)


def test_expect_accept_defaults_by_kind(fixtures_root):
    task = load_task(fixtures_root / "healthy")
    for c in discover_controls(task):
        if c.kind == ControlKind.KNOWN_BAD:
            assert c.expect_accept is False
        elif c.kind == ControlKind.ALTERNATIVE:
            assert c.expect_accept is True


def test_load_integrity_config_defaults_when_absent(fixtures_root):
    task = load_task(fixtures_root / "healthy")
    config = load_integrity_config(task)
    assert config.declared_equivalent_mutants == ()
    assert config.mutation_timeout_s is None
    assert config.mutation_exclude_files == ()


def _write_control(task_dir, kind_dir, name, expect, description="d"):
    control_dir = task_dir / "integrity" / "controls" / kind_dir / name
    control_dir.mkdir(parents=True)
    spec = {"name": name, "description": description}
    if expect is not None:
        spec["expect"] = expect
    (control_dir / "control.json").write_text(json.dumps(spec))
    (control_dir / "placeholder.py").write_text("# overlay content\n")
    return control_dir


@pytest.mark.parametrize("bad_expect", ["accepted", "rejected", "yes", True, 1, []])
def test_malformed_expect_raises_value_error(tmp_path, bad_expect):
    """A typo or non-string in control.json's "expect" field must fail loudly
    at discovery time — silently defaulting would invert the control's
    meaning with no warning anywhere (the exact bug an independent code
    review of this engine found). A missing "expect" key entirely is
    NOT tested here — that's the legitimate, documented per-kind default."""
    task = _bare_task(tmp_path)
    control_dir = tmp_path / "integrity" / "controls" / "known_bad" / "bad"
    control_dir.mkdir(parents=True)
    spec = {"name": "bad", "description": "d", "expect": bad_expect}
    (control_dir / "control.json").write_text(json.dumps(spec))
    with pytest.raises(ValueError, match="expect"):
        discover_controls(task)


def test_expect_accept_and_reject_are_case_and_whitespace_insensitive(tmp_path):
    task = _bare_task(tmp_path)
    _write_control(tmp_path, "known_bad", "a", expect=" REJECT ")
    _write_control(tmp_path, "alternatives", "b", expect="Accept")
    controls = {c.name: c for c in discover_controls(task)}
    assert controls["a"].expect_accept is False
    assert controls["b"].expect_accept is True
