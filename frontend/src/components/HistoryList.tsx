import { Badge } from "@/components/ui/badge"
import { ScrollArea } from "@/components/ui/scroll-area"
import type { RunRecord, RunStatus } from "@/types"

function truncate(s: string, n: number): string {
  return s.length > n ? s.slice(0, n - 1) + "…" : s
}

function statusBadgeVariant(status: RunStatus): "default" | "secondary" | "destructive" | "outline" {
  switch (status) {
    case "running":
      return "default"
    case "done":
      return "secondary"
    case "partial":
      return "outline"
    case "error":
      return "destructive"
  }
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
              className={`w-full text-left border rounded-lg p-2 text-sm hover:bg-accent transition-colors ${
                run.id === viewedRunId ? "border-primary bg-accent/50" : ""
              }`}
            >
              <div className="truncate">{run.question}</div>
              <div className="flex items-center gap-2 mt-1 text-xs text-muted-foreground">
                <Badge variant={statusBadgeVariant(status)} className="text-[10px]">
                  {status}
                </Badge>
                <span>{new Date(run.createdAt).toLocaleString()}</span>
                {run.cost && <span>· ${run.cost.total_usd.toFixed(3)}</span>}
              </div>
              {parent && (
                <div className="text-xs text-muted-foreground italic mt-1">
                  based on: {truncate(parent.question, 60)}
                </div>
              )}
            </button>
          )
        })}
      </div>
    </ScrollArea>
  )
}
