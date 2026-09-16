import { useCallback, useEffect, useRef, useState, useSyncExternalStore } from "react"
import { SettingsIcon } from "lucide-react"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog"
import { Separator } from "@/components/ui/separator"
import { useApiKeys } from "@/hooks/useApiKeys"
import { useConfig } from "@/hooks/useConfig"
import { useModel } from "@/hooks/useModel"
import { useTools } from "@/hooks/useTools"
import { fetchModels, type ModelInfo } from "@/lib/api"
import type { ModelPrefName } from "@/store/modelStore"
import { API_KEY_NAMES, hasUsableLlmKey, type ApiKeyName } from "@/store/apiKeysStore"
import {
  clearSettingsFocusKey,
  getSettingsDialogOpen,
  getSettingsFocusKey,
  setSettingsDialogOpen,
  subscribeSettingsDialog,
} from "@/store/settingsDialogStore"

const KEY_LABELS: Record<ApiKeyName, string> = {
  ANTHROPIC_API_KEY: "Anthropic (Claude)",
  OPENROUTER_API_KEY: "OpenRouter",
  TAVILY_API_KEY: "Tavily",
  AMASS_API_KEY: "Amass",
  NEBIUS_API_KEY: "Nebius",
}

const KEY_HINTS: Record<ApiKeyName, string> = {
  ANTHROPIC_API_KEY: "Runs your questions on Claude. One of Anthropic or OpenRouter is required — there's no shared key.",
  OPENROUTER_API_KEY:
    "Free, no credit card (openrouter.ai/keys) — 50 requests/day per account, 1,000/day after ever buying $10 of credits once. One of Anthropic or OpenRouter is required — there's no shared key.",
  TAVILY_API_KEY: "Optional — enables live web/paper/trial search instead of a mock result.",
  AMASS_API_KEY:
    "Optional — enables live Amass Core lookups in the tool loop instead of a mock result, and upgrades literature grounding from PubMed/ClinicalTrials.gov to Amass's curated corpus. Grounding works fine without this — it just uses the free sources instead.",
  NEBIUS_API_KEY: "Optional — improves gene/protein extraction quality over the built-in regex heuristic.",
}

// The Claude models the cost table (backend/agent/costs.py) knows how to
// price — anything else would show up unpriced in the cost panel. The
// deployment's own defaults come from GET /api/config (models.toml).
const CLAUDE_MODELS: { id: string; name: string }[] = [
  { id: "claude-sonnet-5", name: "Claude Sonnet 5" },
  { id: "claude-opus-5", name: "Claude Opus 5" },
  { id: "claude-haiku-4-5", name: "Claude Haiku 4.5" },
]

const CLAUDE_TIERS: { pref: ModelPrefName; policyKey: "main" | "fast"; label: string; hint: string }[] = [
  {
    pref: "ANTHROPIC_MODEL",
    policyKey: "main",
    label: "Claude model — main",
    hint: "Planning, tool use, revision and the report.",
  },
  {
    pref: "GROUNDING_FAST_MODEL",
    policyKey: "fast",
    label: "Claude model — fast",
    hint: "Cheap sub-tasks: the grounding probe and verification.",
  },
]

function claudeName(id: string): string {
  return CLAUDE_MODELS.find((m) => m.id === id)?.name ?? id
}

export function SettingsDialog() {
  const open = useSyncExternalStore(subscribeSettingsDialog, getSettingsDialogOpen)
  const focusKey = useSyncExternalStore(subscribeSettingsDialog, getSettingsFocusKey)
  const config = useConfig()
  const { tools } = useTools()
  const { keys, setKey, clearKey } = useApiKeys()
  const { preferredModel, setModel, prefs, setPref } = useModel()
  const [drafts, setDrafts] = useState<Partial<Record<ApiKeyName, string>>>({})
  // Latest drafts, readable from the close handler without re-binding it.
  const draftsRef = useRef(drafts)
  useEffect(() => {
    draftsRef.current = drafts
  }, [drafts])
  const [models, setModels] = useState<ModelInfo[]>([])
  const [recommended, setRecommended] = useState<string>("")

  useEffect(() => {
    fetchModels()
      .then((res) => {
        setModels(res.models)
        setRecommended(res.recommended)
      })
      .catch(() => {
        // Model picker just falls back to "Auto" — the backend still picks
        // a free model on its own even if this listing call fails.
      })
  }, [])

  // Jump straight to one key's input (e.g. ToolsPanel's "needs a key" link
  // passes its own key_env_var to openSettingsDialog). One-shot: consumed
  // right after use so a later plain re-open doesn't re-jump to a stale target.
  useEffect(() => {
    if (!open || !focusKey) return
    const target = focusKey
    const raf = requestAnimationFrame(() => {
      const el = document.getElementById(`key-${target}`) as HTMLInputElement | null
      el?.scrollIntoView({ behavior: "smooth", block: "center" })
      el?.focus()
    })
    clearSettingsFocusKey()
    return () => cancelAnimationFrame(raf)
  }, [open, focusKey])

  function platformConfigured(name: ApiKeyName): boolean {
    if (name === "ANTHROPIC_API_KEY") return config?.anthropic_key_configured ?? false
    if (name === "OPENROUTER_API_KEY") return config?.openrouter_key_configured ?? false
    return tools.find((t) => t.key_env_var === name)?.key_configured ?? false
  }

  function handleSave(name: ApiKeyName) {
    const value = (drafts[name] ?? "").trim()
    if (value) setKey(name, value)
    else clearKey(name)
    setDrafts((d) => ({ ...d, [name]: undefined }))
  }

  // Closing the dialog (Escape, backdrop, the X) commits any key that was
  // pasted but never explicitly saved — a typed key silently vanishing on
  // close is the "my key didn't save" bug. An emptied field is left alone:
  // clearing a stored key stays an explicit action (the Clear button).
  const handleOpenChange = useCallback(
    (next: boolean) => {
      if (!next) {
        let flushed = false
        for (const [name, draft] of Object.entries(draftsRef.current) as [ApiKeyName, string | undefined][]) {
          const value = (draft ?? "").trim()
          if (value) {
            setKey(name, value)
            flushed = true
          }
        }
        if (flushed || Object.keys(draftsRef.current).length) setDrafts({})
      }
      setSettingsDialogOpen(next)
    },
    [setKey]
  )

  const policy = config?.anthropic_models
  const claudeOverridable = policy?.allow_override ?? true

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogTrigger asChild>
        <Button variant="outline" size="icon-lg" title="Settings — bring your own API keys">
          <SettingsIcon className="size-4" />
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Settings</DialogTitle>
          <DialogDescription>
            Bring your own API keys. An Anthropic or OpenRouter key is required to run anything — there's no
            platform-held key. Everything here — keys and model picks — is remembered by this browser
            (localStorage) and sent to the backend with each run's request, never saved server-side. With both
            keys set, a run starts on OpenRouter (free) and moves to Claude only if OpenRouter fails.
          </DialogDescription>
        </DialogHeader>

        {!hasUsableLlmKey(keys) && (
          <p className="text-xs text-amber-600 dark:text-amber-400">
            No LLM key set yet — add Anthropic or OpenRouter below before starting a run.
          </p>
        )}

        <div className="space-y-4">
          {API_KEY_NAMES.map((name) => {
            const stored = keys[name]
            const draft = drafts[name]
            const hasStored = !!stored
            return (
              <div key={name} className="space-y-1">
                <div className="flex items-center justify-between gap-2">
                  <label htmlFor={`key-${name}`} className="text-sm font-medium">
                    {KEY_LABELS[name]}
                  </label>
                  <span className="text-[10px] text-muted-foreground shrink-0">
                    {hasStored ? "your key set" : platformConfigured(name) ? "platform default" : "not configured"}
                  </span>
                </div>
                <p className="text-xs text-muted-foreground">{KEY_HINTS[name]}</p>
                <div className="flex items-center gap-2">
                  <input
                    id={`key-${name}`}
                    type="password"
                    autoComplete="off"
                    placeholder={hasStored ? "•••••••••••••• (set — type to replace)" : "paste key"}
                    value={draft ?? ""}
                    onChange={(e) => setDrafts((d) => ({ ...d, [name]: e.target.value }))}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" && draft !== undefined) {
                        e.preventDefault()
                        handleSave(name)
                      }
                    }}
                    className="flex-1 rounded-md border border-input bg-transparent px-2 py-1 text-sm"
                  />
                  <Button size="sm" variant="secondary" onClick={() => handleSave(name)} disabled={draft === undefined}>
                    Save
                  </Button>
                  {hasStored && (
                    <Button size="sm" variant="ghost" onClick={() => clearKey(name)}>
                      Clear
                    </Button>
                  )}
                </div>
              </div>
            )
          })}
        </div>

        <Separator />

        <div className="space-y-1">
          <label htmlFor="model-select" className="text-sm font-medium">
            OpenRouter model
          </label>
          <p className="text-xs text-muted-foreground">
            Only free models are listed — whichever one is picked, it never costs anything. "Auto" always uses
            whatever currently ranks best (this list and the ranking both come live from OpenRouter, so it changes
            as their free lineup does).
          </p>
          <select
            id="model-select"
            value={preferredModel}
            onChange={(e) => setModel(e.target.value)}
            className="w-full rounded-md border border-input bg-transparent px-2 py-1 text-sm"
          >
            <option value="">
              Auto — currently {models.find((m) => m.id === recommended)?.name ?? (recommended || "best free model")}
            </option>
            {models.map((m) => (
              <option key={m.id} value={m.id}>
                {m.name}
              </option>
            ))}
          </select>
        </div>

        <Separator />

        <div className="space-y-3">
          <div>
            <p className="text-sm font-medium">Claude models</p>
            <p className="text-xs text-muted-foreground">
              Used when a run is on your Anthropic key — as the fallback when OpenRouter fails, or on its own
              when no OpenRouter key is set. Sonnet and Opus are billed to your key at full price; Haiku is the
              cheap tier.
              {policy && !claudeOverridable && (
                <>
                  {" "}
                  <span className="text-amber-600 dark:text-amber-400">
                    This {policy.environment} deployment pins both tiers to {claudeName(policy.main)}
                    {policy.fast !== policy.main ? ` / ${claudeName(policy.fast)}` : ""} — the picks below only
                    apply on production.
                  </span>
                </>
              )}
            </p>
          </div>
          {CLAUDE_TIERS.map((tier) => {
            const deploymentDefault = policy?.[tier.policyKey]
            return (
              <div key={tier.pref} className="space-y-1">
                <label htmlFor={`model-${tier.pref}`} className="text-xs font-medium">
                  {tier.label}
                </label>
                <p className="text-[11px] text-muted-foreground">{tier.hint}</p>
                <select
                  id={`model-${tier.pref}`}
                  value={prefs[tier.pref] ?? ""}
                  disabled={!claudeOverridable}
                  onChange={(e) => setPref(tier.pref, e.target.value)}
                  className="w-full rounded-md border border-input bg-transparent px-2 py-1 text-sm disabled:opacity-60"
                >
                  <option value="">
                    Auto — {deploymentDefault ? claudeName(deploymentDefault) : "deployment default"}
                  </option>
                  {CLAUDE_MODELS.map((m) => (
                    <option key={m.id} value={m.id}>
                      {m.name}
                    </option>
                  ))}
                </select>
              </div>
            )
          })}
        </div>

        <Separator />
        <p className="text-xs text-muted-foreground">
          No key is billed or held by the platform — this app doesn't work until you've added one above.
        </p>
      </DialogContent>
    </Dialog>
  )
}
