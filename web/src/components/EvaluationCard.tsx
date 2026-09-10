import { RotateCcw } from "lucide-react";
import { Link } from "react-router-dom";
import type { Job } from "../api/types";
import {
  backendLabel,
  formatDate,
  jobDuration,
  taskScope,
} from "../lib/format";
import { JobStatusBadge } from "./Badges";
import { LinkArrow, ProgressBar } from "./Primitives";

const TERMINAL = new Set(["succeeded", "failed", "canceled"]);

export function EvaluationCard({
  job,
  onRetry,
}: {
  job: Job;
  onRetry?: (job: Job) => void;
}) {
  const progress =
    job.counters.total_runs > 0
      ? job.counters.completed_runs / job.counters.total_runs
      : 0;
  const labelDiffers = Boolean(
    job.params.name && job.params.name !== job.params.model,
  );
  return (
    <article className="evaluation-card">
      <div>
        <div className="evaluation-title">
          <Link to={`/jobs/${encodeURIComponent(job.id)}`}>
            {job.params.model}
          </Link>
          <JobStatusBadge status={job.status} />
        </div>
        {labelDiffers && (
          <div className="evaluation-meta">
            label: <span className="mono">{job.params.name}</span>
          </div>
        )}
        <div className="evaluation-meta">
          {backendLabel(job.params.backend.kind)} ·{" "}
          {taskScope(job.params.tasks.length, job.params.repeats)} ·{" "}
          {formatDate(job.created_at)}
          {job.finished_at ? ` → ${formatDate(job.finished_at)}` : ""}
        </div>
      </div>
      <div className="evaluation-stats">
        {job.counters.passed_runs} pass · {job.counters.failed_runs} fail ·{" "}
        {job.counters.voided_runs} void
        {job.counters.reused_runs
          ? ` · ${job.counters.reused_runs} reused`
          : ""}
      </div>
      <div className="evaluation-progress">
        <ProgressBar
          value={progress}
          label={`${job.counters.completed_runs}/${job.counters.total_runs}`}
          tone={
            job.status === "failed"
              ? "bad"
              : job.status === "succeeded"
                ? "good"
                : "accent"
          }
        />
        <div className="evaluation-meta">
          {jobDuration(job.started_at, job.finished_at)}
        </div>
      </div>
      <div className="evaluation-actions">
        <LinkArrow to={`/jobs/${encodeURIComponent(job.id)}`}>
          Monitor
        </LinkArrow>
        {TERMINAL.has(job.status) && job.counters.completed_runs > 0 && (
          <LinkArrow to={`/jobs/${encodeURIComponent(job.id)}/results`}>
            Results
          </LinkArrow>
        )}
        {TERMINAL.has(job.status) && onRetry && (
          <button
            className="btn btn-ghost btn-small"
            type="button"
            onClick={() => onRetry(job)}
          >
            <RotateCcw size={13} aria-hidden="true" /> Retry
          </button>
        )}
      </div>
      {job.error_message && (
        <div className="evaluation-error">
          <strong>Reason:</strong> {job.error_message}
        </div>
      )}
    </article>
  );
}
