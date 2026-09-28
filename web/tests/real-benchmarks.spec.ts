// Real built app smoke for the Benchmark Releases pages and the existing
// Explorer pages around them (run by playwright.real.config.ts, which serves
// web/dist through the temp-copy API server; run `npm run build` first).
// Each page must show its own heading: the SPA fallback plus the '*' -> /404
// route would let a bare "an h1 is visible" check pass for an unknown route.
import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";
import type { Page } from "@playwright/test";

const release = "phase0-modern-local-v1";
const model = (id: string) =>
  `/benchmarks/${release}/models/${encodeURIComponent(id)}`;

const pages: Array<{
  name: string;
  path: string;
  heading: string | RegExp;
  benchmark: boolean;
}> = [
  {
    name: "benchmarks",
    path: "/benchmarks",
    heading: "AgentForge Modern Local Benchmark v1",
    benchmark: true,
  },
  {
    name: "release",
    path: `/benchmarks/${release}`,
    heading: "AgentForge Modern Local Benchmark v1",
    benchmark: true,
  },
  {
    name: "model-gpt-oss",
    path: model("gpt-oss:20b"),
    heading: "gpt-oss 20B",
    benchmark: true,
  },
  {
    name: "model-devstral",
    path: model("devstral-small-2:24b"),
    heading: "Devstral Small 2 24B",
    benchmark: true,
  },
  {
    name: "model-qwen3.5",
    path: model("qwen3.5:9b"),
    heading: "Qwen 3.5 9B",
    benchmark: true,
  },
  {
    name: "model-qwen3-coder",
    path: model("qwen3-coder:30b"),
    heading: "Qwen3-Coder 30B-A3B",
    benchmark: true,
  },
  {
    name: "model-qwen3.6",
    path: model("qwen3.6:27b"),
    heading: "Qwen3.6 27B",
    benchmark: true,
  },
  {
    name: "methodology",
    path: `/benchmarks/${release}/methodology`,
    heading: "Methodology & provenance",
    benchmark: true,
  },
  {
    name: "historical",
    path: "/benchmarks/historical-pre-phase0",
    heading: "Pre-Phase-0 legacy results",
    benchmark: true,
  },
  {
    name: "historical-model",
    path: "/benchmarks/historical-pre-phase0/models/qwen2.5-coder%3A7b",
    heading: "qwen2.5-coder:7b",
    benchmark: true,
  },
  {
    name: "historical-methodology",
    path: "/benchmarks/historical-pre-phase0/methodology",
    heading: "Methodology & provenance",
    benchmark: true,
  },
  { name: "overview", path: "/", heading: /Run agents/, benchmark: false },
  {
    name: "leaderboard",
    path: "/leaderboard",
    heading: "Leaderboard",
    benchmark: false,
  },
  { name: "jobs", path: "/jobs", heading: "Evaluations", benchmark: false },
  { name: "tasks", path: "/tasks", heading: "Tasks", benchmark: false },
  {
    name: "task",
    path: "/task/fix-binary-search",
    heading: "fix-binary-search",
    benchmark: false,
  },
  { name: "agents", path: "/agents", heading: "Agents", benchmark: false },
  {
    name: "agent",
    path: "/agent/qwen3.5%3A9b",
    heading: "qwen3.5:9b",
    benchmark: false,
  },
];

async function seriousAxe(page: Page) {
  const axe = await new AxeBuilder({ page }).analyze();
  return axe.violations
    .filter((v) => ["serious", "critical"].includes(v.impact ?? ""))
    .map((v) => `${v.id}: ${v.nodes[0]?.target}`);
}

for (const entry of pages) {
  test(`real app: ${entry.name} (${entry.path})`, async ({
    page,
  }, testInfo) => {
    const errors: string[] = [];
    page.on("pageerror", (error) => errors.push(error.message));
    for (const width of [375, 1440]) {
      await page.setViewportSize({ width, height: 900 });
      const response = await page.goto(entry.path, {
        waitUntil: "networkidle",
      });
      expect(response?.ok()).toBeTruthy();
      await expect(page).not.toHaveURL(/\/404$/);
      await expect(
        page.getByRole("heading", {
          level: 1,
          name: entry.heading,
          ...(typeof entry.heading === "string" ? { exact: true } : {}),
        }),
      ).toBeVisible();
      if (entry.benchmark) expect(await seriousAxe(page)).toEqual([]);
      const overflow = await page.evaluate(
        () => document.documentElement.scrollWidth > window.innerWidth + 1,
      );
      expect(overflow, `${entry.path} overflows at ${width}px`).toBe(false);
      await page.screenshot({
        path: testInfo.outputPath(`real-bench-${entry.name}-${width}.png`),
        fullPage: true,
      });
    }
    expect(errors).toEqual([]);
  });
}

test("real app: release status words on model pages", async ({ page }) => {
  await page.goto(model("gpt-oss:20b"), { waitUntil: "networkidle" });
  await expect(page.locator(".bench-status-line .badge")).toHaveText(
    "OFFICIAL",
  );
  await page.goto(
    "/benchmarks/historical-pre-phase0/models/qwen2.5-coder%3A7b",
    { waitUntil: "networkidle" },
  );
  await expect(page.locator(".bench-status-line .badge")).toHaveText(
    "HISTORICAL",
  );
  const text = (await page.locator("main").innerText()).replace(/\s+/g, " ");
  expect(text).not.toMatch(/\bRank\b/);
  expect(text).not.toMatch(/wilson/i);
  expect(text).toContain("67 / 120");
});

test("real app: the historical recorded table is alphabetical, not ranked", async ({
  page,
}) => {
  await page.goto("/benchmarks/historical-pre-phase0", {
    waitUntil: "networkidle",
  });
  const rows = page.locator("table.release-recorded tbody tr");
  await expect(rows).toHaveCount(6);
  await expect(rows.first()).toContainText("deepseek-coder:6.7b");
  await expect(rows.first()).toContainText("28 / 120");
  await expect(page.locator("main")).toContainText(
    "listed alphabetically by Ollama tag. The order is not a ranking.",
  );
});

test("real app: malformed percent-encoding renders not-found, not a blank app", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/benchmarks", { waitUntil: "networkidle" });
  await page.evaluate(() => {
    history.pushState({}, "", "/benchmarks/%E0%A4%A");
    dispatchEvent(new PopStateEvent("popstate"));
  });
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(
    "Release not found",
  );
  await page.evaluate(() => {
    history.pushState({}, "", "/agent/%E0%A4%A");
    dispatchEvent(new PopStateEvent("popstate"));
  });
  await expect(page.locator("nav.breadcrumbs")).toContainText("%E0%A4%A");
  expect(errors).toEqual([]);
});

test("real app: the release data loads only with the benchmark pages", async ({
  page,
}) => {
  const scripts: string[] = [];
  page.on("response", (response) => {
    if (response.request().resourceType() === "script")
      scripts.push(new URL(response.url()).pathname);
  });
  await page.goto("/leaderboard", { waitUntil: "networkidle" });
  const shell = [...scripts];
  expect(
    shell.some((path) => /Benchmark(Release|Model|Methodology)-/.test(path)),
  ).toBe(false);
  // The entry chunk does not carry the datasets.
  const entry = shell.find((path) => /\/assets\/index-[^/]+\.js$/.test(path));
  expect(entry).toBeTruthy();
  const body = await (await page.request.get(entry!)).text();
  expect(body).not.toContain("qwen3-coder:30b");
  expect(body).not.toContain("Pre-Phase-0 legacy results");
  await page
    .locator(".desktop-sidebar")
    .getByRole("link", { name: "Benchmarks" })
    .click();
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(
    "AgentForge Modern Local Benchmark v1",
  );
  expect(scripts.some((path) => /BenchmarkRelease-/.test(path))).toBe(true);
});

test("real app: benchmark CSS is scoped; the existing Leaderboard keeps its look", async ({
  page,
}) => {
  await page.goto("/leaderboard", { waitUntil: "networkidle" });
  await expect(
    page.getByRole("heading", { level: 1, name: "Leaderboard", exact: true }),
  ).toBeVisible();
  const styles = await page.evaluate(() => {
    const rank = document.querySelector<HTMLElement>(".rank-number");
    const cell = rank?.closest("td");
    const links = [...document.querySelectorAll<HTMLElement>(".link-arrow")];
    return {
      inBench: !!document.querySelector(".bench-page"),
      rank: rank
        ? {
            size: getComputedStyle(rank).fontSize,
            weight: getComputedStyle(rank).fontWeight,
            color: getComputedStyle(rank).color,
            cellColor: cell ? getComputedStyle(cell).color : null,
          }
        : null,
      relativeLinks: links.filter(
        (link) => getComputedStyle(link).position === "relative",
      ).length,
      links: links.length,
    };
  });
  expect(styles.inBench).toBe(false);
  // The benchmark rule (13px / 650 / primary text) must not reach this page:
  // a rank inherits the table.data td defaults (12px, normal weight,
  // secondary text colour).
  expect(styles.rank).not.toBeNull();
  expect(styles.rank!.size).toBe("12px");
  expect(styles.rank!.weight).toBe("400");
  expect(styles.rank!.color).toBe(styles.rank!.cellColor);
  expect(styles.links).toBeGreaterThan(0);
  expect(styles.relativeLinks).toBe(0);
});
