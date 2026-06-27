import { Link, useParams } from "react-router-dom";
import { api } from "../api/client";
import { useAsync } from "../lib/useAsync";
import { WilsonBar } from "../components/WilsonBar";
import { CaveatBanner } from "../components/CaveatBanner";
import { ErrorState, Loading } from "../components/States";
import { fixed, pct } from "../lib/format";

export function AgentDetail() {
  const { agent = "" } = useParams();
  const profile = useAsync((s) => api.domainProfile(agent, s), [agent]);
  const meta = useAsync((s) => api.meta(s), []);

  if (profile.loading) return <Loading label={`Loading ${agent}…`} />;
  if (profile.error) return <ErrorState error={profile.error} onRetry={profile.reload} />;

  const tasks = meta.data?.tasks ?? [];

  return (
    <div>
      <h1 className="page-title">{agent}</h1>
      <p className="page-subtitle">Per-domain pooled capability profile.</p>
      <CaveatBanner caveat={meta.data?.notes?.trust} />

      <div className="panel">
        <h2>Domain profile</h2>
        <table className="data">
          <thead>
            <tr>
              <th>domain</th>
              <th className="num">tasks</th>
              <th className="num">runs</th>
              <th className="num">n_eff (Kish)</th>
              <th className="num">pooled p̂</th>
              <th className="num">stability</th>
              <th>interval</th>
              <th>displayable</th>
            </tr>
          </thead>
          <tbody>
            {profile.data!.domains.map((d) => (
              <tr key={d.domain}>
                <td>{d.domain}</td>
                <td className="num">{d.n_tasks}</td>
                <td className="num">{d.n_runs}</td>
                <td className="num">{fixed(d.n_eff, 1)}</td>
                <td className="num">
                  {d.displayable ? pct(d.pooled_pass_rate, 1) : <span className="dash">--</span>}
                </td>
                <td className="num">{fixed(d.stability, 3)}</td>
                <td>
                  {d.displayable ? (
                    <WilsonBar
                      pHat={d.pooled_pass_rate}
                      low={d.wilson_low}
                      high={d.wilson_high}
                      width={160}
                      showLabel={false}
                    />
                  ) : (
                    <span className="note muted">not displayable</span>
                  )}
                </td>
                <td>
                  <span className={`badge ${d.displayable ? "good" : "warn"}`}>
                    {d.displayable ? "yes" : "no"}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        <p className="note muted">
          A domain is <em>displayable</em> only with ≥5 tasks and ≥25 runs (kernel
          rule). Non-displayable domains still list their underlying coverage so
          the imbalance is visible, but the pass rate is withheld as <code>--</code>.
        </p>
      </div>

      <div className="panel">
        <h2>Cells (agent × task)</h2>
        <p className="note muted">Open any task cell for this agent.</p>
        <div className="task-grid" style={{ maxHeight: "none" }}>
          {tasks.map((t) => (
            <Link
              key={t.task_id}
              className="checkbox-row"
              to={`/cell/${encodeURIComponent(agent)}/${encodeURIComponent(t.task_id)}`}
            >
              {t.task_id}
            </Link>
          ))}
        </div>
      </div>
    </div>
  );
}
