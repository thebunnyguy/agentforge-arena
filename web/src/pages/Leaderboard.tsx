import { Filter, Info } from "lucide-react";
import { Link, useSearchParams } from "react-router-dom";
import { api } from "../api/client";
import { useAsync } from "../lib/useAsync";
import { WilsonBar } from "../components/WilsonBar";
import { ProvisionalBadge } from "../components/Badges";
import { CaveatBanner } from "../components/CaveatBanner";
import { ErrorState, SkeletonRows } from "../components/States";
import {
  InlineNotice,
  PageHeader,
  Panel,
  SectionHeader,
} from "../components/Primitives";
import { fixed, pct, rankLabel } from "../lib/format";
import { DomainMatrix } from "./DomainMatrix";

export function Leaderboard() {
  const [params, setParams] = useSearchParams();
  const taskId = params.get("task") ?? "";
  const meta = useAsync((signal) => api.meta(signal), []);
  const leaderboard = useAsync(
    (signal) => api.leaderboard(taskId || null, signal),
    [taskId],
  );

  return (
    <div>
      <PageHeader
        eyebrow="Analyze"
        title="Leaderboard"
        description="A serious benchmark surface: server-ordered ranks, pass rates, and the uncertainty that qualifies them."
        actions={
          <>
            <Link className="btn btn-secondary" to="/runs">
              Advanced runs
            </Link>
            <Link className="btn btn-secondary" to="/methodology">
              <Info size={15} aria-hidden="true" /> Read methodology
            </Link>
          </>
        }
      />
      <CaveatBanner caveat={meta.data?.notes?.trust} />
      <Panel>
        <SectionHeader
          title="Scope"
          description="Each scope is ranked by the benchmark kernel, with its uncertainty preserved."
        />
        <div className="toolbar">
          <label htmlFor="leaderboard-task">
            <Filter size={14} aria-hidden="true" /> Task scope
          </label>
          <select
            id="leaderboard-task"
            value={taskId}
            onChange={(event) => {
              const next = event.target.value;
              if (next) setParams({ task: next });
              else setParams({});
            }}
          >
            <option value="">All tasks · pooled</option>
            {meta.data?.tasks.map((task) => (
              <option key={task.task_id} value={task.task_id}>
                {task.task_id}
              </option>
            ))}
          </select>
        </div>
      </Panel>

      <Panel>
        <SectionHeader
          title={
            taskId ? `Agents on ${taskId}` : "All agents · pooled across tasks"
          }
          description="Rank ranges are preserved from the kernel. Overlapping intervals are evidence of limited separation, not a UI problem."
        />
        {leaderboard.loading ? (
          <SkeletonRows rows={6} cols={6} />
        ) : leaderboard.error ? (
          <ErrorState error={leaderboard.error} onRetry={leaderboard.reload} />
        ) : (
          <div className="table-scroll" tabIndex={0}>
            <table className="data">
              <thead>
                <tr>
                  <th className="num">rank</th>
                  <th>agent</th>
                  <th className="num">valid n</th>
                  <th>pass rate</th>
                  <th>Wilson 95%</th>
                  <th className="num">LCB</th>
                  <th>state</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {leaderboard.data!.entries.map((entry) => (
                  <tr key={entry.agent}>
                    <td className="num">
                      {entry.provisional ? (
                        <ProvisionalBadge />
                      ) : (
                        <span className="rank-number">
                          {rankLabel(
                            entry.provisional,
                            entry.rank_low,
                            entry.rank_high,
                          )}
                        </span>
                      )}
                    </td>
                    <td className="primary-cell">
                      <Link to={`/agent/${encodeURIComponent(entry.agent)}`}>
                        {entry.agent}
                      </Link>
                      {entry.synthetic && (
                        <span className="sub-cell">synthetic baseline</span>
                      )}
                    </td>
                    <td className="num mono">{entry.n}</td>
                    <td>
                      <span className="mono">{pct(entry.pass_rate, 1)}</span>
                    </td>
                    <td>
                      <WilsonBar
                        pHat={entry.pass_rate}
                        low={entry.wilson_low}
                        high={entry.wilson_high}
                      />
                    </td>
                    <td className="num mono">{fixed(entry.wilson_low, 3)}</td>
                    <td>
                      {entry.provisional ? (
                        <ProvisionalBadge />
                      ) : (
                        <span className="badge neutral">ranked</span>
                      )}
                    </td>
                    <td>
                      {taskId ? (
                        <Link
                          className="link-arrow"
                          to={`/cell/${encodeURIComponent(entry.agent)}/${encodeURIComponent(taskId)}`}
                        >
                          Cell →
                        </Link>
                      ) : (
                        <Link
                          className="link-arrow"
                          to={`/agent/${encodeURIComponent(entry.agent)}`}
                        >
                          Profile →
                        </Link>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <InlineNotice tone="info">
          The rank column is the kernel’s Wilson lower-bound ranking. The
          interval bar is not a progress bar: it shows the plausible range
          around the observed pass rate. Provisional rows remain visibly
          unranked.
        </InlineNotice>
      </Panel>

      <Panel>
        <SectionHeader
          title="Domain capability matrix"
          description="Server-returned domain profiles. Suppressed cells remain suppressed; they are not low scores."
        />
        {meta.data?.models ? (
          <DomainMatrix agents={meta.data.models} />
        ) : (
          <p className="note muted">Agent metadata is still loading.</p>
        )}
      </Panel>

      <Panel>
        <SectionHeader
          title="Reference baselines"
          description="Synthetic oracle/noop rows are benchmark bookends, not real competitors."
        />
        {meta.data?.synthetic_agents.length && meta.data.tasks[0] ? (
          <div className="reference-links">
            {meta.data.synthetic_agents.map((reference) => (
              <div className="reference-link" key={reference}>
                <span>{reference}</span>
                <span>
                  <Link
                    to={`/cell/${encodeURIComponent(reference)}/${encodeURIComponent(meta.data!.tasks[0].task_id)}`}
                  >
                    cell
                  </Link>{" "}
                  ·{" "}
                  <Link
                    to={`/cell/${encodeURIComponent(reference)}/${encodeURIComponent(meta.data!.tasks[0].task_id)}/run/0`}
                  >
                    run #0
                  </Link>
                </span>
              </div>
            ))}
          </div>
        ) : (
          <p className="note muted">
            No synthetic baselines reported by the API.
          </p>
        )}
      </Panel>
    </div>
  );
}
