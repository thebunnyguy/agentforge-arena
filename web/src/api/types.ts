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

export interface RealCount {
  n_runs: number;
  n_tasks: number;
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
}

// GET /leaderboard
export interface LeaderboardResponse {
  task_id: string | null;
  found: boolean;
  entries: LeaderboardEntry[];
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
}

export type RunStatus = "valid" | "timeout" | "agent_error" | "infra_failure";
export type CaptureState = "captured" | "not_captured" | "synthetic";

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

// GET /cell/{agent}/{task_id}
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
  test_results?: TestResultRow[];
}

// ----------------------------------------------------------------------- //
// Product / job control-plane (Phases 4-9)
// ----------------------------------------------------------------------- //

export type JobStatus =
  | "queued"
  | "running"
  | "succeeded"
  | "failed"
  | "canceled";

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
}

export interface Job {
  id: string;
  status: JobStatus;
  cancel_requested: boolean;
  params: JobParams;
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
  ts: string;
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
