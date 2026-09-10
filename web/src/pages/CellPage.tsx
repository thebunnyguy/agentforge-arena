import { Link, useParams } from "react-router-dom";
import { ArrowLeft, BarChart3 } from "lucide-react";
import { api } from "../api/client";
import { useAsync } from "../lib/useAsync";
import { WilsonBar } from "../components/WilsonBar";
import {
  GateBadge,
  ProvisionalBadge,
  RunOutcomeBadge,
  ScoreBadge,
  StatusBadge,
} from "../components/Badges";
import { CaveatBanner } from "../components/CaveatBanner";
import { ErrorState, Loading, EmptyState } from "../components/States";
import {
  InlineNotice,
  LinkArrow,
  Metric,
  MetricGroup,
  PageHeader,
  Panel,
  SectionHeader,
} from "../components/Primitives";
import { fixed, pct } from "../lib/format";

export function CellPage() {
  const { agent = "", taskId = "" } = useParams();
  const cell = useAsync(
    (signal) => api.cell(agent, taskId, signal),
    [agent, taskId],
  );
  if (cell.loading) return <Loading label={`Loading ${agent} × ${taskId}…`} />;
  if (cell.error)
    return <ErrorState error={cell.error} onRetry={cell.reload} />;

  const data = cell.data!;
  const aggregate = data.aggregate;
  return (
    <div>
      <PageHeader
        eyebrow="Cell evidence"
        title={`${agent} × ${taskId}`}
        description={`A complete view of this agent/task cell · task version ${data.current_version ?? "—"}.`}
        actions={
          <Link
            className="btn btn-secondary"
            to={`/agent/${encodeURIComponent(agent)}`}
          >
            <ArrowLeft size={15} aria-hidden="true" /> Agent profile
          </Link>
        }
      />
      <CaveatBanner />
      <div className="evidence-strip">
        <div className="evidence-item">
          <span className="evidence-label">Cell records</span>
          <span className="evidence-value">
            <span
              className={`badge ${data.state === "synthetic" ? "synthetic" : data.runs.length ? "neutral" : "warn"}`}
            >
              {data.state === "synthetic"
                ? "synthetic reference"
                : data.runs.length
                  ? "records present"
                  : "no records"}
            </span>
          </span>
        </div>
        <div className="evidence-item">
          <span className="evidence-label">Task versions</span>
          <span className="evidence-value">
            {data.task_versions.join(", ") || "—"}
          </span>
        </div>
        <div className="evidence-item">
          <span className="evidence-label">Runs</span>
          <span className="evidence-value">{data.runs.length}</span>
        </div>
      </div>

      {aggregate ? (
        <>
          <MetricGroup>
            <Metric
              label="Pass rate"
              value={pct(aggregate.pass_rate, 1)}
              detail={`Wilson ${pct(aggregate.wilson_low, 0)}–${pct(aggregate.wilson_high, 0)}`}
              tone="accent"
              mono
            />
            <Metric
              label="Valid evidence"
              value={`${aggregate.n_pass}/${aggregate.n_valid}`}
              detail="functional passes / valid runs"
              mono
            />
            <Metric
              label="Stability"
              value={fixed(aggregate.stability)}
              detail="server-returned diagnostic"
              mono
            />
            <Metric
              label="Reliability"
              value={fixed(aggregate.reliability)}
              detail={`timeout ${pct(aggregate.timeout_rate, 0)}`}
              mono
            />
            <Metric
              label="Infra void rate"
              value={pct(aggregate.infra_void_rate, 1)}
              detail="voided attempts / all attempts"
              tone="void"
              mono
            />
          </MetricGroup>
          <Panel className="panel-accent">
            <SectionHeader
              title="What this cell supports"
              description="The interval and sample size qualify the pass-rate conclusion."
            />
            <WilsonBar
              pHat={aggregate.pass_rate}
              low={aggregate.wilson_low}
              high={aggregate.wilson_high}
              width={500}
            />
            <div className="grid-auto stat-grid">
              <Metric label="Mean S" value={fixed(aggregate.mean_s)} mono />
              <Metric label="Median S" value={fixed(aggregate.median_s)} mono />
              <Metric
                label="Min S"
                value={fixed(aggregate.min_s)}
                detail="worst observed run"
                mono
              />
              <Metric
                label="Max S"
                value={fixed(aggregate.max_s)}
                detail="diagnostic only · cherry-pick hazard"
                mono
              />
              <Metric label="Std S" value={fixed(aggregate.std_s)} mono />
              <Metric
                label="Continuous lower bound"
                value={fixed(aggregate.conservative_continuous)}
                mono
              />
              <Metric
                label="Timeout rate"
                value={pct(aggregate.timeout_rate, 1)}
                mono
              />
              <Metric
                label="Infra void rate"
                value={pct(aggregate.infra_void_rate, 1)}
                tone="void"
                mono
              />
              <Metric
                label="Reliability"
                value={fixed(aggregate.reliability)}
                mono
              />
            </div>
            <div className="badge-row">
              {aggregate.provisional && <ProvisionalBadge />}
              {aggregate.deterministic && (
                <span className="badge warn">deterministic · variance 0</span>
              )}
              {aggregate.bimodal && (
                <span className="badge warn">bimodal · mean needs context</span>
              )}
            </div>
            <p className="note muted">
              Provisional cells have fewer than five valid runs. Deterministic
              cells show zero observed variance; bimodal cells make a mean less
              representative. pass@k is an in-sample retry diagnostic.
            </p>
            <details className="supporting-details" open>
              <summary>Complete aggregate fields</summary>
              <div className="table-scroll" tabIndex={0}>
                <table className="data">
                  <thead>
                    <tr>
                      <th>field</th>
                      <th className="num">server value</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr>
                      <td>n_valid</td>
                      <td className="num mono">{aggregate.n_valid}</td>
                    </tr>
                    <tr>
                      <td>n_pass</td>
                      <td className="num mono">{aggregate.n_pass}</td>
                    </tr>
                    <tr>
                      <td>pass_rate</td>
                      <td className="num mono">{fixed(aggregate.pass_rate)}</td>
                    </tr>
                    <tr>
                      <td>wilson_low</td>
                      <td className="num mono">
                        {fixed(aggregate.wilson_low)}
                      </td>
                    </tr>
                    <tr>
                      <td>wilson_high</td>
                      <td className="num mono">
                        {fixed(aggregate.wilson_high)}
                      </td>
                    </tr>
                    <tr>
                      <td>mean_s</td>
                      <td className="num mono">{fixed(aggregate.mean_s)}</td>
                    </tr>
                    <tr>
                      <td>median_s</td>
                      <td className="num mono">{fixed(aggregate.median_s)}</td>
                    </tr>
                    <tr>
                      <td>min_s</td>
                      <td className="num mono">{fixed(aggregate.min_s)}</td>
                    </tr>
                    <tr>
                      <td>max_s</td>
                      <td className="num mono">{fixed(aggregate.max_s)}</td>
                    </tr>
                    <tr>
                      <td>std_s</td>
                      <td className="num mono">{fixed(aggregate.std_s)}</td>
                    </tr>
                    <tr>
                      <td>stability</td>
                      <td className="num mono">{fixed(aggregate.stability)}</td>
                    </tr>
                    <tr>
                      <td>conservative_continuous</td>
                      <td className="num mono">
                        {fixed(aggregate.conservative_continuous)}
                      </td>
                    </tr>
                    <tr>
                      <td>timeout_rate</td>
                      <td className="num mono">
                        {pct(aggregate.timeout_rate, 1)}
                      </td>
                    </tr>
                    <tr>
                      <td>infra_void_rate</td>
                      <td className="num mono">
                        {pct(aggregate.infra_void_rate, 1)}
                      </td>
                    </tr>
                    <tr>
                      <td>reliability</td>
                      <td className="num mono">
                        {fixed(aggregate.reliability)}
                      </td>
                    </tr>
                    <tr>
                      <td>pass_at_k</td>
                      <td className="num mono">
                        {Object.entries(aggregate.pass_at_k)
                          .map(([k, value]) => `@${k} ${fixed(value)}`)
                          .join(" · ") || "—"}
                      </td>
                    </tr>
                    <tr>
                      <td>deterministic</td>
                      <td className="num mono">
                        {String(aggregate.deterministic)}
                      </td>
                    </tr>
                    <tr>
                      <td>bimodal</td>
                      <td className="num mono">{String(aggregate.bimodal)}</td>
                    </tr>
                    <tr>
                      <td>provisional</td>
                      <td className="num mono">
                        {String(aggregate.provisional)}
                      </td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </details>
            {Object.keys(aggregate.pass_at_k).length > 0 && (
              <div className="pass-k">
                <h3>pass@k · in-sample diagnostic</h3>
                {Object.entries(aggregate.pass_at_k)
                  .sort(([a], [b]) => Number(a) - Number(b))
                  .map(([k, value]) => (
                    <div className="pass-k-row" key={k}>
                      <span>k = {k}</span>
                      <div className="domain-track">
                        <div
                          className="domain-fill"
                          style={{ width: `${value * 100}%` }}
                        />
                      </div>
                      <span className="mono">{pct(value, 1)}</span>
                    </div>
                  ))}
              </div>
            )}
          </Panel>
        </>
      ) : (
        <Panel>
          <EmptyState
            title={
              data.synthetic
                ? "Synthetic baseline cell"
                : "No aggregate evidence"
            }
          >
            <p>
              {data.synthetic
                ? "This reference row is deterministic and has no real agent runs or patch artifacts."
                : "The API returned no captured runs for this cell."}
            </p>
          </EmptyState>
        </Panel>
      )}

      <Panel>
        <SectionHeader
          title={`Individual runs · ${data.runs.length}`}
          description="Voided infrastructure failures stay visible and are excluded from valid n; missing artifacts never appear as success."
          action={<LinkArrow to="/runs">Advanced runs explorer</LinkArrow>}
        />
        {data.runs.length === 0 ? (
          <p className="note muted">
            No real persisted run rows are available in this cell.
          </p>
        ) : (
          <div className="table-scroll" tabIndex={0}>
            <table className="data">
              <thead>
                <tr>
                  <th className="num">run</th>
                  <th>status</th>
                  <th className="num">G</th>
                  <th className="num">T_hidden</th>
                  <th className="num">Q</th>
                  <th className="num">S</th>
                  <th>X</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {data.runs.map((run) => (
                  <tr key={run.idx}>
                    <td className="num mono">#{run.idx}</td>
                    <td>
                      <StatusBadge status={run.status} />
                    </td>
                    <td className="num">
                      <GateBadge g={run.score.gate_product} />
                    </td>
                    <td className="num mono">{fixed(run.score.t_hidden)}</td>
                    <td className="num mono">{fixed(run.score.q)}</td>
                    <td className="num">
                      <ScoreBadge score={run.score.final_score} />
                    </td>
                    <td>
                      <RunOutcomeBadge
                        status={run.status}
                        functionalPass={run.score.functional_pass}
                      />
                    </td>
                    <td>
                      <LinkArrow
                        to={`/cell/${encodeURIComponent(agent)}/${encodeURIComponent(taskId)}/run/${run.idx}`}
                      >
                        Forensics
                      </LinkArrow>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <InlineNotice tone="info">
          <BarChart3 size={16} aria-hidden="true" />
          <span>
            All values above are returned by the frozen kernel. Max S and pass@k
            are diagnostics, not ranking inputs; small samples and bimodal
            results require context.
          </span>
        </InlineNotice>
      </Panel>
    </div>
  );
}
