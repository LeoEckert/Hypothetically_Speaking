import { Badge } from "@/components/ui/badge"
import { ScrollArea } from "@/components/ui/scroll-area"
import type { RunRecord, RunStatus } from "@/types"

function truncate(s: string, n: number): string {
  return s.length > n ? s.slice(0, n - 1) + "…" : s
}

const STATUS_STYLES: Record<RunStatus, string> = {
  running: "border-transparent bg-primary text-primary-foreground animate-pulse",
  done: "border-green-300 bg-green-50 text-green-700 dark:border-green-800 dark:bg-green-950/40 dark:text-green-300",
  partial: "border-amber-300 bg-amber-50 text-amber-700 dark:border-amber-800 dark:bg-amber-950/40 dark:text-amber-300",
  error: "border-transparent bg-destructive text-white",
}

export function HistoryList({
  runs,
  liveRunId,
  viewedRunId,
  onSelect,
}: {
  runs: RunRecord[]
  liveRunId: string | null
  viewedRunId: string | null
  onSelect: (id: string) => void
}) {
  const sorted = [...runs].sort((a, b) => b.createdAt - a.createdAt)
  const byId = new Map(runs.map((r) => [r.id, r]))

  if (sorted.length === 0) {
    return <p className="text-sm text-muted-foreground italic">No requests yet — run one to start building history.</p>
  }

  return (
    <ScrollArea className="h-[45vh] pr-2">
      <div className="space-y-2">
        {sorted.map((run) => {
          const status: RunStatus = run.id === liveRunId ? "running" : run.status
          const parent = run.parentId ? byId.get(run.parentId) : undefined
          return (
            <button
              key={run.id}
              onClick={() => onSelect(run.id)}
              className={`w-full text-left border rounded-lg p-2.5 text-sm hover:bg-accent/70 hover:border-accent-foreground/20 transition-colors ${
                run.id === viewedRunId ? "border-primary bg-accent/50 shadow-sm" : ""
              }`}
            >
              <div className="truncate font-medium">{run.question}</div>
              <div className="flex items-center gap-2 mt-1.5 text-xs text-muted-foreground">
                <Badge variant="outline" className={`text-[10px] ${STATUS_STYLES[status]}`}>
                  {status}
                </Badge>
                <span>{new Date(run.createdAt).toLocaleString()}</span>
                {run.cost && <span className="font-mono">${run.cost.total_usd.toFixed(3)}</span>}
              </div>
              {parent && (
                <div className="text-xs text-muted-foreground italic mt-1 truncate">
                  ↳ based on: {truncate(parent.question, 50)}
                </div>
              )}
            </button>
          )
        })}
      </div>
    </ScrollArea>
  )
}
