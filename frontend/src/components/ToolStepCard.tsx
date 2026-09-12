import { ChevronRightIcon } from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible"
import { WaitingDots } from "@/components/WaitingDots"
import { useElapsedSeconds } from "@/hooks/useElapsedSeconds"
import { humanizeError } from "@/lib/humanizeError"
import { parseSummaryLines } from "@/lib/parseSummary"
import { toolLabel } from "@/lib/toolLabels"

export interface StepData {
  step: number
  tool: string
  args: Record<string, unknown>
  result?: {
    mock: boolean
    error: string | null
    summary: string
  }
  usage?: { prompt_tokens: number; completion_tokens: number } | null
  /** ms timestamp of when this step was first seen, for the in-flight
   * elapsed-time ticker below — set once in the runs store (runsStore.ts). */
  startedAt?: number
}

const LIVE_BADGE = "border-green-300 bg-green-50 text-green-700 dark:border-green-800 dark:bg-green-950/40 dark:text-green-300"
const MOCK_BADGE = "border-amber-300 bg-amber-50 text-amber-700 dark:border-amber-800 dark:bg-amber-950/40 dark:text-amber-300"
const COMPUTE_BADGE = "border-violet-300 bg-violet-50 text-violet-700 dark:border-violet-800 dark:bg-violet-950/40 dark:text-violet-300"

// The one "real computed result" step (CLAUDE.md) — worth a visibly
// different wait treatment from an ordinary evidence-gathering search.
const COMPUTE_TOOLS = new Set(["extract_genes", "run_enrichment"])

function ResultBody({ summary }: { summary: string }) {
  const lines = parseSummaryLines(summary)
  if (!lines) return <p className="leading-relaxed">{summary.slice(0, 500)}</p>
  return (
    <ul className="space-y-1">
      {lines.slice(0, 10).map((line, i) => (
        <li key={i} className="flex gap-2 leading-snug">
          <code className="shrink-0 text-[10px] font-mono bg-muted px-1 py-0.5 rounded h-fit mt-0.5">{line.id}</code>
          <span>{line.text}</span>
        </li>
      ))}
      {lines.length > 10 && <li className="text-xs text-muted-foreground">+{lines.length - 10} more</li>}
    </ul>
  )
}

export function ToolStepCard({ step }: { step: StepData }) {
  const isCompute = COMPUTE_TOOLS.has(step.tool)
  const running = !step.result
  const elapsed = useElapsedSeconds(step.startedAt, running)
  const preview = step.result
    ? (parseSummaryLines(step.result.summary)?.[0]?.text ?? step.result.summary).slice(0, 90)
    : null

  return (
    <Collapsible className="mb-1.5 rounded-lg border bg-card shadow-sm">
      <CollapsibleTrigger className="group flex w-full items-center gap-2 px-3 py-2 text-left text-sm cursor-pointer">
        <ChevronRightIcon className="size-3.5 shrink-0 text-muted-foreground transition-transform group-data-[state=open]:rotate-90" />
        <span className="font-semibold shrink-0">{toolLabel(step.tool)}</span>
        <span className="text-xs text-muted-foreground shrink-0">#{step.step}</span>
        {step.result ? (
          <Badge variant="outline" className={`shrink-0 text-[10px] ${step.result.mock ? MOCK_BADGE : LIVE_BADGE}`}>
            {step.result.mock ? "mock" : "live"}
          </Badge>
        ) : (
          <Badge variant="outline" className={`shrink-0 gap-1 text-[10px] ${isCompute ? COMPUTE_BADGE : ""}`}>
            <WaitingDots />
            {isCompute ? "running analysis" : "running"}
            {elapsed > 0 && ` · ${elapsed}s`}
          </Badge>
        )}
        {preview && <span className="truncate text-muted-foreground text-xs">{preview}</span>}
      </CollapsibleTrigger>
      <CollapsibleContent className="px-3 pb-3 text-sm space-y-2">
        <div className="font-mono text-xs text-muted-foreground bg-muted/50 rounded p-1.5 whitespace-pre-wrap break-all">
          {JSON.stringify(step.args)}
        </div>

        {step.result ? (
          <>
            <ResultBody summary={step.result.summary} />
            {step.result.error && (
              <Collapsible>
                <CollapsibleTrigger className="text-xs text-amber-700 dark:text-amber-400 cursor-pointer hover:underline">
                  ⚠ {humanizeError(step.result.error)} — details
                </CollapsibleTrigger>
                <CollapsibleContent className="font-mono text-xs text-muted-foreground whitespace-pre-wrap break-all mt-1">
                  {step.result.error}
                </CollapsibleContent>
              </Collapsible>
            )}
          </>
        ) : (
          <p className="flex items-center gap-1.5 text-muted-foreground italic text-xs">
            <WaitingDots />
            {isCompute ? "running the computational analysis…" : "waiting for result…"}
          </p>
        )}

        {step.usage && (
          <p className="text-xs text-muted-foreground">
            Nebius usage: {step.usage.prompt_tokens} prompt / {step.usage.completion_tokens} completion tokens
          </p>
        )}
      </CollapsibleContent>
    </Collapsible>
  )
}
