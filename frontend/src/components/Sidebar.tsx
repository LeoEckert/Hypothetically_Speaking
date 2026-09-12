import { Button } from "@/components/ui/button"
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
      <Button className="w-full font-semibold" onClick={onNewRequest}>
        + New Request
      </Button>

      <div className="border rounded-lg p-3">
        <p className="text-sm font-semibold mb-2">History</p>
        <HistoryList runs={runs} liveRunId={liveRunId} viewedRunId={viewedRunId} onSelect={onSelectHistory} />
      </div>

      <HowItWorksPanel />
      <ToolsPanel isRunLive={liveRunId !== null} />
    </aside>
  )
}
