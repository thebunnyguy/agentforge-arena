import { ArrowLeft, History } from "lucide-react";
import { Link, useParams } from "react-router-dom";
import {
  InlineNotice,
  Metric,
  MetricGroup,
  PageHeader,
  Panel,
  SectionHeader,
} from "../components/Primitives";
import { WilsonBar } from "../components/WilsonBar";
import { DomainProfile } from "../components/benchmarks/DomainComparison";
import { recordedVersionText } from "../components/benchmarks/TaskMatrix";
import {
  BenchmarkNotFound,
  CaveatNotice,
  ExternalLink,
  ReleaseStatusBadge,
  TableScroll,
  WilsonInterval,
} from "../components/benchmarks/shared";
import { benchmarkReleases } from "../data/benchmark-releases";
import {
  formatRunWindow,
  fractionText,
  fullTimeoutsText,
  gigabytesText,
  intervalText,
  modelCaveats,
  plainRankingText,
  rankText,
  shortDigest,
  timeoutsText,
} from "../lib/benchmarkDisplay";
import {
  evidenceUrl,
  findModel,
  findRelease,
  isCampaignMethodology,
  modelPath,
  releasePath,
  STATUS_DESCRIPTIONS,
  type BenchmarkRelease,
  type ReleaseModel,
} from "../lib/benchmarkReleases";
import { fixed, pct } from "../lib/format";

/** Links to the release's other models (navigation only on activation). */
function ModelSwitcher({
  release,
  model,
}: {
  release: BenchmarkRelease;
  model: ReleaseModel;
}) {
  return (
    <nav className="model-switcher" aria-labelledby="model-switch-label">
      <span className="fact-label" id="model-switch-label">
        Models in this release
      </span>
      <ul className="chip-list">
        {release.models.map((option) => (
          <li key={option.id}>
            <Link
              className="version-chip model-chip"
              to={modelPath(release, option.id)}
              aria-current={option.id === model.id ? "page" : undefined}
              data-model={option.id}
            >
              {option.display_name}
              {option.identity.ollama_tag !== option.display_name && (
                <span className="chip-sub">{option.identity.ollama_tag}</span>
              )}
            </Link>
          </li>
        ))}
      </ul>
    </nav>
  );
}

function OverallMetrics({
  release,
  model,
}: {
  release: BenchmarkRelease;
  model: ReleaseModel;
}) {
  const t = model.totals;
  const coverage = (
    <Metric
      label="Coverage"
      value={fractionText(
        model.coverage.tasks_with_evidence,
        model.coverage.tasks_total,
      )}
      detail="tasks with evidence"
      mono
    />
  );
  const methodology = release.methodology;
  const interval =
    t.pass_rate !== undefined &&
    t.wilson_low !== undefined &&
    t.wilson_high !== undefined
      ? { pHat: t.pass_rate, low: t.wilson_low, high: t.wilson_high }
      : null;
  // An unranked release (the historical record) or a model without a served
  // interval shows counts only: no rank, pass rate or interval.
  if (!release.ranked || !interval)
    return (
      <MetricGroup>
        <Metric
          label="Passes / runs"
          value={fractionText(t.passes, t.runs)}
          detail="as recorded"
          mono
        />
        <Metric
          label="Timeouts"
          value={t.timeouts}
          detail={`${t.voided} voided runs`}
          mono
        />
        <Metric
          label="Mean final score"
          value={fixed(t.mean_final_score, 3)}
          detail={
            isCampaignMethodology(methodology)
              ? "over all runs"
              : `scoring formula ${methodology.scoring_formula.join(", ")}`
          }
          mono
        />
        {coverage}
      </MetricGroup>
    );
  const text = intervalText(interval.low, interval.high);
  return (
    <>
      <MetricGroup>
        {model.rank && (
          <Metric
            label="Rank"
            value={`${rankText(model)} of ${release.counts.models_ranked}`}
            detail={
              isCampaignMethodology(methodology)
                ? plainRankingText(methodology.ranking_method)
                : undefined
            }
            mono
          />
        )}
        <Metric
          label="Passes"
          value={fractionText(t.passes, t.runs)}
          detail="runs passed"
          mono
        />
        <Metric
          label="Pass rate"
          value={pct(interval.pHat, 1)}
          detail={`Wilson 95% ${text}`}
          mono
        />
        <Metric
          label="Mean final score"
          value={fixed(t.mean_final_score, 3)}
          detail="over all runs"
          mono
        />
      </MetricGroup>
      <MetricGroup>
        <Metric
          label="Timeouts"
          value={t.timeouts}
          detail={
            t.request_timeout_hits !== undefined
              ? fullTimeoutsText(t.request_timeout_hits)
              : undefined
          }
          mono
        />
        <Metric label="Agent errors" value={t.agent_errors ?? "—"} mono />
        {coverage}
        <Metric label="Voided runs" value={t.voided} mono />
      </MetricGroup>
      <Panel className="panel-accent">
        <SectionHeader
          title="Pass rate and its interval"
          description={`${pct(interval.pHat, 1)} observed; Wilson 95% interval ${text}. The range is part of the result.`}
        />
        <div className="bench-overall-plot">
          <WilsonBar
            pHat={interval.pHat}
            low={interval.low}
            high={interval.high}
            width={320}
            showLabel={false}
          />
          <p className="bench-overall-text mono">
            <strong>{pct(interval.pHat, 1)}</strong>{" "}
            <span>Wilson 95% {text}</span>
          </p>
        </div>
      </Panel>
    </>
  );
}

function DocumentedFacts({ model }: { model: ReleaseModel }) {
  if (model.documented_facts.length === 0) return null;
  return (
    <Panel>
      <SectionHeader
        title="Documented in the campaign report"
        description="These figures come from the campaign report, not from the committed result artifacts behind the numbers above."
      />
      <ul className="documented-facts">
        {model.documented_facts.map((fact) => (
          <li key={fact.id}>
            <div className="reading-head">
              <span className="badge neutral">documented</span>
              <strong>{fact.label}</strong>
              <span className="mono">{fractionText(fact.value, fact.of)}</span>
            </div>
            <p className="notice-source">
              Source: <span className="mono">{fact.source}</span>
            </p>
          </li>
        ))}
      </ul>
    </Panel>
  );
}

function Identity({
  release,
  model,
}: {
  release: BenchmarkRelease;
  model: ReleaseModel;
}) {
  const id = model.identity;
  const campaign = isCampaignMethodology(release.methodology);
  const generation = model.generation;
  return (
    <Panel>
      <SectionHeader
        title="Identity"
        description={
          campaign
            ? "The exact model that ran: its pinned registry digest was checked against the local Ollama inventory at every submission and acceptance."
            : "What the historical record identifies about this model."
        }
      />
      <dl className="kv model-identity">
        <dt>Ollama tag</dt>
        <dd>{id.ollama_tag}</dd>
        <dt>display name</dt>
        <dd>{model.display_name}</dd>
        <dt>digest</dt>
        <dd className="digest-value">
          {id.digest ?? "not recorded"}
          {!id.digest && id.digest_prefix_documented && (
            <span className="detail-sub">
              short prefix {id.digest_prefix_documented} documented in the
              README
            </span>
          )}
        </dd>
        {campaign && (
          <>
            <dt>family</dt>
            <dd>{id.family ?? "not recorded"}</dd>
            <dt>parameter count</dt>
            <dd>{id.parameter_size ?? "not recorded"}</dd>
            <dt>quantization</dt>
            <dd>{id.quantization ?? "not recorded"}</dd>
            <dt>format</dt>
            <dd>{id.format ?? "not recorded"}</dd>
            <dt>download size</dt>
            <dd>{gigabytesText(id.download_bytes)}</dd>
            <dt>server default context length</dt>
            <dd>
              {id.context_length !== null && id.context_length !== undefined
                ? id.context_length
                : "not reported"}
            </dd>
            <dt>Ollama version</dt>
            <dd>{id.ollama_version ?? "not recorded"}</dd>
            <dt>digest verified</dt>
            <dd>
              {id.digest_verified_cells !== undefined
                ? `at ${fractionText(id.digest_verified_cells, model.coverage.tasks_total)} cells`
                : "not recorded"}
            </dd>
          </>
        )}
        {!campaign && (
          <>
            <dt>documented generation</dt>
            <dd>
              {generation
                ? [
                    `temperature ${generation.temperature ?? "not recorded"}`,
                    `base seed ${generation.base_seed ?? "not recorded"}`,
                    `request timeout ${generation.request_timeout_s !== null ? `${generation.request_timeout_s} s` : "not recorded"}`,
                    `Ollama ${generation.ollama_version ?? "version not recorded"}`,
                  ].join(" · ")
                : "not documented for this model"}
            </dd>
          </>
        )}
        {model.receipt && (
          <>
            <dt>receipt</dt>
            <dd>
              <ExternalLink href={evidenceUrl(release, model.receipt)}>
                {model.receipt}
              </ExternalLink>
            </dd>
          </>
        )}
        <dt>run window</dt>
        <dd>{formatRunWindow(model.run_window)}</dd>
        {model.tooling_heads && model.tooling_heads.length > 0 && (
          <>
            <dt>tooling head</dt>
            <dd>{model.tooling_heads.join(", ")}</dd>
          </>
        )}
      </dl>
    </Panel>
  );
}

function TaskResults({
  release,
  model,
}: {
  release: BenchmarkRelease;
  model: ReleaseModel;
}) {
  const campaign = release.ranked;
  const pack = new Map(release.task_pack.map((task) => [task.task_id, task]));
  const headingId = "model-tasks-heading";
  return (
    <Panel>
      <SectionHeader
        id={headingId}
        title="Task results"
        description={
          campaign
            ? `All ${model.tasks.length} tasks at their pinned versions, ${release.counts.repetitions} runs each. Task links open the live task page.`
            : `All ${model.tasks.length} tasks as recorded, at the task version each run used.`
        }
      />
      <TableScroll labelledBy={headingId}>
        <table className="data model-tasks" aria-labelledby={headingId}>
          <thead>
            <tr>
              <th scope="col" className="sticky-id">
                task
              </th>
              <th scope="col">version</th>
              <th scope="col" className="num">
                passes / runs
              </th>
              {campaign && (
                <th scope="col" className="num">
                  pass rate
                </th>
              )}
              {campaign && <th scope="col">Wilson 95%</th>}
              <th scope="col" className="num">
                timeouts{campaign ? " (full)" : ""}
              </th>
              {campaign ? (
                <>
                  <th scope="col" className="num">
                    mean final score
                  </th>
                  <th scope="col">evaluation</th>
                </>
              ) : (
                <th scope="col" className="num">
                  voided
                </th>
              )}
            </tr>
          </thead>
          <tbody>
            {model.tasks.map((result) => {
              const task = pack.get(result.task_id);
              return (
                <tr key={result.task_id}>
                  <th
                    scope="row"
                    className="primary-cell row-head sticky-id mono"
                  >
                    {campaign ? (
                      <Link to={`/task/${encodeURIComponent(result.task_id)}`}>
                        {result.task_id}
                      </Link>
                    ) : (
                      result.task_id
                    )}
                  </th>
                  <td className="mono">
                    {!campaign && task
                      ? recordedVersionText(task)
                      : result.task_version}
                  </td>
                  <td className="num mono">
                    {result.evidence &&
                    result.passes !== undefined &&
                    result.runs !== undefined
                      ? fractionText(result.passes, result.runs)
                      : (result.note ?? "no evidence")}
                  </td>
                  {campaign && (
                    <td className="num mono">
                      {result.pass_rate !== undefined
                        ? pct(result.pass_rate, 1)
                        : "—"}
                    </td>
                  )}
                  {campaign && (
                    <td>
                      {result.pass_rate !== undefined &&
                      result.wilson_low !== undefined &&
                      result.wilson_high !== undefined ? (
                        <WilsonInterval
                          pHat={result.pass_rate}
                          low={result.wilson_low}
                          high={result.wilson_high}
                          width={120}
                        />
                      ) : (
                        "—"
                      )}
                    </td>
                  )}
                  <td className="num mono">
                    {timeoutsText(result.timeouts, result.request_timeout_hits)}
                  </td>
                  {campaign ? (
                    <>
                      <td className="num mono">
                        {result.mean_final_score !== undefined
                          ? fixed(result.mean_final_score, 3)
                          : "—"}
                      </td>
                      <td className="mono" title={result.evaluation_id}>
                        {result.evaluation_id
                          ? shortDigest(result.evaluation_id, 8)
                          : "—"}
                      </td>
                    </>
                  ) : (
                    <td className="num mono">{result.voided ?? "—"}</td>
                  )}
                </tr>
              );
            })}
          </tbody>
        </table>
      </TableScroll>
    </Panel>
  );
}

function ModelView({
  release,
  model,
}: {
  release: BenchmarkRelease;
  model: ReleaseModel;
}) {
  const caveats = modelCaveats(release, model.caveat_ids);
  return (
    <div className="bench-page">
      <PageHeader
        eyebrow={release.short_title}
        title={model.display_name}
        description={
          <>
            Ollama tag <span className="mono">{model.identity.ollama_tag}</span>
          </>
        }
        actions={
          <Link className="btn btn-secondary" to={releasePath(release)}>
            <ArrowLeft size={15} aria-hidden="true" /> Back to{" "}
            {release.short_title}
          </Link>
        }
      />
      <p className="release-status bench-status-line">
        <ReleaseStatusBadge status={release.status} />
        <span className="release-status-text">
          {release.short_title}: {STATUS_DESCRIPTIONS[release.status]}
        </span>
      </p>
      <ModelSwitcher release={release} model={model} />
      {release.comparability && (
        <InlineNotice tone="warn">
          <History size={16} aria-hidden="true" />
          <span>{release.comparability}</span>
        </InlineNotice>
      )}
      {caveats.map((caveat) => (
        <CaveatNotice caveat={caveat} tone="warn" key={caveat.id} />
      ))}
      <OverallMetrics release={release} model={model} />
      <DocumentedFacts model={model} />
      <Identity release={release} model={model} />
      {model.domains.length > 0 && (
        <Panel>
          <SectionHeader
            title="Domain profile"
            description="Weighted pooled pass rate per domain as computed by the kernel, with its Wilson 95% interval, effective sample size (n_eff), tasks and runs."
          />
          <DomainProfile domains={model.domains} />
        </Panel>
      )}
      <TaskResults release={release} model={model} />
    </div>
  );
}

export function BenchmarkModel() {
  const { releaseId, modelId } = useParams();
  const release = findRelease(benchmarkReleases, releaseId);
  if (!release)
    return (
      <BenchmarkNotFound
        title="Release not found"
        message={
          <>
            No benchmark release has the id{" "}
            <span className="mono">{releaseId}</span>.
          </>
        }
        backTo="/benchmarks"
        backLabel="Open the current benchmark release"
      />
    );
  const model = findModel(release, modelId);
  if (!model)
    return (
      <BenchmarkNotFound
        title="Model not found"
        message={
          <>
            {release.short_title} has no model{" "}
            <span className="mono">{modelId}</span>.
          </>
        }
        backTo={releasePath(release)}
        backLabel={`Back to ${release.short_title}`}
      />
    );
  return (
    <ModelView
      key={`${release.id}/${model.id}`}
      release={release}
      model={model}
    />
  );
}
