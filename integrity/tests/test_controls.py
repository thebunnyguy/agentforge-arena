from afa_runner.task import load_task

from afa_integrity.controls import discover_controls, load_integrity_config
from afa_integrity.model import ControlKind


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
