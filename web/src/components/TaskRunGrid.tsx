import { Link } from "react-router-dom";
import type { Job, JobEvent } from "../api/types";
import { PARAMS_UNAVAILABLE_TITLE, jobParamsView } from "../lib/jobParams";
import {
  projectEventTape,
  runStateLabel,
  runStateSymbol,
} from "../lib/jobView";

export function TaskRunGrid({
  job,
  events,
  historyLoading = false,
  historyError = null,
}: {
  job: Job;
  events: JobEvent[];
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
  const historyIncomplete = historyLoading || historyError !== null;
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
                const run = projection.runs.get(`${taskId}:${idx}`);
                const state =
                  run?.state ??
                  (taskError
                    ? "error"
                    : historyIncomplete
                      ? "not_recorded"
                      : terminal
                        ? "not_run"
                        : "pending");
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
                const supportedEvidence = Boolean(
                  run?.persisted && run?.phase !== "running",
                );
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
