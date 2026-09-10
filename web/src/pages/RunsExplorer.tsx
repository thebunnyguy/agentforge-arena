import { Filter } from "lucide-react";
import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import { useAsync } from "../lib/useAsync";
import type { CellRunRow } from "../api/types";
import {
  GateBadge,
  RunOutcomeBadge,
  ScoreBadge,
  StatusBadge,
} from "../components/Badges";
import { CaveatBanner } from "../components/CaveatBanner";
import { ErrorState, EmptyState, Loading } from "../components/States";
import { PageHeader, Panel, SectionHeader } from "../components/Primitives";

export function RunsExplorer() {
  const meta = useAsync((signal) => api.meta(signal), []);
  const [agent, setAgent] = useState("");
  const [taskId, setTaskId] = useState("");
  const [status, setStatus] = useState("");
  const [funcPass, setFuncPass] = useState("");
  const ready = Boolean(agent && taskId);
  const cell = useAsync(
    (signal) =>
      ready ? api.cell(agent, taskId, signal) : Promise.resolve(null),
    [agent, taskId],
  );
  const filtered = useMemo<CellRunRow[]>(
    () =>
      (cell.data?.runs ?? []).filter((run) => {
        if (status && run.status !== status) return false;
        if (funcPass === "pass" && !run.score.functional_pass) return false;
        if (
          funcPass === "fail" &&
          (run.score.functional_pass || run.status === "infra_failure")
        )
          return false;
        if (funcPass === "void" && run.status !== "infra_failure") return false;
        return true;
      }),
    [cell.data, status, funcPass],
  );

  if (meta.loading) return <Loading label="Loading run explorer…" />;
  if (meta.error)
    return <ErrorState error={meta.error} onRetry={meta.reload} />;
  return (
    <div>
      <PageHeader
        eyebrow="Advanced analysis"
        title="Runs explorer"
        description="A focused run table for one agent/task cell. Use it when you need a quick filter before opening forensic evidence."
      />
      <CaveatBanner caveat={meta.data?.notes?.trust} />
      <Panel>
        <SectionHeader
          title="Choose evidence scope"
          description="Run identity remains agent + task + repeat index."
        />
        <div className="toolbar">
          <label htmlFor="run-agent">Agent</label>
          <select
            id="run-agent"
            value={agent}
            onChange={(event) => setAgent(event.target.value)}
          >
            <option value="">Choose agent…</option>
            {meta.data!.models.map((item) => (
              <option value={item} key={item}>
                {item}
              </option>
            ))}
          </select>
          <label htmlFor="run-task">Task</label>
          <select
            id="run-task"
            value={taskId}
            onChange={(event) => setTaskId(event.target.value)}
          >
            <option value="">Choose task…</option>
            {meta.data!.tasks.map((task) => (
              <option value={task.task_id} key={task.task_id}>
                {task.task_id}
              </option>
            ))}
          </select>
          <label htmlFor="run-status">
            <Filter size={14} aria-hidden="true" /> Status
          </label>
          <select
            id="run-status"
            value={status}
            onChange={(event) => setStatus(event.target.value)}
          >
            <option value="">Any status</option>
            <option value="valid">Valid</option>
            <option value="timeout">Timeout</option>
            <option value="agent_error">Agent error</option>
            <option value="infra_failure">Void · infra</option>
          </select>
          <label htmlFor="run-outcome">Outcome</label>
          <select
            id="run-outcome"
            value={funcPass}
            onChange={(event) => setFuncPass(event.target.value)}
          >
            <option value="">Any outcome</option>
            <option value="pass">Functional pass</option>
            <option value="fail">Valid failure</option>
            <option value="void">Voided infrastructure</option>
          </select>
        </div>
      </Panel>
      <Panel>
        {!ready ? (
          <EmptyState title="Select an agent and task">
            <p>
              The API exposes run rows per cell, keeping this advanced table
              bounded.
            </p>
          </EmptyState>
        ) : cell.loading ? (
          <Loading />
        ) : cell.error ? (
          <ErrorState error={cell.error} onRetry={cell.reload} />
        ) : (
          <>
            <SectionHeader
              title={`${agent} × ${taskId}`}
              description={`Showing ${filtered.length} of ${cell.data!.runs.length} run rows.`}
            />
            <div className="table-scroll" tabIndex={0}>
              <table className="data">
                <thead>
                  <tr>
                    <th className="num">run</th>
                    <th>status</th>
                    <th className="num">G</th>
                    <th className="num">S</th>
                    <th>X</th>
                    <th></th>
                  </tr>
                </thead>
                <tbody>
                  {filtered.map((run) => (
                    <tr key={run.idx}>
                      <td className="num mono">#{run.idx}</td>
                      <td>
                        <StatusBadge status={run.status} />
                      </td>
                      <td className="num">
                        <GateBadge g={run.score.gate_product} />
                      </td>
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
                        <Link
                          className="link-arrow"
                          to={`/cell/${encodeURIComponent(agent)}/${encodeURIComponent(taskId)}/run/${run.idx}`}
                        >
                          Forensics
                        </Link>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}
      </Panel>
    </div>
  );
}
