import { useState } from "react";
import { ArrowRight, Database, Play } from "lucide-react";
import { Link, useNavigate } from "react-router-dom";
import { api, ApiRequestError } from "../api/client";
import type { Job } from "../api/types";
import { useAsync } from "../lib/useAsync";
import { usePolling } from "../lib/usePolling";
import { CaveatBanner } from "../components/CaveatBanner";
import { EvaluationCard } from "../components/EvaluationCard";
import { ErrorState, Loading, EmptyState } from "../components/States";
import {
  InlineNotice,
  LinkArrow,
  Panel,
  PageHeader,
  SectionHeader,
  StatusDot,
} from "../components/Primitives";
import { WilsonBar } from "../components/WilsonBar";
import { EvidenceScopeBanner } from "../components/EvidenceScopeBanner";
import { MissingCurrentEvidence } from "../components/Badges";
import { linkQuery, useEvidenceScope } from "../lib/useEvidenceScope";
import { backendLabel, pct, rankLabel } from "../lib/format";

export function Overview() {
  const [scope, setScope] = useEvidenceScope();
  const overview = useAsync(
    (signal) => api.overview({ evidence: scope }, signal),
    [scope],
  );
  const meta = useAsync((signal) => api.meta({}, signal), []);
  const jobs = usePolling((signal) => api.jobs(signal), [], 5000);
  const health = useAsync((signal) => api.health(signal), []);
  const settings = useAsync((signal) => api.settings(signal), []);
  const navigate = useNavigate();
  const [retryError, setRetryError] = useState<string | null>(null);

  if (!overview.data)
    return (
      <div>
        <PageHeader
          eyebrow="AgentForge Arena"
          title="Evaluation workspace"
          description="The local benchmark home is waiting for evidence data."
          actions={
            <Link className="btn" to="/new">
              <Play size={15} aria-hidden="true" /> New evaluation
            </Link>
          }
        />
        {overview.loading ? (
          <Loading label="Preparing the evaluation workspace…" />
        ) : (
          <InlineNotice tone="danger">
            <Database size={16} aria-hidden="true" />
            <span>
              {overview.error?.message ?? "The overview could not be loaded."}{" "}
              Use New evaluation to continue or retry this page.
            </span>
          </InlineNotice>
        )}
        <button
          className="btn btn-secondary"
          type="button"
          onClick={overview.reload}
        >
          Retry overview
        </button>
      </div>
    );

  const data = overview.data;
  const obs = data.observability;
  const recentJobs = jobs.data?.jobs.slice(0, 4) ?? [];
  const topEntries = data.leaderboard.slice(0, 4);
  const benchmark = data.current_benchmark;
  const historicalOnly = data.historical_only_models ?? [];
  const configuredBackend = settings.data
    ? `${backendLabel(settings.data.default_backend)} configured · verify before launch`
    : settings.error
      ? "Backend settings unavailable"
      : "Reading backend settings…";
  async function retryJob(job: Job) {
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
      <div className="hero">
        <div>
          <div className="eyebrow">AgentForge Arena</div>
          <h1>
            Run agents.
            <br />
            <span>Trust the evidence.</span>
          </h1>
          <p>
            A local workstation for evaluating coding agents, observing
            behavior, and investigating every failure without hiding
            uncertainty.
          </p>
          <div className="hero-actions">
            <Link className="btn" to="/new">
              <Play size={15} aria-hidden="true" /> New evaluation
            </Link>
            <Link className="btn btn-ghost" to="/leaderboard">
              Open leaderboard <ArrowRight size={15} aria-hidden="true" />
            </Link>
          </div>
        </div>
        <div className="hero-status">
          <div className="hero-status-title">Workspace status</div>
          <div className="status-list">
            <StatusDot
              label={
                health.data?.stores_loaded
                  ? "Evidence database loaded"
                  : health.error
                    ? "Evidence database unavailable"
                    : "Checking evidence database"
              }
              tone={
                health.error
                  ? "bad"
                  : health.data?.stores_loaded
                    ? "good"
                    : "neutral"
              }
              pulse={!health.error && !health.data}
            />
            <StatusDot
              label={configuredBackend}
              tone={
                settings.error ? "bad" : settings.data ? "accent" : "neutral"
              }
            />
            <StatusDot
              label={
                benchmark
                  ? `${benchmark.tasks_with_current_evidence}/${benchmark.n_tasks} tasks with current evidence`
                  : `${data.n_tasks} benchmark tasks`
              }
              tone="accent"
            />
            <StatusDot label="Trusted-local execution" tone="warn" />
          </div>
        </div>
      </div>
      <CaveatBanner caveat={meta.data?.notes?.trust} />
      <EvidenceScopeBanner
        scope={scope}
        onScopeChange={setScope}
        coverage={
          benchmark
            ? {
                withCurrent: benchmark.tasks_with_current_evidence,
                total: benchmark.n_tasks,
              }
            : null
        }
      />
      <div className="split-layout">
        <Panel>
          <SectionHeader
            title="Recent evaluations"
            description="The latest control-plane history. Open one to monitor or inspect its evidence."
            action={<LinkArrow to="/jobs">View all</LinkArrow>}
          />
          {retryError && (
            <div className="inline-notice notice-danger">{retryError}</div>
          )}
          {jobs.error && jobs.data && (
            <div className="inline-notice notice-warn">
              Refresh failed; showing the last loaded evaluation list.
            </div>
          )}
          {jobs.loading && !jobs.data ? (
            <Loading label="Loading recent evaluations…" />
          ) : jobs.error && !jobs.data ? (
            <ErrorState error={jobs.error} onRetry={jobs.reload} />
          ) : recentJobs.length === 0 ? (
            <EmptyState
              title="No evaluations yet"
              action={
                <Link className="btn btn-small" to="/new">
                  Start the first evaluation
                </Link>
              }
            >
              <p>
                Choose a local backend and task set to create a replayable
                evaluation record.
              </p>
            </EmptyState>
          ) : (
            <div>
              {recentJobs.map((job) => (
                <EvaluationCard job={job} onRetry={retryJob} key={job.id} />
              ))}
            </div>
          )}
        </Panel>
        <Panel>
          <SectionHeader
            title="Current benchmark snapshot"
            description="Kernel order over current-version evidence, pooled across the tasks that have it."
            action={
              <LinkArrow to={`/leaderboard${linkQuery(scope)}`}>
                Full ranking
              </LinkArrow>
            }
          />
          <div className="snapshot-list">
            {topEntries.map((entry) => (
              <div className="snapshot-row" key={entry.agent}>
                <span className="snapshot-rank">
                  {rankLabel(
                    entry.provisional,
                    entry.rank_low,
                    entry.rank_high,
                  )}
                </span>
                <div className="snapshot-agent">
                  <Link
                    to={`/agent/${encodeURIComponent(entry.agent)}${linkQuery(scope)}`}
                  >
                    {entry.agent}
                  </Link>
                  <span>
                    {entry.n} valid runs · {pct(entry.pass_rate, 1)}
                    {entry.coverage
                      ? ` · ${entry.coverage.tasks_with_current_evidence}/${entry.coverage.tasks_total} tasks`
                      : ""}
                  </span>
                </div>
                <WilsonBar
                  pHat={entry.pass_rate}
                  low={entry.wilson_low}
                  high={entry.wilson_high}
                  width={150}
                  compact
                  showLabel={false}
                />
              </div>
            ))}
          </div>
          {topEntries.length === 0 && (
            <p className="note muted">
              No model has current benchmark evidence in this scope.
            </p>
          )}
          {historicalOnly.length > 0 && (
            <div className="note muted">
              <MissingCurrentEvidence
                detail={`for ${historicalOnly.join(", ")}; not ranked.`}
              />
            </div>
          )}
          <p className="note muted">
            Intervals qualify every point estimate; rank ranges stay visible
            when evidence overlaps. Partial coverage is not a full-benchmark
            rank.
          </p>
          {meta.data?.synthetic_agents.length ? (
            <p className="note muted">
              Synthetic reference baselines remain available as clearly labelled
              bookend cells, not competing model entries.
            </p>
          ) : null}
        </Panel>
      </div>
      <Panel className="home-health">
        <SectionHeader
          title="Evidence health"
          description="Persisted-run counts cover all versions and evidence classes (API startup snapshot); the current-benchmark counts are the subset used for ranking. Patch and test-result coverage are independent."
        />
        <div className="evidence-strip evidence-strip-strong">
          <div className="evidence-item">
            <span className="evidence-label">
              Persisted runs (all versions)
            </span>
            <span className="evidence-value evidence-good">
              {obs.total_runs}
            </span>
          </div>
          {benchmark && (
            <>
              <div className="evidence-item">
                <span className="evidence-label">Current-benchmark runs</span>
                <span className="evidence-value evidence-good">
                  {benchmark.current_runs}
                </span>
              </div>
              <div className="evidence-item">
                <span className="evidence-label">Historical runs</span>
                <span className="evidence-value evidence-warn">
                  {benchmark.historical_runs}
                </span>
              </div>
            </>
          )}
          <div className="evidence-item">
            <span className="evidence-label">Agents</span>
            <span className="evidence-value">{data.models.length}</span>
          </div>
          <div className="evidence-item">
            <span className="evidence-label">
              {benchmark ? "Tasks with current evidence" : "Tasks"}
            </span>
            <span className="evidence-value">
              {benchmark
                ? `${benchmark.tasks_with_current_evidence}/${benchmark.n_tasks}`
                : data.n_tasks}
            </span>
          </div>
          <div className="evidence-item">
            <span className="evidence-label">Patch coverage (all runs)</span>
            <span className="evidence-value">
              {obs.runs_with_patch}/{obs.total_runs}
            </span>
          </div>
          <div className="evidence-item">
            <span className="evidence-label">
              Test-result coverage (all runs)
            </span>
            <span className="evidence-value">
              {obs.runs_with_test_results}/{obs.total_runs}
            </span>
          </div>
          <div className="evidence-item">
            <span className="evidence-label">Test rows</span>
            <span className="evidence-value">{obs.test_result_rows}</span>
          </div>
        </div>
      </Panel>
    </div>
  );
}
