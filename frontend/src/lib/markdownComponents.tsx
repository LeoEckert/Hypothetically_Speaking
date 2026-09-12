import type { JSX, ReactNode } from "react"
import type { Components } from "react-markdown"
import { withCitations } from "@/lib/citations"
import type { EvidenceItem } from "@/types"

export function buildComponents(evidence: Record<string, EvidenceItem>): Components {
  let counter = 0
  const cited =
    (Tag: keyof JSX.IntrinsicElements, className?: string) =>
    ({ children }: { children?: ReactNode }) => {
      const key = `md-${counter++}`
      return <Tag className={className}>{withCitations(children, evidence, key)}</Tag>
    }

  return {
    h2: cited("h2", "text-lg font-semibold mt-5 mb-1.5 pb-1 border-b first:mt-0"),
    h3: cited("h3", "text-base font-semibold mt-4 mb-1"),
    p: cited("p", "text-sm leading-relaxed mb-2"),
    li: cited("li", "text-sm leading-relaxed"),
    strong: cited("strong", "font-semibold"),
    em: cited("em", "italic"),
    ul: ({ children }) => <ul className="list-disc pl-5 space-y-0.5 mb-2">{children}</ul>,
    ol: ({ children }) => <ol className="list-decimal pl-5 space-y-0.5 mb-2">{children}</ol>,
    blockquote: ({ children }) => (
      <blockquote className="border-l-2 border-muted-foreground/30 pl-3 italic text-muted-foreground">
        {children}
      </blockquote>
    ),
    code: ({ children }) => <code className="font-mono text-xs bg-muted px-1 py-0.5 rounded">{children}</code>,
    hr: () => <hr className="my-3 border-border" />,
  }
}
