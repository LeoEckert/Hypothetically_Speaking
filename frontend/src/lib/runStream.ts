// Module-level fetch-stream singleton, keyed by run_id. Deliberately outside
// React's render cycle: creating this inside a useEffect would double-open
// under StrictMode's dev-mode double-invoke, silently dropping half the
// events (a Queue-backed SSE endpoint has exactly one consumer per event).
//
// POST /api/run now runs the whole agent loop and streams its trace back
// within that one request/response (see backend/server/app.py's module
// docstring) — there's no separate "start" + "stream" endpoint any more, so
// this can't use the native EventSource API (GET-only, no request body): it
// reads the streaming response body directly and parses SSE `data: ` lines
// itself. Cancelling a run means aborting this fetch — the backend treats a
// closed connection as that run's cancel signal.
import { API_BASE } from "@/lib/api"
import { appendEvent, markCancelled, markErrored } from "@/store/runsStore"
import type { RunMode, SseEvent } from "@/types"

let currentRunId: string | null = null
let currentAbort: AbortController | null = null
const finishedListeners = new Set<(runId: string) => void>()

export function onStreamFinished(cb: (runId: string) => void): () => void {
  finishedListeners.add(cb)
  return () => finishedListeners.delete(cb)
}

export function currentLiveRunId(): string | null {
  return currentRunId
}

/** Cancelling a run means aborting its one streaming connection — the
 * backend treats the resulting disconnect as the cancel signal. There's no
 * follow-up `done` event to wait for any more (see runsStore.markCancelled),
 * so this marks the terminal state immediately. */
export function cancelCurrentStream(runId: string): void {
  markCancelled(runId)
  currentAbort?.abort()
}

interface StartRunOptions {
  question: string
  maxToolCalls?: number
  mode?: RunMode
  apiKeys?: Record<string, string>
}

/** Starts a run and streams it into the runsStore, resolving with the
 * run_id as soon as it's known (from the response's X-Run-Id header) — well
 * before the run itself finishes. */
export async function startAndStream(opts: StartRunOptions): Promise<string> {
  currentAbort?.abort()
  const abort = new AbortController()
  currentAbort = abort

  const res = await fetch(`${API_BASE}/api/run`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      question: opts.question,
      max_tool_calls: opts.maxToolCalls,
      mode: opts.mode === "fast" ? "fast" : "normal",
      api_keys: opts.apiKeys ?? {},
    }),
    signal: abort.signal,
  })
  const runId = res.headers.get("X-Run-Id") ?? crypto.randomUUID()
  currentRunId = runId

  const finish = () => {
    if (currentRunId === runId) {
      currentRunId = null
      currentAbort = null
    }
    for (const cb of finishedListeners) cb(runId)
  }

  void (async () => {
    try {
      if (!res.body) throw new Error("no response body")
      const reader = res.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ""
      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        const events = buffer.split("\n\n")
        buffer = events.pop() ?? ""
        for (const rawEvent of events) {
          for (const line of rawEvent.split("\n")) {
            if (!line.startsWith("data: ")) continue
            let event: SseEvent
            try {
              event = JSON.parse(line.slice("data: ".length))
            } catch {
              continue
            }
            appendEvent(runId, event)
            if (event.type === "stream_end") {
              finish()
              return
            }
          }
        }
      }
      finish()
    } catch (err) {
      if (err instanceof DOMException && err.name === "AbortError") {
        finish()
        return
      }
      markErrored(runId)
      finish()
    }
  })()

  return runId
}
