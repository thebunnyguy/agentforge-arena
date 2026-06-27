import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api, ApiRequestError } from "../api/client";
import type { Job } from "../api/types";
import { useJobEvents } from "../lib/useJobEvents";
import { CaveatBanner } from "../components/CaveatBanner";
import { ErrorState, Loading } from "../components/States";
import { formatDate, jobStatusLabel, toPx } from "../lib/format";

const TERMINAL = new Set(["succeeded", "failed", "canceled"]);

export function JobDetail() {
  const { jobId = "" } = useParams();
  const navigate = useNavigate();
  const [job, setJob] = useState<Job | null>(null);
  const [error, setError] = useState<Error | null>(null);
  const [actioning, setActioning] = useState(false);

  const isTerminal = job ? TERMINAL.has(job.status) : false;
  const stream = useJobEvents(jobId, !isTerminal);

  // Poll the job record for counters + terminal state. Stop once terminal.
  useEffect(() => {
    let stopped = false;
    let timer: number | null = null;
    const tick = async () => {
      try {
        const j = await api.job(jobId);
        if (stopped) return;
        setJob(j);
        setError(null);
        if (!TERMINAL.has(j.status)) {
          timer = window.setTimeout(tick, 1500);
        }
      } catch (e) {
        if (stopped) return;
        setError(e instanceof Error ? e : new Error(String(e)));
      }
    };
    tick();
    return () => {
      stopped = true;
      if (timer) window.clearTimeout(timer);
    };
  }, [jobId]);

  // When the stream signals a terminal event, refresh the job once more.
  useEffect(() => {
    const last = stream.events[stream.events.length - 1];
    if (last && ["job_done", "job_failed", "job_canceled"].includes(last.type)) {
      api.job(jobId).then(setJob).catch(() => {});
    }
  }, [stream.events, jobId]);

  if (!job && error) return <ErrorState error={error} onRetry={() => navigate(0)} />;
  if (!job) return <Loading label="Loading job…" />;

  const c = job.counters;
  const progress = c.total_runs > 0 ? c.completed_runs / c.total_runs : 0;

  async function cancel() {
    if (!job) return;
    setActioning(true);
    try {
      const j = await api.cancelJob(job.id);
      setJob(j);
    } catch (e) {
      setError(e instanceof ApiRequestError ? e : new Error(String(e)));
    } finally {
      setActioning(false);
    }
  }

  async function retry() {
    if (!job) return;
    setActioning(true);
    try {
      const j = await api.retryJob(job.id);
      navigate(`/jobs/${encodeURIComponent(j.id)}`);
    } catch (e) {
      setError(e instanceof ApiRequestError ? e : new Error(String(e)));
      setActioning(false);
    }
  }

  const canCancel = job.status === "queued" || job.status === "running";
  const canRetry = TERMINAL.has(job.status);

  return (
    <div>
      <h1 className="page-title">
        Job {job.id.slice(0, 8)} · {job.params.name || job.params.model}
      </h1>
      <p className="page-subtitle">
        {job.params.backend.kind} · {job.params.model} · {job.params.tasks.length}{" "}
        tasks × {job.params.repeats} repeats
      </p>
      <CaveatBanner />

      <div className="panel">
        <div style={{ display: "flex", alignItems: "center", gap: 14, marginBottom: 14 }}>
          <span className={`badge ${badgeClass(job.status)}`}>
            {jobStatusLabel(job.status)}
          </span>
          <span className="conn-pill">
            <span
              className={`dot ${
                stream.transport === "closed"
                  ? ""
                  : stream.connected
                    ? "live"
                    : "bad"
              }`}
            />
            {stream.transport === "closed"
              ? "stream closed"
              : stream.transport === "sse"
                ? stream.connected
                  ? "live (SSE)"
                  : "reconnecting (SSE)"
                : "live (poll fallback)"}
          </span>
          <div className="spacer" />
          {canCancel && (
            <button className="btn danger" disabled={actioning} onClick={cancel}>
              {job.cancel_requested ? "Cancel requested…" : "Cancel"}
            </button>
          )}
          {canRetry && (
            <button className="btn secondary" disabled={actioning} onClick={retry}>
              Retry as new job
            </button>
          )}
          {TERMINAL.has(job.status) && c.completed_runs > 0 && (
            <Link className="btn" to={`/jobs/${encodeURIComponent(job.id)}/results`}>
              View results →
            </Link>
          )}
        </div>

        <div className="progress" style={{ marginBottom: 8 }}>
          <div className="fill" style={{ width: toPx(progress, 100) + "%" }} />
        </div>
        <p className="note">
          {c.completed_runs} / {c.total_runs} runs · {c.passed_runs} passed ·{" "}
          {c.voided_runs} voided · {c.failed_runs} failed
        </p>

        {job.error_message && (
          <p className="note" style={{ color: "var(--bad)" }}>
            {job.error_message}
          </p>
        )}

        <dl className="kv" style={{ marginTop: 12 }}>
          <dt>created</dt>
          <dd>{formatDate(job.created_at)}</dd>
          <dt>started</dt>
          <dd>{formatDate(job.started_at)}</dd>
          <dt>finished</dt>
          <dd>{formatDate(job.finished_at)}</dd>
        </dl>
      </div>

      <div className="panel">
        <h2>Event log ({stream.events.length})</h2>
        {stream.events.length === 0 ? (
          <p className="note muted">Waiting for events…</p>
        ) : (
          <div className="event-log">
            {stream.events.map((e) => (
              <div className="event-row" key={`${e.seq}-${e.type}`}>
                <span className="seq">#{e.seq}</span>
                <span className="type">{e.type}</span>
                <span>{summarize(e.payload)}</span>
              </div>
            ))}
          </div>
        )}
        <p className="note muted">
          Reconnects replay from Last-Event-ID and are deduped by seq, so the log
          never shows duplicate runs after a refresh.
        </p>
      </div>
    </div>
  );
}

function badgeClass(status: string): string {
  switch (status) {
    case "succeeded":
      return "good";
    case "failed":
      return "bad";
    case "canceled":
      return "warn";
    case "running":
      return "void";
    default:
      return "";
  }
}

function summarize(payload: Record<string, unknown> | null): string {
  if (!payload) return "";
  // Render a compact, human summary of common payload shapes.
  const parts: string[] = [];
  for (const key of ["task_id", "idx", "status", "functional_pass", "message", "completed", "total"]) {
    if (key in payload && payload[key] !== null && payload[key] !== undefined) {
      parts.push(`${key}=${String(payload[key])}`);
    }
  }
  if (parts.length > 0) return parts.join(" · ");
  if ("raw" in payload) return String(payload.raw);
  return JSON.stringify(payload);
}
