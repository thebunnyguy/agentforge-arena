import type { CSSProperties } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import { useAsync } from "../lib/useAsync";
import { ErrorState, SkeletonRows } from "../components/States";
import { pct } from "../lib/format";

export function DomainMatrix({ agents }: { agents: string[] }) {
  const matrix = useAsync(
    (signal) => api.domainMatrix(agents, signal),
    [agents.join(",")],
  );

  if (matrix.loading)
    return <SkeletonRows rows={Math.max(agents.length, 3)} cols={6} />;
  if (matrix.error)
    return <ErrorState error={matrix.error} onRetry={matrix.reload} />;
  if (
    !matrix.data ||
    matrix.data.agents.length === 0 ||
    matrix.data.domains.length === 0
  ) {
    return (
      <p className="note muted">No domain data available from the local API.</p>
    );
  }

  return (
    <div className="table-scroll" tabIndex={0}>
      <table className="data matrix">
        <thead>
          <tr>
            <th>agent</th>
            {matrix.data.domains.map((domain) => (
              <th key={domain} className="num" title={domain}>
                {domain}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {matrix.data.agents.map((agent) => (
            <tr key={agent}>
              <td className="primary-cell">
                <Link to={`/agent/${encodeURIComponent(agent)}`}>{agent}</Link>
              </td>
              {matrix.data!.domains.map((domain) => {
                const cell = matrix.data!.byAgent[agent]?.[domain];
                if (!cell || !cell.displayable) {
                  return (
                    <td
                      key={domain}
                      className="cell"
                      title={
                        cell
                          ? `Not displayable · ${cell.n_tasks} tasks · ${cell.n_runs} runs`
                          : "No data"
                      }
                    >
                      <span className="dash">—</span>
                    </td>
                  );
                }
                return (
                  <td
                    key={domain}
                    className="cell matrix-heat"
                    style={{ "--heat": cell.pooled_pass_rate } as CSSProperties}
                    title={`${cell.n_tasks} tasks · ${cell.n_runs} runs · Wilson ${pct(cell.wilson_low, 0)}–${pct(cell.wilson_high, 0)}`}
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
    </div>
  );
}
