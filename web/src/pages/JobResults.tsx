import { Fragment, useMemo } from "react";
import { ArrowLeft, Download, ExternalLink, RefreshCw } from "lucide-react";
import { Link, useParams } from "react-router-dom";
import { api, jobReportUrl } from "../api/client";
import { useAsync } from "../lib/useAsync";
import { TaskRunGrid } from "../components/TaskRunGrid";
import { CaveatBanner } from "../components/CaveatBanner";
import { ErrorState, Loading } from "../components/States";
import { JobStatusBadge, MissingCurrentEvidence } from "../components/Badges";
import {
  PARAMS_UNAVAILABLE_TITLE,
  reasonSentence,
  jobEvidenceClass,
  jobParamsView,
} from "../lib/jobParams";
import type {
  EvaluationReport,
  EvaluationReportTrial,
  EvidenceScope,
  JobCounters,
  JobStatus,
} from "../api/types";
import {
  InlineNotice,
  LinkArrow,
  Metric,
  MetricGroup,
  PageHeader,
  Panel,
  SectionHeader,
} from "../components/Primitives";
import { WilsonBar } from "../components/WilsonBar";
import { backendLabel, fixed, formatDate, pct, taskScope } from "../lib/format";

export function JobResults() {
  const { jobId = "" } = useParams();
  const job = useAsync((signal) => api.job(jobId, signal), [jobId]);
  // The evaluation's own deterministic report (GET /jobs/{id}/report.json):
  // exactly this evaluation's trial rows, counters and limitations, never a
  // pooled global aggregate.
  const report = useAsync((signal) => api.jobReport(jobId, signal), [jobId]);
  // Job.params may be null (unverifiable): only jobParamsView reads it.
  const view = job.data ? jobParamsView(job.data) : null;
  const agent = view?.available ? view.model : "";
  const tasks = view?.available ? view.tasks : [];
  const taskKey = tasks.join(",");
  const evidenceClass = job.data ? jobEvidenceClass(job.data) : "unknown";
  // A mock job's runs are excluded from the benchmark scope; look them up in
  // the synthetic scope and label the result accordingly.
  const cellScope: EvidenceScope =
    evidenceClass === "synthetic" ? "synthetic" : "benchmark";
  const cells = useAsync(
    (signal) =>
      view?.available
        ? Promise.all(
            tasks.map((task) =>
              api.cell(agent, task, { evidence: cellScope }, signal),
            ),
          )
        : Promise.resolve([]),
    [agent, taskKey, cellScope, view?.available],
  );
  const cellsByTask = useMemo(
    () => new Map((cells.data ?? []).map((cell) => [cell.task_id, cell])),
    [cells.data],
  );

  if (job.loading) return <Loading label="Loading evaluation results…" />;
  if (job.error) return <ErrorState error={job.error} onRetry={job.reload} />;
  const evaluation = job.data!;
  const evaluationReport =
    report.data?.evaluation_id === evaluation.id ? report.data : null;
  // Only an explicitly unfinished status; a null status is "unverifiable",
  // which the report's limitations already say.
  const stillRunning =
    evaluationReport?.status === "queued" ||
    evaluationReport?.status === "running";
  const refresh = () => {
    job.reload();
    report.reload();
  };
  return (
    <div>
      <PageHeader
        eyebrow="Evaluation results"
        title={view?.available ? view.model : PARAMS_UNAVAILABLE_TITLE}
        description={
          view?.available
            ? `${taskScope(view.tasks.length, view.repeats)} · evaluation ${evaluation.id.slice(0, 10)}`
            : `evaluation ${evaluation.id.slice(0, 10)}`
        }
        actions={
          <div className="monitor-actions">
            <Link
              className="btn btn-secondary"
              to={`/jobs/${encodeURIComponent(evaluation.id)}`}
            >
              <ArrowLeft size={15} aria-hidden="true" /> Monitor
            </Link>
            <a
              className="btn btn-ghost"
              href={jobReportUrl(evaluation.id, "json")}
              download={`evaluation-${evaluation.id}.json`}
            >
              <Download size={15} aria-hidden="true" /> Report JSON
            </a>
            <a
              className="btn btn-ghost"
              href={jobReportUrl(evaluation.id, "md")}
              download={`evaluation-${evaluation.id}.md`}
            >
              <Download size={15} aria-hidden="true" /> Report Markdown
            </a>
          </div>
        }
      />
      <CaveatBanner />
      {view && !view.available && (
        <InlineNotice tone="warn">
          <span>
            <strong>{PARAMS_UNAVAILABLE_TITLE}.</strong>{" "}
            {reasonSentence(view.reason)} Task outcomes and global aggregates
            cannot be attributed to this evaluation.
          </span>
        </InlineNotice>
      )}
      {evidenceClass === "synthetic" && (
        <InlineNotice tone="warn">
          <span>
            <strong>Synthetic - not benchmark evidence.</strong> This is a mock
            evaluation. Its runs are excluded from the default benchmark
            results, leaderboard and agent profile.{" "}
            <Link to="/leaderboard?evidence=synthetic">
              Open the synthetic view
            </Link>
            .
          </span>
        </InlineNotice>
      )}
      {stillRunning && (
        <InlineNotice tone="info">
          <span>
            <strong>This evaluation has not finished.</strong> The report below
            shows the trials persisted so far.
          </span>
          <button
            className="btn btn-secondary btn-small"
            type="button"
            onClick={refresh}
          >
            <RefreshCw size={14} aria-hidden="true" /> Refresh
          </button>
        </InlineNotice>
      )}
      <ReportMetrics
        status={evaluation.status}
        report={evaluationReport}
        fallback={evaluation.counters}
      />
      <Panel>
        <SectionHeader
          title="Task and repeat outcomes"
          description="This evaluation's persisted trial rows, from its own report. Each linked marker and run id opens exactly the run that trial recorded, even when the same model has other evaluations."
        />
        {view && !view.available ? (
          <p className="note muted">
            {PARAMS_UNAVAILABLE_TITLE}: per-trial outcomes are not attributed to
            this evaluation. Its report still lists what the server could and
            could not verify (see Limitations).
          </p>
        ) : report.loading && !evaluationReport ? (
          <Loading label="Loading evaluation report…" />
        ) : report.error ? (
          <ErrorState error={report.error} onRetry={report.reload} />
        ) : evaluationReport ? (
          <>
            <TaskRunGrid
              job={evaluation}
              events={[]}
              trials={evaluationReport.trials}
            />
            <TrialTable
              jobId={evaluation.id}
              trials={evaluationReport.trials}
            />
          </>
        ) : null}
      </Panel>
      {evaluationReport && (
        <div className="split-layout">
          <ReportProvenance report={evaluationReport} />
          <Panel>
            <SectionHeader
              title="Limitations"
              description="What the server could not verify or complete for this evaluation, in its own words."
            />
            {evaluationReport.limitations.length === 0 ? (
              <p className="note muted">None recorded.</p>
            ) : (
              <ul className="limitation-list">
                {evaluationReport.limitations.map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
            )}
          </Panel>
        </div>
      )}
      <Panel>
        <SectionHeader
          title="Results handoff"
          description="Global cell aggregates are separate projections over the current benchmark; a completed job appears in them immediately when it is benchmark evidence (mock runs never are)."
        />
        <div className="toolbar">
          {view?.available && (
            <Link
              className="btn btn-secondary"
              to={`/agent/${encodeURIComponent(agent)}${cellScope === "synthetic" ? "?evidence=synthetic" : ""}`}
            >
              Open agent profile <ExternalLink size={14} aria-hidden="true" />
            </Link>
          )}
          <Link
            className="btn btn-ghost"
            to={
              cellScope === "synthetic"
                ? "/leaderboard?evidence=synthetic"
                : "/leaderboard"
            }
          >
            Open leaderboard
          </Link>
        </div>
      </Panel>
      <Panel>
        <SectionHeader
          title={
            cellScope === "synthetic"
              ? "Synthetic task aggregates - not benchmark evidence"
              : "Global task aggregates (current benchmark)"
          }
          description={
            cellScope === "synthetic"
              ? "Mock runs are excluded from the benchmark scope, so these cells come from the synthetic view and are shown separately from this evaluation."
              : "Current-version benchmark cells, pooled over every evaluation of this model and shown separately from this evaluation. A task without current-version evidence is marked as missing, not as a zero."
          }
        />
        {view && !view.available ? (
          <p className="note muted">
            {PARAMS_UNAVAILABLE_TITLE}: no per-task cells are requested for this
            evaluation.
          </p>
        ) : cells.loading ? (
          <Loading label="Loading global aggregates…" />
        ) : cells.error ? (
          <ErrorState error={cells.error} onRetry={cells.reload} />
        ) : (
          <div className="table-scroll" tabIndex={0}>
            <table className="data">
              <thead>
                <tr>
                  <th>task</th>
                  <th>global pass rate</th>
                  <th>Wilson interval</th>
                  <th>valid n</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {tasks.map((taskId) => {
                  const cell = cellsByTask.get(taskId);
                  const aggregate = cell?.aggregate;
                  const cellLink = `/cell/${encodeURIComponent(agent)}/${encodeURIComponent(taskId)}${cellScope === "synthetic" ? "?evidence=synthetic" : ""}`;
                  return (
                    <tr key={taskId}>
                      <td className="primary-cell">
                        <Link
                          className="mono"
                          to={`/task/${encodeURIComponent(taskId)}`}
                        >
                          {taskId}
                        </Link>
                      </td>
                      <td className="mono">
                        {aggregate ? (
                          <>
                            {pct(aggregate.pass_rate, 1)}
                            {cellScope === "synthetic" && (
                              <span className="missing-note">
                                Synthetic - not benchmark evidence
                              </span>
                            )}
                          </>
                        ) : cell?.has_historical_evidence &&
                          !cell.has_current_evidence ? (
                          <MissingCurrentEvidence />
                        ) : cellScope === "synthetic" ? (
                          "no synthetic evidence for this task"
                        ) : (
                          "no current benchmark evidence"
                        )}
                      </td>
                      <td>
                        {aggregate ? (
                          <WilsonBar
                            pHat={aggregate.pass_rate}
                            low={aggregate.wilson_low}
                            high={aggregate.wilson_high}
                            width={220}
                            compact
                          />
                        ) : (
                          "—"
                        )}
                      </td>
                      <td className="mono">{aggregate?.n_valid ?? "—"}</td>
                      <td>
                        {cell ? (
                          <LinkArrow to={cellLink}>Open global cell</LinkArrow>
                        ) : (
                          "—"
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </Panel>
      <InlineNotice tone="info">
        Run links on this page resolve through this evaluation&apos;s own trial
        rows, so they never pick another evaluation&apos;s run of the same
        model. Reused trials point at the prior evidence and are labelled
        reused.
      </InlineNotice>
    </div>
  );
}

function ReportMetrics({
  status,
  report,
  fallback,
}: {
  status: JobStatus;
  report: EvaluationReport | null;
  fallback: JobCounters;
}) {
  // The report's counters are recomputed from the trial rows; the job's
  // control-plane counters are only a stand-in until the report loads (it
  // has no "without a usable outcome" count, so that cell waits for it).
  const c = report
    ? report.counters
    : {
        total: fallback.total_runs,
        completed: fallback.completed_runs,
        passed: fallback.passed_runs,
        failed: fallback.failed_runs,
        voided: fallback.voided_runs,
        reused: fallback.reused_runs,
        incomplete: fallback.total_runs - fallback.completed_runs,
        unavailable: null,
      };
  return (
    <>
      <MetricGroup>
        <Metric
          label="Status"
          value={<JobStatusBadge status={report?.status ?? status} />}
          detail={report ? "evaluation report" : "control-plane state"}
        />
        <Metric
          label="Completed"
          value={`${c.completed}/${c.total}`}
          detail="trial rows, reused included"
          mono
        />
        <Metric
          label="Passed"
          value={c.passed}
          detail="fresh functional passes"
          tone="good"
          mono
        />
        <Metric
          label="Failed"
          value={c.failed}
          detail="fresh valid failures"
          tone="bad"
          mono
        />
        <Metric
          label="Voided"
          value={c.voided}
          detail="infra · excluded from n"
          tone="void"
          mono
        />
        <Metric
          label="Reused"
          value={c.reused}
          detail="prior evidence, not fresh"
          mono
        />
        <Metric
          label="Incomplete"
          value={c.incomplete}
          detail="trial rows not completed"
          tone={c.incomplete > 0 ? "warn" : "neutral"}
          mono
        />
        <Metric
          label="No outcome"
          value={c.unavailable ?? "—"}
          detail="rows without a usable score"
          tone={c.unavailable ? "warn" : "neutral"}
          mono
        />
      </MetricGroup>
      {report && (
        <details className="supporting-details">
          <summary>How these counters are defined</summary>
          <dl className="kv">
            {Object.entries(report.counter_semantics).map(([key, text]) => (
              <Fragment key={key}>
                <dt>{key}</dt>
                <dd>{text}</dd>
              </Fragment>
            ))}
          </dl>
        </details>
      )}
    </>
  );
}

function outcomeText(trial: EvaluationReportTrial): {
  text: string;
  tone: string;
} {
  if (trial.evidence_state === "reused")
    return { text: "reused", tone: "neutral" };
  if (!trial.outcome)
    return {
      text: trial.trial_state === "completed" ? "unavailable" : "—",
      tone: "warn",
    };
  if (trial.outcome.voided) return { text: "VOID", tone: "void" };
  return trial.outcome.functional_pass
    ? { text: "PASS", tone: "good" }
    : { text: "FAIL", tone: "bad" };
}

function TrialTable({
  jobId,
  trials,
}: {
  jobId: string;
  trials: EvaluationReportTrial[];
}) {
  if (trials.length === 0)
    return <p className="note muted">This evaluation has no trial rows.</p>;
  return (
    <div className="table-scroll trial-table" tabIndex={0}>
      <table className="data" aria-label="Evaluation trials">
        <thead>
          <tr>
            <th scope="col">task · repeat</th>
            <th scope="col">version</th>
            <th scope="col">trial</th>
            <th scope="col">evidence</th>
            <th scope="col">outcome</th>
            <th scope="col" className="num">
              score
            </th>
            <th scope="col">artifacts</th>
            <th scope="col">comparability</th>
            <th scope="col">provenance</th>
            <th scope="col">run</th>
          </tr>
        </thead>
        <tbody>
          {trials.map((trial) => {
            const outcome = outcomeText(trial);
            return (
              <tr key={`${trial.task_id}:${trial.idx}`}>
                <th scope="row" className="primary-cell">
                  <span className="mono">{trial.task_id}</span> #{trial.idx}
                  {(trial.error_message || trial.integrity_error) && (
                    <span className="missing-note">
                      {trial.integrity_error ?? trial.error_message}
                    </span>
                  )}
                </th>
                <td className="mono">{trial.task_version}</td>
                <td>{trial.trial_state}</td>
                <td>
                  {trial.evidence_state}
                  {trial.evidence_state === "reused" &&
                    trial.source_evaluation_id && (
                      <span className="missing-note">
                        from {trial.source_evaluation_id.slice(0, 10)}
                      </span>
                    )}
                </td>
                <td>
                  <span className={`badge ${outcome.tone}`}>
                    {outcome.text}
                  </span>
                </td>
                <td className="num mono">
                  {trial.outcome ? fixed(trial.outcome.final_score) : "—"}
                </td>
                <td>{trial.artifact_state}</td>
                <td>{trial.comparability ?? "no claim"}</td>
                <td>
                  {trial.provenance}
                  {trial.backend_kind ? ` · ${trial.backend_kind}` : ""}
                </td>
                <td>
                  {trial.run_id !== null ? (
                    <Link
                      className="mono"
                      to={`/jobs/${encodeURIComponent(jobId)}/runs/${encodeURIComponent(trial.task_id)}/${trial.idx}`}
                    >
                      run {trial.run_id}
                    </Link>
                  ) : (
                    "—"
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

const unavailable = "unavailable";

function ReportProvenance({ report }: { report: EvaluationReport }) {
  const gen = report.generation;
  const params = report.evaluation_parameters;
  return (
    <Panel>
      <SectionHeader
        title="Evaluation provenance"
        description="As persisted with this evaluation. A value the server cannot verify is shown as unavailable, never filled in."
      />
      <dl className="kv">
        <dt>evaluation ID</dt>
        <dd className="mono">{report.evaluation_id}</dd>
        <dt>mode</dt>
        <dd>{report.mode ?? unavailable}</dd>
        <dt>model</dt>
        <dd className="mono">{report.model ?? unavailable}</dd>
        <dt>provider</dt>
        <dd>
          {report.backend
            ? `${backendLabel(report.backend.kind)}${report.backend.base_url ? ` · ${report.backend.base_url}` : ""}`
            : unavailable}
        </dd>
        <dt>repeats</dt>
        <dd className="mono">{params.repeats ?? unavailable}</dd>
        <dt>base seed</dt>
        <dd className="mono">
          {gen.base_seed ?? unavailable}
          {gen.seed_provenance ? ` (${gen.seed_provenance})` : ""}
        </dd>
        <dt>temperature</dt>
        <dd className="mono">{gen.temperature ?? unavailable}</dd>
        <dt>request timeout</dt>
        <dd className="mono">
          {gen.request_timeout_s !== null
            ? `${gen.request_timeout_s} s`
            : unavailable}
          {gen.timeout_provenance ? ` (${gen.timeout_provenance})` : ""}
        </dd>
        {params.source_evaluation_id && (
          <>
            <dt>source evaluation</dt>
            <dd className="mono">{params.source_evaluation_id}</dd>
          </>
        )}
        <dt>created</dt>
        <dd>{formatDate(report.created_at)}</dd>
        <dt>started</dt>
        <dd>{formatDate(report.started_at)}</dd>
        <dt>finished</dt>
        <dd>{formatDate(report.finished_at)}</dd>
      </dl>
      <div className="table-scroll" tabIndex={0}>
        <table className="data" aria-label="Task snapshots">
          <thead>
            <tr>
              <th scope="col">task snapshot</th>
              <th scope="col">version</th>
              <th scope="col">content digest</th>
            </tr>
          </thead>
          <tbody>
            {report.task_snapshots.length === 0 ? (
              <tr>
                <td colSpan={3}>{unavailable}</td>
              </tr>
            ) : (
              report.task_snapshots.map((task) => (
                <tr key={task.task_id}>
                  <th scope="row" className="mono">
                    {task.task_id}
                  </th>
                  <td className="mono">{task.task_version}</td>
                  <td className="mono" title={task.task_digest}>
                    {task.task_digest.replace(/^sha256:/, "").slice(0, 16)}…
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </Panel>
  );
}
