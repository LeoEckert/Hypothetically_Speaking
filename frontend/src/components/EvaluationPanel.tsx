import { ChevronDownIcon } from "lucide-react"
import ReactMarkdown from "react-markdown"
import remarkGfm from "remark-gfm"
import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from "@/components/ui/accordion"
import { Alert, AlertDescription } from "@/components/ui/alert"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible"
import { ConfidenceBadge } from "@/components/HypothesisCard"
import { withCitations } from "@/lib/citations"
import { buildComponents } from "@/lib/markdownComponents"
import type { EvaluationResult, EvidenceItem, RankedHypothesis } from "@/types"

function usd(value: number | null): string {
  if (value === null) return "—"
  return `$${value.toFixed(4)}`
}

export function EvaluationPanel({
  evaluation,
  evidence,
  original,
}: {
  evaluation: EvaluationResult
  evidence: Record<string, EvidenceItem>
  original: RankedHypothesis
}) {
  const e = evaluation
  const revisedMarkdown = e.critiques
    .map((c) => `## ${c.title}\n${e.revised.sections[c.section] ?? ""}`)
    .join("\n\n")
  const totalFindings = e.critiques.reduce((n, c) => n + c.findings.length, 0)

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex flex-wrap items-center justify-between gap-2 text-sm">
          <span>AI Evaluation</span>
          <span className="font-mono text-xs font-normal text-muted-foreground">
            {new Date(e.created_at).toLocaleString()} ·{" "}
            {e.cost.rate_configured ? usd(e.cost.usd) : "rate not configured"}
          </span>
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        {e.comment && (
          <p className="border-l-2 border-muted-foreground/30 pl-2 text-sm italic text-muted-foreground">
            “{e.comment}”
          </p>
        )}

        <div className="rounded-md border bg-muted/30 p-3">
          <div className="mb-1 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
            <span>Confidence:</span>
            <ConfidenceBadge confidence={original.confidence} />
            <span>→</span>
            <ConfidenceBadge confidence={e.revised.confidence} />
          </div>
          {e.revised.confidence_reason && (
            <p className="mb-2 text-xs text-muted-foreground">{e.revised.confidence_reason}</p>
          )}
          <p className="text-sm font-medium">{withCitations(e.revised.statement, evidence, "revised-statement")}</p>
        </div>

        <div className="rounded-md border bg-card p-3">
          <ReactMarkdown remarkPlugins={[remarkGfm]} components={buildComponents(evidence)}>
            {revisedMarkdown}
          </ReactMarkdown>
        </div>

        <Collapsible>
          <CollapsibleTrigger className="group flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground">
            <ChevronDownIcon className="size-3 transition-transform group-data-[state=open]:rotate-180" />
            Show critique details ({totalFindings} finding{totalFindings === 1 ? "" : "s"})
          </CollapsibleTrigger>
          <CollapsibleContent className="mt-2">
            <Accordion type="multiple" className="rounded-md border bg-card px-2">
              {e.critiques.map((c) => (
                <AccordionItem key={c.section} value={c.section}>
                  <AccordionTrigger className="text-xs">
                    {c.title}
                    {c.findings.length > 0 && (
                      <span className="ml-1 text-muted-foreground">({c.findings.length})</span>
                    )}
                  </AccordionTrigger>
                  <AccordionContent className="space-y-2 text-xs">
                    <p className="text-muted-foreground">{c.critique}</p>
                    {c.findings.map((f, i) => (
                      <div key={i} className="space-y-0.5 border-l-2 border-muted-foreground/30 pl-2">
                        <p className="font-medium">{f.problem}</p>
                        <p className="text-muted-foreground">{f.why_it_matters}</p>
                        <p className="italic text-muted-foreground">“{f.evidence}”</p>
                        <p className="text-muted-foreground">Suggestion: {f.suggestion}</p>
                      </div>
                    ))}
                  </AccordionContent>
                </AccordionItem>
              ))}
            </Accordion>
          </CollapsibleContent>
        </Collapsible>

        {e.revised.change_log.length > 0 && (
          <div>
            <p className="mb-1 text-xs font-semibold text-muted-foreground">What changed and why</p>
            <ul className="space-y-1">
              {e.revised.change_log.map((c, i) => (
                <li key={i} className="text-xs text-muted-foreground">
                  <span className="font-medium text-foreground">{c.section}:</span> {c.what_changed} — {c.why}
                </li>
              ))}
            </ul>
          </div>
        )}

        {e.revised.unresolved.length > 0 && (
          <Alert variant="destructive">
            <AlertDescription>
              <p className="text-xs font-semibold">Unresolved</p>
              <ul className="list-disc space-y-0.5 pl-4">
                {e.revised.unresolved.map((u, i) => (
                  <li key={i}>{u}</li>
                ))}
              </ul>
            </AlertDescription>
          </Alert>
        )}
      </CardContent>
    </Card>
  )
}
