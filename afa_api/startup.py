"""Control-plane startup boundary shared by the app lifespan and the lazy retry.

Two steps, recorded separately so neither can mask the other:

* additive migration  -> ``app.state.migrate_error`` (job/settings routes answer 503
  while it is set; the lazy retry in ``projection`` re-attempts it);
* same-host recovery of orphaned ``running`` evaluations, then dispatch
  -> ``app.state.recovery_error`` (surfaced by ``/healthz``; never cleared by a
  migration retry, only by a later successful recovery).
"""

from __future__ import annotations

from . import db, jobs, worker


def migrate_control_plane(app) -> bool:
    """Run the idempotent additive migration; True on success."""
    try:
        conn = db.connect(db.resolve_db_path(getattr(app.state, "db_path", None)))
        try:
            db.migrate(conn)
        finally:
            conn.close()
    except Exception as exc:  # noqa: BLE001 - the failure is the state
        app.state.migrate_error = str(exc)
        return False
    app.state.migrate_error = None
    return True


def recover_stale_jobs(app) -> None:
    """Fail closed / requeue orphaned running evaluations and dispatch the
    requeued ones. A failure is recorded, never swallowed."""
    db_path = db.resolve_db_path(getattr(app.state, "db_path", None))
    recovered: list[str] = []
    try:
        conn = db.connect(db_path)
        try:
            recovered = jobs.reclaim_stale_running(conn, recover_unlocked=True)
        finally:
            conn.close()
    except Exception as exc:  # noqa: BLE001 - the failure is the state
        app.state.recovery_error = str(exc)
        return
    app.state.recovery_error = None
    if getattr(app.state, "auto_dispatch", True):
        for job_id in recovered:
            worker.dispatch_job(
                db_path,
                job_id,
                agent_factory=getattr(app.state, "agent_factory", None),
            )
