// Tool errors carry raw exception text (httpx/requests reprs, full URLs,
// MDN links). Good for debugging, bad to show as the primary UI text —
// this extracts a short, human-readable summary and keeps the raw text
// available separately for anyone who wants it.

const PATTERNS: Array<[RegExp, (m: RegExpMatchArray) => string]> = [
  [/'(\d{3}) ([^']+)' for url '([^']+)'/, (m) => `${m[1]} ${m[2]} from ${new URL(m[3]).hostname}`],
  [/timed out|timeout/i, () => "Timed out"],
  [/Connection (refused|reset|error)/i, () => "Connection failed"],
  [/Name or service not known|nodename nor servname/i, () => "Host unreachable"],
]

export function humanizeError(raw: string): string {
  for (const [pattern, format] of PATTERNS) {
    const match = raw.match(pattern)
    if (match) return format(match)
  }
  // Fall back to the first sentence/clause, capped, rather than a full dump.
  const firstClause = raw.split(/[;.]\s/)[0]
  return firstClause.length > 100 ? firstClause.slice(0, 99) + "…" : firstClause
}
