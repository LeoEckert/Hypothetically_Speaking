import { Fragment } from "react"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import type { EvidenceItem } from "@/types"

const CITATION_RE = /\[([A-Za-z0-9_:.\-]+)\]/g

function renderLineWithCitations(line: string, evidence: Record<string, EvidenceItem>, lineKey: string) {
  const parts: React.ReactNode[] = []
  let lastIndex = 0
  let match: RegExpExecArray | null
  let i = 0
  CITATION_RE.lastIndex = 0
  while ((match = CITATION_RE.exec(line)) !== null) {
    if (match.index > lastIndex) {
      parts.push(<Fragment key={`${lineKey}-t${i++}`}>{line.slice(lastIndex, match.index)}</Fragment>)
    }
    const id = match[1]
    const item = evidence[id]
    if (item) {
      parts.push(
        <Tooltip key={`${lineKey}-c${i++}`}>
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
            <p className="text-xs">{item.summary}</p>
          </TooltipContent>
        </Tooltip>
      )
    } else {
      parts.push(
        <code key={`${lineKey}-c${i++}`} className="font-mono text-xs bg-muted px-1 py-0.5 rounded">
          [{id}]
        </code>
      )
    }
    lastIndex = match.index + match[0].length
  }
  if (lastIndex < line.length) {
    parts.push(<Fragment key={`${lineKey}-t${i++}`}>{line.slice(lastIndex)}</Fragment>)
  }
  return parts
}

export function ReportView({
  report,
  evidence,
}: {
  report: string
  evidence: Record<string, EvidenceItem>
}) {
  const lines = report.split("\n")

  return (
    <div className="mt-4 p-6 border rounded-xl shadow-md bg-card space-y-1">
      {lines.map((line, idx) => {
        const key = `line-${idx}`
        if (line.startsWith("## ")) {
          return (
            <h2 key={key} className="text-lg font-semibold mt-5 mb-1.5 pb-1 border-b first:mt-0">
              {line.slice(3)}
            </h2>
          )
        }
        if (line.startsWith("- ")) {
          return (
            <div key={key} className="pl-2">
              • {renderLineWithCitations(line.slice(2), evidence, key)}
            </div>
          )
        }
        if (!line.trim()) {
          return <div key={key} className="h-2" />
        }
        return (
          <p key={key} className="text-sm leading-relaxed">
            {renderLineWithCitations(line, evidence, key)}
          </p>
        )
      })}
    </div>
  )
}
