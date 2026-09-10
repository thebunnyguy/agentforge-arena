import { Search, Users } from "lucide-react";
import { Link } from "react-router-dom";
import { useMemo, useState } from "react";
import { api } from "../api/client";
import { useAsync } from "../lib/useAsync";
import { CaveatBanner } from "../components/CaveatBanner";
import { ErrorState, Loading, EmptyState } from "../components/States";
import { PageHeader, Panel, SectionHeader } from "../components/Primitives";
import { WilsonBar } from "../components/WilsonBar";
import { pct, rankLabel } from "../lib/format";

export function Agents() {
  const meta = useAsync((signal) => api.meta(signal), []);
  const leaderboard = useAsync((signal) => api.leaderboard(null, signal), []);
  const [query, setQuery] = useState("");

  const entries = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return (leaderboard.data?.entries ?? []).filter(
      (entry) => !needle || entry.agent.toLowerCase().includes(needle),
    );
  }, [leaderboard.data, query]);

  if (meta.loading) return <Loading label="Loading agent roster…" />;
  if (meta.error)
    return <ErrorState error={meta.error} onRetry={meta.reload} />;

  return (
    <div>
      <PageHeader
        eyebrow="Analyze"
        title="Agents"
        description="Model identities in the evidence store. Open a profile to see where each agent succeeds, fails, or remains uncertain."
      />
      <CaveatBanner caveat={meta.data?.notes?.trust} />
      <Panel>
        <SectionHeader
          title="Agent roster"
          description={`${meta.data!.models.length} real model identities from the API.`}
        />
        <div className="toolbar">
          <div className="search-field">
            <Search size={15} aria-hidden="true" />
            <input
              aria-label="Search agents"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Search model IDs…"
            />
          </div>
        </div>
        {leaderboard.loading ? (
          <Loading />
        ) : leaderboard.error ? (
          <ErrorState error={leaderboard.error} onRetry={leaderboard.reload} />
        ) : entries.length === 0 ? (
          <EmptyState title="No matching agents">
            <p>Try a different model ID.</p>
          </EmptyState>
        ) : (
          <div className="table-scroll" tabIndex={0}>
            <table className="data">
              <thead>
                <tr>
                  <th>agent</th>
                  <th>benchmark position</th>
                  <th>pass rate</th>
                  <th>valid n</th>
                  <th>uncertainty</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {entries.map((entry) => (
                  <tr key={entry.agent}>
                    <td className="primary-cell">
                      <Link to={`/agent/${encodeURIComponent(entry.agent)}`}>
                        {entry.agent}
                      </Link>
                      <span className="sub-cell">
                        {entry.synthetic
                          ? "synthetic baseline"
                          : "model evidence"}
                      </span>
                    </td>
                    <td className="mono">
                      {rankLabel(
                        entry.provisional,
                        entry.rank_low,
                        entry.rank_high,
                      )}
                    </td>
                    <td className="mono">{pct(entry.pass_rate, 1)}</td>
                    <td className="mono">{entry.n}</td>
                    <td>
                      <WilsonBar
                        pHat={entry.pass_rate}
                        low={entry.wilson_low}
                        high={entry.wilson_high}
                        width={180}
                        compact
                      />
                    </td>
                    <td>
                      <Link
                        className="link-arrow"
                        to={`/agent/${encodeURIComponent(entry.agent)}`}
                      >
                        <Users size={14} aria-hidden="true" /> Profile
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>
    </div>
  );
}
