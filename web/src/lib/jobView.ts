import type { JobEvent } from "../api/types";

export type RunViewState =
  | "pending"
  | "running"
  | "pass"
  | "fail"
  | "voided"
  | "reused"
  | "unknown"
  | "error"
  | "interrupted"
  | "not_run"
  | "not_recorded";
export type RunViewPhase =
  | "pending"
  | "running"
  | "diffed"
  | "graded"
  | "scored"
  | "persisted"
  | "skipped"
  | "error"
  | "interrupted";

export interface RunView {
  taskId: string;
  idx: number;
  state: RunViewState;
  phase: RunViewPhase;
  status?: string;
  functionalPass?: boolean;
  persisted: boolean;
  error?: string;
}

export interface JobEventProjection {
  runs: Map<string, RunView>;
  taskErrors: Map<string, string>;
}

function payloadString(
  payload: Record<string, unknown> | null,
  key: string,
): string | undefined {
  const value = payload?.[key];
  return typeof value === "string" ? value : undefined;
}

function payloadNumber(
  payload: Record<string, unknown> | null,
  key: string,
): number | undefined {
  const value = payload?.[key];
  return typeof value === "number" && Number.isInteger(value)
    ? value
    : undefined;
}

function payloadBoolean(
  payload: Record<string, unknown> | null,
  key: string,
): boolean | undefined {
  const value = payload?.[key];
  return typeof value === "boolean" ? value : undefined;
}

function updateOutcome(
  current: RunView,
  payload: Record<string, unknown> | null,
): Pick<RunView, "state" | "status" | "functionalPass"> {
  const status = payloadString(payload, "status") ?? current.status;
  const functionalPass = payloadBoolean(payload, "functional_pass");
  const voided =
    status === "infra_failure" || payloadBoolean(payload, "voided") === true;
  if (voided)
    return {
      state: "voided",
      status,
      functionalPass: functionalPass ?? current.functionalPass,
    };
  if (functionalPass !== undefined)
    return { state: functionalPass ? "pass" : "fail", status, functionalPass };
  if (
    current.state === "pass" ||
    current.state === "fail" ||
    current.state === "voided" ||
    current.state === "reused"
  ) {
    return {
      state: current.state,
      status,
      functionalPass: current.functionalPass,
    };
  }
  return { state: "unknown", status, functionalPass: current.functionalPass };
}

function runFor(
  runs: Map<string, RunView>,
  taskId: string,
  idx: number,
): RunView {
  const key = `${taskId}:${idx}`;
  const existing = runs.get(key);
  if (existing) return existing;
  const created: RunView = {
    taskId,
    idx,
    state: "pending",
    phase: "pending",
    persisted: false,
  };
  runs.set(key, created);
  return created;
}

export function projectEventTape(events: JobEvent[]): JobEventProjection {
  const runs = new Map<string, RunView>();
  const taskErrors = new Map<string, string>();
  for (const event of events) {
    if (event.type === "job_reclaimed") {
      for (const [key, run] of runs) {
        if (
          !run.persisted &&
          run.state !== "pending" &&
          run.state !== "reused"
        ) {
          runs.set(key, {
            ...run,
            state: "pending",
            phase: "pending",
            status: undefined,
            functionalPass: undefined,
            error: undefined,
          });
        }
      }
      continue;
    }
    const taskId = payloadString(event.payload, "task_id");
    const idx = payloadNumber(event.payload, "idx");
    if (event.type === "error" && taskId && idx === undefined) {
      taskErrors.set(
        taskId,
        payloadString(event.payload, "error") ??
          payloadString(event.payload, "message") ??
          "Worker error",
      );
      continue;
    }
    if (!taskId || idx === undefined) continue;
    const current = runFor(runs, taskId, idx);
    if (event.type === "run_started") {
      runs.set(`${taskId}:${idx}`, {
        ...current,
        state: "running",
        phase: "running",
        status: payloadString(event.payload, "status") ?? current.status,
      });
    } else if (event.type === "run_diff") {
      runs.set(`${taskId}:${idx}`, {
        ...current,
        state: current.state === "pending" ? "running" : current.state,
        phase: "diffed",
      });
    } else if (event.type === "run_graded") {
      runs.set(`${taskId}:${idx}`, {
        ...current,
        ...updateOutcome(current, event.payload),
        phase: "graded",
      });
    } else if (event.type === "run_scored") {
      runs.set(`${taskId}:${idx}`, {
        ...current,
        ...updateOutcome(current, event.payload),
        phase: "scored",
      });
    } else if (event.type === "run_persisted") {
      runs.set(`${taskId}:${idx}`, {
        ...current,
        ...updateOutcome(current, event.payload),
        phase: "persisted",
        persisted: true,
      });
    } else if (event.type === "run_skipped") {
      runs.set(`${taskId}:${idx}`, {
        ...current,
        state: "reused",
        phase: "skipped",
        persisted: true,
        status: payloadString(event.payload, "status") ?? current.status,
      });
    } else if (event.type === "error") {
      runs.set(`${taskId}:${idx}`, {
        ...current,
        state: "error",
        phase: "error",
        error:
          payloadString(event.payload, "error") ??
          payloadString(event.payload, "message") ??
          "Worker error",
      });
    }
  }
  const lastReclaim = events.reduce(
    (last, event, index) => (event.type === "job_reclaimed" ? index : last),
    -1,
  );
  const hasCurrentTerminal = events.some(
    (event, index) =>
      index > lastReclaim &&
      ["job_done", "job_failed", "job_canceled"].includes(event.type),
  );
  if (hasCurrentTerminal) {
    for (const [key, run] of runs) {
      if (!run.persisted && run.state === "running") {
        runs.set(key, {
          ...run,
          state: "interrupted",
          phase: "interrupted",
          error: "Evaluation ended before a persisted result.",
        });
      }
    }
  }
  return { runs, taskErrors };
}

export function projectRuns(events: JobEvent[]): Map<string, RunView> {
  return projectEventTape(events).runs;
}

export function runStateLabel(state: RunViewState): string {
  switch (state) {
    case "pass":
      return "pass";
    case "fail":
      return "fail";
    case "voided":
      return "void";
    case "running":
      return "running";
    case "reused":
      return "reused";
    case "unknown":
      return "recorded · outcome unavailable";
    case "error":
      return "worker error";
    case "interrupted":
      return "interrupted · no persisted result";
    case "not_run":
      return "not run";
    case "not_recorded":
      return "not recorded";
    default:
      return "pending";
  }
}

export function runStateSymbol(state: RunViewState): string {
  switch (state) {
    case "pass":
      return "✓";
    case "fail":
      return "×";
    case "voided":
      return "◇";
    case "running":
      return "●";
    case "reused":
      return "↺";
    case "unknown":
      return "?";
    case "error":
      return "!";
    case "interrupted":
      return "!";
    case "not_run":
      return "–";
    case "not_recorded":
      return "?";
    default:
      return "○";
  }
}

export function latestCurrentRun(events: JobEvent[]): RunView | null {
  const runs = [...projectRuns(events).values()];
  return [...runs].reverse().find((run) => run.state === "running") ?? null;
}

export function summarizeEvent(
  payload: Record<string, unknown> | null,
): string {
  if (!payload) return "";
  const fields = [
    "task_id",
    "idx",
    "status",
    "functional_pass",
    "completed_runs",
    "total_runs",
    "message",
    "reason",
  ];
  const parts = fields.flatMap((field) => {
    const value = payload[field];
    return value === undefined || value === null
      ? []
      : [`${field}=${String(value)}`];
  });
  return parts.length > 0 ? parts.join(" · ") : JSON.stringify(payload);
}
