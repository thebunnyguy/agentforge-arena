import type { CSSProperties } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import type { EvidenceScope } from "../api/types";
import { useAsync } from "../lib/useAsync";
import { MissingCurrentEvidence } from "../components/Badges";
import { ErrorState, SkeletonRows } from "../components/States";
import { pct } from "../lib/format";
import { linkQuery } from "../lib/useEvidenceScope";

// Domain heat grid over CURRENT-version evidence. A model with no current
// evidence gets one explicit MISSING cell instead of a row of dashes, so
// "no current evidence" is never confused with "suppressed".
export function DomainMatrix({
  agents,
  scope = "benchmark",
}: {
  agents: string[];
  scope?: EvidenceScope;
}) {
  const matrix = useAsync(
    (signal) => api.domainMatrix(agents, { evidence: scope }, signal),
    [agents.join(","), scope],
  );

  if (matrix.loading)
    return <SkeletonRows rows={Math.max(agents.length, 3)} cols={6} />;
  if (matrix.error)
    return <ErrorState error={matrix.error} onRetry={matrix.reload} />;
  if (!matrix.data || matrix.data.agents.length === 0) {
    return (
      <p className="note muted">
        No agents have evidence in the selected scope.
      </p>
    );
  }
  if (matrix.data.domains.length === 0) {
    return (
      <p className="note muted">No domain data available from the local API.</p>
    );
  }
  const domainCount = matrix.data.domains.length;

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
          {matrix.data.agents.map((agent) => {
            const profile = matrix.data!.profiles[agent];
            // Server enum: evidence_status "current" | "historical_only" |
            // "none" | "synthetic". Absent (old payload) => treat as current.
            const status = profile?.evidence_status ?? "current";
            const noCurrent = status === "historical_only" || status === "none";
            return (
              <tr key={agent}>
                <td className="primary-cell">
                  <Link
                    to={`/agent/${encodeURIComponent(agent)}${linkQuery(scope)}`}
                  >
                    {agent}
                  </Link>
                </td>
                {noCurrent ? (
                  <td className="cell" colSpan={domainCount}>
                    <MissingCurrentEvidence
                      historicalAvailable={status === "historical_only"}
                    />
                  </td>
                ) : (
                  matrix.data!.domains.map((domain) => {
                    const cell = matrix.data!.byAgent[agent]?.[domain];
                    if (!cell || !cell.displayable) {
                      return (
                        <td
                          key={domain}
                          className="cell"
                          title={
                            cell
                              ? `Suppressed (needs 5 tasks and 25 runs of current evidence) · ${cell.n_tasks} current-version tasks · ${cell.n_runs} runs`
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
                        style={
                          { "--heat": cell.pooled_pass_rate } as CSSProperties
                        }
                        title={`${cell.n_tasks} current-version tasks · ${cell.n_runs} runs · Wilson ${pct(cell.wilson_low, 0)}–${pct(cell.wilson_high, 0)}`}
                      >
                        <Link
                          to={`/agent/${encodeURIComponent(agent)}${linkQuery(scope)}`}
                        >
                          {pct(cell.pooled_pass_rate, 0)}
                        </Link>
                      </td>
                    );
                  })
                )}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
