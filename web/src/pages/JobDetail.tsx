import { useEffect, useMemo, useRef, useState } from "react";
import {
  AlertTriangle,
  ChevronDown,
  CircleDot,
  FileText,
  Pause,
  RotateCcw,
  Wifi,
} from "lucide-react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api, ApiRequestError } from "../api/client";
import type { Job, JobEvent } from "../api/types";
import { useJobEvents } from "../lib/useJobEvents";
import { latestCurrentRun, summarizeEvent } from "../lib/jobView";
import type { RunView } from "../lib/jobView";
import { TaskRunGrid } from "../components/TaskRunGrid";
import { CaveatBanner } from "../components/CaveatBanner";
import { JobEvidenceChip, JobStatusBadge } from "../components/Badges";
import {
  PARAMS_UNAVAILABLE_TITLE,
  reasonSentence,
  jobEvidenceClass,
  jobParamsView,
} from "../lib/jobParams";
import { ErrorState, Loading } from "../components/States";
import {
  InlineNotice,
  Metric,
  MetricGroup,
  PageHeader,
  Panel,
  ProgressBar,
  SectionHeader,
  StatusDot,
} from "../components/Primitives";
import {
  backendLabel,
  formatDate,
  jobDuration,
  taskScope,
} from "../lib/format";

const TERMINAL = new Set(["succeeded", "failed", "canceled"]);

export function JobDetail() {
  const { jobId = "" } = useParams();
  const navigate = useNavigate();
  const [job, setJob] = useState<Job | null>(null);
  const [error, setError] = useState<Error | null>(null);
  const [actioning, setActioning] = useState(false);
  const routeIdRef = useRef(jobId);
  const routeGeneration = useRef(0);
  if (routeIdRef.current !== jobId) {
    routeIdRef.current = jobId;
    routeGeneration.current += 1;
  }
  const stream = useJobEvents(jobId, true);

  useEffect(() => {
    return () => {
      routeGeneration.current += 1;
      routeIdRef.current = "";
    };
  }, []);

  useEffect(() => {
    routeIdRef.current = jobId;
    routeGeneration.current += 1;
    const controller = new AbortController();
    const generation = routeGeneration.current;
    let active = true;
    let timer: number | null = null;
    setJob(null);
    setError(null);
    setActioning(false);
    const tick = async () => {
      try {
        const result = await api.job(jobId, controller.signal);
        if (
          !active ||
          routeGeneration.current !== generation ||
          routeIdRef.current !== jobId
        )
          return;
        setJob(result);
        if (!TERMINAL.has(result.status)) timer = window.setTimeout(tick, 1500);
      } catch (caught) {
        if (
          !active ||
          controller.signal.aborted ||
          routeGeneration.current !== generation ||
          routeIdRef.current !== jobId
        )
          return;
        setError(caught instanceof Error ? caught : new Error(String(caught)));
        timer = window.setTimeout(tick, 2500);
      }
    };
    void tick();
    return () => {
      active = false;
      controller.abort();
      if (timer !== null) window.clearTimeout(timer);
      routeGeneration.current += 1;
      if (routeIdRef.current === jobId) routeIdRef.current = "";
    };
  }, [jobId]);

  useEffect(() => {
    const generation = routeGeneration.current;
    if (
      !stream.events.some((event) =>
        ["job_done", "job_failed", "job_canceled"].includes(event.type),
      )
    )
      return;
    let active = true;
    void api
      .job(jobId)
      .then((result) => {
        if (
          active &&
          routeGeneration.current === generation &&
          routeIdRef.current === jobId &&
          result.id === jobId
        )
          setJob(result);
      })
      .catch(() => undefined);
    return () => {
      active = false;
    };
  }, [stream.events, jobId]);

  const runMap = useMemo(
    () => latestCurrentRun(stream.events),
    [stream.events],
  );
  if (error && (!job || job.id !== jobId))
    return <ErrorState error={error} onRetry={() => navigate(0)} />;
  if (!job || job.id !== jobId) return <Loading label="Loading evaluation…" />;

  const currentJob = job;
  const counters = currentJob.counters;
  const progress =
    counters.total_runs > 0 ? counters.completed_runs / counters.total_runs : 0;
  const terminal = TERMINAL.has(currentJob.status);
  const currentRun = terminal ? null : runMap;
  const canCancel =
    !currentJob.cancel_requested &&
    (currentJob.status === "queued" || currentJob.status === "running");
  const paramsView = jobParamsView(currentJob);
  const evidenceClass = jobEvidenceClass(currentJob);
  // Unverifiable parameters can neither be retried nor resumed.
  const canRetry = terminal && paramsView.available;
  const transportLabel =
    stream.transport === "poll"
      ? "Live · fallback polling"
      : stream.transport === "closed"
        ? "Evidence tape closed"
        : stream.connected
          ? "Live"
          : "Reconnecting";

  async function cancel() {
    if (!canCancel) return;
    const targetId = currentJob.id;
    const targetGeneration = routeGeneration.current;
    const isCurrent = () =>
      routeGeneration.current === targetGeneration &&
      routeIdRef.current === targetId;
    setActioning(true);
    try {
      const result = await api.cancelJob(targetId);
      if (isCurrent()) setJob(result);
    } catch (caught) {
      if (isCurrent())
        setError(
          caught instanceof ApiRequestError
            ? caught
            : new Error(String(caught)),
        );
    } finally {
      if (isCurrent()) setActioning(false);
    }
  }

  async function retry() {
    const targetId = currentJob.id;
    const targetGeneration = routeGeneration.current;
    const isCurrent = () =>
      routeGeneration.current === targetGeneration &&
      routeIdRef.current === targetId;
    setActioning(true);
    try {
      const next = await api.retryJob(targetId);
      if (isCurrent()) navigate(`/jobs/${encodeURIComponent(next.id)}`);
    } catch (caught) {
      if (isCurrent())
        setError(
          caught instanceof ApiRequestError
            ? caught
            : new Error(String(caught)),
        );
      if (isCurrent()) setActioning(false);
    }
  }

  return (
    <div>
      <PageHeader
        eyebrow="Evaluation monitor"
        title={
          paramsView.available ? paramsView.model : PARAMS_UNAVAILABLE_TITLE
        }
        description={
          paramsView.available
            ? `${backendLabel(paramsView.backendKind)} · ${taskScope(paramsView.tasks.length, paramsView.repeats)} · created ${formatDate(currentJob.created_at)}`
            : `evaluation ${currentJob.id.slice(0, 10)} · created ${formatDate(currentJob.created_at)}`
        }
        actions={
          <div className="monitor-actions">
            {canCancel && (
              <button
                className="btn btn-danger"
                type="button"
                disabled={actioning}
                onClick={cancel}
              >
                <Pause size={15} aria-hidden="true" />
                Cancel evaluation
              </button>
            )}
            {currentJob.cancel_requested && (
              <span className="badge warn">cancel requested</span>
            )}
            {canRetry && (
              <button
                className="btn btn-secondary"
                type="button"
                disabled={actioning}
                onClick={retry}
              >
                <RotateCcw size={15} aria-hidden="true" /> Retry as new
                evaluation
              </button>
            )}
            {terminal && counters.completed_runs > 0 && (
              <Link
                className="btn"
                to={`/jobs/${encodeURIComponent(currentJob.id)}/results`}
              >
                <FileText size={15} aria-hidden="true" /> View results
              </Link>
            )}
          </div>
        }
      />
      <CaveatBanner />
      {error && (
        <InlineNotice tone="danger">
          <AlertTriangle size={16} aria-hidden="true" />
          <span>{error.message}</span>
        </InlineNotice>
      )}
      {stream.historyError && (
        <InlineNotice tone="warn">
          <AlertTriangle size={16} aria-hidden="true" />
          <span>
            Event history could not be fully loaded:{" "}
            {stream.historyError.message}
          </span>
        </InlineNotice>
      )}
      <div className="monitor-hero">
        <div>
          <StatusDot
            label={transportLabel}
            tone={
              stream.transport === "closed"
                ? "neutral"
                : stream.connected
                  ? "good"
                  : "warn"
            }
            pulse={stream.connected && stream.transport !== "closed"}
          />
          <div className="monitor-title">
            {currentJob.status === "running"
              ? "Evaluating"
              : currentJob.status === "queued"
                ? "Queued"
                : currentJob.status === "succeeded"
                  ? "Evaluation complete"
                  : currentJob.status === "canceled"
                    ? "Evaluation canceled"
                    : "Evaluation stopped"}
          </div>
          <div className="monitor-count">
            <strong>{counters.completed_runs}</strong> / {counters.total_runs}{" "}
            runs · {counters.passed_runs} passed · {counters.failed_runs} failed
            · {counters.voided_runs} voided
          </div>
          <div className="monitor-progress">
            <ProgressBar
              value={progress}
              label={`${Math.round(progress * 100)}%`}
              tone={
                currentJob.status === "failed"
                  ? "bad"
                  : currentJob.status === "succeeded"
                    ? "good"
                    : "accent"
              }
            />
          </div>
        </div>
        <div className="monitor-actions">
          <JobStatusBadge status={currentJob.status} />
          {!paramsView.available && (
            <span className="badge warn">UNVERIFIABLE PARAMETERS</span>
          )}
          {paramsView.available && evidenceClass !== "unknown" && (
            <JobEvidenceChip
              cls={evidenceClass}
              backendKind={currentJob.backend_kind}
            />
          )}
        </div>
      </div>
      <MetricGroup>
        <Metric
          label="Passed"
          value={counters.passed_runs}
          detail="functional pass"
          tone="good"
          mono
        />
        <Metric
          label="Failed"
          value={counters.failed_runs}
          detail="valid failures"
          tone="bad"
          mono
        />
        <Metric
          label="Voided"
          value={counters.voided_runs}
          detail="infra · excluded from n"
          tone="void"
          mono
        />
        <Metric
          label="Reused"
          value={counters.reused_runs}
          detail="existing evidence reused"
          mono
        />
      </MetricGroup>
      {!paramsView.available && (
        <InlineNotice tone="warn">
          <AlertTriangle size={16} aria-hidden="true" />
          <span>
            <strong>{PARAMS_UNAVAILABLE_TITLE}.</strong>{" "}
            {reasonSentence(paramsView.reason)} The persisted parameters could
            not be verified, so this evaluation cannot be retried or resumed and
            no run evidence is inferred from it.
          </span>
        </InlineNotice>
      )}
      {currentJob.error_message &&
        (paramsView.available ||
          currentJob.error_message !== paramsView.reason) && (
          <InlineNotice tone="danger">
            <AlertTriangle size={16} aria-hidden="true" />
            <span>{currentJob.error_message}</span>
          </InlineNotice>
        )}
      {paramsView.available && evidenceClass === "synthetic" && (
        <InlineNotice tone="info">
          <span>
            <strong>Synthetic (mock) evaluation.</strong> Its runs are excluded
            from the default benchmark views and results. They stay inspectable
            through run links and the synthetic evidence scope.
          </span>
        </InlineNotice>
      )}

      <div className="monitor-grid">
        <div>
          <Panel>
            <SectionHeader
              title="Task progress"
              description="Each marker is one task/repeat unit. Reused work is not counted as a fresh pass."
            />
            {stream.historyLoading && stream.events.length === 0 ? (
              <Loading label="Loading event history…" />
            ) : (
              <TaskRunGrid
                job={currentJob}
                events={stream.events}
                historyLoading={stream.historyLoading}
                historyError={stream.historyError}
              />
            )}
            <div className="legend">
              <span className="legend-item">
                <span className="run-marker pass">✓</span> pass
              </span>
              <span className="legend-item">
                <span className="run-marker fail">×</span> fail
              </span>
              <span className="legend-item">
                <span className="run-marker voided">◇</span> voided
              </span>
              <span className="legend-item">
                <span className="run-marker running">●</span> running
              </span>
              <span className="legend-item">
                <span className="run-marker unknown">?</span> recorded · unknown
              </span>
              <span className="legend-item">
                <span className="run-marker not_run">–</span> not run
              </span>
              <span className="legend-item">
                <span className="run-marker not_recorded">?</span> not recorded
              </span>
              <span className="legend-item">
                <span className="run-marker reused">↺</span> reused
              </span>
            </div>
          </Panel>
        </div>
        <div>
          <Panel>
            <SectionHeader
              title="Current run"
              description="Worker event granularity is intentionally shown as coarse."
            />
            {currentRun ? (
              <CurrentRun
                job={currentJob}
                current={currentRun}
                events={stream.events}
              />
            ) : (
              <div className="current-run">
                <CircleDot size={18} aria-hidden="true" />
                <strong>
                  {terminal
                    ? "No run is active"
                    : currentJob.status === "queued"
                      ? "Waiting for worker"
                      : "No run currently active"}
                </strong>
                <span className="note muted">
                  The raw evidence tape below remains available for inspection.
                </span>
              </div>
            )}
          </Panel>
          <Panel>
            <SectionHeader title="Evaluation record" />
            <dl className="kv">
              <dt>evaluation ID</dt>
              <dd>{currentJob.id}</dd>
              <dt>parameters</dt>
              <dd>
                {paramsView.available
                  ? "verified"
                  : `${PARAMS_UNAVAILABLE_TITLE} (unverifiable)`}
              </dd>
              <dt>evidence class</dt>
              <dd>
                {!paramsView.available
                  ? "unknown - parameters unverifiable"
                  : evidenceClass === "synthetic"
                    ? "synthetic (mock) - excluded from benchmark results"
                    : evidenceClass}
              </dd>
              <dt>created</dt>
              <dd>{formatDate(currentJob.created_at)}</dd>
              <dt>started</dt>
              <dd>{formatDate(currentJob.started_at)}</dd>
              <dt>finished</dt>
              <dd>{formatDate(currentJob.finished_at)}</dd>
              <dt>duration</dt>
              <dd>
                {jobDuration(currentJob.started_at, currentJob.finished_at)}
              </dd>
            </dl>
          </Panel>
        </div>
      </div>

      <Panel>
        <details
          className="advanced-details"
          open={currentJob.status === "failed"}
        >
          <summary>
            <span>
              <Wifi size={15} aria-hidden="true" /> Advanced event evidence ·{" "}
              {stream.events.length} events · last sequence {stream.lastSeq}
            </span>
            <ChevronDown size={15} aria-hidden="true" />
          </summary>
          {stream.events.length === 0 ? (
            <p className="note muted">
              {stream.historyLoading
                ? "Loading worker events…"
                : "No worker events were recorded."}
            </p>
          ) : (
            <div className="event-log">
              {stream.events.map((event) => (
                <EventRow event={event} key={`${event.seq}-${event.type}`} />
              ))}
            </div>
          )}
          <p className="note muted">
            Persisted event timestamps are shown when available. Native SSE
            events do not expose a server timestamp, so those rows say so
            explicitly.
          </p>
        </details>
      </Panel>
    </div>
  );
}

function CurrentRun({
  job,
  current,
  events,
}: {
  job: Job;
  current: RunView;
  events: JobEvent[];
}) {
  const prefix = events.filter(
    (event) =>
      event.payload?.task_id === current.taskId &&
      event.payload?.idx === current.idx,
  );
  const graded = prefix.some(
    (event) => event.type === "run_graded" || event.type === "run_scored",
  );
  const persisted = prefix.some((event) => event.type === "run_persisted");
  return (
    <div className="current-run">
      <div className="current-run-title">{current.taskId}</div>
      <div className="current-run-subtitle">
        Repeat {current.idx + 1}
        {(() => {
          const view = jobParamsView(job);
          return view.available ? ` of ${view.repeats}` : "";
        })()}
      </div>
      <div className="stage-list">
        <div className="stage-row">
          <span>Agent run</span>
          <span className="stage-state">
            <StatusDot label="running" tone="accent" pulse />
          </span>
        </div>
        <div className="stage-row">
          <span>Worker result</span>
          <span className="stage-state">{graded ? "recorded" : "waiting"}</span>
        </div>
        <div className="stage-row">
          <span>Persisted</span>
          <span className="stage-state">{persisted ? "yes" : "waiting"}</span>
        </div>
      </div>
      <p className="note muted">
        The model call is atomic from the worker’s perspective; patch and test
        stages are not presented as live before the result event arrives.
      </p>
    </div>
  );
}

function EventRow({ event }: { event: JobEvent }) {
  const timestamp = event.ts
    ? formatDate(event.ts)
    : "server timestamp unavailable";
  return (
    <details className="event-detail">
      <summary className="event-row">
        <span className="seq">#{event.seq}</span>
        <span className="type">{event.type}</span>
        <span className="payload">
          {summarizeEvent(event.payload)} · {timestamp}
        </span>
      </summary>
      <pre className="log event-payload" tabIndex={0}>
        {event.payload ? JSON.stringify(event.payload, null, 2) : "{}"}
      </pre>
    </details>
  );
}
