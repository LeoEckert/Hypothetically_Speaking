// Production fallback so a fresh deploy works without any Vercel dashboard
// configuration — set VITE_API_BASE_URL as a project env var to override
// this (e.g. after moving the backend to a new host), no code change needed
// either way since the env var always takes precedence when set.
const PROD_API_BASE_FALLBACK = "https://api-185-175-110-142.sslip.io"

export const API_BASE =
  (import.meta.env.VITE_API_BASE_URL as string | undefined) ||
  (import.meta.env.DEV ? "http://localhost:8000" : PROD_API_BASE_FALLBACK)

export interface ConfigResponse {
  dev_mode: boolean
  demo_question: string
  max_tool_calls_default: number
  max_tool_calls_ceiling: number
}

export async function fetchConfig(): Promise<ConfigResponse> {
  const res = await fetch(`${API_BASE}/api/config`)
  return res.json()
}

export async function fetchTools() {
  const res = await fetch(`${API_BASE}/api/tools`)
  return res.json()
}

export async function setToolEnabled(name: string, enabled: boolean) {
  const res = await fetch(`${API_BASE}/api/tools/${encodeURIComponent(name)}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ enabled }),
  })
  return res.json()
}

export async function startRun(
  question: string,
  maxToolCalls?: number
): Promise<{ run_id: string; max_tool_calls: number }> {
  const res = await fetch(`${API_BASE}/api/run`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question, max_tool_calls: maxToolCalls }),
  })
  return res.json()
}

export async function cancelRun(runId: string): Promise<void> {
  await fetch(`${API_BASE}/api/run/${runId}/cancel`, { method: "POST" })
}

export function runStreamUrl(runId: string): string {
  return `${API_BASE}/api/run/${runId}/stream`
}
