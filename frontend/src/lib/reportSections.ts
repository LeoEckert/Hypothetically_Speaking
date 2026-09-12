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

/** Plain-text approximation of "the gist of it" — not a generated summary,
 * just markdown/citation syntax stripped and truncated at a word boundary. */
export function teaser(body: string, maxLen = 180): string {
  const plain = body
    .replace(/\[([A-Za-z0-9_:.-]+)\]/g, "")
    .replace(/^#+\s*/gm, "")
    .replace(/^[-*]\s+/gm, "")
    .replace(/\*\*([^*]+)\*\*/g, "$1")
    .replace(/\*([^*]+)\*/g, "$1")
    .replace(/`([^`]+)`/g, "$1")
    .replace(/\s+/g, " ")
    .replace(/\s+([.,;:!?])/g, "$1")
    .trim()
  if (plain.length <= maxLen) return plain
  const cut = plain.slice(0, maxLen)
  const lastSpace = cut.lastIndexOf(" ")
  return `${cut.slice(0, lastSpace > 40 ? lastSpace : maxLen)}…`
}
