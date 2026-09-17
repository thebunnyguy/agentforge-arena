"""Validate the validator (mission §22/§23): seven fixture tasks, each
engineered to represent one specific benchmark-integrity failure mode, run
through the REAL engine end to end (real grading, real subprocess pytest —
no mocking of afa_kernel/afa_runner). If the engine cannot tell these seven
scenarios apart correctly, its status field cannot be trusted on the real
task pack either.
"""

from __future__ import annotations

from afa_runner.sandbox import LocalSandbox
from afa_runner.task import load_task

from afa_integrity import AuditMode, ControlKind, run_audit
from afa_integrity.model import CheckStatus, Verdict


class FlipSandbox:
    """Test-only Sandbox wrapper: makes the hidden suite's outcome alternate
    deterministically across grades of the SAME artifact, by toggling an env
    var the flaky_benchmark fixture's hidden test reads. This is a controlled
    stand-in for real grader nondeterminism — a real random/os.urandom-based
    fixture would itself be flaky (per docs/agents/ORACLE.md's own note on
    this trap), so this makes the determinism DETECTOR's test deterministic
    instead.
    """

    def __init__(self) -> None:
        self._inner = LocalSandbox()
        self._grade_counter = 0

    def run(self, cmd, cwd, timeout_s, env=None):
        cmd_list = cmd if isinstance(cmd, list) else [cmd]
        is_hidden_run = any("test_hidden.py" in str(part) for part in cmd_list)
        merged_env = dict(env or {})
        if is_hidden_run:
            merged_env["AFA_TEST_FLAKY_TOGGLE"] = str(self._grade_counter % 2)
            self._grade_counter += 1
        else:
            merged_env.setdefault("AFA_TEST_FLAKY_TOGGLE", "0")
        return self._inner.run(cmd, cwd, timeout_s, env=merged_env)


def _load(fixtures_root, name):
    return load_task(fixtures_root / name)


def test_healthy_fixture_is_healthy_in_full_mode(fixtures_root):
    task = _load(fixtures_root, "healthy")
    report = run_audit(task, mode=AuditMode.FULL)
    assert report.status.value == "healthy", report.reason
    ref_check = next(c for c in report.checks if c.check_id == "reference.solution_validation")
    assert ref_check.status == CheckStatus.PASS
    mutation_check = next(c for c in report.checks if c.check_id == "mutation.generic_ast_mutants")
    assert mutation_check.status == CheckStatus.PASS
    assert all(m.verdict != Verdict.ACCEPTED or m.declared_equivalent for m in report.mutations)


def test_healthy_fixture_quick_mode_is_provisional_not_healthy(fixtures_root):
    """QUICK mode never claims HEALTHY (mission §6: PROVISIONAL when the
    audit ran less than the full evidence set)."""
    task = _load(fixtures_root, "healthy")
    report = run_audit(task, mode=AuditMode.QUICK)
    assert report.status.value == "provisional"


def test_broken_oracle_is_invalid(fixtures_root):
    task = _load(fixtures_root, "broken_oracle")
    report = run_audit(task, mode=AuditMode.QUICK)
    assert report.status.value == "invalid"
    bad = next(c for c in report.controls if c.kind == ControlKind.KNOWN_BAD)
    assert bad.verdict == Verdict.ACCEPTED
    assert bad.status == CheckStatus.FAIL
    assert not bad.matched_expectation


def test_impossible_task_is_invalid_via_reference_check(fixtures_root):
    task = _load(fixtures_root, "impossible_task")
    report = run_audit(task, mode=AuditMode.QUICK)
    assert report.status.value == "invalid"
    ref_check = next(c for c in report.checks if c.check_id == "reference.solution_validation")
    assert ref_check.status == CheckStatus.FAIL
    assert ref_check.evidence["repeats"][0]["functional_pass"] is False


def test_trivial_task_is_invalid_via_noop_check(fixtures_root):
    task = _load(fixtures_root, "trivial_task")
    report = run_audit(task, mode=AuditMode.QUICK)
    assert report.status.value == "invalid"
    noop_check = next(c for c in report.checks if c.check_id == "noop.unmodified_baseline")
    assert noop_check.status == CheckStatus.FAIL
    assert noop_check.evidence["hidden_all_passed"] is True


def test_overfitted_grader_is_needs_review_not_invalid(fixtures_root):
    task = _load(fixtures_root, "overfitted_grader")
    report = run_audit(task, mode=AuditMode.QUICK)
    assert report.status.value == "needs_review"
    alt = next(c for c in report.controls if c.kind == ControlKind.ALTERNATIVE)
    assert alt.verdict == Verdict.REJECTED_BY_HIDDEN_TEST
    assert alt.status == CheckStatus.FAIL


def test_flaky_benchmark_is_invalid_via_determinism(fixtures_root):
    task = _load(fixtures_root, "flaky_benchmark")
    sandbox = FlipSandbox()
    report = run_audit(task, mode=AuditMode.QUICK, sandbox=sandbox)
    assert report.status.value == "invalid"
    ref_check = next(c for c in report.checks if c.check_id == "reference.solution_validation")
    assert ref_check.status == CheckStatus.FAIL
    assert "GRADER_NONDETERMINISM" in ref_check.description
    assert ref_check.evidence["deterministic"] is False


def test_weak_hidden_suite_surfaces_a_surviving_mutant(fixtures_root):
    task = _load(fixtures_root, "weak_hidden_suite")
    report = run_audit(task, mode=AuditMode.FULL, max_mutants=30)
    assert report.status.value == "needs_review", report.reason
    mutation_check = next(c for c in report.checks if c.check_id == "mutation.generic_ast_mutants")
    assert mutation_check.status == CheckStatus.WARNING
    survived = [m for m in report.mutations if m.verdict == Verdict.ACCEPTED and not m.declared_equivalent]
    assert survived, "expected at least one surviving mutant on the untested upper boundary"
    assert any("120" in m.description or "core.py" in m.file for m in survived)
