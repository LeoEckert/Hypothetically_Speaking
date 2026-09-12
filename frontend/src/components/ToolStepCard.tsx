import { Badge } from "@/components/ui/badge"
import { Card, CardContent, CardHeader } from "@/components/ui/card"
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible"
import { humanizeError } from "@/lib/humanizeError"
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
}

const LIVE_BADGE = "border-green-300 bg-green-50 text-green-700 dark:border-green-800 dark:bg-green-950/40 dark:text-green-300"
const MOCK_BADGE = "border-amber-300 bg-amber-50 text-amber-700 dark:border-amber-800 dark:bg-amber-950/40 dark:text-amber-300"

export function ToolStepCard({ step }: { step: StepData }) {
  return (
    <Card className="mb-2 py-3 gap-2 shadow-sm">
      <CardHeader className="px-4 gap-1">
        <div className="flex items-center gap-2 text-sm">
          <span className="font-semibold">{toolLabel(step.tool)}</span>
          <span className="text-xs text-muted-foreground">step {step.step}</span>
          {step.result && (
            <Badge variant="outline" className={step.result.mock ? MOCK_BADGE : LIVE_BADGE}>
              {step.result.mock ? "mock" : "live"}
            </Badge>
          )}
        </div>
      </CardHeader>
      <CardContent className="px-4 text-sm space-y-2">
        <Collapsible>
          <CollapsibleTrigger className="text-xs text-muted-foreground font-mono cursor-pointer hover:underline">
            args: {JSON.stringify(step.args).slice(0, 80)}
            {JSON.stringify(step.args).length > 80 ? "…" : ""}
          </CollapsibleTrigger>
          <CollapsibleContent className="font-mono text-xs text-muted-foreground whitespace-pre-wrap break-all mt-1">
            {JSON.stringify(step.args, null, 2)}
          </CollapsibleContent>
        </Collapsible>

        {step.result ? (
          <>
            <p className="leading-relaxed">{step.result.summary.slice(0, 400)}</p>
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
          <p className="text-muted-foreground italic text-xs">waiting for result…</p>
        )}

        {step.usage && (
          <p className="text-xs text-muted-foreground">
            Nebius usage: {step.usage.prompt_tokens} prompt / {step.usage.completion_tokens} completion tokens
          </p>
        )}
      </CardContent>
    </Card>
  )
}
