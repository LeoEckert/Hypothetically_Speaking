import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Textarea } from "@/components/ui/textarea"

export function ComposeBox({
  question,
  onQuestionChange,
  onRun,
  runDisabled,
  statusText,
  forkNote,
  showLiveBanner,
  onViewLive,
}: {
  question: string
  onQuestionChange: (v: string) => void
  onRun: () => void
  runDisabled: boolean
  statusText: string
  forkNote: string | null
  showLiveBanner: boolean
  onViewLive: () => void
}) {
  return (
    <Card className="py-4 shadow-sm">
      <CardContent className="px-4 space-y-3">
        {showLiveBanner && (
          <div className="flex items-center justify-between border rounded-lg p-3 bg-primary/5 text-sm">
            <span>A run is in progress in the background.</span>
            <Button variant="outline" size="sm" onClick={onViewLive}>
              View live run
            </Button>
          </div>
        )}

        {forkNote && <p className="text-sm text-primary">{forkNote}</p>}

        <Textarea
          value={question}
          onChange={(e) => onQuestionChange(e.target.value)}
          placeholder="e.g. Does SIRT1 activation plausibly extend human healthspan via mitochondrial biogenesis?"
          className="min-h-[90px] resize-y"
        />
        <div className="flex items-center gap-3">
          <Button onClick={onRun} disabled={runDisabled || !question.trim()} size="lg">
            Run
          </Button>
          <span className="text-sm font-medium text-muted-foreground">{statusText}</span>
        </div>
      </CardContent>
    </Card>
  )
}
