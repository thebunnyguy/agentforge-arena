import { Link } from "react-router-dom";
import type { Job, JobEvent } from "../api/types";
import { PARAMS_UNAVAILABLE_TITLE, jobParamsView } from "../lib/jobParams";
import {
  mergeRunViews,
  projectEventTape,
  projectTrials,
  runStateLabel,
  runStateSymbol,
} from "../lib/jobView";
import type { PersistedTrial } from "../lib/jobView";

export function TaskRunGrid({
  job,
  events,
  trials = null,
  historyLoading = false,
  historyError = null,
}: {
  job: Job;
  events: JobEvent[];
  /** This evaluation's persisted trial rows (GET /jobs/{id}/results or the
   * report). When given, they outrank the event tape for every position they
   * record, so a gap in the event history no longer hides a stored outcome. */
  trials?: PersistedTrial[] | null;
  historyLoading?: boolean;
  historyError?: Error | null;
}) {
  const view = jobParamsView(job);
  if (!view.available)
    return (
      <p className="note muted">
        {PARAMS_UNAVAILABLE_TITLE}: the task and repeat grid cannot be built
        without verified parameters.
      </p>
    );
  const { tasks, repeats } = view;
  const projection = projectEventTape(events);
  const persisted = trials ? projectTrials(trials) : null;
  // Persisted rows say which positions exist and whether they finished, so a
  // missing event history only matters when there are no rows to fall back on.
  const historyIncomplete =
    persisted === null && (historyLoading || historyError !== null);
  const terminal =
    job.status === "succeeded" ||
    job.status === "failed" ||
    job.status === "canceled";
  return (
    <div className="task-run-grid">
      {tasks.map((taskId) => {
        const taskError = projection.taskErrors.get(taskId);
        return (
          <div className="task-run-row" key={taskId}>
            <span className="task-run-label">
              {taskId}
              {taskError && (
                <span className="task-error-label" title={taskError}>
                  {" "}
                  · worker error
                </span>
              )}
            </span>
            <div className="run-markers">
              {Array.from({ length: repeats }).map((_, idx) => {
                const key = `${taskId}:${idx}`;
                const stored = persisted?.get(key);
                const run = mergeRunViews(stored, projection.runs.get(key));
                // A stored row still pending/claimed after the evaluation
                // ended never ran to completion: use the terminal fallback.
                const unfinishedAfterEnd =
                  terminal &&
                  run !== undefined &&
                  run === stored &&
                  (run.state === "pending" || run.state === "running");
                const state =
                  run && !unfinishedAfterEnd
                    ? run.state
                    : taskError
                      ? "error"
                      : historyIncomplete
                        ? "not_recorded"
                        : terminal
                          ? "not_run"
                          : "pending";
                const label = `${taskId} · repeat ${idx} · ${runStateLabel(state)}`;
                const marker = (
                  <span
                    className={`run-marker ${state}`}
                    aria-label={label}
                    title={run?.error ?? label}
                  >
                    {runStateSymbol(state)}
                  </span>
                );
                const supportedEvidence =
                  run?.runId !== undefined ||
                  Boolean(run?.persisted && run?.phase !== "running");
                return supportedEvidence ? (
                  <Link
                    className="run-marker-link"
                    key={idx}
                    to={`/jobs/${encodeURIComponent(job.id)}/runs/${encodeURIComponent(taskId)}/${idx}`}
                    aria-label={`Open ${label}`}
                  >
                    {marker}
                  </Link>
                ) : (
                  <span key={idx}>{marker}</span>
                );
              })}
            </div>
          </div>
        );
      })}
    </div>
  );
}
