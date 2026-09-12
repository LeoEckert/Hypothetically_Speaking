import { defineConfig, devices } from "@playwright/test"

// Workers are pinned to 1 on purpose: the backend keeps all run state in
// module-level dicts in one uvicorn process, and PUT /api/tools/{name} is a
// process-global toggle — two parallel workers would corrupt each other's
// tool roster mid-run. See CLAUDE.md, "Backend API".
export default defineConfig({
  testDir: "./tests",
  workers: 1,
  fullyParallel: false,
  // A real run at a low tool budget still takes minutes (Anthropic latency
  // dominates, not the tools).
  timeout: 6 * 60 * 1000,
  expect: { timeout: 15 * 1000 },
  reporter: [["list"], ["html", { outputFolder: "playwright-report", open: "never" }]],
  use: {
    baseURL: process.env.HS_BASE_URL ?? "http://localhost:5173",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
})
