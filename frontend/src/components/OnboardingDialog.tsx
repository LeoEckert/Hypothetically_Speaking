import { useState } from "react"
import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { setApiKey } from "@/store/apiKeysStore"

// There is no platform-held LLM key at all (see CLAUDE.md) — every visitor
// needs their own before a run can start. OpenRouter's free tier needs no
// credit card (50 requests/day free, 1,000/day after ever buying $10 of
// credits once) and is the guided path; a Claude API key works too, for
// anyone who already has one.
export function OnboardingDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void }) {
  const [openrouterDraft, setOpenrouterDraft] = useState("")
  const [anthropicDraft, setAnthropicDraft] = useState("")

  const canContinue = openrouterDraft.trim() || anthropicDraft.trim()

  function handleContinue() {
    if (openrouterDraft.trim()) setApiKey("OPENROUTER_API_KEY", openrouterDraft.trim())
    if (anthropicDraft.trim()) setApiKey("ANTHROPIC_API_KEY", anthropicDraft.trim())
    onOpenChange(false)
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>One quick step before you start</DialogTitle>
          <DialogDescription>
            This app needs an LLM key to run — there's no shared key everyone draws from, so every visitor brings
            their own free one. It's stored only in this browser and sent with your run requests, never saved on
            the server.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          <div className="space-y-1.5 rounded-md border p-3">
            <p className="text-sm font-medium">Recommended: a free OpenRouter key</p>
            <p className="text-xs text-muted-foreground">
              No credit card needed.{" "}
              <a
                href="https://openrouter.ai/keys"
                target="_blank"
                rel="noreferrer"
                className="underline underline-offset-2"
              >
                Create an account and copy a key
              </a>{" "}
              (about 30 seconds), then paste it below. Free tier: 50 requests/day per account.
            </p>
            <input
              type="password"
              autoComplete="off"
              placeholder="paste your OpenRouter key"
              value={openrouterDraft}
              onChange={(e) => setOpenrouterDraft(e.target.value)}
              className="w-full rounded-md border border-input bg-transparent px-2 py-1 text-sm"
            />
          </div>

          <div className="space-y-1.5 rounded-md border p-3">
            <p className="text-sm font-medium">Already have a Claude API key?</p>
            <p className="text-xs text-muted-foreground">Use that instead — your run will use Claude directly.</p>
            <input
              type="password"
              autoComplete="off"
              placeholder="paste your Anthropic key"
              value={anthropicDraft}
              onChange={(e) => setAnthropicDraft(e.target.value)}
              className="w-full rounded-md border border-input bg-transparent px-2 py-1 text-sm"
            />
          </div>
        </div>

        <div className="flex items-center justify-between gap-3 pt-1">
          <button
            type="button"
            onClick={() => onOpenChange(false)}
            className="text-xs text-muted-foreground underline underline-offset-2"
          >
            I'll do this later
          </button>
          <Button onClick={handleContinue} disabled={!canContinue}>
            Save and continue
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  )
}
