import { Fragment, type ReactNode } from "react"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import type { EvidenceItem } from "@/types"

const CITATION_RE = /\[([A-Za-z0-9_:.-]+)\]/g

function withCitationsInText(text: string, evidence: Record<string, EvidenceItem>, keyPrefix: string): ReactNode[] {
  const parts: ReactNode[] = []
  let lastIndex = 0
  let match: RegExpExecArray | null
  let i = 0
  CITATION_RE.lastIndex = 0
  while ((match = CITATION_RE.exec(text)) !== null) {
    if (match.index > lastIndex) {
      parts.push(<Fragment key={`${keyPrefix}-t${i++}`}>{text.slice(lastIndex, match.index)}</Fragment>)
    }
    const id = match[1]
    const item = evidence[id]
    if (item) {
      parts.push(
        <Tooltip key={`${keyPrefix}-c${i++}`}>
          <TooltipTrigger asChild>
            <a
              href={item.url || undefined}
              target="_blank"
              rel="noreferrer"
              className="font-mono text-xs bg-muted px-1 py-0.5 rounded hover:underline"
            >
              [{id}]
            </a>
          </TooltipTrigger>
          <TooltipContent className="max-w-xs">
            <p className="text-xs">{item.title || item.summary}</p>
          </TooltipContent>
        </Tooltip>
      )
    } else {
      parts.push(
        <code key={`${keyPrefix}-c${i++}`} className="font-mono text-xs bg-muted px-1 py-0.5 rounded">
          [{id}]
        </code>
      )
    }
    lastIndex = match.index + match[0].length
  }
  if (lastIndex < text.length) {
    parts.push(<Fragment key={`${keyPrefix}-t${i++}`}>{text.slice(lastIndex)}</Fragment>)
  }
  return parts
}

/** Walk React children, resolving citation markers (`[PMID:123]`) found in
 * any string node into a hoverable link against the evidence registry.
 * Non-string children (already-rendered elements, e.g. nested markdown
 * inline formatting) pass through untouched. */
export function withCitations(
  children: ReactNode,
  evidence: Record<string, EvidenceItem>,
  keyPrefix: string
): ReactNode {
  const nodes = Array.isArray(children) ? children : [children]
  return nodes.map((child, i) =>
    typeof child === "string" ? (
      <Fragment key={`${keyPrefix}-n${i}`}>{withCitationsInText(child, evidence, `${keyPrefix}-n${i}`)}</Fragment>
    ) : (
      <Fragment key={`${keyPrefix}-n${i}`}>{child}</Fragment>
    )
  )
}
