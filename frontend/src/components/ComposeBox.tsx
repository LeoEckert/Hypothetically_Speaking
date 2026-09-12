import { useState } from "react"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Textarea } from "@/components/ui/textarea"

export type ComposeVariant = "prominent" | "running" | "results"

export function ComposeBox({
  question,
  onQuestionChange,
  onRun,
  onCancel,
  runDisabled,
  isRunning,
  statusText,
  forkNote,
  showLiveBanner,
  onViewLive,
  maxToolCalls,
  onMaxToolCallsChange,
  maxToolCallsCeiling,
  variant = "prominent",
}: {
  question: string
  onQuestionChange: (v: string) => void
  onRun: () => void
  onCancel: () => void
  runDisabled: boolean
  isRunning: boolean
  statusText: string
  forkNote: string | null
  showLiveBanner: boolean
  onViewLive: () => void
  maxToolCalls: number
  onMaxToolCallsChange: (n: number) => void
  maxToolCallsCeiling: number
  variant?: ComposeVariant
}) {
  const [editorOpen, setEditorOpen] = useState(variant === "prominent")
  const showEditor = variant === "prominent" || editorOpen

  return (
    <Card className={variant === "prominent" ? "py-4 shadow-sm" : "py-3 shadow-sm"}>
      <CardContent className="px-4 space-y-3">
        {showLiveBanner && (
          <div className="flex items-center justify-between border rounded-lg p-3 bg-primary/5 text-sm">
            <span>A run is in progress in the background.</span>
            <Button variant="outline" size="sm" onClick={onViewLive}>
              View live run
            </Button>
          </div>
        )}

        {variant === "running" && (
          <div className="flex items-center justify-between gap-3">
            <div className="min-w-0">
              <p className="text-sm truncate">{question}</p>
              <p className="text-sm font-medium text-muted-foreground">{statusText}</p>
            </div>
            <Button onClick={onCancel} variant="destructive" size="sm" className="shrink-0">
              Cancel
            </Button>
          </div>
        )}

        {variant === "results" && !showEditor && (
          <div className="flex items-center justify-between gap-3">
            <p className="text-sm text-muted-foreground truncate">
              {forkNote ?? "Ask a follow-up, or edit and re-run to branch a new hypothesis."}
            </p>
            <Button variant="outline" size="sm" onClick={() => setEditorOpen(true)} className="shrink-0">
              Edit question
            </Button>
          </div>
        )}

        {showEditor && variant !== "running" && (
          <>
            {forkNote && variant === "prominent" && <p className="text-sm text-primary">{forkNote}</p>}
            <Textarea
              value={question}
              onChange={(e) => onQuestionChange(e.target.value)}
              placeholder="e.g. Does SIRT1 activation plausibly extend human healthspan via mitochondrial biogenesis?"
              className={variant === "prominent" ? "min-h-[90px] resize-y" : "min-h-[60px] resize-y"}
              autoFocus={variant !== "prominent"}
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
                  disabled={isRunning}
                  onChange={(e) => {
                    const n = parseInt(e.target.value, 10)
                    if (!Number.isNaN(n)) onMaxToolCallsChange(Math.max(1, Math.min(n, maxToolCallsCeiling)))
                  }}
                  className="w-16 rounded-md border border-input bg-transparent px-2 py-1 text-sm disabled:opacity-50"
                />
                <span className="text-xs">(max {maxToolCallsCeiling})</span>
              </label>

              {variant === "prominent" && <span className="text-sm font-medium text-muted-foreground">{statusText}</span>}
            </div>
          </>
        )}
      </CardContent>
    </Card>
  )
}
