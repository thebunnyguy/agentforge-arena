import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./tests",
  testMatch: "**/async-lifecycle.spec.ts",
  timeout: 30_000,
  fullyParallel: false,
  reporter: "line",
  webServer: {
    command: "npm run dev -- --host 127.0.0.1 --port 4174",
    url: "http://127.0.0.1:4174",
    reuseExistingServer: false,
    timeout: 60_000,
  },
  use: {
    baseURL: "http://127.0.0.1:4174",
    launchOptions: { channel: "chrome" },
  },
});
