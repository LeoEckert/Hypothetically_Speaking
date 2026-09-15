// Optional OpenRouter model override, kept client-side only — same vanilla
// subscribe/localStorage pattern as apiKeysStore.ts, but deliberately a
// separate store: this isn't a secret (it's a plain dropdown, not a
// password input), it just happens to ride the same api_keys request field
// as a per-request override (backend/agent/providers/__init__.py's
// get_provider() reads api_keys["OPENROUTER_MODEL"] before falling back to
// its own live best-free-model pick). Empty/unset means "let the backend
// pick" — see GET /api/models for the live list this is populated from.
const STORAGE_KEY = "hs_model_pref_v1"

let preferredModel: string = load()
const listeners = new Set<() => void>()

function load(): string {
  try {
    return localStorage.getItem(STORAGE_KEY) ?? ""
  } catch {
    return ""
  }
}

function save() {
  try {
    if (preferredModel) {
      localStorage.setItem(STORAGE_KEY, preferredModel)
    } else {
      localStorage.removeItem(STORAGE_KEY)
    }
  } catch {
    // private window / blocked site data — just won't persist across a reload
  }
}

function notify() {
  for (const listener of listeners) listener()
}

export function subscribePreferredModel(listener: () => void): () => void {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

export function getPreferredModel(): string {
  return preferredModel
}

export function setPreferredModel(modelId: string): void {
  preferredModel = modelId
  save()
  notify()
}
