import { expect, test } from "@playwright/test";
import type { JobEvent } from "../src/api/types";
import { projectRuns, runStateLabel } from "../src/lib/jobView";

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
