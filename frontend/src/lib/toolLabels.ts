export const TOOL_LABELS: Record<string, string> = {
  tavily: "Tavily (web search)",
  amass: "Amass (life-sciences data)",
  open_targets: "Open Targets",
  pubmed: "PubMed",
  clinicaltrials: "ClinicalTrials.gov",
  genage_drugage: "GenAge / DrugAge",
  run_enrichment: "Enrichment analysis (g:Profiler)",
  extract_genes: "Gene extraction (Nebius)",
}

export function toolLabel(name: string): string {
  return TOOL_LABELS[name] ?? name
}

export const PHASE_LABELS: Record<string, string> = {
  grounding: "Ground Premises",
  plan: "Plan",
  plan_and_gather: "Plan & Gather Evidence",
  revise: "Revise",
  report: "Report",
}

export function phaseLabel(phase: string): string {
  return PHASE_LABELS[phase] ?? phase
}
