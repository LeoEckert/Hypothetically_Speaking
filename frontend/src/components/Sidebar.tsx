import { HelpCircleIcon, PanelLeftCloseIcon, PanelLeftOpenIcon, SettingsIcon } from "lucide-react"
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
  collapsed,
  onToggleCollapsed,
}: {
  runs: RunRecord[]
  liveRunId: string | null
  viewedRunId: string | null
  onNewRequest: () => void
  onSelectHistory: (id: string) => void
  collapsed: boolean
  onToggleCollapsed: () => void
}) {
  if (collapsed) {
    return (
      <aside className="shrink-0">
        <Button variant="outline" size="icon-lg" onClick={onToggleCollapsed} title="Expand menu">
          <PanelLeftOpenIcon className="size-4" />
        </Button>
      </aside>
    )
  }

  return (
    <aside className="w-full md:w-[320px] shrink-0 space-y-4">
      <div className="flex gap-2">
        <Button className="flex-1 font-semibold" size="lg" onClick={onNewRequest}>
          + New Hypothesis
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
        <Dialog>
          <DialogTrigger asChild>
            <Button variant="outline" size="icon-lg" title="How it works">
              <HelpCircleIcon className="size-4" />
            </Button>
          </DialogTrigger>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>How it works</DialogTitle>
              <DialogDescription>The agent moves through five phases on every run.</DialogDescription>
            </DialogHeader>
            <HowItWorksPanel />
          </DialogContent>
        </Dialog>
        <Button variant="ghost" size="icon-lg" onClick={onToggleCollapsed} title="Collapse menu">
          <PanelLeftCloseIcon className="size-4" />
        </Button>
      </div>

      <div className="border rounded-lg p-3 bg-card shadow-sm">
        <p className="text-sm font-semibold mb-2">History</p>
        <HistoryList runs={runs} viewedRunId={viewedRunId} onSelect={onSelectHistory} />
      </div>
    </aside>
  )
}
