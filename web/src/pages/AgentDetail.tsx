import { Link, useParams } from "react-router-dom";
import { ArrowLeft } from "lucide-react";
import { api } from "../api/client";
import { useAsync } from "../lib/useAsync";
import { WilsonBar } from "../components/WilsonBar";
import { CaveatBanner } from "../components/CaveatBanner";
import { ErrorState, Loading } from "../components/States";
import {
  LinkArrow,
  Metric,
  MetricGroup,
  PageHeader,
  Panel,
  SectionHeader,
} from "../components/Primitives";
import { ProvisionalBadge } from "../components/Badges";
import { fixed, pct } from "../lib/format";

export function AgentDetail() {
  const { agent = "" } = useParams();
  const profile = useAsync(
    (signal) => api.domainProfile(agent, signal),
    [agent],
  );
  const meta = useAsync((signal) => api.meta(signal), []);
  const leaderboard = useAsync((signal) => api.leaderboard(null, signal), []);
  const taskKey = meta.data?.tasks.map((task) => task.task_id).join(",") ?? "";
  const cells = useAsync(
    (signal) =>
      meta.data
        ? Promise.all(
            meta.data.tasks.map((task) =>
              api.cell(agent, task.task_id, signal),
            ),
          )
        : Promise.resolve([]),
    [agent, taskKey],
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
  const taskRows = (cells.data ?? []).filter(
    (cell) => cell.aggregate !== null && cell.aggregate.n_valid > 0,
  );
  const orderedTasks = [...taskRows].sort(
    (a, b) => (b.aggregate?.pass_rate ?? 0) - (a.aggregate?.pass_rate ?? 0),
  );
  const topTasks = orderedTasks.slice(0, 3);
  const bottomTasks = [...orderedTasks].reverse().slice(0, 3);

  return (
    <div>
      <PageHeader
        eyebrow="Agent profile"
        title={agent}
        description="What this model appears to handle reliably across the current benchmark—and where the evidence remains mixed."
        actions={
          <Link className="btn btn-secondary" to="/agents">
            <ArrowLeft size={15} aria-hidden="true" /> All agents
          </Link>
        }
      />
      <CaveatBanner caveat={meta.data?.notes?.trust} />

      <MetricGroup>
        <Metric
          label="Rank"
          value={
            entry?.provisional ? <ProvisionalBadge /> : (entry?.rank_low ?? "—")
          }
          detail={
            entry?.rank_high && entry.rank_high !== entry.rank_low
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
              : "No pooled result"
          }
          tone="good"
          mono
        />
        <Metric
          label="Valid runs"
          value={entry?.n ?? "—"}
          detail="pooled evidence"
          mono
        />
        <Metric
          label="Task coverage"
          value={taskRows.length}
          detail={`of ${meta.data!.tasks.length} task cells`}
          mono
        />
      </MetricGroup>

      {entry && (
        <Panel className="panel-accent">
          <SectionHeader
            title="Benchmark position"
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
            provisional row is not evidence of a stable rank.
          </p>
        </Panel>
      )}

      <Panel>
        <SectionHeader
          title="Domain capability"
          description="Only server-marked displayable domain values are shown. Suppression is not a low score."
        />
        <div className="domain-list">
          {profile.data!.domains.map((domain) => (
            <div className="domain-row" key={domain.domain}>
              <div className="domain-name">
                <span>{domain.domain}</span>
                <small>
                  {domain.n_tasks} tasks · {domain.n_runs} runs · n_eff{" "}
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
                  <th className="num">tasks</th>
                  <th className="num">runs</th>
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
          description="Open a cell to inspect repeats, score primitives, and captured evidence."
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
                  <th>version</th>
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
                  const aggregate = cell?.aggregate;
                  return (
                    <tr key={task.task_id}>
                      <td className="primary-cell">
                        <Link
                          to={`/cell/${encodeURIComponent(agent)}/${encodeURIComponent(task.task_id)}`}
                        >
                          {task.task_id}
                        </Link>
                      </td>
                      <td>{task.activity ?? "—"}</td>
                      <td className="mono">{task.current_version ?? "—"}</td>
                      <td className="mono">
                        {aggregate && aggregate.n_valid > 0 ? (
                          <>
                            {pct(aggregate.pass_rate, 1)}{" "}
                            {aggregate.provisional && <ProvisionalBadge />}
                          </>
                        ) : (
                          <span className="badge warn">no valid runs</span>
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
                        <LinkArrow
                          to={`/cell/${encodeURIComponent(agent)}/${encodeURIComponent(task.task_id)}`}
                        >
                          Inspect
                        </LinkArrow>
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
