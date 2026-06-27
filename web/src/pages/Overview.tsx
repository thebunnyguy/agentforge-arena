import { Link } from "react-router-dom";
import { api } from "../api/client";
import { useAsync } from "../lib/useAsync";
import { CaveatBanner } from "../components/CaveatBanner";
import { WilsonBar } from "../components/WilsonBar";
import { ProvisionalBadge } from "../components/Badges";
import { ErrorState, Loading, SkeletonRows } from "../components/States";
import { fixed, pct, rankLabel } from "../lib/format";
import { DomainMatrix } from "./DomainMatrix";

export function Overview() {
  const overview = useAsync((s) => api.overview(s), []);
  const meta = useAsync((s) => api.meta(s), []);
  const lb = useAsync((s) => api.leaderboard(null, s), []);

  if (overview.error)
    return <ErrorState error={overview.error} onRetry={overview.reload} />;

  const obs = overview.data?.observability;

  return (
    <div>
      <h1 className="page-title">Overview</h1>
      <p className="page-subtitle">
        Pooled-across-tasks leaderboard and per-domain capability for every agent
        in the local benchmark store.
      </p>

      <CaveatBanner caveat={meta.data?.notes?.trust} />

      {/* Run/DB summary */}
      <div className="grid-2" style={{ marginBottom: 20 }}>
        <Stat label="Total runs" value={obs?.total_runs ?? "—"} />
        <Stat label="Agents" value={overview.data?.models.length ?? "—"} />
        <Stat label="Tasks" value={overview.data?.n_tasks ?? "—"} />
        <Stat
          label="Patch coverage"
          value={obs ? `${obs.runs_with_patch} / ${obs.total_runs}` : "—"}
        />
        <Stat
          label="Test-result coverage"
          value={obs ? `${obs.runs_with_test_results} / ${obs.total_runs}` : "—"}
        />
        <Stat
          label="Synthetic baselines"
          value={overview.data?.synthetic_agents.length ?? "—"}
        />
      </div>

      {/* Hero: leaderboard with Wilson-interval bars */}
      <div className="panel">
        <h2>Leaderboard — Wilson lower-bound ranking (pooled across tasks)</h2>
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
                  </td>
                  <td className="num">{e.n}</td>
                  <td className="num">{fixed(e.pass_rate)}</td>
                  <td>
                    <WilsonBar pHat={e.pass_rate} low={e.wilson_low} high={e.wilson_high} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        <p className="note muted">
          Ranks come straight from the kernel's Wilson-LCB ranking. Agents with
          n&lt;5 valid runs are <em>provisional</em> and excluded from ranking. The
          interval bar shows p̂ (point) inside the server-computed 95% Wilson
          interval. No interval is recomputed in the browser — values are rendered
          as returned by the API.
        </p>
      </div>

      {/* Domain matrix */}
      <div className="panel">
        <h2>Domain capability matrix</h2>
        <p className="note muted">
          Pooled per-domain pass rate per agent. A cell shows{" "}
          <code>--</code> when the domain is not <em>displayable</em> for that agent
          (kernel rule: ≥5 tasks AND ≥25 runs). Non-displayable cells are
          deliberately blank rather than showing an unstable number.
        </p>
        {overview.loading ? (
          <Loading />
        ) : (
          <DomainMatrix agents={overview.data?.models ?? []} />
        )}
      </div>

      {/* Coverage / version distribution */}
      {meta.data && meta.data.tasks.length > 0 && (
        <div className="panel">
          <h2>Task version coverage</h2>
          <table className="data">
            <thead>
              <tr>
                <th>task</th>
                <th>current version</th>
                <th>evaluated versions</th>
              </tr>
            </thead>
            <tbody>
              {meta.data.tasks.map((t) => (
                <tr key={t.task_id}>
                  <td>
                    <Link to={`/task/${encodeURIComponent(t.task_id)}`}>
                      {t.task_id}
                    </Link>
                  </td>
                  <td className="mono">{t.current_version ?? "—"}</td>
                  <td className="mono">
                    {t.evaluated_versions.length > 0
                      ? t.evaluated_versions.join(", ")
                      : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function Stat({
  label,
  value,
  mono,
}: {
  label: string;
  value: React.ReactNode;
  mono?: boolean;
}) {
  return (
    <div className="stat">
      <div className="label">{label}</div>
      <div className={`value ${mono ? "mono" : ""}`}>{value}</div>
    </div>
  );
}

export { pct };
