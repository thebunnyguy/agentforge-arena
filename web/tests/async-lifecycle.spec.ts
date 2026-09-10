import { expect, test } from "@playwright/test";
import type { Page } from "@playwright/test";

const job = (
  id: string,
  model: string,
  status: "queued" | "running" | "succeeded" | "failed" | "canceled",
  cancelRequested = false,
) => ({
  id,
  status,
  cancel_requested: cancelRequested,
  params: {
    backend: { kind: "mock", base_url: null },
    model,
    name: model,
    tasks: ["fix-binary-search"],
    repeats: 1,
    base_seed: 42,
    temperature: 0.8,
    request_timeout_s: 180,
  },
  counters: {
    total_runs: 1,
    completed_runs: status === "succeeded" ? 1 : 0,
    passed_runs: status === "succeeded" ? 1 : 0,
    voided_runs: 0,
    failed_runs: 0,
    reused_runs: 0,
  },
  created_at: "2026-09-09 20:00:00",
  started_at: status === "queued" ? null : "2026-09-09 20:00:01",
  finished_at:
    status === "succeeded" || status === "failed" || status === "canceled"
      ? "2026-09-09 20:00:02"
      : null,
  error_message: null,
});

async function installEventSource(
  page: Page,
  mode: "silent" | "transport-error" | "worker-error",
) {
  await page.addInitScript((sourceMode) => {
    class FixtureEventSource {
      onopen: ((event: Event) => void) | null = null;
      onmessage: ((event: MessageEvent<string>) => void) | null = null;
      onerror: ((event: Event) => void) | null = null;
      listeners = new Map<string, Array<(event: Event) => void>>();
      constructor() {
        window.setTimeout(() => {
          this.onopen?.(new Event("open"));
          if (sourceMode === "transport-error") {
            [20, 50, 80].forEach((delay) =>
              window.setTimeout(
                () => this.onerror?.(new Event("error")),
                delay,
              ),
            );
          }
          if (sourceMode === "worker-error") {
            window.setTimeout(() => {
              const event = new MessageEvent("error", {
                data: JSON.stringify({
                  task_id: "fix-binary-search",
                  error: "worker event error",
                }),
                lastEventId: "1",
              });
              this.listeners
                .get("error")
                ?.forEach((listener) => listener(event));
              this.onerror?.(event);
            }, 35);
          }
        }, 0);
      }
      addEventListener(type: string, listener: (event: Event) => void) {
        this.listeners.set(type, [
          ...(this.listeners.get(type) ?? []),
          listener,
        ]);
      }
      removeEventListener() {
        /* fixture */
      }
      close() {
        /* fixture */
      }
    }
    window.EventSource = FixtureEventSource as unknown as typeof EventSource;
  }, mode);
}

const installSilentEventSource = (page: Page) =>
  installEventSource(page, "silent");

const coreMeta = {
  models: ["mock"],
  synthetic_agents: [
    "oracle (synthetic baseline)",
    "noop (synthetic baseline)",
  ],
  n_tasks: 1,
  tasks: [
    {
      task_id: "fix-binary-search",
      current_version: "1.0.0",
      evaluated_versions: ["1.0.0"],
      difficulty: 2,
      activity: "debugging-bugfix",
      scale: "S",
      domains: [],
    },
  ],
  observability: {
    total_runs: 0,
    first_created_at: null,
    last_created_at: null,
    runs_with_patch: 0,
    runs_with_test_results: 0,
    test_result_rows: 0,
  },
  real_counts: {},
  notes: { trust: "Trusted local fixture" },
};
const coreSettings = {
  ollama_base_url: "http://localhost:11434",
  openai_base_url: null,
  default_backend: "mock",
  default_temperature: 0.8,
  default_repeats: 1,
  default_request_timeout_s: 180,
  extra: {},
};

test.beforeEach(async ({ page }) => {
  await page.route(/\/api\/v1\/meta$/, async (route) =>
    route.fulfill({
      contentType: "application/json",
      body: JSON.stringify(coreMeta),
    }),
  );
  await page.route(/\/api\/v1\/healthz$/, async (route) =>
    route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        status: "ok",
        stores_loaded: true,
        load_error: null,
        db_path: "fixture",
      }),
    }),
  );
  await page.route(/\/api\/v1\/settings$/, async (route) =>
    route.fulfill({
      contentType: "application/json",
      body: JSON.stringify(coreSettings),
    }),
  );
  await page.route(/\/api\/v1\/overview$/, async (route) =>
    route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        models: ["mock"],
        task_ids: ["fix-binary-search"],
        n_tasks: 1,
        real_counts: {},
        observability: coreMeta.observability,
        agent_observability: {},
        leaderboard: [],
        synthetic_agents: coreMeta.synthetic_agents,
      }),
    }),
  );
  await page.route(/\/api\/v1\/jobs$/, async (route) =>
    route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ jobs: [] }),
    }),
  );
});

test("verification ignores stale A→B→A responses and accepts a later current response", async ({
  page,
}) => {
  let mockCalls = 0;
  await page.route("**/api/v1/backends/verify", async (route) => {
    const body = route.request().postDataJSON() as { kind: string };
    if (body.kind === "mock") {
      mockCalls += 1;
      if (mockCalls === 1)
        await new Promise((resolve) => setTimeout(resolve, 300));
      await route.fulfill({
        contentType: "application/json",
        body: JSON.stringify({
          kind: "mock",
          ok: true,
          detail:
            mockCalls === 1 ? "stale verification" : "current verification",
          models: ["mock"],
        }),
      });
      return;
    }
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        kind: body.kind,
        ok: false,
        detail: "unavailable fixture",
        models: [],
      }),
    });
  });
  await page.goto("/new", { waitUntil: "networkidle" });
  await page.getByRole("button", { name: "Verify backend" }).click();
  await page.getByRole("button", { name: /Ollama/ }).click();
  await page.getByRole("button", { name: /Mock/ }).click();
  await page.waitForTimeout(400);
  await expect(
    page.getByText("stale verification", { exact: false }),
  ).toHaveCount(0);
  await expect(
    page.getByRole("button", { name: "Verify backend" }),
  ).toBeEnabled();
  await page.getByRole("button", { name: "Verify backend" }).click();
  await expect(
    page.getByText("current verification", { exact: false }),
  ).toBeVisible();
  await expect(page.getByRole("button", { name: "Continue" })).toBeEnabled();
});

test("unavailable and empty model responses block model progression until re-verified", async ({
  page,
}) => {
  let mode: "unavailable" | "empty" | "success" = "unavailable";
  await page.route("**/api/v1/backends/verify", async (route) => {
    const body = route.request().postDataJSON() as { kind: string };
    const response =
      mode === "success"
        ? {
            kind: body.kind,
            ok: true,
            detail: "ready fixture",
            models: ["fixture-model"],
          }
        : mode === "empty"
          ? {
              kind: body.kind,
              ok: true,
              detail: "no models fixture",
              models: [],
            }
          : {
              kind: body.kind,
              ok: false,
              detail: "backend unavailable fixture",
              models: [],
            };
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify(response),
    });
  });
  await page.goto("/new", { waitUntil: "networkidle" });
  await page.getByRole("button", { name: /Ollama/ }).click();
  await page.getByRole("button", { name: "Verify backend" }).click();
  await expect(page.getByText("Could not connect")).toBeVisible();
  await expect(page.getByRole("button", { name: "Continue" })).toBeDisabled();
  mode = "empty";
  await page.getByRole("button", { name: /Mock/ }).click();
  await page.getByRole("button", { name: "Verify backend" }).click();
  await expect(page.getByText("0 models available")).toBeVisible();
  await expect(page.getByRole("button", { name: "Continue" })).toBeEnabled();
  await page.getByRole("button", { name: "Continue" }).click();
  await expect(
    page.getByText("Verify this backend", { exact: false }),
  ).toBeVisible();
  await expect(page.getByRole("button", { name: "Continue" })).toBeDisabled();
  await page.getByRole("button", { name: "Back", exact: true }).click();
  mode = "success";
  await page.getByRole("button", { name: "Verify backend" }).click();
  await page.getByText("1 model available").waitFor();
  await page.getByRole("button", { name: "Continue" }).click();
  await expect(page.getByRole("button", { name: "Continue" })).toBeEnabled();
  await page.getByRole("button", { name: "Continue" }).click();
  await page.locator('.task-option input[type="checkbox"]').first().check();
  await page.getByRole("button", { name: "Continue" }).click();
  await page.getByLabel("Repeats per task").fill("");
  await expect(page.getByLabel("Repeats per task")).toHaveValue("");
  await expect(page.getByRole("button", { name: "Continue" })).toBeDisabled();
});

test("delayed cancel response cannot replace a different job after navigation", async ({
  page,
}) => {
  await installSilentEventSource(page);
  const jobA = job("job-a", "model-a", "running");
  const jobB = job("job-b", "model-b", "running");
  await page.route("**/api/v1/jobs/job-a/events?since=0", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ job_id: "job-a", events: [] }),
    });
  });
  await page.route("**/api/v1/jobs/job-b/events?since=0", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ job_id: "job-b", events: [] }),
    });
  });
  await page.route("**/api/v1/jobs/job-a/cancel", async (route) => {
    await new Promise((resolve) => setTimeout(resolve, 400));
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ ...jobA, cancel_requested: true }),
    });
  });
  await page.route("**/api/v1/jobs/job-a", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify(jobA),
    });
  });
  await page.route("**/api/v1/jobs/job-b", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify(jobB),
    });
  });
  await page.route(/\/api\/v1\/jobs$/, async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ jobs: [jobB] }),
    });
  });
  await page.goto("/jobs/job-a", { waitUntil: "networkidle" });
  await expect(page.getByRole("heading", { name: "model-a" })).toBeVisible();
  await page.getByRole("button", { name: "Cancel evaluation" }).click();
  await page
    .locator(".desktop-sidebar")
    .getByRole("link", { name: "Evaluations", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "Evaluations" }),
  ).toBeVisible();
  await page.getByRole("link", { name: "model-b", exact: true }).click();
  await expect(page.getByRole("heading", { name: "model-b" })).toBeVisible();
  await page.waitForTimeout(500);
  await expect(page.getByText("model-a", { exact: false })).toHaveCount(0);
  await expect(
    page.getByRole("button", { name: "Cancel evaluation" }),
  ).toBeVisible();
});

test("delayed retry cannot navigate away after leaving the old job and cancel_requested hides cancel", async ({
  page,
}) => {
  await installSilentEventSource(page);
  const retryJob = job("job-retry", "model-retry", "succeeded");
  const cancelJob = job("job-cancel", "model-cancel", "running", true);
  await page.route("**/api/v1/jobs/job-retry/events?since=0", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ job_id: "job-retry", events: [] }),
    });
  });
  await page.route(
    "**/api/v1/jobs/job-cancel/events?since=0",
    async (route) => {
      await route.fulfill({
        contentType: "application/json",
        body: JSON.stringify({ job_id: "job-cancel", events: [] }),
      });
    },
  );
  await page.route("**/api/v1/jobs/job-retry", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify(retryJob),
    });
  });
  await page.route("**/api/v1/jobs/job-cancel", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify(cancelJob),
    });
  });
  await page.route(/\/api\/v1\/jobs$/, async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ jobs: [cancelJob] }),
    });
  });
  await page.route("**/api/v1/jobs/job-retry/retry", async (route) => {
    await new Promise((resolve) => setTimeout(resolve, 400));
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify(job("job-new", "model-new", "queued")),
    });
  });
  await page.goto("/jobs/job-retry", { waitUntil: "networkidle" });
  await expect(
    page.getByRole("button", { name: /Retry as new/ }),
  ).toBeVisible();
  await page.getByRole("button", { name: /Retry as new/ }).click();
  await page
    .locator(".desktop-sidebar")
    .getByRole("link", { name: "Overview", exact: true })
    .click();
  await expect(page.getByRole("heading", { name: /Run agents/ })).toBeVisible();
  await page
    .locator(".desktop-sidebar")
    .getByRole("link", { name: "Evaluations", exact: true })
    .click();
  await page.getByRole("link", { name: "model-cancel", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "model-cancel" }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Cancel evaluation" }),
  ).toHaveCount(0);
  await page.waitForTimeout(500);
  await expect(page).toHaveURL(/\/jobs\/job-cancel$/);
});

test("empty canceled history finishes loading without inventing a current run", async ({
  page,
}) => {
  await page.addInitScript(() => {
    Object.defineProperty(window, "EventSource", {
      configurable: true,
      value: undefined,
    });
  });
  const canceled = job("job-empty", "model-empty", "canceled");
  await page.route(
    /\/api\/v1\/jobs\/job-empty(?:\/events.*)?$/,
    async (route) => {
      const url = new URL(route.request().url());
      if (url.pathname.endsWith("/events"))
        await route.fulfill({
          contentType: "application/json",
          body: JSON.stringify({ job_id: "job-empty", events: [] }),
        });
      else
        await route.fulfill({
          contentType: "application/json",
          body: JSON.stringify(canceled),
        });
    },
  );
  await page.goto("/jobs/job-empty", { waitUntil: "networkidle" });
  await expect(
    page.getByRole("heading", { name: "model-empty" }),
  ).toBeVisible();
  await page.getByText("Advanced event evidence", { exact: false }).click();
  await expect(page.getByText("No worker events were recorded.")).toBeVisible();
  await expect(page.getByText("No run is active")).toBeVisible();
});

test("initial JSON replay drains 1000-plus events with persisted timestamps", async ({
  page,
}) => {
  await page.addInitScript(() => {
    Object.defineProperty(window, "EventSource", {
      configurable: true,
      value: undefined,
    });
  });
  const history = Array.from({ length: 1002 }, (_, index) => ({
    job_id: "job-history",
    seq: index + 1,
    ts: "2026-09-09 20:00:00",
    type: "log",
    payload: { sequence: index + 1 },
  }));
  const completed = job("job-history", "model-history", "succeeded");
  let firstPage = true;
  await page.route(
    /\/api\/v1\/jobs\/job-history(?:\/events.*)?$/,
    async (route) => {
      const url = new URL(route.request().url());
      if (url.pathname.endsWith("/events")) {
        const since = Number(url.searchParams.get("since") ?? "0");
        const events =
          firstPage && since === 0
            ? history.slice(0, 1000)
            : since === 1000
              ? history.slice(999)
              : [];
        firstPage = false;
        await route.fulfill({
          contentType: "application/json",
          body: JSON.stringify({ job_id: "job-history", events }),
        });
      } else
        await route.fulfill({
          contentType: "application/json",
          body: JSON.stringify(completed),
        });
    },
  );
  await page.goto("/jobs/job-history", { waitUntil: "networkidle" });
  await page
    .getByText("Advanced event evidence · 1002 events", { exact: false })
    .click();
  await expect(
    page.getByText("Advanced event evidence · 1002 events", { exact: false }),
  ).toBeVisible();
});

test("a named worker error is not treated as a transport failure", async ({
  page,
}) => {
  await installEventSource(page, "worker-error");
  const running = job("job-worker-error", "model-worker-error", "running");
  await page.route(
    /\/api\/v1\/jobs\/job-worker-error(?:\/events.*)?$/,
    async (route) => {
      const url = new URL(route.request().url());
      if (url.pathname.endsWith("/events"))
        await route.fulfill({
          contentType: "application/json",
          body: JSON.stringify({ job_id: "job-worker-error", events: [] }),
        });
      else
        await route.fulfill({
          contentType: "application/json",
          body: JSON.stringify(running),
        });
    },
  );
  await page.goto("/jobs/job-worker-error", { waitUntil: "networkidle" });
  await page.waitForTimeout(150);
  await expect(
    page.getByText("worker error", { exact: false }).first(),
  ).toBeVisible();
  await expect(
    page.getByText("fallback polling", { exact: false }),
  ).toHaveCount(0);
});

test("transport errors fall back to polling and preserve the server pass marker", async ({
  page,
}) => {
  await installEventSource(page, "transport-error");
  const running = job("job-fallback", "model-fallback", "running");
  const completed = job("job-fallback", "model-fallback", "succeeded");
  completed.counters.completed_runs = 1;
  completed.counters.passed_runs = 1;
  const events = [
    {
      job_id: "job-fallback",
      seq: 1,
      ts: "2026-09-09 20:00:01",
      type: "run_started",
      payload: { task_id: "fix-binary-search", idx: 0 },
    },
    {
      job_id: "job-fallback",
      seq: 2,
      ts: "2026-09-09 20:00:02",
      type: "run_graded",
      payload: {
        task_id: "fix-binary-search",
        idx: 0,
        status: "valid",
        functional_pass: true,
      },
    },
    {
      job_id: "job-fallback",
      seq: 3,
      ts: "2026-09-09 20:00:03",
      type: "run_scored",
      payload: {
        task_id: "fix-binary-search",
        idx: 0,
        final_score: 1,
        voided: false,
      },
    },
    {
      job_id: "job-fallback",
      seq: 4,
      ts: "2026-09-09 20:00:04",
      type: "run_persisted",
      payload: { task_id: "fix-binary-search", idx: 0, status: "valid" },
    },
    {
      job_id: "job-fallback",
      seq: 5,
      ts: "2026-09-09 20:00:05",
      type: "job_done",
      payload: { status: "succeeded" },
    },
  ];
  let initialRead = true;
  let pollReads = 0;
  await page.route(
    /\/api\/v1\/jobs\/job-fallback(?:\/events.*)?$/,
    async (route) => {
      const url = new URL(route.request().url());
      if (url.pathname.endsWith("/events")) {
        if (initialRead) {
          initialRead = false;
          await route.fulfill({
            contentType: "application/json",
            body: JSON.stringify({ job_id: "job-fallback", events: [] }),
          });
        } else {
          pollReads += 1;
          await route.fulfill({
            contentType: "application/json",
            body: JSON.stringify({
              job_id: "job-fallback",
              events: pollReads === 1 ? events : [],
            }),
          });
        }
      } else
        await route.fulfill({
          contentType: "application/json",
          body: JSON.stringify(pollReads > 0 ? completed : running),
        });
    },
  );
  await page.goto("/jobs/job-fallback", { waitUntil: "networkidle" });
  await page.waitForTimeout(2500);
  await expect(page.getByText("Evidence tape closed")).toBeVisible();
  await expect(page.locator(".task-run-grid .run-marker.pass")).toHaveCount(1);
  expect(pollReads).toBeGreaterThan(0);
});

test("pending JSON history from an old job cannot paint a new job", async ({
  page,
}) => {
  await installEventSource(page, "silent");
  const oldJob = job("job-nav-old", "model-old", "running");
  const newJob = job("job-nav-new", "model-new", "running");
  await page.route(
    /\/api\/v1\/jobs\/job-nav-old(?:\/events.*)?$/,
    async (route) => {
      const url = new URL(route.request().url());
      if (url.pathname.endsWith("/events")) {
        await new Promise((resolve) => setTimeout(resolve, 400));
        await route.fulfill({
          contentType: "application/json",
          body: JSON.stringify({
            job_id: "job-nav-old",
            events: [
              {
                job_id: "job-nav-old",
                seq: 1,
                ts: "2026-09-09 20:00:00",
                type: "error",
                payload: { task_id: "task-a", error: "old tape" },
              },
            ],
          }),
        });
      } else
        await route.fulfill({
          contentType: "application/json",
          body: JSON.stringify(oldJob),
        });
    },
  );
  await page.route(
    /\/api\/v1\/jobs\/job-nav-new(?:\/events.*)?$/,
    async (route) => {
      const url = new URL(route.request().url());
      if (url.pathname.endsWith("/events"))
        await route.fulfill({
          contentType: "application/json",
          body: JSON.stringify({ job_id: "job-nav-new", events: [] }),
        });
      else
        await route.fulfill({
          contentType: "application/json",
          body: JSON.stringify(newJob),
        });
    },
  );
  const oldNavigation = page
    .goto("/jobs/job-nav-old", { waitUntil: "domcontentloaded" })
    .catch(() => null);
  await page.waitForTimeout(40);
  await page.goto("/jobs/job-nav-new", { waitUntil: "networkidle" });
  await oldNavigation;
  await page.waitForTimeout(500);
  await expect(page.getByRole("heading", { name: "model-new" })).toBeVisible();
  await expect(page.getByText("old tape", { exact: false })).toHaveCount(0);
});
