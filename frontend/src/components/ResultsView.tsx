import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from "@/components/ui/accordion"
import { CostPanel } from "@/components/CostPanel"
import { EvidencePanel } from "@/components/EvidencePanel"
import { HypothesisList } from "@/components/HypothesisCard"
import { ReportView } from "@/components/ReportView"
import { TraceTimeline } from "@/components/TraceTimeline"
import type { CostSummary, EvidenceItem, RankedHypothesis, RunRecord } from "@/types"

export function ResultsView({
  run,
  report,
  evidence,
  hypotheses,
  cost,
  onIterate,
}: {
  run: RunRecord
  report: string
  evidence: Record<string, EvidenceItem>
  hypotheses: RankedHypothesis[]
  cost: CostSummary
  onIterate: (seedQuestion: string) => void
}) {
  return (
    <div className="mt-4 space-y-4">
      {hypotheses.length > 0 && (
        <div className="p-4 border rounded-xl shadow-sm bg-card">
          <p className="text-sm font-semibold mb-2">Candidate hypotheses (ranked)</p>
          <HypothesisList
            hypotheses={hypotheses}
            evidence={evidence}
            onIterate={onIterate}
            autoExpandSelected
          />
        </div>
      )}

      <ReportView report={report} evidence={evidence} />

      <Accordion type="multiple" className="border rounded-xl bg-card px-4">
        <AccordionItem value="evidence">
          <AccordionTrigger>Evidence ({Object.keys(evidence).length})</AccordionTrigger>
          <AccordionContent>
            <EvidencePanel evidence={evidence} />
          </AccordionContent>
        </AccordionItem>
        <AccordionItem value="trace">
          <AccordionTrigger>Tool-call trace</AccordionTrigger>
          <AccordionContent>
            <TraceTimeline events={run.events} />
          </AccordionContent>
        </AccordionItem>
      </Accordion>

      <CostPanel cost={cost} />
    </div>
  )
}
