import { useEffect, useRef, useState } from "react"
import { AppHeader } from "@/components/AppHeader"
import { ComposeDialog } from "@/components/ComposeDialog"
import { HistoryPanel } from "@/components/HistoryPanel"
import { HypothesisDetailsView } from "@/components/HypothesisDetailsView"
import { LiveRunBar } from "@/components/LiveRunBar"
import { OnboardingDialog } from "@/components/OnboardingDialog"
import { ProgressView } from "@/components/ProgressView"
import { ResultsView } from "@/components/ResultsView"
import { TooltipProvider } from "@/components/ui/tooltip"
import { useConfig } from "@/hooks/useConfig"
import { useRunsStore } from "@/hooks/useRunsStore"
import { evaluateHypothesis } from "@/lib/api"
import { deriveLiveStatus } from "@/lib/liveStatus"
import { cancelCurrentStream, currentLiveRunId, onStreamFinished, startAndStream } from "@/lib/runStream"
import { getApiKeysSnapshot, hasUsableLlmKey, loadApiKeys } from "@/store/apiKeysStore"
import { getModelPrefs } from "@/store/modelStore"
import { appendEvaluation, createRun, deleteRun, getRun } from "@/store/runsStore"
import type { SseEvent, RunMode } from "@/types"

function App() {
  const runs = useRunsStore()
  const config = useConfig()

  const [liveRunId, setLiveRunId] = useState<string | null>(currentLiveRunId())
  const [viewedRunId, setViewedRunId] = useState<string | null>(null)
  const [showDetails, setShowDetails] = useState(false)
  const [composeOpen, setComposeOpen] = useState(false)
  const [historyOpen, setHistoryOpen] = useState(false)
  const [onboardingOpen, setOnboardingOpen] = useState(() => !hasUsableLlmKey(getApiKeysSnapshot()))
  const [question, setQuestion] = useState("")
  const [maxToolCalls, setMaxToolCalls] = useState(15)
  const [mode, setMode] = useState<RunMode>("fast")
  const prefilledRef = useRef(false)
  const budgetInitRef = useRef(false)

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
    setQuestion(config?.dev_mode ? config.demo_question : "")
    setComposeOpen(true)
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

  // Model preferences (Settings) ride the same api_keys request field as the
  // actual BYOK keys (see backend/agent/providers/__init__.py's get_provider()
  // and backend/agent/model_policy.py) — merged in here rather than inside
  // apiKeysStore itself, since they aren't secrets and live in their own
  // store (modelStore.ts). Only set entries are sent, so the backend's own
  // defaults apply to anything left on "Auto".
  function apiKeysForRequest() {
    return { ...loadApiKeys(), ...getModelPrefs() }
  }

  async function handleRun() {
    const trimmed = question.trim()
    if (!trimmed || liveRunId) return

    if (!hasUsableLlmKey(getApiKeysSnapshot())) {
      setOnboardingOpen(true)
      return
    }

    const forkedFrom = viewedRunId && viewedRunId !== liveRunId ? viewedRunId : null
    const runId = await startAndStream({ question: trimmed, maxToolCalls, mode, apiKeys: apiKeysForRequest() })
    createRun(runId, trimmed, forkedFrom)
    setLiveRunId(runId)
    setViewedRunId(runId)
    setShowDetails(false)
    setComposeOpen(false)
  }

  function handleCancel() {
    if (!liveRunId) return
    cancelCurrentStream(liveRunId)
  }

  function handleDeleteHistory(id: string) {
    if (id === liveRunId) {
      cancelCurrentStream(id)
      setLiveRunId(null)
    }
    if (id === viewedRunId) {
      setViewedRunId(null)
      setShowDetails(false)
    }
    deleteRun(id)
  }

  function handleIterate(seedQuestion: string) {
    setQuestion(seedQuestion)
    setComposeOpen(true)
  }

  async function handleEvaluate(comment: string) {
    if (!viewedRunId || !doneEvent) return
    const result = await evaluateHypothesis(
      viewedRunId,
      { report: doneEvent.report, hypotheses: doneEvent.hypotheses, evidence: doneEvent.evidence },
      comment,
      apiKeysForRequest()
    )
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
      ? "Basing the new question on the run you're viewing — edit it below and hit Run to branch a new hypothesis."
      : null

  const showLiveBanner = liveRunId !== null && viewedRunId !== liveRunId

  return (
    <TooltipProvider>
      <div className="min-h-screen bg-muted/20">
        <div className="max-w-6xl mx-auto p-4 sm:p-6">
          <AppHeader
            runsCount={runs.length}
            onOpenHistory={() => setHistoryOpen(true)}
            onNewRequest={handleNewRequest}
          />

          <OnboardingDialog open={onboardingOpen} onOpenChange={setOnboardingOpen} />

          <HistoryPanel
            runs={runs}
            viewedRunId={viewedRunId}
            onSelect={handleSelectHistory}
            onDelete={handleDeleteHistory}
            open={historyOpen}
            onOpenChange={setHistoryOpen}
          />

          <ComposeDialog
            open={composeOpen}
            onOpenChange={setComposeOpen}
            question={question}
            onQuestionChange={setQuestion}
            onRun={handleRun}
            runDisabled={liveRunId !== null}
            isRunLive={liveRunId !== null}
            forkNote={forkNote}
            mode={mode}
            onModeChange={setMode}
            maxToolCalls={maxToolCalls}
            onMaxToolCallsChange={setMaxToolCalls}
            maxToolCallsCeiling={config?.max_tool_calls_ceiling ?? 25}
          />

          <main>
            <LiveRunBar
              isRunning={isRunning}
              question={viewedRun?.question ?? ""}
              statusText={statusText}
              run={isViewingLive ? viewedRun : undefined}
              onCancel={handleCancel}
              showLiveBanner={showLiveBanner}
              onViewLive={handleViewLive}
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
            ) : viewedRun ? (
              <ProgressView run={viewedRun} />
            ) : (
              <p className="text-sm text-muted-foreground italic py-8 text-center">
                Ask a research question to get started — use "+ New Hypothesis" above.
              </p>
            )}
          </main>
        </div>
      </div>
    </TooltipProvider>
  )
}

export default App
