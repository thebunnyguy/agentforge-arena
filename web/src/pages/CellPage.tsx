import { Link, useParams, useSearchParams } from "react-router-dom";
import { ArrowLeft, BarChart3, History } from "lucide-react";
import { api } from "../api/client";
import { useAsync } from "../lib/useAsync";
import { WilsonBar } from "../components/WilsonBar";
import {
  EvidenceClassBadge,
  GateBadge,
  ProvisionalBadge,
  RunOutcomeBadge,
  ScoreBadge,
  StatusBadge,
  VersionStatusBadge,
} from "../components/Badges";
import { CaveatBanner } from "../components/CaveatBanner";
import { EvidenceScopeSelect } from "../components/EvidenceScopeBanner";
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
import { runHref } from "../lib/links";
import { linkQuery, useEvidenceScope } from "../lib/useEvidenceScope";

export function CellPage() {
  const { agent = "", taskId = "" } = useParams();
  const [searchParams] = useSearchParams();
  const version = searchParams.get("version") || null;
  const [scope, setScope] = useEvidenceScope();
  const cell = useAsync(
    (signal) => api.cell(agent, taskId, { version, evidence: scope }, signal),
    [agent, taskId, version, scope],
  );
  if (cell.loading) return <Loading label={`Loading ${agent} × ${taskId}…`} />;
  if (cell.error)
    return <ErrorState error={cell.error} onRetry={cell.reload} />;

  const data = cell.data!;
  const aggregate = data.aggregate;
  const versions = data.versions ?? [];
  // Server enums only: evidence_status is about the SELECTED view, state /
  // has_current_evidence about the CURRENT benchmark. Old payloads without
  // the version fields fall back to "records present => current".
  const viewStatus =
    data.evidence_status ??
    (data.state === "synthetic"
      ? "synthetic"
      : data.runs.length > 0
        ? "current"
        : "none");
  const hasCurrent = data.has_current_evidence ?? data.state === "captured";
  const hasHistorical = data.has_historical_evidence ?? false;
  const historicalVersions = data.historical_versions ?? [];
  const viewingHistorical = viewStatus === "historical";
  const showsRuns = viewStatus === "current" || viewingHistorical;
  const currentRunCount =
    data.current_runs ?? (hasCurrent ? data.runs.length : 0);
  const historicalRunCount = data.historical_runs ?? 0;
  const hasCurrentChip = versions.some((v) => v.status === "current");
  const excludedSynthetic = data.excluded?.synthetic_runs ?? 0;
  const excludedConflict = data.excluded?.provenance_conflict_runs ?? 0;
  const statusBadge =
    viewStatus === "none" && hasHistorical && !hasCurrent
      ? "missing"
      : viewStatus;
  const versionLink = (target: string | null) => {
    const next = new URLSearchParams(searchParams);
    if (target) next.set("version", target);
    else next.delete("version");
    const text = next.toString();
    return `/cell/${encodeURIComponent(agent)}/${encodeURIComponent(taskId)}${text ? `?${text}` : ""}`;
  };
  return (
    <div>
      <PageHeader
        eyebrow="Cell evidence"
        title={`${agent} × ${taskId}`}
        description="Evidence for this agent/task cell. The evidence version, the current task version and the status are labelled separately below."
        actions={
          <Link
            className="btn btn-secondary"
            to={`/agent/${encodeURIComponent(agent)}${linkQuery(scope)}`}
          >
            <ArrowLeft size={15} aria-hidden="true" /> Agent profile
          </Link>
        }
      />
      <CaveatBanner />
      {(scope === "synthetic" || data.state === "synthetic") && (
        <InlineNotice tone="warn">
          <span>
            <strong>Synthetic - not benchmark evidence.</strong>{" "}
            {data.state === "synthetic"
              ? "This is a deterministic reference baseline."
              : "This view shows mock (synthetic) runs only."}
          </span>
        </InlineNotice>
      )}
      <dl className="evidence-facts" aria-label="Evidence status">
        {showsRuns && (
          <div>
            <dt>Evidence version</dt>
            <dd className="mono">{data.selected_version ?? "—"}</dd>
          </div>
        )}
        <div>
          <dt>Current task version</dt>
          <dd className="mono">{data.current_version ?? "—"}</dd>
        </div>
        <div>
          <dt>Status</dt>
          <dd>
            <VersionStatusBadge status={statusBadge} />
          </dd>
        </div>
        <div>
          <dt>Current benchmark evidence</dt>
          <dd>
            <strong>{hasCurrent ? "AVAILABLE" : "NONE"}</strong>
            {hasCurrent ? ` (${currentRunCount} runs)` : ""}
          </dd>
        </div>
        <div>
          <dt>Historical evidence</dt>
          <dd>
            <strong>{hasHistorical ? "AVAILABLE" : "NONE"}</strong>
            {hasHistorical
              ? ` (versions ${historicalVersions.join(", ") || "—"}; ${historicalRunCount} runs)`
              : ""}
          </dd>
        </div>
      </dl>
      {(versions.length > 0 || (hasHistorical && !hasCurrentChip)) && (
        <nav className="version-switch" aria-label="Evidence version">
          <span className="fact-label">View version</span>
          {!hasCurrentChip && data.current_version && (
            <Link
              className="version-chip"
              to={versionLink(null)}
              aria-current={!viewingHistorical ? "true" : undefined}
            >
              {data.current_version} · current · no evidence
            </Link>
          )}
          {versions.map((v) => (
            <Link
              className="version-chip"
              key={v.version}
              to={versionLink(v.status === "current" ? null : v.version)}
              aria-current={
                showsRuns && v.version === data.selected_version
                  ? "true"
                  : undefined
              }
            >
              {v.version} · {v.status === "current" ? "current" : "historical"}{" "}
              · {v.n_runs} runs
            </Link>
          ))}
        </nav>
      )}
      <div className="toolbar scope-toolbar">
        <EvidenceScopeSelect
          scope={scope}
          id="cell-evidence-scope"
          onChange={setScope}
        />
      </div>
      {viewingHistorical && (
        <InlineNotice tone="warn">
          <History size={16} aria-hidden="true" />
          <span>
            <strong>HISTORICAL evidence</strong> - task version{" "}
            <span className="mono">{data.selected_version}</span>. The current
            task version is{" "}
            <span className="mono">{data.current_version ?? "unknown"}</span>
            {hasCurrent
              ? "; current-version runs exist for this model."
              : " and has no runs for this model."}{" "}
            These numbers are not part of the current benchmark and are never
            pooled with it.{" "}
            <Link to={versionLink(null)}>View the current version</Link>.
          </span>
        </InlineNotice>
      )}
      {(excludedSynthetic > 0 || excludedConflict > 0) && (
        <InlineNotice tone="info">
          <span>
            {excludedSynthetic > 0 &&
              `${excludedSynthetic} synthetic (mock) run${excludedSynthetic === 1 ? "" : "s"} in this cell are outside the selected evidence scope. `}
            {excludedConflict > 0 &&
              `${excludedConflict} run${excludedConflict === 1 ? "" : "s"} with conflicting provenance are excluded. `}
            {excludedSynthetic > 0 && scope === "benchmark" && (
              <Link
                to={`?evidence=synthetic${version ? `&version=${encodeURIComponent(version)}` : ""}`}
              >
                View synthetic runs
              </Link>
            )}
          </span>
        </InlineNotice>
      )}

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
              title={
                viewingHistorical
                  ? "What this HISTORICAL evidence supports"
                  : "What this cell supports"
              }
              description={
                viewingHistorical
                  ? "Historical version only: not part of the current benchmark and not comparable to current-version results."
                  : "The interval and sample size qualify the pass-rate conclusion."
              }
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
                : hasHistorical && !hasCurrent
                  ? "MISSING current evidence"
                  : "No aggregate evidence"
            }
          >
            <p>
              {data.synthetic
                ? "This reference row is deterministic and has no real agent runs or patch artifacts."
                : hasHistorical && !hasCurrent
                  ? `This model has no runs at the current task version${data.current_version ? ` (${data.current_version})` : ""}, so it contributes nothing to the current benchmark for this task. Historical evidence is available (versions ${historicalVersions.join(", ") || "—"}); select a historical version above to inspect it.`
                  : "No runs in the selected evidence scope exist for this cell."}
            </p>
          </EmptyState>
        </Panel>
      )}

      {versions.length > 0 && (
        <Panel>
          <SectionHeader
            title="Evidence by task version"
            description="Each version is aggregated independently and never pooled with another."
          />
          <div className="table-scroll" tabIndex={0}>
            <table className="data">
              <thead>
                <tr>
                  <th>version</th>
                  <th>status</th>
                  <th className="num">runs</th>
                  <th className="num">valid n</th>
                  <th className="num">pass rate</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {versions.map((v) => (
                  <tr key={v.version}>
                    <td className="mono">{v.version}</td>
                    <td>
                      <VersionStatusBadge status={v.status} />
                    </td>
                    <td className="num mono">{v.n_runs}</td>
                    <td className="num mono">{v.aggregate?.n_valid ?? "—"}</td>
                    <td className="num mono">
                      {v.aggregate ? pct(v.aggregate.pass_rate, 1) : "—"}
                    </td>
                    <td>
                      <Link
                        className="link-arrow"
                        to={versionLink(
                          v.status === "current" ? null : v.version,
                        )}
                      >
                        <History size={14} aria-hidden="true" /> View
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Panel>
      )}

      <Panel>
        <SectionHeader
          title={`${viewingHistorical ? "Historical runs" : "Individual runs"} · ${data.runs.length}`}
          description="Voided infrastructure failures stay visible and are excluded from valid n; missing artifacts never appear as success."
          action={<LinkArrow to="/runs">Advanced runs explorer</LinkArrow>}
        />
        {data.runs.length === 0 ? (
          <p className="note muted">
            {hasHistorical && !hasCurrent && !viewingHistorical
              ? "No runs at the current task version. Historical runs are listed under the version selector above."
              : "No persisted run rows are available in this cell for the selected evidence scope."}
          </p>
        ) : (
          <div className="table-scroll" tabIndex={0}>
            <table className="data">
              <thead>
                <tr>
                  <th className="num">run</th>
                  <th>version</th>
                  <th>evidence class</th>
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
                  <tr key={run.run_id ?? `${run.task_version}:${run.idx}`}>
                    <td className="num mono">#{run.idx}</td>
                    <td className="mono">{run.task_version ?? "—"}</td>
                    <td>
                      {run.evidence_class ? (
                        <EvidenceClassBadge
                          cls={run.evidence_class}
                          backendKind={run.backend_kind}
                        />
                      ) : (
                        "—"
                      )}
                    </td>
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
                      <LinkArrow to={runHref(run, agent, taskId)}>
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
