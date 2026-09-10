import { useState } from "react";
import type { KeyboardEvent } from "react";
import { FileCode2, FlaskConical, Info, ShieldCheck } from "lucide-react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api/client";
import { useAsync } from "../lib/useAsync";
import type { CaptureState, RunDetailResponse } from "../api/types";
import {
  CaptureBadge,
  GateBadge,
  PassBadge,
  RunOutcomeBadge,
  ScoreBadge,
  StatusBadge,
} from "../components/Badges";
import { CaveatBanner } from "../components/CaveatBanner";
import { PatchView } from "../components/PatchView";
import { ErrorState, EmptyState, Loading } from "../components/States";
import {
  InlineNotice,
  Metric,
  MetricGroup,
  PageHeader,
  Panel,
  SectionHeader,
} from "../components/Primitives";
import { durationMs, fixed, formatDate } from "../lib/format";

export function RunPage() {
  const { agent, taskId = "", idx = "0", jobId } = useParams();
  const runIndex = Number(idx);
  const [tab, setTab] = useState<"patch" | "tests" | "metadata">("patch");
  const job = useAsync(
    (signal) => (jobId ? api.job(jobId, signal) : Promise.resolve(null)),
    [jobId],
  );
  const resolvedAgent = jobId ? (job.data?.params.model ?? "") : (agent ?? "");
  const detail = useAsync(
    (signal) =>
      resolvedAgent
        ? api.run(resolvedAgent, taskId, runIndex, signal)
        : Promise.resolve(null),
    [resolvedAgent, taskId, runIndex],
  );

  if (job.loading || detail.loading)
    return <Loading label="Loading run evidence…" />;
  if (job.error) return <ErrorState error={job.error} onRetry={job.reload} />;
  if (detail.error)
    return <ErrorState error={detail.error} onRetry={detail.reload} />;
  const run = detail.data as RunDetailResponse | null;
  if (!run || !run.found || !run.score)
    return (
      <EmptyState title="Run not found">
        <p>
          No run for {resolvedAgent} × {taskId} #{runIndex} was returned by the
          local API.
        </p>
      </EmptyState>
    );

  const runStatus = run.status ?? run.score.status;
  const captureState: CaptureState = run.synthetic
    ? "synthetic"
    : run.patch_available
      ? "captured"
      : "not_captured";
  const backLink = jobId
    ? `/jobs/${encodeURIComponent(jobId)}`
    : `/cell/${encodeURIComponent(run.agent)}/${encodeURIComponent(run.task_id)}`;
  const testRows = Array.isArray(run.test_results) ? run.test_results : [];

  return (
    <div>
      <PageHeader
        eyebrow="Run forensics"
        title={`Run #${run.idx}`}
        description={`${run.agent} · ${run.task_id} · task version ${run.task_version ?? "—"}`}
        actions={
          <Link className="btn btn-secondary" to={backLink}>
            ← Back to {jobId ? "evaluation" : "cell"}
          </Link>
        }
      />
      <CaveatBanner />
      <div className="score-hero">
        <div>
          <div className="score-hero-label">Functional outcome</div>
          <div className="score-hero-value">
            {runStatus === "infra_failure"
              ? "VOID"
              : run.score.functional_pass
                ? "PASS"
                : "FAIL"}
          </div>
          <div className="note muted">
            Evidence state: <CaptureBadge state={captureState} />
          </div>
        </div>
        <div className="score-hero-badges">
          <StatusBadge status={runStatus} />
          <ScoreBadge score={run.score.final_score} />
          <RunOutcomeBadge
            status={runStatus}
            functionalPass={run.score.functional_pass}
          />
        </div>
      </div>

      <MetricGroup>
        <Metric
          label="G"
          value={<GateBadge g={run.score.gate_product} />}
          detail="gate product"
          mono
        />
        <Metric
          label="T_hidden"
          value={fixed(run.score.t_hidden)}
          detail="hidden test fraction"
          mono
        />
        <Metric
          label="Q"
          value={fixed(run.score.q)}
          detail={
            run.score.q_components_available
              ? "quality components"
              : "components unavailable"
          }
          mono
        />
        <Metric
          label="S"
          value={fixed(run.score.final_score)}
          detail="final score"
          tone={
            runStatus === "infra_failure"
              ? "void"
              : run.score.functional_pass
                ? "good"
                : "bad"
          }
          mono
        />
      </MetricGroup>

      <Panel>
        <SectionHeader
          title="Score reading"
          description="Persisted score primitives and the evidence available for this run."
        />
        <div className="formula">
          S = G · T_hidden · (0.85 + 0.15 · Q) ={" "}
          <strong>{fixed(run.score.final_score)}</strong>
        </div>
        {run.score.q_components_available &&
          Object.keys(run.score.q_components).length > 0 && (
            <table className="data q-components">
              <thead>
                <tr>
                  <th>Q component</th>
                  <th className="num">value</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(run.score.q_components).map(([key, value]) => (
                  <tr key={key}>
                    <td>{key}</td>
                    <td className="num mono">{fixed(value)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        <div className="grid-2 evidence-copy">
          <InlineNotice
            tone={run.score.gate_product === 1 ? "success" : "danger"}
          >
            <ShieldCheck size={16} aria-hidden="true" />
            <span>
              G = {run.score.gate_product}. The stored gate product is
              available; per-gate booleans are not persisted in v0.1.
            </span>
          </InlineNotice>
          <InlineNotice
            tone={run.score.q_components_available ? "success" : "info"}
          >
            <Info size={16} aria-hidden="true" />
            <span>
              {run.score.q_components_available
                ? "Q components are available for this run."
                : "Q components are unavailable in persisted v0.1 records; do not treat the absence as a failed quality check."}
            </span>
          </InlineNotice>
        </div>
      </Panel>

      <Panel>
        <EvidenceTabs tab={tab} setTab={setTab} />
        {tab === "patch" && (
          <div
            id="run-panel-patch"
            role="tabpanel"
            aria-labelledby="run-tab-patch"
          >
            <SectionHeader
              title="Patch"
              description="Unified diff capture is shown exactly when the API marks it available."
            />
            <PatchView
              patch={run.patch_available ? (run.patch_text ?? null) : null}
              captureState={captureState}
            />
            <div className="grid-auto stat-grid">
              <Metric
                label="Files changed"
                value={run.files_changed ?? "—"}
                mono
              />
              <Metric label="Lines added" value={run.lines_added ?? "—"} mono />
              <Metric
                label="Lines removed"
                value={run.lines_removed ?? "—"}
                mono
              />
              <Metric
                label="Protected paths"
                value={
                  run.touched_protected === undefined
                    ? "unavailable"
                    : run.touched_protected
                      ? "touched"
                      : "not touched"
                }
                tone={
                  run.touched_protected === undefined
                    ? "warn"
                    : run.touched_protected
                      ? "bad"
                      : "good"
                }
              />
            </div>
          </div>
        )}
        {tab === "tests" && (
          <div
            id="run-panel-tests"
            role="tabpanel"
            aria-labelledby="run-tab-tests"
          >
            <TestEvidence run={run} testRows={testRows} />
          </div>
        )}
        {tab === "metadata" && (
          <div
            id="run-panel-metadata"
            role="tabpanel"
            aria-labelledby="run-tab-metadata"
          >
            <SectionHeader
              title="Provenance"
              description="Identity fields make this result traceable to a task version and repeat."
            />
            <dl className="kv">
              <dt>agent</dt>
              <dd>{run.agent}</dd>
              <dt>task</dt>
              <dd>{run.task_id}</dd>
              <dt>known task</dt>
              <dd>{run.known_task ? "yes" : "no"}</dd>
              <dt>repeat index</dt>
              <dd>{run.idx}</dd>
              <dt>task version</dt>
              <dd>{run.task_version ?? "—"}</dd>
              <dt>status</dt>
              <dd>{runStatus}</dd>
              <dt>voided</dt>
              <dd>{run.score.voided ? "yes" : "no"}</dd>
              <dt>duration</dt>
              <dd>{durationMs(run.duration_ms)}</dd>
              <dt>created</dt>
              <dd>{formatDate(run.created_at)}</dd>
              <dt>transcript hash</dt>
              <dd>{run.transcript_hash ?? "—"}</dd>
            </dl>
          </div>
        )}
      </Panel>
    </div>
  );
}

function EvidenceTabs({
  tab,
  setTab,
}: {
  tab: "patch" | "tests" | "metadata";
  setTab: (tab: "patch" | "tests" | "metadata") => void;
}) {
  const tabs: Array<{
    id: "patch" | "tests" | "metadata";
    label: string;
    icon: typeof FileCode2;
  }> = [
    { id: "patch", label: "Patch", icon: FileCode2 },
    { id: "tests", label: "Tests", icon: FlaskConical },
    { id: "metadata", label: "Metadata", icon: Info },
  ];
  function selectAndFocus(id: "patch" | "tests" | "metadata") {
    setTab(id);
    requestAnimationFrame(() =>
      document.getElementById(`run-tab-${id}`)?.focus(),
    );
  }
  function onKeyDown(event: KeyboardEvent<HTMLButtonElement>) {
    const current = tabs.findIndex((item) => item.id === tab);
    if (event.key === "ArrowRight" || event.key === "ArrowDown") {
      event.preventDefault();
      selectAndFocus(tabs[(current + 1) % tabs.length].id);
    }
    if (event.key === "ArrowLeft" || event.key === "ArrowUp") {
      event.preventDefault();
      selectAndFocus(tabs[(current - 1 + tabs.length) % tabs.length].id);
    }
    if (event.key === "Home") {
      event.preventDefault();
      selectAndFocus(tabs[0].id);
    }
    if (event.key === "End") {
      event.preventDefault();
      selectAndFocus(tabs[tabs.length - 1].id);
    }
  }
  return (
    <div className="evidence-tabs" role="tablist" aria-label="Run evidence">
      {tabs.map(({ id, label, icon: Icon }) => (
        <button
          type="button"
          key={id}
          id={`run-tab-${id}`}
          className={tab === id ? "active" : ""}
          role="tab"
          aria-selected={tab === id}
          aria-controls={`run-panel-${id}`}
          tabIndex={tab === id ? 0 : -1}
          onKeyDown={onKeyDown}
          onClick={() => setTab(id)}
        >
          <Icon size={15} aria-hidden="true" /> {label}
        </button>
      ))}
    </div>
  );
}

function TestEvidence({
  run,
  testRows,
}: {
  run: RunDetailResponse;
  testRows: Array<{
    suite: string;
    test_name: string;
    passed: boolean;
    weight: number;
  }>;
}) {
  if (run.synthetic)
    return (
      <InlineNotice tone="info">
        <FlaskConical size={16} aria-hidden="true" />
        <span>
          Synthetic baseline — no real patch or per-test results exist.
        </span>
      </InlineNotice>
    );
  if (testRows.length > 0) {
    const suites = [...new Set(testRows.map((row) => row.suite))];
    return (
      <div>
        {suites.map((suite) => (
          <div className="test-suite" key={suite}>
            <h3>{suite}</h3>
            {testRows
              .filter((row) => row.suite === suite)
              .map((row) => (
                <div className="test-row" key={`${row.suite}:${row.test_name}`}>
                  <span className="test-name">{row.test_name}</span>
                  <span className="mono">w {row.weight}</span>
                  <PassBadge pass={row.passed} />
                </div>
              ))}
          </div>
        ))}
      </div>
    );
  }
  if (!run.patch_available)
    return (
      <InlineNotice tone="warn">
        <FlaskConical size={16} aria-hidden="true" />
        <span>Per-test results were not captured for this legacy run.</span>
      </InlineNotice>
    );
  return (
    <InlineNotice tone="warn">
      <FlaskConical size={16} aria-hidden="true" />
      <span>
        Patch captured, but the grade report recorded no per-test rows.
      </span>
    </InlineNotice>
  );
}
