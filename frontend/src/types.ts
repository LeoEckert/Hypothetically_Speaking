export interface ToolInfo {
  name: string
  description: string
  enabled: boolean
  key_env_var: string | null
  key_configured: boolean
  paid: boolean
}

export interface AdminKeyInfo {
  name: string
  masked: string | null
  source: "override" | "base" | "unset"
}

export interface AdminUsageSnapshot {
  amass: { rate_configured: boolean; remaining_credits?: number; note?: string }
  anthropic: { rate_configured: boolean; total_usd_last_7d?: number; daily?: Array<{ starting_at: string; usd: number }>; note?: string }
  tavily: { rate_configured: boolean; usd: number | null; calls: number; source: string }
  nebius: { rate_configured: boolean; usd: number | null; calls: number; source: string }
  runs_counted: number
}

export type AdminUsageSource = "local_reports" | "anthropic_usage_api"

export interface AdminUsageDayPoint {
  date: string
  runs: number
  anthropic: { usd: number | null; rate_configured: boolean; source: AdminUsageSource }
  nebius: { usd: number | null; rate_configured: boolean; source: AdminUsageSource }
  tavily: { usd: number | null; rate_configured: boolean; source: AdminUsageSource }
  amass: { credits_used: number }
}

export interface AdminUsageHistory {
  granularity: "day" | "hour"
  days: number | null
  hours: number | null
  start_date: string
  end_date: string
  series: AdminUsageDayPoint[]
  totals: {
    anthropic_usd: number | null
    nebius_usd: number | null
    tavily_usd: number | null
    amass_credits_used: number
    runs: number
  }
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
    // Still keyed "anthropic" for backend/report-JSON compatibility, but this
    // row reports whichever LLM provider the run actually used — `provider`
    // ("anthropic" | "openrouter" | null) is what actually distinguishes them.
    provider: string | null
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

export interface GroundingTriple {
  subject: string
  verb: string
  object: string
}

export interface GroundingPremise extends GroundingTriple {
  statement: string
  status: "ESTABLISHED" | "CONTESTED" | "UNVERIFIED"
  evidence: Array<{
    amass_id: string
    pmid: string | null
    nct_id: string | null
    url: string | null
    how: string
  }>
  absence_checked: string | null
  derived_from: string
}

export interface GroundingHypothesis extends GroundingTriple {
  id: string
  statement: string
  targets: string
  intervention: string
  readout: string
  model_system: string
  falsification?: string
  rationale: string
  supported_by?: string[]
  conflicts_with?: string[]
  missing?: string | null
  dropped?: string | null
  story?: string
}

export type RunMode = "fast" | "normal"

/** About once a second while PLAN / REVISE / REPORT stream their single long reply. */
export interface ProgressEvent {
  type: "progress"
  phase: string
  chars: number
  section?: string | null
  sections_done?: number
  sections_total?: number
  hypotheses?: number
  evidence?: number
  candidates?: number
  tool_calls?: number
}

/** Fired as each grounding stage lands, before the full `grounding` event. */
export interface GroundingStepEvent {
  type: "grounding_step"
  stage: "L0" | "L1" | "L2" | "L4"
  coherent?: boolean
  why?: string
  triples?: GroundingTriple[]
  destination?: string
  links?: GroundingTriple[]
  cut?: number
  link?: GroundingTriple
  status?: GroundingPremise["status"] | "error"
  kept?: number
  rejected?: number
}

export interface GroundingEvent {
  type: "grounding"
  status: "complete" | "skipped" | "failed"
  mode?: RunMode
  coherent: boolean | null
  why: string
  triples: GroundingTriple[]
  destination?: string
  premises: GroundingPremise[]
  knowledge_graph: string
  hypotheses: GroundingHypothesis[]
  rejected?: GroundingHypothesis[]
}

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
  | { type: "phase"; phase: string; detail?: Record<string, number | string> }
  | ProgressEvent
  | GroundingStepEvent
  | GroundingEvent
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
  | { type: "error"; error: string; error_code?: string }
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
  grounding?: GroundingEvent
  groundingSteps?: GroundingStepEvent[]
  phase?: string
  phaseStartedAt?: number
  /** ms timestamp each tool_call step was first seen, keyed by step number —
   * backs the per-step elapsed-time ticker in ToolStepCard. */
  toolStepStartedAt?: Record<number, number>
  progress?: ProgressEvent
  mode?: RunMode
  evaluations?: EvaluationResult[]
}
