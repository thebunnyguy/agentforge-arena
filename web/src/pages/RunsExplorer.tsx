import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import { useAsync } from "../lib/useAsync";
import type { CellRunRow } from "../api/types";
import {
  CaptureBadge,
  GateBadge,
  PassBadge,
  ScoreBadge,
  StatusBadge,
} from "../components/Badges";
import { CaveatBanner } from "../components/CaveatBanner";
import { ErrorState, Loading } from "../components/States";
import { fixed } from "../lib/format";

// Filterable run table. The read-only API exposes runs per (agent, task) cell,
// so the explorer scopes by agent + task and then filters in-browser for
// DISPLAY only (status / functional pass / capture). No statistics derived.
export function RunsExplorer() {
  const meta = useAsync((s) => api.meta(s), []);
  const [agent, setAgent] = useState("");
  const [taskId, setTaskId] = useState("");
  const [status, setStatus] = useState("");
  const [funcPass, setFuncPass] = useState("");

  const ready = agent && taskId;
  const cell = useAsync(
    (s) => (ready ? api.cell(agent, taskId, s) : Promise.resolve(null)),
    [agent, taskId],
  );

  const filtered = useMemo<CellRunRow[]>(() => {
    const rows = cell.data?.runs ?? [];
    return rows.filter((r) => {
      if (status && r.status !== status) return false;
      if (funcPass === "pass" && !r.score.functional_pass) return false;
      if (funcPass === "fail" && r.score.functional_pass) return false;
      return true;
    });
  }, [cell.data, status, funcPass]);

  if (meta.loading) return <Loading />;
  if (meta.error) return <ErrorState error={meta.error} onRetry={meta.reload} />;

  return (
    <div>
      <h1 className="page-title">Runs</h1>
      <p className="page-subtitle">
        Browse runs in a cell. Pick an agent and task, then filter for display.
      </p>
      <CaveatBanner caveat={meta.data?.notes?.trust} />

      <div className="toolbar">
        <select value={agent} onChange={(e) => setAgent(e.target.value)}>
          <option value="">agent…</option>
          {meta.data!.models.map((a: string) => (
            <option key={a} value={a}>
              {a}
            </option>
          ))}
        </select>
        <select value={taskId} onChange={(e) => setTaskId(e.target.value)}>
          <option value="">task…</option>
          {meta.data!.tasks.map((t) => (
            <option key={t.task_id} value={t.task_id}>
              {t.task_id}
            </option>
          ))}
        </select>
        <select value={status} onChange={(e) => setStatus(e.target.value)}>
          <option value="">any status</option>
          <option value="valid">valid</option>
          <option value="timeout">timeout</option>
          <option value="agent_error">agent_error</option>
          <option value="infra_failure">infra_failure</option>
        </select>
        <select value={funcPass} onChange={(e) => setFuncPass(e.target.value)}>
          <option value="">pass/fail</option>
          <option value="pass">functional pass</option>
          <option value="fail">functional fail</option>
        </select>
      </div>

      <div className="panel">
        {!ready ? (
          <p className="note muted">Select an agent and a task to list runs.</p>
        ) : cell.loading ? (
          <Loading />
        ) : cell.error ? (
          <ErrorState error={cell.error} onRetry={cell.reload} />
        ) : (
          <>
            <p className="note">
              Cell state <CaptureBadge state={cell.data!.state} />
            </p>
            <table className="data">
              <thead>
                <tr>
                  <th className="num">idx</th>
                  <th>status</th>
                  <th className="num">G</th>
                  <th className="num">S</th>
                  <th>X</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {filtered.map((r) => (
                  <tr key={r.idx}>
                    <td className="num">{r.idx}</td>
                    <td>
                      <StatusBadge status={r.status} />
                    </td>
                    <td className="num">
                      <GateBadge g={r.score.gate_product} />
                    </td>
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
              Showing {filtered.length} of {cell.data!.runs.length} runs
              {cell.data!.aggregate
                ? ` · mean S (server) ${fixed(cell.data!.aggregate.mean_s)}`
                : ""}
              .
            </p>
          </>
        )}
      </div>
    </div>
  );
}
