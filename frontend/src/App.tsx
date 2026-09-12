import { useEffect, useRef, useState } from "react"
import { ComposeBox, type ComposeVariant } from "@/components/ComposeBox"
import { HypothesisDetailsView } from "@/components/HypothesisDetailsView"
import { ProgressView } from "@/components/ProgressView"
import { ResultsView } from "@/components/ResultsView"
import { Sidebar } from "@/components/Sidebar"
import { TooltipProvider } from "@/components/ui/tooltip"
import { useConfig } from "@/hooks/useConfig"
import { useRunsStore } from "@/hooks/useRunsStore"
import { cancelRun, evaluateHypothesis, startRun } from "@/lib/api"
import { deriveLiveStatus } from "@/lib/liveStatus"
import { currentLiveRunId, ensureStream, onStreamFinished } from "@/lib/runStream"
import { appendEvaluation, createRun, getRun, markCancelling } from "@/store/runsStore"
import type { SseEvent } from "@/types"

function App() {
  const runs = useRunsStore()
  const config = useConfig()

  const [liveRunId, setLiveRunId] = useState<string | null>(currentLiveRunId())
  const [viewedRunId, setViewedRunId] = useState<string | null>(null)
  const [showDetails, setShowDetails] = useState(false)
  const [question, setQuestion] = useState("")
  const [maxToolCalls, setMaxToolCalls] = useState(30)
  const [sidebarCollapsed, setSidebarCollapsed] = useState(() => {
    try {
      return localStorage.getItem("hs_sidebar_collapsed") === "1"
    } catch {
      return false
    }
  })
  const prefilledRef = useRef(false)
  const budgetInitRef = useRef(false)

  useEffect(() => {
    try {
      localStorage.setItem("hs_sidebar_collapsed", sidebarCollapsed ? "1" : "0")
    } catch {
      // ignore — private browsing / quota, not worth surfacing for a UI preference
    }
  }, [sidebarCollapsed])

  useEffect(() => {
    if (prefilledRef.current) return
    if (config?.dev_mode && config.demo_question) {
      setQuestion(config.demo_question)
      prefilledRef.current = true
    }
  }, [config])

  useEffect(() => {
    if (budgetInitRef.current) return
    if (config?.max_tool_calls_default) {
      setMaxToolCalls(config.max_tool_calls_default)
      budgetInitRef.current = true
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
  const selectedHypothesis = doneEvent?.hypotheses?.find((h) => h.selected)

  function handleNewRequest() {
    setViewedRunId(null)
    setShowDetails(false)
    setQuestion(config?.dev_mode ? config.demo_question : "")
  }

  function handleSelectHistory(id: string) {
    const run = getRun(id)
    if (!run) return
    setViewedRunId(id)
    setShowDetails(false)
    setQuestion(run.question)
  }

  function handleViewLive() {
    if (liveRunId) setViewedRunId(liveRunId)
  }

  async function handleRun() {
    const trimmed = question.trim()
    if (!trimmed || liveRunId) return

    const forkedFrom = viewedRunId && viewedRunId !== liveRunId ? viewedRunId : null
    const { run_id } = await startRun(trimmed, maxToolCalls)
    createRun(run_id, trimmed, forkedFrom)
    setLiveRunId(run_id)
    setViewedRunId(run_id)
    setShowDetails(false)
    ensureStream(run_id)
  }

  function handleCancel() {
    if (!liveRunId) return
    markCancelling(liveRunId)
    cancelRun(liveRunId)
  }

  function handleIterate(seedQuestion: string) {
    setQuestion(seedQuestion)
  }

  async function handleEvaluate(comment: string) {
    if (!viewedRunId) return
    const result = await evaluateHypothesis(viewedRunId, comment)
    appendEvaluation(viewedRunId, result)
  }

  const isViewingLive = liveRunId !== null && viewedRunId === liveRunId
  const isRunning = isViewingLive && (viewedRun?.status === "running" || viewedRun?.status === "cancelling")
  const statusText = (() => {
    if (viewedRun?.status === "cancelling") return "cancelling…"
    if (isViewingLive && viewedRun) return deriveLiveStatus(viewedRun.events)
    if (!viewedRun) return ""
    if (viewedRun.status === "done") return "done"
    if (viewedRun.status === "partial") return "done (partial run — budget limit reached)"
    if (viewedRun.status === "cancelled") return "done (cancelled by you)"
    if (viewedRun.status === "error") return "run failed — see trace"
    return ""
  })()

  const forkNote =
    viewedRunId && viewedRunId !== liveRunId
      ? "Viewing a past run — edit the question above and hit Run to create a new hypothesis based on it."
      : null

  const composeVariant: ComposeVariant = isRunning ? "running" : doneEvent ? "results" : "prominent"

  return (
    <TooltipProvider>
      <div className="min-h-screen bg-muted/20">
        <div className="max-w-6xl mx-auto p-4 sm:p-6">
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
              collapsed={sidebarCollapsed}
              onToggleCollapsed={() => setSidebarCollapsed((v) => !v)}
            />

            <main className="flex-1 min-w-0">
              <ComposeBox
                question={question}
                onQuestionChange={setQuestion}
                onRun={handleRun}
                onCancel={handleCancel}
                runDisabled={liveRunId !== null}
                isRunning={isRunning}
                statusText={statusText}
                forkNote={forkNote}
                showLiveBanner={liveRunId !== null && viewedRunId !== liveRunId}
                onViewLive={handleViewLive}
                maxToolCalls={maxToolCalls}
                onMaxToolCallsChange={setMaxToolCalls}
                maxToolCallsCeiling={config?.max_tool_calls_ceiling ?? 40}
                variant={composeVariant}
              />

              {showDetails && doneEvent && viewedRun && selectedHypothesis ? (
                <HypothesisDetailsView
                  hypothesis={selectedHypothesis}
                  report={doneEvent.report}
                  evidence={doneEvent.evidence}
                  evaluations={viewedRun.evaluations}
                  onIterate={handleIterate}
                  onEvaluate={handleEvaluate}
                  onBack={() => setShowDetails(false)}
                />
              ) : doneEvent && viewedRun ? (
                <ResultsView
                  run={viewedRun}
                  report={doneEvent.report}
                  evidence={doneEvent.evidence}
                  hypotheses={doneEvent.hypotheses ?? []}
                  cost={doneEvent.cost}
                  onIterate={handleIterate}
                  onOpenDetails={() => setShowDetails(true)}
                />
              ) : (
                viewedRun && <ProgressView run={viewedRun} />
              )}
            </main>
          </div>
        </div>
      </div>
    </TooltipProvider>
  )
}

export default App
