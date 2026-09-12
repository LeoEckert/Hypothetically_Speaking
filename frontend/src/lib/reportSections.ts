export interface ReportSection {
  heading: string
  body: string
}

const HEADING_RE = /^##\s+(.+?)\s*$/gm

/** Split the report's '## Heading' sections into heading/body pairs, in
 * order. Never throws — an unexpected shape (e.g. a single-section error
 * report) just comes back as one section. */
export function splitReportSections(report: string): ReportSection[] {
  const text = report || ""
  const matches = [...text.matchAll(HEADING_RE)]
  if (matches.length === 0) {
    return text.trim() ? [{ heading: "Report", body: text.trim() }] : []
  }
  return matches.map((m, i) => {
    const start = (m.index ?? 0) + m[0].length
    const end = i + 1 < matches.length ? (matches[i + 1].index ?? text.length) : text.length
    return { heading: m[1].trim(), body: text.slice(start, end).trim() }
  })
}

function stripMarkdown(line: string): string {
  return line
    .replace(/\[([A-Za-z0-9_:.-]+)\]/g, "")
    .replace(/^#+\s*/, "")
    .replace(/^[-*]\s+/, "")
    .replace(/\*\*([^*]+)\*\*/g, "$1")
    .replace(/\*([^*]+)\*/g, "$1")
    .replace(/`([^`]+)`/g, "$1")
    .replace(/\s+/g, " ")
    .replace(/\s+([.,;:!?])/g, "$1")
    .trim()
}

/** A complete plain-text preview — the first whole sentence (or the whole
 * first bullet/line if it has no sentence-ending punctuation) with markdown
 * and citation syntax stripped. Never a mid-word/mid-sentence fragment; no
 * character cap, no ellipsis. */
export function teaser(body: string): string {
  const firstLine = body.split("\n").map(stripMarkdown).find((l) => l.length > 0) ?? ""
  const sentenceMatch = firstLine.match(/^.*?[.!?](?=\s|$)/)
  return sentenceMatch ? sentenceMatch[0].trim() : firstLine
}
