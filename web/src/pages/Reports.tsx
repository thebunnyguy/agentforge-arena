import { useState } from "react";
import { api, exportUrl, ApiRequestError } from "../api/client";
import { useAsync } from "../lib/useAsync";
import { CaveatBanner } from "../components/CaveatBanner";
import { ErrorState, Loading } from "../components/States";
import { formatDate } from "../lib/format";

// Reports = regenerate the static leaderboard from the current DB and download
// the JSON export (GET /export). All numbers come from the server.
export function Reports() {
  const meta = useAsync((s) => api.meta(s), []);
  const [regenerating, setRegenerating] = useState(false);
  const [regenMsg, setRegenMsg] = useState<string | null>(null);
  const [regenErr, setRegenErr] = useState<string | null>(null);

  if (meta.loading) return <Loading />;
  if (meta.error) return <ErrorState error={meta.error} onRetry={meta.reload} />;

  const obs = meta.data!.observability;

  async function regenerate() {
    setRegenerating(true);
    setRegenErr(null);
    setRegenMsg(null);
    try {
      const body = await api.regenerateReport();
      setRegenMsg(
        body.path
          ? `Report regenerated → ${body.path} (${body.bytes} bytes)`
          : "Report regenerated.",
      );
    } catch (e) {
      setRegenErr(e instanceof ApiRequestError ? e.message : String(e));
    } finally {
      setRegenerating(false);
    }
  }

  return (
    <div>
      <h1 className="page-title">Reports &amp; export</h1>
      <p className="page-subtitle">
        Regenerate the static leaderboard from the current database and export a
        snapshot.
      </p>
      <CaveatBanner caveat={meta.data?.notes?.trust} />

      <div className="panel">
        <h2>Database snapshot</h2>
        <dl className="kv">
          <dt>runs</dt>
          <dd>{obs.total_runs}</dd>
          <dt>agents</dt>
          <dd>{meta.data!.models.length}</dd>
          <dt>tasks</dt>
          <dd>{meta.data!.n_tasks}</dd>
          <dt>earliest run</dt>
          <dd>{formatDate(obs.first_created_at)}</dd>
          <dt>latest run</dt>
          <dd>{formatDate(obs.last_created_at)}</dd>
          <dt>patch coverage</dt>
          <dd>
            {obs.runs_with_patch}/{obs.total_runs}
          </dd>
        </dl>
        <p className="note muted">
          A regenerated report is a point-in-time snapshot of this database, not a
          live view. Mixed task versions cause a 409 refusal (never silently
          merged).
        </p>
      </div>

      <div className="panel">
        <h2>Regenerate</h2>
        <div className="row-actions">
          <button className="btn" disabled={regenerating} onClick={regenerate}>
            {regenerating ? "Regenerating…" : "Regenerate leaderboard.html"}
          </button>
        </div>
        {regenMsg && (
          <p className="note" style={{ color: "var(--good)" }}>
            {regenMsg}
          </p>
        )}
        {regenErr && (
          <p className="note" style={{ color: "var(--bad)" }}>
            {regenErr}
          </p>
        )}
      </div>

      <div className="panel">
        <h2>Export</h2>
        <p className="note muted">
          The JSON export reuses the frozen report functions; synthetic baselines
          are excluded.
        </p>
        <div className="row-actions">
          <a
            className="btn secondary"
            href={exportUrl()}
            target="_blank"
            rel="noreferrer"
          >
            Download JSON snapshot
          </a>
        </div>
      </div>
    </div>
  );
}
