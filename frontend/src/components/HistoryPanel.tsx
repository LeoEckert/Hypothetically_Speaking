import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet"
import { HistoryList } from "@/components/HistoryList"
import type { RunRecord } from "@/types"

export function HistoryPanel({
  runs,
  viewedRunId,
  onSelect,
  open,
  onOpenChange,
}: {
  runs: RunRecord[]
  viewedRunId: string | null
  onSelect: (id: string) => void
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="left" className="sm:max-w-md">
        <SheetHeader>
          <SheetTitle>History</SheetTitle>
          <SheetDescription>Past and in-progress runs. Select one to view it.</SheetDescription>
        </SheetHeader>
        <div className="flex-1 min-h-0 px-4 pb-4">
          <HistoryList
            runs={runs}
            viewedRunId={viewedRunId}
            onSelect={(id) => {
              onSelect(id)
              onOpenChange(false)
            }}
          />
        </div>
      </SheetContent>
    </Sheet>
  )
}
