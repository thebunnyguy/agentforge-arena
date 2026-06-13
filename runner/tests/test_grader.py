"""Tests for afa_runner.grader (framework §1, §8, §9).

These tests assert independently-reasoned expected behavior of clean-room
grading: parsing pytest JUnit XML, running suites, and assembling the kernel's
RunInput so score_run produces the intended S/X. Unit tests for parse_junit_xml
use hand-written XML; integration tests drive the real fix-list-dedup task.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from afa_kernel.scoring import score_run
from afa_kernel.types import QualityInputs, RunStatus
from afa_runner.diffing import capture_diff
from afa_runner.grader import (
    GradeReport,
    SuiteOutcome,
    grade,
    parse_junit_xml,
    run_pytest_suite,
)
from afa_runner.sandbox import LocalSandbox
from afa_runner.task import load_task

# Resolve the real benchmark task: <root>/tasks/fix-list-dedup.
# This test file lives at <root>/runner/tests/test_grader.py.
ROOT = Path(__file__).resolve().parents[2]
TASK_DIR = ROOT / "tasks" / "fix-list-dedup"


# --------------------------------------------------------------------------
# parse_junit_xml — hand-written XML strings
# --------------------------------------------------------------------------

def test_parse_all_passing():
    xml = (
        '<testsuites><testsuite name="pytest" errors="0" failures="0" '
        'skipped="0" tests="2">'
        '<testcase classname="test_hidden" name="test_a" time="0.01"/>'
        '<testcase classname="test_hidden" name="test_b" time="0.01"/>'
        "</testsuite></testsuites>"
    )
    outcome = parse_junit_xml(xml, {})

    assert len(outcome.results) == 2
    assert all(r.passed for r in outcome.results)
    assert {r.name for r in outcome.results} == {"test_a", "test_b"}
    assert outcome.all_passed is True
    assert outcome.errored is False
    # No weight overrides => default weight 1.0.
    assert all(r.weight == 1.0 for r in outcome.results)


def test_parse_failure_marks_not_passed():
    xml = (
        '<testsuites><testsuite errors="0" failures="1" tests="2">'
        '<testcase classname="m" name="ok"/>'
        '<testcase classname="m" name="bad">'
        '<failure message="boom">trace</failure>'
        "</testcase>"
        "</testsuite></testsuites>"
    )
    outcome = parse_junit_xml(xml, {})

    by_name = {r.name: r for r in outcome.results}
    assert by_name["ok"].passed is True
    assert by_name["bad"].passed is False
    assert outcome.all_passed is False
    assert outcome.errored is False


def test_parse_error_child_marks_not_passed():
    # A per-testcase <error> (e.g. fixture error) is a non-pass, but tests ran.
    xml = (
        '<testsuites><testsuite errors="0" failures="0" tests="1">'
        '<testcase classname="m" name="boom">'
        '<error message="setup error">trace</error>'
        "</testcase>"
        "</testsuite></testsuites>"
    )
    outcome = parse_junit_xml(xml, {})

    assert len(outcome.results) == 1
    assert outcome.results[0].passed is False
    assert outcome.all_passed is False
    # A testcase did run, so this is not a zero-test errored suite.
    assert outcome.errored is False


def test_parse_collection_error_is_errored():
    # Suite-level errors attribute => collection failed; treat suite as errored
    # even though a placeholder testcase appears.
    xml = (
        '<testsuites><testsuite errors="1" failures="0" tests="1">'
        '<testcase classname="" name="test_collerr">'
        '<error message="collection failure">ImportError</error>'
        "</testcase>"
        "</testsuite></testsuites>"
    )
    outcome = parse_junit_xml(xml, {})

    assert outcome.errored is True
    assert outcome.all_passed is False


def test_parse_skips_are_not_counted():
    xml = (
        '<testsuites><testsuite errors="0" failures="0" skipped="1" tests="2">'
        '<testcase classname="m" name="run"/>'
        '<testcase classname="m" name="skipped_one">'
        '<skipped type="pytest.skip" message="why"/>'
        "</testcase>"
        "</testsuite></testsuites>"
    )
    outcome = parse_junit_xml(xml, {})

    # The skipped case is ignored entirely; only the real test remains.
    assert len(outcome.results) == 1
    assert outcome.results[0].name == "run"
    assert outcome.all_passed is True
    assert outcome.errored is False


def test_parse_empty_suite_is_errored():
    xml = (
        '<testsuites><testsuite errors="0" failures="0" tests="0"/>'
        "</testsuites>"
    )
    outcome = parse_junit_xml(xml, {})

    assert outcome.results == ()
    assert outcome.errored is True
    assert outcome.all_passed is False


def test_parse_weight_override_file_qualified():
    xml = (
        '<testsuites><testsuite errors="0" failures="0" tests="2">'
        '<testcase classname="test_hidden" name="weighted"/>'
        '<testcase classname="test_hidden" name="plain"/>'
        "</testsuite></testsuites>"
    )
    weights = {"test_hidden.py::weighted": 3.0}
    outcome = parse_junit_xml(xml, weights)

    by_name = {r.name: r for r in outcome.results}
    # classname "test_hidden" -> file "test_hidden.py" -> node id matched.
    assert by_name["weighted"].weight == 3.0
    # Unmatched test keeps the default weight.
    assert by_name["plain"].weight == 1.0


def test_parse_weight_override_bare_name():
    xml = (
        '<testsuites><testsuite errors="0" failures="0" tests="1">'
        '<testcase classname="test_hidden" name="solo"/>'
        "</testsuite></testsuites>"
    )
    outcome = parse_junit_xml(xml, {"solo": 2.5})
    assert outcome.results[0].weight == 2.5


# --------------------------------------------------------------------------
# Helpers for integration tests: build the agent workspace + diff.
# --------------------------------------------------------------------------

def _build_diff(task, mutate, tmp_path):
    """Copy the pristine snapshot into a throwaway agent workspace, apply a
    `mutate(workspace)` edit, then capture the whole-file diff against the
    snapshot using the task's protected globs."""
    workspace = tmp_path / "agent_ws"
    shutil.copytree(task.snapshot_dir, workspace)
    mutate(workspace)
    return capture_diff(
        task.snapshot_dir, workspace, protected_globs=task.protected_paths
    )


def _apply_reference(task):
    """Return a mutate-fn that overlays the reference solution (correct fix)."""
    ref_file = task.reference_dir / "listkit" / "dedup.py"
    text = ref_file.read_text(encoding="utf-8")

    def mutate(ws: Path) -> None:
        (ws / "listkit" / "dedup.py").write_text(text, encoding="utf-8")

    return mutate


def _apply_buggy_sorted_fix(ws: Path) -> None:
    """A plausible-but-wrong fix: sorted(set(items)) removes duplicates (so
    regression still passes) but does not preserve first-occurrence order (so
    hidden order tests fail)."""
    (ws / "listkit" / "dedup.py").write_text(
        "def dedup(items):\n    return sorted(set(items))\n",
        encoding="utf-8",
    )


def _edit_protected_test(ws: Path) -> None:
    """Touch a protected test file (a scope violation) while also fixing the
    bug, so the only thing keeping the run from passing is scope_ok."""
    ref = (TASK_DIR / "reference" / "listkit" / "dedup.py").read_text(
        encoding="utf-8"
    )
    (ws / "listkit" / "dedup.py").write_text(ref, encoding="utf-8")
    vis = ws / "tests_visible" / "test_visible.py"
    vis.write_text(vis.read_text(encoding="utf-8") + "\n# tampered\n", encoding="utf-8")


# --------------------------------------------------------------------------
# Integration: the unmodified snapshot baseline (§8 task validity).
# --------------------------------------------------------------------------

def test_unmodified_snapshot_regression_passes_hidden_fails(tmp_path):
    """Sanity-anchor for the buggy/no-op cases below: with a non-empty but
    behavior-preserving touch (re-writing dedup.py with identical-but-reformatted
    code that is still buggy), regression passes and hidden does not."""
    task = load_task(TASK_DIR)
    sandbox = LocalSandbox()

    def keep_buggy(ws: Path) -> None:
        # Rewrite the buggy impl with a comment so diff_exists, but behavior is
        # unchanged (still set()-based, order lost).
        (ws / "listkit" / "dedup.py").write_text(
            "def dedup(items):\n    # still buggy\n    return list(set(items))\n",
            encoding="utf-8",
        )

    diff = _build_diff(task, keep_buggy, tmp_path)
    report = grade(task, diff, sandbox)

    # Regression (duplicate removal, flatten) still works on a set()-based impl.
    assert report.regression.all_passed is True
    assert report.regression.errored is False
    # Hidden order tests fail with a set()-based impl -> not all passed.
    assert report.hidden.all_passed is False
    assert report.hidden.errored is False


# --------------------------------------------------------------------------
# Integration: reference overlay (correct fix) => S=1.0, X=True.
# --------------------------------------------------------------------------

def test_reference_overlay_scores_perfect(tmp_path):
    task = load_task(TASK_DIR)
    sandbox = LocalSandbox()

    diff = _build_diff(task, _apply_reference(task), tmp_path)
    report = grade(task, diff, sandbox)

    # Every suite passes in the clean room.
    assert report.hidden.all_passed is True
    assert report.hidden.errored is False
    assert report.regression.all_passed is True

    gates = report.run_input.gates
    assert gates.setup_ok is True
    assert gates.diff_exists is True
    assert gates.scope_ok is True
    assert gates.regression_pass is True
    assert gates.no_timeout is True
    assert gates.product() == 1

    # Hidden results carried into the RunInput must be the actual graded tests.
    assert len(report.run_input.hidden) == 5
    assert all(t.passed for t in report.run_input.hidden)

    score = score_run(report.run_input)
    # Q defaults to 1.0 -> multiplier 1.0; all gates and hidden pass -> S=1.0.
    assert score.functional_pass is True
    assert score.final_score == 1.0
    assert score.voided is False


def test_reference_overlay_grades_deterministically(tmp_path):
    """Grader determinism (§9): three independent grades of the same diff yield
    identical scores."""
    task = load_task(TASK_DIR)
    sandbox = LocalSandbox()
    diff = _build_diff(task, _apply_reference(task), tmp_path)

    scores = []
    for _ in range(3):
        report = grade(task, diff, sandbox)
        s = score_run(report.run_input)
        scores.append((s.final_score, s.functional_pass))

    assert scores == [(1.0, True), (1.0, True)] + [(1.0, True)]
    assert len(set(scores)) == 1


# --------------------------------------------------------------------------
# Integration: no-op / empty diff => diff_exists gate False, G=0, S=0.
# --------------------------------------------------------------------------

def test_empty_diff_fails_diff_exists_gate(tmp_path):
    task = load_task(TASK_DIR)
    sandbox = LocalSandbox()

    # No mutation at all -> identical workspace -> empty diff.
    diff = _build_diff(task, lambda ws: None, tmp_path)
    assert diff.exists() is False

    report = grade(task, diff, sandbox)
    gates = report.run_input.gates
    assert gates.diff_exists is False
    assert gates.product() == 0

    score = score_run(report.run_input)
    assert score.final_score == 0.0
    assert score.functional_pass is False


# --------------------------------------------------------------------------
# Integration: scope violation (edits a protected test) => scope_ok False.
# --------------------------------------------------------------------------

def test_scope_violation_fails_scope_gate(tmp_path):
    task = load_task(TASK_DIR)
    sandbox = LocalSandbox()

    diff = _build_diff(task, _edit_protected_test, tmp_path)
    # The diff did touch a protected path.
    assert diff.touched_protected is True

    report = grade(task, diff, sandbox)
    gates = report.run_input.gates
    # Even though the source fix is correct, scope_ok is False.
    assert gates.scope_ok is False
    assert gates.product() == 0

    score = score_run(report.run_input)
    assert score.final_score == 0.0
    assert score.functional_pass is False


# --------------------------------------------------------------------------
# Integration: still-buggy fix => gates pass but hidden partial, X=False, 0<S<1.
# --------------------------------------------------------------------------

def test_buggy_sorted_fix_gates_pass_but_not_functional(tmp_path):
    task = load_task(TASK_DIR)
    sandbox = LocalSandbox()

    diff = _build_diff(task, _apply_buggy_sorted_fix, tmp_path)
    report = grade(task, diff, sandbox)

    gates = report.run_input.gates
    # sorted(set(...)) still removes duplicates -> regression passes; the diff
    # exists, touches no protected path, no timeout -> all gates pass (G=1).
    assert gates.regression_pass is True
    assert gates.diff_exists is True
    assert gates.scope_ok is True
    assert gates.product() == 1

    # But order tests in the hidden suite fail -> partial hidden, not all pass.
    assert report.hidden.all_passed is False
    assert any(not t.passed for t in report.run_input.hidden)
    assert any(t.passed for t in report.run_input.hidden)

    score = score_run(report.run_input)
    assert score.functional_pass is False
    # G=1 and some (but not all) hidden tests pass => 0 < S < 1.
    assert 0.0 < score.final_score < 1.0


# --------------------------------------------------------------------------
# Integration: INFRA_FAILURE short-circuits grading and voids the run.
# --------------------------------------------------------------------------

def test_infra_failure_short_circuits_and_voids(tmp_path):
    task = load_task(TASK_DIR)
    sandbox = LocalSandbox()

    diff = _build_diff(task, _apply_reference(task), tmp_path)
    report = grade(task, diff, sandbox, status=RunStatus.INFRA_FAILURE)

    assert report.status is RunStatus.INFRA_FAILURE
    assert report.run_input.status is RunStatus.INFRA_FAILURE
    # No grading happened: the hidden/regression suites are the empty sentinel.
    assert report.hidden.results == ()
    assert report.regression.results == ()

    score = score_run(report.run_input)
    assert score.voided is True
    assert score.final_score == 0.0
    assert score.functional_pass is False


# --------------------------------------------------------------------------
# timed_out flag flips the no_timeout gate.
# --------------------------------------------------------------------------

def test_timed_out_flag_fails_no_timeout_gate(tmp_path):
    task = load_task(TASK_DIR)
    sandbox = LocalSandbox()

    diff = _build_diff(task, _apply_reference(task), tmp_path)
    report = grade(task, diff, sandbox, timed_out=True)

    gates = report.run_input.gates
    assert gates.no_timeout is False
    assert gates.product() == 0
    assert score_run(report.run_input).final_score == 0.0


# --------------------------------------------------------------------------
# run_pytest_suite leaves no JUnit XML behind in the workspace.
# --------------------------------------------------------------------------

def test_run_pytest_suite_cleans_up_report(tmp_path):
    task = load_task(TASK_DIR)
    sandbox = LocalSandbox()

    # Build a real clean-room-like workspace: pristine snapshot + reference fix
    # + the hidden suite copied in.
    ws = tmp_path / "ws"
    shutil.copytree(task.snapshot_dir, ws)
    ref = (task.reference_dir / "listkit" / "dedup.py").read_text(encoding="utf-8")
    (ws / "listkit" / "dedup.py").write_text(ref, encoding="utf-8")
    src = task.task_dir / task.hidden.src
    shutil.copy2(src / task.hidden.paths[0], ws / task.hidden.paths[0])

    outcome = run_pytest_suite(
        sandbox, ws, list(task.hidden.paths), task.hidden.weights, task.timeout_s
    )
    assert outcome.all_passed is True
    assert outcome.errored is False

    # No JUnit report file should remain in the workspace.
    leftover = list(ws.glob(".afa_junit_*.xml"))
    assert leftover == []


def test_run_pytest_suite_empty_files_is_errored(tmp_path):
    sandbox = LocalSandbox()
    outcome = run_pytest_suite(sandbox, tmp_path, [], {}, 30)
    assert outcome.errored is True
    assert isinstance(outcome, SuiteOutcome)


# --------------------------------------------------------------------------
# grade returns a GradeReport with quality defaulting to QualityInputs().
# --------------------------------------------------------------------------

def test_grade_returns_report_with_default_quality(tmp_path):
    task = load_task(TASK_DIR)
    sandbox = LocalSandbox()
    diff = _build_diff(task, _apply_reference(task), tmp_path)

    report = grade(task, diff, sandbox)
    assert isinstance(report, GradeReport)
    # Quality defaults to QualityInputs() (all None) -> Q resolves to 1.0.
    assert report.run_input.quality == QualityInputs()
    assert score_run(report.run_input).q == 1.0


# --------------------------------------------------------------------------
# Clean-room bytecode hygiene (framework §9): a stale .pyc must never decide the
# grade. Even if the snapshot dir contains compiled bytecode for the OLD buggy
# source, grade() must run the freshly-applied source.
# --------------------------------------------------------------------------

def test_grade_ignores_stale_snapshot_bytecode(tmp_path):
    """Compile the buggy snapshot dedup.py to a real timestamp-based .pyc inside
    the snapshot's __pycache__, then grade the correct reference diff. grade()
    strips bytecode and runs pytest with -B, so the CORRECT applied source must
    be executed -> all hidden pass -> S=1.0, regardless of the stale .pyc."""
    import py_compile

    task = load_task(TASK_DIR)
    sandbox = LocalSandbox()

    pycache = task.snapshot_dir / "listkit" / "__pycache__"
    pyc = py_compile.compile(
        str(task.snapshot_dir / "listkit" / "dedup.py"), optimize=-1
    )
    try:
        assert Path(pyc).is_file()  # a stale buggy .pyc now sits in the snapshot

        diff = _build_diff(task, _apply_reference(task), tmp_path)
        report = grade(task, diff, sandbox)

        assert report.hidden.all_passed is True
        assert report.hidden.errored is False
        assert len(report.run_input.hidden) == 5
        assert score_run(report.run_input).final_score == 1.0
    finally:
        # Never leave compiled artifacts in the committed task fixture.
        shutil.rmtree(pycache, ignore_errors=True)


def test_grade_strips_bytecode_with_worst_case_pyc_collision(tmp_path):
    """The adversarial case from the finding: a stale buggy .pyc whose recorded
    source size+mtime are forced to match the applied correct source. Without
    stripping/-B, CPython would accept the stale bytecode and run the OLD buggy
    dedup. grade() must still execute the correct source."""
    import os
    import py_compile
    import struct

    task = load_task(TASK_DIR)
    sandbox = LocalSandbox()

    snap_dedup = task.snapshot_dir / "listkit" / "dedup.py"
    buggy_size = len(snap_dedup.read_bytes())
    pycache = task.snapshot_dir / "listkit" / "__pycache__"

    # Build a CORRECT order-preserving fix padded to EXACTLY the buggy source size
    # so a timestamp-based .pyc compiled from the buggy source can validate it.
    correct = (
        "def dedup(items):\n"
        "    seen = set()\n"
        "    out = []\n"
        "    for x in items:\n"
        "        if x not in seen:\n"
        "            seen.add(x)\n"
        "            out.append(x)\n"
        "    return out\n"
    )
    pad = buggy_size - len(correct.encode("utf-8"))
    assert pad >= 0, "correct fix unexpectedly larger than buggy source"
    correct_padded = correct + "#" * pad
    assert len(correct_padded.encode("utf-8")) == buggy_size

    pyc = Path(py_compile.compile(str(snap_dedup), optimize=-1))
    try:
        # Force the .pyc's recorded source mtime to a fixed whole second, and the
        # source size to the (shared) size, so it would validate the applied fix.
        data = bytearray(pyc.read_bytes())
        forced_mtime = 1781326603
        struct.pack_into("<I", data, 8, forced_mtime & 0xFFFFFFFF)
        struct.pack_into("<I", data, 12, buggy_size & 0xFFFFFFFF)
        pyc.write_bytes(bytes(data))

        def mutate(ws: Path) -> None:
            f = ws / "listkit" / "dedup.py"
            f.write_text(correct_padded, encoding="utf-8")
            os.utime(f, (forced_mtime, forced_mtime))

        diff = _build_diff(task, mutate, tmp_path)
        report = grade(task, diff, sandbox)

        # If the stale .pyc had been imported, the order tests would FAIL.
        assert report.hidden.all_passed is True, report.hidden.notes
        assert score_run(report.run_input).final_score == 1.0
    finally:
        shutil.rmtree(pycache, ignore_errors=True)


# --------------------------------------------------------------------------
# Determinism hardening (framework §9): a transient suite-level pytest error is
# retried before being accepted; a genuine test FAILURE is never retried.
# --------------------------------------------------------------------------

class _FlakySandbox:
    """Wraps a real sandbox; forces the first N pytest invocations to look like a
    transient collection failure (writes no JUnit report), then delegates."""

    def __init__(self, inner, flaky_runs: int) -> None:
        self._inner = inner
        self._remaining = flaky_runs
        self.calls = 0

    def run(self, cmd, cwd, timeout_s, env=None):
        self.calls += 1
        if self._remaining > 0 and "pytest" in (cmd if isinstance(cmd, str) else " ".join(cmd)):
            self._remaining -= 1
            # Simulate a crash before the JUnit report is written: run a no-op so
            # no .afa_junit_*.xml file appears -> run_pytest_suite sees errored.
            from afa_runner.sandbox import CommandResult

            return CommandResult(
                cmd="(forced-flaky pytest)",
                exit_code=1,
                stdout="",
                stderr="forced transient collection failure",
                duration_ms=1,
                timed_out=False,
            )
        return self._inner.run(cmd, cwd, timeout_s, env=env)


def test_run_pytest_suite_retries_transient_error(tmp_path):
    """A suite that errors transiently (no report) on the first attempt but
    succeeds on retry must come back as a clean, non-errored outcome."""
    task = load_task(TASK_DIR)
    inner = LocalSandbox()
    flaky = _FlakySandbox(inner, flaky_runs=1)

    ws = tmp_path / "ws"
    shutil.copytree(task.snapshot_dir, ws)
    ref = (task.reference_dir / "listkit" / "dedup.py").read_text(encoding="utf-8")
    (ws / "listkit" / "dedup.py").write_text(ref, encoding="utf-8")
    src = task.task_dir / task.hidden.src
    shutil.copy2(src / task.hidden.paths[0], ws / task.hidden.paths[0])

    outcome = run_pytest_suite(
        flaky, ws, list(task.hidden.paths), task.hidden.weights, task.timeout_s
    )
    # Despite the first flaky attempt, the retry produced a real, passing suite.
    assert outcome.errored is False
    assert outcome.all_passed is True
    assert flaky.calls >= 2  # at least one retry happened


def test_run_pytest_suite_errored_outcome_carries_notes(tmp_path):
    """A persistently-errored suite surfaces pytest diagnostics in notes so the
    flake is diagnosable (framework §9)."""
    task = load_task(TASK_DIR)
    inner = LocalSandbox()
    # Force EVERY attempt to be flaky so the suite stays errored after retries.
    flaky = _FlakySandbox(inner, flaky_runs=99)

    ws = tmp_path / "ws"
    shutil.copytree(task.snapshot_dir, ws)
    src = task.task_dir / task.hidden.src
    shutil.copy2(src / task.hidden.paths[0], ws / task.hidden.paths[0])

    outcome = run_pytest_suite(
        flaky, ws, list(task.hidden.paths), task.hidden.weights, task.timeout_s
    )
    assert outcome.errored is True
    assert outcome.notes  # non-empty diagnostics
    # Retried PYTEST_ERROR_RETRIES times after the first attempt.
    assert flaky.calls == 1 + 2


def test_run_pytest_suite_does_not_retry_genuine_failure(tmp_path):
    """A suite where tests actually RAN and one FAILED must be returned
    immediately (errored=False), never retried — retries are only for infra
    errors. The buggy snapshot makes hidden order tests genuinely fail."""
    task = load_task(TASK_DIR)

    class _CountingSandbox:
        def __init__(self, inner):
            self._inner = inner
            self.pytest_calls = 0

        def run(self, cmd, cwd, timeout_s, env=None):
            label = cmd if isinstance(cmd, str) else " ".join(cmd)
            if "pytest" in label:
                self.pytest_calls += 1
            return self._inner.run(cmd, cwd, timeout_s, env=env)

    counting = _CountingSandbox(LocalSandbox())

    ws = tmp_path / "ws"
    shutil.copytree(task.snapshot_dir, ws)  # buggy dedup left in place
    src = task.task_dir / task.hidden.src
    shutil.copy2(src / task.hidden.paths[0], ws / task.hidden.paths[0])

    outcome = run_pytest_suite(
        counting, ws, list(task.hidden.paths), task.hidden.weights, task.timeout_s
    )
    # Tests ran; some failed (order tests) -> not errored, NOT retried.
    assert outcome.errored is False
    assert outcome.all_passed is False
    assert any(not r.passed for r in outcome.results)
    assert counting.pytest_calls == 1
