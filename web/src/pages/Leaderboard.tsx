import { useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import { useAsync } from "../lib/useAsync";
import { WilsonBar } from "../components/WilsonBar";
import { ProvisionalBadge } from "../components/Badges";
import { CaveatBanner } from "../components/CaveatBanner";
import { ErrorState, SkeletonRows } from "../components/States";
import { fixed, rankLabel } from "../lib/format";

export function Leaderboard() {
  const [taskId, setTaskId] = useState<string>("");
  const meta = useAsync((s) => api.meta(s), []);
  const lb = useAsync((s) => api.leaderboard(taskId || null, s), [taskId]);

  return (
    <div>
      <h1 className="page-title">Leaderboard</h1>
      <p className="page-subtitle">
        Wilson lower-bound ranking. Choose a single task to scope the ranking, or
        keep "All tasks (pooled)".
      </p>
      <CaveatBanner caveat={meta.data?.notes?.trust} />

      <div className="toolbar">
        <label htmlFor="scope">Scope</label>
        <select id="scope" value={taskId} onChange={(e) => setTaskId(e.target.value)}>
          <option value="">All tasks (pooled)</option>
          {meta.data?.tasks.map((t) => (
            <option key={t.task_id} value={t.task_id}>
              {t.task_id}
            </option>
          ))}
        </select>
      </div>

      <div className="panel">
        {lb.loading ? (
          <SkeletonRows rows={5} cols={5} />
        ) : lb.error ? (
          <ErrorState error={lb.error} onRetry={lb.reload} />
        ) : (
          <table className="data">
            <thead>
              <tr>
                <th className="num">rank</th>
                <th>agent</th>
                <th className="num">n</th>
                <th className="num">p̂</th>
                <th className="num">LCB</th>
                <th>95% Wilson interval</th>
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
                    {taskId && (
                      <>
                        {" · "}
                        <Link
                          to={`/cell/${encodeURIComponent(e.agent)}/${encodeURIComponent(taskId)}`}
                        >
                          cell
                        </Link>
                      </>
                    )}
                  </td>
                  <td className="num">{e.n}</td>
                  <td className="num">{fixed(e.pass_rate)}</td>
                  <td className="num">{fixed(e.wilson_low)}</td>
                  <td>
                    <WilsonBar pHat={e.pass_rate} low={e.wilson_low} high={e.wilson_high} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        <p className="note muted">
          Strict out-ranking uses LCB&gt;p̂ ties (kernel §6). Provisional agents
          (n&lt;5) are unranked. All values server-computed.
        </p>
      </div>
    </div>
  );
}
