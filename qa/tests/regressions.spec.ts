import { expect, test } from "@playwright/test"
import { latestRun, startRun, waitForTerminal } from "./helpers"

// Each test below encodes a bug confirmed by hand on 2026-09-12 against
// main @ 8967e8a. They are expected to FAIL until the bug is fixed — that is
// the point; they are the regression net, not a green baseline.

test.describe("terminal run status is never shown to the user", () => {
  // LiveRunBar is the only consumer of App.tsx's statusText, and it returns
  // null unless isRunning || showLiveBanner. isRunning is true only for
  // "running"/"cancelling", so every terminal string it can produce —
  // "done (partial run — budget limit reached)", "done (cancelled by you)",
  // "run failed — see trace" — is computed and thrown away.
  test("a budget-truncated run says so somewhere in the results view", async ({ page }) => {
    await page.goto("/")
    // budget 6 reliably exhausts before the compute step
    await startRun(page, "Does rapamycin extend healthspan via mTOR inhibition?", 6)
    const run = await waitForTerminal(page)
    expect(run.status).toBe("partial")

    const body = await page.evaluate(() => document.body.innerText)
    // "partial estimate" in the cost panel refers to the COST, not the run,
    // so it must not be what satisfies this assertion.
    const costBadgeOnly = /partial estimate/i.test(body)
    const explainsTruncation = /budget limit|partial run|cut short|incomplete run|did not finish/i.test(body)
    expect(
      explainsTruncation,
      `run was "${run.status}" but nothing in the results view explains it` +
        (costBadgeOnly ? ' (only the cost panel\'s "partial estimate" badge appears)' : "")
    ).toBe(true)
  })

  test("a cancelled run says so in the results view", async ({ page }) => {
    await page.goto("/")
    await startRun(page, "Does metformin extend healthspan via AMPK activation?", 30)
    await expect(page.getByRole("button", { name: /^Cancel$/ })).toBeVisible({ timeout: 60_000 })
    await page.getByRole("button", { name: /^Cancel$/ }).click()

    const run = await waitForTerminal(page)
    expect(run.status).toBe("cancelled")
    const body = await page.evaluate(() => document.body.innerText)
    expect(
      /cancelled|canceled|stopped by you/i.test(body),
      "run was cancelled but the results view never says so"
    ).toBe(true)
  })
})

test("reloading mid-run does not abandon the run", async ({ page }) => {
  // The backend replays the whole event list to a late subscriber by design
  // (see CLAUDE.md, "Backend API"), but ensureStream() is only ever called
  // from handleRun — nothing re-attaches on mount, and the page-unload
  // teardown fires es.onerror -> markErrored, so a healthy in-flight run is
  // marked "error" by the act of reloading.
  await page.goto("/")
  await startRun(page, "Does NAD+ repletion restore mitochondrial function in ageing?", 30)

  await expect.poll(async () => (await latestRun(page))?.events ?? 0, { timeout: 90_000 }).toBeGreaterThan(3)
  const before = await latestRun(page)
  expect(before?.status).toBe("running")

  await page.reload({ waitUntil: "networkidle" })
  await page.waitForTimeout(3000)

  const after = await latestRun(page)
  expect(after?.status, "reloading flipped a healthy run to a failed one").not.toBe("error")

  // and it should still be progressing
  await expect
    .poll(async () => (await latestRun(page))?.events ?? 0, { timeout: 90_000 })
    .toBeGreaterThan(before!.events)
})

test("a dead backend is reported to the user, not shown as still running", async ({ page }) => {
  // There is no client-side liveness watchdog. The backend emits ": keepalive"
  // every 15s precisely because long gaps are normal, but the client never
  // checks that they still arrive, so it cannot tell a slow agent from a dead
  // backend. Observed: readyState stays OPEN(1) and no error event fires for
  // 60s+ after the server process is killed.
  await page.goto("/")
  await page.route("**/api/run/*/stream", (route) => route.abort("connectionfailed"))
  await startRun(page, "Does senolytic treatment extend healthspan?", 6)

  await expect
    .poll(
      async () => {
        const body = await page.evaluate(() => document.body.innerText)
        return /lost connection|disconnected|reconnect|backend unavailable|run failed/i.test(body)
      },
      { timeout: 45_000, message: "stream died but the UI never told the user" }
    )
    .toBe(true)
})

test("lowering the tool budget warns that the compute step may be skipped", async ({ page }) => {
  // extract_genes -> run_enrichment is the one mandatory "real computed
  // result" step (CLAUDE.md). At the default budget of 30 it runs (20 calls
  // used). At <=10 the agent spends the whole budget on retrieval and never
  // reaches it — with no warning at the point of choosing the budget.
  await page.goto("/")
  await page.getByRole("button", { name: /New Hypothesis/i }).click()
  await page.locator('input[type="number"]').fill("5")
  await page.waitForTimeout(300)

  // Scope this to the compose controls, NOT the whole dialog: the tool roster
  // below lists "Enrichment analysis (g:Profiler)", so a body-wide match on
  // /enrichment/ passes without any warning existing.
  const controls = await page
    .locator("div", { has: page.locator('input[type="number"]') })
    .last()
    .innerText()
  expect(
    /may not finish|too low|won't reach|will skip|skips the|not enough/i.test(controls),
    `budget set to 5 with no warning that the enrichment step will be skipped; ` +
      `compose controls read: ${JSON.stringify(controls)}`
  ).toBe(true)
})
