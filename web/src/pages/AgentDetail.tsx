import { Link, useParams } from "react-router-dom";
import { ArrowLeft } from "lucide-react";
import { api } from "../api/client";
import { useAsync } from "../lib/useAsync";
import { WilsonBar } from "../components/WilsonBar";
import { CaveatBanner } from "../components/CaveatBanner";
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
import {
  MissingCurrentEvidence,
  ProvisionalBadge,
  VersionStatusBadge,
} from "../components/Badges";
import { EvidenceScopeBanner } from "../components/EvidenceScopeBanner";
import { fixed, pct } from "../lib/format";
import { linkQuery, useEvidenceScope } from "../lib/useEvidenceScope";

export function AgentDetail() {
  const { agent = "" } = useParams();
  const [scope, setScope] = useEvidenceScope();
  const profile = useAsync(
    (signal) => api.domainProfile(agent, { evidence: scope }, signal),
    [agent, scope],
  );
  const meta = useAsync(
    (signal) => api.meta({ evidence: scope }, signal),
    [scope],
  );
  const leaderboard = useAsync(
    (signal) => api.leaderboard(null, { evidence: scope }, signal),
    [scope],
  );
  const taskKey = meta.data?.tasks.map((task) => task.task_id).join(",") ?? "";
  const cells = useAsync(
    (signal) =>
      meta.data
        ? Promise.all(
            meta.data.tasks.map((task) =>
              api.cell(agent, task.task_id, { evidence: scope }, signal),
            ),
          )
        : Promise.resolve([]),
    [agent, taskKey, scope],
  );

  if (profile.loading || meta.loading || leaderboard.loading)
    return <Loading label={`Loading ${agent}…`} />;
  if (profile.error)
    return <ErrorState error={profile.error} onRetry={profile.reload} />;
  if (meta.error)
    return <ErrorState error={meta.error} onRetry={meta.reload} />;
  if (leaderboard.error)
    return (
      <ErrorState error={leaderboard.error} onRetry={leaderboard.reload} />
    );

  const entry = leaderboard.data!.entries.find(
    (candidate) => candidate.agent === agent,
  );
  // Only current-benchmark cells count as evidence; a historical view or a
  // null aggregate never does.
  const taskRows = (cells.data ?? []).filter(
    (cell) =>
      cell.aggregate !== null &&
      cell.aggregate.n_valid > 0 &&
      cell.evidence_status !== "historical",
  );
  const orderedTasks = [...taskRows].sort(
    (a, b) => (b.aggregate?.pass_rate ?? 0) - (a.aggregate?.pass_rate ?? 0),
  );
  const topTasks = orderedTasks.slice(0, 3);
  const bottomTasks = [...orderedTasks].reverse().slice(0, 3);
  // Coverage comes from the server (profile.coverage / meta.evidence_counts).
  const counts = meta.data!.evidence_counts?.[agent];
  const profileCoverage = profile.data!.coverage;
  const coverageNow =
    profileCoverage?.current_tasks ??
    counts?.current_tasks ??
    entry?.coverage?.tasks_with_current_evidence ??
    null;
  const coverageTotal =
    profileCoverage?.tasks_total ??
    counts?.tasks_total ??
    meta.data!.n_tasks ??
    meta.data!.tasks.length;
  const historicalRuns = counts?.historical_runs ?? 0;
  const historicalOnlyTasks =
    profileCoverage?.historical_only_tasks ??
    counts?.historical_only_tasks ??
    0;
  const noCurrentEvidence = !entry;
  const hasHistorical = historicalRuns > 0 || historicalOnlyTasks > 0;

  return (
    <div>
      <PageHeader
        eyebrow="Agent profile"
        title={agent}
        description="What this model appears to handle reliably on the current benchmark (each task's current version)—and where the evidence remains mixed."
        actions={
          <Link className="btn btn-secondary" to="/agents">
            <ArrowLeft size={15} aria-hidden="true" /> All agents
          </Link>
        }
      />
      <CaveatBanner caveat={meta.data?.notes?.trust} />
      <EvidenceScopeBanner
        scope={scope}
        onScopeChange={setScope}
        coverage={
          coverageNow === null
            ? null
            : { withCurrent: coverageNow, total: coverageTotal }
        }
      />
      {noCurrentEvidence && (
        <InlineNotice tone="warn">
          <span>
            <strong>Current benchmark evidence: NONE.</strong>{" "}
            {hasHistorical ? (
              <>
                <strong>Historical evidence: AVAILABLE</strong> (
                {historicalRuns} runs on {historicalOnlyTasks} tasks at older
                task versions). This model is not ranked and must not be read as
                having completed the current benchmark. Open a task cell below
                and pick a historical version to inspect it.
              </>
            ) : (
              "No evidence exists for this model in the selected scope."
            )}
          </span>
        </InlineNotice>
      )}

      <MetricGroup>
        <Metric
          label="Rank"
          value={
            noCurrentEvidence ? (
              "—"
            ) : entry?.provisional ? (
              <ProvisionalBadge />
            ) : (
              (entry?.rank_low ?? "—")
            )
          }
          detail={
            noCurrentEvidence
              ? "not ranked · no current evidence"
              : entry?.rank_high && entry.rank_high !== entry.rank_low
                ? `range to ${entry.rank_high}`
                : "kernel position"
          }
          tone="accent"
          mono
        />
        <Metric
          label="Pass rate"
          value={entry ? pct(entry.pass_rate, 1) : "—"}
          detail={
            entry
              ? `Wilson ${pct(entry.wilson_low, 0)}–${pct(entry.wilson_high, 0)}`
              : "No current pooled result"
          }
          tone="good"
          mono
        />
        <Metric
          label="Valid runs"
          value={entry?.n ?? "—"}
          detail="current-version evidence"
          mono
        />
        <Metric
          label="Current coverage"
          value={coverageNow === null ? "—" : `${coverageNow}/${coverageTotal}`}
          detail="tasks with current evidence"
          mono
        />
      </MetricGroup>

      {hasHistorical && !noCurrentEvidence && (
        <p className="note muted">
          Historical evidence: AVAILABLE ({historicalRuns} runs on{" "}
          {historicalOnlyTasks} tasks whose evidence is at an older task
          version). It is kept as history and is not part of the figures above.
        </p>
      )}

      {entry && (
        <Panel className="panel-accent">
          <SectionHeader
            title="Current benchmark position"
            description="The observed point sits inside its Wilson interval; the range is part of the result."
          />
          <WilsonBar
            pHat={entry.pass_rate}
            low={entry.wilson_low}
            high={entry.wilson_high}
            width={520}
          />
          <p className="note muted">
            The leaderboard preserves the kernel’s lower-bound ordering. A
            provisional row is not evidence of a stable rank
            {entry.coverage && !entry.coverage.complete
              ? `, and coverage is partial (${entry.coverage.tasks_with_current_evidence}/${entry.coverage.tasks_total} tasks with current evidence), so this is not a full-benchmark rank`
              : ""}
            .
          </p>
        </Panel>
      )}

      <Panel>
        <SectionHeader
          title="Domain capability (current benchmark)"
          description="Only server-marked displayable domain values are shown. Suppression is not a low score."
        />
        {noCurrentEvidence ? (
          <MissingCurrentEvidence historicalAvailable={hasHistorical} />
        ) : coverageNow !== null && coverageNow < coverageTotal ? (
          <p className="note muted">
            Domains need at least 5 tasks and 25 runs of current evidence. With{" "}
            {coverageNow}/{coverageTotal} tasks covered, many domains stay
            suppressed; that reflects coverage, not a low score.
          </p>
        ) : null}
        <div className="domain-list">
          {profile.data!.domains.map((domain) => (
            <div className="domain-row" key={domain.domain}>
              <div className="domain-name">
                <span>{domain.domain}</span>
                <small>
                  {domain.n_tasks} current tasks · {domain.n_runs} runs · n_eff{" "}
                  {domain.displayable ? fixed(domain.n_eff, 1) : "—"}
                </small>
              </div>
              {domain.displayable ? (
                <>
                  <div className="domain-track">
                    <div
                      className="domain-fill"
                      style={{ width: `${domain.pooled_pass_rate * 100}%` }}
                    />
                  </div>
                  <span className="domain-value mono">
                    {pct(domain.pooled_pass_rate, 0)}
                  </span>
                  <WilsonBar
                    pHat={domain.pooled_pass_rate}
                    low={domain.wilson_low}
                    high={domain.wilson_high}
                    width={150}
                    compact
                    showLabel={false}
                  />
                </>
              ) : (
                <span className="badge warn">not displayable</span>
              )}
            </div>
          ))}
        </div>
        <details className="supporting-details">
          <summary>Coverage and stability details</summary>
          <div className="table-scroll" tabIndex={0}>
            <table className="data">
              <thead>
                <tr>
                  <th>domain</th>
                  <th className="num">current tasks</th>
                  <th className="num">current runs</th>
                  <th className="num">n_eff</th>
                  <th className="num">stability</th>
                  <th>display</th>
                </tr>
              </thead>
              <tbody>
                {profile.data!.domains.map((domain) => (
                  <tr key={domain.domain}>
                    <td>{domain.domain}</td>
                    <td className="num mono">{domain.n_tasks}</td>
                    <td className="num mono">{domain.n_runs}</td>
                    <td className="num mono">{fixed(domain.n_eff, 1)}</td>
                    <td className="num mono">
                      {domain.displayable ? fixed(domain.stability) : "—"}
                    </td>
                    <td>
                      {domain.displayable ? (
                        <span className="badge good">displayable</span>
                      ) : (
                        <span className="badge warn">suppressed</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </details>
      </Panel>

      <div className="split-layout">
        <Panel>
          <SectionHeader
            title="Highest observed task results"
            description="Ordered by observed cell pass rate; provisional labels stay visible beside each result."
          />
          <TaskPerformance rows={topTasks} agent={agent} />
        </Panel>
        <Panel>
          <SectionHeader
            title="Where to investigate"
            description="Lower observed pass-rate cells with valid evidence are starting points for review."
          />
          <TaskPerformance rows={bottomTasks} agent={agent} />
        </Panel>
      </div>

      <Panel>
        <SectionHeader
          title="All task cells"
          description="Status is the server's read of each cell against the task's current version. Open a cell to inspect repeats, score primitives, captured evidence and any historical versions."
        />
        {cells.loading ? (
          <Loading label="Loading task cells…" />
        ) : cells.error ? (
          <ErrorState error={cells.error} onRetry={cells.reload} />
        ) : (
          <div className="table-scroll" tabIndex={0}>
            <table className="data">
              <thead>
                <tr>
                  <th>task</th>
                  <th>activity</th>
                  <th>current version</th>
                  <th>status</th>
                  <th>pass rate</th>
                  <th>valid n</th>
                  <th>interval</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {meta.data!.tasks.map((task) => {
                  const cell = cells.data?.find(
                    (candidate) => candidate.task_id === task.task_id,
                  );
                  const aggregate =
                    cell?.evidence_status === "historical"
                      ? null
                      : cell?.aggregate;
                  // cell.state is about CURRENT evidence (server enum).
                  const state = cell?.state;
                  const historicalOnly = state === "historical_only";
                  const cellPath = `/cell/${encodeURIComponent(agent)}/${encodeURIComponent(task.task_id)}`;
                  const firstHistorical = cell?.historical_versions?.[0];
                  return (
                    <tr
                      key={task.task_id}
                      className={historicalOnly ? "row-missing" : undefined}
                    >
                      <td className="primary-cell">
                        <Link to={`${cellPath}${linkQuery(scope)}`}>
                          {task.task_id}
                        </Link>
                      </td>
                      <td>{task.activity ?? "—"}</td>
                      <td className="mono">{task.current_version ?? "—"}</td>
                      <td>
                        <VersionStatusBadge
                          status={
                            state === "captured"
                              ? "current"
                              : state === "historical_only"
                                ? "missing"
                                : state === "synthetic"
                                  ? "synthetic"
                                  : "none"
                          }
                        />
                      </td>
                      <td className="mono">
                        {aggregate && aggregate.n_valid > 0 ? (
                          <>
                            {pct(aggregate.pass_rate, 1)}{" "}
                            {aggregate.provisional && <ProvisionalBadge />}
                          </>
                        ) : historicalOnly ? (
                          <MissingCurrentEvidence />
                        ) : state === "captured" ? (
                          <span className="badge warn">no valid runs</span>
                        ) : (
                          <span className="badge neutral">
                            no current evidence
                          </span>
                        )}
                      </td>
                      <td className="mono">{aggregate?.n_valid ?? "—"}</td>
                      <td>
                        {aggregate && aggregate.n_valid > 0 ? (
                          <WilsonBar
                            pHat={aggregate.pass_rate}
                            low={aggregate.wilson_low}
                            high={aggregate.wilson_high}
                            width={160}
                            compact
                          />
                        ) : (
                          "—"
                        )}
                      </td>
                      <td>
                        <LinkArrow to={`${cellPath}${linkQuery(scope)}`}>
                          Inspect
                        </LinkArrow>
                        {historicalOnly && firstHistorical && (
                          <Link
                            className="link-arrow"
                            to={`${cellPath}${linkQuery(scope, firstHistorical)}`}
                          >
                            Historical {firstHistorical}
                          </Link>
                        )}
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

function TaskPerformance({
  rows,
  agent,
}: {
  rows: Array<{
    task_id: string;
    aggregate: {
      pass_rate: number;
      wilson_low: number;
      wilson_high: number;
      n_valid: number;
      provisional: boolean;
    } | null;
  }>;
  agent: string;
}) {
  if (rows.length === 0)
    return <p className="note muted">No aggregate task evidence available.</p>;
  return (
    <div className="mini-list">
      {rows.map(
        (row) =>
          row.aggregate && (
            <div className="mini-list-row" key={row.task_id}>
              <div>
                <Link
                  className="mono"
                  to={`/cell/${encodeURIComponent(agent)}/${encodeURIComponent(row.task_id)}`}
                >
                  {row.task_id}
                </Link>
                <span className="sub-cell">
                  {row.aggregate.provisional && "provisional · "}
                  {row.aggregate.n_valid} valid runs
                </span>
              </div>
              <div className="mini-list-value">
                <strong>{pct(row.aggregate.pass_rate, 0)}</strong>
                <WilsonBar
                  pHat={row.aggregate.pass_rate}
                  low={row.aggregate.wilson_low}
                  high={row.aggregate.wilson_high}
                  width={150}
                  compact
                  showLabel={false}
                />
              </div>
            </div>
          ),
      )}
    </div>
  );
}
