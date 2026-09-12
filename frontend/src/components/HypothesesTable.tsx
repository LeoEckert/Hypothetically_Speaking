import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { renderLineWithCitations } from "@/components/ReportView"
import type { EvidenceItem, RankedHypothesis } from "@/types"

const CONFIDENCE_STYLES: Record<string, string> = {
  high: "border-green-300 bg-green-50 text-green-700 dark:border-green-800 dark:bg-green-950/40 dark:text-green-300",
  medium: "border-amber-300 bg-amber-50 text-amber-700 dark:border-amber-800 dark:bg-amber-950/40 dark:text-amber-300",
  low: "border-muted-foreground/30 bg-muted text-muted-foreground",
}

export function HypothesesTable({
  hypotheses,
  evidence,
  onIterate,
}: {
  hypotheses: RankedHypothesis[]
  evidence: Record<string, EvidenceItem>
  onIterate: (seedQuestion: string) => void
}) {
  const sorted = [...hypotheses].sort((a, b) => a.rank - b.rank)

  return (
    <div className="mt-4 p-4 border rounded-xl shadow-sm bg-card">
      <p className="text-sm font-semibold mb-2">Candidate hypotheses (ranked)</p>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead className="w-10">#</TableHead>
            <TableHead>Hypothesis</TableHead>
            <TableHead className="w-24">Confidence</TableHead>
            <TableHead>Rationale</TableHead>
            <TableHead className="w-10" />
          </TableRow>
        </TableHeader>
        <TableBody>
          {sorted.map((h) => (
            <TableRow key={h.rank}>
              <TableCell className="font-mono text-xs">{h.rank}</TableCell>
              <TableCell className={h.selected ? "font-semibold" : undefined}>
                {h.statement}
                {h.selected && (
                  <Badge variant="outline" className="ml-2 text-[10px] align-middle">
                    selected
                  </Badge>
                )}
              </TableCell>
              <TableCell>
                <Badge
                  variant="outline"
                  className={`text-[10px] ${h.confidence ? CONFIDENCE_STYLES[h.confidence] : CONFIDENCE_STYLES.low}`}
                >
                  {h.confidence ?? "—"}
                </Badge>
              </TableCell>
              <TableCell className="text-sm text-muted-foreground line-clamp-2 max-w-md" title={h.rationale}>
                {renderLineWithCitations(h.rationale, evidence, `hyp-${h.rank}`)}
              </TableCell>
              <TableCell>
                <Button size="sm" variant="outline" onClick={() => onIterate(h.seed_question)}>
                  Iterate on hypothesis
                </Button>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  )
}
