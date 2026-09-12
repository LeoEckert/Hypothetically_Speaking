import { GroundingLive, GroundingTrace } from "@/components/GroundingTrace"
import { HypothesisList } from "@/components/HypothesisCard"
import { TraceTimeline } from "@/components/TraceTimeline"
import type { RunRecord } from "@/types"

export function ProgressView({ run }: { run: RunRecord }) {
  return (
    <div className="mt-4 space-y-4">
      {run.grounding ? (
        <GroundingTrace grounding={run.grounding} question={run.question} />
      ) : (
        <GroundingLive steps={run.groundingSteps ?? []} question={run.question} status={run.status} />
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
