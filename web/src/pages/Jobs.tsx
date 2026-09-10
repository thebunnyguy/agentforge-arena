import { Filter, Plus, RefreshCw, Search } from "lucide-react";
import { useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api, ApiRequestError } from "../api/client";
import { usePolling } from "../lib/usePolling";
import type { Job, JobStatus } from "../api/types";
import { CaveatBanner } from "../components/CaveatBanner";
import { EvaluationCard } from "../components/EvaluationCard";
import { ErrorState, EmptyState, Loading } from "../components/States";
import { PageHeader, Panel, SectionHeader } from "../components/Primitives";

export function Jobs() {
  const navigate = useNavigate();
  const jobs = usePolling((signal) => api.jobs(signal), [], 5000);
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState<"" | JobStatus>("");
  const [retryError, setRetryError] = useState<string | null>(null);
  const filtered = useMemo(
    () =>
      (jobs.data?.jobs ?? []).filter((job) => {
        const needle = query.trim().toLowerCase();
        return (
          (!needle ||
            job.params.model.toLowerCase().includes(needle) ||
            job.id.includes(needle)) &&
          (!status || job.status === status)
        );
      }),
    [jobs.data, query, status],
  );

  async function retry(job: Job) {
    setRetryError(null);
    try {
      const next = await api.retryJob(job.id);
      navigate(`/jobs/${encodeURIComponent(next.id)}`);
    } catch (error) {
      setRetryError(
        error instanceof ApiRequestError ? error.message : String(error),
      );
    }
  }

  return (
    <div>
      <PageHeader
        eyebrow="Evaluate"
        title="Evaluations"
        description="A history of local experiments. Running, canceled, failed, and reused work stays visible instead of disappearing into logs."
        actions={
          <Link className="btn" to="/new">
            <Plus size={15} aria-hidden="true" /> New evaluation
          </Link>
        }
      />
      <CaveatBanner />
      {retryError && (
        <div className="inline-notice notice-danger">{retryError}</div>
      )}
      <Panel>
        <SectionHeader
          title="Evaluation history"
          description={`${filtered.length} shown · newest first from the API`}
          action={
            <button
              className="btn btn-ghost btn-small"
              type="button"
              onClick={jobs.reload}
            >
              <RefreshCw size={14} aria-hidden="true" /> Refresh
            </button>
          }
        />
        <div className="toolbar">
          <div className="search-field">
            <Search size={15} aria-hidden="true" />
            <input
              aria-label="Search evaluations"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Search model IDs or evaluation IDs…"
            />
          </div>
          <label htmlFor="evaluation-status">
            <Filter size={14} aria-hidden="true" /> Status
          </label>
          <select
            id="evaluation-status"
            value={status}
            onChange={(event) =>
              setStatus(event.target.value as "" | JobStatus)
            }
          >
            <option value="">All statuses</option>
            <option value="queued">Queued</option>
            <option value="running">Running</option>
            <option value="succeeded">Succeeded</option>
            <option value="failed">Failed</option>
            <option value="canceled">Canceled</option>
          </select>
        </div>
        {jobs.loading && !jobs.data ? (
          <Loading label="Loading evaluations…" />
        ) : jobs.error && !jobs.data ? (
          <ErrorState error={jobs.error} onRetry={jobs.reload} />
        ) : filtered.length === 0 ? (
          <EmptyState
            title={
              jobs.data?.jobs.length
                ? "No matching evaluations"
                : "No evaluations yet"
            }
            action={
              <Link className="btn btn-small" to="/new">
                Create evaluation
              </Link>
            }
          >
            <p>
              {jobs.data?.jobs.length
                ? "Change the search or status filter."
                : "Run a mock evaluation to verify the local pipeline, or connect a local model backend."}
            </p>
          </EmptyState>
        ) : (
          <div className="evaluation-list">
            {filtered.map((job) => (
              <EvaluationCard job={job} onRetry={retry} key={job.id} />
            ))}
          </div>
        )}
      </Panel>
    </div>
  );
}
