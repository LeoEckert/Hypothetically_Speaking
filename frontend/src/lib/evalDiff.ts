import { diffWordsWithSpace } from "diff"
import { splitReportSections } from "@/lib/reportSections"
import type { ChangeLogEntry, EvaluationResult, SectionCritique } from "@/types"

/** Above `REWRITTEN_MIN` of the wording moved, the reviser rewrote the
 * section wholesale: word-level highlighting there marks nearly every word
 * and reads as confetti, so both versions render clean instead. Anything
 * below it — down to a single word — is highlighted, never rounded off to
 * "unchanged". A section counts as unchanged only when the diff is empty. */
const REWRITTEN_MIN = 0.6

export type SectionStatus = "unchanged" | "revised" | "rewritten"

export interface DiffPart {
  value: string
  added?: boolean
  removed?: boolean
}

export interface SectionPair {
  /** Rubric section id, e.g. `evidence_for`. */
  section: string
  /** Section heading — identical to the report's `##` heading (backend
   * RUBRIC keeps `title` and `report_heading` in sync; see
   * backend/agent/evaluate.py). */
  title: string
  /** Raw markdown, rendered as-is when the section is unchanged or wholly
   * rewritten. */
  original: string
  revised: string
  /** Markdown flattened to prose — what the word diff actually compares. */
  originalText: string
  revisedText: string
  status: SectionStatus
  /** Word-level diff of the normalised text. Empty unless `status` is
   * `"revised"` — the other two statuses render plain markdown. */
  parts: DiffPart[]
  changeRatio: number
  critique?: SectionCritique
  changeLog?: ChangeLogEntry
}

/** Flatten markdown to plain text so a word diff compares prose rather than
 * syntax — an added `**` around an unchanged clause should not read as a
 * change. Line structure and list markers survive; the rendered diff is
 * whitespace-preserving, so numbered failure modes still look like a list.
 * Citation markers (`[PMID:123]`) are left intact for the renderer to
 * resolve, and bullet markers become real bullets so a flattened list still
 * reads as one. */
export function normalizeDashes(text: string): string {
  // The reviser writes ASCII `--` where the report uses a real em dash.
  // Left alone, every dash in the section reads as an edit and buries the
  // changes that matter — and the two spellings sit side by side on screen.
  return (text || "").replace(/(\s)--(\s)/g, "$1—$2")
}

export function toPlainText(markdown: string): string {
  return normalizeDashes(markdown || "")
    .replace(/^#{1,6}\s+/gm, "")
    .replace(/^\s*[-*]\s+/gm, "• ")
    .replace(/\*\*([^*]+)\*\*/g, "$1")
    .replace(/(?<!\*)\*([^*\n]+)\*(?!\*)/g, "$1")
    .replace(/`([^`]+)`/g, "$1")
    .replace(/[ \t]+$/gm, "")
    .trim()
}

function wordCount(text: string): number {
  return text.split(/\s+/).filter(Boolean).length
}

export function classifyDiff(parts: DiffPart[]): { status: SectionStatus; changeRatio: number } {
  let changed = 0
  let total = 0
  for (const p of parts) {
    const n = wordCount(p.value)
    total += n
    if (p.added || p.removed) changed += n
  }
  const changeRatio = total === 0 ? 0 : changed / total
  if (changed === 0) return { status: "unchanged", changeRatio }
  if (changeRatio >= REWRITTEN_MIN) return { status: "rewritten", changeRatio }
  return { status: "revised", changeRatio }
}

/** Pair every critiqued section's original report text with its revised text,
 * word-diff the pair, and attach that section's critique and change-log entry
 * so both render next to the text they describe rather than in a footer. */
export function buildSectionPairs(
  evaluation: EvaluationResult,
  report: string
): SectionPair[] {
  const originalByHeading = new Map(
    splitReportSections(report).map((s) => [s.heading, s.body])
  )
  const changeLogBySection = new Map(
    evaluation.revised.change_log.map((c) => [c.section, c])
  )

  return evaluation.critiques.map((critique) => {
    const original = (originalByHeading.get(critique.title) ?? "").trim()
    const revised = (evaluation.revised.sections[critique.section] ?? "").trim()
    const originalText = toPlainText(original)
    const revisedText = toPlainText(revised)
    const parts: DiffPart[] = diffWordsWithSpace(originalText, revisedText)
    const { status, changeRatio } = classifyDiff(parts)
    return {
      section: critique.section,
      title: critique.title,
      original,
      revised,
      originalText,
      revisedText,
      status,
      parts: status === "revised" ? parts : [],
      changeRatio,
      critique,
      changeLog: changeLogBySection.get(critique.section),
    }
  })
}
