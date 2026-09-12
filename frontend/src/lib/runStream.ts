// Module-level EventSource singleton, keyed by run_id. Deliberately outside
// React's render cycle: creating this inside a useEffect would double-open
// under StrictMode's dev-mode double-invoke, silently dropping half the
// events (a Queue-backed SSE endpoint has exactly one consumer per event).
import { runStreamUrl } from "@/lib/api"
import { appendEvent, markErrored } from "@/store/runsStore"
import type { SseEvent } from "@/types"

let currentRunId: string | null = null
let currentSource: EventSource | null = null
const finishedListeners = new Set<(runId: string) => void>()

export function onStreamFinished(cb: (runId: string) => void): () => void {
  finishedListeners.add(cb)
  return () => finishedListeners.delete(cb)
}

export function ensureStream(runId: string): void {
  if (currentRunId === runId && currentSource) return

  currentSource?.close()
  currentRunId = runId
  const es = new EventSource(runStreamUrl(runId))
  currentSource = es

  const finish = () => {
    es.close()
    if (currentRunId === runId) {
      currentSource = null
      currentRunId = null
    }
    for (const cb of finishedListeners) cb(runId)
  }

  es.onmessage = (msg) => {
    let event: SseEvent
    try {
      event = JSON.parse(msg.data)
    } catch {
      return
    }
    appendEvent(runId, event)
    if (event.type === "stream_end") finish()
  }

  es.onerror = () => {
    markErrored(runId)
    finish()
  }
}

export function currentLiveRunId(): string | null {
  return currentRunId
}
