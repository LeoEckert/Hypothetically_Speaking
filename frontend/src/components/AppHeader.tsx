import { HelpCircleIcon, HistoryIcon } from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog"
import { HowItWorksPanel } from "@/components/HowItWorksPanel"

export function AppHeader({
  runsCount,
  onOpenHistory,
  onNewRequest,
}: {
  runsCount: number
  onOpenHistory: () => void
  onNewRequest: () => void
}) {
  return (
    <div className="mb-6 pb-4 border-b flex items-start justify-between gap-4 flex-wrap">
      <div className="flex items-start gap-3">
        <Button variant="outline" size="icon-lg" onClick={onOpenHistory} title="History" className="relative shrink-0">
          <HistoryIcon className="size-4" />
          {runsCount > 0 && (
            <Badge variant="default" className="absolute -top-1.5 -right-1.5 h-4 min-w-4 px-1 text-[10px]">
              {runsCount}
            </Badge>
          )}
        </Button>

        <div>
          <h1 className="text-2xl font-bold tracking-tight">Hypothetically Speaking</h1>
          <p className="text-muted-foreground mt-1">
            A Longevity AI Scientist — ask an ageing/longevity research question, watch it plan, retrieve,
            compute, and cite.
          </p>
        </div>
      </div>

      <div className="flex items-center gap-2 shrink-0">
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

        <Button className="font-semibold" size="lg" onClick={onNewRequest}>
          + New Hypothesis
        </Button>
      </div>
    </div>
  )
}
