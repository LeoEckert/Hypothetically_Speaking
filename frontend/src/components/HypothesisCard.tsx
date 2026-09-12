import { useState } from "react"
import { ChevronRightIcon, FileTextIcon } from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { withCitations } from "@/lib/citations"
import type { EvidenceItem, RankedHypothesis } from "@/types"

const CONFIDENCE_STYLES: Record<string, string> = {
  high: "border-green-300 bg-green-50 text-green-700 dark:border-green-800 dark:bg-green-950/40 dark:text-green-300",
  medium: "border-amber-300 bg-amber-50 text-amber-700 dark:border-amber-800 dark:bg-amber-950/40 dark:text-amber-300",
  low: "border-muted-foreground/30 bg-muted text-muted-foreground",
}

export function ConfidenceBadge({ confidence }: { confidence: RankedHypothesis["confidence"] }) {
  if (!confidence) {
    return (
      <Badge variant="outline" className="text-[10px] border-dashed text-muted-foreground">
        unevaluated
      </Badge>
    )
  }
  return (
    <Badge variant="outline" className={`text-[10px] ${CONFIDENCE_STYLES[confidence]}`}>
      {confidence} confidence
    </Badge>
  )
}

function EvidenceLinks({
  ids,
  evidence,
  emptyLabel,
}: {
  ids: string[]
  evidence: Record<string, EvidenceItem>
  emptyLabel: string
}) {
  const resolved = ids.map((id) => ({ id, item: evidence[id] })).filter((e) => e.item)
  if (resolved.length === 0) {
    return <p className="text-xs text-muted-foreground italic">{emptyLabel}</p>
  }
  return (
    <ul className="space-y-1">
      {resolved.map(({ id, item }) => (
        <li key={id} className="text-xs leading-snug">
          <a
            href={item.url || undefined}
            target="_blank"
            rel="noreferrer"
            className="hover:underline"
          >
            {item.title || item.summary.slice(0, 80)}
          </a>{" "}
          <code className="font-mono text-[10px] text-muted-foreground">[{id}]</code>
        </li>
      ))}
    </ul>
  )
}

function HypothesisCard({
  hypothesis,
  evidence,
  expanded,
  onToggle,
  onIterate,
  onOpenDetails,
}: {
  hypothesis: RankedHypothesis
  evidence: Record<string, EvidenceItem>
  expanded: boolean
  onToggle: () => void
  onIterate?: (seedQuestion: string) => void
  onOpenDetails?: () => void
}) {
  const h = hypothesis
  return (
    <div className={`border rounded-lg ${h.selected ? "border-primary/40 bg-primary/[0.02]" : ""}`}>
      <div className="flex items-start gap-2 p-3">
        <button
          type="button"
          onClick={onToggle}
          className="flex min-w-0 flex-1 items-start gap-2 text-left cursor-pointer"
        >
          <ChevronRightIcon
            className={`size-4 mt-0.5 shrink-0 text-muted-foreground transition-transform ${expanded ? "rotate-90" : ""}`}
          />
          <span className="font-mono text-xs text-muted-foreground mt-0.5">#{h.rank}</span>
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 flex-wrap">
              <span className={`text-sm ${h.selected ? "font-semibold" : ""}`}>{h.statement}</span>
              {h.selected && (
                <Badge variant="outline" className="text-[10px] align-middle">
                  selected
                </Badge>
              )}
            </div>
          </div>
        </button>
        <div className="flex shrink-0 items-center gap-2">
          {h.selected && onOpenDetails && (
            <Button size="sm" onClick={onOpenDetails}>
              <FileTextIcon className="size-3.5" />
              Full report
            </Button>
          )}
          <ConfidenceBadge confidence={h.confidence} />
        </div>
      </div>

      {expanded && (
        <div className="px-3 pb-3 pl-9 space-y-3">
          {h.rationale && (
            <p className="text-sm text-muted-foreground leading-relaxed">
              {withCitations(h.rationale, evidence, `hyp-${h.id}-rationale`)}
            </p>
          )}
          <div className="grid sm:grid-cols-2 gap-3">
            <div>
              <p className="text-xs font-semibold text-muted-foreground mb-1">Evidence that supports it</p>
              <EvidenceLinks ids={h.evidence_ids} evidence={evidence} emptyLabel="No evidence linked yet." />
            </div>
            <div>
              <p className="text-xs font-semibold text-muted-foreground mb-1">Evidence against it</p>
              <EvidenceLinks
                ids={h.contradicting_ids}
                evidence={evidence}
                emptyLabel="Nothing contradicting found yet."
              />
            </div>
          </div>
          {!h.selected && onIterate && h.seed_question && (
            <Button size="sm" variant="outline" onClick={() => onIterate(h.seed_question)}>
              Iterate on this hypothesis
            </Button>
          )}
        </div>
      )}
    </div>
  )
}

export function HypothesisList({
  hypotheses,
  evidence,
  onIterate,
  onOpenDetails,
}: {
  hypotheses: RankedHypothesis[]
  evidence: Record<string, EvidenceItem>
  onIterate?: (seedQuestion: string) => void
  onOpenDetails?: () => void
}) {
  const [expandedId, setExpandedId] = useState<string | null>(null)

  const sorted = [...hypotheses].sort((a, b) => a.rank - b.rank)

  return (
    <div className="space-y-2">
      {sorted.map((h) => (
        <HypothesisCard
          key={h.id}
          hypothesis={h}
          evidence={evidence}
          expanded={expandedId === h.id}
          onToggle={() => setExpandedId((cur) => (cur === h.id ? null : h.id))}
          onIterate={onIterate}
          onOpenDetails={h.selected ? onOpenDetails : undefined}
        />
      ))}
    </div>
  )
}
