// Benchmark releases: the frozen, published results of a campaign (or the
// read-only historical record), shipped with the UI as static datasets that
// `python3 -m afa_campaign release-data` generates from the committed evidence.
// Display-only: every number here was produced by the campaign tooling or the
// kernel; nothing in the UI recomputes a rate, interval or rank.
//
// This module is side-effect free (no import.meta, no window, no JSON imports)
// so the logic tests can load it under Node.

export const RELEASE_STATUSES = [
  "OFFICIAL",
  "EXPERIMENTAL",
  "SUPERSEDED",
  "HISTORICAL",
] as const;
export type ReleaseStatus = (typeof RELEASE_STATUSES)[number];

export interface ReleaseRepository {
  url: string | null;
  ref: string | null;
  commit: string | null;
}

export interface ReleaseCounts {
  models: number;
  models_ranked: number;
  tasks: number;
  repetitions: number;
  evaluations: number | null;
  runs: number;
  runs_per_model: number;
}

export interface SourcedText {
  text: string;
  source: string;
}

export interface ReleaseHeadline {
  inference: string;
  paid_api_cost: SourcedText;
}

export interface ReleaseEnvironment {
  scope: string;
  hardware: {
    chip: string;
    architecture: string;
    memory: string;
    os: string;
    source: string;
  };
  hosted_api: string;
  ollama_version: string;
  backend: string;
}

export interface RuntimeRelease {
  tag: string;
  commit: string;
  paths: string[];
  rule?: string;
}

export interface CampaignMethodology {
  campaign_id: string;
  campaign_title: string;
  plan_kind: string;
  mode: string;
  backend: { kind: string; base_url: string };
  ollama_version: string;
  temperature: number;
  base_seed: number;
  seeds: number[];
  seed_policy: string;
  request: string;
  request_timeout_s: number;
  repetitions: number;
  evaluation_granularity: string;
  official_rule: string;
  minimum_ranked_models: number;
  ranking_method: string;
  one_model_at_a_time: boolean;
  runtime_release: RuntimeRelease & { rule: string };
  manifest_sha256: string;
  ledger_sha256: string;
  historical_evidence: { path: string; sha256: string };
  evidence_scope: { class: string; ownership: string; excludes: string[] };
  model_identity_source: string;
}

export interface GenerationGroup {
  group: string;
  temperature: number | null;
  base_seed: number | null;
  request_timeout_s: number | null;
  ollama_version: string | null;
  models: string;
}

export interface HistoricalMethodology {
  scoring_formula: string[];
  generation_groups: GenerationGroup[];
  generation_sources: string[];
  not_recorded: string[];
  task_versions_changed: number;
  run_window: { started_at: string; finished_at: string };
}

export interface NotClaimed {
  property: string;
  status: string;
  note: string;
  source: string;
}

export interface ReleaseIntegrity {
  complete: boolean;
  official: boolean;
  problems: string[];
  warnings: string[];
  planned_runs: number;
  accepted_runs: number;
  valid_runs: number;
  planned_evaluations: number;
  accepted_evaluations: number;
  models_total: number;
  models_complete: number;
  tasks_total: number;
  task_coverage_min: number;
  missing_runs: number;
  missing_evaluations: number;
  extra_runs: number;
  untracked_evaluations: number;
  disowned_evaluations: number;
  superseded_entries: number;
  voided_runs: number;
  evidence_classes: {
    real: number;
    synthetic: number;
    legacy: number;
    conflict: number;
  };
  backend_kind: string;
  task_pins: { tasks: number; basis: string };
  model_identity: {
    cells_at_pinned_digest: number;
    cells_total: number;
    ollama_version: string;
  };
  runtime: RuntimeRelease & {
    launches_with_code_check: number;
    launches: number;
  };
  historical_evidence_unchanged: boolean;
  not_claimed: NotClaimed[];
}

export interface ReleaseTaskPackEntry {
  task_id: string;
  task_version: string;
  task_digest: string | null;
  domains: { domain: string; weight: number }[];
  activity: string | null;
  timeout_s: number | null;
  version_changed_since_pre_phase0: boolean;
  /** Historical releases: the version the task has in the comparison release. */
  current_version?: string;
}

export interface ReleaseDomainResult {
  domain: string;
  pooled_pass_rate: number;
  wilson_low: number;
  wilson_high: number;
  n_eff: number;
  n_tasks: number;
  n_runs: number;
  stability: number;
  displayable: boolean;
}

/** One model × task cell. Official releases carry the kernel aggregate
 * (pass rate, Wilson interval); historical releases only recorded counts. */
export interface ReleaseTaskResult {
  task_id: string;
  task_version: string;
  evidence: boolean;
  note?: string;
  runs?: number;
  passes?: number;
  timeouts?: number;
  voided?: number;
  pass_rate?: number;
  wilson_low?: number;
  wilson_high?: number;
  mean_final_score?: number;
  request_timeout_hits?: number;
  agent_errors?: number;
  provisional?: boolean;
  evaluation_id?: string;
}

export interface ReleaseModelTotals {
  runs: number;
  passes: number;
  timeouts: number;
  voided: number;
  mean_final_score: number;
  pass_rate?: number;
  wilson_low?: number;
  wilson_high?: number;
  request_timeout_hits?: number;
  agent_errors?: number;
}

export interface ReleaseModelIdentity {
  ollama_tag: string;
  digest: string | null;
  family?: string;
  parameter_size?: string;
  quantization?: string;
  format?: string;
  download_bytes?: number;
  context_length?: number | null;
  digest_verified_cells?: number;
  ollama_version?: string;
  digest_prefix_documented?: string | null;
}

export interface DocumentedFact {
  id: string;
  model: string | null;
  label: string;
  value: number;
  of: number;
  source: string;
}

export interface ReleaseModel {
  id: string;
  display_name: string;
  phase?: string;
  optional?: boolean;
  state: string;
  ranked: boolean;
  classification?: string | null;
  rank: { low: number; high: number; provisional: boolean } | null;
  identity: ReleaseModelIdentity;
  totals: ReleaseModelTotals;
  coverage: { tasks_with_evidence: number; tasks_total: number };
  run_window: { started_at: string; finished_at: string };
  tooling_heads?: string[];
  receipt?: string;
  generation?: {
    group: string;
    temperature: number | null;
    base_seed: number | null;
    request_timeout_s: number | null;
    ollama_version: string | null;
  } | null;
  domains: ReleaseDomainResult[];
  tasks: ReleaseTaskResult[];
  caveat_ids: string[];
  documented_facts: DocumentedFact[];
}

export interface ReleaseCaveat {
  id: string;
  model: string | null;
  kind: string;
  label: string;
  summary: string;
  points: string[];
  source: string;
  verified_fields: string[];
  documented_fact: string | null;
}

export interface EvidenceLink {
  label: string;
  path: string;
  kind: string;
  model?: string;
}

export interface BenchmarkRelease {
  schema_version: 1;
  id: string;
  title: string;
  short_title: string;
  status: ReleaseStatus;
  released_at: string;
  summary: string;
  repository: ReleaseRepository;
  campaign_id: string | null;
  comparable: boolean;
  ranked: boolean;
  comparability?: string;
  counts: ReleaseCounts;
  headline?: ReleaseHeadline;
  environment: ReleaseEnvironment | null;
  methodology: CampaignMethodology | HistoricalMethodology;
  integrity: ReleaseIntegrity | null;
  domains: string[];
  task_pack: ReleaseTaskPackEntry[];
  models: ReleaseModel[];
  caveats: ReleaseCaveat[];
  evidence_links: EvidenceLink[];
  sources: { path: string; sha256: string }[];
}

export class ReleaseDataError extends Error {}

function need(condition: unknown, message: string): asserts condition {
  if (!condition) throw new ReleaseDataError(message);
}

/** Narrow a parsed dataset to a BenchmarkRelease. JSON imports widen every
 * literal (a status becomes `string`), so the registry validates each dataset
 * once instead of trusting a cast. */
export function asBenchmarkRelease(raw: unknown): BenchmarkRelease {
  need(raw && typeof raw === "object", "release dataset is not an object");
  const r = raw as Record<string, unknown>;
  const id = String(r.id ?? "?");
  need(r.schema_version === 1, `${id}: unsupported schema_version`);
  need(typeof r.id === "string" && r.id !== "", "release without an id");
  for (const key of ["title", "short_title", "released_at", "summary"]) {
    need(typeof r[key] === "string" && r[key] !== "", `${id}: missing ${key}`);
  }
  need(
    RELEASE_STATUSES.includes(r.status as ReleaseStatus),
    `${id}: unknown status ${String(r.status)}`,
  );
  need(Array.isArray(r.models) && r.models.length > 0, `${id}: no models`);
  need(Array.isArray(r.task_pack), `${id}: no task pack`);
  need(Array.isArray(r.caveats), `${id}: no caveats list`);
  need(typeof r.ranked === "boolean", `${id}: ranked flag missing`);
  const counts = r.counts as ReleaseCounts | undefined;
  need(counts && typeof counts.runs === "number", `${id}: no counts`);
  const models = r.models as ReleaseModel[];
  for (const model of models) {
    need(typeof model.id === "string", `${id}: model without an id`);
    need(
      model.tasks.length === (r.task_pack as unknown[]).length,
      `${id}: ${model.id} does not cover the task pack`,
    );
    need(
      !r.ranked || model.rank === null || typeof model.rank.low === "number",
      `${id}: ${model.id} has no rank`,
    );
  }
  need(
    models.reduce((sum, model) => sum + model.totals.runs, 0) === counts.runs,
    `${id}: model runs do not add up to the release total`,
  );
  return raw as BenchmarkRelease;
}

/** The release the benchmark page opens on: the newest OFFICIAL release by its
 * own metadata; failing that the newest non-historical one; failing that the
 * newest of all. Never a hard-coded id. */
export function selectDefaultRelease(
  releases: readonly BenchmarkRelease[],
): BenchmarkRelease {
  need(releases.length > 0, "no benchmark releases are registered");
  const newest = (list: readonly BenchmarkRelease[]) =>
    [...list].sort(
      (a, b) =>
        b.released_at.localeCompare(a.released_at) || a.id.localeCompare(b.id),
    )[0];
  const official = releases.filter((r) => r.status === "OFFICIAL");
  if (official.length) return newest(official);
  const current = releases.filter((r) => r.status !== "HISTORICAL");
  if (current.length) return newest(current);
  return newest(releases);
}

/** Registry order for a release selector: the default first, then the other
 * non-historical releases newest first, then historical ones. */
export function orderReleases(
  releases: readonly BenchmarkRelease[],
): BenchmarkRelease[] {
  const first = selectDefaultRelease(releases);
  const rest = releases
    .filter((r) => r.id !== first.id)
    .sort(
      (a, b) =>
        Number(a.status === "HISTORICAL") - Number(b.status === "HISTORICAL") ||
        b.released_at.localeCompare(a.released_at),
    );
  return [first, ...rest];
}

export function findRelease(
  releases: readonly BenchmarkRelease[],
  id: string | undefined,
): BenchmarkRelease | undefined {
  return id === undefined
    ? selectDefaultRelease(releases)
    : releases.find((r) => r.id === id);
}

export function findModel(
  release: BenchmarkRelease,
  modelId: string | undefined,
): ReleaseModel | undefined {
  return release.models.find((m) => m.id === modelId);
}

export function caveatsFor(
  release: BenchmarkRelease,
  modelId: string | null,
): ReleaseCaveat[] {
  return release.caveats.filter((c) => c.model === modelId);
}

export function isCampaignMethodology(
  methodology: BenchmarkRelease["methodology"],
): methodology is CampaignMethodology {
  return "campaign_id" in methodology;
}

/** Link to a committed evidence file at the release's frozen git ref. */
export function evidenceUrl(
  release: BenchmarkRelease,
  path: string,
): string | null {
  const { url, ref } = release.repository;
  if (!url || !ref) return null;
  return `${url}/blob/${encodeURIComponent(ref)}/${path
    .split("/")
    .map(encodeURIComponent)
    .join("/")}`;
}

export function releasePath(release: BenchmarkRelease): string {
  return `/benchmarks/${encodeURIComponent(release.id)}`;
}

export function modelPath(release: BenchmarkRelease, modelId: string): string {
  return `${releasePath(release)}/models/${encodeURIComponent(modelId)}`;
}

export function methodologyPath(release: BenchmarkRelease): string {
  return `${releasePath(release)}/methodology`;
}

export const STATUS_DESCRIPTIONS: Record<ReleaseStatus, string> = {
  OFFICIAL:
    "Frozen, validated benchmark release. Its numbers come from campaign-owned evidence and never change in place.",
  EXPERIMENTAL:
    "Published for inspection; not an official ranking and may be superseded.",
  SUPERSEDED: "Replaced by a newer release; kept unchanged for the record.",
  HISTORICAL:
    "Recorded before the current evaluation-integrity system. Shown as recorded, unranked, and not comparable with current releases.",
};
