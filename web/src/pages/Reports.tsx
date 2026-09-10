import { Download, FileJson, RefreshCw } from "lucide-react";
import { useState } from "react";
import { api, ApiRequestError, exportUrl } from "../api/client";
import { useAsync } from "../lib/useAsync";
import { CaveatBanner } from "../components/CaveatBanner";
import { ErrorState, Loading } from "../components/States";
import {
  InlineNotice,
  Metric,
  MetricGroup,
  PageHeader,
  Panel,
  SectionHeader,
} from "../components/Primitives";
import { formatDate } from "../lib/format";

export function Reports() {
  const meta = useAsync((signal) => api.meta(signal), []);
  const [regenerating, setRegenerating] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  if (meta.loading) return <Loading label="Loading report provenance…" />;
  if (meta.error)
    return <ErrorState error={meta.error} onRetry={meta.reload} />;
  const obs = meta.data!.observability;
  async function regenerate() {
    setRegenerating(true);
    setMessage(null);
    setError(null);
    try {
      const result = await api.regenerateReport();
      setMessage(`${result.path} · ${result.bytes} bytes`);
    } catch (caught) {
      setError(
        caught instanceof ApiRequestError ? caught.message : String(caught),
      );
    } finally {
      setRegenerating(false);
    }
  }
  return (
    <div>
      <PageHeader
        eyebrow="Tools"
        title="Reports"
        description="Regenerate a server-owned snapshot or export the currently supported JSON projection."
      />
      <CaveatBanner caveat={meta.data?.notes?.trust} />
      <MetricGroup>
        <Metric
          label="Persisted runs"
          value={obs.total_runs}
          detail="report source"
          mono
        />
        <Metric
          label="Agents"
          value={meta.data!.models.length}
          detail="real model identities"
          mono
        />
        <Metric
          label="Tasks"
          value={meta.data!.n_tasks}
          detail="task pack"
          mono
        />
        <Metric
          label="Latest evidence"
          value={formatDate(obs.last_created_at)}
          detail="database timestamp"
          mono
        />
      </MetricGroup>
      <div className="split-layout">
        <Panel>
          <SectionHeader
            title="Report snapshot"
            description="The report is generated from the current database and keeps mixed-version refusal behavior."
          />
          <dl className="kv">
            <dt>earliest run</dt>
            <dd>{formatDate(obs.first_created_at)}</dd>
            <dt>latest run</dt>
            <dd>{formatDate(obs.last_created_at)}</dd>
            <dt>patch capture</dt>
            <dd>
              {obs.runs_with_patch}/{obs.total_runs}
            </dd>
            <dt>test-result coverage</dt>
            <dd>
              {obs.runs_with_test_results}/{obs.total_runs}
            </dd>
            <dt>test-result rows</dt>
            <dd>{obs.test_result_rows}</dd>
          </dl>
          <p className="note muted">
            This is a point-in-time artifact. The app view and the generated
            HTML should be treated as projections of the same local evidence
            source, not as new benchmark truth. Report generation time is not
            provided by the API.
          </p>
        </Panel>
        <Panel>
          <SectionHeader
            title="Regenerate"
            description="Write the existing leaderboard HTML projection through the backend report flow."
          />
          <button
            className="btn"
            type="button"
            disabled={regenerating}
            onClick={regenerate}
          >
            <RefreshCw size={15} aria-hidden="true" />
            {regenerating ? "Regenerating…" : "Regenerate report"}
          </button>
          {message && <InlineNotice tone="success">{message}</InlineNotice>}
          {error && <InlineNotice tone="danger">{error}</InlineNotice>}
        </Panel>
      </div>
      <Panel>
        <SectionHeader
          title="Export"
          description="Only formats currently exposed by the API are shown here."
        />
        <a
          className="btn btn-secondary"
          href={exportUrl()}
          target="_blank"
          rel="noreferrer"
        >
          <FileJson size={15} aria-hidden="true" /> Download JSON snapshot{" "}
          <Download size={14} aria-hidden="true" />
        </a>
        <p className="note muted">
          CSV and HTML download actions are not shown because the current API
          exposes JSON export only. Report regeneration remains available
          separately.
        </p>
      </Panel>
    </div>
  );
}
