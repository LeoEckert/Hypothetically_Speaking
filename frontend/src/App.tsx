import { useEffect, useRef, useState } from "react"
import { ComposeBox } from "@/components/ComposeBox"
import { CostPanel } from "@/components/CostPanel"
import { ReportView } from "@/components/ReportView"
import { Sidebar } from "@/components/Sidebar"
import { TraceTimeline } from "@/components/TraceTimeline"
import { TooltipProvider } from "@/components/ui/tooltip"
import { useConfig } from "@/hooks/useConfig"
import { useRunsStore } from "@/hooks/useRunsStore"
import { startRun } from "@/lib/api"
import { currentLiveRunId, ensureStream, onStreamFinished } from "@/lib/runStream"
import { createRun, getRun } from "@/store/runsStore"
import type { SseEvent } from "@/types"

function App() {
  const runs = useRunsStore()
  const config = useConfig()

  const [liveRunId, setLiveRunId] = useState<string | null>(currentLiveRunId())
  const [viewedRunId, setViewedRunId] = useState<string | null>(null)
  const [question, setQuestion] = useState("")
  const prefilledRef = useRef(false)

  useEffect(() => {
    if (prefilledRef.current) return
    if (config?.dev_mode && config.demo_question) {
      setQuestion(config.demo_question)
      prefilledRef.current = true
    }
  }, [config])

  useEffect(() => {
    return onStreamFinished((id) => {
      setLiveRunId((cur) => (cur === id ? null : cur))
    })
  }, [])

  const viewedRun = viewedRunId ? getRun(viewedRunId) : undefined
  const doneEvent = viewedRun?.events.find(
    (e): e is Extract<SseEvent, { type: "done" }> => e.type === "done"
  )

  function handleNewRequest() {
    setViewedRunId(null)
    setQuestion(config?.dev_mode ? config.demo_question : "")
  }

  function handleSelectHistory(id: string) {
    const run = getRun(id)
    if (!run) return
    setViewedRunId(id)
    setQuestion(run.question)
  }

  function handleViewLive() {
    if (liveRunId) setViewedRunId(liveRunId)
  }

  async function handleRun() {
    const trimmed = question.trim()
    if (!trimmed || liveRunId) return

    const forkedFrom = viewedRunId && viewedRunId !== liveRunId ? viewedRunId : null
    const { run_id } = await startRun(trimmed)
    createRun(run_id, trimmed, forkedFrom)
    setLiveRunId(run_id)
    setViewedRunId(run_id)
    ensureStream(run_id)
  }

  const isViewingLive = liveRunId !== null && viewedRunId === liveRunId
  const statusText = (() => {
    if (isViewingLive) return `run ${liveRunId} in progress…`
    if (!viewedRun) return ""
    if (viewedRun.status === "done") return "done"
    if (viewedRun.status === "partial") return "done (partial run — budget limit reached)"
    if (viewedRun.status === "error") return "run failed — see trace"
    return ""
  })()

  const forkNote =
    viewedRunId && viewedRunId !== liveRunId
      ? "Viewing a past run — edit the question above and hit Run to create a new hypothesis based on it."
      : null

  return (
    <TooltipProvider>
      <div className="min-h-screen bg-muted/20">
        <div className="max-w-6xl mx-auto p-6">
          <div className="mb-6 pb-4 border-b">
            <h1 className="text-2xl font-bold tracking-tight">Hypothetically Speaking</h1>
            <p className="text-muted-foreground mt-1">
              A Longevity AI Scientist — ask an ageing/longevity research question, watch it plan, retrieve,
              compute, and cite.
            </p>
          </div>

          <div className="flex flex-col md:flex-row gap-6 items-start">
            <Sidebar
              runs={runs}
              liveRunId={liveRunId}
              viewedRunId={viewedRunId}
              onNewRequest={handleNewRequest}
              onSelectHistory={handleSelectHistory}
            />

            <main className="flex-1 min-w-0">
              <ComposeBox
                question={question}
                onQuestionChange={setQuestion}
                onRun={handleRun}
                runDisabled={liveRunId !== null}
                statusText={statusText}
                forkNote={forkNote}
                showLiveBanner={liveRunId !== null && viewedRunId !== liveRunId}
                onViewLive={handleViewLive}
              />

              {viewedRun && <TraceTimeline events={viewedRun.events} />}
              {viewedRun?.cost && <CostPanel cost={viewedRun.cost} />}
              {doneEvent && <ReportView report={doneEvent.report} evidence={doneEvent.evidence} />}
            </main>
          </div>
        </div>
      </div>
    </TooltipProvider>
  )
}

export default App
