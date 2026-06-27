import { Link, useParams } from "react-router-dom";
import { api } from "../api/client";
import { useAsync } from "../lib/useAsync";
import type { CaptureState, RunDetailResponse } from "../api/types";
import {
  CaptureBadge,
  GateBadge,
  PassBadge,
  ScoreBadge,
  StatusBadge,
} from "../components/Badges";
import { CaveatBanner } from "../components/CaveatBanner";
import { PatchView } from "../components/PatchView";
import { EmptyState, ErrorState, Loading } from "../components/States";
import { durationMs, fixed, formatDate } from "../lib/format";

// Single run detail. Serves BOTH the explorer route
// (/cell/:agent/:taskId/run/:idx) and the product job route
// (/jobs/:jobId/runs/:taskId/:idx). For the job route the agent name is the
// job's run-group label (params.name || params.model), resolved by first
// fetching the job, then reading the run by (agent, task_id, idx).
export function RunPage() {
  const { agent, taskId = "", idx = "0", jobId } = useParams();
  const i = Number(idx);

  // When on the job route, resolve the agent name from the job first.
  const job = useAsync(
    (s) => (jobId ? api.job(jobId, s) : Promise.resolve(null)),
    [jobId],
  );

  const resolvedAgent = jobId
    ? job.data?.params.name || job.data?.params.model || ""
    : agent || "";

  const detail = useAsync(
    (s) =>
      jobId && !resolvedAgent
        ? Promise.resolve(null)
        : api.run(resolvedAgent, taskId, i, s),
    [resolvedAgent, taskId, i],
  );

  if (job.loading || detail.loading) return <Loading label="Loading run…" />;
  if (job.error) return <ErrorState error={job.error} onRetry={job.reload} />;
  if (detail.error) return <ErrorState error={detail.error} onRetry={detail.reload} />;

  const r = detail.data as RunDetailResponse | null;
  if (!r || !r.found) {
    return (
      <EmptyState title="Run not found">
        <p className="note muted">
          No run for {resolvedAgent} × {taskId} #{i}.
        </p>
      </EmptyState>
    );
  }

  const captureState: CaptureState = r.synthetic
    ? "synthetic"
    : r.patch_available
      ? "captured"
      : "not_captured";

  const backLink = jobId
    ? `/jobs/${encodeURIComponent(jobId)}`
    : `/cell/${encodeURIComponent(r.agent)}/${encodeURIComponent(r.task_id)}`;

  const score = r.score!;

  return (
    <div>
      <h1 className="page-title">
        Run {r.idx} · {r.agent} × {r.task_id}
      </h1>
      <p className="page-subtitle">
        <Link to={backLink}>← back to {jobId ? "job" : "cell"}</Link> · task version{" "}
        <code>{r.task_version ?? "—"}</code>
      </p>
      <CaveatBanner />

      <div className="panel">
        <h2>
          Identity &amp; status {r.status && <StatusBadge status={r.status} />}{" "}
          <CaptureBadge state={captureState} />{" "}
          {r.synthetic && <span className="badge synthetic">synthetic</span>}
        </h2>
        <dl className="kv">
          <dt>agent</dt>
          <dd>{r.agent}</dd>
          <dt>task</dt>
          <dd>{r.task_id}</dd>
          <dt>task version</dt>
          <dd>{r.task_version ?? "—"}</dd>
          <dt>idx</dt>
          <dd>{r.idx}</dd>
          <dt>status</dt>
          <dd>{r.status ?? "—"}</dd>
          <dt>known task</dt>
          <dd>{r.known_task ? "yes" : "no"}</dd>
          <dt>duration</dt>
          <dd>{durationMs(r.duration_ms)}</dd>
          <dt>created at</dt>
          <dd>{formatDate(r.created_at)}</dd>
          {r.transcript_hash && (
            <>
              <dt>transcript hash</dt>
              <dd>{r.transcript_hash}</dd>
            </>
          )}
        </dl>
      </div>

      <div className="panel">
        <h2>
          Score breakdown <ScoreBadge score={score.final_score} />{" "}
          <PassBadge pass={score.functional_pass} />
        </h2>
        <div className="grid-2">
          <Stat label="G (gate product)" value={<GateBadge g={score.gate_product} />} />
          <Stat label="T_hidden" value={fixed(score.t_hidden)} />
          <Stat label="Q (quality)" value={fixed(score.q)} />
          <Stat label="S (final score)" value={fixed(score.final_score)} />
          <Stat label="X (functional pass)" value={score.functional_pass ? "true" : "false"} />
          <Stat label="voided" value={score.voided ? "true" : "false"} />
        </div>

        <h3>Q components</h3>
        {!score.q_components_available ||
        Object.keys(score.q_components).length === 0 ? (
          <p className="note muted">
            Q components unavailable for this run — the scorer used the default
            Q&nbsp;=&nbsp;1.0 (absent evidence must not penalise). The
            0.85+0.15·Q band therefore contributes its full 1.0 multiplier. (Q
            components are not persisted in v0.1.)
          </p>
        ) : (
          <table className="data" style={{ maxWidth: 420 }}>
            <thead>
              <tr>
                <th>component</th>
                <th className="num">value</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(score.q_components).map(([k, v]) => (
                <tr key={k}>
                  <td>{k}</td>
                  <td className="num">{fixed(v)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        <p className="note muted">S = G · T_hidden · (0.85 + 0.15·Q).</p>
      </div>

      <div className="panel">
        <h2>Diff</h2>
        {r.files_changed === undefined ? (
          <p className="note muted">Diff stats not captured for this run.</p>
        ) : (
          <div className="grid-2">
            <Stat label="files changed" value={r.files_changed} />
            <Stat label="lines added" value={r.lines_added ?? 0} />
            <Stat label="lines removed" value={r.lines_removed ?? 0} />
            <Stat
              label="touched protected"
              value={
                r.touched_protected ? (
                  <span className="badge bad">yes</span>
                ) : (
                  <span className="badge good">no</span>
                )
              }
            />
          </div>
        )}
      </div>

      <div className="panel">
        <h2>Patch</h2>
        <PatchView
          patch={r.patch_available ? (r.patch_text ?? null) : null}
          captureState={captureState}
        />
      </div>

      <div className="panel">
        <h2>Hidden test results</h2>
        {!r.test_results || r.test_results.length === 0 ? (
          <p className="note muted">
            {r.synthetic
              ? "Per-test results not captured (synthetic baseline)."
              : "No per-test results captured for this run."}
          </p>
        ) : (
          <table className="data">
            <thead>
              <tr>
                <th>test</th>
                <th>suite</th>
                <th className="num">weight</th>
                <th>result</th>
              </tr>
            </thead>
            <tbody>
              {r.test_results.map((t) => (
                <tr key={`${t.suite}:${t.test_name}`}>
                  <td className="mono">{t.test_name}</td>
                  <td>{t.suite}</td>
                  <td className="num">{t.weight}</td>
                  <td>
                    <span className={`badge ${t.passed ? "good" : "bad"}`}>
                      {t.passed ? "pass" : "fail"}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="stat">
      <div className="label">{label}</div>
      <div className="value mono">{value}</div>
    </div>
  );
}
