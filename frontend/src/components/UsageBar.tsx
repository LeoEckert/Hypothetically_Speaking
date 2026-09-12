import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"

export function UsageBar({
  label,
  fraction,
  endLabel,
  tooltip,
  placeholder,
}: {
  label: string
  /** 0-1, ignored when `placeholder` is true */
  fraction: number
  endLabel: string
  tooltip?: string
  placeholder?: boolean
}) {
  const row = (
    <div className="flex items-center gap-2 py-1 sm:gap-3">
      <span className="w-16 shrink-0 truncate text-xs text-muted-foreground sm:w-28">{label}</span>
      <div className="relative h-2.5 min-w-0 flex-1 overflow-hidden rounded-full bg-muted">
        {placeholder ? (
          <div
            className="absolute inset-0 rounded-full opacity-60"
            style={{
              backgroundImage:
                "repeating-linear-gradient(45deg, var(--color-border), var(--color-border) 3px, transparent 3px, transparent 7px)",
            }}
          />
        ) : (
          <div
            className="absolute inset-y-0 left-0 rounded-full bg-foreground transition-[width]"
            style={{ width: `${Math.max(fraction, fraction > 0 ? 0.03 : 0) * 100}%` }}
          />
        )}
      </div>
      <span className="w-16 shrink-0 text-right font-mono text-xs sm:w-20">{endLabel}</span>
    </div>
  )

  if (!tooltip) return row

  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <div>{row}</div>
      </TooltipTrigger>
      <TooltipContent>{tooltip}</TooltipContent>
    </Tooltip>
  )
}
