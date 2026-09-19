import { chromium } from "/Users/manuk/Downloads/projects/agentforge arena/web/node_modules/playwright-core/index.mjs";
import fs from "node:fs";

const SP = "/private/tmp/claude-501/-Users-manuk-Downloads-projects-agentforge-arena/a4b308d1-f6d9-4aaf-a1ce-ef53d97bb3aa/scratchpad";
const OUT = `${SP}/smoke/ui_${process.argv[3] || "run"}`;
fs.mkdirSync(OUT, { recursive: true });
const base = "http://127.0.0.1:8765";
const model = fs.readFileSync(`${SP}/smoke/model.txt`, "utf8").trim();
const job = fs.readFileSync(`${SP}/smoke/job.txt`, "utf8").trim();
const enc = encodeURIComponent;
const routes = (process.argv[2] || "all") === "503"
  ? [["overview_503", "/"], ["leaderboard_503", "/leaderboard"], ["cell_503", `/cell/${enc("qwen3.5:9b")}/sanitize-filename`], ["jobs_503", "/jobs"], ["job_results_503", `/jobs/${job}/results`]]
  : [
      ["overview", "/"],
      ["leaderboard", "/leaderboard"],
      ["agents", "/agents"],
      ["tasks", "/tasks"],
      ["task_sanitize", "/task/sanitize-filename"],
      ["cell_new_model", `/cell/${enc(model)}/sanitize-filename`],
      ["cell_historical_bumped", `/cell/${enc("qwen3.5:9b")}/sanitize-filename`],
      ["cell_historical_unbumped", `/cell/${enc("qwen3.5:9b")}/fix-binary-search`],
      ["jobs", "/jobs"],
      ["job_detail", `/jobs/${job}`],
      ["job_results", `/jobs/${job}/results`],
      ["run_from_job", `/jobs/${job}/runs/sanitize-filename/0`],
      ["reports", "/reports"],
    ];

const browser = await chromium.launch();
const ctx = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
const summary = [];
for (const [name, path] of routes) {
  const page = await ctx.newPage();
  const consoleErrs = [];
  const bad = [];
  page.on("console", (m) => { if (m.type() === "error") consoleErrs.push(m.text().slice(0, 200)); });
  page.on("pageerror", (e) => consoleErrs.push("pageerror: " + e.message.slice(0, 200)));
  page.on("response", (r) => { if (r.status() >= 400) bad.push(`${r.status()} ${r.url().replace(base, "")}`); });
  let status = "ok";
  try {
    await page.goto(base + path, { waitUntil: "networkidle", timeout: 30000 });
    await page.waitForTimeout(700);
  } catch (e) { status = "nav-error: " + e.message.slice(0, 120); }
  const text = await page.evaluate(() => document.body.innerText).catch(() => "");
  fs.writeFileSync(`${OUT}/${name}.txt`, text);
  await page.screenshot({ path: `${OUT}/${name}.png`, fullPage: true }).catch(() => {});
  summary.push({ name, path, status, chars: text.length, consoleErrors: consoleErrs, badResponses: bad });
  await page.close();
}
await browser.close();
fs.writeFileSync(`${OUT}/summary.json`, JSON.stringify(summary, null, 2));
for (const s of summary) console.log(`${s.name.padEnd(26)} chars=${String(s.chars).padEnd(6)} ${s.status} consoleErrors=${s.consoleErrors.length} bad=${JSON.stringify(s.badResponses)}`);
