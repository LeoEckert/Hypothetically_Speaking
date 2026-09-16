import { ArrowLeftIcon } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { ConfidenceBadge } from "@/components/HypothesisCard"
import type { EvaluateProgress } from "@/lib/api"
import { EvaluateBlock } from "@/components/EvaluateBlock"
import { ReportView } from "@/components/ReportView"
import type { EvaluationResult, EvidenceItem, RankedHypothesis } from "@/types"

export function HypothesisDetailsView({
  hypothesis,
  report,
  evidence,
  evaluations,
  onIterate,
  onEvaluate,
  onBack,
}: {
  hypothesis: RankedHypothesis
  report: string
  evidence: Record<string, EvidenceItem>
  evaluations?: EvaluationResult[]
  onIterate: (seedQuestion: string) => void
  onEvaluate: (comment: string, onProgress?: (p: EvaluateProgress) => void) => Promise<void>
  onBack: () => void
}) {
  const h = hypothesis
  return (
    <div className="mt-4 space-y-4">
      <Button variant="ghost" size="sm" onClick={onBack} className="-ml-2">
        <ArrowLeftIcon className="size-3.5" />
        Back to overview
      </Button>

      <div className="flex flex-wrap items-center gap-2">
        <span className="font-mono text-xs text-muted-foreground">#{h.rank}</span>
        <p className="text-sm font-semibold">{h.statement}</p>
        <ConfidenceBadge confidence={h.confidence} />
      </div>

      <ReportView report={report} evidence={evidence} />

      {h.seed_question && (
        <Button size="sm" variant="outline" onClick={() => onIterate(h.seed_question)}>
          Iterate on this hypothesis
        </Button>
      )}

      <Card>
        <CardContent>
          <EvaluateBlock
            hypothesis={h}
            report={report}
            evidence={evidence}
            evaluations={evaluations ?? []}
            onEvaluate={onEvaluate}
          />
        </CardContent>
      </Card>
    </div>
  )
}
