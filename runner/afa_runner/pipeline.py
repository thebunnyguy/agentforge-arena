"""Run orchestration (framework §9 pipeline).

run_once: provision a fresh agent workspace from the snapshot, run the agent
(timed), capture the diff, grade it in a clean room, and score it with the
kernel. run_group: repeat n times for one (agent, task) and aggregate.
"""

from __future__ import annotations

import hashlib
import shutil
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from afa_kernel.aggregate import aggregate_runs
from afa_kernel.scoring import score_run
from afa_kernel.types import AggregateResult, RunScore, RunStatus

from .agents import Agent, AgentOutcome
from .diffing import Diff, capture_diff
from .grader import grade
from .sandbox import LocalSandbox, Sandbox
from .task import Task


@dataclass(frozen=True)
class RunRecord:
    """One executed run: its score plus provenance for storage/aggregation."""

    task_id: str
    task_version: str
    agent: str
    idx: int
    status: RunStatus
    score: RunScore
    files_changed: int
    lines_added: int
    lines_removed: int
    transcript_hash: str
    duration_ms: int


def transcript_hash(transcript: str, patch_text: str) -> str:
    """SHA-256 over (agent transcript || captured patch) for determinism
    detection (framework §2). Two runs with equal hashes are identical."""
    h = hashlib.sha256()
    h.update(transcript.encode("utf-8", "replace"))
    h.update(b"\0")
    h.update(patch_text.encode("utf-8", "replace"))
    return "sha256:" + h.hexdigest()


def run_once(
    agent: Agent,
    task: Task,
    *,
    sandbox: Sandbox | None = None,
    idx: int = 0,
) -> RunRecord:
    """Execute one run end to end.

    1. Fresh temp workspace; copy task.snapshot_dir into it.
    2. Time agent.act(workspace, task, sandbox). On exception or outcome.errored
       -> status AGENT_ERROR. If wall-clock exceeds task.timeout_s -> TIMEOUT
       (timed_out gate). (LocalSandbox enforces per-command timeouts too.)
    3. capture_diff(snapshot, workspace, task.protected_paths).
    4. grade(...) in a clean room -> RunInput; score_run -> RunScore.
    5. Build RunRecord (transcript_hash from agent transcript + diff.patch_text).
    Always tear down the workspace. Default sandbox is LocalSandbox().
    Implements framework §9.
    """
    if sandbox is None:
        sandbox = LocalSandbox()

    # 1. Fresh, isolated agent workspace: a writable copy of the pristine
    #    snapshot. Kept in its own temp tree so it is torn down in finally.
    tmp_root = Path(tempfile.mkdtemp(prefix="afa_agent_"))
    workspace = tmp_root / "workspace"
    try:
        shutil.copytree(task.snapshot_dir, workspace)

        # 2. Run the agent, timed by wall-clock. An exception or an errored
        #    outcome maps to AGENT_ERROR; exceeding task.timeout_s maps to
        #    TIMEOUT. Either way we still capture whatever the agent left behind
        #    so the diff/scope gates remain meaningful.
        status = RunStatus.VALID
        timed_out = False
        start = time.monotonic()
        try:
            outcome = agent.act(workspace, task, sandbox)
        except Exception as exc:  # the agent crashed: no usable attempt.
            outcome = AgentOutcome(
                transcript=f"AGENT_EXCEPTION: {type(exc).__name__}: {exc}",
                errored=True,
            )
        duration_ms = int((time.monotonic() - start) * 1000)

        if duration_ms > task.timeout_s * 1000:
            # The agent blew the wall-clock budget. TIMEOUT flips the no_timeout
            # gate (G=0, S=0) and is counted in n as a failure.
            status = RunStatus.TIMEOUT
            timed_out = True
        elif outcome.infra_failed:
            # Infrastructure failure (e.g. the model server is unreachable):
            # VOIDED, excluded from n, never held against the agent (§1).
            # Checked before `errored` so a transport failure is never miscounted
            # as an agent loss.
            status = RunStatus.INFRA_FAILURE
        elif outcome.errored:
            status = RunStatus.AGENT_ERROR

        # 3. Capture the whole-file diff of the agent's edits against the
        #    pristine snapshot, honoring the task's protected globs and (when
        #    configured) its editable allow-list. The allow-list catches injected
        #    files outside the agent's remit (e.g. conftest.py) as scope
        #    violations (framework §8/§9 clean-room integrity).
        diff: Diff = capture_diff(
            task.snapshot_dir,
            workspace,
            protected_globs=task.protected_paths,
            editable_globs=task.editable_paths,
        )

        # 4. Grade the captured diff in a SEPARATE clean room (a fresh snapshot
        #    copy that the agent's workspace/process never touched). The grader
        #    builds the RunInput; the kernel scores it.
        report = grade(
            task,
            diff,
            sandbox,
            status=status,
            setup_ok=True,
            timed_out=timed_out,
        )
        score = score_run(report.run_input)

        # 5. Provenance: hash (transcript || captured patch) for determinism
        #    detection (framework §2). The status carried on the RunScore is the
        #    authoritative one (it survived score_run's INFRA_FAILURE handling).
        thash = transcript_hash(outcome.transcript, diff.patch_text)

        return RunRecord(
            task_id=task.id,
            task_version=task.version,
            agent=agent.name,
            idx=idx,
            status=score.status,
            score=score,
            files_changed=diff.files_changed,
            lines_added=diff.lines_added,
            lines_removed=diff.lines_removed,
            transcript_hash=thash,
            duration_ms=duration_ms,
        )
    finally:
        # Always tear down the agent workspace (framework §9 reproducibility).
        shutil.rmtree(tmp_root, ignore_errors=True)


def run_group(
    agent: Agent,
    task: Task,
    n: int,
    *,
    sandbox: Sandbox | None = None,
) -> list[RunRecord]:
    """Run the same (agent, task) n times, returning n RunRecords (idx 0..n-1).

    The SAME agent instance is reused across runs (so a stateful SequenceAgent
    varies its output). Each run gets fresh workspaces. Implements framework §9.
    """
    return [
        run_once(agent, task, sandbox=sandbox, idx=i)
        for i in range(n)
    ]


def aggregate_group(records: list[RunRecord]) -> AggregateResult:
    """Aggregate a run group with the kernel.

    Pass each record's RunScore and the aligned transcript_hashes (in idx order,
    voided runs excluded by the kernel) to afa_kernel.aggregate_runs.
    Implements framework §2.
    """
    # Records arrive in idx order from run_group; sort defensively so an aligned
    # hash sequence is well-defined regardless of caller ordering.
    ordered = sorted(records, key=lambda r: r.idx)
    scores = [r.score for r in ordered]

    # The kernel aligns transcript_hashes 1:1 with the VALID (non-voided) runs.
    # INFRA_FAILURE runs are voided and excluded from n_valid, so their hashes
    # must NOT be supplied or the length check fails and determinism detection is
    # silently skipped. Filter to non-voided records, preserving idx order.
    hashes = [
        r.transcript_hash
        for r in ordered
        if r.status is not RunStatus.INFRA_FAILURE
    ]
    return aggregate_runs(scores, transcript_hashes=hashes)


def validate_task(task: Task, sandbox: Sandbox | None = None) -> dict:
    """Run the §8 benchmark CI / anti-gaming checks for one task.

    A well-formed task must satisfy two invariants, both graded in the clean
    room (framework §8):

      1. EMPTY DIFF (unmodified snapshot): the regression suite PASSES (the
         pre-existing behavior is intact) and the hidden suite does NOT fully
         pass (there is a real bug to fix, so the task is not trivially solved).
         The empty diff also fails the diff_exists gate, so its score is 0.

      2. REFERENCE OVERLAY (canonical fix copied over the snapshot): every
         hidden + regression test passes, all gates hold, so the kernel gives
         final_score == 1.0 and functional_pass (X) == True; AND the grade
         reproduces IDENTICALLY three times (grader determinism, framework §9).

    Returns a diagnostics dict. Raises AssertionError (with a descriptive
    message) if any invariant is violated, so this doubles as a CI gate.
    Requires task.reference_dir to be present.
    """
    if sandbox is None:
        sandbox = LocalSandbox()
    if task.reference_dir is None:
        raise AssertionError(
            f"task {task.id} has no reference_dir; cannot validate §8 invariants"
        )

    results: dict = {"task_id": task.id, "task_version": task.version}

    # ----- Invariant 1: the empty diff (unmodified snapshot). -----------------
    empty_diff = capture_diff(
        task.snapshot_dir,
        task.snapshot_dir,
        protected_globs=task.protected_paths,
        editable_globs=task.editable_paths,
    )
    assert not empty_diff.exists(), (
        f"empty diff must touch no files; got {empty_diff.files_changed}"
    )
    empty_report = grade(task, empty_diff, sandbox)
    empty_score = score_run(empty_report.run_input)

    assert empty_report.regression.all_passed and not empty_report.regression.errored, (
        "unmodified snapshot: regression suite must PASS "
        f"(all_passed={empty_report.regression.all_passed}, "
        f"errored={empty_report.regression.errored})"
    )
    assert not empty_report.hidden.all_passed, (
        "unmodified snapshot: hidden suite must NOT fully pass "
        "(there must be a real bug to fix)"
    )
    # The empty diff fails diff_exists, so the run cannot score or pass.
    assert empty_report.run_input.gates.diff_exists is False, (
        "empty diff must fail the diff_exists gate"
    )
    assert empty_score.final_score == 0.0, (
        f"empty diff must score 0.0; got {empty_score.final_score}"
    )
    assert empty_score.functional_pass is False, (
        "empty diff must not be a functional pass"
    )

    results["empty"] = {
        "regression_all_passed": empty_report.regression.all_passed,
        "hidden_all_passed": empty_report.hidden.all_passed,
        "n_hidden": len(empty_report.hidden.results),
        "final_score": empty_score.final_score,
        "functional_pass": empty_score.functional_pass,
    }

    # ----- Invariant 2: the reference overlay (canonical fix). ----------------
    # Overlay the reference solution onto a throwaway agent workspace and capture
    # the resulting diff, exactly as run_once would for a perfect agent.
    ref_diff = _reference_diff(task)
    assert ref_diff.exists(), "reference overlay produced an empty diff"

    ref_scores: list[tuple[float, bool]] = []
    for _ in range(3):
        report = grade(task, ref_diff, sandbox)
        s = score_run(report.run_input)
        ref_scores.append((s.final_score, s.functional_pass))

    first = ref_scores[0]
    assert first == (1.0, True), (
        f"reference overlay must score (1.0, X=True); got {first}"
    )
    assert all(rs == first for rs in ref_scores), (
        f"reference overlay must grade deterministically; got {ref_scores}"
    )
    assert len(set(ref_scores)) == 1, (
        f"reference overlay grades must be identical 3x; got {ref_scores}"
    )

    results["reference"] = {
        "final_score": first[0],
        "functional_pass": first[1],
        "reproduced_identically_3x": len(set(ref_scores)) == 1,
        "repeats": ref_scores,
    }
    results["valid"] = True
    return results


def _reference_diff(task: Task) -> Diff:
    """Overlay the task's reference solution onto a throwaway snapshot copy and
    capture the resulting diff. The temp tree is always removed."""
    if task.reference_dir is None:
        raise AssertionError(f"task {task.id} has no reference_dir")

    tmp_root = Path(tempfile.mkdtemp(prefix="afa_ref_"))
    workspace = tmp_root / "workspace"
    try:
        shutil.copytree(task.snapshot_dir, workspace)
        # Overlay every file from the reference dir onto the snapshot copy,
        # preserving subdirectory structure (e.g. listkit/dedup.py).
        ref_root = Path(task.reference_dir)
        for src in sorted(ref_root.rglob("*")):
            if not src.is_file():
                continue
            rel = src.relative_to(ref_root)
            dest = workspace / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)
        return capture_diff(
            task.snapshot_dir,
            workspace,
            protected_globs=task.protected_paths,
            editable_globs=task.editable_paths,
        )
    finally:
        shutil.rmtree(tmp_root, ignore_errors=True)
