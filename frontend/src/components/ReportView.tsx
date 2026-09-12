import { ChevronDownIcon } from "lucide-react"
import ReactMarkdown from "react-markdown"
import remarkGfm from "remark-gfm"
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible"
import { buildComponents } from "@/lib/markdownComponents"
import { splitReportSections, teaser } from "@/lib/reportSections"
import type { EvidenceItem } from "@/types"

function Section({
  heading,
  body,
  evidence,
}: {
  heading: string
  body: string
  evidence: Record<string, EvidenceItem>
}) {
  return (
    <div className="border-b pb-4 last:border-b-0 last:pb-0">
      <h2 className="mb-1.5 text-lg font-semibold">{heading}</h2>
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={buildComponents(evidence)}>
        {body}
      </ReactMarkdown>
    </div>
  )
}

function CollapsibleSection({
  heading,
  body,
  evidence,
}: {
  heading: string
  body: string
  evidence: Record<string, EvidenceItem>
}) {
  return (
    <Collapsible className="border-b pb-3 last:border-b-0 last:pb-0">
      <CollapsibleTrigger className="group flex w-full items-start justify-between gap-2 text-left">
        <div>
          <h2 className="text-lg font-semibold">{heading}</h2>
          <p className="mt-0.5 text-sm text-muted-foreground">{teaser(body)}</p>
        </div>
        <ChevronDownIcon className="mt-1 size-4 shrink-0 text-muted-foreground transition-transform group-data-[state=open]:rotate-180" />
      </CollapsibleTrigger>
      <CollapsibleContent className="mt-2">
        <ReactMarkdown remarkPlugins={[remarkGfm]} components={buildComponents(evidence)}>
          {body}
        </ReactMarkdown>
      </CollapsibleContent>
    </Collapsible>
  )
}

export function ReportView({
  report,
  evidence,
}: {
  report: string
  evidence: Record<string, EvidenceItem>
}) {
  const sections = splitReportSections(report)

  return (
    <div className="mt-4 space-y-4 rounded-xl border bg-card p-6 shadow-md">
      {sections.map((s, i) =>
        i === 0 ? (
          <Section key={s.heading} heading={s.heading} body={s.body} evidence={evidence} />
        ) : (
          <CollapsibleSection key={s.heading} heading={s.heading} body={s.body} evidence={evidence} />
        )
      )}
    </div>
  )
}
