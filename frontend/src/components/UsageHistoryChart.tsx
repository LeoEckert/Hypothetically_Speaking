import { useMemo, useState } from "react"
import type { AdminUsageDayPoint } from "@/types"

// Series colors are CSS custom properties (--series-anthropic/nebius/tavily/
// credits) defined in index.css from the project's validated categorical
// palette (dataviz skill, references/palette.md, slots 1-4) — fixed order,
// never cycled, with light/dark pairs swapped via the app's existing `.dark`
// class convention.

const PROVIDERS = ["anthropic", "nebius", "tavily"] as const
type Provider = (typeof PROVIDERS)[number]

const LABEL: Record<Provider, string> = { anthropic: "Anthropic", nebius: "Nebius", tavily: "Tavily" }
const UNCONFIGURED_HINT: Record<Provider, string> = {
  anthropic: "set ANTHROPIC pricing in costs.py",
  nebius: "set NEBIUS_PRICE_PER_1M_INPUT / _OUTPUT",
  tavily: "set TAVILY_USD_PER_CALL",
}

function usd(value: number): string {
  return `$${value.toFixed(value < 1 ? 4 : 2)}`
}

// x/y helpers work in a fixed viewBox, independent of the rendered pixel
// size, so stroke widths never distort (no preserveAspectRatio="none").
const W = 600
const H = 150
const PAD_L = 8
const PAD_R = 8
const PAD_TOP = 10
const PAD_BOTTOM = 4

function formatBucketLabel(date: string, granularity: "day" | "hour"): string {
  if (granularity === "hour") {
    const hourPart = date.split("T")[1]
    return hourPart ?? date
  }
  return date
}

export function UsageHistoryChart({ series, granularity }: { series: AdminUsageDayPoint[]; granularity: "day" | "hour" }) {
  const [hover, setHover] = useState<number | null>(null)

  const n = series.length
  const xFor = (i: number) => (n <= 1 ? (W - PAD_L - PAD_R) / 2 + PAD_L : PAD_L + (i / (n - 1)) * (W - PAD_L - PAD_R))

  const maxUsd = useMemo(() => {
    let max = 0
    for (const point of series) {
      for (const p of PROVIDERS) {
        const v = point[p]
        if (v.rate_configured && v.usd !== null) max = Math.max(max, v.usd)
      }
    }
    return max <= 0 ? 1 : max
  }, [series])

  const maxCredits = useMemo(() => {
    const max = Math.max(0, ...series.map((p) => p.amass.credits_used))
    return max <= 0 ? 1 : max
  }, [series])

  const yFor = (usdValue: number) => H - PAD_BOTTOM - (usdValue / maxUsd) * (H - PAD_TOP - PAD_BOTTOM)

  // Build one <path> per contiguous run of priced points — an unpriced day
  // (rate_configured: false) breaks the line into a gap rather than being
  // plotted as a misleading 0.
  const pathsFor = (provider: Provider) => {
    const segments: string[] = []
    let current: string[] = []
    series.forEach((point, i) => {
      const v = point[provider]
      if (v.rate_configured && v.usd !== null) {
        current.push(`${i === 0 || current.length === 0 ? "M" : "L"} ${xFor(i)} ${yFor(v.usd)}`)
      } else if (current.length) {
        segments.push(current.join(" "))
        current = []
      }
    })
    if (current.length) segments.push(current.join(" "))
    return segments
  }

  const anyUnconfigured = (provider: Provider) => series.some((p) => !p[provider].rate_configured)
  const bucketWord = granularity === "hour" ? "hour" : "day"
  const anthropicIsLive = series.some((p) => p.anthropic.source === "anthropic_usage_api")

  const hovered = hover !== null ? series[hover] : null

  return (
    <div>
      <svg viewBox={`0 0 ${W} ${H}`} width="100%" height={H} role="img" aria-label={`Cost per ${bucketWord} by provider`}>
        {/* gridlines */}
        {[0, 0.5, 1].map((f) => (
          <line
            key={f}
            x1={PAD_L}
            x2={W - PAD_R}
            y1={PAD_TOP + f * (H - PAD_TOP - PAD_BOTTOM)}
            y2={PAD_TOP + f * (H - PAD_TOP - PAD_BOTTOM)}
            className="stroke-border"
            strokeWidth={1}
          />
        ))}
        {PROVIDERS.map((provider) => (
          <g key={provider}>
            {pathsFor(provider).map((d, i) => (
              <path
                key={i}
                d={d}
                fill="none"
                stroke={`var(--series-${provider})`}
                strokeWidth={2}
                strokeLinecap="round"
              />
            ))}
          </g>
        ))}
        {/* hover crosshair + hit targets */}
        {series.map((point, i) => (
          <rect
            key={point.date}
            x={xFor(i) - (W - PAD_L - PAD_R) / Math.max(n, 1) / 2}
            y={0}
            width={(W - PAD_L - PAD_R) / Math.max(n, 1)}
            height={H}
            fill="transparent"
            onMouseEnter={() => setHover(i)}
            onMouseLeave={() => setHover((h) => (h === i ? null : h))}
          />
        ))}
        {hover !== null && (
          <line x1={xFor(hover)} x2={xFor(hover)} y1={PAD_TOP} y2={H - PAD_BOTTOM} className="stroke-muted-foreground" strokeWidth={1} strokeDasharray="2 2" />
        )}
      </svg>

      <div className="flex flex-wrap items-center gap-3 pt-1 text-xs">
        {PROVIDERS.map((provider) => (
          <span key={provider} className="flex items-center gap-1.5">
            <span className="inline-block h-2 w-2 rounded-full" style={{ background: `var(--series-${provider})` }} />
            <span className="text-muted-foreground">{LABEL[provider]}</span>
          </span>
        ))}
      </div>

      <p className="pt-1 text-xs text-muted-foreground" aria-live="polite">
        {hovered
          ? `${formatBucketLabel(hovered.date, granularity)} · ${PROVIDERS.map((p) => (hovered[p].rate_configured ? `${LABEL[p]} ${usd(hovered[p].usd ?? 0)}` : `${LABEL[p]} not configured`)).join(" · ")} · ${hovered.runs} run${hovered.runs === 1 ? "" : "s"}`
          : `Hover the chart for a ${bucketWord}'s breakdown.`}
      </p>

      {anthropicIsLive && (
        <p className="text-xs text-muted-foreground">Anthropic: live from Anthropic's Usage API.</p>
      )}

      {PROVIDERS.filter(anyUnconfigured).map((provider) => (
        <p key={provider} className="text-xs text-muted-foreground">
          {LABEL[provider]}: rate not configured for some {bucketWord}s — {UNCONFIGURED_HINT[provider]}.
        </p>
      ))}

      <div className="pt-3">
        <p className="pb-1 text-xs font-medium">Amass credits used</p>
        <svg viewBox={`0 0 ${W} 40`} width="100%" height={40} role="img" aria-label={`Amass credits used per ${bucketWord}`}>
          {series.map((point, i) => {
            const barW = Math.max(1, (W - PAD_L - PAD_R) / n - 2)
            const barH = point.amass.credits_used > 0 ? (point.amass.credits_used / maxCredits) * 32 : 0
            return (
              <rect
                key={point.date}
                x={xFor(i) - barW / 2}
                y={36 - barH}
                width={barW}
                height={barH}
                fill="var(--series-credits)"
                rx={1}
              />
            )
          })}
        </svg>
      </div>
    </div>
  )
}
