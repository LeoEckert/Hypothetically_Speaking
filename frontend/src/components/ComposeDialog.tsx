import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Separator } from "@/components/ui/separator"
import { Textarea } from "@/components/ui/textarea"
import { ToolsPanel } from "@/components/ToolsPanel"

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

        <Separator />

        <div>
          <p className="text-sm font-semibold mb-2">Tools</p>
          <ToolsPanel isRunLive={isRunLive} />
        </div>
      </DialogContent>
    </Dialog>
  )
}
