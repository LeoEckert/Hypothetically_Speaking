// Every tool that returns multiple evidence items formats its summary as
// one "[citation-id] description" line per item (see backend/tools/*.py's
// shared `"\n".join(f"[{it['id']}] {it['summary']}" ...)` pattern). Parse
// that into a list to render as compact rows instead of one dense
// wrapped paragraph — falls back to null (render as plain text) for
// anything that doesn't match, e.g. single-line "No results for X."
export interface SummaryLine {
  id: string
  text: string
}

const LINE_RE = /^\[([^\]]+)\]\s*(.*)$/

export function parseSummaryLines(summary: string): SummaryLine[] | null {
  const lines = summary.split("\n").filter((l) => l.trim())
  if (lines.length < 1) return null
  const parsed: SummaryLine[] = []
  for (const line of lines) {
    const match = line.match(LINE_RE)
    if (!match) return null
    parsed.push({ id: match[1], text: match[2] })
  }
  return parsed
}
