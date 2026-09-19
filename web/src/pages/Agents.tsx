import { Search, Users } from "lucide-react";
import { Link } from "react-router-dom";
import { useMemo, useState } from "react";
import { api } from "../api/client";
import { useAsync } from "../lib/useAsync";
import { CaveatBanner } from "../components/CaveatBanner";
import { EvidenceScopeBanner } from "../components/EvidenceScopeBanner";
import { MissingCurrentEvidence, ProvisionalBadge } from "../components/Badges";
import { ErrorState, Loading, EmptyState } from "../components/States";
import { PageHeader, Panel, SectionHeader } from "../components/Primitives";
import { WilsonBar } from "../components/WilsonBar";
import { pct, rankLabel } from "../lib/format";
import { linkQuery, useEvidenceScope } from "../lib/useEvidenceScope";

export function Agents() {
  const [scope, setScope] = useEvidenceScope();
  const meta = useAsync(
    (signal) => api.meta({ evidence: scope }, signal),
    [scope],
  );
  const leaderboard = useAsync(
    (signal) => api.leaderboard(null, { evidence: scope }, signal),
    [scope],
  );
  const [query, setQuery] = useState("");

  const needle = query.trim().toLowerCase();
  const entries = useMemo(
    () =>
      (leaderboard.data?.entries ?? []).filter(
        (entry) => !needle || entry.agent.toLowerCase().includes(needle),
      ),
    [leaderboard.data, needle],
  );
  // Left join: every roster model appears, even with no current evidence.
  const missing = useMemo(() => {
    const ranked = new Set(
      (leaderboard.data?.entries ?? []).map((e) => e.agent),
    );
    const historicalOnly = new Set([
      ...(leaderboard.data?.historical_only_agents ?? []),
      ...(meta.data?.historical_only_models ?? []),
    ]);
    const roster = new Set([...(meta.data?.models ?? []), ...historicalOnly]);
    return [...roster]
      .filter((agent) => !ranked.has(agent))
      .filter((agent) => !needle || agent.toLowerCase().includes(needle))
      .sort()
      .map((agent) => ({ agent, historical: historicalOnly.has(agent) }));
  }, [leaderboard.data, meta.data, needle]);

  if (meta.loading) return <Loading label="Loading agent roster…" />;
  if (meta.error)
    return <ErrorState error={meta.error} onRetry={meta.reload} />;

  const benchmark = meta.data!.current_benchmark;
  const rosterSize = new Set([
    ...meta.data!.models,
    ...(meta.data!.historical_only_models ?? []),
  ]).size;

  return (
    <div>
      <PageHeader
        eyebrow="Analyze"
        title="Agents"
        description="Model identities in the evidence store, positioned on the current benchmark. Open a profile to see where each agent succeeds, fails, or remains uncertain."
      />
      <CaveatBanner caveat={meta.data?.notes?.trust} />
      <EvidenceScopeBanner
        scope={scope}
        onScopeChange={setScope}
        coverage={
          benchmark
            ? {
                withCurrent: benchmark.tasks_with_current_evidence,
                total: benchmark.n_tasks,
              }
            : null
        }
      />
      <Panel>
        <SectionHeader
          title="Agent roster"
          description={`${rosterSize} model identities from the API${benchmark ? ` · ${benchmark.models_with_current_evidence} with current benchmark evidence` : ""}.`}
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
        ) : entries.length === 0 && missing.length === 0 ? (
          <EmptyState title="No matching agents">
            <p>
              {needle
                ? "Try a different model ID."
                : "No agents have evidence in the selected scope."}
            </p>
          </EmptyState>
        ) : (
          <div className="table-scroll" tabIndex={0}>
            <table className="data">
              <thead>
                <tr>
                  <th>agent</th>
                  <th>current benchmark position</th>
                  <th>coverage</th>
                  <th>pass rate</th>
                  <th>valid n</th>
                  <th>uncertainty</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {entries.map((entry) => {
                  const cov = entry.coverage;
                  const classes =
                    meta.data?.evidence_counts?.[entry.agent]?.current_by_class;
                  return (
                    <tr key={entry.agent}>
                      <td className="primary-cell">
                        <Link
                          to={`/agent/${encodeURIComponent(entry.agent)}${linkQuery(scope)}`}
                        >
                          {entry.agent}
                        </Link>
                        <span className="sub-cell">
                          {entry.synthetic
                            ? "synthetic baseline"
                            : classes
                              ? `evidence: ${
                                  Object.entries(classes)
                                    .filter(([, n]) => n > 0)
                                    .map(([cls, n]) => `${cls} ${n} runs`)
                                    .join(" · ") || "none"
                                }`
                              : "model evidence"}
                        </span>
                      </td>
                      <td className="mono">
                        {entry.provisional ? (
                          <ProvisionalBadge />
                        ) : (
                          rankLabel(
                            entry.provisional,
                            entry.rank_low,
                            entry.rank_high,
                          )
                        )}
                        {cov && !cov.complete && (
                          <span className="sub-cell">
                            <span className="badge warn">PARTIAL COVERAGE</span>
                          </span>
                        )}
                      </td>
                      <td className="mono">
                        {cov
                          ? `${cov.tasks_with_current_evidence}/${cov.tasks_total}`
                          : "—"}
                        <span className="sub-cell">
                          tasks with current evidence
                        </span>
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
                          to={`/agent/${encodeURIComponent(entry.agent)}${linkQuery(scope)}`}
                        >
                          <Users size={14} aria-hidden="true" /> Profile
                        </Link>
                      </td>
                    </tr>
                  );
                })}
                {missing.map(({ agent, historical }) => {
                  const counts = meta.data?.evidence_counts?.[agent];
                  return (
                    <tr className="row-missing" key={`missing-${agent}`}>
                      <td className="primary-cell">
                        <Link
                          to={`/agent/${encodeURIComponent(agent)}${linkQuery(scope)}`}
                        >
                          {agent}
                        </Link>
                        <span className="sub-cell">model evidence</span>
                      </td>
                      <td>
                        <span className="badge warn">NOT RANKED</span>
                      </td>
                      <td className="mono">
                        {counts
                          ? `${counts.current_tasks}/${counts.tasks_total}`
                          : "—"}
                        <span className="sub-cell">
                          tasks with current evidence
                        </span>
                      </td>
                      <td colSpan={3}>
                        <MissingCurrentEvidence
                          historicalAvailable={historical}
                          detail={
                            counts
                              ? `(${counts.historical_runs} historical runs on ${counts.historical_tasks} tasks)`
                              : undefined
                          }
                        />
                      </td>
                      <td>
                        <Link
                          className="link-arrow"
                          to={`/agent/${encodeURIComponent(agent)}${linkQuery(scope)}`}
                        >
                          <Users size={14} aria-hidden="true" /> Profile
                        </Link>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </Panel>
    </div>
  );
}
