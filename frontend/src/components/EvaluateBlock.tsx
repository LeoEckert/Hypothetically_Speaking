import { useState } from "react"
import { SparklesIcon } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Textarea } from "@/components/ui/textarea"
import { EvaluationPanel } from "@/components/EvaluationPanel"
import { useElapsedSeconds } from "@/hooks/useElapsedSeconds"
import type { EvaluateProgress } from "@/lib/api"
import type { EvaluationResult, EvidenceItem, RankedHypothesis } from "@/types"

// Two long model passes, in the order the backend runs them.
const PASSES: { phase: EvaluateProgress["phase"]; label: string; detail: string }[] = [
  { phase: "judge", label: "Critiquing", detail: "reading the hypothesis against the evidence" },
  { phase: "revise", label: "Revising", detail: "rewriting each section from the critique" },
]

function EvaluateProgressReadout({ progress, startedAt }: { progress: EvaluateProgress | null; startedAt: number }) {
  const elapsed = useElapsedSeconds(startedAt, true)
  const activeIndex = progress ? PASSES.findIndex((p) => p.phase === progress.phase) : -1

  return (
    <div className="space-y-1.5 rounded-md border bg-muted/30 p-2.5">
      {PASSES.map((pass, index) => {
        const state = index < activeIndex ? "done" : index === activeIndex ? "active" : "pending"
        return (
          <div key={pass.phase} className="flex items-baseline gap-2 text-xs">
            <span
              className={
                state === "active"
                  ? "text-foreground font-medium"
                  : state === "done"
                    ? "text-muted-foreground"
                    : "text-muted-foreground/60"
              }
            >
              {state === "done" ? "✓" : state === "active" ? "•" : "·"} {pass.label}
            </span>
            <span className="text-muted-foreground/80">
              {state === "active"
                ? `${pass.detail}${progress ? ` — ${progress.chars.toLocaleString()} characters` : ""}`
                : state === "done"
                  ? "done"
                  : pass.detail}
            </span>
          </div>
        )
      })}
      <p className="text-[11px] text-muted-foreground/70">
        {activeIndex === -1 ? "Sending the request…" : "Each pass is one long model call."} {elapsed}s elapsed.
      </p>
    </div>
  )
}

export function EvaluateBlock({
  hypothesis,
  report,
  evidence,
  evaluations,
  onEvaluate,
}: {
  hypothesis: RankedHypothesis
  /** The run's report markdown — the evaluation panel diffs its revised
   * sections against these originals. */
  report: string
  evidence: Record<string, EvidenceItem>
  evaluations: EvaluationResult[]
  onEvaluate: (comment: string, onProgress?: (p: EvaluateProgress) => void) => Promise<void>
}) {
  const [comment, setComment] = useState("")
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [progress, setProgress] = useState<EvaluateProgress | null>(null)
  const [startedAt, setStartedAt] = useState(0)

  async function handleClick() {
    setBusy(true)
    setError(null)
    setProgress(null)
    setStartedAt(Date.now())
    try {
      await onEvaluate(comment, setProgress)
      setComment("")
    } catch (err) {
      setError(err instanceof Error ? err.message : "Evaluation failed.")
    } finally {
      setBusy(false)
      setProgress(null)
    }
  }

  // Only one evaluation per hypothesis — once it exists, it's persisted on
  // the run record, so this gate holds even after navigating away and back.
  if (evaluations.length > 0) {
    return (
      <div className="space-y-3">
        <p className="text-xs font-semibold text-muted-foreground">AI Evaluation</p>
        {evaluations.map((ev, i) => (
          <EvaluationPanel
            key={`${ev.created_at}-${i}`}
            evaluation={ev}
            evidence={evidence}
            original={hypothesis}
            report={report}
          />
        ))}
      </div>
    )
  }

  return (
    <div className="space-y-2">
      <p className="text-xs font-semibold text-muted-foreground">Evaluate with AI</p>
      <p className="text-xs text-muted-foreground">
        One considered pass, not a chat — the model critiques this hypothesis against the
        evidence and returns a revised version. Add a note below if you want to steer it.
      </p>
      <Textarea
        value={comment}
        onChange={(e) => setComment(e.target.value)}
        placeholder="Optional note for the reviewer — e.g. a concern, a paper you know of, what to double-check…"
        className="text-sm"
        rows={2}
      />
      <div className="flex items-center gap-2">
        <Button size="sm" variant="outline" onClick={handleClick} disabled={busy}>
          <SparklesIcon className="size-3.5" />
          {busy ? "Evaluating…" : "Evaluate with AI"}
        </Button>
        {error && <span className="text-xs text-destructive">{error}</span>}
      </div>
      {busy && <EvaluateProgressReadout progress={progress} startedAt={startedAt} />}
    </div>
  )
}
