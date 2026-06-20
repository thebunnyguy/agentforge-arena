"""Tests for afa_runner.diffing (framework §1, §9).

These tests assert independently-reasoned expected behavior of whole-file
diffing, scope checking, and clean-room application. They build small file
trees in tmp dirs rather than depending on any benchmark task.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from afa_runner.diffing import (
    Diff,
    apply_diff,
    capture_diff,
    path_is_always_protected,
    path_is_protected,
    snapshot_tree,
)


def _write(root: Path, rel: str, text: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


# --------------------------------------------------------------------------
# snapshot_tree
# --------------------------------------------------------------------------

def test_snapshot_tree_maps_relpaths_to_contents(tmp_path):
    _write(tmp_path, "a.py", "print('a')\n")
    _write(tmp_path, "pkg/b.py", "x = 1\n")

    tree = snapshot_tree(tmp_path)

    assert tree == {
        "a.py": "print('a')\n",
        "pkg/b.py": "x = 1\n",
    }
    # Keys are POSIX-style even for nested files.
    assert "pkg/b.py" in tree


def test_snapshot_tree_skips_ignored_dirs_and_suffixes(tmp_path):
    _write(tmp_path, "keep.py", "ok\n")
    _write(tmp_path, "__pycache__/cached.txt", "junk\n")
    _write(tmp_path, "pkg/__pycache__/nested.txt", "junk\n")
    _write(tmp_path, "mod.pyc", "compiled\n")
    _write(tmp_path, "mod.pyo", "compiled\n")

    tree = snapshot_tree(tmp_path)

    assert set(tree) == {"keep.py"}


def test_snapshot_tree_skips_undecodable_files(tmp_path):
    _write(tmp_path, "text.txt", "hello\n")
    # Invalid UTF-8 bytes (0xff 0xfe are not valid UTF-8 start bytes).
    (tmp_path / "binary.bin").write_bytes(b"\xff\xfe\x00\x01garbage\x80")

    tree = snapshot_tree(tmp_path)

    assert set(tree) == {"text.txt"}


def test_snapshot_tree_ignores_file_symlink_to_out_of_tree_content(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "secret.txt"
    outside.write_text("OUT-OF-TREE SECRET\n", encoding="utf-8")
    _write(root, "normal.py", "safe = True\n")
    try:
        (root / "leak.txt").symlink_to(outside)
    except OSError as exc:
        pytest.skip(f"symlinks unavailable on this platform: {exc}")

    assert snapshot_tree(root) == {"normal.py": "safe = True\n"}


def test_snapshot_tree_ignores_symlinked_directory_but_keeps_normal_tree(tmp_path):
    root = tmp_path / "root"
    external = tmp_path / "external"
    root.mkdir()
    external.mkdir()
    _write(root, "pkg/real.py", "REAL = 1\n")
    _write(external, "captured.py", "SECRET = 1\n")
    try:
        (root / "linked").symlink_to(external, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"directory symlinks unavailable on this platform: {exc}")

    tree = snapshot_tree(root)
    assert tree == {"pkg/real.py": "REAL = 1\n"}
    assert all("captured" not in path for path in tree)


# --------------------------------------------------------------------------
# path_is_protected
# --------------------------------------------------------------------------

def test_protected_double_star_prefix_matches_bare_and_nested():
    globs = ("**/test_*.py",)
    # Zero leading directories.
    assert path_is_protected("test_x.py", globs)
    # One or more leading directories.
    assert path_is_protected("tests_visible/test_visible.py", globs)
    assert path_is_protected("a/b/c/test_deep.py", globs)


def test_protected_double_star_suffix_matches_dir_and_contents():
    globs = ("tests_visible/**",)
    # Directory itself.
    assert path_is_protected("tests_visible", globs)
    # Anything directly under it.
    assert path_is_protected("tests_visible/anything.py", globs)
    # Anything nested under it.
    assert path_is_protected("tests_visible/sub/deep.py", globs)


def test_protected_does_not_match_unrelated_paths():
    globs = ("tests_visible/**", "**/test_*.py")
    assert not path_is_protected("listkit/dedup.py", globs)
    # Basename must START with "test_"; "mytest_" does not qualify.
    assert not path_is_protected("mytest_helper.py", globs)
    assert not path_is_protected("src/conftest.py", globs)


def test_protected_empty_globs_never_match():
    assert not path_is_protected("anything/at/all.py", ())


# --------------------------------------------------------------------------
# capture_diff
# --------------------------------------------------------------------------

def test_capture_unchanged_tree_is_empty(tmp_path):
    snap = tmp_path / "snap"
    mod = tmp_path / "mod"
    _write(snap, "a.py", "same\n")
    _write(mod, "a.py", "same\n")

    diff = capture_diff(snap, mod)

    assert diff.files_changed == 0
    assert diff.changed == {}
    assert diff.deleted == ()
    assert diff.lines_added == 0
    assert diff.lines_removed == 0
    assert diff.exists() is False


def test_capture_modified_file_records_new_text_and_line_counts(tmp_path):
    snap = tmp_path / "snap"
    mod = tmp_path / "mod"
    old = "line1\nline2\nline3\n"
    new = "line1\nCHANGED\nline3\nline4\n"
    _write(snap, "f.py", old)
    _write(mod, "f.py", new)

    diff = capture_diff(snap, mod)

    # Only f.py changed; deleted nothing.
    assert diff.files_changed == 1
    assert diff.changed == {"f.py": new}
    assert diff.deleted == ()
    # Independently reasoned: "line2" removed (-1); "CHANGED" and "line4"
    # added (+2). Headers (+++/---) excluded from counts.
    assert diff.lines_added == 2
    assert diff.lines_removed == 1
    assert diff.exists() is True


def test_capture_added_file(tmp_path):
    snap = tmp_path / "snap"
    mod = tmp_path / "mod"
    _write(snap, "keep.py", "k\n")
    _write(mod, "keep.py", "k\n")
    _write(mod, "new.py", "alpha\nbeta\n")

    diff = capture_diff(snap, mod)

    assert diff.changed == {"new.py": "alpha\nbeta\n"}
    assert diff.deleted == ()
    assert diff.files_changed == 1
    # Brand-new file: both lines are additions, no removals.
    assert diff.lines_added == 2
    assert diff.lines_removed == 0


def test_capture_deleted_file(tmp_path):
    snap = tmp_path / "snap"
    mod = tmp_path / "mod"
    _write(snap, "gone.py", "one\ntwo\nthree\n")
    _write(snap, "keep.py", "k\n")
    _write(mod, "keep.py", "k\n")

    diff = capture_diff(snap, mod)

    assert diff.changed == {}
    assert diff.deleted == ("gone.py",)
    assert diff.files_changed == 1
    # Deleted file contributes all three lines as removals.
    assert diff.lines_added == 0
    assert diff.lines_removed == 3


def test_capture_touched_protected_flag(tmp_path):
    snap = tmp_path / "snap"
    mod = tmp_path / "mod"
    _write(snap, "listkit/dedup.py", "buggy\n")
    _write(snap, "tests_visible/test_visible.py", "orig\n")
    _write(mod, "listkit/dedup.py", "fixed\n")
    # Agent illegally edited a protected test file.
    _write(mod, "tests_visible/test_visible.py", "tampered\n")

    protected = ("tests_visible/**", "**/test_*.py")
    diff = capture_diff(snap, mod, protected)
    assert diff.touched_protected is True

    # Without touching the protected file, the flag is False.
    mod2 = tmp_path / "mod2"
    _write(mod2, "listkit/dedup.py", "fixed\n")
    _write(mod2, "tests_visible/test_visible.py", "orig\n")
    diff2 = capture_diff(snap, mod2, protected)
    assert diff2.touched_protected is False


def test_capture_patch_text_renders_unified_diff(tmp_path):
    snap = tmp_path / "snap"
    mod = tmp_path / "mod"
    _write(snap, "f.py", "a\n")
    _write(mod, "f.py", "b\n")

    diff = capture_diff(snap, mod)

    # Audit rendering uses a/ b/ headers and shows the actual change.
    assert "a/f.py" in diff.patch_text
    assert "b/f.py" in diff.patch_text
    assert "-a\n" in diff.patch_text
    assert "+b\n" in diff.patch_text


# --------------------------------------------------------------------------
# apply_diff  (clean-room application / round-trip)
# --------------------------------------------------------------------------

def test_apply_diff_round_trip_reproduces_modified_tree(tmp_path):
    snap = tmp_path / "snap"
    mod = tmp_path / "mod"

    # Pristine snapshot.
    _write(snap, "listkit/dedup.py", "return list(set(items))\n")
    _write(snap, "listkit/keep.py", "untouched\n")
    _write(snap, "obsolete.py", "delete me\n")

    # Agent's modified workspace: change one file, add one, delete one.
    _write(mod, "listkit/dedup.py", "seen = set()\nreturn [x for x in items]\n")
    _write(mod, "listkit/keep.py", "untouched\n")
    _write(mod, "listkit/new_helper.py", "def helper():\n    pass\n")
    # obsolete.py intentionally absent (deleted by agent).

    diff = capture_diff(snap, mod)

    # Fresh pristine copy of the snapshot is the clean-room grade workspace.
    grade = tmp_path / "grade"
    for rel, text in snapshot_tree(snap).items():
        _write(grade, rel, text)

    apply_diff(diff, grade)

    # The clean room must now match the agent's modified tree exactly.
    assert snapshot_tree(grade) == snapshot_tree(mod)
    # And specifically: deleted file is gone, new file exists, change applied.
    assert not (grade / "obsolete.py").exists()
    assert (grade / "listkit/new_helper.py").exists()
    assert (grade / "listkit/dedup.py").read_text() == (mod / "listkit/dedup.py").read_text()


def test_apply_diff_creates_parent_dirs(tmp_path):
    target = tmp_path / "grade"
    target.mkdir()
    diff = Diff(
        changed={"deep/nested/new.py": "content\n"},
        deleted=(),
        files_changed=1,
        lines_added=1,
        lines_removed=0,
        touched_protected=False,
        patch_text="",
    )

    apply_diff(diff, target)

    assert (target / "deep/nested/new.py").read_text() == "content\n"


def test_apply_diff_deletion_of_missing_file_is_safe(tmp_path):
    target = tmp_path / "grade"
    target.mkdir()
    diff = Diff(
        changed={},
        deleted=("not_there.py",),
        files_changed=1,
        lines_added=0,
        lines_removed=0,
        touched_protected=False,
        patch_text="",
    )

    # Should not raise even though the file does not exist in target.
    apply_diff(diff, target)
    assert not (target / "not_there.py").exists()


# --------------------------------------------------------------------------
# Clean-room integrity: auto-executed config files (conftest.py, *.pth, ...)
# are ALWAYS protected, an editable allow-list turns the scope gate into an
# allow-list, and apply_diff refuses to carry auto-executed files into the
# clean room (findings: conftest-injection exploit + scope deny-list gap).
# --------------------------------------------------------------------------

def test_path_is_always_protected_flags_auto_executed_files():
    # conftest.py in any directory, plus the other interpreter/pytest auto-loads.
    for p in [
        "conftest.py",
        "listkit/conftest.py",
        "a/b/c/conftest.py",
        "sitecustomize.py",
        "usercustomize.py",
        "pytest.ini",
        "tox.ini",
        "setup.cfg",
        "pyproject.toml",
        "evil.pth",
        "site-packages/inject.pth",
        "Conftest.py",
        "CONFTEST.PY",
        "pkg\\Conftest.py",
        "SiteCustomize.py",
        "USERCUSTOMIZE.PY",
        "PyTest.InI",
        "EVIL.PTH",
        "site-packages/inject.PtH",
    ]:
        assert path_is_always_protected(p), p
    # Ordinary source/test files are NOT always-protected.
    for p in ["listkit/dedup.py", "test_hidden.py", "tests_visible/test_visible.py", "README.md"]:
        assert not path_is_always_protected(p), p


@pytest.mark.parametrize("name", ["Conftest.py", "CONFTEST.PY", "SiteCustomize.py", "hook.PTH"])
def test_capture_diff_case_variants_are_scope_violations(tmp_path, name):
    snap = tmp_path / "snap"
    mod = tmp_path / "mod"
    _write(snap, "pkg/core.py", "old\n")
    _write(mod, "pkg/core.py", "new\n")
    _write(mod, name, "malicious\n")

    diff = capture_diff(snap, mod, protected_globs=())
    assert name in diff.changed
    assert diff.touched_protected is True


def test_capture_diff_marks_conftest_injection_as_scope_violation(tmp_path):
    """An agent that leaves the buggy source but adds a root conftest.py (which
    pytest would auto-import and could use to monkeypatch the function under
    test) is a scope violation, even though conftest.py matches no protected
    glob and no editable allow-list is configured."""
    snap = tmp_path / "snap"
    mod = tmp_path / "mod"
    _write(snap, "listkit/dedup.py", "buggy\n")
    _write(mod, "listkit/dedup.py", "buggy\n")  # unchanged: bug NOT fixed
    _write(mod, "conftest.py", "import listkit\nlistkit.dedup = lambda x: x\n")

    # No protected globs catch conftest.py; the always-protected rule must.
    diff = capture_diff(snap, mod, protected_globs=())
    assert "conftest.py" in diff.changed
    assert diff.touched_protected is True


def test_capture_diff_marks_pth_and_sitecustomize_as_scope_violation(tmp_path):
    snap = tmp_path / "snap"
    mod = tmp_path / "mod"
    _write(snap, "listkit/dedup.py", "buggy\n")
    _write(mod, "listkit/dedup.py", "fixed\n")
    _write(mod, "evil.pth", "import os\n")
    _write(mod, "sitecustomize.py", "x = 1\n")

    diff = capture_diff(snap, mod, protected_globs=())
    assert diff.touched_protected is True


def test_editable_allowlist_enforced_as_allowlist(tmp_path):
    """With an editable allow-list, ANY changed path outside it is a scope
    violation — even an innocuous brand-new module — turning the scope gate from
    a deny-list into an allow-list."""
    snap = tmp_path / "snap"
    mod = tmp_path / "mod"
    _write(snap, "listkit/dedup.py", "buggy\n")
    _write(mod, "listkit/dedup.py", "fixed\n")
    _write(mod, "evilmod.py", "x = 1\n")  # outside listkit/**

    editable = ("listkit/**",)
    diff = capture_diff(snap, mod, protected_globs=(), editable_globs=editable)
    assert "evilmod.py" in diff.changed
    assert diff.touched_protected is True

    # The same edit WITHOUT the extra file stays in scope.
    mod2 = tmp_path / "mod2"
    _write(mod2, "listkit/dedup.py", "fixed\n")
    diff2 = capture_diff(snap, mod2, protected_globs=(), editable_globs=editable)
    assert diff2.touched_protected is False


def test_editable_allowlist_empty_is_backcompat_denylist_only(tmp_path):
    """An empty editable allow-list imposes no allow-list restriction: only the
    protected deny-list (and always-protected files) gate scope."""
    snap = tmp_path / "snap"
    mod = tmp_path / "mod"
    _write(snap, "listkit/dedup.py", "buggy\n")
    _write(mod, "listkit/dedup.py", "fixed\n")
    _write(mod, "anywhere/new.py", "x = 1\n")  # not protected, no allow-list

    diff = capture_diff(snap, mod, protected_globs=("**/test_*.py",), editable_globs=())
    assert diff.touched_protected is False


def test_apply_diff_refuses_auto_executed_files(tmp_path):
    """Defense in depth: even a Diff that lists an auto-executed config file must
    not write it into the clean room."""
    target = tmp_path / "grade"
    target.mkdir()
    diff = Diff(
        changed={
            "conftest.py": "import listkit\n",
            "Conftest.py": "import listkit\n",
            "evil.pth": "import os\n",
            "HOOK.PTH": "import os\n",
            "listkit/dedup.py": "fixed\n",
        },
        deleted=("sitecustomize.py",),
        files_changed=6,
        lines_added=5,
        lines_removed=1,
        touched_protected=True,
        patch_text="",
    )
    # Pre-seed a sitecustomize.py that a malicious deletion would try to remove;
    # apply_diff must leave it untouched (it refuses to act on protected paths).
    (target / "sitecustomize.py").write_text("pristine\n", encoding="utf-8")

    apply_diff(diff, target)

    # The legitimate source edit landed.
    assert (target / "listkit/dedup.py").read_text() == "fixed\n"
    # The auto-executed config files were NOT written into the clean room.
    assert not (target / "conftest.py").exists()
    assert not (target / "Conftest.py").exists()
    assert not (target / "evil.pth").exists()
    assert not (target / "HOOK.PTH").exists()
    # The protected deletion was refused (pristine file preserved).
    assert (target / "sitecustomize.py").read_text() == "pristine\n"
