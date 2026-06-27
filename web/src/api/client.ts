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
  constructor(message: string, status: number, detail?: string) {
    super(message);
    this.name = "ApiRequestError";
    this.status = status;
    this.detail = detail;
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
    let message = `Request failed (${res.status})`;
    try {
      const body = await res.json();
      if (body && typeof body === "object") {
        message = (body.error as string) || (body.detail as string) || message;
        detail = body.detail as string | undefined;
      }
    } catch {
      // non-JSON error body
    }
    throw new ApiRequestError(message, res.status, detail);
  }

  if (res.status === 204) return undefined as unknown as T;
  return (await res.json()) as T;
}

// ----------------------------- Read-only ------------------------------ //

export const api = {
  baseUrl: API_BASE,

  health: (signal?: AbortSignal) =>
    request<HealthResponse>("/healthz", { signal }),

  meta: (signal?: AbortSignal) => request<MetaResponse>("/meta", { signal }),

  overview: (signal?: AbortSignal) =>
    request<OverviewResponse>("/overview", { signal }),

  leaderboard: (taskId?: string | null, signal?: AbortSignal) => {
    const q = taskId ? `?task_id=${encodeURIComponent(taskId)}` : "";
    return request<LeaderboardResponse>(`/leaderboard${q}`, { signal });
  },

  domainProfile: (agent: string, signal?: AbortSignal) =>
    request<DomainProfileResponse>(
      `/domains/${encodeURIComponent(agent)}`,
      { signal },
    ),

  cell: (agent: string, taskId: string, signal?: AbortSignal) =>
    request<CellResponse>(
      `/cell/${encodeURIComponent(agent)}/${encodeURIComponent(taskId)}`,
      { signal },
    ),

  run: (agent: string, taskId: string, idx: number, signal?: AbortSignal) =>
    request<RunDetailResponse>(
      `/run/${encodeURIComponent(agent)}/${encodeURIComponent(taskId)}/${idx}`,
      { signal },
    ),

  // Domain matrix = per-agent profiles stitched into one grid. There is no
  // matrix endpoint; we fetch each agent's profile and assemble for DISPLAY.
  // No pooling/statistics here — every cell value is the server's pooled rate.
  domainMatrix: async (
    agents: string[],
    signal?: AbortSignal,
  ): Promise<{
    domains: string[];
    agents: string[];
    byAgent: Record<string, Record<string, DomainScore>>;
  }> => {
    const profiles = await Promise.all(
      agents.map((a) => api.domainProfile(a, signal)),
    );
    const domainSet = new Set<string>();
    const byAgent: Record<string, Record<string, DomainScore>> = {};
    profiles.forEach((p) => {
      byAgent[p.agent] = {};
      p.domains.forEach((d) => {
        domainSet.add(d.domain);
        byAgent[p.agent][d.domain] = d;
      });
    });
    return {
      domains: [...domainSet].sort(),
      agents,
      byAgent,
    };
  },

  // ----------------------------- Jobs -------------------------------- //

  jobs: (signal?: AbortSignal) =>
    request<JobListResponse>("/jobs", { signal }),

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
