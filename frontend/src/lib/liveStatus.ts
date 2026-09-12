import { phaseLabel, toolLabel } from "@/lib/toolLabels"
import type { RunRecord, SseEvent } from "@/types"

/** The fixed order of a run. The stepper in the live bar is drawn from this. */
export const RUN_PHASES = ["grounding", "plan", "plan_and_gather", "revise", "report"] as const

export type StepState = "done" | "current" | "upcoming"

export interface LiveProgress {
  phase: string | null
  steps: Array<{ key: string; label: string; state: StepState }>
  headline: string
  detail: string
  remaining: string[]
}

export function deriveLiveStatus(events: SseEvent[]): string {
  let phase: string | null = null
  const pending = new Map<number, string>() // step -> tool name, cleared once its result arrives

  for (const e of events) {
    if (e.type === "phase") phase = e.phase
    else if (e.type === "tool_call") pending.set(e.step, e.tool)
    else if (e.type === "tool_result") pending.delete(e.step)
  }

  const label = phase ? phaseLabel(phase) : "Starting"
  if (pending.size > 0) {
    const tools = [...new Set(pending.values())].map(toolLabel)
    return `${label} — calling ${tools.join(", ")}…`
  }
  if (phase === "grounding") return `${label} — decomposing and checking links…`
  if (phase === "plan") return `${label} — proposing hypotheses…`
  if (phase === "revise") return `${label} — weighing the evidence…`
  if (phase === "report") return `${label} — writing the final report…`
  return `${label}…`
}

function compact(n: number): string {
  return n >= 1000 ? `${(n / 1000).toFixed(1)}k` : String(n)
}

/**
 * Everything the live bar needs: which step we are on, which are done and
 * which remain, one headline, and a second line that changes while a phase
 * is running — so the user always sees movement, including during the two
 * long single-call phases (REVISE, REPORT) that used to sit silent.
 */
export function deriveLiveProgress(run: RunRecord): LiveProgress {
  const phase = run.phase ?? null
  const index = phase ? RUN_PHASES.indexOf(phase as (typeof RUN_PHASES)[number]) : -1
  const finished = run.status !== "running" && run.status !== "cancelling"
  const steps = RUN_PHASES.map((key, i) => ({
    key,
    label: phaseLabel(key),
    state: (finished || i < index ? "done" : i === index ? "current" : "upcoming") as StepState,
  }))
  const remaining = steps.filter((s) => s.state === "upcoming").map((s) => s.label)

  const pending = new Map<number, string>()
  let toolCalls = 0
  for (const e of run.events) {
    if (e.type === "tool_call") {
      pending.set(e.step, e.tool)
      toolCalls += 1
    } else if (e.type === "tool_result") pending.delete(e.step)
  }
  const calling = [...new Set(pending.values())].map(toolLabel)
  const p = run.progress

  let detail = ""
  switch (phase) {
    case "grounding": {
      const stepsSeen = run.groundingSteps ?? []
      const l1 = stepsSeen.find((s) => s.stage === "L1")
      const verdicts = stepsSeen.filter((s) => s.stage === "L2").length
      const l4 = stepsSeen.find((s) => s.stage === "L4")
      if (l4) detail = `${l4.kept ?? 0} hypothesis candidate(s) ready — handing over to the planner`
      else if (l1) detail = `Verifying ${l1.links?.length ?? 0} links against the literature — ${verdicts}/${l1.links?.length ?? 0} verdicts in`
      else if (stepsSeen.length) detail = "Expanding the causal chain around the question's claims"
      else detail = "Splitting the question into the claims it asserts"
      if (calling.length) detail += ` · calling ${calling.join(", ")}`
      break
    }
    case "plan":
      detail = p?.candidates
        ? `Adopting ${p.candidates} grounded candidate(s) as the hypotheses to test${p.chars ? ` · ${compact(p.chars)} chars` : ""}`
        : "Proposing hypotheses from the grounded premises"
      break
    case "plan_and_gather":
      detail = calling.length
        ? `Tool call ${toolCalls} · calling ${calling.join(", ")}`
        : `${toolCalls} tool call(s) so far · deciding which evidence to fetch next`
      break
    case "revise":
      detail = `Weighing ${p?.hypotheses ?? run.hypotheses?.length ?? 0} hypotheses against ${p?.evidence ?? Object.keys(run.evidence ?? {}).length} evidence items` +
        (p?.chars ? ` · ${compact(p.chars)} chars of reasoning written` : " · reading the evidence")
      break
    case "report": {
      const total = p?.sections_total ?? 7
      const done = p?.sections_done ?? 0
      detail = p?.section
        ? `Writing section ${Math.min(done, total)}/${total} — ${p.section}${p.chars ? ` · ${compact(p.chars)} chars` : ""}`
        : `Writing the report — ${total} sections, citing ${p?.evidence ?? Object.keys(run.evidence ?? {}).length} evidence items`
      break
    }
    default:
      detail = "Connecting…"
  }

  return {
    phase,
    steps,
    headline: finished ? phaseLabel("report") + " — done" : deriveLiveStatus(run.events),
    detail,
    remaining,
  }
}
