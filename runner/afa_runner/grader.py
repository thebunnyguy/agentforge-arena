"""Clean-room grading (framework §1, §9).

Given a captured diff, build a pristine snapshot copy, apply ONLY the diff, run
the regression then hidden pytest suites (via JUnit XML), and assemble the
kernel's RunInput. The agent's workspace never touches this environment.
"""

from __future__ import annotations

import shutil
import sys
import tempfile
import uuid
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

from afa_kernel.types import Gates, QualityInputs, RunInput, RunStatus, TestResult

from .diffing import Diff, apply_diff
from .sandbox import Sandbox
from .task import Task, TestSuiteSpec


@dataclass(frozen=True)
class SuiteOutcome:
    """Per-suite pytest results, parsed from JUnit XML."""

    results: tuple[TestResult, ...]   # kernel TestResult (name, passed, weight)
    all_passed: bool
    errored: bool                     # collection error / no tests ran
    notes: str = ""                   # diagnostics (e.g. pytest output on error)


@dataclass(frozen=True)
class GradeReport:
    """Everything needed to score a run, plus diagnostics."""

    run_input: RunInput               # ready for afa_kernel.score_run
    status: RunStatus
    diff: Diff
    hidden: SuiteOutcome
    regression: SuiteOutcome
    setup_ok: bool
    timed_out: bool
    notes: str


def _weight_for(
    classname: str, name: str, weights: dict[str, float]
) -> float:
    """Resolve a test's weight from the task's weight overrides.

    Tries, in order: the file-qualified pytest node id ("<file>::<name>"),
    then the bare test name, then the default of 1.0. The JUnit ``classname``
    is pytest's dotted module path with no ".py" suffix (e.g. "test_hidden" or
    "pkg.test_hidden"); the task keys its weights by the pytest node id
    ("test_hidden.py::test_x"), so we reconstruct the file path from classname.
    """
    if not weights:
        return 1.0
    if classname:
        file_path = classname.replace(".", "/") + ".py"
        keyed = f"{file_path}::{name}"
        if keyed in weights:
            return float(weights[keyed])
        # Also accept the raw "classname::name" form, just in case a task keys
        # its weights that way.
        alt = f"{classname}::{name}"
        if alt in weights:
            return float(weights[alt])
    if name in weights:
        return float(weights[name])
    return 1.0


def parse_junit_xml(xml_text: str, weights: dict[str, float]) -> SuiteOutcome:
    """Parse a pytest JUnit XML report into a SuiteOutcome.

    Use xml.etree.ElementTree (stdlib). Each <testcase> is a pass unless it has
    a child <failure> or <error> (skips are ignored: not counted as tests).
    weight per test = weights.get("<file>::<name>") or weights.get(name) or 1.0.
    errored=True if the XML reports collection errors or zero testcases.
    Implements framework §1 (hidden-test grading).
    """
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        # Malformed / truncated XML: treat as an errored suite.
        return SuiteOutcome(results=(), all_passed=False, errored=True)

    # The root may be <testsuites> wrapping one or more <testsuite>, or a bare
    # <testsuite>. Collect every <testsuite> either way.
    if root.tag == "testsuite":
        suites = [root]
    else:
        suites = list(root.iter("testsuite"))

    # A suite-level collection error is reported via the testsuite's
    # errors="N" attribute, independent of per-testcase <error> children.
    collection_errors = 0
    for suite in suites:
        try:
            collection_errors += int(suite.get("errors", "0"))
        except (TypeError, ValueError):
            pass

    results: list[TestResult] = []
    all_passed = True
    for suite in suites:
        for case in suite.findall("testcase"):
            # A <skipped> testcase is not counted as a test at all.
            if case.find("skipped") is not None:
                continue
            passed = (
                case.find("failure") is None and case.find("error") is None
            )
            classname = case.get("classname", "") or ""
            name = case.get("name", "") or ""
            weight = _weight_for(classname, name, weights)
            results.append(
                TestResult(name=name, passed=passed, weight=weight)
            )
            if not passed:
                all_passed = False

    # errored: any collection error reported, or no testcases ran at all.
    errored = collection_errors > 0 or len(results) == 0
    if errored:
        all_passed = False

    return SuiteOutcome(
        results=tuple(results),
        all_passed=all_passed,
        errored=errored,
    )


# A suite that comes back errored (collection failure / zero tests collected /
# pytest crash before writing a report) is RETRIED this many times before being
# accepted as a genuine error. This protects the §9 grader-determinism invariant
# against transient pytest collection failures under CI parallelism: a real
# regression failure (tests ran and one FAILED) is never retried — only an
# infra-shaped suite-level error is (framework §9).
PYTEST_ERROR_RETRIES = 2


def _run_pytest_once(
    sandbox: Sandbox,
    workspace: Path,
    test_files: list[str],
    weights: dict[str, float],
    timeout_s: int,
) -> SuiteOutcome:
    """One pytest invocation -> SuiteOutcome. On any infra-shaped failure
    (timeout, crash, missing/unreadable report) returns an errored SuiteOutcome
    whose ``notes`` carry the pytest stdout/stderr for diagnosis."""
    workspace = Path(workspace)

    # Write the JUnit XML to a uniquely-named file inside the workspace so it
    # cannot collide with another suite's report nor be mistaken for a test.
    xml_name = f".afa_junit_{uuid.uuid4().hex}.xml"
    xml_path = workspace / xml_name

    # argv-direct (list) invocation: no shell, deterministic argument handling.
    # Use sys.executable (the interpreter running the runner) rather than a bare
    # "python" on PATH: it is the deterministic grading interpreter and is
    # guaranteed to have pytest available (framework §9 reproducibility).
    # -B forces source-based imports (never read a copied/stale .pyc), and
    # -p no:cacheprovider keeps the run from writing a .pytest_cache into the
    # clean room and decouples grading from any cache state (framework §9).
    cmd = [
        sys.executable,
        "-B",
        "-m",
        "pytest",
        f"--junitxml={xml_name}",
        "-p",
        "no:cacheprovider",
        "-o",
        "cache_dir=/dev/null",
        *test_files,
    ]

    try:
        result = sandbox.run(cmd, cwd=workspace, timeout_s=timeout_s)
        diag = (
            f"exit={result.exit_code} timed_out={result.timed_out}\n"
            f"--- stdout ---\n{result.stdout}\n--- stderr ---\n{result.stderr}"
        )
        if result.timed_out:
            return SuiteOutcome(
                results=(), all_passed=False, errored=True,
                notes="pytest timed out\n" + diag,
            )
        if not xml_path.is_file():
            # pytest crashed before writing the report (e.g. interpreter error).
            return SuiteOutcome(
                results=(), all_passed=False, errored=True,
                notes="pytest wrote no JUnit report\n" + diag,
            )
        try:
            xml_text = xml_path.read_text(encoding="utf-8")
        except OSError as exc:
            return SuiteOutcome(
                results=(), all_passed=False, errored=True,
                notes=f"could not read JUnit report: {exc}\n" + diag,
            )
        outcome = parse_junit_xml(xml_text, weights)
        if outcome.errored:
            # Surface pytest output so a transient collection error is diagnosable.
            return SuiteOutcome(
                results=outcome.results,
                all_passed=outcome.all_passed,
                errored=True,
                notes="suite errored (collection failure / zero tests)\n" + diag,
            )
        return outcome
    finally:
        # Remove the report so the clean-room workspace stays pristine and a
        # subsequent suite cannot accidentally read a stale report.
        try:
            xml_path.unlink()
        except OSError:
            pass


def run_pytest_suite(
    sandbox: Sandbox,
    workspace: Path,
    test_files: list[str],
    weights: dict[str, float],
    timeout_s: int,
) -> SuiteOutcome:
    """Run the given test files in workspace via `python -m pytest --junitxml`.

    Run with cwd=workspace so the task package imports (workspace on sys.path).
    Write JUnit XML to a temp file inside the workspace, read it back, and parse
    with parse_junit_xml. A pytest crash / timeout / missing XML => errored.

    Determinism hardening (framework §9): an *errored* suite (collection failure,
    zero tests collected, or a pytest crash — as opposed to tests that ran and
    FAILED) is retried up to PYTEST_ERROR_RETRIES times before being accepted as
    a real error. Transient collection failures under CI parallelism otherwise
    flip a deterministic perfect run to S=0. A suite that ran with genuine test
    failures is returned immediately and never retried.
    """
    workspace = Path(workspace)

    # Nothing to run: an empty suite is an errored (zero-test) suite per spec.
    if not test_files:
        return SuiteOutcome(
            results=(), all_passed=False, errored=True,
            notes="no test files supplied",
        )

    outcome = _run_pytest_once(sandbox, workspace, test_files, weights, timeout_s)
    attempts = 0
    while outcome.errored and attempts < PYTEST_ERROR_RETRIES:
        attempts += 1
        outcome = _run_pytest_once(
            sandbox, workspace, test_files, weights, timeout_s
        )
    return outcome


def _strip_bytecode(root: Path) -> None:
    """Remove every __pycache__ dir and stray .pyc/.pyo under root.

    Stale compiled bytecode must never be imported in the clean room: a
    timestamp-based .pyc whose recorded source size+mtime happen to match the
    applied fix is accepted by CPython, running OLD bytecode instead of the new
    source and producing a wrong, nondeterministic grade (framework §9). Belt to
    pytest's -B / PYTHONDONTWRITEBYTECODE, which prevent WRITING but not READING
    an already-present .pyc.
    """
    root = Path(root)
    for cache in root.rglob("__pycache__"):
        if cache.is_dir():
            shutil.rmtree(cache, ignore_errors=True)
    for pat in ("*.pyc", "*.pyo"):
        for f in root.rglob(pat):
            try:
                f.unlink()
            except OSError:
                pass


def _materialize_grading_suite(
    task: Task, suite: TestSuiteSpec, workspace: Path
) -> list[str]:
    """Copy a grading suite's files (from task <src> dir) into the clean-room
    workspace root and return the list of file names placed. Implements the
    hidden/regression-tests-never-in-agent-workspace rule (framework §8)."""
    workspace = Path(workspace)
    placed: list[str] = []

    # src is the subdirectory under task_dir holding the suite files (e.g.
    # "grading"). If src is None the files already live in the snapshot (a
    # visible suite) and are graded in place — nothing to copy.
    if suite.src is None:
        return list(suite.paths)

    src_dir = task.task_dir / suite.src
    for rel in suite.paths:
        source = src_dir / rel
        dest = workspace / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, dest)
        placed.append(rel)
    return placed


def grade(
    task: Task,
    diff: Diff,
    sandbox: Sandbox,
    *,
    status: RunStatus = RunStatus.VALID,
    setup_ok: bool = True,
    timed_out: bool = False,
    quality: QualityInputs | None = None,
) -> GradeReport:
    """Grade a captured diff in a clean room and build the RunInput.

    Steps:
      1. If status is INFRA_FAILURE -> return a GradeReport whose run_input has
         that status (the kernel voids it); skip grading.
      2. Fresh temp dir; copy task.snapshot_dir into it (pristine).
      3. apply_diff(diff, cleanroom).
      4. Materialize + run the REGRESSION suite; then materialize + run the
         HIDDEN suite. (Regression first: if pre-existing behavior broke, the
         run already fails its gate.)
      5. Build Gates:
           setup_ok        = setup_ok arg
           diff_exists     = diff.exists()
           scope_ok        = not diff.touched_protected
           regression_pass = regression.all_passed and not regression.errored
           no_timeout      = not timed_out
      6. RunInput(status, gates, hidden=hidden.results, quality=quality or QualityInputs()).
    Quality defaults to QualityInputs() (all None -> Q=1.0) in v0.1; lint/type
    hooks are optional and may be wired via the quality arg.
    Always clean up the temp dir.
    Implements framework §1 + §9.
    """
    quality = quality if quality is not None else QualityInputs()
    empty = SuiteOutcome(results=(), all_passed=False, errored=True)

    # 1. INFRA_FAILURE short-circuit: the platform failed, not the agent. Build
    #    a voided RunInput and skip all grading work entirely.
    if status is RunStatus.INFRA_FAILURE:
        gates = Gates(
            setup_ok=setup_ok,
            diff_exists=diff.exists(),
            scope_ok=not diff.touched_protected,
            regression_pass=False,
            no_timeout=not timed_out,
        )
        run_input = RunInput(
            status=status,
            gates=gates,
            hidden=(),
            quality=quality,
        )
        return GradeReport(
            run_input=run_input,
            status=status,
            diff=diff,
            hidden=empty,
            regression=empty,
            setup_ok=setup_ok,
            timed_out=timed_out,
            notes="infra_failure: grading skipped (run voided)",
        )

    # 2. Fresh clean-room temp dir; copy the pristine snapshot into it.
    #    Never copy compiled-bytecode artifacts: a stale __pycache__/*.pyc shipped
    #    in (or generated for) the snapshot can be timestamp-validated as current
    #    against a same-size/same-mtime applied fix, causing CPython to run the
    #    OLD buggy bytecode instead of the applied source -> wrong, nondeterministic
    #    grades (framework §9 clean-room hygiene). Strip them on copy, then sweep
    #    any that remain. (-B at pytest time is the belt; this is the suspenders.)
    tmp_root = Path(tempfile.mkdtemp(prefix="afa_grade_"))
    cleanroom = tmp_root / "cleanroom"
    regression = empty
    hidden = empty
    try:
        shutil.copytree(
            task.snapshot_dir,
            cleanroom,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo"),
        )
        _strip_bytecode(cleanroom)

        # 3. Apply ONLY the captured diff into the pristine copy. The agent's
        #    workspace/process never crosses into the clean room.
        apply_diff(diff, cleanroom)

        # 4a. Regression suite first: pre-existing behavior must still hold.
        regression_files = _materialize_grading_suite(
            task, task.regression, cleanroom
        )
        regression = run_pytest_suite(
            sandbox,
            cleanroom,
            regression_files,
            task.regression.weights,
            task.timeout_s,
        )

        # 4b. Hidden suite: the graded correctness signal.
        hidden_files = _materialize_grading_suite(
            task, task.hidden, cleanroom
        )
        hidden = run_pytest_suite(
            sandbox,
            cleanroom,
            hidden_files,
            task.hidden.weights,
            task.timeout_s,
        )

        # 5. Build the five hard gates (framework §1).
        gates = Gates(
            setup_ok=setup_ok,
            diff_exists=diff.exists(),
            scope_ok=not diff.touched_protected,
            regression_pass=regression.all_passed and not regression.errored,
            no_timeout=not timed_out,
        )

        # 6. Assemble the RunInput. Only the hidden results feed T_hidden.
        run_input = RunInput(
            status=status,
            gates=gates,
            hidden=hidden.results,
            quality=quality,
        )

        notes = (
            f"regression: {len(regression.results)} tests, "
            f"all_passed={regression.all_passed}, errored={regression.errored}; "
            f"hidden: {len(hidden.results)} tests, "
            f"all_passed={hidden.all_passed}, errored={hidden.errored}"
        )

        return GradeReport(
            run_input=run_input,
            status=status,
            diff=diff,
            hidden=hidden,
            regression=regression,
            setup_ok=setup_ok,
            timed_out=timed_out,
            notes=notes,
        )
    finally:
        # Always remove the clean-room temp tree (framework §9 reproducibility).
        shutil.rmtree(tmp_root, ignore_errors=True)
