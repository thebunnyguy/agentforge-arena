"""Tests for the pack-level runner's failure isolation: one broken task must
never discard every other task's already-completed report (the bug an
independent code review of this engine found — a bare `future.result()`
propagated an exception straight out of `audit_pack`).
"""

import json
import shutil

from afa_integrity.model import AuditMode
from afa_integrity.pack import audit_pack


def test_one_broken_task_does_not_discard_other_reports(tmp_path, fixtures_root):
    """Copies the real 'healthy' fixture (a complete, working task) plus a
    second task directory with a malformed task.json into a scratch
    tasks_root, then asserts audit_pack still returns the healthy task's
    report and records the broken one in .failures instead of raising.
    """
    tasks_root = tmp_path / "tasks"
    tasks_root.mkdir()

    shutil.copytree(fixtures_root / "healthy", tasks_root / "good-task")

    broken_dir = tasks_root / "broken-task"
    broken_dir.mkdir()
    (broken_dir / "task.json").write_text("{ this is not valid json")

    summary = audit_pack(
        tasks_root=tasks_root,
        task_ids=["good-task", "broken-task"],
        mode=AuditMode.QUICK,
        workers=2,
    )

    assert "broken-task" in summary.failures
    assert summary.failures["broken-task"]  # non-empty error message

    # The healthy fixture's own task.json carries id "fixture-healthy" —
    # load_task reads that field, not the directory name it was copied to.
    audited_ids = {r.task_id for r in summary.reports}
    assert "fixture-healthy" in audited_ids
    assert len(summary.reports) == 1
