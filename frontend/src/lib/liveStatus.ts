import { phaseLabel, toolLabel } from "@/lib/toolLabels"
import type { SseEvent } from "@/types"

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
  if (phase === "plan") return `${label} — proposing hypotheses…`
  if (phase === "revise") return `${label} — weighing the evidence…`
  if (phase === "report") return `${label} — writing the final report…`
  return `${label}…`
}
