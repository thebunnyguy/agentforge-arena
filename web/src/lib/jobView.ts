import type { EvaluationTrial, JobEvent } from "../api/types";

export type RunViewState =
  | "pending"
  | "running"
  | "pass"
  | "fail"
  | "voided"
  | "reused"
  | "unknown"
  | "error"
  | "blocked"
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
  /** The exact run a persisted trial row names (evaluation-scoped). */
  runId?: number;
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

// A reclaim (crashed worker) or an explicit resume restarts the evaluation's
// unfinished positions under the same ID: runs without a persisted result go
// back to pending, and only a terminal event after the last restart ends it.
const RESTART_EVENTS = new Set(["job_reclaimed", "job_resumed"]);

export function projectEventTape(events: JobEvent[]): JobEventProjection {
  const runs = new Map<string, RunView>();
  const taskErrors = new Map<string, string>();
  for (const event of events) {
    if (RESTART_EVENTS.has(event.type)) {
      // An explicit resume re-verifies the task snapshot and unblocks blocked
      // positions, so task-level errors from before it no longer apply.
      if (event.type === "job_resumed") taskErrors.clear();
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
    (last, event, index) => (RESTART_EVENTS.has(event.type) ? index : last),
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

/** The fields shared by /jobs/{id}/results rows and report.json trials. */
export type PersistedTrial = Pick<
  EvaluationTrial,
  | "task_id"
  | "idx"
  | "trial_state"
  | "evidence_state"
  | "run_id"
  | "outcome"
  | "error_message"
>;

/**
 * One persisted trial row as a grid marker. This is the evaluation's durable
 * state, so it outranks the event tape wherever it records an outcome; a
 * pending or claimed row says only "not finished yet" and leaves the live
 * state to the events.
 */
export function trialRunView(trial: PersistedTrial): RunView {
  const base = {
    taskId: trial.task_id,
    idx: trial.idx,
    runId: trial.run_id ?? undefined,
    error: trial.error_message ?? undefined,
  };
  if (trial.trial_state === "blocked")
    return { ...base, state: "blocked", phase: "error", persisted: false };
  if (trial.trial_state === "claimed")
    return { ...base, state: "running", phase: "running", persisted: false };
  if (trial.trial_state !== "completed")
    return { ...base, state: "pending", phase: "pending", persisted: false };
  const persisted = trial.run_id !== null;
  // Reused evidence is never counted as a fresh outcome, whatever it scored.
  if (trial.evidence_state === "reused")
    return {
      ...base,
      state: "reused",
      phase: "skipped",
      persisted,
      status: trial.outcome?.status,
    };
  const outcome = trial.outcome;
  if (!outcome)
    return { ...base, state: "unknown", phase: "persisted", persisted };
  return {
    ...base,
    state: outcome.voided
      ? "voided"
      : outcome.functional_pass
        ? "pass"
        : "fail",
    phase: "persisted",
    persisted,
    status: outcome.status,
    functionalPass: outcome.functional_pass,
  };
}

export function projectTrials(trials: PersistedTrial[]): Map<string, RunView> {
  return new Map(
    trials.map((trial) => [
      `${trial.task_id}:${trial.idx}`,
      trialRunView(trial),
    ]),
  );
}

/**
 * Pick the marker for one (task, repeat) position. A persisted trial that has
 * left pending/claimed is authoritative; otherwise the live event tape wins,
 * then the persisted pending/claimed row, then the grid's own fallback.
 */
export function mergeRunViews(
  persisted: RunView | undefined,
  live: RunView | undefined,
): RunView | undefined {
  if (
    persisted &&
    persisted.state !== "pending" &&
    persisted.state !== "running"
  )
    return persisted;
  return live ?? persisted;
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
    case "blocked":
      return "blocked · not executed";
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
    case "blocked":
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
