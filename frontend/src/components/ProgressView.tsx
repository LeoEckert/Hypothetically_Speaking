import { GroundingLive, GroundingTrace } from "@/components/GroundingTrace"
import { HypothesisList } from "@/components/HypothesisCard"
import { KnowledgeTrajectory } from "@/components/KnowledgeTrajectory"
import { TraceTimeline } from "@/components/TraceTimeline"
import type { RunRecord } from "@/types"

export function ProgressView({ run }: { run: RunRecord }) {
  const steps = run.groundingSteps ?? []
  // The trajectory draws itself from the grounding_step stream as the links
  // are checked, so it is worth showing from the first L0 event on; a
  // grounding that was skipped or failed has nothing to draw.
  const showTrajectory = steps.length > 0 && (!run.grounding || run.grounding.status === "complete")
  return (
    <div className="mt-4 space-y-4">
      {run.grounding ? (
        <GroundingTrace grounding={run.grounding} question={run.question} />
      ) : (
        <GroundingLive steps={steps} question={run.question} status={run.status} />
      )}
      {showTrajectory && (
        <section className="rounded-xl border bg-card p-4 shadow-sm" aria-live="polite">
          <p className="mb-3 text-sm font-semibold">Knowledge trajectory</p>
          <KnowledgeTrajectory grounding={run.grounding} steps={steps} question={run.question} />
        </section>
      )}
      {run.hypotheses && run.hypotheses.length > 0 && (
        <div className="p-4 border rounded-xl shadow-sm bg-card">
          <p className="text-sm font-semibold mb-2">Candidate hypotheses</p>
          <HypothesisList hypotheses={run.hypotheses} evidence={run.evidence ?? {}} grounding={run.grounding} />
        </div>
      )}
      <TraceTimeline events={run.events} startedAtByStep={run.toolStepStartedAt} />
    </div>
  )
}
