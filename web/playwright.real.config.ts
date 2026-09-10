import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./tests",
  testMatch: "**/real-app.spec.ts",
  timeout: 120_000,
  fullyParallel: false,
  reporter: "line",
  webServer: {
    command: "node tests/real-app-server.mjs",
    url: "http://127.0.0.1:4175",
    reuseExistingServer: false,
    timeout: 90_000,
  },
  use: {
    baseURL: "http://127.0.0.1:4175",
    launchOptions: { channel: "chrome" },
  },
});
