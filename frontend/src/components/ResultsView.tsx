import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from "@/components/ui/accordion"
import { CostPanel } from "@/components/CostPanel"
import { EvidencePanel } from "@/components/EvidencePanel"
import { GroundingTrace } from "@/components/GroundingTrace"
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
              {/* Not available on this deployment, not a bug to chase: the
                  trajectory view reads runs/knowledge.db, a graph that's
                  meant to accumulate across many runs — but this app is a
                  stateless Vercel serverless function with no persistent
                  disk between requests (see docs/DEPLOY.md), so that file
                  never has anything in it here. Works locally
                  (`python -m scripts.run_grounding --kb`) where the
                  filesystem actually persists between runs. */}
              <p className="text-sm text-muted-foreground">
                Not available on this deployment — the knowledge trajectory accumulates across many runs on a local
                database file, and this app runs as a stateless serverless function with no persistent storage
                between requests. Works when running the backend locally.
              </p>
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
