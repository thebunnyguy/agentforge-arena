import { cpSync, mkdirSync, mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { spawn } from "node:child_process";

const repo = resolve(fileURLToPath(new URL("../..", import.meta.url)));
const temp = mkdtempSync(join(tmpdir(), "agentforge-arena-real-app-"));
const port = Number(process.env.AFA_REAL_APP_PORT ?? 4175);

for (const directory of ["afa_api", "kernel", "runner", "examples", "tasks"]) {
  cpSync(join(repo, directory), join(temp, directory), { recursive: true });
}
mkdirSync(join(temp, "reports"), { recursive: true });
mkdirSync(join(temp, "web"), { recursive: true });
// The runtime refuses ROOT/reports/runs.sqlite as a writable DB (immutable evidence);
// the app works on a differently named copy of it.
cpSync(join(repo, "reports", "runs.sqlite"), join(temp, "reports", "app.sqlite"));
cpSync(join(repo, "web", "dist"), join(temp, "web", "dist"), { recursive: true });

const child = spawn("python3", ["-m", "uvicorn", "afa_api.main:app", "--host", "127.0.0.1", "--port", String(port)], {
  cwd: temp,
  env: {
    ...process.env,
    AFA_DB_PATH: join(temp, "reports", "app.sqlite"),
    AFA_SERVE_WEB: "1",
    AFA_WEB_DIST: join(temp, "web", "dist"),
    PYTHONPATH: [temp, join(temp, "kernel"), join(temp, "runner")].join(":"),
  },
  stdio: ["ignore", "pipe", "pipe"],
});

let output = "";
child.stdout.on("data", (chunk) => { output += chunk.toString(); });
child.stderr.on("data", (chunk) => { output += chunk.toString(); });

async function waitForServer() {
  for (let attempt = 0; attempt < 120; attempt += 1) {
    try {
      const response = await fetch(`http://127.0.0.1:${port}/api/v1/healthz`);
      if (response.ok) return;
    } catch {
      // Startup is still in progress.
    }
    await new Promise((resolvePromise) => setTimeout(resolvePromise, 250));
  }
  throw new Error(`AgentForge API did not start.\n${output}`);
}

function cleanup() {
  child.kill("SIGTERM");
  setTimeout(() => child.kill("SIGKILL"), 3000).unref();
  rmSync(temp, { recursive: true, force: true });
}

process.on("SIGTERM", cleanup);
process.on("SIGINT", cleanup);
process.on("exit", () => rmSync(temp, { recursive: true, force: true }));

await waitForServer();
console.log(`AgentForge real app ready at http://127.0.0.1:${port}`);
await new Promise(() => {});
