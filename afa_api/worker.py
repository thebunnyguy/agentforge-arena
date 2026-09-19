"""Background evaluation worker.

The worker executes frozen ``run_once`` scoring but persists each result through
one borrowed SQLite connection: raw evidence, its creating evaluation origin,
and the evaluation trial association become visible at one commit boundary.
"""

from __future__ import annotations

import os
import sqlite3
import sys
import threading
import time
import traceback
from pathlib import Path
from typing import Callable, Protocol

from . import db, evidence, jobs
from .db import ROOT
from .schemas import JobParams

for _p in (ROOT / "kernel", ROOT / "runner", ROOT / "examples"):
    _s = str(_p)
    if _s not in sys.path:
        sys.path.insert(0, _s)

import afa_runner as afa  # noqa: E402
TASKS_DIR = ROOT / "tasks"


class Agent(Protocol):
    name: str

    def act(self, workspace, task, sandbox): ...  # noqa: D401,E704


AgentFactory = Callable[[str, "afa.Task", JobParams], Agent]


def _read_reference_writes(task: "afa.Task") -> dict[str, str]:
    """Overlay reference Python files for the deterministic offline mock."""
    ref_dir = Path(task.reference_dir)
    writes: dict[str, str] = {}
    if not ref_dir.exists():
        return writes
    for path in ref_dir.glob("**/*.py"):
        rel = path.relative_to(ref_dir).as_posix()
        try:
            writes[rel] = path.read_text()
        except (UnicodeDecodeError, OSError):
            continue
    return writes


def mock_agent_factory(model: str, task: "afa.Task", params: JobParams) -> Agent:
    return afa.MockAgent(name=model, writes=_read_reference_writes(task))


def ollama_agent_factory(model: str, task: "afa.Task", params: JobParams) -> Agent:
    base_url = (params.backend.base_url or "http://localhost:11434").rstrip("/")
    return afa.OllamaAgent(
        name=model,
        model=model,
        base_url=base_url,
        temperature=params.temperature,
        base_seed=params.base_seed,
        request_timeout=params.request_timeout_s,
    )


def openai_compat_agent_factory(
    model: str, task: "afa.Task", params: JobParams
) -> Agent:
    base_url = (params.backend.base_url or "http://localhost:1234").rstrip("/")
    return afa.OpenAICompatAgent(
        name=model,
        model=model,
        base_url=base_url,
        temperature=params.temperature,
        base_seed=params.base_seed,
        request_timeout=params.request_timeout_s,
    )


# Each production factory declares which backend it really drives. The worker
# records THAT (not merely what was requested) as the run's provenance, so a
# mock-driven run can never be persisted as ollama/openai_compat evidence.
mock_agent_factory.backend_kind = "mock"  # type: ignore[attr-defined]
ollama_agent_factory.backend_kind = "ollama"  # type: ignore[attr-defined]
openai_compat_agent_factory.backend_kind = "openai_compat"  # type: ignore[attr-defined]


def factory_for(params: JobParams) -> AgentFactory:
    if params.backend.kind == "ollama":
        return ollama_agent_factory
    if params.backend.kind == "openai_compat":
        return openai_compat_agent_factory
    return mock_agent_factory


def _conn_db_path(conn: sqlite3.Connection) -> str:
    """Resolve an on-disk control DB for compatibility callers."""
    rows = conn.execute("PRAGMA database_list").fetchall()
    for row in rows:
        if row[1] == "main" and row[2]:
            return str(Path(row[2]).expanduser().resolve())
    raise RuntimeError(
        "cannot determine the control-plane database; use a bound connection"
    )


def _completed_indices(
    store: "afa.SqliteRunStore", task_id: str, task_version: str, agent: str
) -> set[int]:
    """Retained compatibility helper; new execution never uses global matches."""
    return {
        r.idx
        for r in store.load_runs(task_id=task_id, agent=agent)
        if r.task_version == task_version
    }


def _set_effective_seed(agent: Agent, seed: int) -> None:
    setter = getattr(agent, "set_run_seed", None)
    if callable(setter):
        setter(seed)


def _snapshot_task(snapshot: dict, task_id: str) -> dict | None:
    return next(
        (item for item in snapshot.get("tasks", []) if item.get("task_id") == task_id),
        None,
    )


def _load_snapshot_task(snapshot: dict, task_id: str) -> "afa.Task":
    expected = _snapshot_task(snapshot, task_id)
    if expected is None:
        raise jobs.JobStateError(f"task {task_id} is absent from evaluation snapshot")
    task = afa.load_task(TASKS_DIR / task_id)
    current = jobs.task_snapshot(task_id)
    if (
        task.version != expected.get("task_version")
        or current.get("task_digest") != expected.get("task_digest")
    ):
        raise jobs.JobStateError(
            f"task {task_id} changed since evaluation creation; refusing snapshot drift"
        )
    return task


def _progress(conn: sqlite3.Connection, job_id: str) -> None:
    jobs.refresh_counters(conn, job_id)
    fresh = jobs.get_job(conn, job_id)
    if fresh is None:
        return
    jobs.append_event(
        conn,
        job_id,
        "progress",
        {
            "completed_runs": fresh.counters.completed_runs,
            "total_runs": fresh.counters.total_runs,
            "passed_runs": fresh.counters.passed_runs,
            "voided_runs": fresh.counters.voided_runs,
            "failed_runs": fresh.counters.failed_runs,
            "reused_runs": fresh.counters.reused_runs,
        },
    )


def _release_claim(
    conn: sqlite3.Connection, evaluation_id: str, task_id: str, idx: int, token: str
) -> None:
    conn.execute(
        "UPDATE evaluation_trials SET trial_state='pending', claim_token=NULL, "
        "claimed_at=NULL WHERE evaluation_id=? AND task_id=? AND idx=? "
        "AND trial_state='claimed' AND claim_token=?",
        (evaluation_id, task_id, idx, token),
    )
    conn.commit()


def _fail_unverifiable(
    conn: sqlite3.Connection, job_id: str, owner: str, reason: str
) -> None:
    """Terminalise an evaluation that must not execute: its non-completed trials
    become blocked/unverifiable, no agent is created and no run is written."""
    for task_id in sorted(
        {
            row["task_id"]
            for row in jobs.trial_rows(conn, job_id)
            if row["trial_state"] != "completed"
        }
    ):
        jobs.mark_trial_unverifiable(
            conn, job_id, task_id, error_message=reason, owner_token=owner
        )
    jobs.append_event(conn, job_id, "error", {"error": reason})
    jobs.mark_terminal(conn, job_id, "failed", error_message=reason, owner_token=owner)


def run_job(
    conn: sqlite3.Connection,
    job_id: str,
    *,
    agent_factory: AgentFactory | None = None,
    store: "afa.SqliteRunStore | None" = None,
    sandbox=None,
    owner_token: str | None = None,
) -> None:
    """Execute one claimed evaluation while holding its same-host owner lock."""
    job = jobs.get_job(conn, job_id)
    if job is None:
        return
    # The dispatcher must pass the token it acquired. Reading a token here
    # would let a delayed old dispatcher adopt a successor after recovery.
    expected_owner = owner_token
    if expected_owner is None:
        return
    if jobs.is_unreadable(job):
        # The claim was made on the raw row; the API can only show a placeholder
        # for it. Fail it closed (fenced by our token) instead of abandoning a
        # phantom 'running' row that would be requeued forever.
        jobs.mark_terminal(
            conn, job_id, "failed", error_message=jobs.UNREADABLE_JOB_MESSAGE,
            owner_token=expected_owner,
        )
        return
    if job.status != "running":
        return
    lock = jobs.try_acquire_owner_lock(conn, job_id)
    if lock is None:
        return
    try:
        # A delayed dispatcher must not adopt a successor's token after a
        # process restart or stale-owner recovery.
        if jobs.owner_token(conn, job_id) != expected_owner:
            return
        _run_job_locked(
            conn,
            job_id,
            agent_factory=agent_factory,
            store=store,
            sandbox=sandbox,
            owner_token=expected_owner,
        )
    finally:
        lock.release()


def _run_job_locked(
    conn: sqlite3.Connection,
    job_id: str,
    *,
    agent_factory: AgentFactory | None = None,
    store: "afa.SqliteRunStore | None" = None,
    sandbox=None,
    owner_token: str,
) -> None:
    """Execute one evaluation after the caller acquired its owner lock."""
    job = jobs.get_job(conn, job_id)
    if job is None or job.status != "running":
        return
    snapshot = jobs.get_snapshot(conn, job_id)
    owner = owner_token
    if snapshot is None or job.mode == "legacy":
        jobs.mark_terminal(
            conn, job_id, "failed", error_message="missing evaluation snapshot",
            owner_token=owner,
        )
        return
    # Fail closed BEFORE any agent factory is chosen or called: corrupt persisted
    # parameters (or parameters that contradict the creation snapshot) must never
    # degrade to defaults, i.e. never run the reference-overlay mock agent.
    try:
        params = jobs.execution_params(conn, job_id)
    except jobs.InvalidPersistedParams as exc:
        _fail_unverifiable(conn, job_id, owner, str(exc))
        return
    if agent_factory is None:
        agent_factory = factory_for(params)
    declared_kind = getattr(agent_factory, "backend_kind", None)
    # The run records what the factory DECLARES it drives, i.e. what actually ran.
    # A factory that declares nothing (an injected test double) is not attested:
    # the run then carries NO provider of its own (NULL) and its class is derived
    # from the evaluation's REQUESTED backend, labelled provider_source
    # "evaluation". The evaluation snapshot keeps what was requested; a declared
    # kind that disagrees with it is surfaced as a conflict, never resolved silently.
    backend_kind = declared_kind if declared_kind in evidence.BACKEND_KINDS else None

    # The borrowed connection is essential: save_run(commit=False) and the
    # trial update must publish together. Injected stores remain for test seams,
    # but production/API callers use this same control-plane connection.
    close_store = False
    if store is None:
        store = afa.SqliteRunStore(connection=conn)
        close_store = True
    elif getattr(store, "_conn", None) is not conn:
        raise ValueError(
            "worker persistence store must borrow the claimed evaluation connection"
        )
    if sandbox is None:
        sandbox = afa.LocalSandbox()

    agents: dict[str, Agent] = {}
    jobs.refresh_counters(conn, job_id)
    jobs.append_event(
        conn,
        job_id,
        "job_started",
        {
            "model": params.model,
            "backend": params.backend.kind,
            "mode": job.mode,
            "tasks": [t.get("task_id") for t in snapshot.get("tasks", [])],
            "repeats": snapshot.get("repeats", params.repeats),
            "total_runs": job.counters.total_runs,
        },
    )

    try:
        for trial in jobs.trial_rows(conn, job_id):
            task_id = trial["task_id"]
            idx = int(trial["idx"])
            if not jobs.touch_owner(conn, job_id, owner):
                return
            if trial["trial_state"] == "completed":
                jobs.append_event(
                    conn,
                    job_id,
                    "run_skipped",
                    {
                        "task_id": task_id,
                        "idx": idx,
                        "run_id": trial["run_id"],
                        "reason": "completed evaluation trial",
                        "evidence_state": trial["evidence_state"],
                    },
                )
                _progress(conn, job_id)
                continue
            if trial["trial_state"] == "blocked":
                continue
            if jobs.is_cancel_requested(conn, job_id):
                jobs.append_event(conn, job_id, "job_canceled", {"reason": "cancel requested"})
                jobs.mark_terminal(conn, job_id, "canceled", owner_token=owner)
                return

            try:
                task = _load_snapshot_task(snapshot, task_id)
            except Exception as exc:
                jobs.mark_trial_unverifiable(
                    conn, job_id, task_id, error_message=str(exc), owner_token=owner
                )
                jobs.append_event(
                    conn, job_id, "error", {"task_id": task_id, "error": str(exc)}
                )
                continue

            claim = jobs.claim_trial(conn, job_id, task_id, idx, owner)
            if claim is None:
                # Another owner has the position; never execute it speculatively.
                continue
            try:
                agent = agents.get(task_id)
                if agent is None:
                    agent = agent_factory(params.model, task, params)
                    agents[task_id] = agent
                _set_effective_seed(agent, params.base_seed + idx)
                jobs.append_event(conn, job_id, "run_started", {"task_id": task_id, "idx": idx})
            except Exception:
                conn.rollback()
                _release_claim(conn, job_id, task_id, idx, claim)
                raise
            try:
                rec = afa.run_once(agent, task, sandbox=sandbox, idx=idx)
                jobs.append_event(
                    conn,
                    job_id,
                    "run_diff",
                    {
                        "task_id": task_id,
                        "idx": idx,
                        "files_changed": rec.files_changed,
                        "lines_added": rec.lines_added,
                        "lines_removed": rec.lines_removed,
                    },
                )
                jobs.append_event(
                    conn,
                    job_id,
                    "run_graded",
                    {
                        "task_id": task_id,
                        "idx": idx,
                        "status": rec.status.value,
                        "functional_pass": rec.score.functional_pass,
                    },
                )
                jobs.append_event(
                    conn,
                    job_id,
                    "run_scored",
                    {
                        "task_id": task_id,
                        "idx": idx,
                        "final_score": rec.score.final_score,
                        "voided": rec.score.voided,
                    },
                )
                # Raw rows and evaluation association are one transaction.
                run_id = store.save_run(
                    rec,
                    report=rec.grade_report,
                    commit=False,
                    job_id=job_id,
                    backend_kind=backend_kind,
                )
                jobs.complete_trial(
                    conn,
                    job_id,
                    task_id,
                    idx,
                    claim,
                    run_id,
                    owner_token=owner,
                    evidence_state="fresh",
                    origin_evaluation_id=job_id,
                )
                conn.commit()
            except Exception:
                conn.rollback()
                _release_claim(conn, job_id, task_id, idx, claim)
                raise

            jobs.append_event(
                conn,
                job_id,
                "run_persisted",
                {"task_id": task_id, "idx": idx, "run_id": run_id, "status": rec.status.value},
            )
            _progress(conn, job_id)

        if jobs.is_cancel_requested(conn, job_id):
            jobs.append_event(conn, job_id, "job_canceled", {"reason": "cancel requested"})
            jobs.mark_terminal(conn, job_id, "canceled", owner_token=owner)
            return
        jobs.refresh_counters(conn, job_id)
        if not jobs.all_trials_completed(conn, job_id):
            jobs.append_event(
                conn,
                job_id,
                "job_failed",
                {"error": "one or more evaluation trials have no verifiable evidence"},
            )
            jobs.mark_terminal(
                conn,
                job_id,
                "failed",
                error_message="one or more evaluation trials have no verifiable evidence",
                owner_token=owner,
            )
            return
        jobs.append_event(conn, job_id, "job_done", {"status": "succeeded"})
        jobs.mark_terminal(conn, job_id, "succeeded", owner_token=owner)
    except Exception as exc:
        # A failed attempt never fabricates a scored trial. The claimed row is
        # released when the failure occurred inside the persistence boundary.
        jobs.append_event(
            conn,
            job_id,
            "job_failed",
            {"error": str(exc), "traceback": traceback.format_exc()},
        )
        jobs.mark_terminal(
            conn, job_id, "failed", error_message=str(exc), owner_token=owner
        )
    finally:
        if close_store:
            store.close()


def claim_and_run(
    conn: sqlite3.Connection,
    *,
    agent_factory: AgentFactory | None = None,
    store: "afa.SqliteRunStore | None" = None,
    sandbox=None,
) -> str | None:
    # Standalone polling and API dispatch use the same fail-closed boundary.
    db.migrate(conn)
    claim = jobs.claim_next_queued_token(conn)
    if claim is None:
        return None
    job_id, token = claim
    run_job(
        conn,
        job_id,
        agent_factory=agent_factory,
        store=store,
        sandbox=sandbox,
        owner_token=token,
    )
    return job_id


def dispatch_job(db_path, job_id: str, *, agent_factory: AgentFactory | None = None) -> threading.Thread:
    """Dispatch through the same token-preserving path used by startup recovery."""
    def _work() -> None:
        conn = db.connect(db_path)
        token = None
        try:
            # Revalidate the control-plane schema at the actual dispatch
            # boundary; startup state alone must not authorize a later write.
            db.migrate(conn)
            token = jobs.claim_job_token(conn, job_id)
            if token is not None:
                run_job(conn, job_id, agent_factory=agent_factory, owner_token=token)
        except Exception as exc:  # noqa: BLE001 - last-resort safety net
            # A dispatch thread must never die silently and leave an evaluation
            # 'running' behind a live-looking owner: fail it (fenced by our token).
            if token is None:
                raise  # nothing was claimed: keep the thread traceback (job stays queued)
            try:
                jobs.mark_terminal(
                    conn, job_id, "failed",
                    error_message=f"dispatch failed: {type(exc).__name__}",
                    owner_token=token,
                )
            except Exception:  # noqa: BLE001
                traceback.print_exc()  # the secondary failure is logged, not hidden
        finally:
            conn.close()

    thread = threading.Thread(target=_work, name=f"afa-job-{job_id}", daemon=True)
    thread.start()
    return thread


def serve(poll_interval: float = 2.0, db_path=None) -> None:
    db_path = db.resolve_db_path(db_path)
    db.ensure_working_db(db_path)
    afa.SqliteRunStore(db_path).close()
    conn = db.connect(db_path)
    try:
        db.migrate(conn)
        try:
            reclaimed = jobs.reclaim_stale_running(conn, recover_unlocked=True)
        except jobs.RecoveryIncomplete as exc:
            # keep serving: the requeued jobs are picked up by the polling loop
            reclaimed = exc.recovered
            print(f"[afa-worker] recovery incomplete: {exc}", flush=True)
        except Exception as exc:  # noqa: BLE001 - never crash-loop the worker on startup
            reclaimed = []
            print(f"[afa-worker] recovery failed: {type(exc).__name__}", flush=True)
        if reclaimed:
            print(f"[afa-worker] reclaimed {len(reclaimed)} stale running job(s): {reclaimed}", flush=True)
        print(f"[afa-worker] polling {db_path} every {poll_interval}s", flush=True)
        while True:
            try:
                ran = claim_and_run(conn)
            except Exception as exc:  # pragma: no cover
                print(f"[afa-worker] claim error: {exc}", flush=True)
                ran = None
            if ran is None:
                time.sleep(poll_interval)
    finally:
        conn.close()


if __name__ == "__main__":
    try:
        serve(poll_interval=float(os.environ.get("AFA_WORKER_POLL_SECONDS", "2.0")))
    except KeyboardInterrupt:
        print("[afa-worker] shutting down", flush=True)
