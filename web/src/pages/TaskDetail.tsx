import { Link, useParams } from "react-router-dom";
import { api } from "../api/client";
import { useAsync } from "../lib/useAsync";
import { WilsonBar } from "../components/WilsonBar";
import { ProvisionalBadge } from "../components/Badges";
import { CaveatBanner } from "../components/CaveatBanner";
import { ErrorState, Loading } from "../components/States";
import { fixed, rankLabel } from "../lib/format";

// Per-task view = leaderboard scoped to this task. Each agent row links to the
// agent × task cell. Uses the task-scoped leaderboard endpoint only.
export function TaskDetail() {
  const { taskId = "" } = useParams();
  const lb = useAsync((s) => api.leaderboard(taskId, s), [taskId]);
  const meta = useAsync((s) => api.meta(s), []);
  const task = meta.data?.tasks.find((t) => t.task_id === taskId);

  if (lb.loading) return <Loading label={`Loading ${taskId}…`} />;
  if (lb.error) return <ErrorState error={lb.error} onRetry={lb.reload} />;

  return (
    <div>
      <h1 className="page-title">{taskId}</h1>
      <p className="page-subtitle">
        Version <code>{task?.current_version ?? "—"}</code> · ranking scoped to
        this task.
      </p>
      <CaveatBanner caveat={meta.data?.notes?.trust} />

      <div className="panel">
        <h2>Agents on this task</h2>
        <table className="data">
          <thead>
            <tr>
              <th className="num">rank</th>
              <th>agent</th>
              <th className="num">n</th>
              <th className="num">p̂</th>
              <th>interval</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {lb.data!.entries.map((e) => (
              <tr key={e.agent}>
                <td className="num">
                  {e.provisional ? (
                    <ProvisionalBadge />
                  ) : (
                    rankLabel(e.provisional, e.rank_low, e.rank_high)
                  )}
                </td>
                <td>
                  <Link to={`/agent/${encodeURIComponent(e.agent)}`}>{e.agent}</Link>
                </td>
                <td className="num">{e.n}</td>
                <td className="num">{fixed(e.pass_rate)}</td>
                <td>
                  <WilsonBar pHat={e.pass_rate} low={e.wilson_low} high={e.wilson_high} />
                </td>
                <td>
                  <Link
                    to={`/cell/${encodeURIComponent(e.agent)}/${encodeURIComponent(taskId)}`}
                  >
                    open cell →
                  </Link>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
