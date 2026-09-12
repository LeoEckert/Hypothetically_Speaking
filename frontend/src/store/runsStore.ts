import type { EvaluationResult, RunRecord, SseEvent } from "@/types"

const STORAGE_KEY = "hs_history_v3"
const PREV_STORAGE_KEY = "hs_history_v2"
const MAX_HISTORY = 25

let runs: RunRecord[] = load()
const listeners = new Set<() => void>()

// v2 -> v3: hypotheses gained `id`/`evidence_ids`/`contradicting_ids`. Old
// records predate all three — backfill so nothing crashes on render; the
// v2 key is left in place (no delete) as a rollback safety net.
function migrateHypothesis(h: Record<string, unknown>, index: number): Record<string, unknown> {
  return {
    id: h.id ?? `h${index + 1}`,
    evidence_ids: h.evidence_ids ?? [],
    contradicting_ids: h.contradicting_ids ?? [],
    ...h,
  }
}

function migrateRun(run: RunRecord): RunRecord {
  if (!run.hypotheses?.length) return run
  return { ...run, hypotheses: run.hypotheses.map((h, i) => migrateHypothesis(h as unknown as Record<string, unknown>, i) as never) }
}

function load(): RunRecord[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (raw) return JSON.parse(raw) as RunRecord[]

    const prevRaw = localStorage.getItem(PREV_STORAGE_KEY)
    if (!prevRaw) return []
    const migrated = (JSON.parse(prevRaw) as RunRecord[]).map(migrateRun)
    localStorage.setItem(STORAGE_KEY, JSON.stringify(migrated))
    return migrated
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
    updated.status = event.cancelled ? "cancelled" : event.partial ? "partial" : "done"
    updated.cost = event.cost
    updated.evidence = event.evidence
    updated.hypotheses = event.hypotheses
  } else if (event.type === "hypotheses") {
    // Live-updates the run's hypotheses as they form/re-rank at plan and
    // revise stages; the `done` branch above overwrites this again with
    // the final stage's list, which is emitted right before `done` anyway.
    updated.hypotheses = event.hypotheses
  } else if (event.type === "error") {
    // An "error" event means the run is failing, but a `done` event still
    // follows it in this codebase's loop (it always finalizes) — don't
    // downgrade status here, `done` is authoritative for the final state.
  }
  runs = [...runs.slice(0, idx), updated, ...runs.slice(idx + 1)]
  save()
  notify()
}

export function appendEvaluation(runId: string, evaluation: EvaluationResult) {
  const idx = runs.findIndex((r) => r.id === runId)
  if (idx === -1) return
  const run = runs[idx]
  const updated: RunRecord = { ...run, evaluations: [...(run.evaluations ?? []), evaluation] }
  runs = [...runs.slice(0, idx), updated, ...runs.slice(idx + 1)]
  save()
  notify()
}

export function deleteRun(runId: string) {
  const idx = runs.findIndex((r) => r.id === runId)
  if (idx === -1) return
  runs = [...runs.slice(0, idx), ...runs.slice(idx + 1)]
  save()
  notify()
}

export function markCancelling(runId: string) {
  const idx = runs.findIndex((r) => r.id === runId)
  if (idx === -1) return
  const run = runs[idx]
  if (run.status !== "running") return
  const updated: RunRecord = { ...run, status: "cancelling" }
  runs = [...runs.slice(0, idx), updated, ...runs.slice(idx + 1)]
  save()
  notify()
}

export function markErrored(runId: string) {
  const idx = runs.findIndex((r) => r.id === runId)
  if (idx === -1) return
  const run = runs[idx]
  if (run.status !== "running" && run.status !== "cancelling") return
  const updated: RunRecord = { ...run, status: "error" }
  runs = [...runs.slice(0, idx), updated, ...runs.slice(idx + 1)]
  save()
  notify()
}
