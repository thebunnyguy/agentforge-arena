import { expect, test } from "@playwright/test";
import type { JobEvent } from "../src/api/types";
import {
  mergeRunViews,
  projectEventTape,
  projectRuns,
  projectTrials,
  runStateLabel,
  trialRunView,
} from "../src/lib/jobView";
import type { PersistedTrial } from "../src/lib/jobView";

function event(
  type: string,
  payload: Record<string, unknown> | null,
  seq: number,
): JobEvent {
  return { job_id: "job", seq, ts: "2026-09-09 20:00:00", type, payload };
}

test("preserves a passing outcome through partial score and persistence events", () => {
  const runs = projectRuns([
    event("run_started", { task_id: "task-a", idx: 0 }, 1),
    event("run_diff", { task_id: "task-a", idx: 0 }, 2),
    event(
      "run_graded",
      { task_id: "task-a", idx: 0, status: "valid", functional_pass: true },
      3,
    ),
    event(
      "run_scored",
      { task_id: "task-a", idx: 0, final_score: 1, voided: false },
      4,
    ),
    event("run_persisted", { task_id: "task-a", idx: 0, status: "valid" }, 5),
  ]);

  expect(runs.get("task-a:0")?.state).toBe("pass");
  expect(runs.get("task-a:0")?.functionalPass).toBe(true);
});

test("does not turn a persisted run with unavailable outcome into a failure", () => {
  const runs = projectRuns([
    event("run_started", { task_id: "task-a", idx: 0 }, 1),
    event("run_scored", { task_id: "task-a", idx: 0, final_score: 0.4 }, 2),
    event("run_persisted", { task_id: "task-a", idx: 0, status: "valid" }, 3),
  ]);

  expect(runs.get("task-a:0")?.state).toBe("unknown");
  expect(runs.get("task-a:0")?.functionalPass).toBeUndefined();
});

test("keeps voided, reused, and task-level error semantics distinct", () => {
  const runs = projectRuns([
    event("run_started", { task_id: "void-task", idx: 0 }, 1),
    event(
      "run_graded",
      {
        task_id: "void-task",
        idx: 0,
        status: "infra_failure",
        functional_pass: false,
      },
      2,
    ),
    event(
      "run_persisted",
      { task_id: "void-task", idx: 0, status: "infra_failure" },
      3,
    ),
    event("run_skipped", { task_id: "reused-task", idx: 0 }, 4),
    event("error", { task_id: "broken-task", error: "load_task failed" }, 5),
  ]);

  expect(runs.get("void-task:0")?.state).toBe("voided");
  expect(runs.get("reused-task:0")?.state).toBe("reused");
  expect(runs.has("broken-task:0")).toBe(false);
  expect(runStateLabel(runs.get("reused-task:0")?.state ?? "pending")).toBe(
    "reused",
  );
});

test("marks an unfinished run interrupted when a job ends", () => {
  const runs = projectRuns([
    event("run_started", { task_id: "task-a", idx: 0 }, 1),
    event("job_failed", { error: "worker stopped" }, 2),
  ]);

  expect(runs.get("task-a:0")?.state).toBe("interrupted");
  expect(runs.get("task-a:0")?.persisted).toBe(false);
});

test("reclaim resets an unfinished attempt including partial pass facts", () => {
  const runs = projectRuns([
    event("run_started", { task_id: "task-a", idx: 0 }, 1),
    event(
      "run_graded",
      { task_id: "task-a", idx: 0, status: "valid", functional_pass: true },
      2,
    ),
    event(
      "run_scored",
      { task_id: "task-a", idx: 0, final_score: 1, voided: false },
      3,
    ),
    event("job_reclaimed", { reason: "worker restarted" }, 4),
  ]);

  expect(runs.get("task-a:0")?.state).toBe("pending");
  expect(runs.get("task-a:0")?.functionalPass).toBeUndefined();
  expect(runs.get("task-a:0")?.persisted).toBe(false);
});

test("an old terminal marker cannot interrupt a run after reclaim", () => {
  const runs = projectRuns([
    event("run_started", { task_id: "task-a", idx: 0 }, 1),
    event("job_failed", { error: "worker stopped" }, 2),
    event("job_reclaimed", { reason: "worker restarted" }, 3),
    event("run_started", { task_id: "task-a", idx: 0 }, 4),
  ]);

  expect(runs.get("task-a:0")?.state).toBe("running");
});

test("does not invent run outcomes from terminal events without a run", () => {
  const runs = projectRuns([
    event("job_canceled", { reason: "cancel requested" }, 1),
  ]);
  expect(runs.size).toBe(0);
});

test("an explicit resume restarts the tape: the earlier cancel no longer interrupts", () => {
  const projection = projectEventTape([
    event("run_started", { task_id: "task-a", idx: 1 }, 1),
    event("job_canceled", { reason: "cancel requested" }, 2),
    event("job_resumed", { evaluation_id: "job" }, 3),
  ]);
  // Before the resume boundary the unfinished run would read "interrupted";
  // after it the position is simply pending again.
  expect(projection.runs.get("task-a:1")?.state).toBe("pending");
  const resumedAndRunning = projectRuns([
    event("run_started", { task_id: "task-a", idx: 1 }, 1),
    event("job_canceled", { reason: "cancel requested" }, 2),
    event("job_resumed", { evaluation_id: "job" }, 3),
    event("run_started", { task_id: "task-a", idx: 1 }, 4),
  ]);
  expect(resumedAndRunning.get("task-a:1")?.state).toBe("running");
});

test("a resume clears task-level errors from before it; a reclaim keeps them", () => {
  const blocked = [
    event("error", { task_id: "task-a", error: "task pack changed" }, 1),
    event("job_failed", { error: "blocked" }, 2),
  ];
  expect(
    projectEventTape([...blocked, event("job_resumed", {}, 3)]).taskErrors.size,
  ).toBe(0);
  expect(
    projectEventTape([...blocked, event("job_reclaimed", {}, 3)]).taskErrors
      .size,
  ).toBe(1);
});

const trial = (overrides: Partial<PersistedTrial>): PersistedTrial => ({
  task_id: "task-a",
  idx: 0,
  trial_state: "completed",
  evidence_state: "fresh",
  run_id: 1221,
  outcome: {
    status: "valid",
    functional_pass: true,
    voided: false,
    final_score: 1,
  },
  error_message: null,
  ...overrides,
});

test("persisted trial rows map to markers without inventing outcomes", () => {
  expect(trialRunView(trial({}))).toMatchObject({
    state: "pass",
    persisted: true,
    runId: 1221,
  });
  expect(
    trialRunView(
      trial({
        outcome: {
          status: "valid",
          functional_pass: false,
          voided: false,
          final_score: 0.2,
        },
      }),
    ).state,
  ).toBe("fail");
  expect(
    trialRunView(
      trial({
        outcome: {
          status: "infra_failure",
          functional_pass: false,
          voided: true,
          final_score: 0,
        },
      }),
    ).state,
  ).toBe("voided");
  // A completed row without a usable score is "outcome unavailable", not a fail.
  expect(trialRunView(trial({ outcome: null })).state).toBe("unknown");
  // Reused evidence is never shown as a fresh pass, whatever it scored.
  expect(
    trialRunView(trial({ evidence_state: "reused", run_id: 900 })),
  ).toMatchObject({ state: "reused", runId: 900 });
  expect(
    trialRunView(
      trial({
        trial_state: "blocked",
        evidence_state: "unverifiable",
        run_id: null,
        outcome: null,
        error_message: "task pack changed",
      }),
    ),
  ).toMatchObject({
    state: "blocked",
    persisted: false,
    runId: undefined,
    error: "task pack changed",
  });
  expect(
    trialRunView(trial({ trial_state: "claimed", run_id: null, outcome: null }))
      .state,
  ).toBe("running");
  expect(
    trialRunView(trial({ trial_state: "pending", run_id: null, outcome: null }))
      .state,
  ).toBe("pending");
  expect(runStateLabel("blocked")).toBe("blocked · not executed");
});

test("a finished trial row outranks the event tape; an unfinished one defers to it", () => {
  const stored = projectTrials([
    trial({}),
    trial({ idx: 1, trial_state: "pending", run_id: null, outcome: null }),
  ]);
  const live = projectRuns([
    event("run_started", { task_id: "task-a", idx: 0 }, 1),
    event("run_started", { task_id: "task-a", idx: 1 }, 2),
  ]);
  // idx 0: the stored pass wins over a stale "running" from the tape.
  expect(
    mergeRunViews(stored.get("task-a:0"), live.get("task-a:0"))?.state,
  ).toBe("pass");
  // idx 1: still pending in storage, so the live "running" is shown.
  expect(
    mergeRunViews(stored.get("task-a:1"), live.get("task-a:1"))?.state,
  ).toBe("running");
  // No live information: the stored row is used as-is.
  expect(mergeRunViews(stored.get("task-a:1"), undefined)?.state).toBe(
    "pending",
  );
  expect(mergeRunViews(undefined, undefined)).toBeUndefined();
});
