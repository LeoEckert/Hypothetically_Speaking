import { useEffect, useState } from "react"
import { EvaluationPanel } from "@/components/EvaluationPanel"
import { TooltipProvider } from "@/components/ui/tooltip"
import type { EvaluationResult, EvidenceItem, RankedHypothesis } from "@/types"

interface Fixture {
  question: string
  hypothesis: RankedHypothesis
  report: string
  evidence: Record<string, EvidenceItem>
  evaluation: EvaluationResult
}

/** Dev-only harness for the evaluation diff view: renders EvaluationPanel
 * against a saved real evaluation so the component can be iterated on
 * without paying for (or waiting on) a full agent run. Reachable at
 * `?evalpreview` in `vite dev` only; the fixture is a local, gitignored
 * file under `frontend/public/`. */
export function EvalPreview() {
  const [fixture, setFixture] = useState<Fixture | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    fetch("/eval-fixture.json")
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`))))
      .then(setFixture)
      .catch((err: Error) => setError(err.message))
  }, [])

  if (error) {
    return (
      <div className="mx-auto max-w-5xl p-8 text-sm">
        <p className="font-semibold">No fixture found ({error}).</p>
        <p className="mt-2 text-muted-foreground">
          Generate one into <code>frontend/public/eval-fixture.json</code> — it needs the keys{" "}
          <code>hypothesis</code>, <code>report</code>, <code>evidence</code>, <code>evaluation</code>.
        </p>
      </div>
    )
  }

  if (!fixture) return <div className="p-8 text-sm text-muted-foreground">Loading fixture…</div>

  return (
    <TooltipProvider>
      <div className="mx-auto max-w-6xl space-y-4 p-6">
        <div>
          <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            Dev preview · evaluation diff view
          </p>
          <p className="text-sm">{fixture.question}</p>
        </div>
        <EvaluationPanel
          evaluation={fixture.evaluation}
          evidence={fixture.evidence}
          original={fixture.hypothesis}
          report={fixture.report}
        />
      </div>
    </TooltipProvider>
  )
}
