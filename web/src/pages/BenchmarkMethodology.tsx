import { ArrowLeft, History, MapPin } from "lucide-react";
import { Link, useParams } from "react-router-dom";
import {
  InlineNotice,
  PageHeader,
  Panel,
  SectionHeader,
} from "../components/Primitives";
import { DatasetSources } from "../components/benchmarks/EvidencePanel";
import {
  BenchmarkNotFound,
  ExternalLink,
  ReleaseStatusBadge,
  TableScroll,
} from "../components/benchmarks/shared";
import { benchmarkReleases } from "../data/benchmark-releases";
import {
  formatReleaseDate,
  formatRunWindow,
  releaseDateLabel,
  repositoryCommitUrl,
  repositoryTreeUrl,
  seedsText,
  shortDigest,
} from "../lib/benchmarkDisplay";
import {
  findRelease,
  isCampaignMethodology,
  releasePath,
  STATUS_DESCRIPTIONS,
  type BenchmarkRelease,
  type CampaignMethodology,
  type HistoricalMethodology,
} from "../lib/benchmarkReleases";

const orNotRecorded = (value: string | number | null | undefined) =>
  value === null || value === undefined ? "not recorded" : String(value);

function ReleaseFacts({ release }: { release: BenchmarkRelease }) {
  const { ref, commit } = release.repository;
  return (
    <Panel>
      <SectionHeader title="Release" />
      <dl className="kv">
        <dt>release id</dt>
        <dd>{release.id}</dd>
        <dt>status</dt>
        <dd className="release-status">
          <ReleaseStatusBadge status={release.status} />
          <span className="release-status-text">
            {STATUS_DESCRIPTIONS[release.status]}
          </span>
        </dd>
        <dt>{releaseDateLabel(release.status).toLowerCase()}</dt>
        <dd>{formatReleaseDate(release.released_at)}</dd>
        <dt>git ref</dt>
        <dd>
          {ref ? (
            <ExternalLink href={repositoryTreeUrl(release)}>{ref}</ExternalLink>
          ) : (
            "not recorded"
          )}
        </dd>
        <dt>commit</dt>
        <dd>
          {commit ? (
            <ExternalLink href={repositoryCommitUrl(release)}>
              {commit}
            </ExternalLink>
          ) : (
            "not recorded"
          )}
        </dd>
        <dt>campaign id</dt>
        <dd>{release.campaign_id ?? "none (not a campaign release)"}</dd>
      </dl>
    </Panel>
  );
}

function CampaignSections({
  release,
  methodology,
}: {
  release: BenchmarkRelease;
  methodology: CampaignMethodology;
}) {
  const environment = release.environment;
  const runtime = methodology.runtime_release;
  return (
    <>
      <div className="split-layout">
        <div>
          <ReleaseFacts release={release} />
          <Panel>
            <SectionHeader title="Generation" />
            <dl className="method-list method-list-stack">
              <div>
                <dt>temperature</dt>
                <dd className="mono">{methodology.temperature}</dd>
              </div>
              <div>
                <dt>seeds</dt>
                <dd>
                  <span className="mono">{seedsText(methodology.seeds)}</span>{" "}
                  (base seed {methodology.base_seed})
                </dd>
              </div>
              <div>
                <dt>seed policy</dt>
                <dd>{methodology.seed_policy}</dd>
              </div>
              <div>
                <dt>request timeout</dt>
                <dd className="mono">{methodology.request_timeout_s} s</dd>
              </div>
              <div>
                <dt>request</dt>
                <dd>{methodology.request}</dd>
              </div>
              <div>
                <dt>repetitions</dt>
                <dd className="mono">{methodology.repetitions}</dd>
              </div>
              <div>
                <dt>mode</dt>
                <dd>
                  <span className="mono">{methodology.mode}</span> ·{" "}
                  {methodology.plan_kind}
                  {methodology.one_model_at_a_time && " · one model at a time"}
                </dd>
              </div>
            </dl>
          </Panel>
          <Panel>
            <SectionHeader title="Evaluation identity" />
            <dl className="method-list method-list-stack">
              <div>
                <dt>granularity</dt>
                <dd>{methodology.evaluation_granularity}</dd>
              </div>
              <div>
                <dt>evidence class</dt>
                <dd className="mono">{methodology.evidence_scope.class}</dd>
              </div>
              <div>
                <dt>ownership</dt>
                <dd>{methodology.evidence_scope.ownership}</dd>
              </div>
              <div>
                <dt>excludes</dt>
                <dd>
                  <ul className="plain-list">
                    {methodology.evidence_scope.excludes.map((item) => (
                      <li key={item}>{item}</li>
                    ))}
                  </ul>
                </dd>
              </div>
              <div>
                <dt>official rule</dt>
                <dd>{methodology.official_rule}</dd>
              </div>
              <div>
                <dt>minimum ranked</dt>
                <dd>
                  <span className="mono">
                    {methodology.minimum_ranked_models}
                  </span>{" "}
                  models
                </dd>
              </div>
              <div id="ranking">
                <dt>ranking</dt>
                <dd>{methodology.ranking_method}</dd>
              </div>
            </dl>
          </Panel>
        </div>
        <div>
          <Panel>
            <SectionHeader title="Runtime release" />
            <dl className="kv kv-stacked">
              <dt>tag</dt>
              <dd>{runtime.tag}</dd>
              <dt>commit</dt>
              <dd>{runtime.commit}</dd>
              <dt>paths</dt>
              <dd>
                <span className="tag-list">
                  {runtime.paths.map((path) => (
                    <span className="tag" key={path}>
                      {path}
                    </span>
                  ))}
                </span>
              </dd>
            </dl>
            <p className="note">{runtime.rule}</p>
          </Panel>
          {environment && (
            <Panel>
              <SectionHeader title="Environment" />
              <dl className="kv kv-stacked">
                <dt>hardware</dt>
                <dd>
                  {environment.hardware.chip} ·{" "}
                  {environment.hardware.architecture} ·{" "}
                  {environment.hardware.memory} · {environment.hardware.os}
                </dd>
                <dt>hardware source</dt>
                <dd className="prose-value">{environment.hardware.source}</dd>
                <dt>Ollama version</dt>
                <dd>{environment.ollama_version}</dd>
                <dt>backend</dt>
                <dd>
                  {methodology.backend.kind} at {methodology.backend.base_url}
                </dd>
                <dt>hosted API</dt>
                <dd className="prose-value">{environment.hosted_api}</dd>
                {release.headline && (
                  <>
                    <dt>paid API cost</dt>
                    <dd className="prose-value">
                      {release.headline.paid_api_cost.text}
                      <span className="detail-sub">
                        Source: {release.headline.paid_api_cost.source}
                      </span>
                    </dd>
                  </>
                )}
              </dl>
              <InlineNotice tone="info">
                <MapPin size={16} aria-hidden="true" />
                <span>{environment.scope}</span>
              </InlineNotice>
            </Panel>
          )}
          <Panel>
            <SectionHeader title="Hashes" />
            <dl className="kv kv-stacked hash-list">
              <dt>manifest (canonical JSON sha256)</dt>
              <dd>{methodology.manifest_sha256}</dd>
              <dt>ledger sha256</dt>
              <dd>{methodology.ledger_sha256}</dd>
              <dt>historical evidence</dt>
              <dd>
                {methodology.historical_evidence.path}
                <span className="detail-sub">
                  sha256 {methodology.historical_evidence.sha256}
                </span>
              </dd>
            </dl>
            <p className="note muted">
              The manifest hash is taken over its canonical JSON form (sorted
              keys, compact separators), so it differs from the file's own
              sha256 listed under dataset sources.
            </p>
          </Panel>
        </div>
      </div>
      <Panel>
        <SectionHeader
          id="methodology-identity-heading"
          title="Model identity"
          description={methodology.model_identity_source}
        />
        <TableScroll labelledBy="methodology-identity-heading">
          <table
            className="data method-identity"
            aria-labelledby="methodology-identity-heading"
          >
            <thead>
              <tr>
                <th scope="col" className="sticky-id">
                  model
                </th>
                <th scope="col">Ollama tag</th>
                <th scope="col">pinned digest</th>
              </tr>
            </thead>
            <tbody>
              {release.models.map((model) => (
                <tr key={model.id}>
                  <th scope="row" className="primary-cell row-head sticky-id">
                    {model.display_name}
                  </th>
                  <td className="mono">{model.identity.ollama_tag}</td>
                  <td className="mono digest-value">
                    {model.identity.digest ?? "not recorded"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </TableScroll>
      </Panel>
    </>
  );
}

function HistoricalSections({
  release,
  methodology,
}: {
  release: BenchmarkRelease;
  methodology: HistoricalMethodology;
}) {
  return (
    <div className="split-layout">
      <div>
        <ReleaseFacts release={release} />
        <Panel>
          <SectionHeader
            id="methodology-generation-heading"
            title="Generation (documented per group)"
            description="Settings documented for groups of runs; the record keeps no per-run generation configuration."
          />
          <TableScroll labelledBy="methodology-generation-heading">
            <table
              className="data generation-groups"
              aria-labelledby="methodology-generation-heading"
            >
              <thead>
                <tr>
                  <th scope="col" className="sticky-id">
                    group
                  </th>
                  <th scope="col" className="num">
                    temperature
                  </th>
                  <th scope="col" className="num">
                    base seed
                  </th>
                  <th scope="col" className="num">
                    request timeout
                  </th>
                  <th scope="col">Ollama</th>
                  <th scope="col">models</th>
                </tr>
              </thead>
              <tbody>
                {methodology.generation_groups.map((group) => (
                  <tr key={group.group}>
                    <th scope="row" className="row-head sticky-id mono">
                      {group.group}
                    </th>
                    <td className="num mono">
                      {orNotRecorded(group.temperature)}
                    </td>
                    <td className="num mono">
                      {orNotRecorded(group.base_seed)}
                    </td>
                    <td className="num mono">
                      {group.request_timeout_s === null
                        ? "not recorded"
                        : `${group.request_timeout_s} s`}
                    </td>
                    <td className="mono">
                      {orNotRecorded(group.ollama_version)}
                    </td>
                    <td>{group.models}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </TableScroll>
          <h3>Sources</h3>
          <ul className="plain-list">
            {methodology.generation_sources.map((source) => (
              <li key={source} className="mono">
                {source}
              </li>
            ))}
          </ul>
        </Panel>
      </div>
      <div>
        <Panel>
          <SectionHeader title="Record" />
          <dl className="kv kv-stacked">
            <dt>scoring formula</dt>
            <dd>{methodology.scoring_formula.join(", ")}</dd>
            <dt>run window</dt>
            <dd>{formatRunWindow(methodology.run_window)}</dd>
            <dt>task versions changed</dt>
            <dd>
              {methodology.task_versions_changed} of {release.task_pack.length}{" "}
              tasks since this record
            </dd>
          </dl>
        </Panel>
        <Panel>
          <SectionHeader title="Not recorded" />
          <ul className="not-recorded">
            {methodology.not_recorded.map((item) => (
              <li key={item}>
                <span className="badge neutral">not recorded</span>
                <span>{item}</span>
              </li>
            ))}
          </ul>
        </Panel>
      </div>
    </div>
  );
}

function TaskPack({ release }: { release: BenchmarkRelease }) {
  const campaign = isCampaignMethodology(release.methodology);
  return (
    <Panel>
      <SectionHeader
        id="methodology-task-pack-heading"
        title="Task pack"
        description={
          campaign
            ? `${release.task_pack.length} tasks, each pinned by version and content digest.`
            : `${release.task_pack.length} tasks at the version each recorded run used, and the version the task has now.`
        }
      />
      <TableScroll labelledBy="methodology-task-pack-heading">
        <table
          className="data task-pack"
          aria-labelledby="methodology-task-pack-heading"
        >
          <thead>
            <tr>
              <th scope="col" className="sticky-id">
                task
              </th>
              <th scope="col">{campaign ? "version" : "recorded version"}</th>
              {campaign ? (
                <>
                  <th scope="col">digest</th>
                  <th scope="col">domains (weight)</th>
                  <th scope="col">activity</th>
                  <th scope="col" className="num">
                    timeout
                  </th>
                  <th scope="col">since pre-Phase-0</th>
                </>
              ) : (
                <>
                  <th scope="col">current version</th>
                  <th scope="col">since this record</th>
                </>
              )}
            </tr>
          </thead>
          <tbody>
            {release.task_pack.map((task) => (
              <tr key={task.task_id}>
                <th
                  scope="row"
                  className="primary-cell row-head sticky-id mono"
                >
                  {task.task_id}
                </th>
                <td className="mono">{task.task_version}</td>
                {campaign ? (
                  <>
                    <td className="mono" title={task.task_digest ?? ""}>
                      {shortDigest(task.task_digest)}
                    </td>
                    <td>
                      <span className="tag-list">
                        {task.domains.map((domain) => (
                          <span className="tag" key={domain.domain}>
                            {domain.domain} · {String(domain.weight)}
                          </span>
                        ))}
                      </span>
                    </td>
                    <td className="mono">{task.activity ?? "—"}</td>
                    <td className="num mono">
                      {task.timeout_s !== null ? `${task.timeout_s} s` : "—"}
                    </td>
                  </>
                ) : (
                  <td className="mono">{task.current_version ?? "—"}</td>
                )}
                <td>
                  {task.version_changed_since_pre_phase0 ? (
                    <span className="badge warn">changed</span>
                  ) : (
                    <span className="badge neutral">unchanged</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </TableScroll>
    </Panel>
  );
}

export function BenchmarkMethodology() {
  const { releaseId } = useParams();
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
  const methodology = release.methodology;
  return (
    <div className="bench-page">
      <PageHeader
        eyebrow={release.short_title}
        title="Methodology & provenance"
        description={`How ${release.status === "HISTORICAL" ? `the ${release.short_title} record` : release.short_title} was produced, and what it can be checked against.`}
        actions={
          <Link className="btn btn-secondary" to={releasePath(release)}>
            <ArrowLeft size={15} aria-hidden="true" /> Back to{" "}
            {release.short_title}
          </Link>
        }
      />
      {release.comparability && (
        <InlineNotice tone="warn">
          <History size={16} aria-hidden="true" />
          <span>{release.comparability}</span>
        </InlineNotice>
      )}
      {isCampaignMethodology(methodology) ? (
        <CampaignSections release={release} methodology={methodology} />
      ) : (
        <HistoricalSections release={release} methodology={methodology} />
      )}
      <TaskPack release={release} />
      <Panel>
        <SectionHeader
          title="Dataset sources"
          description="This page reads a dataset generated from committed evidence; it recomputes nothing."
        />
        <DatasetSources release={release} />
      </Panel>
    </div>
  );
}
