import { useMemo, useState } from "react"
import { Badge } from "@/components/ui/badge"
import { toolLabel } from "@/lib/toolLabels"
import type { EvidenceItem } from "@/types"

export function EvidencePanel({ evidence }: { evidence: Record<string, EvidenceItem> }) {
  const [filter, setFilter] = useState("")

  const grouped = useMemo(() => {
    const q = filter.trim().toLowerCase()
    const bySource = new Map<string, EvidenceItem[]>()
    for (const item of Object.values(evidence)) {
      if (q && !item.title.toLowerCase().includes(q) && !item.summary.toLowerCase().includes(q) && !item.id.toLowerCase().includes(q)) {
        continue
      }
      const list = bySource.get(item.source) ?? []
      list.push(item)
      bySource.set(item.source, list)
    }
    return [...bySource.entries()].sort(([a], [b]) => a.localeCompare(b))
  }, [evidence, filter])

  const total = Object.keys(evidence).length

  return (
    <div className="space-y-3">
      <input
        value={filter}
        onChange={(e) => setFilter(e.target.value)}
        placeholder={`Filter ${total} evidence item${total === 1 ? "" : "s"}…`}
        className="w-full rounded-md border border-input bg-transparent px-3 py-1.5 text-sm"
      />
      {grouped.length === 0 && <p className="text-sm text-muted-foreground">No evidence matches "{filter}".</p>}
      {grouped.map(([source, items]) => (
        <div key={source}>
          <p className="text-xs font-semibold text-muted-foreground mb-1 flex items-center gap-2">
            {toolLabel(source)}
            <Badge variant="outline" className="text-[10px]">
              {items.length}
            </Badge>
          </p>
          <ul className="space-y-1">
            {items.map((item) => (
              <li key={item.id} className="text-sm leading-snug flex items-baseline gap-1.5">
                <code className="font-mono text-[10px] text-muted-foreground shrink-0">[{item.id}]</code>
                <a href={item.url || undefined} target="_blank" rel="noreferrer" className="hover:underline">
                  {item.title || item.summary.slice(0, 80)}
                </a>
              </li>
            ))}
          </ul>
        </div>
      ))}
    </div>
  )
}
