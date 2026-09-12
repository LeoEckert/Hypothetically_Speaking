import { SettingsIcon } from "lucide-react"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog"
import { HistoryList } from "@/components/HistoryList"
import { HowItWorksPanel } from "@/components/HowItWorksPanel"
import { ToolsPanel } from "@/components/ToolsPanel"
import type { RunRecord } from "@/types"

export function Sidebar({
  runs,
  liveRunId,
  viewedRunId,
  onNewRequest,
  onSelectHistory,
}: {
  runs: RunRecord[]
  liveRunId: string | null
  viewedRunId: string | null
  onNewRequest: () => void
  onSelectHistory: (id: string) => void
}) {
  return (
    <aside className="w-full md:w-[320px] shrink-0 space-y-4">
      <div className="flex gap-2">
        <Button className="flex-1 font-semibold" size="lg" onClick={onNewRequest}>
          + New Request
        </Button>
        <Dialog>
          <DialogTrigger asChild>
            <Button variant="outline" size="icon-lg" title="Settings — available tools">
              <SettingsIcon className="size-4" />
            </Button>
          </DialogTrigger>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>Available tools</DialogTitle>
              <DialogDescription>
                Enable or disable which tools the agent can call. Takes effect on the next run.
              </DialogDescription>
            </DialogHeader>
            <ToolsPanel isRunLive={liveRunId !== null} />
          </DialogContent>
        </Dialog>
      </div>

      <div className="border rounded-lg p-3 bg-card shadow-sm">
        <p className="text-sm font-semibold mb-2">History</p>
        <HistoryList runs={runs} liveRunId={liveRunId} viewedRunId={viewedRunId} onSelect={onSelectHistory} />
      </div>

      <HowItWorksPanel />
    </aside>
  )
}
