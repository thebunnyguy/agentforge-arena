"""Isolation probe: can code being graded read the hidden tests it is being
graded against (mission §13/§14)?

"Never mounted in the agent workspace" (true — grading/ is never copied into
the directory an agent edits) is a different claim from "unreachable by the
code being graded" (false, by construction): grader.py materializes
grading/test_hidden.py into the SAME cleanroom directory the submission's code
runs from, before running the hidden suite (see afa_runner/grader.py's
_materialize_grading_suite call order). A submission that imports code able to
read files from its own cwd can read the hidden test source during grading.

This check both cites that static fact and empirically confirms it with a live
probe, then reports the result as CheckStatus.UNVERIFIABLE — never PASS or
FAIL — because there is nothing a task author can do to fix this under the
current LocalSandbox threat model (framework's own "deliberately still open"
item: real untrusted-agent isolation). afa_integrity.health explicitly excludes
this specific check from the health-status precedence function so this
limitation (present on every task) doesn't make every report UNVERIFIABLE and
drown out signal.
"""

from __future__ import annotations

import textwrap
import time
from pathlib import Path

from afa_runner.sandbox import Sandbox
from afa_runner.task import Task

from ..model import CheckStatus, IntegrityCheckResult, Severity
from ..overlay import grade_diff, overlay_files_diff, read_overlay_files

MARKER = "AFA_ISOLATION_PROBE_HIDDEN_TEST_READABLE"


def _editable_package_dir(task: Task) -> str | None:
    if not task.editable_paths:
        return None
    first = task.editable_paths[0]
    if not first.endswith("/**"):
        return None
    return first[: -len("/**")]


def run_isolation_probe(task: Task, sandbox: Sandbox) -> IntegrityCheckResult:
    start = time.monotonic()
    check_id = "isolation.hidden_test_readability"

    pkg_dir = _editable_package_dir(task)
    if pkg_dir is None:
        return IntegrityCheckResult(
            check_id=check_id,
            category="isolation_limitation",
            status=CheckStatus.SKIPPED,
            severity=Severity.LOW,
            description=(
                "Could not confidently derive the editable package directory "
                "from editable_paths; skipping the live probe. The static "
                "fact (grader.py materializes hidden tests into the same "
                "cleanroom directory the submission executes from, before "
                "running the hidden suite) still applies regardless."
            ),
            evidence={"editable_paths": list(task.editable_paths)},
            duration_ms=int((time.monotonic() - start) * 1000),
        )

    init_rel = f"{pkg_dir}/__init__.py"
    base_files: dict[str, str] = {}
    if task.reference_dir is not None:
        base_files = read_overlay_files(task.reference_dir)
    if init_rel not in base_files:
        init_path = task.snapshot_dir / init_rel
        base_files[init_rel] = init_path.read_text(encoding="utf-8") if init_path.is_file() else ""

    hidden_names = [Path(p).name for p in task.hidden.paths]
    probe_code = textwrap.dedent(
        f"""
        # --- afa_integrity isolation probe (appended) ---
        import os as _afa_os
        for _afa_name in {hidden_names!r}:
            if _afa_os.path.isfile(_afa_name):
                raise RuntimeError(
                    "{MARKER}: " + _afa_name + " cwd=" + _afa_os.getcwd()
                )
        """
    )
    base_files[init_rel] = base_files[init_rel] + "\n" + probe_code

    diff = overlay_files_diff(task, base_files)
    report, score = grade_diff(task, diff, sandbox, timeout_s=30)
    duration_ms = int((time.monotonic() - start) * 1000)

    combined_notes = (report.hidden.notes or "") + (report.regression.notes or "")
    marker_seen = MARKER in combined_notes

    evidence = {
        "probe_package_init": init_rel,
        "hidden_test_filenames_probed": hidden_names,
        "marker_observed_in_hidden_suite_notes": MARKER in (report.hidden.notes or ""),
        "marker_observed_in_regression_suite_notes": MARKER in (report.regression.notes or ""),
        "regression_all_passed": report.regression.all_passed,
        "static_evidence": (
            "afa_runner/afa_runner/grader.py materializes the hidden suite "
            "into the cleanroom root via _materialize_grading_suite BEFORE "
            "running it (grade(), step 4b), in the same directory the "
            "submission's own code executes from."
        ),
    }

    if marker_seen:
        return IntegrityCheckResult(
            check_id=check_id,
            category="isolation_limitation",
            status=CheckStatus.UNVERIFIABLE,
            severity=Severity.HIGH,
            description=(
                "CONFIRMED: code under grading can read the hidden test "
                "source during the hidden-suite run (the probe successfully "
                "detected and read the hidden test file from its own cwd). "
                "This is a known, deliberate limitation of the current "
                "trusted-local LocalSandbox threat model, not a defect in "
                "this task specifically — real untrusted-agent isolation "
                "(e.g. a network-disabled, filesystem-scoped DockerSandbox) "
                "is out of scope for this engine (mission §14/§25) and is "
                "tracked as a repo-wide 'deliberately still open' item."
            ),
            evidence=evidence,
            duration_ms=duration_ms,
        )

    return IntegrityCheckResult(
        check_id=check_id,
        category="isolation_limitation",
        status=CheckStatus.UNVERIFIABLE,
        severity=Severity.MEDIUM,
        description=(
            "The live probe did not observe its marker (regression suite may "
            "not import the probed package, or pytest's collection-error "
            "output was truncated before capture). The STATIC fact still "
            "holds regardless of this probe's outcome: grader.py "
            "materializes the hidden suite into the same directory the "
            "submission executes from before running it, so isolation "
            "cannot be asserted as guaranteed. Reported UNVERIFIABLE, not "
            "PASS — absence of a live confirmation is not evidence of "
            "isolation."
        ),
        evidence=evidence,
        duration_ms=duration_ms,
    )
