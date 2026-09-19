import { useMemo } from "react";
import { ArrowLeft, ExternalLink } from "lucide-react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api/client";
import { useAsync } from "../lib/useAsync";
import { useJobEvents } from "../lib/useJobEvents";
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
import type { EvidenceScope } from "../api/types";
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
import { pct, taskScope } from "../lib/format";

export function JobResults() {
  const { jobId = "" } = useParams();
  const job = useAsync((signal) => api.job(jobId, signal), [jobId]);
  const stream = useJobEvents(jobId, true);
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
          <Link
            className="btn btn-secondary"
            to={`/jobs/${encodeURIComponent(evaluation.id)}`}
          >
            <ArrowLeft size={15} aria-hidden="true" /> Monitor
          </Link>
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
      <MetricGroup>
        <Metric
          label="Status"
          value={<JobStatusBadge status={evaluation.status} />}
          detail="control-plane state"
        />
        <Metric
          label="Completed"
          value={`${evaluation.counters.completed_runs}/${evaluation.counters.total_runs}`}
          detail="job counters"
          mono
        />
        <Metric
          label="Passed"
          value={evaluation.counters.passed_runs}
          detail="fresh functional passes"
          tone="good"
          mono
        />
        <Metric
          label="Voided / reused"
          value={`${evaluation.counters.voided_runs} / ${evaluation.counters.reused_runs}`}
          detail="voided excluded · reused retained"
          tone="void"
          mono
        />
      </MetricGroup>
      <Panel>
        <SectionHeader
          title="Results handoff"
          description="The task/repeat tape below is scoped to this evaluation. Global cell aggregates are separate projections over the current benchmark; a completed job appears in them immediately when it is benchmark evidence (mock runs never are)."
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
        {stream.historyError && (
          <InlineNotice tone="warn">
            Event history is incomplete: {stream.historyError.message}
          </InlineNotice>
        )}
      </Panel>
      <Panel>
        <SectionHeader
          title="Task and repeat outcomes"
          description="Only persisted or reused evidence gets a forensic run link. Pending, running, unknown, and task-level errors remain unlinked."
        />
        {stream.historyLoading && stream.events.length === 0 ? (
          <Loading label="Loading evaluation tape…" />
        ) : (
          <TaskRunGrid
            job={evaluation}
            events={stream.events}
            historyLoading={stream.historyLoading}
            historyError={stream.historyError}
          />
        )}
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
              : "Current-version benchmark cells shown separately from this evaluation. A task without current-version evidence is marked as missing, not as a zero."
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
        Job-scoped run URLs resolve through the stored model/task/repeat
        identity. They do not create a separate database namespace; reused runs
        are labelled as reused evidence.
      </InlineNotice>
    </div>
  );
}
