import { ErrorBanner } from "@/components/ErrorBanner"
import { ReasoningBlock } from "@/components/ReasoningBlock"
import { Separator } from "@/components/ui/separator"
import { phaseLabel } from "@/lib/toolLabels"
import type { SseEvent } from "@/types"
import { ToolStepCard, type StepData } from "@/components/ToolStepCard"

type TimelineItem =
  | { kind: "phase"; phase: string; key: string }
  | { kind: "reasoning"; text: string; key: string }
  | { kind: "step"; step: StepData; key: string }
  | { kind: "error"; error: string; key: string }

function buildTimeline(events: SseEvent[]): TimelineItem[] {
  const items: TimelineItem[] = []
  const stepIndexByNumber = new Map<number, number>()

  events.forEach((event, i) => {
    switch (event.type) {
      case "phase":
        items.push({ kind: "phase", phase: event.phase, key: `phase-${i}` })
        break
      case "assistant_text":
        items.push({ kind: "reasoning", text: event.text, key: `reasoning-${i}` })
        break
      case "tool_call": {
        const step: StepData = { step: event.step, tool: event.tool, args: event.args }
        const itemIndex = items.length
        items.push({ kind: "step", step, key: `step-${event.step}` })
        stepIndexByNumber.set(event.step, itemIndex)
        break
      }
      case "tool_result": {
        const itemIndex = stepIndexByNumber.get(event.step)
        if (itemIndex !== undefined) {
          const item = items[itemIndex]
          if (item.kind === "step") {
            item.step = {
              ...item.step,
              result: { mock: event.mock, error: event.error, summary: event.summary },
              usage: event.usage,
            }
          }
        }
        break
      }
      case "error":
        items.push({ kind: "error", error: event.error, key: `error-${i}` })
        break
      default:
        break
    }
  })

  return items
}

export function TraceTimeline({ events }: { events: SseEvent[] }) {
  const items = buildTimeline(events)

  if (items.length === 0) {
    return null
  }

  return (
    <div className="mt-4">
      {items.map((item) => {
        switch (item.kind) {
          case "phase":
            return (
              <div key={item.key} className="flex items-center gap-3 my-4 text-primary">
                <Separator className="flex-1" />
                <span className="text-xs font-bold uppercase tracking-wide">{phaseLabel(item.phase)}</span>
                <Separator className="flex-1" />
              </div>
            )
          case "reasoning":
            return <ReasoningBlock key={item.key} text={item.text} />
          case "step":
            return <ToolStepCard key={item.key} step={item.step} />
          case "error":
            return <ErrorBanner key={item.key} error={item.error} />
          default:
            return null
        }
      })}
    </div>
  )
}
