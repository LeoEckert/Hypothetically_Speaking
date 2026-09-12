import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Separator } from "@/components/ui/separator"
import { Textarea } from "@/components/ui/textarea"
import { ToolsPanel } from "@/components/ToolsPanel"
import type { RunMode } from "@/types"

const MODES: Array<{ value: RunMode; label: string; hint: string }> = [
  { value: "fast", label: "Fast", hint: "The question's own claims plus one hop (4 links), shorter abstracts, no second search — about half the time and cost" },
  { value: "normal", label: "Thorough", hint: "Up to 8 links, whole abstracts, and a second literature search before any link is called unverified" },
]

export function ComposeDialog({
  open,
  onOpenChange,
  question,
  onQuestionChange,
  onRun,
  runDisabled,
  isRunLive,
  forkNote,
  maxToolCalls,
  onMaxToolCallsChange,
  maxToolCallsCeiling,
  mode,
  onModeChange,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  question: string
  onQuestionChange: (v: string) => void
  onRun: () => void
  runDisabled: boolean
  isRunLive: boolean
  forkNote: string | null
  maxToolCalls: number
  onMaxToolCallsChange: (n: number) => void
  maxToolCallsCeiling: number
  mode: RunMode
  onModeChange: (mode: RunMode) => void
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>New hypothesis</DialogTitle>
          <DialogDescription>
            Ask an ageing/longevity research question — the agent will plan, retrieve, compute, and cite.
          </DialogDescription>
        </DialogHeader>

        {forkNote && <p className="text-sm text-primary">{forkNote}</p>}

        <Textarea
          value={question}
          onChange={(e) => onQuestionChange(e.target.value)}
          placeholder="e.g. Does SIRT1 activation plausibly extend human healthspan via mitochondrial biogenesis?"
          className="min-h-[120px] resize-y"
          autoFocus
        />

        <div className="flex items-center gap-3 flex-wrap">
          <Button onClick={onRun} disabled={runDisabled || !question.trim()} size="lg">
            Run
          </Button>

          <div className="flex items-center gap-1 rounded-md border p-0.5" role="radiogroup" aria-label="Run mode">
            {MODES.map((option) => (
              <button
                key={option.value}
                type="button"
                role="radio"
                aria-checked={mode === option.value}
                title={option.hint}
                onClick={() => onModeChange(option.value)}
                className={`rounded px-2.5 py-1 text-xs font-medium transition-colors ${
                  mode === option.value ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:bg-muted"
                }`}
              >
                {option.label}
              </button>
            ))}
          </div>

          <label className="flex items-center gap-1.5 text-sm text-muted-foreground">
            Tool budget:
            <input
              type="number"
              min={1}
              max={maxToolCallsCeiling}
              value={maxToolCalls}
              onChange={(e) => {
                const n = parseInt(e.target.value, 10)
                if (!Number.isNaN(n)) onMaxToolCallsChange(Math.max(1, Math.min(n, maxToolCallsCeiling)))
              }}
              className="w-16 rounded-md border border-input bg-transparent px-2 py-1 text-sm"
            />
            <span className="text-xs">(max {maxToolCallsCeiling})</span>
          </label>
        </div>

        <p className="text-xs text-muted-foreground">{MODES.find((option) => option.value === mode)?.hint}</p>

        <Separator />

        <div>
          <p className="text-sm font-semibold mb-2">Tools</p>
          <ToolsPanel isRunLive={isRunLive} />
        </div>
      </DialogContent>
    </Dialog>
  )
}
