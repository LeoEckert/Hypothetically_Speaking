import type { RunRecord, SseEvent } from "@/types"

const STORAGE_KEY = "hs_history_v2"
const MAX_HISTORY = 25

let runs: RunRecord[] = load()
const listeners = new Set<() => void>()

function load(): RunRecord[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    return raw ? (JSON.parse(raw) as RunRecord[]) : []
  } catch {
    return []
  }
}

function save() {
  // Cap history size; if we still can't fit (quota), drop oldest until it works
  // or give up rather than losing every run's history.
  let toSave = runs
  while (toSave.length > 0) {
    try {
      const trimmed = [...toSave].sort((a, b) => b.createdAt - a.createdAt).slice(0, MAX_HISTORY)
      localStorage.setItem(STORAGE_KEY, JSON.stringify(trimmed))
      return
    } catch {
      // quota exceeded — drop the oldest entry and retry
      toSave = [...toSave].sort((a, b) => b.createdAt - a.createdAt).slice(0, toSave.length - 1)
    }
  }
}

function notify() {
  for (const listener of listeners) listener()
}

export function subscribe(listener: () => void): () => void {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

export function getSnapshot(): RunRecord[] {
  return runs
}

export function getRun(id: string): RunRecord | undefined {
  return runs.find((r) => r.id === id)
}

export function createRun(id: string, question: string, parentId: string | null): RunRecord {
  const run: RunRecord = {
    id,
    question,
    createdAt: Date.now(),
    status: "running",
    events: [],
    parentId,
  }
  runs = [run, ...runs]
  if (runs.length > MAX_HISTORY) {
    runs = [...runs].sort((a, b) => b.createdAt - a.createdAt).slice(0, MAX_HISTORY)
  }
  save()
  notify()
  return run
}

export function appendEvent(runId: string, event: SseEvent) {
  const idx = runs.findIndex((r) => r.id === runId)
  if (idx === -1) return
  const run = runs[idx]
  const updated: RunRecord = { ...run, events: [...run.events, event] }
  if (event.type === "done") {
    updated.status = event.partial ? "partial" : "done"
    updated.cost = event.cost
    updated.evidence = event.evidence
  } else if (event.type === "error") {
    // An "error" event means the run is failing, but a `done` event still
    // follows it in this codebase's loop (it always finalizes) — don't
    // downgrade status here, `done` is authoritative for the final state.
  }
  runs = [...runs.slice(0, idx), updated, ...runs.slice(idx + 1)]
  save()
  notify()
}

export function markErrored(runId: string) {
  const idx = runs.findIndex((r) => r.id === runId)
  if (idx === -1) return
  const run = runs[idx]
  if (run.status !== "running") return
  const updated: RunRecord = { ...run, status: "error" }
  runs = [...runs.slice(0, idx), updated, ...runs.slice(idx + 1)]
  save()
  notify()
}
