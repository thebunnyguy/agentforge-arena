import { RotateCcw } from "lucide-react";
import { Link } from "react-router-dom";
import type { Job } from "../api/types";
import {
  backendLabel,
  formatDate,
  jobDuration,
  taskScope,
} from "../lib/format";
import {
  PARAMS_UNAVAILABLE_TITLE,
  reasonSentence,
  jobEvidenceClass,
  jobParamsView,
} from "../lib/jobParams";
import { JobEvidenceChip, JobStatusBadge } from "./Badges";
import { LinkArrow, ProgressBar } from "./Primitives";

const TERMINAL = new Set(["succeeded", "failed", "canceled"]);

export function EvaluationCard({
  job,
  onRetry,
}: {
  job: Job;
  onRetry?: (job: Job) => void;
}) {
  const view = jobParamsView(job);
  const evidenceClass = jobEvidenceClass(job);
  const progress =
    job.counters.total_runs > 0
      ? job.counters.completed_runs / job.counters.total_runs
      : 0;
  const labelDiffers = Boolean(
    view.available && view.name && view.name !== view.model,
  );
  return (
    <article className="evaluation-card">
      <div>
        <div className="evaluation-title">
          <Link to={`/jobs/${encodeURIComponent(job.id)}`}>
            {view.available ? view.model : PARAMS_UNAVAILABLE_TITLE}
          </Link>
          <JobStatusBadge status={job.status} />
          {!view.available && (
            <span className="badge warn">UNVERIFIABLE PARAMETERS</span>
          )}
        </div>
        {labelDiffers && view.available && (
          <div className="evaluation-meta">
            label: <span className="mono">{view.name}</span>
          </div>
        )}
        <div className="evaluation-meta">
          {view.available ? (
            <>
              {backendLabel(view.backendKind)} ·{" "}
              {taskScope(view.tasks.length, view.repeats)} ·{" "}
            </>
          ) : (
            <>evaluation {job.id.slice(0, 10)} · </>
          )}
          {formatDate(job.created_at)}
          {job.finished_at ? ` → ${formatDate(job.finished_at)}` : ""}
        </div>
        {view.available && evidenceClass !== "unknown" && (
          <div className="evaluation-meta">
            <JobEvidenceChip
              cls={evidenceClass}
              backendKind={job.backend_kind}
            />
          </div>
        )}
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
        {TERMINAL.has(job.status) && onRetry && view.available && (
          <button
            className="btn btn-ghost btn-small"
            type="button"
            onClick={() => onRetry(job)}
          >
            <RotateCcw size={13} aria-hidden="true" /> Retry
          </button>
        )}
      </div>
      {!view.available && (
        <div className="evaluation-error">
          <strong>{PARAMS_UNAVAILABLE_TITLE}:</strong>{" "}
          {reasonSentence(view.reason)} Retry and resume are disabled for this
          evaluation.
        </div>
      )}
      {job.error_message &&
        job.error_message !== (view.available ? null : view.reason) && (
          <div className="evaluation-error">
            <strong>Reason:</strong> {job.error_message}
          </div>
        )}
    </article>
  );
}
