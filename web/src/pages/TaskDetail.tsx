import { ArrowLeft, Info } from "lucide-react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api/client";
import { useAsync } from "../lib/useAsync";
import { WilsonBar } from "../components/WilsonBar";
import { ProvisionalBadge } from "../components/Badges";
import { CaveatBanner } from "../components/CaveatBanner";
import { ErrorState, Loading } from "../components/States";
import {
  LinkArrow,
  Metric,
  MetricGroup,
  PageHeader,
  Panel,
  SectionHeader,
} from "../components/Primitives";
import { pct, rankLabel } from "../lib/format";

export function TaskDetail() {
  const { taskId = "" } = useParams();
  const leaderboard = useAsync(
    (signal) => api.leaderboard(taskId, signal),
    [taskId],
  );
  const meta = useAsync((signal) => api.meta(signal), []);
  if (leaderboard.loading || meta.loading)
    return <Loading label={`Loading ${taskId}…`} />;
  if (leaderboard.error)
    return (
      <ErrorState error={leaderboard.error} onRetry={leaderboard.reload} />
    );
  if (meta.error)
    return <ErrorState error={meta.error} onRetry={meta.reload} />;

  const task = meta.data!.tasks.find(
    (candidate) => candidate.task_id === taskId,
  );
  return (
    <div>
      <PageHeader
        eyebrow="Task detail"
        title={taskId}
        description="Which agents solve this task reliably? Compare the server-ranked outcomes, then drill into the cell evidence."
        actions={
          <Link className="btn btn-secondary" to="/tasks">
            <ArrowLeft size={15} aria-hidden="true" /> All tasks
          </Link>
        }
      />
      <CaveatBanner caveat={meta.data?.notes?.trust} />
      <MetricGroup>
        <Metric
          label="Current version"
          value={task?.current_version ?? "—"}
          detail="task contract"
          mono
        />
        <Metric
          label="Difficulty"
          value={task?.difficulty ?? "—"}
          detail="task metadata"
          mono
        />
        <Metric
          label="Activity"
          value={task?.activity ?? "—"}
          detail="benchmark context"
        />
        <Metric
          label="Agents"
          value={leaderboard.data!.entries.length}
          detail="returned for this scope"
          mono
        />
      </MetricGroup>
      <Panel>
        <SectionHeader
          title="Task metadata"
          description="Task contract fields are shown as recorded, including version and domain weights."
        />
        <dl className="kv">
          <dt>task ID</dt>
          <dd>{taskId}</dd>
          <dt>version</dt>
          <dd>{task?.current_version ?? "—"}</dd>
          <dt>activity</dt>
          <dd>{task?.activity ?? "—"}</dd>
          <dt>scale</dt>
          <dd>{task?.scale ?? "—"}</dd>
          <dt>domains</dt>
          <dd>
            {task?.domains
              .map((tag) => `${tag.domain} (${tag.weight})`)
              .join(", ") || "—"}
          </dd>
          <dt>evaluated versions</dt>
          <dd>{task?.evaluated_versions.join(", ") || "—"}</dd>
        </dl>
      </Panel>
      {meta.data!.synthetic_agents.length > 0 && (
        <Panel>
          <SectionHeader
            title="Synthetic references"
            description="API-returned oracle/noop reference rows are deterministic bookends, not competing agents."
          />
          <div className="reference-links">
            {meta.data!.synthetic_agents.map((reference) => (
              <div className="reference-link" key={reference}>
                <span>{reference}</span>
                <span>
                  <Link
                    to={`/cell/${encodeURIComponent(reference)}/${encodeURIComponent(taskId)}`}
                  >
                    cell
                  </Link>{" "}
                  ·{" "}
                  <Link
                    to={`/cell/${encodeURIComponent(reference)}/${encodeURIComponent(taskId)}/run/0`}
                  >
                    run #0
                  </Link>
                </span>
              </div>
            ))}
          </div>
        </Panel>
      )}
      <Panel>
        <SectionHeader
          title="Agent performance"
          description="Rows remain in the order returned by the kernel-scoped leaderboard."
        />
        <div className="table-scroll" tabIndex={0}>
          <table className="data">
            <thead>
              <tr>
                <th className="num">rank</th>
                <th>agent</th>
                <th>pass rate</th>
                <th>valid n</th>
                <th>Wilson interval</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {leaderboard.data!.entries.map((entry) => (
                <tr key={entry.agent}>
                  <td className="num">
                    {entry.provisional ? (
                      <ProvisionalBadge />
                    ) : (
                      rankLabel(
                        entry.provisional,
                        entry.rank_low,
                        entry.rank_high,
                      )
                    )}
                  </td>
                  <td className="primary-cell">
                    <Link to={`/agent/${encodeURIComponent(entry.agent)}`}>
                      {entry.agent}
                    </Link>
                  </td>
                  <td className="mono">{pct(entry.pass_rate, 1)}</td>
                  <td className="mono">{entry.n}</td>
                  <td>
                    <WilsonBar
                      pHat={entry.pass_rate}
                      low={entry.wilson_low}
                      high={entry.wilson_high}
                    />
                  </td>
                  <td>
                    <LinkArrow
                      to={`/cell/${encodeURIComponent(entry.agent)}/${encodeURIComponent(taskId)}`}
                    >
                      Open cell
                    </LinkArrow>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="inline-notice notice-info">
          <Info size={16} aria-hidden="true" />
          <span>
            Open a cell to see individual repeats, voided runs, score
            primitives, capture state, and forensic artifacts.
          </span>
        </div>
      </Panel>
    </div>
  );
}
