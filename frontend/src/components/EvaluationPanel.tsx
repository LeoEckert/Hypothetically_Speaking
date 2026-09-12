import ReactMarkdown from "react-markdown"
import remarkGfm from "remark-gfm"
import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from "@/components/ui/accordion"
import { Alert, AlertDescription } from "@/components/ui/alert"
import { ConfidenceBadge } from "@/components/HypothesisCard"
import { withCitations } from "@/lib/citations"
import { buildComponents } from "@/lib/markdownComponents"
import type { EvaluationResult, EvidenceItem } from "@/types"

function usd(value: number | null): string {
  if (value === null) return "—"
  return `$${value.toFixed(4)}`
}

export function EvaluationPanel({
  evaluation,
  evidence,
}: {
  evaluation: EvaluationResult
  evidence: Record<string, EvidenceItem>
}) {
  const e = evaluation
  const revisedMarkdown = e.critiques
    .map((c) => `## ${c.title}\n${e.revised.sections[c.section] ?? ""}`)
    .join("\n\n")

  return (
    <div className="space-y-3 rounded-lg border bg-muted/30 p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-xs text-muted-foreground">
          Evaluated {new Date(e.created_at).toLocaleString()}
          {e.comment && <> · comment: “{e.comment}”</>}
        </p>
        <span className="font-mono text-xs text-muted-foreground">
          {e.cost.rate_configured ? usd(e.cost.usd) : "rate not configured"}
        </span>
      </div>

      <div>
        <p className="mb-1 text-xs font-semibold text-muted-foreground">Critique</p>
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
      </div>

      <div>
        <div className="mb-1 flex flex-wrap items-center gap-2">
          <p className="text-xs font-semibold text-muted-foreground">Revised hypothesis</p>
          <ConfidenceBadge confidence={e.revised.confidence} />
        </div>
        <p className="mb-1 text-sm font-medium">
          {withCitations(e.revised.statement, evidence, "revised-statement")}
        </p>
        {e.revised.confidence_reason && (
          <p className="mb-2 text-xs text-muted-foreground">{e.revised.confidence_reason}</p>
        )}
        <div className="rounded-md border bg-card p-3">
          <ReactMarkdown remarkPlugins={[remarkGfm]} components={buildComponents(evidence)}>
            {revisedMarkdown}
          </ReactMarkdown>
        </div>
      </div>

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
    </div>
  )
}
