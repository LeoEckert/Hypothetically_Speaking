export interface ToolInfo {
  name: string
  description: string
  enabled: boolean
}

export interface EvidenceItem {
  id: string
  source: string
  url: string
  title: string
  summary: string
  raw: Record<string, unknown>
}

export interface ProviderCost {
  calls?: number
  usd: number | null
  rate_configured: boolean
  [key: string]: unknown
}

export interface CostSummary {
  anthropic: ProviderCost & {
    model: string
    input_tokens: number
    output_tokens: number
    cache_creation_input_tokens: number
    cache_read_input_tokens: number
  }
  nebius: ProviderCost & { prompt_tokens: number; completion_tokens: number }
  amass: ProviderCost & {
    live_calls: number
    mock_calls: number
    credits_before: number | null
    credits_after: number | null
    credits_used: number | null
    note: string
  }
  tavily: ProviderCost & { live_calls: number; mock_calls: number }
  free_tools: Record<string, { calls: number }>
  total_usd: number
  total_usd_is_partial: boolean
  unpriced_components: string[]
}

export type HypothesisConfidence = "high" | "medium" | "low"

// `id` is assigned once at PLAN and never renumbered at REVISE/REPORT —
// keep components keyed on it, not on `rank`, which changes every stage.
// At the PLAN stage, confidence/rationale/selected/evidence_ids/
// contradicting_ids are always present but "empty" (null/""/false/[]) —
// nothing has been evidenced yet. Never fabricate a rating for them.
export interface RankedHypothesis {
  id: string
  rank: number
  statement: string
  confidence: HypothesisConfidence | null
  rationale: string
  selected: boolean
  evidence_ids: string[]
  contradicting_ids: string[]
  seed_question: string
}

export type HypothesisStage = "plan" | "revise" | "final"

export interface EvaluationFinding {
  criterion: string
  problem: string
  why_it_matters: string
  evidence: string
  suggestion: string
}

export interface SectionCritique {
  section: string
  title: string
  source: "human" | "llm"
  critique: string
  findings: EvaluationFinding[]
}

export interface ChangeLogEntry {
  section: string
  what_changed: string
  why: string
}

export interface RevisedHypothesis {
  statement: string
  confidence: HypothesisConfidence
  confidence_reason: string
  sections: Record<string, string>
  change_log: ChangeLogEntry[]
  unresolved: string[]
}

export interface EvaluationResult {
  hypothesis_id: string
  comment: string
  model: string
  critiques: SectionCritique[]
  revised: RevisedHypothesis
  cost: { usd: number | null; rate_configured: boolean; input_tokens: number; output_tokens: number }
  created_at: string
}

export type SseEvent =
  | { type: "start"; run_id: string; question: string }
  | { type: "phase"; phase: string }
  | { type: "assistant_text"; text: string }
  | { type: "tool_call"; tool: string; args: Record<string, unknown>; step: number }
  | {
      type: "tool_result"
      tool: string
      step: number
      mock: boolean
      error: string | null
      summary: string
      usage: { prompt_tokens: number; completion_tokens: number } | null
    }
  | { type: "hypotheses"; stage: HypothesisStage; hypotheses: RankedHypothesis[] }
  | { type: "error"; error: string }
  | {
      type: "done"
      report: string
      partial: boolean
      cancelled: boolean
      run_id: string
      cost: CostSummary
      evidence: Record<string, EvidenceItem>
      hypotheses: RankedHypothesis[]
    }
  | { type: "stream_end" }

export type RunStatus = "running" | "cancelling" | "done" | "partial" | "cancelled" | "error"

export interface RunRecord {
  id: string
  question: string
  createdAt: number
  status: RunStatus
  events: SseEvent[]
  parentId: string | null
  cost?: CostSummary
  evidence?: Record<string, EvidenceItem>
  hypotheses?: RankedHypothesis[]
  evaluations?: EvaluationResult[]
}
