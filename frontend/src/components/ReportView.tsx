import ReactMarkdown from "react-markdown"
import remarkGfm from "remark-gfm"
import { buildComponents } from "@/lib/markdownComponents"
import type { EvidenceItem } from "@/types"

export function ReportView({
  report,
  evidence,
}: {
  report: string
  evidence: Record<string, EvidenceItem>
}) {
  return (
    <div className="mt-4 p-6 border rounded-xl shadow-md bg-card">
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={buildComponents(evidence)}>
        {report}
      </ReactMarkdown>
    </div>
  )
}
