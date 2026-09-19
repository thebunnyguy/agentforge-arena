// Type contract for the read-only + product API exposed by afa_api/.
// These mirror EXACTLY the JSON the backend serializer emits (afa_api/serialize.py,
// afa_api/schemas.py, afa_api/routes_*.py). All endpoints live under /api/v1.
// The SPA renders SERVER values only; it never recomputes any statistic.

export interface HealthResponse {
  status: string; // "ok" | "degraded"
  stores_loaded: boolean;
  load_error: string | null;
  db_path: string;
}

// Mirrors afa_runner.store.RunStoreSummary projection (_summary_dict).
export interface ObservabilitySummary {
  total_runs: number;
  first_created_at: string | null;
  last_created_at: string | null;
  runs_with_patch: number;
  runs_with_test_results: number;
  test_result_rows: number;
}

// real_counts is EXACT {n_runs, n_tasks} of CURRENT in-scope runs (server).
export interface RealCount {
  n_runs: number;
  n_tasks: number;
}

// ---------------------------------------------------------------------- //
// Evidence vocabulary (server enums; the SPA never compares version strings).
// ---------------------------------------------------------------------- //

/** ?evidence= scope accepted by every aggregate read route. */
export type EvidenceScope = "benchmark" | "real" | "synthetic" | "all";
/** Provider provenance of a run (server-resolved). */
export type EvidenceClass = "real" | "legacy" | "synthetic" | "conflict";
/** Status of the evidence shown for a selected version. */
export type VersionStatus = "current" | "historical";

/** Per-agent evidence coverage (overview / meta `evidence_counts`). */
export interface EvidenceCounts {
  current_runs: number;
  current_tasks: number;
  current_by_class?: Partial<Record<EvidenceClass, number>>;
  historical_runs: number;
  historical_tasks: number;
  historical_only_tasks: number;
  tasks_total: number;
  coverage_complete: boolean;
}

/** overview/meta `current_benchmark` block. */
export interface CurrentBenchmark {
  n_tasks: number;
  tasks_with_current_evidence: number;
  current_runs: number;
  historical_runs: number;
  models_with_current_evidence: number;
  models_total: number;
}

export interface ExcludedEvidence {
  synthetic_runs: number;
  synthetic_models?: string[];
  provenance_conflict_runs: number;
}

/** Per-entry coverage on GLOBAL leaderboard entries (absent on task scope). */
export interface EntryCoverage {
  tasks_with_current_evidence: number;
  tasks_total: number;
  complete: boolean;
}

export interface DomainTag {
  domain: string;
  weight: number;
}

export interface TaskMeta {
  task_id: string;
  current_version: string | null;
  evaluated_versions: string[];
  difficulty?: number | string | null;
  activity?: string | null;
  scale?: string | null;
  dir?: string | null;
  domains: DomainTag[];
  // Version-aware fields (optional: older payloads omit them).
  current_runs?: number;
  historical_runs?: number;
  historical_versions?: string[];
  has_current_evidence?: boolean;
  models_with_current_evidence?: number;
}

// GET /meta
export interface MetaResponse {
  models: string[];
  synthetic_agents: string[];
  n_tasks: number;
  tasks: TaskMeta[];
  observability: ObservabilitySummary;
  real_counts: Record<string, RealCount>;
  notes: Record<string, string>;
  evidence_scope?: EvidenceScope;
  current_models?: string[];
  historical_only_models?: string[];
  evidence_counts?: Record<string, EvidenceCounts>;
  current_benchmark?: CurrentBenchmark;
  excluded?: ExcludedEvidence;
}

// Mirrors afa_kernel.types.LeaderboardEntry (+ synthetic flag from serializer).
export interface LeaderboardEntry {
  agent: string;
  pass_rate: number;
  wilson_low: number;
  wilson_high: number;
  n: number;
  provisional: boolean;
  rank_low: number | null;
  rank_high: number | null;
  synthetic?: boolean;
  coverage?: EntryCoverage;
}

// GET /leaderboard
export interface LeaderboardResponse {
  task_id: string | null;
  found: boolean;
  entries: LeaderboardEntry[];
  evidence_scope?: EvidenceScope;
  current_version?: string | null;
  version?: string | null;
  evidence_status?: VersionStatus | null;
  /** Agents with in-scope rows but none at the selected version. */
  historical_only_agents?: string[];
}

// GET /overview
export interface OverviewResponse {
  models: string[];
  task_ids: string[];
  n_tasks: number;
  real_counts: Record<string, RealCount>;
  observability: ObservabilitySummary;
  agent_observability: Record<string, ObservabilitySummary>;
  leaderboard: LeaderboardEntry[];
  synthetic_agents: string[];
  evidence_scope?: EvidenceScope;
  current_models?: string[];
  historical_only_models?: string[];
  evidence_counts?: Record<string, EvidenceCounts>;
  current_benchmark?: CurrentBenchmark;
  excluded?: ExcludedEvidence;
}

// Mirrors afa_kernel.types.DomainScore
export interface DomainScore {
  domain: string;
  pooled_pass_rate: number;
  n_eff: number;
  wilson_low: number;
  wilson_high: number;
  stability: number;
  n_tasks: number;
  n_runs: number;
  displayable: boolean;
}

// GET /domains/{agent}
export interface DomainProfileResponse {
  agent: string;
  captured: boolean;
  synthetic: boolean;
  domains: DomainScore[];
  evidence_scope?: EvidenceScope;
  evidence_status?: "current" | "historical_only" | "none" | "synthetic";
  coverage?: {
    current_tasks: number;
    historical_only_tasks: number;
    tasks_total: number;
  };
}

export type RunStatus = "valid" | "timeout" | "agent_error" | "infra_failure";
export type CaptureState =
  "captured" | "historical_only" | "not_captured" | "synthetic";

// Mirrors _run_score_dict
export interface RunScore {
  status: RunStatus;
  gate_product: number; // G in {0,1}
  t_hidden: number;
  q: number;
  q_components: Record<string, number>;
  q_components_available: boolean;
  final_score: number; // S
  functional_pass: boolean; // X
  voided: boolean;
}

// A run row inside a cell (serializer build_cell -> runs[]).
export interface CellRunRow {
  agent: string;
  task_id: string;
  idx: number;
  status: RunStatus;
  score: RunScore;
  run_id?: number;
  task_version?: string | null;
  backend_kind?: BackendKind | null;
  evidence_class?: EvidenceClass;
}

// Mirrors afa_kernel.types.AggregateResult
export interface AggregateResult {
  n_valid: number;
  n_pass: number;
  pass_rate: number;
  wilson_low: number;
  wilson_high: number;
  mean_s: number;
  median_s: number;
  min_s: number;
  max_s: number;
  std_s: number;
  stability: number;
  conservative_continuous: number;
  timeout_rate: number;
  infra_void_rate: number;
  reliability: number;
  pass_at_k: Record<string, number>;
  deterministic: boolean;
  bimodal: boolean;
  provisional: boolean;
}

// One evidence version inside a cell (server aggregates each independently).
export interface CellVersion {
  version: string;
  status: VersionStatus;
  n_runs: number;
  run_ids: number[];
  aggregate: AggregateResult | null;
}

// GET /cell/{agent}/{task_id}[?version=&evidence=]
// `state` describes CURRENT evidence and is independent of ?version;
// `evidence_status` describes the SELECTED view.
export interface CellResponse {
  agent: string;
  task_id: string;
  known_task: boolean;
  captured: boolean;
  synthetic: boolean;
  state: CaptureState;
  current_version: string | null;
  task_versions: string[];
  runs: CellRunRow[];
  aggregate: AggregateResult | null;
  // Version-aware fields (optional: older payloads omit them).
  selected_version?: string | null;
  evidence_status?: "current" | "historical" | "none" | "synthetic";
  evidence_scope?: EvidenceScope;
  has_current_evidence?: boolean;
  has_historical_evidence?: boolean;
  current_runs?: number;
  historical_runs?: number;
  historical_versions?: string[];
  excluded?: { synthetic_runs: number; provenance_conflict_runs: number };
  versions?: CellVersion[];
}

export interface TestResultRow {
  suite: string;
  test_name: string;
  passed: boolean;
  weight: number;
}

// GET /run/{agent}/{task_id}/{idx}
export interface RunDetailResponse {
  agent: string;
  task_id: string;
  idx: number;
  found: boolean;
  synthetic: boolean;
  captured?: boolean;
  known_task: boolean;
  task_version?: string;
  status?: RunStatus;
  score?: RunScore;
  files_changed?: number;
  lines_added?: number;
  lines_removed?: number;
  transcript_hash?: string | null;
  duration_ms?: number | null;
  created_at?: string | null;
  touched_protected?: boolean;
  patch_text?: string | null;
  patch_available?: boolean;
  test_results?: TestResultRow[] | string;
  // Provenance / version fields (optional: older payloads omit them).
  run_id?: number;
  job_id?: string | null;
  backend_kind?: BackendKind | null;
  evidence_class?: EvidenceClass;
  provider_source?: "run" | "evaluation" | "none";
  version_status?: VersionStatus | null;
  current_version?: string | null;
  // Tuple route answers found:false with these when the version is absent.
  selected_version?: string | null;
  historical_versions?: string[];
  ambiguous?: boolean;
  candidate_run_ids?: number[];
}

// ----------------------------------------------------------------------- //
// Product / job control-plane (Phases 4-9)
// ----------------------------------------------------------------------- //

export type JobStatus =
  "queued" | "running" | "succeeded" | "failed" | "canceled";

export type BackendKind = "mock" | "ollama" | "openai_compat";

export interface Backend {
  kind: BackendKind;
  base_url: string | null;
}

export interface JobParams {
  backend: Backend;
  model: string;
  name: string | null;
  tasks: string[];
  repeats: number;
  base_seed: number;
  temperature: number;
  request_timeout_s: number;
}

export interface JobCounters {
  total_runs: number;
  completed_runs: number;
  passed_runs: number;
  voided_runs: number;
  failed_runs: number;
  reused_runs: number;
}

export type ParamsStatus = "available" | "unverifiable";
/** Job evidence class: real (ollama/openai_compat), synthetic (mock), unknown. */
export type JobEvidenceClass = "real" | "synthetic" | "unknown";

export interface Job {
  id: string;
  status: JobStatus;
  cancel_requested: boolean;
  /** null when the persisted parameters are unverifiable (see params_status). */
  params: JobParams | null;
  params_status?: ParamsStatus;
  params_error?: string | null;
  backend_kind?: BackendKind | null;
  evidence_class?: JobEvidenceClass;
  counters: JobCounters;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  error_message: string | null;
}

export interface JobListResponse {
  jobs: Job[];
}

export interface JobEvent {
  job_id?: string;
  seq: number;
  /** Persisted poll events carry the server timestamp; native SSE does not. */
  ts: string | null;
  type: string;
  payload: Record<string, unknown> | null;
}

export interface JobEventsResponse {
  job_id: string;
  events: JobEvent[];
}

export interface BackendVerifyRequest {
  kind: BackendKind;
  base_url: string | null;
}

export interface BackendVerifyResponse {
  kind: BackendKind;
  ok: boolean;
  detail: string;
  models: string[];
}

// GET/PUT /settings — mirrors schemas.Settings
export interface AppSettings {
  ollama_base_url: string;
  openai_base_url: string | null;
  default_backend: BackendKind;
  default_temperature: number;
  default_repeats: number;
  default_request_timeout_s: number;
  extra: Record<string, unknown>;
}

export interface RegenerateResponse {
  ok: boolean;
  path: string;
  bytes: number;
  real_counts: Record<string, RealCount>;
}
