// Model preferences, kept client-side only — same vanilla subscribe/
// localStorage pattern as apiKeysStore.ts, but deliberately a separate
// store: none of these is a secret (plain dropdowns, not password inputs),
// they just ride the same api_keys request field as per-request overrides
// (App.tsx's apiKeysForRequest() merges them in):
//
//   OPENROUTER_MODEL      pins a specific free OpenRouter model instead of
//                         get_provider()'s live best-free pick (GET /api/models)
//   ANTHROPIC_MODEL       the Claude model for the main tier
//   GROUNDING_FAST_MODEL  the Claude model for the fast tier (grounding probe)
//
// The two Claude picks are honoured by backend/agent/model_policy.py only
// where backend/config/models.toml allows overrides for that deployment
// (production/local yes, the dev preview is pinned to Haiku); GET
// /api/config's `anthropic_models` says which, and SettingsDialog disables
// the pickers accordingly. Empty/unset means "let the backend pick".
const STORAGE_KEY = "hs_model_prefs_v2"
const LEGACY_OPENROUTER_KEY = "hs_model_pref_v1" // v1 held only the OpenRouter pick, as a bare string

export type ModelPrefName = "OPENROUTER_MODEL" | "ANTHROPIC_MODEL" | "GROUNDING_FAST_MODEL"
export type ModelPrefs = Partial<Record<ModelPrefName, string>>

let prefs: ModelPrefs = load()
const listeners = new Set<() => void>()

function load(): ModelPrefs {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (raw) {
      const parsed = JSON.parse(raw) as ModelPrefs
      return typeof parsed === "object" && parsed ? parsed : {}
    }
    const legacy = localStorage.getItem(LEGACY_OPENROUTER_KEY)
    return legacy ? { OPENROUTER_MODEL: legacy } : {}
  } catch {
    return {}
  }
}

function save() {
  try {
    if (Object.keys(prefs).length) {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(prefs))
    } else {
      localStorage.removeItem(STORAGE_KEY)
    }
    localStorage.removeItem(LEGACY_OPENROUTER_KEY)
  } catch {
    // private window / blocked site data — just won't persist across a reload
  }
}

function notify() {
  for (const listener of listeners) listener()
}

export function subscribeModelPrefs(listener: () => void): () => void {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

export function getModelPrefs(): ModelPrefs {
  return prefs
}

export function setModelPref(name: ModelPrefName, modelId: string): void {
  const next = { ...prefs }
  if (modelId) next[name] = modelId
  else delete next[name]
  prefs = next
  save()
  notify()
}

// --- OpenRouter pick, the original single-value API kept for its callers ---

export const subscribePreferredModel = subscribeModelPrefs

export function getPreferredModel(): string {
  return prefs.OPENROUTER_MODEL ?? ""
}

export function setPreferredModel(modelId: string): void {
  setModelPref("OPENROUTER_MODEL", modelId)
}
