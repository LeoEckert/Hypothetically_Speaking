import { useState } from "react"
import { SparklesIcon } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Textarea } from "@/components/ui/textarea"
import { EvaluationPanel } from "@/components/EvaluationPanel"
import type { EvaluationResult, EvidenceItem } from "@/types"

export function EvaluateBlock({
  evidence,
  evaluations,
  onEvaluate,
}: {
  evidence: Record<string, EvidenceItem>
  evaluations: EvaluationResult[]
  onEvaluate: (comment: string) => Promise<void>
}) {
  const [comment, setComment] = useState("")
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function handleClick() {
    setBusy(true)
    setError(null)
    try {
      await onEvaluate(comment)
      setComment("")
    } catch (err) {
      setError(err instanceof Error ? err.message : "Evaluation failed.")
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="space-y-2">
      <p className="text-xs font-semibold text-muted-foreground">Evaluate with AI</p>
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
      {evaluations
        .slice()
        .reverse()
        .map((ev, i) => (
          <EvaluationPanel key={`${ev.created_at}-${i}`} evaluation={ev} evidence={evidence} />
        ))}
    </div>
  )
}
