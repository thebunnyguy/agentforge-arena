import { defineConfig } from "@playwright/test";

// Benchmark Releases pages against the Vite dev server with a fully mocked
// API (tests/benchmark-releases.spec.ts). The release data is bundled with
// the SPA, so no backend is needed.
export default defineConfig({
  testDir: "./tests",
  testMatch: "**/benchmark-releases.spec.ts",
  timeout: 60_000,
  fullyParallel: false,
  reporter: "line",
  webServer: {
    command: "npm run dev -- --host 127.0.0.1 --port 4176 --strictPort",
    url: "http://127.0.0.1:4176",
    reuseExistingServer: false,
    timeout: 60_000,
  },
  use: {
    baseURL: "http://127.0.0.1:4176",
    launchOptions: { channel: "chrome" },
  },
});
