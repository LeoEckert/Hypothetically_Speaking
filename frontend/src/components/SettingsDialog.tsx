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
import { API_KEY_NAMES, type ApiKeyName } from "@/store/apiKeysStore"

const KEY_LABELS: Record<ApiKeyName, string> = {
  ANTHROPIC_API_KEY: "Anthropic (Claude)",
  GROQ_API_KEY: "Groq",
  TAVILY_API_KEY: "Tavily",
  AMASS_API_KEY: "Amass",
  NEBIUS_API_KEY: "Nebius",
}

const KEY_HINTS: Record<ApiKeyName, string> = {
  ANTHROPIC_API_KEY:
    "Optional — the platform runs on a free-tier default and holds no Claude key of its own. Add yours to run on Claude instead.",
  GROQ_API_KEY: "Optional — the platform provides a shared free-tier Groq key by default; add your own only if it's rate-limited.",
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
    if (name === "GROQ_API_KEY") return config?.groq_key_configured ?? false
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
            Bring your own API keys. Everything here is optional, stored only in this browser, and sent to the
            backend with each run's request — never saved server-side.
          </DialogDescription>
        </DialogHeader>

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
          Default provider: {config?.default_provider ?? "groq"} (free tier, no key needed from you). Adding your own
          Anthropic key runs your next question on Claude instead.
        </p>
      </DialogContent>
    </Dialog>
  )
}
