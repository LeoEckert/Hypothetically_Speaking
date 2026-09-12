import type { Page } from "@playwright/test"

export const STORE_KEY = "hs_history_v3"

export type RunProbe = {
  id: string
  status: string
  events: number
  toolsCalled: string[]
  hasDone: boolean
}

/** Read the newest run straight out of the store the app actually persists to,
 *  rather than scraping rendered text — page copy is what we're testing. */
export async function latestRun(page: Page): Promise<RunProbe | null> {
  return page.evaluate((key) => {
    const raw = localStorage.getItem(key)
    if (!raw) return null
    const runs = JSON.parse(raw) as Array<Record<string, never>>
    const r = [...runs].sort((a, b) => (b.createdAt as never) - (a.createdAt as never))[0]
    if (!r) return null
    const events = (r.events ?? []) as Array<Record<string, string>>
    return {
      id: r.id as unknown as string,
      status: r.status as unknown as string,
      events: events.length,
      toolsCalled: events.filter((e) => e.type === "tool_call").map((e) => e.tool),
      hasDone: events.some((e) => e.type === "done"),
    }
  }, STORE_KEY)
}

export async function startRun(page: Page, question: string, budget: number) {
  await page.getByRole("button", { name: /New Hypothesis/i }).click()
  await page.locator("textarea").fill(question)
  await page.locator('input[type="number"]').fill(String(budget))
  await page.getByRole("button", { name: /^Run$/ }).click()
}

/** Poll the store until the run leaves a non-terminal state. */
export async function waitForTerminal(page: Page, timeoutMs = 5 * 60 * 1000) {
  const deadline = Date.now() + timeoutMs
  while (Date.now() < deadline) {
    const r = await latestRun(page)
    if (r && r.status !== "running" && r.status !== "cancelling") return r
    await page.waitForTimeout(5000)
  }
  throw new Error("run did not reach a terminal status in time")
}
