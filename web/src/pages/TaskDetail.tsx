import { ArrowLeft, History, Info } from "lucide-react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { api } from "../api/client";
import { useAsync } from "../lib/useAsync";
import { WilsonBar } from "../components/WilsonBar";
import {
  MissingCurrentEvidence,
  ProvisionalBadge,
  VersionStatusBadge,
} from "../components/Badges";
import { CaveatBanner } from "../components/CaveatBanner";
import { EvidenceScopeBanner } from "../components/EvidenceScopeBanner";
import { ErrorState, Loading } from "../components/States";
import {
  InlineNotice,
  LinkArrow,
  Metric,
  MetricGroup,
  PageHeader,
  Panel,
  SectionHeader,
} from "../components/Primitives";
import { pct, rankLabel } from "../lib/format";
import { linkQuery, useEvidenceScope } from "../lib/useEvidenceScope";

export function TaskDetail() {
  const { taskId = "" } = useParams();
  const [searchParams, setSearchParams] = useSearchParams();
  const version = searchParams.get("version") || null;
  const [scope, setScope] = useEvidenceScope();
  const leaderboard = useAsync(
    (signal) => api.leaderboard(taskId, { evidence: scope, version }, signal),
    [taskId, version, scope],
  );
  const meta = useAsync(
    (signal) => api.meta({ evidence: scope }, signal),
    [scope],
  );
  if (leaderboard.loading || meta.loading)
    return <Loading label={`Loading ${taskId}…`} />;
  if (leaderboard.error)
    return (
      <ErrorState error={leaderboard.error} onRetry={leaderboard.reload} />
    );
  if (meta.error)
    return <ErrorState error={meta.error} onRetry={meta.reload} />;

  const task = meta.data!.tasks.find(
    (candidate) => candidate.task_id === taskId,
  );
  const lb = leaderboard.data!;
  const viewingHistorical = lb.evidence_status === "historical";
  const historicalVersions = task?.historical_versions ?? [];
  const totalModels =
    meta.data!.current_benchmark?.models_total ?? meta.data!.models.length;
  const modelsWithCurrent = task?.models_with_current_evidence;
  const hasCurrent = task?.has_current_evidence;

  // Ranked = entries with valid runs at the selected version. Everything else
  // in the roster is a MISSING row (a left join over meta.models), never a
  // zero score.
  const ranked = lb.entries.filter((entry) => entry.n > 0);
  const historicalSet = new Set(lb.historical_only_agents ?? []);
  const rankedNames = new Set(ranked.map((entry) => entry.agent));
  const missing = [
    ...new Set([
      ...meta.data!.models,
      ...lb.entries.map((entry) => entry.agent),
      ...historicalSet,
    ]),
  ]
    .filter((agent) => !rankedNames.has(agent))
    .filter((agent) => !meta.data!.synthetic_agents.includes(agent))
    .sort();

  function setVersion(next: string | null) {
    const params = new URLSearchParams(searchParams);
    if (next) params.set("version", next);
    else params.delete("version");
    setSearchParams(params);
  }

  return (
    <div>
      <PageHeader
        eyebrow="Task detail"
        title={taskId}
        description="Which agents solve this task reliably? Compare the server-ranked outcomes at one task version, then drill into the cell evidence."
        actions={
          <Link className="btn btn-secondary" to="/tasks">
            <ArrowLeft size={15} aria-hidden="true" /> All tasks
          </Link>
        }
      />
      <CaveatBanner caveat={meta.data?.notes?.trust} />
      <EvidenceScopeBanner scope={scope} onScopeChange={setScope} />
      <MetricGroup>
        <Metric
          label="Current task version"
          value={task?.current_version ?? "—"}
          detail="task contract"
          mono
        />
        <Metric
          label="Models with current evidence"
          value={
            modelsWithCurrent === undefined
              ? "—"
              : `${modelsWithCurrent}/${totalModels}`
          }
          detail="server count, current version only"
          mono
        />
        <Metric
          label="Historical runs"
          value={task?.historical_runs ?? "—"}
          detail={
            historicalVersions.length
              ? `versions ${historicalVersions.join(", ")}`
              : "no older versions"
          }
          mono
        />
        <Metric
          label="Difficulty"
          value={task?.difficulty ?? "—"}
          detail="task metadata"
          mono
        />
      </MetricGroup>
      <Panel>
        <SectionHeader
          title="Task metadata"
          description="Task contract fields are shown as recorded, including version and domain weights."
        />
        <dl className="kv">
          <dt>task ID</dt>
          <dd>{taskId}</dd>
          <dt>current task version</dt>
          <dd>{task?.current_version ?? "—"}</dd>
          <dt>evidence at current version</dt>
          <dd>
            {task?.current_runs === undefined
              ? "—"
              : task.current_runs > 0
                ? `${task.current_runs} runs`
                : "none - no model has evidence at the current version"}
          </dd>
          <dt>historical versions</dt>
          <dd>
            {historicalVersions.length ? (
              <span className="badge-row">
                {historicalVersions.map((v) => (
                  <Link
                    className="version-chip"
                    key={v}
                    to={`?version=${encodeURIComponent(v)}${scope === "benchmark" ? "" : `&evidence=${scope}`}`}
                  >
                    {v} · historical
                  </Link>
                ))}
              </span>
            ) : (
              "none"
            )}
          </dd>
          <dt>activity</dt>
          <dd>{task?.activity ?? "—"}</dd>
          <dt>scale</dt>
          <dd>{task?.scale ?? "—"}</dd>
          <dt>domains</dt>
          <dd>
            {task?.domains
              .map((tag) => `${tag.domain} (${tag.weight})`)
              .join(", ") || "—"}
          </dd>
          <dt>versions stored</dt>
          <dd>{task?.evaluated_versions.join(", ") || "—"}</dd>
        </dl>
      </Panel>
      {meta.data!.synthetic_agents.length > 0 && (
        <Panel>
          <SectionHeader
            title="Synthetic references"
            description="API-returned oracle/noop reference rows are deterministic bookends, not competing agents."
          />
          <div className="reference-links">
            {meta.data!.synthetic_agents.map((reference) => (
              <div className="reference-link" key={reference}>
                <span>{reference}</span>
                <span>
                  <Link
                    to={`/cell/${encodeURIComponent(reference)}/${encodeURIComponent(taskId)}`}
                  >
                    cell
                  </Link>{" "}
                  ·{" "}
                  <Link
                    to={`/cell/${encodeURIComponent(reference)}/${encodeURIComponent(taskId)}/run/0`}
                  >
                    run #0
                  </Link>
                </span>
              </div>
            ))}
          </div>
        </Panel>
      )}
      <Panel>
        <SectionHeader
          title={
            viewingHistorical
              ? `HISTORICAL agent performance · version ${lb.version}`
              : "Agent performance (current version)"
          }
          description={
            viewingHistorical
              ? "Historical version only. Not part of the current benchmark; no ranks are claimed."
              : "Rows follow the kernel-scoped leaderboard for the current task version. Models without current evidence are listed as missing, not scored."
          }
          action={
            historicalVersions.length > 0 || version ? (
              <div className="scope-select">
                <label htmlFor="task-version">
                  <History size={14} aria-hidden="true" /> Task version
                </label>
                <select
                  id="task-version"
                  value={version ?? ""}
                  onChange={(event) => setVersion(event.target.value || null)}
                >
                  <option value="">
                    Current
                    {task?.current_version ? ` (${task.current_version})` : ""}
                  </option>
                  {historicalVersions.map((v) => (
                    <option key={v} value={v}>
                      Historical {v}
                    </option>
                  ))}
                </select>
              </div>
            ) : undefined
          }
        />
        {viewingHistorical && (
          <InlineNotice tone="warn">
            <History size={16} aria-hidden="true" />
            <span>
              <strong>HISTORICAL</strong> - viewing task version{" "}
              <span className="mono">{lb.version}</span>; the current version is{" "}
              <span className="mono">
                {lb.current_version ?? task?.current_version ?? "unknown"}
              </span>
              .{" "}
              <Link to={`?${scope === "benchmark" ? "" : `evidence=${scope}`}`}>
                Back to current
              </Link>
            </span>
          </InlineNotice>
        )}
        {!viewingHistorical && hasCurrent === false && (
          <InlineNotice tone="warn">
            <span>
              <strong>Current benchmark evidence: NONE</strong> for this task.
              Every model below is missing current evidence
              {historicalVersions.length
                ? `; historical evidence is available (versions ${historicalVersions.join(", ")})`
                : ""}
              .
            </span>
          </InlineNotice>
        )}
        <div className="table-scroll" tabIndex={0}>
          <table className="data">
            <thead>
              <tr>
                {!viewingHistorical && <th className="num">rank</th>}
                <th>agent</th>
                <th>status</th>
                <th>pass rate</th>
                <th>valid n</th>
                <th>Wilson interval</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {ranked.map((entry) => (
                <tr key={entry.agent}>
                  {!viewingHistorical && (
                    <td className="num">
                      {entry.provisional ? (
                        <ProvisionalBadge />
                      ) : (
                        rankLabel(
                          entry.provisional,
                          entry.rank_low,
                          entry.rank_high,
                        )
                      )}
                    </td>
                  )}
                  <td className="primary-cell">
                    <Link
                      to={`/agent/${encodeURIComponent(entry.agent)}${linkQuery(scope)}`}
                    >
                      {entry.agent}
                    </Link>
                  </td>
                  <td>
                    <VersionStatusBadge
                      status={viewingHistorical ? "historical" : "current"}
                    />
                  </td>
                  <td className="mono">{pct(entry.pass_rate, 1)}</td>
                  <td className="mono">{entry.n}</td>
                  <td>
                    <WilsonBar
                      pHat={entry.pass_rate}
                      low={entry.wilson_low}
                      high={entry.wilson_high}
                    />
                  </td>
                  <td>
                    <LinkArrow
                      to={`/cell/${encodeURIComponent(entry.agent)}/${encodeURIComponent(taskId)}${linkQuery(scope, version)}`}
                    >
                      Open cell
                    </LinkArrow>
                  </td>
                </tr>
              ))}
              {missing.map((agent) => {
                const hasHistory = historicalSet.has(agent);
                return (
                  <tr className="row-missing" key={`missing-${agent}`}>
                    {!viewingHistorical && (
                      <td className="num">
                        <span className="dash">—</span>
                      </td>
                    )}
                    <td className="primary-cell">
                      <Link
                        to={`/agent/${encodeURIComponent(agent)}${linkQuery(scope)}`}
                      >
                        {agent}
                      </Link>
                    </td>
                    <td colSpan={4}>
                      {viewingHistorical ? (
                        <span>
                          <span className="badge neutral">NO EVIDENCE</span>
                          <span className="missing-note">
                            No runs at historical version {lb.version}
                          </span>
                        </span>
                      ) : (
                        <MissingCurrentEvidence
                          historicalAvailable={hasHistory}
                        />
                      )}
                    </td>
                    <td>
                      <LinkArrow
                        to={`/cell/${encodeURIComponent(agent)}/${encodeURIComponent(taskId)}${linkQuery(scope, version)}`}
                      >
                        Open cell
                      </LinkArrow>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        <div className="inline-notice notice-info">
          <Info size={16} aria-hidden="true" />
          <span>
            Open a cell to see individual repeats, voided runs, score
            primitives, capture state, forensic artifacts and each stored task
            version.
          </span>
        </div>
      </Panel>
    </div>
  );
}
