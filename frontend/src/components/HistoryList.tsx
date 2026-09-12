import { Trash2Icon } from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { ScrollArea } from "@/components/ui/scroll-area"
import type { RunRecord, RunStatus } from "@/types"

function truncate(s: string, n: number): string {
  return s.length > n ? s.slice(0, n - 1) + "…" : s
}

const STATUS_STYLES: Record<RunStatus, string> = {
  running: "border-transparent bg-primary text-primary-foreground animate-pulse",
  cancelling: "border-transparent bg-primary/60 text-primary-foreground animate-pulse",
  done: "border-green-300 bg-green-50 text-green-700 dark:border-green-800 dark:bg-green-950/40 dark:text-green-300",
  partial: "border-amber-300 bg-amber-50 text-amber-700 dark:border-amber-800 dark:bg-amber-950/40 dark:text-amber-300",
  cancelled: "border-muted-foreground/30 bg-muted text-muted-foreground",
  error: "border-transparent bg-destructive text-white",
}

export function HistoryList({
  runs,
  viewedRunId,
  onSelect,
  onDelete,
}: {
  runs: RunRecord[]
  viewedRunId: string | null
  onSelect: (id: string) => void
  onDelete: (id: string) => void
}) {
  const sorted = [...runs].sort((a, b) => b.createdAt - a.createdAt)
  const byId = new Map(runs.map((r) => [r.id, r]))

  if (sorted.length === 0) {
    return <p className="text-sm text-muted-foreground italic">No requests yet — run one to start building history.</p>
  }

  return (
    <ScrollArea className="h-full pr-2">
      <div className="space-y-2">
        {sorted.map((run) => {
          const status: RunStatus = run.status
          const parent = run.parentId ? byId.get(run.parentId) : undefined
          return (
            <div
              key={run.id}
              className={`group relative border rounded-lg transition-colors ${
                run.id === viewedRunId ? "border-primary bg-accent/50 shadow-sm" : "hover:bg-accent/70 hover:border-accent-foreground/20"
              }`}
            >
              <button onClick={() => onSelect(run.id)} className="w-full text-left p-2.5 pr-9 text-sm">
                <div className="line-clamp-2 font-medium">{run.question}</div>
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
              <button
                type="button"
                onClick={(e) => {
                  e.stopPropagation()
                  if (window.confirm("Delete this run from history? This can't be undone.")) {
                    onDelete(run.id)
                  }
                }}
                title="Delete from history"
                className="absolute top-2 right-2 rounded-md p-1 text-muted-foreground opacity-40 transition-opacity hover:bg-destructive/10 hover:text-destructive hover:opacity-100 group-hover:opacity-100 focus-visible:opacity-100"
              >
                <Trash2Icon className="size-3.5" />
              </button>
            </div>
          )
        })}
      </div>
    </ScrollArea>
  )
}
