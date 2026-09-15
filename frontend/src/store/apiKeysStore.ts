// BYOK API keys, kept client-side only. Mirrors runsStore.ts's pattern
// (versioned localStorage key, try/catch load/save, subscribe/notify, no
// external state lib) — see docs/DEPLOY.md and CLAUDE.md for why these keys
// live here rather than on the backend: there is no platform-held LLM key at
// all (neither Anthropic nor OpenRouter) — every visitor brings their own,
// guided by OnboardingDialog.tsx. The three tool keys stay optional.
//
// Unlike run history, these are stored in localStorage rather than
// sessionStorage (the admin token's choice, docs/DEPLOY.md) — they're
// load-bearing for the app to do anything at all, not an occasional
// elevated action, so they should survive a tab close.
const STORAGE_KEY = "hs_api_keys_v1"

export type ApiKeyName =
  | "ANTHROPIC_API_KEY"
  | "OPENROUTER_API_KEY"
  | "TAVILY_API_KEY"
  | "AMASS_API_KEY"
  | "NEBIUS_API_KEY"
export type ApiKeys = Partial<Record<ApiKeyName, string>>

export const API_KEY_NAMES: ApiKeyName[] = [
  "ANTHROPIC_API_KEY",
  "OPENROUTER_API_KEY",
  "TAVILY_API_KEY",
  "AMASS_API_KEY",
  "NEBIUS_API_KEY",
]

let keys: ApiKeys = load()
const listeners = new Set<() => void>()

function load(): ApiKeys {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    return raw ? (JSON.parse(raw) as ApiKeys) : {}
  } catch {
    return {}
  }
}

function save() {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(keys))
  } catch {
    // private window / blocked site data / quota — keys just won't persist
    // across a reload; the app still works against whatever's in memory.
  }
}

function notify() {
  for (const listener of listeners) listener()
}

export function subscribeApiKeys(listener: () => void): () => void {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

export function getApiKeysSnapshot(): ApiKeys {
  return keys
}

/** Non-empty keys only, ready to spread into a RunRequest/EvaluateRequest's
 * `api_keys` field — the backend treats an absent key the same as an empty
 * one, but there's no reason to send blanks. */
export function loadApiKeys(): ApiKeys {
  return Object.fromEntries(Object.entries(keys).filter(([, v]) => v && v.trim())) as ApiKeys
}

export function setApiKey(name: ApiKeyName, value: string): void {
  keys = { ...keys, [name]: value }
  save()
  notify()
}

export function clearApiKey(name: ApiKeyName): void {
  const next = { ...keys }
  delete next[name]
  keys = next
  save()
  notify()
}

/** Is there any usable LLM key at all — the thing that actually gates
 * whether a run can start (see OnboardingDialog.tsx / App.tsx's handleRun). */
export function hasUsableLlmKey(k: ApiKeys = keys): boolean {
  return !!(k.ANTHROPIC_API_KEY?.trim() || k.OPENROUTER_API_KEY?.trim())
}
