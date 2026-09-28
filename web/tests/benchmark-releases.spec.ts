// Benchmark Releases pages (static, bundled release data) against a fully
// mocked API, so nothing depends on a live backend. Run with
// `npm run test:benchmarks` (playwright.benchmarks.config.ts starts Vite on
// 4176). Expected values are read from the release datasets (and, for the
// leaderboard, the frozen campaign artifact) with node:fs, so a wrong number
// on screen fails a test.
import { readFileSync } from "node:fs";
import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";
import type { Page, Route } from "@playwright/test";

const dataDir = new URL("../src/data/benchmark-releases/", import.meta.url);
const official = JSON.parse(
  readFileSync(new URL("phase0-modern-local-v1.json", dataDir), "utf8"),
);
const historical = JSON.parse(
  readFileSync(new URL("historical-pre-phase0.json", dataDir), "utf8"),
);
const frozenBoard = JSON.parse(
  readFileSync(
    new URL(
      "../../campaigns/phase0-modern-local-v1/results/outputs/modern-local-leaderboard.json",
      import.meta.url,
    ),
    "utf8",
  ),
);

type Json = any; // eslint-disable-line @typescript-eslint/no-explicit-any

const COMPARABILITY =
  "Historical results are not directly comparable with Modern Local v1. Eighteen of the 24 task definitions changed and the historical runs predate the current evaluation-integrity system.";
const M = official.id as string;
const H = historical.id as string;
const modelUrl = (releaseId: string, modelId: string) =>
  `/benchmarks/${releaseId}/models/${encodeURIComponent(modelId)}`;

// Expected text, built from the data here (not by the app's helpers).
const pct1 = (v: number) => `${(v * 100).toFixed(1)}%`;
const interval = (low: number, high: number) =>
  `${(low * 100).toFixed(1)}–${(high * 100).toFixed(1)}%`;
const rankOf = (rank: { low: number; high: number; provisional: boolean }) =>
  rank.provisional
    ? "provisional"
    : rank.low === rank.high
      ? String(rank.low)
      : `${rank.low}–${rank.high}`;
const INTERVAL_TEXT = /\d+(\.\d+)?\s*[–-]\s*\d+(\.\d+)?%/;
const BAD_TEXT = /\b(NaN|undefined|null|Infinity)\b|\[object Object\]/;

// ---- API mock (copied from version-evidence.spec.ts) --------------------
const META = {
  evidence_scope: "benchmark",
  models: ["alpha:7b"],
  current_models: ["alpha:7b"],
  historical_only_models: [],
  synthetic_agents: [],
  n_tasks: 24,
  tasks: [],
  observability: {
    total_runs: 210,
    first_created_at: "2026-06-18 06:11:14",
    last_created_at: "2026-09-17 11:49:05",
    runs_with_patch: 200,
    runs_with_test_results: 200,
    test_result_rows: 100,
  },
  real_counts: {},
  evidence_counts: {},
  current_benchmark: {
    n_tasks: 24,
    tasks_with_current_evidence: 6,
    current_runs: 30,
    historical_runs: 180,
    models_with_current_evidence: 1,
    models_total: 1,
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

async function mockApi(page: Page) {
  await page.route("**/api/v1/**", async (route) => {
    const url = new URL(route.request().url());
    const path = url.pathname.replace("/api/v1", "");
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
    return json(route, { error: `unmocked ${path}` }, 404);
  });
}

async function noSeriousAxe(page: Page) {
  const axe = await new AxeBuilder({ page }).analyze();
  const bad = axe.violations.filter((v) =>
    ["serious", "critical"].includes(v.impact ?? ""),
  );
  expect(bad.map((v) => `${v.id}: ${v.nodes[0]?.target}`)).toEqual([]);
}

async function layout(page: Page) {
  return page.evaluate(() => {
    const root = document.documentElement;
    const plots = [
      ...document.querySelectorAll<SVGElement>(".wilson-svg"),
    ].filter((plot) => !plot.closest(".table-scroll"));
    return {
      pageOverflow: root.scrollWidth > window.innerWidth + 1,
      plotOverflow: plots.some(
        (plot) => plot.getBoundingClientRect().right > window.innerWidth + 1,
      ),
    };
  });
}

/** Text and title/aria-label/href attributes that leak a JS non-value. */
async function badTextHits(page: Page): Promise<string[]> {
  return page.evaluate((source) => {
    const re = new RegExp(source);
    const hits: string[] = [];
    const main = document.querySelector("main") as HTMLElement;
    for (const line of main.innerText.split("\n"))
      if (re.test(line)) hits.push(`text: ${line.slice(0, 160)}`);
    for (const el of document.querySelectorAll(
      "main [title], main [aria-label], main a[href]",
    ))
      for (const attr of ["title", "aria-label", "href"]) {
        const value = el.getAttribute(attr);
        if (value && re.test(value)) hits.push(`${attr}: ${value}`);
      }
    return hits;
  }, BAD_TEXT.source);
}

const mainText = async (page: Page) =>
  (await page.locator("main").innerText()).replace(/\s+/g, " ");

const panel = (page: Page, title: string) =>
  page.locator("section.panel", {
    has: page.getByRole("heading", { level: 2, name: title, exact: true }),
  });

const releaseLinks = (page: Page) =>
  page.getByRole("navigation", { name: "Benchmark releases" });

const matrixCell = (page: Page, task: string, model: string) =>
  page.locator(
    `table.task-matrix .matrix-cell-button[data-task="${task}"][data-model="${model}"]`,
  );

test.beforeEach(async ({ page }) => {
  await mockApi(page);
});

test("/benchmarks opens the default OFFICIAL release with its headline facts", async ({
  page,
}) => {
  await page.goto("/benchmarks", { waitUntil: "networkidle" });
  await expect(page.locator("h1")).toHaveCount(1);
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(
    official.title,
  );
  const strip = page.locator(".headline-strip");
  await expect(strip.locator("li", { hasText: "fresh runs" })).toHaveText(
    "600 fresh runs",
  );
  await expect(strip.locator("li", { hasText: "evaluations" })).toHaveText(
    "120 evaluations (model × task cells)",
  );
  await expect(strip).not.toContainText("600 evaluations");
  await expect(strip).not.toContainText("120 fresh runs");
  await expect(strip.locator("li", { hasText: "audited tasks" })).toHaveText(
    "24 audited tasks",
  );
  const context = page.locator(".headline-context");
  await expect(context).toContainText("Apple M4 Max · 36 GiB unified memory");
  await expect(context).toContainText("$0 paid API cost");
  await expect(context).toContainText("local Ollama inference");
  // The documented hardware and cost facts carry a visible marker that
  // links to the methodology page, where their sources are shown.
  const markers = context.locator(".doc-marker");
  await expect(markers).toHaveCount(2);
  for (const marker of await markers.all()) {
    await expect(marker).toContainText("documented");
    await expect(marker).toHaveAttribute(
      "href",
      `/benchmarks/${M}/methodology`,
    );
  }
  await expect(page.getByText(official.environment.scope)).toBeVisible();
  // Release switcher: links with the status word and the default marker.
  const links = releaseLinks(page).getByRole("link");
  await expect(links).toHaveCount(2);
  await expect(links.first()).toHaveText(
    /Modern Local v1\s*·\s*OFFICIAL\s*·\s*default/,
  );
  await expect(links.first()).toHaveAttribute("aria-current", "page");
  await expect(links.first()).toHaveAttribute("href", `/benchmarks/${M}`);
  await expect(links.nth(1)).toHaveText(
    /Pre-Phase-0 \(legacy\)\s*·\s*HISTORICAL/,
  );
  await expect(links.nth(1)).not.toHaveAttribute("aria-current", /.+/);
  await expect(page.locator("main select#benchmark-release")).toHaveCount(0);
  const facts = page.locator(".release-facts");
  await expect(facts).toContainText("OFFICIAL");
  await expect(facts.locator("dt", { hasText: "Released" })).toHaveCount(1);
  await expect(facts).toContainText("Sep 28, 2026");
  const ref = page.locator(".release-facts a", {
    hasText: "phase0-modern-local-v1",
  });
  await expect(ref).toHaveAttribute(
    "href",
    "https://github.com/thebunnyguy/agentforge-arena/tree/phase0-modern-local-v1",
  );
  await expect(ref).toHaveAttribute("rel", "noopener noreferrer");
  // Release-level caveat is present and calm (info, not a warning).
  await expect(
    page.locator('.notice-info [data-caveat="historical-not-comparable"]'),
  ).toBeVisible();
  // Nav: the Benchmarks link is active; the shell's breadcrumb needs no data.
  await expect(
    page.locator(".desktop-sidebar").getByRole("link", { name: "Benchmarks" }),
  ).toHaveAttribute("aria-current", "page");
  await expect(page.locator("nav.breadcrumbs")).toHaveText(
    "Overview/Benchmarks",
  );
  await noSeriousAxe(page);
});

test("official leaderboard (desktop): served rank, order, counts and intervals", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto(`/benchmarks/${M}`, { waitUntil: "networkidle" });
  await expect(page.locator(".leaderboard-cards")).toBeHidden();
  const table = page.locator("table.release-leaderboard");
  await expect(table).toBeVisible();
  const rows = table.locator("tbody tr");
  await expect(rows).toHaveCount(frozenBoard.leaderboard.length);
  // Every row equals the FROZEN campaign leaderboard, rank included.
  for (let i = 0; i < frozenBoard.leaderboard.length; i += 1) {
    const want = frozenBoard.leaderboard[i];
    const model = official.models.find((m: Json) => m.id === want.agent);
    const row = rows.nth(i);
    await expect(row.locator("td").first()).toHaveText(
      want.rank_low === want.rank_high
        ? String(want.rank_low)
        : `${want.rank_low}–${want.rank_high}`,
    );
    await expect(row.locator("td").first()).toHaveText(rankOf(model.rank));
    await expect(row.locator('th[scope="row"] a')).toHaveText(
      model.display_name,
    );
    const cells = (await row.locator("td").allInnerTexts()).map((t) =>
      t.replace(/\s+/g, " ").trim(),
    );
    expect(cells[1]).toBe(`${model.totals.passes} / ${want.n}`);
    expect(cells[2]).toBe(pct1(want.pass_rate));
    expect(cells[3]).toContain(interval(want.wilson_low, want.wilson_high));
    expect(cells[4]).toBe("24 / 24");
    expect(cells[5]).toBe(
      `${want.timeouts} (${want.request_timeout_hits} full)`,
    );
    expect(cells[6]).toBe(String(want.agent_errors));
    const box = await row.locator(".bench-interval-text").boundingBox();
    expect(box && box.width > 5 && box.height > 5).toBeTruthy();
  }
  const latency = rows.filter({ hasText: "qwen3.6:27b" });
  await expect(latency).toContainText("105 (83 full)");
  await expect(latency).toContainText("11 / 120");
  await expect(latency).toContainText("5.2–15.7%");
  // Caveat badges on exactly the two caveated rows, as words.
  await expect(table.locator("[data-caveat-badge]")).toHaveCount(2);
  await expect(latency.locator("[data-caveat-badge]")).toHaveText(
    "Latency constrained",
  );
  await expect(
    rows.filter({ hasText: "qwen3-coder:30b" }).locator("[data-caveat-badge]"),
  ).toHaveText("Protocol sensitivity");
  // Plain-language ranking description; the file paths live on the
  // methodology page, which "How ranking works" opens.
  const board = panel(page, "Official leaderboard");
  const description = board.locator(".section-header p");
  await expect(description).toContainText("Wilson 95% lower bound");
  await expect(description).toContainText(
    "Pass rate alone does not order the table.",
  );
  await expect(description).not.toContainText(".py");
  await expect(
    board.getByRole("link", { name: /How ranking works/ }),
  ).toHaveAttribute("href", `/benchmarks/${M}/methodology`);
  await noSeriousAxe(page);
});

test("official leaderboard (375px): stacked cards carry every column without horizontal scrolling", async ({
  page,
}) => {
  await page.setViewportSize({ width: 375, height: 812 });
  await page.goto(`/benchmarks/${M}`, { waitUntil: "networkidle" });
  await expect(page.locator("table.release-leaderboard")).toBeHidden();
  const cards = page.locator(".leaderboard-cards > li");
  await expect(cards).toHaveCount(official.models.length);
  for (let i = 0; i < official.models.length; i += 1) {
    const model = official.models[i];
    const t = model.totals;
    const card = cards.nth(i);
    await expect(card).toBeVisible();
    await expect(card.locator("[data-rank]")).toHaveText(rankOf(model.rank));
    await expect(card.getByRole("link").first()).toHaveText(model.display_name);
    const fact = (label: string) =>
      card.locator(".card-facts > div", {
        has: page.locator("dt", { hasText: new RegExp(`^${label}$`, "i") }),
      });
    await expect(fact("Passes").locator("dd")).toHaveText(
      `${t.passes} / ${t.runs}`,
    );
    await expect(fact("Pass rate").locator("dd")).toHaveText(pct1(t.pass_rate));
    await expect(fact("Wilson 95%").locator(".bench-interval-text")).toHaveText(
      interval(t.wilson_low, t.wilson_high),
    );
    await expect(fact("Wilson 95%").locator(".wilson-svg")).toBeVisible();
    await expect(fact("Coverage").locator("dd")).toHaveText("24 / 24");
    await expect(fact("Timeouts \\(full\\)").locator("dd")).toHaveText(
      `${t.timeouts} (${t.request_timeout_hits} full)`,
    );
    await expect(fact("Agent errors").locator("dd")).toHaveText(
      String(t.agent_errors),
    );
    const box = await card.boundingBox();
    expect(box!.x).toBeGreaterThanOrEqual(0);
    expect(box!.x + box!.width).toBeLessThanOrEqual(375);
  }
  const result = await layout(page);
  expect(result.pageOverflow).toBe(false);
  expect(result.plotOverflow).toBe(false);
  await noSeriousAxe(page);
});

test("reading these results shows every model caveat's summary and points", async ({
  page,
}) => {
  await page.goto("/benchmarks", { waitUntil: "networkidle" });
  const reading = panel(page, "Reading these results");
  const modelCaveats = official.caveats.filter((c: Json) => c.model !== null);
  await expect(reading.locator("li[data-caveat]")).toHaveCount(
    modelCaveats.length,
  );
  for (const caveat of modelCaveats) {
    const item = reading.locator(`li[data-caveat="${caveat.id}"]`);
    await expect(item).toContainText(caveat.label);
    await expect(item).toContainText(caveat.summary);
    for (const point of caveat.points) await expect(item).toContainText(point);
    await expect(item).toContainText(caveat.source);
    // Calm styling: a neutral word badge, not a warning.
    await expect(item.locator(".badge.neutral")).toHaveText(caveat.label);
  }
  const text = await reading.innerText();
  for (const phrase of [
    "96 of 120 campaign runs produced no applied edit.",
    "not independently proven for all 96",
    "not a finding that the model has poor underlying coding capability",
    "105 of 120 runs were classified as timeouts.",
    "83 of them were full 180-second model request timeouts.",
    "uniform local time budget",
  ])
    expect(text.replace(/\s+/g, " ")).toContain(phrase);
  await expect(
    reading.getByRole("link", { name: /Qwen3\.6 27B details/ }),
  ).toHaveAttribute("href", modelUrl(M, "qwen3.6:27b"));
});

test("domain comparison: every heat cell shows its rate and interval; one plot per profile row", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/benchmarks", { waitUntil: "networkidle" });
  const domains = panel(page, "Domain comparison");
  const rows = domains.locator("table tbody tr");
  await expect(rows).toHaveCount(official.models.length);
  for (let i = 0; i < official.models.length; i += 1) {
    const model = official.models[i];
    await expect(rows.nth(i).locator('th[scope="row"]')).toHaveText(
      model.display_name,
    );
    const cells = rows.nth(i).locator("td");
    for (let j = 0; j < official.domains.length; j += 1) {
      const d = model.domains.find(
        (x: Json) => x.domain === official.domains[j],
      );
      await expect(cells.nth(j).locator(".cell-rate")).toHaveText(
        pct1(d.pooled_pass_rate),
      );
      await expect(cells.nth(j).locator(".cell-ci")).toContainText(
        interval(d.wilson_low, d.wilson_high),
      );
    }
  }
  await expect(rows.first().locator("td").first()).toContainText("97.5%");
  await expect(rows.first().locator("td").first()).toContainText("81.6–99.7%");
  // Column headers carry the domain's tasks and runs.
  const first = official.models[0].domains;
  for (let j = 0; j < official.domains.length; j += 1) {
    const d = first.find((x: Json) => x.domain === official.domains[j]);
    await expect(domains.locator("thead th").nth(j + 1)).toContainText(
      `${d.n_tasks} tasks · ${d.n_runs} runs`,
    );
  }
  // Domain profile: one point-and-interval plot per domain, no 0–100 bar.
  await domains.getByLabel("Domain profile for").selectOption("qwen3.6:27b");
  const profile = domains.locator(".domain-row");
  await expect(profile).toHaveCount(5);
  await expect(domains.locator(".domain-track")).toHaveCount(0);
  const qwen36 = official.models.find((m: Json) => m.id === "qwen3.6:27b");
  for (let j = 0; j < qwen36.domains.length; j += 1) {
    const d = qwen36.domains[j];
    const row = profile.nth(j);
    await expect(row.locator(".wilson-svg")).toHaveCount(1);
    await expect(row.locator(".domain-value")).toHaveText(
      pct1(d.pooled_pass_rate),
    );
    await expect(row.locator(".bench-interval-text")).toHaveText(
      interval(d.wilson_low, d.wilson_high),
    );
    await expect(row).toContainText(`n_eff ${d.n_eff.toFixed(1)}`);
  }
  await noSeriousAxe(page);
});

test("benchmark integrity lists its facts and does not claim isolation", async ({
  page,
}) => {
  await page.goto("/benchmarks", { waitUntil: "networkidle" });
  const integrity = panel(page, "Benchmark integrity");
  for (const text of [
    "600 / 600 planned",
    "120 / 120 planned",
    "24 / 24 tasks for every model",
    "600 runs · backend ollama",
    "120 / 120 cells at the pinned digest · Ollama 0.31.1",
    "phase0-integrity-v1 · 5 / 5 launches code-checked",
    "Hidden-test isolation",
    "UNVERIFIABLE",
  ])
    await expect(integrity).toContainText(text);
  const synthetic = integrity.locator(".integrity-list > div", {
    hasText: "Synthetic (mock) evidence",
  });
  await expect(synthetic).toContainText("0 runs");
  await expect(synthetic.locator(".badge")).toHaveText("none");
  // The note says the hidden tests are readable and that no isolation is
  // claimed; the panel never says the tests are isolated.
  const note = official.integrity.not_claimed[0].note;
  await expect(integrity).toContainText(note);
  await expect(integrity).toContainText("can read the hidden-test file");
  await expect(integrity).toContainText("makes no hidden-test isolation claim");
  expect(await integrity.innerText()).not.toMatch(/cryptograph|\bisolated\b/i);
  await expect(
    integrity.locator(".integrity-list dt", { hasText: /isolation/i }),
  ).toHaveCount(0);
  const evidence = panel(page, "Evidence");
  await expect(evidence).toContainText(
    "web/src/data/benchmark-releases/phase0-modern-local-v1.json",
  );
  await expect(evidence).toContainText("python3 -m afa_campaign release-data");
  await noSeriousAxe(page);
});

test("the release links switch to the historical release: unranked, alphabetical, no intervals", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/benchmarks", { waitUntil: "networkidle" });
  await releaseLinks(page)
    .getByRole("link", { name: /HISTORICAL/ })
    .click();
  await expect(page).toHaveURL(new RegExp(`/benchmarks/${H}$`));
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(
    historical.title,
  );
  await expect(
    releaseLinks(page).getByRole("link", { name: /HISTORICAL/ }),
  ).toHaveAttribute("aria-current", "page");
  await expect(page.getByText(COMPARABILITY).first()).toBeVisible();
  await expect(page.locator(".notice-warn").first()).toContainText(
    COMPARABILITY,
  );
  // A historical record was never released: its date is the last run.
  const facts = page.locator(".release-facts");
  await expect(
    facts.locator("dt", { hasText: "Last recorded run" }),
  ).toHaveCount(1);
  await expect(facts.locator("dt", { hasText: /^Released$/ })).toHaveCount(0);
  await expect(facts).toContainText("HISTORICAL");
  // No rank, no Wilson, no interval anywhere on the page.
  await expect(page.getByRole("columnheader", { name: /rank/i })).toHaveCount(
    0,
  );
  const text = await mainText(page);
  expect(text).not.toMatch(/\bRank\b/);
  expect(text).not.toMatch(/wilson/i);
  expect(text).not.toMatch(INTERVAL_TEXT);
  await expect(page.locator(".headline-context")).toHaveCount(0);
  // Recorded table: alphabetical by Ollama tag and says it is not a ranking.
  const recorded = panel(page, "Recorded results (unranked)");
  await expect(recorded).toContainText(
    "listed alphabetically by Ollama tag. The order is not a ranking.",
  );
  const rows = recorded.locator("tbody tr");
  await expect(rows).toHaveCount(6);
  await expect(recorded.locator("thead")).toContainText(
    "mean final score (formula v0.1)",
  );
  await expect(rows.first().locator('th[scope="row"]')).toContainText(
    "deepseek-coder:6.7b",
  );
  await expect(rows.first()).toContainText("28 / 120");
  const names = await rows.locator('th[scope="row"] a').allInnerTexts();
  expect(names).toEqual(historical.models.map((m: Json) => m.display_name));
  expect(names).toEqual([...names].sort());
  for (const model of historical.models)
    await expect(rows.filter({ hasText: model.id })).toContainText(
      `${model.totals.passes} / ${model.totals.runs}`,
    );
  await expect(page.locator(".headline-strip")).toContainText(
    "720 recorded runs",
  );
  await expect(page.locator(".headline-window")).toContainText(
    "2026-06-18 06:11 UTC",
  );
  // Live Explorer note.
  const main = page.locator("main");
  await expect(
    main.getByRole("link", { name: "Leaderboard", exact: true }),
  ).toHaveAttribute("href", "/leaderboard");
  await expect(
    main.getByRole("link", { name: "Tasks", exact: true }),
  ).toHaveAttribute("href", "/tasks");
  // Task column shows the recorded version and the change as text.
  await expect(
    page.locator("table.task-matrix tbody th", { hasText: "fix-list-dedup" }),
  ).toContainText("1.0.1 → 1.0.2 (changed)");
  await expect(page.locator("table.task-matrix td.matrix-heat")).toHaveCount(0);
  // A historical cell says what the dataset does not include.
  await matrixCell(page, "escape-html", "deepseek-coder:6.7b").click();
  const detail = page.getByRole("region", { name: "Selected task result" });
  await expect(detail).toContainText("voided");
  await expect(
    detail.locator("dt", { hasText: "mean final score" }).locator("+ dd"),
  ).toHaveText("not included in this dataset");
  await expect(
    detail.locator("dt", { hasText: "evaluation id" }).locator("+ dd"),
  ).toHaveText("not recorded (runs are not linked to evaluation jobs)");
  expect(await mainText(page)).not.toMatch(/wilson/i);
  // Not recorded instead of integrity facts.
  await expect(panel(page, "Benchmark integrity")).toContainText(
    "Not recorded",
  );
  await noSeriousAxe(page);
  // Back to the official release through its link.
  await releaseLinks(page)
    .getByRole("link", { name: /OFFICIAL/ })
    .click();
  await expect(page).toHaveURL(new RegExp(`/benchmarks/${M}$`));
});

test("browser back/forward after switching releases; per-release state resets", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/benchmarks", { waitUntil: "networkidle" });
  await matrixCell(page, "async-retry", "qwen3.6:27b").click();
  await expect(page.locator(".matrix-detail-row")).toHaveCount(1);
  await releaseLinks(page)
    .getByRole("link", { name: /HISTORICAL/ })
    .click();
  await expect(page).toHaveURL(new RegExp(`/benchmarks/${H}$`));
  await expect(page.locator("h1")).toHaveText(historical.title);
  await expect(page.locator(".matrix-detail-row")).toHaveCount(0);
  await expect(
    page.locator('.matrix-cell-button[aria-pressed="true"]'),
  ).toHaveCount(0);
  await page.goBack();
  await expect(page).toHaveURL(/\/benchmarks$/);
  await expect(page.locator("h1")).toHaveText(official.title);
  await expect(
    releaseLinks(page).getByRole("link", { name: /OFFICIAL/ }),
  ).toHaveAttribute("aria-current", "page");
  await expect(
    page.locator('.matrix-cell-button[aria-pressed="true"]'),
  ).toHaveCount(0);
  await page.goForward();
  await expect(page).toHaveURL(new RegExp(`/benchmarks/${H}$`));
  await expect(page.locator("h1")).toHaveText(historical.title);
  await expect(
    releaseLinks(page).getByRole("link", { name: /HISTORICAL/ }),
  ).toHaveAttribute("aria-current", "page");
  expect(errors).toEqual([]);
});

for (const model of official.models as Json[]) {
  test(`model page renders for ${model.id}`, async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto(modelUrl(M, model.id), { waitUntil: "networkidle" });
    await expect(page.getByRole("heading", { level: 1 })).toHaveText(
      model.display_name,
    );
    await expect(page.locator("h1")).toHaveCount(1);
    // Release status near the header, with its word.
    await expect(page.locator(".bench-status-line .badge")).toHaveText(
      "OFFICIAL",
    );
    await expect(page.locator(".bench-status-line")).toContainText(
      "Frozen, validated benchmark release.",
    );
    // Model switcher: links, the current one marked.
    const switcher = page.getByRole("navigation", {
      name: "Models in this release",
    });
    await expect(switcher.getByRole("link")).toHaveCount(
      official.models.length,
    );
    await expect(switcher.locator('[aria-current="page"]')).toHaveAttribute(
      "href",
      modelUrl(M, model.id),
    );
    await expect(page.locator("main select#benchmark-model")).toHaveCount(0);
    await expect(page.locator(".model-identity")).toContainText(
      model.identity.digest,
    );
    // Overall metrics: served rank and interval, the interval shown once at
    // one decimal, the plot scaled uniformly (viewBox 100 × 24).
    const t = model.totals;
    await expect(
      page.locator(".metric", { hasText: "Rank" }).first(),
    ).toContainText(`${rankOf(model.rank)} of 5`);
    const plot = page.locator(".bench-overall-plot");
    await expect(plot.locator(".bench-overall-text")).toHaveText(
      `${pct1(t.pass_rate)} Wilson 95% ${interval(t.wilson_low, t.wilson_high)}`,
    );
    await expect(plot.locator(".compact-range")).toBeHidden();
    await expect(plot.locator(".wilson-label")).toBeHidden();
    const svg = await plot.locator(".wilson-svg").boundingBox();
    expect(svg!.width).toBeLessThanOrEqual(321);
    expect(Math.abs(svg!.width / svg!.height - 100 / 24)).toBeLessThan(0.1);
    expect(await mainText(page)).not.toMatch(/\[\d+%–\d+%\]/);
    await expect(page.locator(".bench-domain-list .domain-row")).toHaveCount(5);
    await expect(page.locator(".bench-domain-list .domain-track")).toHaveCount(
      0,
    );
    const rows = page.locator("table.model-tasks tbody tr");
    await expect(rows).toHaveCount(24);
    for (let i = 0; i < 24; i += 1) {
      const task = model.tasks[i];
      const row = rows.nth(i);
      await expect(row.locator('th[scope="row"]')).toHaveText(task.task_id);
      await expect(row).toContainText(`${task.passes} / ${task.runs}`);
      await expect(row).toContainText(
        interval(task.wilson_low, task.wilson_high),
      );
    }
    await expect(page.locator("nav.breadcrumbs")).toHaveText(
      `Overview/Benchmarks/${M}/${model.id}`,
    );
    const protocol = page.locator(
      '.inline-notice [data-caveat="qwen3-coder-protocol-sensitivity"]',
    );
    const latency = page.locator(
      '.inline-notice [data-caveat="qwen3.6-latency-constrained"]',
    );
    await expect(protocol).toHaveCount(model.id === "qwen3-coder:30b" ? 1 : 0);
    await expect(latency).toHaveCount(model.id === "qwen3.6:27b" ? 1 : 0);
    if (model.id === "qwen3-coder:30b") {
      await expect(protocol).toContainText("Protocol sensitivity");
      for (const point of official.caveats[0].points)
        await expect(protocol).toContainText(point);
      const facts = panel(page, "Documented in the campaign report");
      await expect(facts).toContainText("96 / 120");
      await expect(facts).toContainText("the committed artifacts do not carry");
      await expect(page.locator(".model-identity")).toContainText("18.56 GB");
    }
    if (model.id === "qwen3.6:27b") {
      await expect(latency).toContainText("Latency constrained");
      await expect(page.locator(".model-identity")).toContainText(
        "not reported",
      );
      await expect(page.locator(".metric-group").first()).toContainText(
        "5 of 5",
      );
    }
    await noSeriousAxe(page);
  });
}

test("model switcher links navigate between models", async ({ page }) => {
  await page.goto(modelUrl(M, "gpt-oss:20b"), { waitUntil: "networkidle" });
  await page
    .getByRole("navigation", { name: "Models in this release" })
    .getByRole("link", { name: /Qwen3\.6 27B/ })
    .click();
  await expect(page).toHaveURL(modelUrl(M, "qwen3.6:27b"));
  await expect(page.locator("h1")).toHaveText("Qwen3.6 27B");
  await page.goBack();
  await expect(page.locator("h1")).toHaveText("gpt-oss 20B");
});

for (const model of historical.models as Json[]) {
  test(`historical model page for ${model.id}: HISTORICAL, counts only`, async ({
    page,
  }) => {
    await page.goto(modelUrl(H, model.id), { waitUntil: "networkidle" });
    await expect(page.getByRole("heading", { level: 1 })).toHaveText(
      model.display_name,
    );
    await expect(page.locator(".bench-status-line .badge")).toHaveText(
      "HISTORICAL",
    );
    await expect(page.locator(".bench-status-line")).toContainText(
      "Recorded before the current evaluation-integrity system.",
    );
    await expect(page.locator(".metric-group")).toContainText(
      `${model.totals.passes} / ${model.totals.runs}`,
    );
    await expect(page.locator(".model-identity")).toContainText("not recorded");
    await expect(page.locator("table.model-tasks tbody tr")).toHaveCount(24);
    const text = await mainText(page);
    expect(text).not.toMatch(/\bRank\b/);
    expect(text).not.toMatch(/wilson/i);
    expect(text).not.toMatch(INTERVAL_TEXT);
    expect(text).not.toMatch(/[0-9a-f]{64}/);
    await expect(page.locator(".wilson-svg")).toHaveCount(0);
    if (model.id === "qwen3.5:9b") {
      await expect(page.locator(".metric-group")).toContainText("40 / 120");
      await expect(page.locator(".model-identity")).toContainText(
        "temperature 0.6",
      );
      await noSeriousAxe(page);
    }
  });
}

test("keyboard: the task matrix is one tab stop with arrow-key navigation and an inline detail", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/benchmarks", { waitUntil: "networkidle" });
  const tasks = official.task_pack;
  const models = official.models;
  const tabStops = page.locator(
    'table.task-matrix .matrix-cell-button[tabindex="0"]',
  );
  await expect(tabStops).toHaveCount(1);
  // One Tab from the control before the matrix lands on its first cell.
  await page.locator("#domain-model").focus();
  await page.keyboard.press("Tab");
  await expect(matrixCell(page, tasks[0].task_id, models[0].id)).toBeFocused();
  await page.keyboard.press("ArrowRight");
  await expect(matrixCell(page, tasks[0].task_id, models[1].id)).toBeFocused();
  await page.keyboard.press("ArrowDown");
  const target = matrixCell(page, tasks[1].task_id, models[1].id);
  await expect(target).toBeFocused();
  await expect(tabStops).toHaveCount(1);
  await expect(target).toHaveAttribute("tabindex", "0");
  await page.keyboard.press("ArrowUp");
  await page.keyboard.press("ArrowUp"); // clamps at the first row
  await expect(matrixCell(page, tasks[0].task_id, models[1].id)).toBeFocused();
  await page.keyboard.press("ArrowDown");
  await page.keyboard.press("Enter");
  await expect(target).toHaveAttribute("aria-pressed", "true");
  await expect(target).toBeFocused();
  // The detail opens as a row directly under the selected task's row.
  const detail = page.getByRole("region", { name: "Selected task result" });
  await expect(detail).toBeVisible();
  const directlyBelow = await target.evaluate((button) => {
    const next = button.closest("tr")?.nextElementSibling;
    return !!next?.classList.contains("matrix-detail-row");
  });
  expect(directlyBelow).toBe(true);
  await expect(target).toHaveAttribute("aria-controls", /task-matrix-detail/);
  const model = models[1];
  const result = model.tasks.find((r: Json) => r.task_id === tasks[1].task_id);
  await expect(detail).toContainText(
    `${tasks[1].task_id} ${tasks[1].task_version}`,
  );
  await expect(detail).toContainText(model.display_name);
  await expect(detail).toContainText(result.evaluation_id);
  await expect(detail).toContainText(
    interval(result.wilson_low, result.wilson_high),
  );
  const box = await detail.boundingBox();
  expect(box!.x).toBeGreaterThanOrEqual(0);
  expect(box!.x + box!.width).toBeLessThanOrEqual(1440);
  // The always-present live region announces a one-line summary.
  const live = page.locator(".matrix-live");
  await expect(live).toHaveAttribute("aria-live", "polite");
  await expect(live).toHaveAttribute("aria-atomic", "true");
  const noun = result.timeouts === 1 ? "timeout" : "timeouts";
  await expect(live).toHaveText(
    `${tasks[1].task_id} ${tasks[1].task_version} · ${model.display_name}: ${result.passes} of ${result.runs} passed, Wilson ${interval(result.wilson_low, result.wilson_high)}, ${result.timeouts} ${noun} (${result.request_timeout_hits} full)`,
  );
  // Escape closes it and keeps focus on the cell.
  await page.keyboard.press("Escape");
  await expect(page.locator(".matrix-detail-row")).toHaveCount(0);
  await expect(target).toHaveAttribute("aria-pressed", "false");
  await expect(target).toBeFocused();
  await expect(live).toHaveText("");
  // Space selects too; Home/End go to the row's ends.
  await page.keyboard.press(" ");
  await expect(target).toHaveAttribute("aria-pressed", "true");
  await page.keyboard.press("End");
  const last = matrixCell(page, tasks[1].task_id, models[models.length - 1].id);
  await expect(last).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(last).toHaveAttribute("aria-pressed", "true");
  await expect(target).toHaveAttribute("aria-pressed", "false");
  await expect(live).toContainText(models[models.length - 1].display_name);
  await page.keyboard.press("Home");
  await expect(matrixCell(page, tasks[1].task_id, models[0].id)).toBeFocused();
  // Tab goes to the detail's close button, then out of the matrix.
  await page.keyboard.press("Tab");
  await expect(
    page.getByRole("button", { name: "Close details" }),
  ).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(page.locator(".matrix-detail-row")).toHaveCount(0);
  await expect(matrixCell(page, tasks[1].task_id, models[0].id)).toBeFocused();
  await page.keyboard.press("Tab");
  const inMatrix = await page.evaluate(
    () => !!document.activeElement?.closest("table.task-matrix"),
  );
  expect(inMatrix).toBe(false);
  // Shift+Tab returns to the remembered cell.
  await page.keyboard.press("Shift+Tab");
  await expect(matrixCell(page, tasks[1].task_id, models[0].id)).toBeFocused();
  // Every cell is a number; timeouts carry a number too.
  const timeouts = page.locator("table.task-matrix .cell-timeouts");
  expect(await timeouts.count()).toBeGreaterThan(0);
  await expect(timeouts.first()).toHaveText(/\d+ timeouts?$/);
  await page.keyboard.press("Enter");
  await noSeriousAxe(page);
});

test("task matrix at 375px: inline detail stays on screen, focus clears the sticky column, header stays", async ({
  page,
}) => {
  await page.setViewportSize({ width: 375, height: 812 });
  await page.goto("/benchmarks", { waitUntil: "networkidle" });
  const cell = matrixCell(page, "async-retry", "qwen3.6:27b");
  await cell.scrollIntoViewIfNeeded();
  await cell.click();
  const detail = page.getByRole("region", { name: "Selected task result" });
  await expect(detail).toContainText("async-retry");
  await expect(detail).toContainText("Qwen3.6 27B");
  const box = await detail.boundingBox();
  expect(box!.x).toBeGreaterThanOrEqual(0);
  expect(box!.x + box!.width).toBeLessThanOrEqual(375);
  await page.keyboard.press("Escape");
  await expect(page.locator(".matrix-detail-row")).toHaveCount(0);
  // Arrowing left across the scrolled matrix keeps the focused cell clear
  // of the sticky task column.
  const cleared = async () =>
    page.evaluate(() => {
      const active = document.activeElement as HTMLElement;
      const sticky = active
        .closest("tr")!
        .querySelector("th.sticky-col")!
        .getBoundingClientRect();
      return active.getBoundingClientRect().left >= sticky.right - 1;
    });
  for (let i = 0; i < official.models.length - 1; i += 1) {
    await page.keyboard.press("ArrowLeft");
    expect(await cleared()).toBe(true);
  }
  await page.keyboard.press("End");
  expect(await cleared()).toBe(true);
  // Scrolling the matrix down keeps the model header row visible.
  const scroller = page.locator(".matrix-scroll");
  await scroller.evaluate((el) => {
    el.scrollTop = 600;
  });
  const header = await page.evaluate(() => {
    const scrollerBox = document
      .querySelector(".matrix-scroll")!
      .getBoundingClientRect();
    const th = document
      .querySelector("table.task-matrix thead th:nth-child(2)")!
      .getBoundingClientRect();
    return { top: th.top - scrollerBox.top };
  });
  expect(Math.abs(header.top)).toBeLessThan(2);
  const result = await layout(page);
  expect(result.pageOverflow).toBe(false);
});

test("wide tables at 375px pin their identifying column and show a scroll cue", async ({
  page,
}) => {
  await page.setViewportSize({ width: 375, height: 812 });
  for (const [path, table] of [
    [modelUrl(M, "qwen3.6:27b"), "table.model-tasks"],
    [`/benchmarks/${H}`, "table.release-recorded"],
    [`/benchmarks/${M}/methodology`, "table.task-pack"],
    [`/benchmarks/${M}`, "table.domain-matrix"],
  ] as const) {
    await page.goto(path, { waitUntil: "networkidle" });
    const scroller = page.locator(".table-scroll", {
      has: page.locator(table),
    });
    await scroller.scrollIntoViewIfNeeded();
    await expect(
      page.locator(".scroll-hint").filter({ hasText: "Scroll sideways" }),
    ).not.toHaveCount(0);
    await scroller.evaluate((el) => {
      el.scrollLeft = el.scrollWidth;
    });
    const pinned = await scroller.evaluate((el) => {
      const box = el.getBoundingClientRect();
      const th = el
        .querySelector('tbody th[scope="row"]')!
        .getBoundingClientRect();
      return { offset: th.left - box.left, scrolled: el.scrollLeft };
    });
    expect(pinned.scrolled, path).toBeGreaterThan(0);
    expect(Math.abs(pinned.offset), path).toBeLessThan(2);
  }
});

test("tables have row headers, column scopes and accessible names; scroll regions are named", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  for (const path of [
    `/benchmarks/${M}`,
    `/benchmarks/${H}`,
    modelUrl(M, "gpt-oss:20b"),
    modelUrl(H, "gemma2:2b"),
    `/benchmarks/${M}/methodology`,
    `/benchmarks/${H}/methodology`,
  ]) {
    await page.goto(path, { waitUntil: "networkidle" });
    const report = await page.evaluate(() => {
      const nameOf = (el: Element) =>
        (el.getAttribute("aria-labelledby") ?? "")
          .split(/\s+/)
          .map((id) => document.getElementById(id)?.textContent?.trim() ?? "")
          .join(" ")
          .trim();
      const problems: string[] = [];
      const tables = [...document.querySelectorAll("main table")];
      for (const table of tables) {
        const label = table.className;
        if (!nameOf(table) && !table.querySelector("caption"))
          problems.push(`${label}: no accessible name`);
        if (!table.querySelector('tbody th[scope="row"]'))
          problems.push(`${label}: no row headers`);
        for (const th of table.querySelectorAll("thead th"))
          if (th.getAttribute("scope") !== "col")
            problems.push(`${label}: header without scope=col`);
      }
      for (const scroller of document.querySelectorAll("main .table-scroll")) {
        if (scroller.getAttribute("role") !== "region")
          problems.push("scroller without role=region");
        if (!nameOf(scroller)) problems.push("scroller without a name");
      }
      return { tables: tables.length, problems };
    });
    expect(report.tables, path).toBeGreaterThan(0);
    expect(report.problems, path).toEqual([]);
  }
});

test("methodology & provenance page", async ({ page }) => {
  await page.goto(`/benchmarks/${M}/methodology`, {
    waitUntil: "networkidle",
  });
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(
    "Methodology & provenance",
  );
  const generation = panel(page, "Generation");
  await expect(generation.locator("dd").first()).toHaveText("0.8");
  await expect(generation).toContainText("42–46");
  await expect(generation).toContainText("180 s");
  await expect(panel(page, "Environment")).toContainText("0.31.1");
  await expect(panel(page, "Environment")).toContainText(
    `Source: ${official.headline.paid_api_cost.source}`,
  );
  await expect(panel(page, "Environment")).toContainText(
    official.environment.hardware.source,
  );
  // The full ranking method, file paths included.
  await expect(panel(page, "Evaluation identity")).toContainText(
    official.methodology.ranking_method,
  );
  await expect(panel(page, "Evaluation identity")).toContainText("rank_by_lcb");
  await expect(panel(page, "Runtime release")).toContainText(
    "phase0-integrity-v1",
  );
  await expect(
    panel(page, "Release").locator("dt", { hasText: "released" }),
  ).toHaveCount(1);
  const pack = page.locator("table.task-pack tbody tr");
  await expect(pack).toHaveCount(24);
  // Domain weights exactly as served (String(weight), never rounded).
  const first = official.task_pack[0];
  const tags = await pack.first().locator(".tag").allInnerTexts();
  expect(tags).toEqual(
    first.domains.map((d: Json) => `${d.domain} · ${String(d.weight)}`),
  );
  await expect(panel(page, "Hashes")).toContainText(
    official.methodology.manifest_sha256,
  );
  await expect(page.locator("nav.breadcrumbs")).toHaveText(
    `Overview/Benchmarks/${M}/Methodology`,
  );
  expect(await badTextHits(page)).toEqual([]);
  await noSeriousAxe(page);

  await page.goto(`/benchmarks/${H}/methodology`, {
    waitUntil: "networkidle",
  });
  await expect(page.getByText(COMPARABILITY)).toBeVisible();
  const groups = panel(page, "Generation (documented per group)");
  await expect(groups).toContainText("not recorded");
  await expect(groups.locator('tbody th[scope="row"]')).toHaveText(
    historical.methodology.generation_groups.map((g: Json) => g.group),
  );
  await expect(
    panel(page, "Release").locator("dt", { hasText: "last recorded run" }),
  ).toHaveCount(1);
  await expect(page.locator("table.task-pack tbody tr")).toHaveCount(24);
  const text = await mainText(page);
  expect(text).not.toMatch(/\bRank\b/);
  expect(text).not.toMatch(INTERVAL_TEXT);
  await noSeriousAxe(page);
});

test("unknown release and unknown model show explicit not-found states", async ({
  page,
}) => {
  await page.goto("/benchmarks/no-such-release", { waitUntil: "networkidle" });
  await expect(page).toHaveURL(/\/benchmarks\/no-such-release$/);
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(
    "Release not found",
  );
  await expect(
    page.getByRole("link", { name: "Open the current benchmark release" }),
  ).toHaveAttribute("href", "/benchmarks");
  await noSeriousAxe(page);

  await page.goto(modelUrl(M, "nope:1b"), { waitUntil: "networkidle" });
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(
    "Model not found",
  );
  await expect(page.locator("main")).toContainText("nope:1b");
  await expect(
    page.getByRole("link", { name: "Back to Modern Local v1" }),
  ).toHaveAttribute("href", `/benchmarks/${M}`);
  await noSeriousAxe(page);

  // A model of the other release is not found in this one.
  await page.goto(modelUrl(H, "gpt-oss:20b"), { waitUntil: "networkidle" });
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(
    "Model not found",
  );
});

test("malformed percent-encoding via in-app navigation renders not-found, not a blank app", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/benchmarks", { waitUntil: "networkidle" });
  const navigate = (url: string) =>
    page.evaluate((to) => {
      history.pushState({}, "", to);
      dispatchEvent(new PopStateEvent("popstate"));
    }, url);
  await navigate("/benchmarks/%E0%A4%A");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(
    "Release not found",
  );
  await expect(page.locator("nav.breadcrumbs")).toContainText("%E0%A4%A");
  await navigate(`/benchmarks/${M}/models/%`);
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(
    "Model not found",
  );
  await navigate(`/benchmarks/%E0%A4%A/methodology`);
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(
    "Release not found",
  );
  // The same safe decode protects the existing routes' breadcrumbs.
  await navigate("/agent/%E0%A4%A");
  await expect(page.locator("nav.breadcrumbs")).toContainText("%E0%A4%A");
  await expect(page.locator(".sidebar").first()).toBeVisible();
  expect(errors).toEqual([]);
});

test("a benchmark chunk that fails to load shows an error panel inside the app", async ({
  page,
}) => {
  await page.goto("/settings", { waitUntil: "networkidle" });
  await page.route(/\/src\/pages\/BenchmarkRelease\.tsx/, (route) =>
    route.abort(),
  );
  await page
    .locator(".desktop-sidebar")
    .getByRole("link", { name: "Benchmarks" })
    .click();
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(
    "Benchmark release unavailable",
  );
  await expect(page.locator(".desktop-sidebar")).toBeVisible();
  await expect(page.locator("header.topbar")).toBeVisible();
});

const allRoutes = [
  "/benchmarks",
  `/benchmarks/${M}`,
  `/benchmarks/${H}`,
  `/benchmarks/${M}/methodology`,
  `/benchmarks/${H}/methodology`,
  ...official.models.map((m: Json) => modelUrl(M, m.id)),
  ...historical.models.map((m: Json) => modelUrl(H, m.id)),
];

test("no benchmark page shows NaN, undefined, null, Infinity or [object Object]", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  for (const route of allRoutes) {
    await page.goto(route, { waitUntil: "networkidle" });
    await expect(page.locator("h1")).toHaveCount(1);
    await expect(page.locator("h1")).not.toHaveText(/not found|unavailable/i);
    // Open a matrix cell too, so its detail is swept.
    const cell = page.locator(".matrix-cell-button").first();
    if (await cell.count()) await cell.click();
    expect(await badTextHits(page), route).toEqual([]);
  }
  expect(errors).toEqual([]);
});

const pages = [
  ["release", "/benchmarks"],
  ["historical", `/benchmarks/${H}`],
  ["model", modelUrl(M, "qwen3.6:27b")],
  ["historical-model", modelUrl(H, "qwen2.5-coder:7b")],
  ["methodology", `/benchmarks/${M}/methodology`],
  ["historical-methodology", `/benchmarks/${H}/methodology`],
] as const;

for (const width of [375, 768, 1440]) {
  test(`benchmark pages fit and pass axe at ${width}px`, async ({
    page,
  }, testInfo) => {
    await page.setViewportSize({ width, height: 900 });
    for (const [name, path] of pages) {
      await page.goto(path, { waitUntil: "networkidle" });
      await expect(page.locator("h1")).toBeVisible();
      await expect(page.locator("h1")).toHaveCount(1);
      // Audit the selected-cell state as well.
      const cell = page.locator(".matrix-cell-button").nth(3);
      if (await cell.count()) await cell.click();
      const result = await layout(page);
      expect(result.pageOverflow, `${path} overflows at ${width}`).toBe(false);
      expect(result.plotOverflow, `${path} plot overflows at ${width}`).toBe(
        false,
      );
      await noSeriousAxe(page);
      await page.screenshot({
        path: testInfo.outputPath(`benchmarks-${name}-${width}.png`),
        fullPage: true,
      });
    }
  });
}

// Every matrix cell, in order, shows the dataset's passes/runs and timeouts: a
// UI that swapped passes for failures (or reordered cells) fails here.
for (const release of [official, historical]) {
  test(`every ${release.id} task-matrix cell shows its passes/runs and timeouts`, async ({
    page,
  }) => {
    await page.goto(`/benchmarks/${release.id}`, { waitUntil: "networkidle" });
    const want = release.task_pack.flatMap((task: Json) =>
      release.models.map((model: Json) => {
        const r = model.tasks.find((x: Json) => x.task_id === task.task_id);
        return [
          task.task_id,
          model.id,
          r?.evidence ? `${r.passes}/${r.runs}` : "no evidence",
          r?.timeouts > 0
            ? `${r.timeouts} timeout${r.timeouts === 1 ? "" : "s"}`
            : null,
        ];
      }),
    );
    const got = await page
      .locator("table.task-matrix .matrix-cell-button")
      .evaluateAll((buttons) =>
        buttons.map((b) => [
          (b as HTMLElement).dataset.task,
          (b as HTMLElement).dataset.model,
          b.querySelector(".cell-count")?.textContent ?? null,
          b.querySelector(".cell-timeouts")?.textContent ?? null,
        ]),
      );
    expect(got).toEqual(want);
  });
}
