import { Link, useParams } from "react-router-dom";
import { api } from "../api/client";
import { useAsync } from "../lib/useAsync";
import { WilsonBar } from "../components/WilsonBar";
import {
  CaptureBadge,
  GateBadge,
  PassBadge,
  ProvisionalBadge,
  ScoreBadge,
  StatusBadge,
} from "../components/Badges";
import { CaveatBanner } from "../components/CaveatBanner";
import { ErrorState, Loading } from "../components/States";
import { fixed, pct } from "../lib/format";

export function CellPage() {
  const { agent = "", taskId = "" } = useParams();
  const cell = useAsync((s) => api.cell(agent, taskId, s), [agent, taskId]);

  if (cell.loading) return <Loading label={`${agent} × ${taskId}…`} />;
  if (cell.error) return <ErrorState error={cell.error} onRetry={cell.reload} />;

  const data = cell.data!;
  const { aggregate: a, runs } = data;

  return (
    <div>
      <h1 className="page-title">
        <Link to={`/agent/${encodeURIComponent(agent)}`}>{agent}</Link>
        {" × "}
        <Link to={`/task/${encodeURIComponent(taskId)}`}>{taskId}</Link>{" "}
        <CaptureBadge state={data.state} />
      </h1>
      <p className="page-subtitle">
        Aggregate result for this cell and its runs · current version{" "}
        <code>{data.current_version ?? "—"}</code>
        {data.task_versions.length > 0 && (
          <> · evaluated versions {data.task_versions.join(", ")}</>
        )}
      </p>
      <CaveatBanner />

      {!data.known_task && (
        <div className="caveat">Unknown task id — not part of the loaded task pack.</div>
      )}

      {a === null ? (
        <div className="panel">
          <h2>Aggregate</h2>
          <p className="note muted">
            {data.state === "synthetic"
              ? "Synthetic baseline — no persisted runs to aggregate."
              : "No captured runs for this cell."}
          </p>
        </div>
      ) : (
      <div className="panel">
        <h2>
          Aggregate{" "}
          {a.provisional && <ProvisionalBadge />}{" "}
          {a.deterministic && <span className="badge warn">deterministic</span>}{" "}
          {a.bimodal && <span className="badge warn">bimodal</span>}
        </h2>
        <div style={{ marginBottom: 14 }}>
          <WilsonBar pHat={a.pass_rate} low={a.wilson_low} high={a.wilson_high} width={320} />
        </div>
        <div className="grid-2">
          <Stat label="pass rate (p̂)" value={pct(a.pass_rate, 1)} />
          <Stat label="n_pass / n_valid" value={`${a.n_pass} / ${a.n_valid}`} />
          <Stat label="Wilson interval" value={`[${fixed(a.wilson_low)}, ${fixed(a.wilson_high)}]`} />
          <Stat label="mean S" value={fixed(a.mean_s)} />
          <Stat label="median S" value={fixed(a.median_s)} />
          <Stat label="min / max S" value={`${fixed(a.min_s)} / ${fixed(a.max_s)}`} />
          <Stat label="std S" value={fixed(a.std_s)} />
          <Stat label="stability" value={fixed(a.stability)} />
          <Stat label="conservative continuous" value={fixed(a.conservative_continuous)} />
          <Stat label="reliability" value={fixed(a.reliability)} />
          <Stat label="timeout rate" value={pct(a.timeout_rate, 1)} />
          <Stat label="infra void rate" value={pct(a.infra_void_rate, 1)} />
        </div>
        {Object.keys(a.pass_at_k).length > 0 && (
          <>
            <h3>pass@k</h3>
            <table className="data" style={{ maxWidth: 360 }}>
              <thead>
                <tr>
                  <th className="num">k</th>
                  <th className="num">pass@k</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(a.pass_at_k)
                  .sort((x, y) => Number(x[0]) - Number(y[0]))
                  .map(([k, v]) => (
                    <tr key={k}>
                      <td className="num">{k}</td>
                      <td className="num">{fixed(v)}</td>
                    </tr>
                  ))}
              </tbody>
            </table>
          </>
        )}
        <p className="note muted">
          Every statistic above is computed by the frozen kernel and returned by
          the API. Max S is a cherry-picking hazard shown for diagnostics only.
        </p>
      </div>
      )}

      <div className="panel">
        <h2>Runs ({runs.length})</h2>
        <table className="data">
          <thead>
            <tr>
              <th className="num">idx</th>
              <th>status</th>
              <th className="num">G</th>
              <th className="num">T_hidden</th>
              <th className="num">Q</th>
              <th className="num">S</th>
              <th>X (functional)</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {runs.map((r) => (
              <tr key={r.idx}>
                <td className="num">{r.idx}</td>
                <td>
                  <StatusBadge status={r.status} />
                </td>
                <td className="num">
                  <GateBadge g={r.score.gate_product} />
                </td>
                <td className="num">{fixed(r.score.t_hidden)}</td>
                <td className="num">{fixed(r.score.q)}</td>
                <td className="num">
                  <ScoreBadge score={r.score.final_score} />
                </td>
                <td>
                  <PassBadge pass={r.score.functional_pass} />
                </td>
                <td>
                  <Link
                    to={`/cell/${encodeURIComponent(agent)}/${encodeURIComponent(taskId)}/run/${r.idx}`}
                  >
                    open →
                  </Link>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        <p className="note muted">
          S = G · T_hidden · (0.85 + 0.15·Q). X is true iff G=1 and every hidden
          test passed. Voided infra failures are excluded from n.
        </p>
      </div>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="stat">
      <div className="label">{label}</div>
      <div className="value mono">{value}</div>
    </div>
  );
}
