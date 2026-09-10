import { expect, test } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

const agent = "qwen2.5-coder:7b";
const task = "fix-binary-search";

async function auditPage(
  page: import("@playwright/test").Page,
  route: string,
  screenshot: string,
  width: number,
) {
  await page.setViewportSize({ width, height: 900 });
  const response = await page.goto(route, { waitUntil: "networkidle" });
  expect(response?.ok()).toBeTruthy();
  await expect(page.locator("h1").first()).toBeVisible();
  const axe = await new AxeBuilder({ page }).analyze();
  const serious = axe.violations.filter((violation) =>
    ["serious", "critical"].includes(violation.impact),
  );
  expect(
    serious,
    `${route}: ${serious.map((violation) => violation.id).join(", ")}`,
  ).toHaveLength(0);
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth > window.innerWidth + 1,
  );
  expect(overflow, `${route} has page-level horizontal overflow`).toBe(false);
  await page.screenshot({
    path: `test-artifacts/real-${screenshot}-${width}.png`,
    fullPage: true,
  });
}

async function launchMock(
  page: import("@playwright/test").Page,
  repeats = 1,
): Promise<string> {
  await page.goto("/new", { waitUntil: "networkidle" });
  await page.getByRole("button", { name: "Verify backend" }).click();
  await expect(page.getByText("1 model available")).toBeVisible();
  await page.getByRole("button", { name: "Continue" }).click();
  await page.getByRole("button", { name: "Continue" }).click();
  await page.locator('.task-option input[type="checkbox"]').first().check();
  await page.getByRole("button", { name: "Continue" }).click();
  await page.getByLabel("Repeats per task").fill(String(repeats));
  await page.getByRole("button", { name: "Continue" }).click();
  await page
    .getByRole("button", { name: new RegExp(`Launch ${repeats} runs`) })
    .click();
  await page.waitForURL(/\/jobs\/[^/]+$/);
  return new URL(page.url()).pathname.split("/").pop() ?? "";
}

async function waitForTerminal(page: import("@playwright/test").Page) {
  await expect(
    page
      .getByText(/Evaluation complete|Evaluation canceled|Evaluation stopped/)
      .first(),
  ).toBeVisible({ timeout: 120_000 });
}

test("existing evidence navigates through patch, tests, legacy, and synthetic references", async ({
  page,
}) => {
  const consoleErrors: string[] = [];
  page.on("console", (message) => {
    if (message.type() === "error") consoleErrors.push(message.text());
  });
  const widths = [375, 768, 1440, 2560];
  for (const width of widths) await auditPage(page, "/", "home", width);
  for (const width of widths) await auditPage(page, "/new", "wizard", width);
  for (const width of widths)
    await auditPage(page, "/leaderboard", "leaderboard", width);
  for (const width of widths)
    await auditPage(
      page,
      `/agent/${encodeURIComponent(agent)}`,
      "agent",
      width,
    );
  for (const width of widths)
    await auditPage(
      page,
      `/cell/${encodeURIComponent(agent)}/${task}`,
      "cell",
      width,
    );
  for (const width of widths)
    await auditPage(
      page,
      `/cell/${encodeURIComponent(agent)}/${task}/run/0`,
      "run",
      width,
    );
  for (const width of widths)
    await auditPage(page, "/settings", "settings", width);
  for (const width of widths)
    await auditPage(page, "/reports", "reports", width);

  await page.goto(`/cell/${encodeURIComponent(agent)}/${task}/run/0`, {
    waitUntil: "networkidle",
  });
  await page.getByRole("tab", { name: "Tests" }).click();
  await expect(page.getByText("hidden", { exact: true }).first()).toBeVisible();
  await expect(page.locator(".test-name").first()).toBeVisible();

  const meta = await page.request
    .get("/api/v1/meta")
    .then((response) => response.json());
  let legacy: { agent: string; task: string; idx: number } | null = null;
  for (const candidateAgent of meta.models as string[]) {
    for (const candidateTask of (meta.tasks as Array<{ task_id: string }>).map(
      (item) => item.task_id,
    )) {
      for (let idx = 0; idx < 5; idx += 1) {
        const result = await page.request
          .get(
            `/api/v1/run/${encodeURIComponent(candidateAgent)}/${encodeURIComponent(candidateTask)}/${idx}`,
          )
          .then((response) => response.json());
        if (
          result.found &&
          !result.synthetic &&
          result.patch_available === false
        ) {
          legacy = { agent: candidateAgent, task: candidateTask, idx };
          break;
        }
      }
      if (legacy) break;
    }
    if (legacy) break;
  }
  expect(legacy).not.toBeNull();
  await page.goto(
    `/cell/${encodeURIComponent(legacy!.agent)}/${encodeURIComponent(legacy!.task)}/run/${legacy!.idx}`,
    { waitUntil: "networkidle" },
  );
  await expect(
    page.getByText("Patch not captured", { exact: false }),
  ).toBeVisible();
  await expect(page.getByRole("tab", { name: "Tests" })).toBeVisible();
  await page.goto(`/task/${task}`, { waitUntil: "networkidle" });
  await page.getByRole("link", { name: "run #0" }).first().click();
  await expect(
    page.getByText("Synthetic baseline", { exact: false }).first(),
  ).toBeVisible();
  expect(consoleErrors).toEqual([]);
});

test("mock evaluation launches, streams, retries with reuse, cancels, and exposes results", async ({
  page,
}) => {
  const firstId = await launchMock(page, 1);
  await waitForTerminal(page);
  await expect(page.getByText("1 passed")).toBeVisible();
  for (const width of [375, 768, 1440, 2560])
    await auditPage(page, `/jobs/${firstId}`, "monitor", width);
  await page.getByRole("link", { name: /View results/ }).click();
  const resultsPath = new URL(page.url()).pathname;
  for (const width of [375, 768, 1440, 2560])
    await auditPage(page, resultsPath, "results", width);
  await page.goto(`/jobs/${firstId}`, { waitUntil: "networkidle" });
  await page.getByRole("button", { name: /Retry as new/ }).click();
  await page.waitForURL(new RegExp(`/jobs/(?!${firstId})[^/]+$`));
  await waitForTerminal(page);
  await expect(
    page.getByText("existing evidence reused", { exact: false }),
  ).toBeVisible();
  await expect(page.locator(".task-run-grid .run-marker.reused")).toHaveCount(
    1,
  );
  await page.getByRole("link", { name: /View results/ }).click();
  await expect(
    page.getByRole("heading", { name: "Task and repeat outcomes" }),
  ).toBeVisible();
  await expect(page.locator(".task-run-grid")).toBeVisible();

  await launchMock(page, 3);
  await expect(
    page.getByRole("button", { name: "Cancel evaluation" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Cancel evaluation" }).click();
  await waitForTerminal(page);
  await expect(page.getByText("Evaluation canceled")).toBeVisible();
});

test("reports regeneration, JSON export, settings round-trip, and unreachable Ollama recovery work", async ({
  page,
}) => {
  await page.goto("/reports", { waitUntil: "networkidle" });
  await page.getByRole("button", { name: "Regenerate report" }).click();
  await expect(
    page.getByText("reports/leaderboard.html", { exact: false }),
  ).toBeVisible();
  const exportResponse = await page.request.get("/api/v1/export?format=json");
  expect(exportResponse.ok()).toBeTruthy();
  expect((await exportResponse.json()).format).toBe("json");

  await page.goto("/settings", { waitUntil: "networkidle" });
  await page.getByLabel("Default repeats").fill("2");
  await page.getByRole("button", { name: "Save defaults" }).click();
  await expect(page.getByText("saved", { exact: true })).toBeVisible();
  await page.reload({ waitUntil: "networkidle" });
  await expect(page.getByLabel("Default repeats")).toHaveValue("2");

  await page.goto("/new", { waitUntil: "networkidle" });
  await page.getByRole("button", { name: /Ollama/ }).click();
  await page.getByLabel("Base URL").fill("http://127.0.0.1:9");
  await page.getByRole("button", { name: "Verify backend" }).click();
  await expect(page.getByText("Could not connect")).toBeVisible();
  await page.getByRole("button", { name: /Mock/ }).click();
  await page.getByRole("button", { name: "Verify backend" }).click();
  await expect(page.getByText("1 model available")).toBeVisible();
});

test("optional single local Ollama smoke runs only when an installed model is reachable", async ({
  page,
}) => {
  let tags: { models?: Array<{ name?: string }> };
  try {
    const response = await fetch("http://127.0.0.1:11434/api/tags");
    if (!response.ok) {
      test.skip(true, "Ollama is not reachable");
      return;
    }
    tags = (await response.json()) as { models?: Array<{ name?: string }> };
  } catch {
    test.skip(true, "Ollama is not reachable");
    return;
  }
  const model = tags.models?.find((item) => item.name)?.name;
  if (!model) {
    test.skip(true, "Ollama has no installed models");
    return;
  }
  test.setTimeout(180_000);
  await page.goto("/new", { waitUntil: "networkidle" });
  await page.getByRole("button", { name: /Ollama/ }).click();
  await page.getByRole("button", { name: "Verify backend" }).click();
  await expect(page.getByText(/model.*available/).first()).toBeVisible({
    timeout: 10_000,
  });
  await page.getByRole("button", { name: "Continue" }).click();
  await page
    .getByRole("button", {
      name: new RegExp(model.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")),
    })
    .click();
  await page.getByRole("button", { name: "Continue" }).click();
  await page.locator('.task-option input[type="checkbox"]').first().check();
  await page.getByRole("button", { name: "Continue" }).click();
  await page.getByLabel("Repeats per task").fill("1");
  await page.getByRole("button", { name: "Continue" }).click();
  await page.getByRole("button", { name: /Launch 1 runs/ }).click();
  await page.waitForURL(/\/jobs\/[^/]+$/);
  await waitForTerminal(page);
});
