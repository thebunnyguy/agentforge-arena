import { Link } from "react-router-dom";
import { api } from "../api/client";
import { useAsync } from "../lib/useAsync";
import { ErrorState, SkeletonRows } from "../components/States";
import { pct } from "../lib/format";

// Agent × domain matrix assembled from per-agent domain profiles. Each cell
// renders the server's pooled pass rate when `displayable`, otherwise the
// honest "--" placeholder. No pooling math here — values come from the kernel
// via /domains/{agent}.
export function DomainMatrix({ agents }: { agents: string[] }) {
  const { data, loading, error, reload } = useAsync(
    (s) => api.domainMatrix(agents, s),
    [agents.join(",")],
  );

  if (loading) return <SkeletonRows rows={Math.max(agents.length, 3)} cols={6} />;
  if (error) return <ErrorState error={error} onRetry={reload} />;
  if (!data || data.agents.length === 0 || data.domains.length === 0) {
    return <p className="note muted">No domain data available.</p>;
  }

  return (
    <table className="data matrix">
      <thead>
        <tr>
          <th>agent</th>
          {data.domains.map((d) => (
            <th key={d} className="num" title={d}>
              {d}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {data.agents.map((agent) => (
          <tr key={agent}>
            <td>
              <Link to={`/agent/${encodeURIComponent(agent)}`}>{agent}</Link>
            </td>
            {data.domains.map((domain) => {
              const cell = data.byAgent[agent]?.[domain];
              if (!cell || !cell.displayable) {
                return (
                  <td
                    key={domain}
                    className="cell"
                    title={
                      cell
                        ? `not displayable — ${cell.n_tasks} tasks, ${cell.n_runs} runs (needs ≥5 tasks & ≥25 runs)`
                        : "no data"
                    }
                  >
                    <span className="dash">--</span>
                  </td>
                );
              }
              return (
                <td
                  key={domain}
                  className="cell"
                  title={`${cell.n_tasks} tasks · ${cell.n_runs} runs`}
                >
                  <Link to={`/agent/${encodeURIComponent(agent)}`}>
                    {pct(cell.pooled_pass_rate, 0)}
                  </Link>
                </td>
              );
            })}
          </tr>
        ))}
      </tbody>
    </table>
  );
}
