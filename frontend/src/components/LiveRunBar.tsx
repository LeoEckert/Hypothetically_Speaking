import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"

export function LiveRunBar({
  isRunning,
  question,
  statusText,
  onCancel,
  showLiveBanner,
  onViewLive,
}: {
  isRunning: boolean
  question: string
  statusText: string
  onCancel: () => void
  showLiveBanner: boolean
  onViewLive: () => void
}) {
  if (!isRunning && !showLiveBanner) return null

  return (
    <Card className="mb-4 py-3 shadow-sm">
      <CardContent className="px-4 space-y-3">
        {showLiveBanner && (
          <div className="flex items-center justify-between border rounded-lg p-3 bg-primary/5 text-sm">
            <span>A run is in progress in the background.</span>
            <Button variant="outline" size="sm" onClick={onViewLive}>
              View live run
            </Button>
          </div>
        )}

        {isRunning && (
          <div className="flex items-center justify-between gap-3">
            <div className="min-w-0">
              <p className="text-sm truncate">{question}</p>
              <p className="text-sm font-medium text-muted-foreground">{statusText}</p>
            </div>
            <Button onClick={onCancel} variant="destructive" size="sm" className="shrink-0">
              Cancel
            </Button>
          </div>
        )}
      </CardContent>
    </Card>
  )
}
