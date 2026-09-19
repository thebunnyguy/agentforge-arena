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
import { EvidenceScopeSelect } from "../components/EvidenceScopeBanner";
import { EvidenceClassBadge, VersionStatusBadge } from "../components/Badges";
import { runHref } from "../lib/links";
import { useEvidenceScope } from "../lib/useEvidenceScope";

export function RunsExplorer() {
  const meta = useAsync((signal) => api.meta({}, signal), []);
  const [agent, setAgent] = useState("");
  const [taskId, setTaskId] = useState("");
  const [status, setStatus] = useState("");
  const [funcPass, setFuncPass] = useState("");
  const [version, setVersion] = useState("");
  const [scope, setScope] = useEvidenceScope();
  const ready = Boolean(agent && taskId);
  const cell = useAsync(
    (signal) =>
      ready
        ? api.cell(
            agent,
            taskId,
            { version: version || null, evidence: scope },
            signal,
          )
        : Promise.resolve(null),
    [agent, taskId, version, scope],
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
          description="Run identity is the exact run id: agent + task + repeat index repeats across task versions, so each row links by run id."
        />
        <div className="toolbar">
          <label htmlFor="run-agent">Agent</label>
          <select
            id="run-agent"
            value={agent}
            onChange={(event) => {
              setAgent(event.target.value);
              setVersion("");
            }}
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
            onChange={(event) => {
              setTaskId(event.target.value);
              setVersion("");
            }}
          >
            <option value="">Choose task…</option>
            {meta.data!.tasks.map((task) => (
              <option value={task.task_id} key={task.task_id}>
                {task.task_id}
              </option>
            ))}
          </select>
          <label htmlFor="run-version">Task version</label>
          <select
            id="run-version"
            value={version}
            onChange={(event) => setVersion(event.target.value)}
            disabled={!ready}
          >
            <option value="">Current version</option>
            {(cell.data?.versions ?? [])
              .filter((v) => v.status === "historical")
              .map((v) => (
                <option key={v.version} value={v.version}>
                  Historical {v.version}
                </option>
              ))}
          </select>
          <EvidenceScopeSelect
            scope={scope}
            onChange={setScope}
            id="runs-evidence-scope"
          />
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
              action={
                cell.data!.evidence_status ? (
                  <VersionStatusBadge
                    status={
                      cell.data!.evidence_status === "none" &&
                      cell.data!.has_historical_evidence &&
                      !cell.data!.has_current_evidence
                        ? "missing"
                        : cell.data!.evidence_status
                    }
                  />
                ) : undefined
              }
            />
            <div className="table-scroll" tabIndex={0}>
              <table className="data">
                <thead>
                  <tr>
                    <th className="num">run</th>
                    <th>version</th>
                    <th>evidence class</th>
                    <th>status</th>
                    <th className="num">G</th>
                    <th className="num">S</th>
                    <th>X</th>
                    <th></th>
                  </tr>
                </thead>
                <tbody>
                  {filtered.map((run) => (
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
                          to={runHref(run, agent, taskId)}
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
