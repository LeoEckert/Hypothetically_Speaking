import { useState, type ReactNode } from "react"
import { ChevronDownIcon, Columns2Icon, Rows2Icon } from "lucide-react"
import ReactMarkdown from "react-markdown"
import remarkGfm from "remark-gfm"
import { Badge } from "@/components/ui/badge"
import { Alert, AlertDescription } from "@/components/ui/alert"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible"
import { ConfidenceBadge } from "@/components/HypothesisCard"
import { withCitations } from "@/lib/citations"
import { buildComponents } from "@/lib/markdownComponents"
import {
  buildSectionPairs,
  classifyDiff,
  normalizeDashes,
  toPlainText,
  type DiffPart,
  type SectionPair,
  type SectionStatus,
} from "@/lib/evalDiff"
import { diffWordsWithSpace } from "diff"
import type { EvaluationResult, EvidenceItem, RankedHypothesis } from "@/types"

type ViewMode = "split" | "unified"

function usd(value: number | null): string {
  if (value === null) return "—"
  return `$${value.toFixed(4)}`
}

const STATUS_LABEL: Record<SectionStatus, string> = {
  unchanged: "Unchanged",
  revised: "Revised",
  rewritten: "Rewritten",
}

const STATUS_STYLE: Record<SectionStatus, string> = {
  unchanged: "border-dashed text-muted-foreground",
  revised: "border-amber-500/40 text-amber-700 dark:text-amber-400",
  rewritten: "border-violet-500/40 text-violet-700 dark:text-violet-400",
}

/** Insertions and deletions are marked by shape as well as colour —
 * strikethrough for cut text, underline for added text — so the diff still
 * reads without colour vision. */
const REMOVED_CLASS =
  "bg-red-500/10 text-red-800 dark:text-red-300 line-through decoration-red-500/70"
const ADDED_CLASS =
  "bg-emerald-500/10 text-emerald-900 dark:text-emerald-300 underline decoration-emerald-500/70 decoration-2 underline-offset-2"

/** One side of a word-level diff. `side` decides which parts are dropped:
 * the original never shows insertions, the revision never shows deletions,
 * and the unified view shows both in reading order. */
function DiffText({
  parts,
  side,
  evidence,
  keyPrefix,
}: {
  parts: DiffPart[]
  side: "original" | "revised" | "unified"
  evidence: Record<string, EvidenceItem>
  keyPrefix: string
}) {
  return (
    <p className="whitespace-pre-wrap text-sm leading-relaxed">
      {parts.map((part, i) => {
        if (part.added && side === "original") return null
        if (part.removed && side === "revised") return null
        const className = part.removed ? REMOVED_CLASS : part.added ? ADDED_CLASS : undefined
        return (
          <span key={`${keyPrefix}-${i}`} className={className}>
            {withCitations(part.value, evidence, `${keyPrefix}-${i}`)}
          </span>
        )
      })}
    </p>
  )
}

function Markdown({ body, evidence }: { body: string; evidence: Record<string, EvidenceItem> }) {
  return (
    <ReactMarkdown remarkPlugins={[remarkGfm]} components={buildComponents(evidence)}>
      {normalizeDashes(body)}
    </ReactMarkdown>
  )
}

function ColumnLabel({ children }: { children: ReactNode }) {
  return (
    <p className="mb-1.5 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
      {children}
    </p>
  )
}

function SectionDiff({
  pair,
  view,
  evidence,
}: {
  pair: SectionPair
  view: ViewMode
  evidence: Record<string, EvidenceItem>
}) {
  // Sections the reviser left alone start collapsed: the eye should go
  // straight to where work actually happened.
  const [open, setOpen] = useState(pair.status !== "unchanged")
  const findings = pair.critique?.findings ?? []

  return (
    <div className="rounded-md border bg-card">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full flex-wrap items-center gap-2 px-3 py-2 text-left hover:bg-muted/40"
      >
        <ChevronDownIcon className={`size-3.5 shrink-0 transition-transform ${open ? "" : "-rotate-90"}`} />
        <span className="text-sm font-semibold">{pair.title}</span>
        <Badge variant="outline" className={`text-[10px] ${STATUS_STYLE[pair.status]}`}>
          {STATUS_LABEL[pair.status]}
        </Badge>
        {findings.length > 0 && (
          <span className="text-xs text-muted-foreground">
            {findings.length} finding{findings.length === 1 ? "" : "s"}
          </span>
        )}
      </button>

      {open && (
        <div className="space-y-3 border-t px-3 py-3">
          {pair.changeLog && (
            <p className="text-xs text-muted-foreground">
              <span className="font-medium text-foreground">What changed: </span>
              {pair.changeLog.what_changed}{" "}
              <span className="font-medium text-foreground">Why: </span>
              {pair.changeLog.why}
            </p>
          )}

          {pair.status === "unchanged" ? (
            <div>
              <ColumnLabel>Unchanged by the reviser</ColumnLabel>
              <Markdown body={pair.revised || pair.original} evidence={evidence} />
            </div>
          ) : view === "split" ? (
            <div className="grid gap-4 lg:grid-cols-2">
              <div className="lg:border-r lg:pr-4">
                <ColumnLabel>Original</ColumnLabel>
                {pair.status === "revised" ? (
                  <DiffText parts={pair.parts} side="original" evidence={evidence} keyPrefix={`${pair.section}-o`} />
                ) : (
                  <Markdown body={pair.original} evidence={evidence} />
                )}
              </div>
              <div>
                <ColumnLabel>Revised</ColumnLabel>
                {pair.status === "revised" ? (
                  <DiffText parts={pair.parts} side="revised" evidence={evidence} keyPrefix={`${pair.section}-r`} />
                ) : (
                  <Markdown body={pair.revised} evidence={evidence} />
                )}
              </div>
            </div>
          ) : (
            <div className="space-y-3">
              {pair.status === "revised" ? (
                <DiffText parts={pair.parts} side="unified" evidence={evidence} keyPrefix={`${pair.section}-u`} />
              ) : (
                <>
                  <div>
                    <ColumnLabel>Original</ColumnLabel>
                    <Markdown body={pair.original} evidence={evidence} />
                  </div>
                  <div className="border-t pt-3">
                    <ColumnLabel>Revised</ColumnLabel>
                    <Markdown body={pair.revised} evidence={evidence} />
                  </div>
                </>
              )}
            </div>
          )}

          {pair.status === "rewritten" && (
            <p className="text-[11px] italic text-muted-foreground">
              Rewritten end to end — word-level highlighting would mark nearly every word, so
              both versions are shown in full instead.
            </p>
          )}

          {pair.critique && (findings.length > 0 || pair.critique.critique) && (
            <Collapsible>
              <CollapsibleTrigger className="group flex items-center gap-1 text-xs font-medium text-primary hover:underline">
                <ChevronDownIcon className="size-3 transition-transform group-data-[state=open]:rotate-180" />
                <span className="group-data-[state=open]:hidden">Why it changed</span>
                <span className="hidden group-data-[state=open]:inline">Hide critique</span>
              </CollapsibleTrigger>
              <CollapsibleContent className="mt-2 space-y-2 rounded-md bg-muted/40 p-3 text-xs">
                <p className="text-muted-foreground">{pair.critique.critique}</p>
                {findings.map((f, i) => (
                  <div key={i} className="space-y-0.5 border-l-2 border-amber-500/50 pl-2">
                    <p className="font-medium">{f.problem}</p>
                    <p className="text-muted-foreground">{f.why_it_matters}</p>
                    <p className="italic text-muted-foreground">“{f.evidence}”</p>
                    <p className="text-muted-foreground">
                      <span className="font-medium text-foreground">Suggestion: </span>
                      {f.suggestion}
                    </p>
                  </div>
                ))}
              </CollapsibleContent>
            </Collapsible>
          )}
        </div>
      )}
    </div>
  )
}

export function EvaluationPanel({
  evaluation,
  evidence,
  original,
  report,
}: {
  evaluation: EvaluationResult
  evidence: Record<string, EvidenceItem>
  original: RankedHypothesis
  /** The run's report markdown — the left-hand side of every diff. */
  report: string
}) {
  const e = evaluation
  const [view, setView] = useState<ViewMode>("split")

  const pairs = buildSectionPairs(e, report)
  const changedCount = pairs.filter((p) => p.status !== "unchanged").length
  const totalFindings = pairs.reduce((n, p) => n + (p.critique?.findings.length ?? 0), 0)
  const confidenceChanged = original.confidence !== e.revised.confidence

  const statementParts = diffWordsWithSpace(
    toPlainText(original.statement),
    toPlainText(e.revised.statement)
  )
  // A statement rewritten end to end gets the same treatment as a section
  // rewritten end to end: show both versions plainly instead of highlighting
  // every word of them.
  const statementStatus = classifyDiff(statementParts).status
  const statementChanged = statementStatus === "revised" 

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

        {/* What the review did, before a word of it is read. */}
        <div className="flex flex-wrap items-center gap-x-3 gap-y-2 rounded-md border bg-muted/30 px-3 py-2 text-xs">
          <span className="font-medium">
            {changedCount} of {pairs.length} section{pairs.length === 1 ? "" : "s"} revised
          </span>
          <span className="text-muted-foreground">·</span>
          <span className="flex items-center gap-1.5">
            <span className="text-muted-foreground">Confidence:</span>
            <ConfidenceBadge confidence={original.confidence} />
            {confidenceChanged && (
              <>
                <span className="text-muted-foreground">→</span>
                <ConfidenceBadge confidence={e.revised.confidence} />
              </>
            )}
            {!confidenceChanged && <span className="text-muted-foreground">(unchanged)</span>}
          </span>
          <span className="text-muted-foreground">·</span>
          <span className="text-muted-foreground">
            {totalFindings} finding{totalFindings === 1 ? "" : "s"}
          </span>

          <div className="ml-auto flex items-center gap-1">
            <button
              type="button"
              onClick={() => setView("split")}
              aria-pressed={view === "split"}
              className={`flex items-center gap-1 rounded px-2 py-1 ${
                view === "split" ? "bg-background shadow-sm" : "text-muted-foreground hover:text-foreground"
              }`}
            >
              <Columns2Icon className="size-3" />
              Side by side
            </button>
            <button
              type="button"
              onClick={() => setView("unified")}
              aria-pressed={view === "unified"}
              className={`flex items-center gap-1 rounded px-2 py-1 ${
                view === "unified" ? "bg-background shadow-sm" : "text-muted-foreground hover:text-foreground"
              }`}
            >
              <Rows2Icon className="size-3" />
              Unified
            </button>
          </div>
        </div>

        {/* The hypothesis statement itself, diffed like any other section. */}
        <div className="rounded-md border bg-card p-3">
          <div className="grid gap-4 lg:grid-cols-2">
            <div className="lg:border-r lg:pr-4">
              <ColumnLabel>Original hypothesis</ColumnLabel>
              {statementChanged ? (
                <DiffText parts={statementParts} side="original" evidence={evidence} keyPrefix="stmt-o" />
              ) : (
                <p className="text-sm leading-relaxed">
                  {withCitations(normalizeDashes(original.statement), evidence, "stmt-plain-o")}
                </p>
              )}
            </div>
            <div>
              <ColumnLabel>Revised hypothesis</ColumnLabel>
              {statementChanged ? (
                <DiffText parts={statementParts} side="revised" evidence={evidence} keyPrefix="stmt-r" />
              ) : (
                <p className="text-sm leading-relaxed">
                  {withCitations(normalizeDashes(e.revised.statement), evidence, "stmt-plain-r")}
                </p>
              )}
            </div>
          </div>
          {e.revised.confidence_reason && (
            <p className="mt-2 border-t pt-2 text-xs text-muted-foreground">
              <span className="font-medium text-foreground">Confidence: </span>
              {withCitations(normalizeDashes(e.revised.confidence_reason), evidence, "conf-reason")}
            </p>
          )}
        </div>

        {pairs.map((pair) => (
          <SectionDiff key={pair.section} pair={pair} view={view} evidence={evidence} />
        ))}

        {e.revised.unresolved.length > 0 && (
          <Alert>
            <AlertDescription>
              <p className="text-xs font-semibold text-amber-700 dark:text-amber-400">
                Unresolved — the review could not settle these
              </p>
              <ul className="list-disc space-y-0.5 pl-4 text-xs text-muted-foreground">
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
