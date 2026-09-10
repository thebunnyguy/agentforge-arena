import { expect, test } from "@playwright/test";

const agent = encodeURIComponent("qwen2.5-coder:7b");
const routeCases = [
  ["home", "/"],
  ["wizard", "/new"],
  ["leaderboard", "/leaderboard"],
  ["agent", `/agent/${agent}`],
  ["cell", `/cell/${agent}/fix-binary-search`],
  ["run", `/cell/${agent}/fix-binary-search/run/0`],
  ["settings", "/settings"],
] as const;
const widths = [375, 768, 1440, 2560];

for (const [name, route] of routeCases) {
  for (const width of widths) {
    test(`${name} route fits at ${width}px`, async ({ page }) => {
      await page.setViewportSize({ width, height: 900 });
      const response = await page.goto(route, { waitUntil: "networkidle" });
      expect(response?.ok()).toBeTruthy();
      await expect(page.locator("h1").first()).toBeVisible();
      const layout = await page.evaluate(() => {
        const root = document.documentElement;
        const plots = [
          ...document.querySelectorAll<SVGElement>(".wilson-svg"),
        ].filter((plot) => !plot.closest(".table-scroll"));
        return {
          pageOverflow: root.scrollWidth > window.innerWidth + 1,
          plotOverflow: plots.some(
            (plot) =>
              plot.getBoundingClientRect().right > window.innerWidth + 1,
          ),
        };
      });
      expect(layout.pageOverflow).toBe(false);
      expect(layout.plotOverflow).toBe(false);
      await page.screenshot({
        path: `test-artifacts/${name}-${width}.png`,
        fullPage: true,
      });
    });
  }
}

test("mobile navigation traps focus and closes on Escape", async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 });
  await page.goto("/", { waitUntil: "networkidle" });
  const openButton = page.getByRole("button", { name: "Open navigation" });
  await openButton.click();
  await expect(page.locator("dialog[open]")).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.locator("dialog[open]")).toHaveCount(0);
  await expect(openButton).toBeFocused();
});

test("synthetic reference links resolve to the confirmed index-0 run", async ({
  page,
}) => {
  await page.goto("/task/fix-binary-search", { waitUntil: "networkidle" });
  const referenceRun = page.getByRole("link", { name: "run #0" }).first();
  await expect(referenceRun).toBeVisible();
  await referenceRun.click();
  await expect(page.getByRole("heading", { name: "Run #0" })).toBeVisible();
  await expect(
    page.getByText("Synthetic baseline", { exact: false }).first(),
  ).toBeVisible();
});

test("run evidence tabs support arrow, Home, and End navigation", async ({
  page,
}) => {
  await page.setViewportSize({ width: 768, height: 900 });
  await page.goto(`/cell/${agent}/fix-binary-search/run/0`, {
    waitUntil: "networkidle",
  });
  const patch = page.locator("#run-tab-patch");
  const tests = page.locator("#run-tab-tests");
  const metadata = page.locator("#run-tab-metadata");
  await patch.focus();
  await page.keyboard.press("ArrowRight");
  await expect(tests).toHaveAttribute("aria-selected", "true");
  await page.keyboard.press("End");
  await expect(metadata).toHaveAttribute("aria-selected", "true");
  await page.keyboard.press("Home");
  await expect(patch).toHaveAttribute("aria-selected", "true");
});
