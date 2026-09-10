import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./tests",
  testMatch: "**/*.spec.ts",
  timeout: 30_000,
  fullyParallel: false,
  reporter: "line",
  use: {
    baseURL: process.env.AFA_TEST_BASE_URL ?? "http://127.0.0.1:8125",
    launchOptions: { channel: "chrome" },
  },
});
