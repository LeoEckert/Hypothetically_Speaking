import { ChevronDownIcon } from "lucide-react"
import { useState } from "react"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible"
import { UsageBar } from "@/components/UsageBar"
import { toolLabel } from "@/lib/toolLabels"
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
  const [detailsOpen, setDetailsOpen] = useState(false)

  const costRows = [
    {
      key: "anthropic",
      label: "Anthropic",
      usd: cost.anthropic.usd,
      rateConfigured: cost.anthropic.rate_configured,
      tooltip: `${cost.anthropic.calls ?? 0} calls · ${cost.anthropic.input_tokens}/${cost.anthropic.output_tokens} in/out tokens`,
    },
    {
      key: "nebius",
      label: "Nebius",
      usd: cost.nebius.usd,
      rateConfigured: cost.nebius.rate_configured,
      tooltip: `${cost.nebius.calls ?? 0} calls · ${cost.nebius.prompt_tokens}/${cost.nebius.completion_tokens} in/out tokens`,
    },
    {
      key: "amass",
      label: "Amass",
      usd: cost.amass.usd,
      rateConfigured: cost.amass.rate_configured,
      tooltip:
        cost.amass.credits_used !== null
          ? `${cost.amass.live_calls} live calls · ${cost.amass.credits_used} credits used`
          : `${cost.amass.live_calls} live calls`,
    },
    {
      key: "tavily",
      label: "Tavily",
      usd: cost.tavily.usd,
      rateConfigured: cost.tavily.rate_configured,
      tooltip: `${cost.tavily.live_calls} live calls`,
    },
  ]
  const maxCost = Math.max(
    0.0001,
    ...costRows.filter((r) => r.rateConfigured && r.usd !== null).map((r) => r.usd as number)
  )

  const activityRows = [
    { key: "anthropic", label: "Anthropic", calls: cost.anthropic.calls ?? 0 },
    { key: "nebius", label: toolLabel("extract_genes"), calls: cost.nebius.calls ?? 0 },
    { key: "amass", label: "Amass", calls: cost.amass.calls ?? 0 },
    { key: "tavily", label: "Tavily", calls: cost.tavily.calls ?? 0 },
    ...Object.entries(cost.free_tools).map(([name, v]) => ({ key: name, label: toolLabel(name), calls: v.calls })),
  ].filter((r) => r.calls > 0)
  const maxCalls = Math.max(1, ...activityRows.map((r) => r.calls))

  return (
    <Card className="mt-4">
      <CardHeader>
        <CardTitle className="flex flex-wrap items-center gap-2 text-sm">
          Cost &amp; Usage
          <span className="font-mono font-normal text-muted-foreground">{usd(cost.total_usd)}</span>
          {cost.total_usd_is_partial && (
            <Badge variant="outline" className="text-xs">
              partial estimate
            </Badge>
          )}
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <div>
          <p className="mb-1 text-xs font-semibold text-muted-foreground">Cost by provider</p>
          {costRows.map((r) => (
            <UsageBar
              key={r.key}
              label={r.label}
              fraction={r.rateConfigured && r.usd !== null ? r.usd / maxCost : 0}
              endLabel={r.rateConfigured ? usd(r.usd) : "not priced"}
              tooltip={r.tooltip}
              placeholder={!r.rateConfigured}
            />
          ))}
          {cost.unpriced_components.length > 0 && (
            <p className="mt-1 text-xs text-muted-foreground">
              Not priced: {cost.unpriced_components.join(", ")} — set their price env vars to include them.
            </p>
          )}
        </div>

        {activityRows.length > 0 && (
          <div>
            <p className="mb-1 text-xs font-semibold text-muted-foreground">Tool activity</p>
            {activityRows.map((r) => (
              <UsageBar
                key={r.key}
                label={r.label}
                fraction={r.calls / maxCalls}
                endLabel={`${r.calls} call${r.calls === 1 ? "" : "s"}`}
              />
            ))}
          </div>
        )}

        <Collapsible open={detailsOpen} onOpenChange={setDetailsOpen}>
          <CollapsibleTrigger className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground">
            <ChevronDownIcon className={`size-3 transition-transform ${detailsOpen ? "rotate-180" : ""}`} />
            {detailsOpen ? "Hide details" : "Show details"}
          </CollapsibleTrigger>
          <CollapsibleContent className="space-y-1 pt-2">
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
            <p className="pt-1 text-xs text-muted-foreground">{cost.amass.note}</p>
            <div className="mt-2 border-t pt-2">
              <Row label="Total (priced components only)" right={usd(cost.total_usd)} />
            </div>
          </CollapsibleContent>
        </Collapsible>
      </CardContent>
    </Card>
  )
}
