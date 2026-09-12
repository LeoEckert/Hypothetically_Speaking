import { Badge } from "@/components/ui/badge"
import { Card, CardContent, CardHeader } from "@/components/ui/card"
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible"
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

export function ToolStepCard({ step }: { step: StepData }) {
  return (
    <Card className="mb-2 py-3 gap-2">
      <CardHeader className="px-4 gap-1">
        <div className="flex items-center gap-2 text-sm">
          <span className="font-semibold">{toolLabel(step.tool)}</span>
          <span className="text-xs text-muted-foreground">step {step.step}</span>
          {step.result && (
            <Badge variant={step.result.mock ? "destructive" : "secondary"}>
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
            <p>{step.result.summary.slice(0, 400)}</p>
            {step.result.error && <p className="text-destructive text-xs">{step.result.error}</p>}
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
