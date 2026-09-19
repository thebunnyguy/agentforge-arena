import { Filter, History, Info } from "lucide-react";
import { Link, useSearchParams } from "react-router-dom";
import { api } from "../api/client";
import type { LeaderboardEntry } from "../api/types";
import { useAsync } from "../lib/useAsync";
import { WilsonBar } from "../components/WilsonBar";
import {
  MissingCurrentEvidence,
  ProvisionalBadge,
  VersionStatusBadge,
} from "../components/Badges";
import { CaveatBanner } from "../components/CaveatBanner";
import { EvidenceScopeBanner } from "../components/EvidenceScopeBanner";
import { ErrorState, SkeletonRows } from "../components/States";
import {
  InlineNotice,
  PageHeader,
  Panel,
  SectionHeader,
} from "../components/Primitives";
import { fixed, pct, rankLabel } from "../lib/format";
import { linkQuery, useEvidenceScope } from "../lib/useEvidenceScope";
import { DomainMatrix } from "./DomainMatrix";

// An entry with no valid runs at the selected version is a MISSING row, not a
// score of zero (task-scoped leaderboards emit n = 0 placeholder entries).
function hasEvidence(entry: LeaderboardEntry): boolean {
  return entry.n > 0;
}

export function Leaderboard() {
  const [params, setParams] = useSearchParams();
  const [scope, setScope] = useEvidenceScope();
  const taskId = params.get("task") ?? "";
  const version = taskId ? params.get("version") || null : null;
  const meta = useAsync(
    (signal) => api.meta({ evidence: scope }, signal),
    [scope],
  );
  const leaderboard = useAsync(
    (signal) =>
      api.leaderboard(taskId || null, { evidence: scope, version }, signal),
    [taskId, version, scope],
  );

  function update(changes: Record<string, string | null>) {
    setParams(
      (previous) => {
        const next = new URLSearchParams(previous);
        for (const [key, value] of Object.entries(changes)) {
          if (value) next.set(key, value);
          else next.delete(key);
        }
        return next;
      },
      { replace: false },
    );
  }

  const lb = leaderboard.data;
  const task = meta.data?.tasks.find(
    (candidate) => candidate.task_id === taskId,
  );
  const viewingHistorical = lb?.evidence_status === "historical";
  const benchmark = meta.data?.current_benchmark;
  const coverage = benchmark
    ? {
        withCurrent: benchmark.tasks_with_current_evidence,
        total: benchmark.n_tasks,
      }
    : null;

  // Rows: ranked entries first, then models that only have historical evidence.
  const entries = lb?.entries ?? [];
  const ranked = entries.filter(hasEvidence);
  const missingNames = new Set<string>([
    ...(lb?.historical_only_agents ?? []),
    ...entries
      .filter((entry) => !hasEvidence(entry))
      .map((entry) => entry.agent),
    ...(!taskId ? (meta.data?.historical_only_models ?? []) : []),
  ]);
  ranked.forEach((entry) => missingNames.delete(entry.agent));
  const historicalSet = new Set<string>([
    ...(lb?.historical_only_agents ?? []),
    ...(!taskId ? (meta.data?.historical_only_models ?? []) : []),
  ]);
  const missing = [...missingNames].sort();
  const historicalVersions = task?.historical_versions ?? [];

  return (
    <div>
      <PageHeader
        eyebrow="Analyze"
        title="Leaderboard"
        description={
          taskId
            ? `Agents on ${taskId}. Ranks are the kernel's, computed from one task version at a time.`
            : "Current benchmark evidence: server-ordered ranks over each task's current version, with the coverage and uncertainty that qualify them."
        }
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
      <EvidenceScopeBanner
        scope={scope}
        onScopeChange={setScope}
        coverage={taskId ? null : coverage}
      />
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
            onChange={(event) =>
              update({ task: event.target.value || null, version: null })
            }
          >
            <option value="">All tasks · pooled (current benchmark)</option>
            {meta.data?.tasks.map((item) => (
              <option key={item.task_id} value={item.task_id}>
                {item.task_id}
              </option>
            ))}
          </select>
          {taskId && (
            <>
              <label htmlFor="leaderboard-version">
                <History size={14} aria-hidden="true" /> Task version
              </label>
              <select
                id="leaderboard-version"
                value={version ?? ""}
                onChange={(event) =>
                  update({ version: event.target.value || null })
                }
              >
                <option value="">
                  Current version
                  {task?.current_version ? ` (${task.current_version})` : ""}
                </option>
                {historicalVersions.map((v) => (
                  <option key={v} value={v}>
                    Historical {v}
                  </option>
                ))}
              </select>
            </>
          )}
        </div>
      </Panel>

      {viewingHistorical && (
        <InlineNotice tone="warn">
          <History size={16} aria-hidden="true" />
          <span>
            <strong>HISTORICAL leaderboard</strong> - task {taskId}, version{" "}
            <span className="mono">{lb?.version}</span>. The current version is{" "}
            <span className="mono">{lb?.current_version ?? "unknown"}</span>.
            These rows are not part of the current benchmark; ranks are not
            claimed for historical evidence.
          </span>
        </InlineNotice>
      )}

      <Panel>
        <SectionHeader
          title={
            taskId
              ? `${viewingHistorical ? "HISTORICAL · " : ""}Agents on ${taskId}`
              : scope === "synthetic"
                ? "All agents · synthetic evidence (not benchmark)"
                : scope === "all"
                  ? "All agents · all evidence classes (not a benchmark view)"
                  : "All agents · current benchmark evidence"
          }
          description={
            viewingHistorical
              ? "Observed pass rates for the historical version only; nothing here is ranked."
              : "Rank ranges are preserved from the kernel. Overlapping intervals are evidence of limited separation, not a UI problem."
          }
        />
        {leaderboard.loading ? (
          <SkeletonRows rows={6} cols={6} />
        ) : leaderboard.error ? (
          <ErrorState error={leaderboard.error} onRetry={leaderboard.reload} />
        ) : ranked.length === 0 && missing.length === 0 ? (
          <p className="note muted">
            No agents have evidence in the selected scope
            {taskId ? " for this task" : ""}.
          </p>
        ) : (
          <div className="table-scroll" tabIndex={0}>
            <table className="data">
              <thead>
                <tr>
                  {!viewingHistorical && <th className="num">rank</th>}
                  <th>agent</th>
                  {!taskId && <th>coverage</th>}
                  <th className="num">valid n</th>
                  <th>pass rate</th>
                  <th>Wilson 95%</th>
                  <th className="num">LCB</th>
                  <th>state</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {ranked.map((entry) => {
                  const cov = entry.coverage;
                  const classes =
                    meta.data?.evidence_counts?.[entry.agent]?.current_by_class;
                  return (
                    <tr key={entry.agent}>
                      {!viewingHistorical && (
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
                      )}
                      <td className="primary-cell">
                        <Link
                          to={`/agent/${encodeURIComponent(entry.agent)}${linkQuery(scope)}`}
                        >
                          {entry.agent}
                        </Link>
                        {entry.synthetic && (
                          <span className="sub-cell">synthetic baseline</span>
                        )}
                        {!entry.synthetic && !taskId && classes && (
                          <span className="sub-cell">
                            evidence:{" "}
                            {Object.entries(classes)
                              .filter(([, n]) => n > 0)
                              .map(([cls, n]) => `${cls} ${n} runs`)
                              .join(" · ") || "none"}
                          </span>
                        )}
                      </td>
                      {!taskId && (
                        <td className="mono">
                          {cov ? (
                            <span
                              title={`${cov.tasks_with_current_evidence} of ${cov.tasks_total} tasks have current evidence`}
                            >
                              {cov.tasks_with_current_evidence}/
                              {cov.tasks_total}
                              <span className="sub-cell">
                                tasks with current evidence
                              </span>
                            </span>
                          ) : (
                            "—"
                          )}
                        </td>
                      )}
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
                        {viewingHistorical ? (
                          <VersionStatusBadge status="historical" />
                        ) : (
                          <>
                            {entry.provisional ? (
                              <ProvisionalBadge />
                            ) : (
                              <span className="badge neutral">ranked</span>
                            )}
                            {cov && !cov.complete && (
                              <span className="sub-cell">
                                <span className="badge warn">
                                  PARTIAL COVERAGE
                                </span>
                              </span>
                            )}
                          </>
                        )}
                      </td>
                      <td>
                        {taskId ? (
                          <Link
                            className="link-arrow"
                            to={`/cell/${encodeURIComponent(entry.agent)}/${encodeURIComponent(taskId)}${linkQuery(scope, version)}`}
                          >
                            Cell →
                          </Link>
                        ) : (
                          <Link
                            className="link-arrow"
                            to={`/agent/${encodeURIComponent(entry.agent)}${linkQuery(scope)}`}
                          >
                            Profile →
                          </Link>
                        )}
                      </td>
                    </tr>
                  );
                })}
                {missing.map((agent) => {
                  const counts = meta.data?.evidence_counts?.[agent];
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
                      {!taskId && (
                        <td className="mono">
                          {counts
                            ? `${counts.current_tasks}/${counts.tasks_total}`
                            : "—"}
                          <span className="sub-cell">
                            tasks with current evidence
                          </span>
                        </td>
                      )}
                      <td colSpan={4}>
                        {viewingHistorical ? (
                          <span>
                            <span className="badge neutral">NO EVIDENCE</span>
                            <span className="missing-note">
                              No runs at historical version {lb?.version}
                            </span>
                          </span>
                        ) : (
                          <MissingCurrentEvidence
                            historicalAvailable={historicalSet.has(agent)}
                            detail={
                              counts && !taskId
                                ? `(${counts.historical_runs} historical runs on ${counts.historical_tasks} tasks)`
                                : undefined
                            }
                          />
                        )}
                      </td>
                      <td>
                        <span className="badge warn">NOT RANKED</span>
                      </td>
                      <td>
                        {taskId ? (
                          <Link
                            className="link-arrow"
                            to={`/cell/${encodeURIComponent(agent)}/${encodeURIComponent(taskId)}${linkQuery(scope)}`}
                          >
                            Cell →
                          </Link>
                        ) : (
                          <Link
                            className="link-arrow"
                            to={`/agent/${encodeURIComponent(agent)}${linkQuery(scope)}`}
                          >
                            Profile →
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
        <InlineNotice tone="info">
          The rank column is the kernel’s Wilson lower-bound ranking over
          current-version evidence. The interval bar is not a progress bar: it
          shows the plausible range around the observed pass rate. Provisional
          rows remain visibly unranked, and a model with only historical
          evidence is listed as MISSING current evidence instead of being
          ranked.
        </InlineNotice>
      </Panel>

      <Panel>
        <SectionHeader
          title={
            scope === "synthetic" || scope === "all"
              ? "Domain capability matrix (current task versions, not benchmark evidence)"
              : "Domain capability matrix (current benchmark)"
          }
          description="Server-returned domain profiles built from current-version evidence only. Suppressed cells remain suppressed; they are not low scores."
        />
        {coverage && coverage.withCurrent < coverage.total && (
          <p className="note muted">
            With {coverage.withCurrent}/{coverage.total} tasks covered by
            current evidence, most domains do not reach the minimum of 5 tasks
            and 25 runs and stay suppressed (—). That reflects coverage, not low
            scores.
          </p>
        )}
        {meta.data?.models ? (
          <DomainMatrix agents={meta.data.models} scope={scope} />
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
