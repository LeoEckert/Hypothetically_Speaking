import { CheckIcon } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { WaitingDots } from "@/components/WaitingDots"
import { useElapsedSeconds } from "@/hooks/useElapsedSeconds"
import { deriveLiveProgress } from "@/lib/liveStatus"
import type { RunRecord } from "@/types"

function PhaseStepper({ steps }: { steps: ReturnType<typeof deriveLiveProgress>["steps"] }) {
  return (
    <ol className="flex flex-wrap items-center gap-x-1 gap-y-1" aria-label="Run steps">
      {steps.map((step, i) => (
        <li key={step.key} className="flex items-center gap-1">
          {i > 0 && <span className={`h-px w-4 ${step.state === "upcoming" ? "bg-border" : "bg-primary/60"}`} />}
          <span
            className={`flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] ${
              step.state === "current"
                ? "border-primary bg-primary/10 font-medium text-primary"
                : step.state === "done"
                  ? "border-primary/40 text-foreground/80"
                  : "border-dashed text-muted-foreground"
            }`}
          >
            {step.state === "done" && <CheckIcon className="size-3" />}
            {step.state === "current" && <span className="size-2 animate-pulse rounded-full bg-primary" />}
            {step.label}
          </span>
        </li>
      ))}
    </ol>
  )
}

export function LiveRunBar({
  isRunning,
  question,
  statusText,
  run,
  onCancel,
  showLiveBanner,
  onViewLive,
}: {
  isRunning: boolean
  question: string
  statusText: string
  run?: RunRecord
  onCancel: () => void
  showLiveBanner: boolean
  onViewLive: () => void
}) {
  const progress = run ? deriveLiveProgress(run) : null
  const elapsed = useElapsedSeconds(run?.phaseStartedAt, isRunning)

  if (!isRunning && !showLiveBanner) return null

  return (
    <Card className="mb-4 py-3 shadow-sm">
      <CardContent className="px-4 space-y-3">
        {showLiveBanner && (
          <div className="flex items-center justify-between border rounded-lg p-3 bg-primary/5 text-sm">
            <span>A run is in progress in the background.</span>
            <Button variant="outline" size="sm" onClick={onViewLive}>
              View live run
            </Button>
          </div>
        )}

        {isRunning && (
          <div className="space-y-2">
            <div className="flex items-center justify-between gap-3">
              <div className="min-w-0">
                <p className="text-sm truncate">{question}</p>
                <p className="text-sm font-medium text-muted-foreground">{progress?.headline ?? statusText}</p>
              </div>
              <Button onClick={onCancel} variant="destructive" size="sm" className="shrink-0">
                Cancel
              </Button>
            </div>
            {progress && (
              <>
                <PhaseStepper steps={progress.steps} />
                <p className="text-xs text-muted-foreground" aria-live="polite">
                  {progress.waiting ? (
                    <WaitingDots className="mr-1.5" />
                  ) : (
                    <span className="inline-block size-1.5 animate-pulse rounded-full bg-primary/70 align-middle mr-1.5" />
                  )}
                  {progress.detail}
                  {run?.phaseStartedAt ? ` · ${elapsed}s in this step` : ""}
                  {progress.remaining.length > 0 && (
                    <span className="text-muted-foreground/70"> · then: {progress.remaining.join(" → ")}</span>
                  )}
                </p>
              </>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  )
}
