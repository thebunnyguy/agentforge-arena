import { useMemo } from "react";
import { ArrowLeft, ExternalLink } from "lucide-react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api/client";
import { useAsync } from "../lib/useAsync";
import { useJobEvents } from "../lib/useJobEvents";
import { TaskRunGrid } from "../components/TaskRunGrid";
import { CaveatBanner } from "../components/CaveatBanner";
import { ErrorState, Loading } from "../components/States";
import { JobStatusBadge } from "../components/Badges";
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
  const agent = job.data?.params.model ?? "";
  const taskKey = job.data?.params.tasks.join(",") ?? "";
  const cells = useAsync(
    (signal) =>
      job.data
        ? Promise.all(
            job.data.params.tasks.map((task) => api.cell(agent, task, signal)),
          )
        : Promise.resolve([]),
    [agent, taskKey],
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
        title={evaluation.params.model}
        description={`${taskScope(evaluation.params.tasks.length, evaluation.params.repeats)} · evaluation ${evaluation.id.slice(0, 10)}`}
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
          description="The task/repeat tape below is scoped to this evaluation. Global cell aggregates are separate API projections and may require an API reload after a newly completed job."
        />
        <div className="toolbar">
          <Link
            className="btn btn-secondary"
            to={`/agent/${encodeURIComponent(agent)}`}
          >
            Open agent profile <ExternalLink size={14} aria-hidden="true" />
          </Link>
          <Link className="btn btn-ghost" to="/leaderboard">
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
          title="Global task aggregates"
          description="These are global task cells shown separately from this evaluation."
        />
        {cells.loading ? (
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
                {evaluation.params.tasks.map((taskId) => {
                  const aggregate = cellsByTask.get(taskId)?.aggregate;
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
                        {aggregate
                          ? pct(aggregate.pass_rate, 1)
                          : "not available in loaded snapshot"}
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
                        {aggregate ? (
                          <LinkArrow
                            to={`/cell/${encodeURIComponent(agent)}/${encodeURIComponent(taskId)}`}
                          >
                            Open global cell
                          </LinkArrow>
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
