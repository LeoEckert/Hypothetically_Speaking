import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from "@/components/ui/accordion"
import { CostPanel } from "@/components/CostPanel"
import { EvidencePanel } from "@/components/EvidencePanel"
import { GroundingTrace } from "@/components/GroundingTrace"
import { API_BASE } from "@/lib/api"
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
  onOpenDetails,
}: {
  run: RunRecord
  report: string
  evidence: Record<string, EvidenceItem>
  hypotheses: RankedHypothesis[]
  cost: CostSummary
  onIterate: (seedQuestion: string) => void
  onOpenDetails?: () => void
}) {
  const hasSelected = hypotheses.some((h) => h.selected)

  return (
    <div className="mt-4 space-y-4">
      {hypotheses.length > 0 && (
        <div className="p-4 border rounded-xl shadow-sm bg-card">
          <p className="text-sm font-semibold mb-2">Candidate hypotheses (ranked)</p>
          <HypothesisList
            hypotheses={hypotheses}
            evidence={evidence}
            onIterate={onIterate}
            onOpenDetails={onOpenDetails}
            grounding={run.grounding}
          />
        </div>
      )}

      {/* A run with no selected hypothesis (error/empty run) has no details
          view to send the report to — show it inline so it's never hidden. */}
      {!hasSelected && <ReportView report={report} evidence={evidence} />}

      <Accordion type="multiple" className="border rounded-xl bg-card px-4">
        {run.grounding && (
          <AccordionItem value="grounding">
            <AccordionTrigger>Premise grounding trace</AccordionTrigger>
            <AccordionContent>
              <GroundingTrace grounding={run.grounding} question={run.question} embedded />
            </AccordionContent>
          </AccordionItem>
        )}
        {run.grounding?.status === "complete" && run.grounding.coherent && (
          <AccordionItem value="trajectory">
            <AccordionTrigger>Knowledge trajectory</AccordionTrigger>
            <AccordionContent>
              <iframe
                title="Knowledge trajectory"
                src={`${API_BASE}/api/trajectory/view?question=${encodeURIComponent(run.question)}`}
                className="h-[520px] w-full rounded-lg border bg-background"
              />
            </AccordionContent>
          </AccordionItem>
        )}
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
