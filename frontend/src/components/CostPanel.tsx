import { Badge } from "@/components/ui/badge"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import type { CostSummary } from "@/types"

function usd(value: number | null): string {
  if (value === null) return "—"
  return `$${value.toFixed(4)}`
}

function Row({ label, right, sub }: { label: string; right: React.ReactNode; sub?: string }) {
  return (
    <div className="flex items-center justify-between text-sm py-1">
      <div>
        <span>{label}</span>
        {sub && <span className="block text-xs text-muted-foreground">{sub}</span>}
      </div>
      <span className="font-mono">{right}</span>
    </div>
  )
}

export function CostPanel({ cost }: { cost: CostSummary }) {
  return (
    <Card className="mt-4">
      <CardHeader>
        <CardTitle className="text-sm flex items-center gap-2">
          Cost &amp; Usage
          {cost.total_usd_is_partial && (
            <Badge variant="outline" className="text-xs">
              partial estimate
            </Badge>
          )}
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-1">
        <Row
          label="Anthropic"
          sub={`${cost.anthropic.calls} calls · ${cost.anthropic.input_tokens}/${cost.anthropic.output_tokens} in/out tokens`}
          right={cost.anthropic.rate_configured ? usd(cost.anthropic.usd) : "rate not configured"}
        />
        <Row
          label="Nebius"
          sub={`${cost.nebius.calls} calls · ${cost.nebius.prompt_tokens}/${cost.nebius.completion_tokens} in/out tokens`}
          right={cost.nebius.rate_configured ? usd(cost.nebius.usd) : "rate not configured"}
        />
        <Row
          label="Amass"
          sub={
            cost.amass.credits_used !== null
              ? `${cost.amass.live_calls} live calls · ${cost.amass.credits_used} credits used`
              : `${cost.amass.live_calls} live calls`
          }
          right={cost.amass.rate_configured ? usd(cost.amass.usd) : "rate not configured"}
        />
        <Row
          label="Tavily"
          sub={`${cost.tavily.live_calls} live calls`}
          right={cost.tavily.rate_configured ? usd(cost.tavily.usd) : "rate not configured"}
        />
        <Row
          label="Free/keyless tools"
          sub={Object.entries(cost.free_tools)
            .map(([name, v]) => `${name}: ${v.calls}`)
            .join(" · ")}
          right="$0"
        />
        <div className="border-t mt-2 pt-2">
          <Row label="Total (priced components only)" right={usd(cost.total_usd)} />
        </div>
        {cost.unpriced_components.length > 0 && (
          <p className="text-xs text-muted-foreground">
            Not priced: {cost.unpriced_components.join(", ")} — set their price env vars to include them.
          </p>
        )}
      </CardContent>
    </Card>
  )
}
