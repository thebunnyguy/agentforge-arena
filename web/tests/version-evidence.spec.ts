// Current vs historical vs missing evidence, evidence scope, and unverifiable
// job parameters. The API is fully mocked with page.route (payload shapes
// follow the implemented contract), so no backend data is assumed; the SPA
// itself is served by the base URL (default config: AFA_TEST_BASE_URL).
import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";
import type { Page, Route } from "@playwright/test";

const AGGREGATE = {
  n_valid: 5,
  n_pass: 2,
  pass_rate: 0.4,
  wilson_low: 0.1176,
  wilson_high: 0.7693,
  mean_s: 0.58,
  median_s: 0.9,
  min_s: 0,
  max_s: 1,
  std_s: 0.53,
  stability: 0,
  conservative_continuous: 0.07,
  timeout_rate: 0.2,
  infra_void_rate: 0,
  reliability: 0.8,
  pass_at_k: { "1": 0.4 },
  deterministic: false,
  bimodal: false,
  provisional: false,
};

const score = (pass: boolean) => ({
  status: "valid",
  gate_product: pass ? 1 : 0,
  t_hidden: pass ? 1 : 0.3,
  q: 1,
  q_components: {},
  q_components_available: false,
  final_score: pass ? 1 : 0,
  functional_pass: pass,
  voided: false,
});

const run = (idx: number, runId: number, version: string) => ({
  agent: "qwen3.5:9b",
  task_id: "sanitize-filename",
  idx,
  run_id: runId,
  task_version: version,
  status: "valid",
  score: score(idx % 2 === 0),
  backend_kind: null,
  evidence_class: "legacy",
});

const cellBase = {
  agent: "qwen3.5:9b",
  task_id: "sanitize-filename",
  known_task: true,
  synthetic: false,
  evidence_scope: "benchmark",
  current_version: "1.0.2",
  excluded: { synthetic_runs: 0, provenance_conflict_runs: 0 },
  task_versions: ["1.0.1"],
};

const HISTORICAL_ONLY_DEFAULT = {
  ...cellBase,
  state: "historical_only",
  captured: false,
  has_current_evidence: false,
  has_historical_evidence: true,
  selected_version: "1.0.2",
  evidence_status: "none",
  current_runs: 0,
  historical_runs: 5,
  historical_versions: ["1.0.1"],
  runs: [],
  aggregate: null,
  versions: [
    {
      version: "1.0.1",
      status: "historical",
      n_runs: 5,
      run_ids: [1156, 1157, 1158, 1159, 1160],
      aggregate: AGGREGATE,
    },
  ],
};

const HISTORICAL_VIEW = {
  ...HISTORICAL_ONLY_DEFAULT,
  selected_version: "1.0.1",
  evidence_status: "historical",
  runs: [1156, 1157, 1158].map((id, i) => run(i, id, "1.0.1")),
  aggregate: AGGREGATE,
};

const CURRENT_CELL = {
  ...cellBase,
  state: "captured",
  captured: true,
  task_versions: ["1.0.2"],
  has_current_evidence: true,
  has_historical_evidence: false,
  selected_version: "1.0.2",
  evidence_status: "current",
  current_runs: 5,
  historical_runs: 0,
  historical_versions: [],
  runs: [2001, 2002].map((id, i) => run(i, id, "1.0.2")),
  aggregate: AGGREGATE,
  versions: [
    {
      version: "1.0.2",
      status: "current",
      n_runs: 5,
      run_ids: [2001, 2002],
      aggregate: AGGREGATE,
    },
  ],
};

const entry = (agent: string, rank: number) => ({
  agent,
  pass_rate: 0.7,
  wilson_low: 0.5,
  wilson_high: 0.85,
  n: 30,
  provisional: false,
  rank_low: rank,
  rank_high: rank,
  synthetic: false,
  coverage: {
    tasks_with_current_evidence: 6,
    tasks_total: 24,
    complete: false,
  },
});

const META = {
  evidence_scope: "benchmark",
  models: ["alpha:7b", "ghost:1b"],
  current_models: ["alpha:7b"],
  historical_only_models: ["ghost:1b"],
  synthetic_agents: [],
  n_tasks: 24,
  tasks: [
    {
      task_id: "sanitize-filename",
      current_version: "1.0.2",
      evaluated_versions: ["1.0.1"],
      current_runs: 0,
      historical_runs: 5,
      historical_versions: ["1.0.1"],
      has_current_evidence: false,
      models_with_current_evidence: 0,
      domains: [{ domain: "backend", weight: 1 }],
      activity: "bugfix",
    },
  ],
  observability: {
    total_runs: 210,
    first_created_at: "2026-06-18 06:11:14",
    last_created_at: "2026-09-17 11:49:05",
    runs_with_patch: 200,
    runs_with_test_results: 200,
    test_result_rows: 100,
  },
  real_counts: {
    "alpha:7b": { n_runs: 30, n_tasks: 6 },
    "ghost:1b": { n_runs: 0, n_tasks: 0 },
  },
  evidence_counts: {
    "alpha:7b": {
      current_runs: 30,
      current_tasks: 6,
      current_by_class: { legacy: 30 },
      historical_runs: 90,
      historical_tasks: 18,
      historical_only_tasks: 18,
      tasks_total: 24,
      coverage_complete: false,
    },
    "ghost:1b": {
      current_runs: 0,
      current_tasks: 0,
      current_by_class: {},
      historical_runs: 90,
      historical_tasks: 18,
      historical_only_tasks: 18,
      tasks_total: 24,
      coverage_complete: false,
    },
  },
  current_benchmark: {
    n_tasks: 24,
    tasks_with_current_evidence: 6,
    current_runs: 30,
    historical_runs: 180,
    models_with_current_evidence: 1,
    models_total: 2,
  },
  excluded: {
    synthetic_runs: 0,
    synthetic_models: [],
    provenance_conflict_runs: 0,
  },
  notes: { trust: "Trusted local." },
};

const json = (route: Route, body: unknown, status = 200) =>
  route.fulfill({
    status,
    contentType: "application/json",
    body: JSON.stringify(body),
  });

type Handler = (url: URL) => unknown | undefined;

// Installs one catch-all API mock; `overrides` answer first, the rest is a
// small consistent default. Returns the list of API URLs requested.
async function mockApi(page: Page, overrides: Handler) {
  const seen: string[] = [];
  await page.route("**/api/v1/**", async (route) => {
    const url = new URL(route.request().url());
    const path = url.pathname.replace("/api/v1", "");
    seen.push(path + url.search);
    const custom = overrides(url);
    if (custom !== undefined) return json(route, custom);
    if (path === "/healthz")
      return json(route, {
        status: "ok",
        stores_loaded: true,
        load_error: null,
        db_path: "x",
      });
    if (path === "/meta") return json(route, META);
    if (path === "/settings")
      return json(route, {
        ollama_base_url: "http://localhost:11434",
        openai_base_url: null,
        default_backend: "mock",
        default_temperature: 0.8,
        default_repeats: 1,
        default_request_timeout_s: 180,
        extra: {},
      });
    if (path === "/jobs") return json(route, { jobs: [] });
    if (/^\/jobs\/.+\/events$/.test(path) && !url.searchParams.has("since"))
      return route.abort();
    if (/^\/jobs\/.+\/events$/.test(path))
      return json(route, { job_id: "x", events: [] });
    if (path.startsWith("/domains/"))
      return json(route, {
        agent: decodeURIComponent(path.split("/")[2]),
        captured: !path.includes("ghost"),
        synthetic: false,
        evidence_scope: "benchmark",
        evidence_status: path.includes("ghost") ? "historical_only" : "current",
        coverage: {
          current_tasks: path.includes("ghost") ? 0 : 6,
          historical_only_tasks: 18,
          tasks_total: 24,
        },
        domains: [
          {
            domain: "backend",
            pooled_pass_rate: 0.5,
            n_eff: 5,
            wilson_low: 0.2,
            wilson_high: 0.8,
            stability: 0.3,
            n_tasks: 1,
            n_runs: 5,
            displayable: false,
          },
        ],
      });
    return json(route, { error: `unmocked ${path}` }, 404);
  });
  return seen;
}

async function noSeriousAxe(page: Page) {
  const axe = await new AxeBuilder({ page }).analyze();
  const bad = axe.violations.filter((v) =>
    ["serious", "critical"].includes(v.impact ?? ""),
  );
  expect(bad.map((v) => `${v.id}: ${v.nodes[0]?.target}`)).toEqual([]);
}

const cellUrl = "/cell/qwen3.5%3A9b/sanitize-filename";
const cellApi = (url: URL) =>
  url.pathname.startsWith("/api/v1/cell/")
    ? url.searchParams.get("version") === "1.0.1"
      ? HISTORICAL_VIEW
      : HISTORICAL_ONLY_DEFAULT
    : undefined;

test("historical-only cell says NONE current / AVAILABLE historical and never prints the current version as evidence", async ({
  page,
}) => {
  await mockApi(page, cellApi);
  await page.goto(cellUrl, { waitUntil: "networkidle" });
  const facts = page.getByLabel("Evidence status");
  await expect(facts).toContainText("Current task version");
  await expect(facts).toContainText("1.0.2");
  await expect(facts).toContainText("MISSING CURRENT");
  await expect(facts).toContainText("Current benchmark evidence");
  await expect(facts).toContainText("NONE");
  await expect(facts).toContainText("AVAILABLE (versions 1.0.1; 5 runs)");
  // No "Evidence version" row at all: nothing is shown at the current version.
  await expect(facts).not.toContainText("Evidence version");
  await expect(
    page.getByRole("heading", { name: "MISSING current evidence" }),
  ).toBeVisible();
  await expect(page.locator(".panel .data").first()).toContainText(
    "HISTORICAL",
  );
  await noSeriousAxe(page);
});

test("?version=old shows the HISTORICAL evidence view with run links by run id", async ({
  page,
}) => {
  await mockApi(page, cellApi);
  await page.goto(`${cellUrl}?version=1.0.1`, { waitUntil: "networkidle" });
  const facts = page.getByLabel("Evidence status");
  await expect(
    facts.locator("div", { hasText: "Evidence version" }).first(),
  ).toContainText("1.0.1");
  await expect(facts).toContainText("Current task version");
  await expect(facts).toContainText("HISTORICAL");
  await expect(
    page.getByText("HISTORICAL evidence", { exact: false }).first(),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", {
      name: "What this HISTORICAL evidence supports",
    }),
  ).toBeVisible();
  const links = page.getByRole("link", { name: /Forensics/ });
  await expect(links).toHaveCount(3);
  await expect(links.first()).toHaveAttribute("href", "/runs/1156");
  await expect(page.locator("table.data tbody tr").last()).toContainText(
    "1.0.1",
  );
  await expect(page.locator("table.data tbody tr").last()).toContainText(
    "LEGACY",
  );
  await noSeriousAxe(page);
});

test("current cell shows evidence version = current version with a CURRENT badge", async ({
  page,
}) => {
  await mockApi(page, (url) =>
    url.pathname.startsWith("/api/v1/cell/") ? CURRENT_CELL : undefined,
  );
  await page.goto(cellUrl, { waitUntil: "networkidle" });
  const facts = page.getByLabel("Evidence status");
  await expect(facts).toContainText("Evidence version");
  await expect(facts).toContainText("CURRENT");
  await expect(facts).toContainText("AVAILABLE (5 runs)");
  await expect(facts).not.toContainText("HISTORICAL");
  await expect(page.locator(".inline-notice.notice-warn")).toHaveCount(0);
  await expect(
    page.getByRole("link", { name: /Forensics/ }).first(),
  ).toHaveAttribute("href", "/runs/2001");
});

test("leaderboard lists a historical-only model as MISSING current evidence, unranked, with server coverage", async ({
  page,
}) => {
  const seen = await mockApi(page, (url) =>
    url.pathname === "/api/v1/leaderboard"
      ? {
          task_id: null,
          found: true,
          evidence_scope: url.searchParams.get("evidence") ?? "benchmark",
          current_version: null,
          version: null,
          evidence_status: null,
          entries: [entry("alpha:7b", 1)],
          historical_only_agents: ["ghost:1b"],
        }
      : undefined,
  );
  await page.goto("/leaderboard", { waitUntil: "networkidle" });
  await expect(
    page.getByText("CURRENT benchmark evidence.", { exact: false }).first(),
  ).toBeVisible();
  await expect(
    page.getByText("Coverage: 6/24 tasks with current evidence"),
  ).toBeVisible();
  const ghost = page.locator("tr", { hasText: "ghost:1b" }).first();
  await expect(ghost).toContainText("MISSING current evidence");
  await expect(ghost).toContainText("historical evidence available");
  await expect(ghost).toContainText("NOT RANKED");
  const alpha = page.locator("tr", { hasText: "alpha:7b" }).first();
  await expect(alpha).toContainText("PARTIAL COVERAGE");
  await expect(alpha).toContainText("6/24");
  // The evidence selector is a labelled select bound to ?evidence=.
  await page.getByLabel("Evidence scope").first().selectOption("synthetic");
  await expect(page).toHaveURL(/evidence=synthetic/);
  await expect(
    page.getByText("Synthetic - not benchmark evidence.").first(),
  ).toBeVisible();
  expect(seen.some((u) => u.includes("evidence=synthetic"))).toBeTruthy();
  await noSeriousAxe(page);
});

test("agents page keeps a historical-only model visible and unranked", async ({
  page,
}) => {
  await mockApi(page, (url) =>
    url.pathname === "/api/v1/leaderboard"
      ? {
          task_id: null,
          found: true,
          entries: [entry("alpha:7b", 1)],
          historical_only_agents: ["ghost:1b"],
        }
      : undefined,
  );
  await page.goto("/agents", { waitUntil: "networkidle" });
  const ghost = page.locator("tr", { hasText: "ghost:1b" }).first();
  await expect(ghost).toContainText("MISSING current evidence");
  await expect(ghost).toContainText("NOT RANKED");
  await expect(page.locator("tr", { hasText: "alpha:7b" })).toContainText(
    "6/24",
  );
});

test("task detail marks n=0 entries as missing (not 0%) and offers the historical version", async ({
  page,
}) => {
  await mockApi(page, (url) => {
    if (url.pathname !== "/api/v1/leaderboard") return undefined;
    const version = url.searchParams.get("version");
    const zero = (agent: string) => ({
      agent,
      pass_rate: 0,
      wilson_low: 0,
      wilson_high: 1,
      n: 0,
      provisional: true,
      rank_low: null,
      rank_high: null,
      synthetic: false,
    });
    return version
      ? {
          task_id: "sanitize-filename",
          found: true,
          current_version: "1.0.2",
          version,
          evidence_status: "historical",
          entries: [
            { ...entry("alpha:7b", 1), coverage: undefined },
            zero("ghost:1b"),
          ],
          historical_only_agents: [],
        }
      : {
          task_id: "sanitize-filename",
          found: true,
          current_version: "1.0.2",
          version: "1.0.2",
          evidence_status: "current",
          entries: [zero("alpha:7b"), zero("ghost:1b")],
          historical_only_agents: ["alpha:7b", "ghost:1b"],
        };
  });
  await page.goto("/task/sanitize-filename", { waitUntil: "networkidle" });
  await expect(
    page.getByText("Current benchmark evidence: NONE"),
  ).toBeVisible();
  const row = page.locator("tr", { hasText: "ghost:1b" }).first();
  await expect(row).toContainText("MISSING current evidence");
  await expect(row).not.toContainText("0.0%");
  await page.getByLabel("Task version").selectOption("1.0.1");
  await expect(page).toHaveURL(/version=1.0.1/);
  await expect(
    page.getByText("HISTORICAL", { exact: false }).first(),
  ).toBeVisible();
  // No rank column in a historical view.
  await expect(page.locator("th", { hasText: /^rank$/i })).toHaveCount(0);
});

const params = {
  backend: { kind: "mock", base_url: null },
  model: "mock-model",
  name: "mock-model",
  tasks: ["fix-binary-search"],
  repeats: 1,
  base_seed: 42,
  temperature: 0.8,
  request_timeout_s: 180,
};
const jobBase = {
  id: "job-bad-0001",
  cancel_requested: false,
  counters: {
    total_runs: 1,
    completed_runs: 0,
    passed_runs: 0,
    voided_runs: 0,
    failed_runs: 0,
    reused_runs: 0,
  },
  created_at: "2026-09-09 20:00:00",
  started_at: "2026-09-09 20:00:01",
  finished_at: "2026-09-09 20:00:02",
};
const REASON = "invalid persisted evaluation parameters: temperature";
const BAD_JOB = {
  ...jobBase,
  status: "failed",
  params: null,
  params_status: "unverifiable",
  params_error: REASON,
  backend_kind: null,
  evidence_class: "unknown",
  error_message: REASON,
};
const MOCK_JOB = {
  ...jobBase,
  id: "job-mock-0001",
  status: "succeeded",
  params,
  params_status: "available",
  params_error: null,
  backend_kind: "mock",
  evidence_class: "synthetic",
  counters: { ...jobBase.counters, completed_runs: 1, passed_runs: 1 },
  error_message: null,
};

test("unverifiable job: monitor, list, results and run pages never dereference null params", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  const seen = await mockApi(page, (url) => {
    if (url.pathname === "/api/v1/jobs") return { jobs: [BAD_JOB, MOCK_JOB] };
    if (url.pathname === "/api/v1/jobs/job-bad-0001") return BAD_JOB;
    if (url.pathname === "/api/v1/jobs/job-mock-0001") return MOCK_JOB;
    return undefined;
  });
  await page.goto("/jobs/job-bad-0001", { waitUntil: "networkidle" });
  await expect(
    page.getByRole("heading", { name: "Evaluation parameters unavailable" }),
  ).toBeVisible();
  await expect(page.getByText(REASON).first()).toBeVisible();
  await expect(page.getByRole("button", { name: /Retry/ })).toHaveCount(0);
  await expect(page.getByText("UNVERIFIABLE PARAMETERS").first()).toBeVisible();
  await expect(page.getByText("Failed", { exact: true }).first()).toBeVisible();
  await expect(
    page.getByText("unknown - parameters unverifiable"),
  ).toBeVisible();
  await noSeriousAxe(page);

  await page.goto("/jobs", { waitUntil: "networkidle" });
  await page.getByLabel("Search evaluations").fill("mock-model");
  const cards = page.locator(".evaluation-card");
  await expect(cards).toHaveCount(1);
  await expect(cards.first()).toContainText("excluded from benchmark results");
  await page.getByLabel("Search evaluations").fill("");
  await expect(cards).toHaveCount(2);
  const bad = cards.filter({ hasText: "Evaluation parameters unavailable" });
  await expect(bad).toContainText("UNVERIFIABLE PARAMETERS");
  await expect(bad.getByRole("button", { name: "Retry" })).toHaveCount(0);

  await page.goto("/jobs/job-bad-0001/results", { waitUntil: "networkidle" });
  await expect(
    page.getByRole("heading", { name: "Evaluation parameters unavailable" }),
  ).toBeVisible();
  expect(seen.some((u) => u.startsWith("/cell/"))).toBe(false);

  await page.goto("/jobs/job-bad-0001/runs/fix-binary-search/0", {
    waitUntil: "networkidle",
  });
  await expect(
    page.getByRole("heading", { name: "Evaluation parameters unavailable" }),
  ).toBeVisible();
  expect(errors).toEqual([]);
});

test("evaluation cards never clip their actions or overlap columns at any width", async ({
  page,
}) => {
  await mockApi(page, (url) => {
    if (url.pathname === "/api/v1/jobs") return { jobs: [BAD_JOB, MOCK_JOB] };
    if (url.pathname === "/api/v1/overview")
      return {
        models: [],
        task_ids: [],
        n_tasks: 24,
        real_counts: {},
        observability: META.observability,
        agent_observability: {},
        leaderboard: [],
        synthetic_agents: [],
        evidence_scope: "benchmark",
        current_models: [],
        historical_only_models: [],
        evidence_counts: {},
        current_benchmark: META.current_benchmark,
        excluded: META.excluded,
      };
    return undefined;
  });
  for (const width of [1440, 1280, 1100, 900, 390]) {
    await page.setViewportSize({ width, height: 900 });
    for (const path of ["/", "/jobs"]) {
      await page.goto(path, { waitUntil: "networkidle" });
      const cards = page.locator(".evaluation-card");
      await expect(cards).toHaveCount(2);
      const problems = await cards.evaluateAll((els) =>
        els.flatMap((card) => {
          const out: string[] = [];
          const box = card.getBoundingClientRect();
          const kids = [...card.children] as HTMLElement[];
          const rects = kids.map((kid) => kid.getBoundingClientRect());
          kids.forEach((kid, i) => {
            const r = rects[i];
            const name = kid.className || kid.tagName;
            if (r.right > box.right + 1 || r.left < box.left - 1)
              out.push(
                `${name} leaves the card (${r.left}..${r.right} vs ${box.left}..${box.right})`,
              );
            if (kid.scrollWidth > kid.clientWidth + 1)
              out.push(
                `${name} overflows its own box (${kid.scrollWidth} > ${kid.clientWidth})`,
              );
            kids.forEach((other, j) => {
              if (j <= i) return;
              const o = rects[j];
              const w = Math.min(r.right, o.right) - Math.max(r.left, o.left);
              const h = Math.min(r.bottom, o.bottom) - Math.max(r.top, o.top);
              if (w > 1 && h > 1)
                out.push(
                  `${name} overlaps ${other.className || other.tagName}`,
                );
            });
          });
          return out;
        }),
      );
      expect(problems, `${path} @${width}px`).toEqual([]);
    }
  }
});

test("mock job results explain the benchmark exclusion instead of 'not available'", async ({
  page,
}) => {
  const seen = await mockApi(page, (url) => {
    if (url.pathname === "/api/v1/jobs/job-mock-0001") return MOCK_JOB;
    if (url.pathname.startsWith("/api/v1/cell/"))
      return {
        ...CURRENT_CELL,
        agent: "mock-model",
        task_id: "fix-binary-search",
        synthetic: false,
        evidence_scope: url.searchParams.get("evidence"),
      };
    return undefined;
  });
  await page.goto("/jobs/job-mock-0001/results", { waitUntil: "networkidle" });
  await expect(
    page
      .getByText("Synthetic - not benchmark evidence.", { exact: false })
      .first(),
  ).toBeVisible();
  await expect(page.getByText("not available in loaded snapshot")).toHaveCount(
    0,
  );
  await expect(
    page.getByRole("link", { name: "Open the synthetic view" }),
  ).toHaveAttribute("href", "/leaderboard?evidence=synthetic");
  expect(
    seen.some((u) => u.includes("/cell/") && u.includes("evidence=synthetic")),
  ).toBe(true);
});

test("new evaluation labels the Mock backend as synthetic", async ({
  page,
}) => {
  await mockApi(page, () => undefined);
  await page.goto("/new", { waitUntil: "networkidle" });
  await expect(page.getByRole("button", { name: /Mock/ })).toContainText(
    "Synthetic - excluded from benchmark results",
  );
});

for (const width of [375, 1440]) {
  test(`mocked evidence states do not overflow at ${width}px`, async ({
    page,
  }) => {
    await page.setViewportSize({ width, height: 900 });
    await mockApi(page, (url) => {
      if (url.pathname.startsWith("/api/v1/cell/"))
        return url.searchParams.get("version")
          ? HISTORICAL_VIEW
          : HISTORICAL_ONLY_DEFAULT;
      if (url.pathname === "/api/v1/leaderboard")
        return {
          task_id: null,
          found: true,
          entries: [entry("alpha:7b", 1)],
          historical_only_agents: ["ghost:1b"],
        };
      if (url.pathname === "/api/v1/jobs") return { jobs: [BAD_JOB, MOCK_JOB] };
      if (url.pathname === "/api/v1/jobs/job-bad-0001") return BAD_JOB;
      return undefined;
    });
    for (const path of [
      cellUrl,
      `${cellUrl}?version=1.0.1`,
      "/leaderboard",
      "/agents",
      "/jobs",
      "/jobs/job-bad-0001",
    ]) {
      await page.goto(path, { waitUntil: "networkidle" });
      const overflow = await page.evaluate(
        () => document.documentElement.scrollWidth > window.innerWidth + 1,
      );
      expect(overflow, path).toBe(false);
      if (process.env.AFA_SHOTS)
        await page.screenshot({
          path: `test-artifacts/mock-${path.replace(/[^a-z0-9]+/gi, "_")}-${width}.png`,
          fullPage: true,
        });
    }
  });
}

test("run page by run id labels evidence version, current version and status", async ({
  page,
}) => {
  await mockApi(page, (url) =>
    url.pathname === "/api/v1/runs/1156"
      ? {
          run_id: 1156,
          job_id: null,
          agent: "qwen3.5:9b",
          task_id: "sanitize-filename",
          idx: 0,
          found: true,
          synthetic: false,
          captured: true,
          known_task: true,
          task_version: "1.0.1",
          backend_kind: null,
          evidence_class: "legacy",
          provider_source: "none",
          version_status: "historical",
          current_version: "1.0.2",
          status: "valid",
          score: score(false),
          patch_available: false,
          test_results: [],
        }
      : undefined,
  );
  await page.goto("/runs/1156", { waitUntil: "networkidle" });
  await expect(page.getByRole("heading", { name: "Run #0" })).toBeVisible();
  const facts = page.getByLabel("Run evidence status");
  await expect(facts).toContainText("Evidence version");
  await expect(facts).toContainText("1.0.1");
  await expect(facts).toContainText("Current task version");
  await expect(facts).toContainText("1.0.2");
  await expect(facts).toContainText("HISTORICAL");
  await expect(facts).toContainText("LEGACY · unknown provider");
  await noSeriousAxe(page);
});

test("agent profile with only historical evidence is not ranked", async ({
  page,
}) => {
  await mockApi(page, (url) => {
    if (url.pathname === "/api/v1/leaderboard")
      return {
        task_id: null,
        found: true,
        entries: [entry("alpha:7b", 1)],
        historical_only_agents: ["ghost:1b"],
      };
    if (url.pathname.startsWith("/api/v1/cell/"))
      return { ...HISTORICAL_ONLY_DEFAULT, agent: "ghost:1b" };
    return undefined;
  });
  await page.goto("/agent/ghost%3A1b", { waitUntil: "networkidle" });
  await expect(
    page.getByText("Current benchmark evidence: NONE"),
  ).toBeVisible();
  await expect(
    page.getByText("Historical evidence: AVAILABLE").first(),
  ).toBeVisible();
  await expect(
    page.getByText("not ranked", { exact: false }).first(),
  ).toBeVisible();
  await expect(
    page.locator(".metric", { hasText: "Current coverage" }),
  ).toContainText("0/24");
  await noSeriousAxe(page);
});

// ------------------ Evaluation-scoped results (GET /jobs/{id}/...) ------------------ //

const EVAL_ID = "job-eval-0001";
const EVAL_JOB = {
  ...MOCK_JOB,
  id: EVAL_ID,
  status: "failed",
  params: { ...params, tasks: ["fix-binary-search"], repeats: 2 },
  counters: {
    ...jobBase.counters,
    total_runs: 2,
    completed_runs: 1,
    passed_runs: 1,
  },
  error_message: "task pack changed for fix-binary-search",
};
const TRIAL_PASS = {
  evaluation_id: EVAL_ID,
  task_id: "fix-binary-search",
  idx: 0,
  task_version: "1.0.0",
  trial_state: "completed",
  evidence_state: "fresh",
  run_id: 1221,
  source_evaluation_id: null,
  source_run_id: null,
  origin_evaluation_id: EVAL_ID,
  error_message: null,
  backend_kind: "mock",
  provenance: "consistent",
  outcome: {
    status: "valid",
    functional_pass: true,
    voided: false,
    final_score: 1,
  },
  artifact_state: "complete",
  comparability: "comparable",
};
const TRIAL_BLOCKED = {
  ...TRIAL_PASS,
  idx: 1,
  trial_state: "blocked",
  evidence_state: "unverifiable",
  run_id: null,
  origin_evaluation_id: null,
  error_message: "task pack changed for fix-binary-search",
  backend_kind: null,
  provenance: "unknown",
  outcome: null,
  artifact_state: "absent",
  comparability: undefined,
};
const reportTrial = ({
  evaluation_id: _id,
  ...trial
}: typeof TRIAL_PASS | typeof TRIAL_BLOCKED) => ({
  ...trial,
  task_digest:
    "sha256:97d42f89f91ca3ba10ee968ac43ec0281bd986ece26f76f6a7bdaef7c13484ce",
  comparability: trial.comparability ?? null,
});
const LIMITATION =
  "fix-binary-search trial 1 is blocked; no completed outcome is available.";
const REPORT = {
  schema_version: 1,
  evaluation_id: EVAL_ID,
  status: "failed",
  mode: "fresh",
  created_at: "2026-09-09 20:00:00",
  started_at: "2026-09-09 20:00:01",
  finished_at: "2026-09-09 20:00:02",
  model: "mock-model",
  backend: { kind: "mock", base_url: null },
  provider: "mock",
  evaluation_parameters: {
    model: "mock-model",
    name: "mock-model",
    repeats: 2,
    base_seed: 42,
    temperature: 0.8,
    request_timeout_s: 180,
    backend: { kind: "mock", base_url: null },
    source_evaluation_id: null,
  },
  generation: {
    base_seed: 42,
    temperature: 0.8,
    request_timeout_s: 180,
    seed_provenance: "unavailable",
    timeout_provenance: "not_applicable",
  },
  task_snapshots: [
    {
      task_id: "fix-binary-search",
      task_version: "1.0.0",
      task_digest:
        "sha256:97d42f89f91ca3ba10ee968ac43ec0281bd986ece26f76f6a7bdaef7c13484ce",
    },
  ],
  counters: {
    total: 2,
    completed: 1,
    passed: 1,
    failed: 0,
    voided: 0,
    reused: 0,
    incomplete: 1,
    unavailable: 1,
  },
  counter_semantics: {
    total: "canonical requested evaluation trial rows",
    completed: "completed rows, including reused evidence",
    passed: "fresh completed rows with a usable non-voided passing score",
    failed: "fresh completed rows with a usable non-voided failing score",
    voided: "fresh completed rows with a usable voided score",
    reused: "completed rows explicitly linked to prior evidence",
    incomplete: "rows not in completed trial state",
    unavailable: "rows without a usable outcome",
  },
  trials: [reportTrial(TRIAL_PASS), reportTrial(TRIAL_BLOCKED)],
  limitations: [LIMITATION],
};
const EVAL_RESULTS = {
  evaluation_id: EVAL_ID,
  status: "failed",
  mode: "fresh",
  snapshot: null,
  counters: EVAL_JOB.counters,
  trials: [TRIAL_PASS, TRIAL_BLOCKED],
};
const RUN_1221 = {
  run_id: 1221,
  agent: "mock-model",
  task_id: "fix-binary-search",
  idx: 0,
  found: true,
  synthetic: false,
  captured: true,
  known_task: true,
  task_version: "1.0.0",
  backend_kind: "mock",
  evidence_class: "synthetic",
  provider_source: "run",
  version_status: "current",
  current_version: "1.0.0",
  status: "valid",
  score: score(true),
  patch_available: false,
  test_results: [],
};

test("evaluation results come from the evaluation's own report, not global cells", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  const seen = await mockApi(page, (url) => {
    if (url.pathname === `/api/v1/jobs/${EVAL_ID}`) return EVAL_JOB;
    if (url.pathname === `/api/v1/jobs/${EVAL_ID}/report.json`) return REPORT;
    if (url.pathname.startsWith("/api/v1/cell/"))
      return {
        ...CURRENT_CELL,
        agent: "mock-model",
        task_id: "fix-binary-search",
      };
    return undefined;
  });
  await page.goto(`/jobs/${EVAL_ID}/results`, { waitUntil: "networkidle" });
  expect(seen).toContain(`/jobs/${EVAL_ID}/report.json`);

  // Every report counter has its own labelled cell.
  const metric = (label: string) =>
    page.locator(".metric-group .metric").filter({
      has: page.locator(".metric-label", { hasText: new RegExp(`^${label}$`) }),
    });
  await expect(metric("Completed")).toContainText("1/2");
  await expect(metric("Incomplete")).toContainText("1");
  await expect(metric("No outcome")).toContainText("1");
  await expect(metric("Passed")).toContainText("1");

  // The grid and the trial table are the persisted trial rows.
  await expect(page.locator(".task-run-grid .run-marker.pass")).toHaveCount(1);
  await expect(page.locator(".task-run-grid .run-marker.blocked")).toHaveCount(
    1,
  );
  const trials = page.getByRole("table", { name: "Evaluation trials" });
  const passRow = trials.locator("tr", { hasText: "#0" });
  await expect(passRow).toContainText("PASS");
  await expect(passRow.getByRole("link", { name: "run 1221" })).toHaveAttribute(
    "href",
    `/jobs/${EVAL_ID}/runs/fix-binary-search/0`,
  );
  const blockedRow = trials.locator("tr", { hasText: "#1" });
  await expect(blockedRow).toContainText("blocked");
  await expect(blockedRow).toContainText("unverifiable");
  await expect(blockedRow.getByRole("link")).toHaveCount(0);

  // Provenance and limitations are the server's words, not inferred.
  await expect(
    page.getByRole("table", { name: "Task snapshots" }),
  ).toContainText("97d42f89f91ca3ba");
  await expect(page.locator(".limitation-list")).toContainText(LIMITATION);
  await expect(page.getByRole("link", { name: "Report JSON" })).toHaveAttribute(
    "href",
    new RegExp(`/api/v1/jobs/${EVAL_ID}/report\\.json$`),
  );
  await expect(
    page.getByRole("link", { name: "Report Markdown" }),
  ).toHaveAttribute("href", new RegExp(`/api/v1/jobs/${EVAL_ID}/report\\.md$`));
  await noSeriousAxe(page);
  expect(errors).toEqual([]);
});

test("a job-scoped run link opens the trial's exact run, never the (model, task, idx) tuple", async ({
  page,
}) => {
  const seen = await mockApi(page, (url) => {
    if (url.pathname === `/api/v1/jobs/${EVAL_ID}`) return EVAL_JOB;
    if (url.pathname === `/api/v1/jobs/${EVAL_ID}/trials/fix-binary-search/0`)
      return TRIAL_PASS;
    if (url.pathname === `/api/v1/jobs/${EVAL_ID}/trials/fix-binary-search/1`)
      return TRIAL_BLOCKED;
    if (url.pathname === "/api/v1/runs/1221") return RUN_1221;
    return undefined;
  });
  await page.goto(`/jobs/${EVAL_ID}/runs/fix-binary-search/0`, {
    waitUntil: "networkidle",
  });
  await expect(page.getByRole("heading", { name: "Run #0" })).toBeVisible();
  await expect(
    page.locator(".inline-notice", { hasText: "Evaluation trial." }),
  ).toContainText("run id 1221");
  expect(seen).toContain(`/jobs/${EVAL_ID}/trials/fix-binary-search/0`);
  expect(seen).toContain("/runs/1221");
  // The ambiguous tuple route is never consulted for a job-scoped URL.
  expect(seen.some((u) => u.startsWith("/run/"))).toBe(false);

  await page.goto(`/jobs/${EVAL_ID}/runs/fix-binary-search/1`, {
    waitUntil: "networkidle",
  });
  await expect(
    page.getByRole("heading", { name: "No persisted run for this trial" }),
  ).toBeVisible();
  await expect(
    page.getByText("task pack changed", { exact: false }),
  ).toBeVisible();

  await page.goto(`/jobs/${EVAL_ID}/runs/fix-binary-search/7`, {
    waitUntil: "networkidle",
  });
  await expect(
    page.getByRole("heading", { name: "Trial not found" }),
  ).toBeVisible();
  expect(seen.some((u) => u.startsWith("/run/"))).toBe(false);
});

test("the monitor fills an ended evaluation's grid from its trial rows and can resume it", async ({
  page,
}) => {
  let resumed = false;
  const seen = await mockApi(page, (url) => {
    if (url.pathname === `/api/v1/jobs/${EVAL_ID}`)
      return resumed
        ? {
            ...EVAL_JOB,
            status: "queued",
            finished_at: null,
            error_message: null,
          }
        : EVAL_JOB;
    if (url.pathname === `/api/v1/jobs/${EVAL_ID}/results`) return EVAL_RESULTS;
    if (url.pathname === `/api/v1/jobs/${EVAL_ID}/resume`) {
      resumed = true;
      return {
        ...EVAL_JOB,
        status: "queued",
        finished_at: null,
        error_message: null,
      };
    }
    return undefined;
  });
  await page.goto(`/jobs/${EVAL_ID}`, { waitUntil: "networkidle" });
  // The event history is empty here; the persisted rows still give the pass
  // (linked to its exact run) and the blocked position.
  const grid = page.locator(".task-run-grid");
  await expect(grid.locator(".run-marker.pass")).toHaveCount(1);
  await expect(grid.locator(".run-marker.blocked")).toHaveCount(1);
  await expect(grid.locator(".run-marker.not_run")).toHaveCount(0);
  await expect(grid.locator("a.run-marker-link")).toHaveAttribute(
    "href",
    `/jobs/${EVAL_ID}/runs/fix-binary-search/0`,
  );
  await expect(page.getByRole("link", { name: "JSON" })).toHaveAttribute(
    "href",
    new RegExp(`/api/v1/jobs/${EVAL_ID}/report\\.json$`),
  );

  const resume = page.getByRole("button", { name: /Resume evaluation/ });
  await expect(resume).toBeVisible();
  await resume.click();
  await expect(page.locator(".monitor-title")).toHaveText("Queued");
  await expect(resume).toHaveCount(0);
  expect(seen).toContain(`/jobs/${EVAL_ID}/resume`);
  await expect(page).toHaveURL(new RegExp(`/jobs/${EVAL_ID}$`));
});

test("below-threshold domain evidence is shown as provisional; a domain without runs shows no value", async ({
  page,
}) => {
  const domains = (agent: string) => ({
    agent,
    captured: true,
    synthetic: false,
    evidence_scope: "benchmark",
    evidence_status: agent === "ghost:1b" ? "historical_only" : "current",
    coverage: { current_tasks: 6, historical_only_tasks: 18, tasks_total: 24 },
    domains: [
      {
        domain: "backend",
        pooled_pass_rate: 0.9,
        n_eff: 22.9,
        wilson_low: 0.715,
        wilson_high: 0.97,
        stability: 0.8,
        n_tasks: 5,
        n_runs: 25,
        displayable: true,
      },
      {
        // The kernel's degenerate placeholder: no valid runs, not a 0% score.
        domain: "performance",
        pooled_pass_rate: 0,
        n_eff: 0,
        wilson_low: 0,
        wilson_high: 1,
        stability: 0,
        n_tasks: 0,
        n_runs: 0,
        displayable: false,
      },
      {
        domain: "security",
        pooled_pass_rate: 1,
        n_eff: 5,
        wilson_low: 0.566,
        wilson_high: 1,
        stability: 1,
        n_tasks: 1,
        n_runs: 5,
        displayable: false,
      },
    ],
  });
  await mockApi(page, (url) => {
    if (url.pathname.startsWith("/api/v1/domains/"))
      return domains(decodeURIComponent(url.pathname.split("/").pop() ?? ""));
    if (url.pathname === "/api/v1/leaderboard")
      return {
        task_id: null,
        found: true,
        evidence_scope: "benchmark",
        current_version: null,
        version: null,
        evidence_status: null,
        entries: [entry("alpha:7b", 1)],
        historical_only_agents: ["ghost:1b"],
      };
    if (url.pathname.startsWith("/api/v1/cell/"))
      return { ...CURRENT_CELL, agent: "alpha:7b" };
    return undefined;
  });

  await page.goto("/agent/alpha%3A7b", { waitUntil: "networkidle" });
  const rows = page.locator(".domain-list .domain-row");
  const security = rows.filter({ hasText: "security" });
  await expect(security).toContainText("provisional");
  await expect(security).toContainText("100%");
  await expect(security).toContainText("1 current tasks · 5 runs");
  await expect(security.locator(".wilson-svg")).toHaveCount(1);
  const performance = rows.filter({ hasText: "performance" });
  await expect(performance).toContainText("no current evidence");
  await expect(performance).not.toContainText("0%");
  await expect(performance).not.toContainText("provisional");
  const backend = rows.filter({ hasText: "backend" });
  await expect(backend).toContainText("90%");
  await expect(backend).not.toContainText("provisional");
  await expect(
    page.getByText("Provisional domains have current evidence below", {
      exact: false,
    }),
  ).toBeVisible();
  await noSeriousAxe(page);

  await page.goto("/leaderboard", { waitUntil: "networkidle" });
  const alpha = page.locator("table.matrix tr", { hasText: "alpha:7b" });
  const cells = alpha.locator("td");
  // agent | backend | performance | security (domains sorted by name)
  await expect(cells.nth(1)).toHaveClass(/matrix-heat/);
  await expect(cells.nth(1)).toContainText("90%");
  await expect(cells.nth(2)).toContainText("—");
  await expect(cells.nth(2)).not.toContainText("0%");
  await expect(cells.nth(3)).toHaveClass(/matrix-provisional/);
  await expect(cells.nth(3)).toContainText("100%");
  await expect(cells.nth(3)).toContainText("prov.");
  await noSeriousAxe(page);
  // The cells' visually hidden labels stay anchored inside the scrolled table.
  await page.setViewportSize({ width: 375, height: 800 });
  await page.goto("/leaderboard", { waitUntil: "networkidle" });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth > window.innerWidth + 1,
    ),
  ).toBe(false);
});
