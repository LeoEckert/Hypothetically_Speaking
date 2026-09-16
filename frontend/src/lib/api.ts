// The backend is a Python serverless function inside this same Vercel
// project (frontend/api/[...path].py, staged at deploy time — see
// .github/workflows/deploy-frontend.yml) — production calls are
// same-origin, so no base URL at all is the right default.
// VITE_API_BASE_URL still overrides this if the backend is ever split back
// out to its own host.
import type { AdminKeyInfo, AdminUsageHistory, AdminUsageSnapshot, EvaluationResult, ToolInfo } from "@/types"

const PROD_API_BASE_FALLBACK = ""

export const API_BASE =
  (import.meta.env.VITE_API_BASE_URL as string | undefined) ||
  (import.meta.env.DEV ? "http://localhost:8000" : PROD_API_BASE_FALLBACK)

export interface ConfigResponse {
  dev_mode: boolean
  demo_question: string
  max_tool_calls_default: number
  max_tool_calls_ceiling: number
  anthropic_key_configured: boolean
  openrouter_key_configured: boolean
  default_provider: string
  // With both keys a run starts on provider_order[0] and falls back to the
  // next one only if it fails (backend/agent/providers/fallback.py).
  provider_order?: string[]
  // Which Claude models this deployment uses per tier and whether Settings
  // may override them — backend/config/models.toml via model_policy.py.
  anthropic_models?: AnthropicModelPolicy
}

export interface AnthropicModelPolicy {
  environment: "production" | "preview" | "development" | string
  main: string
  fast: string
  allow_override: boolean
}

export async function fetchConfig(): Promise<ConfigResponse> {
  const res = await fetch(`${API_BASE}/api/config`)
  return res.json()
}

export interface ModelInfo {
  id: string
  name: string
  context_length: number | null
}

export interface ModelsResponse {
  models: ModelInfo[]
  recommended: string
}

export async function fetchModels(): Promise<ModelsResponse> {
  const res = await fetch(`${API_BASE}/api/models`)
  return res.json()
}

export async function fetchTools(): Promise<ToolInfo[]> {
  const res = await fetch(`${API_BASE}/api/tools`)
  return res.json()
}

// Every path below stays ONE segment past /api. On this Vercel account the
// catch-all Python function only matches a single segment, so anything
// deeper 404s at the platform level before the backend is ever invoked —
// that is what broke "Evaluate with AI" in production. See docs/DEPLOY.md's
// routing section; the identifier goes in the body instead of the path.
export async function setToolEnabled(name: string, enabled: boolean) {
  const res = await fetch(`${API_BASE}/api/tool`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, enabled }),
  })
  return res.json()
}

// startRun/cancelRun/runStreamUrl are gone: POST /api/run now runs the whole
// agent loop and streams its trace back within that one request/response
// (see backend/server/app.py) — starting and streaming a run is one call,
// implemented in @/lib/runStream since it needs to read a streaming fetch
// response body rather than issue a plain JSON fetch. Cancelling means
// aborting that same request (@/lib/runStream's cancelCurrentStream).

export async function evaluateHypothesis(
  runId: string,
  runResult: { report: string; hypotheses: unknown[]; evidence: Record<string, unknown> },
  comment: string,
  apiKeys: Record<string, string> = {}
): Promise<EvaluationResult> {
  const res = await fetch(`${API_BASE}/api/evaluate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ comment, run_result: runResult, api_keys: apiKeys, run_id: runId }),
  })
  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    throw new Error(body.detail || `evaluate failed (${res.status})`)
  }
  return res.json()
}

function adminHeaders(token: string): HeadersInit {
  return { "Content-Type": "application/json", "X-Admin-Token": token }
}

async function adminJson<T>(path: string, token: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, { ...init, headers: adminHeaders(token) })
  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    throw new Error(body.detail || `admin request failed (${res.status})`)
  }
  return res.json()
}

export async function fetchAdminUsage(token: string): Promise<AdminUsageSnapshot> {
  return adminJson<AdminUsageSnapshot>("/api/admin/usage", token)
}

export async function fetchAdminUsageHistory(
  token: string,
  opts: { granularity?: "day" | "hour"; days?: number; hours?: number } = {}
): Promise<AdminUsageHistory> {
  const { granularity = "day", days = 30, hours = 24 } = opts
  const query = granularity === "hour" ? `granularity=hour&hours=${hours}` : `granularity=day&days=${days}`
  return adminJson<AdminUsageHistory>(`/api/admin/usage/history?${query}`, token)
}

export async function fetchAdminKeys(token: string): Promise<AdminKeyInfo[]> {
  return adminJson<AdminKeyInfo[]>("/api/admin/keys", token)
}

export async function rotateAdminKey(
  token: string,
  name: string,
  value: string
): Promise<{ name: string; updated: boolean; masked: string }> {
  return adminJson(`/api/admin/keys/${encodeURIComponent(name)}`, token, {
    method: "POST",
    body: JSON.stringify({ value }),
  })
}

export async function rotateAdminToken(token: string): Promise<{ token: string }> {
  return adminJson("/api/admin/token/rotate", token, { method: "POST" })
}
