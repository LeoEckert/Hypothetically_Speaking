export const API_BASE =
  (import.meta.env.VITE_API_BASE_URL as string | undefined) ||
  (import.meta.env.DEV ? "http://localhost:8000" : "")

if (!API_BASE && !import.meta.env.DEV) {
  // eslint-disable-next-line no-console
  console.warn(
    "VITE_API_BASE_URL is not set — API calls will fail. Set it in your Vercel project's environment variables."
  )
}

export interface ConfigResponse {
  dev_mode: boolean
  demo_question: string
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

export async function startRun(question: string): Promise<{ run_id: string }> {
  const res = await fetch(`${API_BASE}/api/run`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question }),
  })
  return res.json()
}

export function runStreamUrl(runId: string): string {
  return `${API_BASE}/api/run/${runId}/stream`
}
