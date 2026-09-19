// The ONE api client module for the SPA. Base URL comes from VITE_API_BASE,
// falling back to window.location.origin (the API/web container serves the
// built assets, so same-origin is the production default).
//
// All backend routes live under /api/v1 (see afa_api/routes_*.py). This module
// is request plumbing + typed wrappers only; it computes NO statistics. The one
// piece of assembly here (domainMatrix) stitches per-agent domain profiles into
// a grid for display — pure field selection, not stat math.

import type {
  AppSettings,
  BackendVerifyRequest,
  BackendVerifyResponse,
  CellResponse,
  DomainProfileResponse,
  DomainScore,
  EvidenceScope,
  HealthResponse,
  Job,
  JobEvent,
  JobEventsResponse,
  JobListResponse,
  JobParams,
  LeaderboardResponse,
  MetaResponse,
  OverviewResponse,
  RegenerateResponse,
  RunDetailResponse,
} from "./types";

const API_PREFIX = "/api/v1";

function resolveBaseUrl(): string {
  const fromEnv = import.meta.env.VITE_API_BASE;
  if (fromEnv && fromEnv.length > 0) {
    return fromEnv.replace(/\/$/, "");
  }
  if (typeof window !== "undefined" && window.location) {
    return window.location.origin;
  }
  return "";
}

export const API_BASE = resolveBaseUrl();

export class ApiRequestError extends Error {
  status: number;
  detail?: string;
  /** Parsed JSON error body, when the server sent one (e.g. 409 ambiguous). */
  body?: unknown;
  constructor(
    message: string,
    status: number,
    detail?: string,
    body?: unknown,
  ) {
    super(message);
    this.name = "ApiRequestError";
    this.status = status;
    this.detail = detail;
    this.body = body;
  }
}

async function request<T>(
  path: string,
  init?: RequestInit & { signal?: AbortSignal },
): Promise<T> {
  const url = `${API_BASE}${API_PREFIX}${path}`;
  let res: Response;
  try {
    res = await fetch(url, {
      headers: {
        Accept: "application/json",
        ...(init?.body ? { "Content-Type": "application/json" } : {}),
        ...(init?.headers || {}),
      },
      ...init,
    });
  } catch (err) {
    throw new ApiRequestError(
      "Cannot reach the local API server.",
      0,
      err instanceof Error ? err.message : String(err),
    );
  }

  if (!res.ok) {
    let detail: string | undefined;
    let errorBody: unknown;
    let message = `Request failed (${res.status})`;
    try {
      const body: unknown = await res.json();
      errorBody = body;
      if (body && typeof body === "object") {
        const envelope = body as {
          error?: unknown;
          detail?: unknown;
          message?: unknown;
        };
        const error = envelope.error;
        if (typeof error === "string") message = error;
        else if (error && typeof error === "object") {
          const nested = error as { message?: unknown; detail?: unknown };
          if (typeof nested.message === "string") message = nested.message;
          else if (typeof nested.detail === "string") message = nested.detail;
          if (typeof nested.detail === "string") detail = nested.detail;
          else detail = JSON.stringify(error);
        } else if (typeof envelope.message === "string")
          message = envelope.message;
        else if (typeof envelope.detail === "string") message = envelope.detail;
        else if (Array.isArray(envelope.detail)) {
          const messages = envelope.detail.map((item) =>
            typeof item === "string" ? item : JSON.stringify(item),
          );
          message = messages.join("; ") || message;
          detail = message;
        }
      }
    } catch {
      // non-JSON error body
    }
    throw new ApiRequestError(message, res.status, detail, errorBody);
  }

  if (res.status === 204) return undefined as unknown as T;
  return (await res.json()) as T;
}

/** Optional selectors accepted by the aggregate/read routes. */
export interface ReadOpts {
  /** Evidence scope. "benchmark" (real + legacy) is the server default. */
  evidence?: EvidenceScope | null;
  /** Task version for cell / task-scoped leaderboard (default: current). */
  version?: string | null;
}

function query(opts?: ReadOpts, extra?: Record<string, string>): string {
  const params = new URLSearchParams(extra);
  if (opts?.version) params.set("version", opts.version);
  if (opts?.evidence && opts.evidence !== "benchmark")
    params.set("evidence", opts.evidence);
  const text = params.toString();
  return text ? `?${text}` : "";
}

// ----------------------------- Read-only ------------------------------ //

export const api = {
  baseUrl: API_BASE,

  health: (signal?: AbortSignal) =>
    request<HealthResponse>("/healthz", { signal }),

  // Aggregate reads default to the CURRENT benchmark (?evidence=benchmark).
  // The default is omitted from the URL so default requests stay unchanged.
  meta: (opts?: ReadOpts, signal?: AbortSignal) =>
    request<MetaResponse>(`/meta${query(opts)}`, { signal }),

  overview: (opts?: ReadOpts, signal?: AbortSignal) =>
    request<OverviewResponse>(`/overview${query(opts)}`, { signal }),

  leaderboard: (
    taskId?: string | null,
    opts?: ReadOpts,
    signal?: AbortSignal,
  ) =>
    request<LeaderboardResponse>(
      `/leaderboard${query(opts, taskId ? { task_id: taskId } : undefined)}`,
      { signal },
    ),

  domainProfile: (agent: string, opts?: ReadOpts, signal?: AbortSignal) =>
    request<DomainProfileResponse>(
      `/domains/${encodeURIComponent(agent)}${query(opts)}`,
      { signal },
    ),

  cell: (
    agent: string,
    taskId: string,
    opts?: ReadOpts,
    signal?: AbortSignal,
  ) =>
    request<CellResponse>(
      `/cell/${encodeURIComponent(agent)}/${encodeURIComponent(taskId)}${query(opts)}`,
      { signal },
    ),

  // Tuple route (agent, task, idx): idx alone collides across versions, so
  // prefer runById for links. Kept for pre-existing /cell/.../run/:idx URLs.
  run: (
    agent: string,
    taskId: string,
    idx: number,
    opts?: ReadOpts,
    signal?: AbortSignal,
  ) =>
    request<RunDetailResponse>(
      `/run/${encodeURIComponent(agent)}/${encodeURIComponent(taskId)}/${idx}${query(opts)}`,
      { signal },
    ),

  // Exact forensic identity; never class-filtered (mock rows stay inspectable).
  runById: (runId: number | string, signal?: AbortSignal) =>
    request<RunDetailResponse>(`/runs/${encodeURIComponent(String(runId))}`, {
      signal,
    }),

  // Domain matrix = per-agent profiles stitched into one grid. There is no
  // matrix endpoint; we fetch each agent's profile and assemble for DISPLAY.
  // No pooling/statistics here — every cell value is the server's pooled rate.
  domainMatrix: async (
    agents: string[],
    opts?: ReadOpts,
    signal?: AbortSignal,
  ): Promise<{
    domains: string[];
    agents: string[];
    byAgent: Record<string, Record<string, DomainScore>>;
    profiles: Record<string, DomainProfileResponse>;
  }> => {
    const profiles = await Promise.all(
      agents.map((a) => api.domainProfile(a, opts, signal)),
    );
    const domainSet = new Set<string>();
    const byAgent: Record<string, Record<string, DomainScore>> = {};
    const byProfile: Record<string, DomainProfileResponse> = {};
    profiles.forEach((p) => {
      byAgent[p.agent] = {};
      byProfile[p.agent] = p;
      p.domains.forEach((d) => {
        domainSet.add(d.domain);
        byAgent[p.agent][d.domain] = d;
      });
    });
    return {
      domains: [...domainSet].sort(),
      agents,
      byAgent,
      profiles: byProfile,
    };
  },

  // ----------------------------- Jobs -------------------------------- //

  jobs: (signal?: AbortSignal) => request<JobListResponse>("/jobs", { signal }),

  job: (jobId: string, signal?: AbortSignal) =>
    request<Job>(`/jobs/${encodeURIComponent(jobId)}`, { signal }),

  createJob: (params: JobParams, signal?: AbortSignal) =>
    request<Job>("/jobs", {
      method: "POST",
      body: JSON.stringify(params),
      signal,
    }),

  cancelJob: (jobId: string, signal?: AbortSignal) =>
    request<Job>(`/jobs/${encodeURIComponent(jobId)}/cancel`, {
      method: "POST",
      signal,
    }),

  retryJob: (jobId: string, signal?: AbortSignal) =>
    request<Job>(`/jobs/${encodeURIComponent(jobId)}/retry`, {
      method: "POST",
      signal,
    }),

  // Poll fallback for the live monitor (?since= returns JSON, no SSE).
  jobEvents: (jobId: string, since: number, signal?: AbortSignal) =>
    request<JobEventsResponse>(
      `/jobs/${encodeURIComponent(jobId)}/events?since=${since}`,
      { signal },
    ),

  // ----------------------------- Settings ---------------------------- //

  settings: (signal?: AbortSignal) =>
    request<AppSettings>("/settings", { signal }),

  updateSettings: (settings: AppSettings, signal?: AbortSignal) =>
    request<AppSettings>("/settings", {
      method: "PUT",
      body: JSON.stringify(settings),
      signal,
    }),

  verifyBackend: (req: BackendVerifyRequest, signal?: AbortSignal) =>
    request<BackendVerifyResponse>("/backends/verify", {
      method: "POST",
      body: JSON.stringify(req),
      signal,
    }),

  // ----------------------------- Reports ----------------------------- //

  regenerateReport: (signal?: AbortSignal) =>
    request<RegenerateResponse>("/reports/regenerate", {
      method: "POST",
      signal,
    }),
};

// SSE URL for the live monitor (no ?since= => stream). EventSource handles
// Last-Event-ID reconnect natively.
export function jobEventsSseUrl(jobId: string): string {
  return `${API_BASE}${API_PREFIX}/jobs/${encodeURIComponent(jobId)}/events`;
}

// Direct download URL for the JSON export (GET /export).
export function exportUrl(): string {
  return `${API_BASE}${API_PREFIX}/export`;
}

export type { JobEvent };
