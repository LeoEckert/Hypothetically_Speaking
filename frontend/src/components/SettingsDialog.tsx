import { useState } from "react"
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
import { useTools } from "@/hooks/useTools"
import { API_KEY_NAMES, hasUsableLlmKey, type ApiKeyName } from "@/store/apiKeysStore"

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
  AMASS_API_KEY: "Optional — enables live Amass Core lookups instead of a mock result.",
  NEBIUS_API_KEY: "Optional — improves gene/protein extraction quality over the built-in regex heuristic.",
}

export function SettingsDialog() {
  const config = useConfig()
  const { tools } = useTools()
  const { keys, setKey, clearKey } = useApiKeys()
  const [drafts, setDrafts] = useState<Partial<Record<ApiKeyName, string>>>({})

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

  return (
    <Dialog>
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
            platform-held key. Everything here is stored only in this browser and sent to the backend with each
            run's request, never saved server-side.
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
        <p className="text-xs text-muted-foreground">
          No key is billed or held by the platform — this app doesn't work until you've added one above.
        </p>
      </DialogContent>
    </Dialog>
  )
}
