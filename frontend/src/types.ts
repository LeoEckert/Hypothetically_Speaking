export interface ToolInfo {
  name: string
  description: string
  enabled: boolean
}

export interface EvidenceItem {
  id: string
  source: string
  url: string
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
  | { type: "error"; error: string }
  | {
      type: "done"
      report: string
      partial: boolean
      run_id: string
      cost: CostSummary
      evidence: Record<string, EvidenceItem>
    }
  | { type: "stream_end" }

export type RunStatus = "running" | "done" | "partial" | "error"

export interface RunRecord {
  id: string
  question: string
  createdAt: number
  status: RunStatus
  events: SseEvent[]
  parentId: string | null
  cost?: CostSummary
  evidence?: Record<string, EvidenceItem>
}
