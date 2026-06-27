"""Background evaluation worker (Phase 5).

The worker mirrors ``examples/eval_persist.py``: it claims a queued job, loads
the selected tasks, constructs an agent ONCE per (model, backend), and for each
unit calls the frozen pipeline ``run_once`` and persists the record with
``SqliteRunStore.save_run``. It adds NO scoring — all of that stays in the
kernel/runner.

Testability: the per-job run logic accepts an INJECTED ``agent_factory``. The
default factory builds a deterministic offline :class:`~afa_runner.MockAgent`
overlaid with each task's ``reference/`` files (a passing mock, no Ollama). The
real Ollama/OpenAI-compat factory (plan Phase 7) plugs in the same way. This is
what makes the worker runnable in tests with no model server.

Run identity inside a job: ``idx`` is the repeat index for that (job, task).
Globally a run is still (agent, task_id, idx) in the raw layer; the job_runs
link + runs.job_id disambiguate repeats across jobs.

Cancellation is honored BETWEEN runs: before each unit we re-check the
cancel-requested flag and stop cleanly, marking the job ``canceled``.
"""

from __future__ import annotations

import os
import sqlite3
import sys
import time
import traceback
from pathlib import Path
from typing import Callable, Protocol

from . import db, jobs
from .db import ROOT
from .schemas import JobParams

# Make kernel + runner importable when only the repo root is on sys.path.
for _p in (ROOT / "kernel", ROOT / "runner", ROOT / "examples"):
    _s = str(_p)
    if _s not in sys.path:
        sys.path.insert(0, _s)

import afa_runner as afa  # noqa: E402
from afa_kernel.types import RunStatus  # noqa: E402

TASKS_DIR = ROOT / "tasks"


# --------------------------------------------------------------------------- #
# Agent factory (injection point)
# --------------------------------------------------------------------------- #

class Agent(Protocol):
    name: str

    def act(self, workspace, task, sandbox): ...  # noqa: D401,E704


# An AgentFactory builds an agent for a given (model, task, params). It is given
# the loaded Task so a passing mock can overlay that task's reference files.
AgentFactory = Callable[[str, "afa.Task", JobParams], Agent]


def _read_reference_writes(task: "afa.Task") -> dict[str, str]:
    """Overlay every reference/**/*.py file as a workspace write.

    Globs only ``*.py`` (NOT rglob('*')) because task dirs contain a non-UTF8
    ``.DS_Store`` that crashes ``read_text()``.
    """
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
    """Deterministic, offline, PASSING mock: overlays the task's reference files.

    No Ollama, no network. Verified to produce status=valid / S=1.0 / X=True on
    the captured anchor task.
    """
    return afa.MockAgent(name=model, writes=_read_reference_writes(task))


def ollama_agent_factory(model: str, task: "afa.Task", params: JobParams) -> Agent:
    """Real local-model factory (plan Phase 7). Local server only; no
    Authorization header (OpenAI-compat key is unsupported for generation)."""
    base_url = (params.backend.base_url or "http://localhost:11434").rstrip("/")
    return afa.OllamaAgent(
        name=model,
        model=model,
        base_url=base_url,
        temperature=params.temperature,
        base_seed=params.base_seed,
    )


def factory_for(params: JobParams) -> AgentFactory:
    """Pick the default factory for a job's backend kind."""
    if params.backend.kind in ("ollama", "openai_compat"):
        return ollama_agent_factory
    return mock_agent_factory


# --------------------------------------------------------------------------- #
# Per-job execution
# --------------------------------------------------------------------------- #

def _conn_db_path(conn: sqlite3.Connection) -> str:
    """Best-effort resolve the on-disk file backing a sqlite connection so the
    run store writes to the SAME database as the control plane."""
    try:
        for _seq, name, file in conn.execute("PRAGMA database_list"):
            if name == "main":
                return file or str(db.DB_PATH)
    except sqlite3.Error:  # pragma: no cover - defensive
        pass
    return str(db.DB_PATH)


def _completed_indices(
    store: "afa.SqliteRunStore", task_id: str, task_version: str, agent: str
) -> set[int]:
    """Resume idiom: idx already saved for the EXACT task_version."""
    return {
        r.idx
        for r in store.load_runs(task_id=task_id, agent=agent)
        if r.task_version == task_version
    }


def run_job(
    conn: sqlite3.Connection,
    job_id: str,
    *,
    agent_factory: AgentFactory | None = None,
    store: "afa.SqliteRunStore | None" = None,
    sandbox=None,
) -> None:
    """Execute a single ALREADY-CLAIMED (running) job to completion.

    Caller must have won ``claim_job`` first. Emits job_events, stamps
    runs.job_id + job_runs links, honors cancel between runs, and marks the
    terminal state. ``store``/``sandbox`` are injectable for tests; defaults are
    the on-disk store and a LocalSandbox.

    Reuses the frozen pipeline (run_once/grade/score_run) verbatim — no new
    scoring.
    """
    job = jobs.get_job(conn, job_id)
    if job is None:
        return
    params = job.params
    if agent_factory is None:
        agent_factory = factory_for(params)

    own_store = store is None
    if store is None:
        # Persist runs into the SAME db file the control-plane connection uses,
        # so job_runs links + runs.job_id stamps stay consistent across temp/live
        # databases. Fall back to the configured DB_PATH if the path is opaque.
        store = afa.SqliteRunStore(_conn_db_path(conn))
    if sandbox is None:
        sandbox = afa.LocalSandbox()

    jobs.append_event(
        conn, job_id, "job_started",
        {"model": params.model, "backend": params.backend.kind,
         "tasks": params.tasks, "repeats": params.repeats,
         "total_runs": job.counters.total_runs},
    )

    try:
        for task_id in params.tasks:
            try:
                task = afa.load_task(TASKS_DIR / task_id)
            except Exception as exc:  # unknown/broken task -> log, count failed
                jobs.append_event(
                    conn, job_id, "error",
                    {"task_id": task_id, "error": f"load_task failed: {exc}"},
                )
                jobs.bump_counters(conn, job_id, completed=params.repeats,
                                   failed=params.repeats)
                continue

            agent = agent_factory(params.model, task, params)
            done = _completed_indices(store, task_id, task.version, params.model)

            for idx in range(params.repeats):
                # Honor cancel BETWEEN runs.
                if jobs.is_cancel_requested(conn, job_id):
                    jobs.append_event(conn, job_id, "job_canceled",
                                      {"reason": "cancel requested"})
                    jobs.mark_terminal(conn, job_id, "canceled")
                    return

                if idx in done:
                    # A prior run for this (agent, task, version, idx) already
                    # exists. It is REUSED, not re-executed — surfaced as a
                    # distinct event + counter so the monitor never shows a
                    # reused run as if the model just ran.
                    jobs.append_event(
                        conn, job_id, "run_skipped",
                        {"task_id": task_id, "idx": idx,
                         "reason": "already completed (reused prior run)"},
                    )
                    jobs.bump_counters(conn, job_id, completed=1, reused=1)
                    fresh = jobs.get_job(conn, job_id)
                    jobs.append_event(
                        conn, job_id, "progress",
                        {"completed_runs": fresh.counters.completed_runs,
                         "total_runs": fresh.counters.total_runs,
                         "passed_runs": fresh.counters.passed_runs,
                         "voided_runs": fresh.counters.voided_runs,
                         "failed_runs": fresh.counters.failed_runs,
                         "reused_runs": fresh.counters.reused_runs},
                    )
                    continue

                jobs.append_event(conn, job_id, "run_started",
                                  {"task_id": task_id, "idx": idx})
                rec = afa.run_once(agent, task, sandbox=sandbox, idx=idx)
                jobs.append_event(
                    conn, job_id, "run_diff",
                    {"task_id": task_id, "idx": idx,
                     "files_changed": rec.files_changed,
                     "lines_added": rec.lines_added,
                     "lines_removed": rec.lines_removed},
                )
                jobs.append_event(
                    conn, job_id, "run_graded",
                    {"task_id": task_id, "idx": idx,
                     "status": rec.status.value,
                     "functional_pass": rec.score.functional_pass},
                )
                jobs.append_event(
                    conn, job_id, "run_scored",
                    {"task_id": task_id, "idx": idx,
                     "final_score": rec.score.final_score,
                     "voided": rec.score.voided},
                )

                run_id = store.save_run(rec, report=rec.grade_report)
                jobs.link_run(conn, job_id, run_id)
                jobs.append_event(
                    conn, job_id, "run_persisted",
                    {"task_id": task_id, "idx": idx, "run_id": run_id,
                     "status": rec.status.value},
                )

                passed = 1 if rec.score.functional_pass else 0
                voided = 1 if rec.status == RunStatus.INFRA_FAILURE else 0
                failed = 1 if (not rec.score.functional_pass and not voided) else 0
                jobs.bump_counters(conn, job_id, completed=1, passed=passed,
                                   voided=voided, failed=failed)

                fresh = jobs.get_job(conn, job_id)
                jobs.append_event(
                    conn, job_id, "progress",
                    {"completed_runs": fresh.counters.completed_runs,
                     "total_runs": fresh.counters.total_runs,
                     "passed_runs": fresh.counters.passed_runs,
                     "voided_runs": fresh.counters.voided_runs,
                     "failed_runs": fresh.counters.failed_runs,
                     "reused_runs": fresh.counters.reused_runs},
                )

        # One last cancel check before declaring success.
        if jobs.is_cancel_requested(conn, job_id):
            jobs.append_event(conn, job_id, "job_canceled",
                              {"reason": "cancel requested"})
            jobs.mark_terminal(conn, job_id, "canceled")
            return

        jobs.append_event(conn, job_id, "job_done", {"status": "succeeded"})
        jobs.mark_terminal(conn, job_id, "succeeded")
    except Exception as exc:  # pragma: no cover - defensive
        tb = traceback.format_exc()
        jobs.append_event(conn, job_id, "job_failed",
                          {"error": str(exc), "traceback": tb})
        jobs.mark_terminal(conn, job_id, "failed", error_message=str(exc))
    finally:
        if own_store:
            store.close()


def claim_and_run(
    conn: sqlite3.Connection,
    *,
    agent_factory: AgentFactory | None = None,
    store: "afa.SqliteRunStore | None" = None,
    sandbox=None,
) -> str | None:
    """Claim the next queued job and run it. Returns the job id run, or None if
    no job was claimable."""
    job_id = jobs.claim_next_queued(conn)
    if job_id is None:
        return None
    run_job(conn, job_id, agent_factory=agent_factory, store=store, sandbox=sandbox)
    return job_id


# --------------------------------------------------------------------------- #
# Process entrypoint: `python -m afa_api.worker`
# --------------------------------------------------------------------------- #

def serve(poll_interval: float = 2.0, db_path=None) -> None:
    """Long-running poll loop for the Docker `worker` service.

    Opens ONE app-side connection (WAL + busy_timeout) against the shared
    reports/runs.sqlite, ensures the additive app tables exist (idempotent),
    then claims and runs queued jobs one at a time. Adds NO scoring — every
    unit goes through the frozen pipeline via run_job/claim_and_run.

    The DB path resolves from AFA_DB_PATH (the Docker env contract) and falls
    back to the repo-relative default so this also runs bare on the host.
    """
    if db_path is None:
        db_path = os.environ.get("AFA_DB_PATH", str(db.DB_PATH))

    # Work on a copy of the evidence DB (seeded once), never the committed
    # reports/runs.sqlite. No-op when db_path already is/points at an existing DB.
    db.ensure_working_db(db_path)

    # Ensure the frozen raw layer (runs/run_scores/diffs/test_results) exists
    # before the additive migration touches runs.job_id. On the live DB this is
    # a no-op; on a fresh volume it creates the raw schema via the runner store
    # (idempotent — no scoring, no data written here).
    afa.SqliteRunStore(db_path).close()

    conn = db.connect(db_path)
    try:
        db.migrate(conn)  # idempotent, additive; never touches the raw layer
        reclaimed = jobs.reclaim_stale_running(conn)
        if reclaimed:
            print(f"[afa-worker] reclaimed {len(reclaimed)} stale running "
                  f"job(s): {reclaimed}", flush=True)
        print(f"[afa-worker] polling {db_path} every {poll_interval}s", flush=True)
        while True:
            try:
                ran = claim_and_run(conn)
            except Exception as exc:  # pragma: no cover - keep the loop alive
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
