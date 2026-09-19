import { useState } from "react";
import type { KeyboardEvent } from "react";
import { FileCode2, FlaskConical, Info, ShieldCheck } from "lucide-react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { api, ApiRequestError } from "../api/client";
import { useAsync } from "../lib/useAsync";
import {
  PARAMS_UNAVAILABLE_TITLE,
  jobParamsView,
  reasonSentence,
} from "../lib/jobParams";
import type { CaptureState, RunDetailResponse } from "../api/types";
import {
  CaptureBadge,
  EvidenceClassBadge,
  GateBadge,
  PassBadge,
  RunOutcomeBadge,
  ScoreBadge,
  StatusBadge,
  VersionStatusBadge,
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
  const { agent, taskId = "", idx = "0", jobId, runId } = useParams();
  const [searchParams] = useSearchParams();
  const version = searchParams.get("version") || null;
  const runIndex = Number(idx);
  const [tab, setTab] = useState<"patch" | "tests" | "metadata">("patch");
  const job = useAsync(
    (signal) => (jobId ? api.job(jobId, signal) : Promise.resolve(null)),
    [jobId],
  );
  // Job.params can be null (unverifiable): never dereference it here.
  const jobView = job.data ? jobParamsView(job.data) : null;
  const resolvedAgent = jobId
    ? jobView?.available
      ? jobView.model
      : ""
    : (agent ?? "");
  const detail = useAsync(
    (signal) => {
      if (runId) return api.runById(runId, signal);
      return resolvedAgent
        ? api.run(resolvedAgent, taskId, runIndex, { version }, signal)
        : Promise.resolve(null);
    },
    [runId, resolvedAgent, taskId, runIndex, version],
  );

  if (job.loading || detail.loading)
    return <Loading label="Loading run evidence…" />;
  if (job.error) return <ErrorState error={job.error} onRetry={job.reload} />;
  if (jobId && jobView && !jobView.available)
    return (
      <EmptyState
        title={PARAMS_UNAVAILABLE_TITLE}
        action={
          <Link
            className="btn btn-secondary btn-small"
            to={`/jobs/${encodeURIComponent(jobId)}`}
          >
            Back to evaluation
          </Link>
        }
      >
        <p>
          This evaluation's persisted parameters are unverifiable, so the run
          cannot be resolved through it. {reasonSentence(jobView.reason)}
        </p>
      </EmptyState>
    );
  if (detail.error) {
    const body =
      detail.error instanceof ApiRequestError ? detail.error.body : null;
    const candidates =
      detail.error instanceof ApiRequestError &&
      detail.error.status === 409 &&
      body &&
      typeof body === "object" &&
      Array.isArray((body as { candidate_run_ids?: unknown }).candidate_run_ids)
        ? ((body as { candidate_run_ids: number[] }).candidate_run_ids ?? [])
        : null;
    if (candidates)
      return (
        <EmptyState title="Ambiguous run identity">
          <p>
            More than one run matches {resolvedAgent} × {taskId} #{runIndex}.
            Open the exact run:
          </p>
          <div className="badge-row">
            {candidates.map((id) => (
              <Link className="version-chip" key={id} to={`/runs/${id}`}>
                run id {id}
              </Link>
            ))}
          </div>
        </EmptyState>
      );
    return <ErrorState error={detail.error} onRetry={detail.reload} />;
  }
  const run = detail.data as RunDetailResponse | null;
  if (!run || !run.found || !run.score)
    return (
      <EmptyState title="Run not found">
        <p>
          {runId
            ? `No run with id ${runId} was returned by the local API.`
            : `No run for ${resolvedAgent} × ${taskId} #${runIndex} at ${version ? `version ${version}` : "the current task version"} was returned by the local API.`}
        </p>
        {run?.historical_versions && run.historical_versions.length > 0 && (
          <p>
            Historical versions with a run at this index:{" "}
            {run.historical_versions.map((v) => (
              <Link
                className="version-chip"
                key={v}
                to={`?version=${encodeURIComponent(v)}`}
              >
                {v} · historical
              </Link>
            ))}
          </p>
        )}
      </EmptyState>
    );

  const runStatus = run.status ?? run.score.status;
  const captureState: CaptureState = run.synthetic
    ? "synthetic"
    : run.patch_available
      ? "captured"
      : "not_captured";
  const cellBase = `/cell/${encodeURIComponent(run.agent)}/${encodeURIComponent(run.task_id)}`;
  const backLink = jobId
    ? `/jobs/${encodeURIComponent(jobId)}`
    : run.version_status === "historical" && run.task_version
      ? `${cellBase}?version=${encodeURIComponent(run.task_version)}`
      : cellBase;
  const testRows = Array.isArray(run.test_results) ? run.test_results : [];

  return (
    <div>
      <PageHeader
        eyebrow="Run forensics"
        title={`Run #${run.idx}`}
        description={`${run.agent} · ${run.task_id} · evidence version ${run.task_version ?? "—"}`}
        actions={
          <Link className="btn btn-secondary" to={backLink}>
            ← Back to {jobId ? "evaluation" : "cell"}
          </Link>
        }
      />
      <CaveatBanner />
      {run.evidence_class === "synthetic" && !run.synthetic && (
        <InlineNotice tone="warn">
          <span>
            <strong>Synthetic - not benchmark evidence.</strong> This run was
            produced by the mock backend and is excluded from benchmark views.
          </span>
        </InlineNotice>
      )}
      <dl className="evidence-facts" aria-label="Run evidence status">
        <div>
          <dt>Evidence version</dt>
          <dd className="mono">{run.task_version ?? "—"}</dd>
        </div>
        {run.current_version !== undefined && (
          <div>
            <dt>Current task version</dt>
            <dd className="mono">{run.current_version ?? "—"}</dd>
          </div>
        )}
        {run.version_status && (
          <div>
            <dt>Status</dt>
            <dd>
              <VersionStatusBadge status={run.version_status} />
            </dd>
          </div>
        )}
        {run.evidence_class && (
          <div>
            <dt>Evidence class</dt>
            <dd>
              <EvidenceClassBadge
                cls={run.evidence_class}
                backendKind={run.backend_kind}
                long
              />
            </dd>
          </div>
        )}
      </dl>
      {run.version_status === "historical" && (
        <InlineNotice tone="warn">
          <span>
            <strong>HISTORICAL run</strong> - recorded at task version{" "}
            <span className="mono">{run.task_version}</span>; the current
            version is{" "}
            <span className="mono">{run.current_version ?? "unknown"}</span>. It
            is not part of the current benchmark.
          </span>
        </InlineNotice>
      )}
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
              <dt>evidence version</dt>
              <dd>{run.task_version ?? "—"}</dd>
              {run.current_version !== undefined && (
                <>
                  <dt>current task version</dt>
                  <dd>{run.current_version ?? "—"}</dd>
                </>
              )}
              {run.version_status && (
                <>
                  <dt>version status</dt>
                  <dd>{run.version_status.toUpperCase()}</dd>
                </>
              )}
              {run.run_id !== undefined && (
                <>
                  <dt>run id</dt>
                  <dd>{run.run_id}</dd>
                </>
              )}
              {run.job_id && (
                <>
                  <dt>evaluation</dt>
                  <dd>
                    <Link to={`/jobs/${encodeURIComponent(run.job_id)}`}>
                      {run.job_id}
                    </Link>
                  </dd>
                </>
              )}
              {run.evidence_class && (
                <>
                  <dt>evidence class</dt>
                  <dd>
                    {run.evidence_class}
                    {run.backend_kind ? ` · ${run.backend_kind}` : ""}
                    {run.provider_source
                      ? ` (provider source: ${run.provider_source})`
                      : ""}
                  </dd>
                </>
              )}
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
