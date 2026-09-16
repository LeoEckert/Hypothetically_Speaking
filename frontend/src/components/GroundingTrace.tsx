import { Badge } from "@/components/ui/badge"
import type {
  GroundingEvent,
  GroundingHypothesis,
  GroundingPremise,
  GroundingStepEvent,
  GroundingTriple,
  RunStatus,
} from "@/types"

/** A premise verdict, or the L2 step outcome when the verifier's reply could
 * not be parsed twice — that link is left out of the graph, not marked as a gap. */
type LinkVerdict = GroundingPremise["status"] | "error"

const STATUS_STYLES: Record<LinkVerdict, string> = {
  ESTABLISHED:
    "border-green-300 bg-green-50 text-green-700 dark:border-green-800 dark:bg-green-950/40 dark:text-green-300",
  CONTESTED:
    "border-amber-300 bg-amber-50 text-amber-700 dark:border-amber-800 dark:bg-amber-950/40 dark:text-amber-300",
  UNVERIFIED: "border-primary/40 bg-primary/5 text-primary",
  error: "border-destructive/40 bg-destructive/5 text-destructive",
}

const STAGES: Array<[GroundingStepEvent["stage"] | "L3", string]> = [
  ["L0", "Split"],
  ["L1", "Probe"],
  ["L2", "Verify"],
  ["L3", "Premises"],
  ["L4", "Hypotheses"],
]

export function StageRail({ active }: { active?: string }) {
  const activeIndex = active ? STAGES.findIndex(([stage]) => stage === active) : STAGES.length
  return (
    <div className="grid grid-cols-5 gap-1" aria-label="Grounding stages L0 through L4">
      {STAGES.map(([layer, label], index) => {
        const done = index < activeIndex
        const current = index === activeIndex
        return (
          <div key={layer} className="relative flex flex-col items-center text-center">
            {index > 0 && <div className={`absolute right-1/2 top-3 h-px w-full ${done || current ? "bg-primary/60" : "bg-border"}`} />}
            <span
              className={`relative z-10 grid size-6 place-items-center rounded-full border bg-card font-mono text-[10px] font-semibold ${
                current ? "border-primary text-primary ring-2 ring-primary/30 animate-pulse" : done ? "border-primary/60" : "text-muted-foreground"
              }`}
            >
              {layer.slice(1)}
            </span>
            <span className={`mt-1 text-[10px] font-medium ${current ? "text-primary" : "text-muted-foreground"}`}>{label}</span>
          </div>
        )
      })}
    </div>
  )
}

function EntityBox({ name, destination }: { name?: string; destination?: string }) {
  // Everything drawn here came out of a model as JSON. One missing key used
  // to take the whole page down to a white screen mid-run, which on this
  // view — the grounding trace — is the most visible thing in the app. Same
  // reasoning as the backend's schema hardening: degrade the one box, never
  // the page.
  const label = name ?? ""
  const isDestination = !!destination && label.toLowerCase() === destination.toLowerCase()
  return (
    <div
      className={`rounded-md border px-3 py-2 text-center text-xs font-medium ${
        isDestination ? "border-primary bg-primary/10 ring-2 ring-primary/30" : "bg-muted/30"
      }`}
      title={isDestination ? "Destination — the outcome your question asks about" : undefined}
    >
      {isDestination && <span className="mb-0.5 block text-[9px] uppercase tracking-wide text-primary">destination</span>}
      {label || <span className="text-muted-foreground">(unnamed)</span>}
    </div>
  )
}

export function TripleGraph({ triple, destination }: { triple: GroundingTriple; destination?: string }) {
  return (
    <div className="grid grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)] items-center gap-2">
      <EntityBox name={triple.subject} destination={destination} />
      <div className="flex min-w-16 flex-col items-center text-primary">
        <span className="max-w-24 text-center text-[10px] font-medium leading-tight">{triple.verb}</span>
        <span className="font-mono text-sm leading-none" aria-hidden="true">
          ──→
        </span>
      </div>
      <EntityBox name={triple.object} destination={destination} />
    </div>
  )
}

function StatusBadge({ status }: { status?: LinkVerdict }) {
  const verdict = status ?? "error"
  return (
    <Badge variant="outline" className={`text-[10px] ${STATUS_STYLES[verdict] ?? ""}`}>
      {verdict === "error" ? "no verdict" : verdict.toLowerCase()}
    </Badge>
  )
}

function evidenceLabel(evidence: GroundingPremise["evidence"][number]): string {
  return evidence.pmid ? `PMID:${evidence.pmid}` : evidence.nct_id ? `NCT:${evidence.nct_id}` : evidence.amass_id
}

function PremiseRow({ premise, destination }: { premise: GroundingPremise; destination?: string }) {
  return (
    <div className="space-y-2 rounded-lg border p-3">
      <div className="flex items-start justify-between gap-2">
        <p className="text-xs font-medium leading-snug">{premise.statement}</p>
        <StatusBadge status={premise.status} />
      </div>
      <TripleGraph triple={premise} destination={destination} />
      {(premise.evidence?.length ?? 0) > 0 && (
        <details className="border-t pt-2">
          <summary className="cursor-pointer text-[10px] text-muted-foreground">
            {premise.evidence?.length ?? 0} records — how each verified the link
          </summary>
          <ul className="mt-1 space-y-1">
            {(premise.evidence ?? []).map((evidence, index) => (
              <li key={evidence.amass_id || `evidence-${index}`} className="text-[10px] text-muted-foreground">
                {evidence.url ? (
                  <a href={evidence.url} target="_blank" rel="noreferrer" className="font-mono hover:underline">
                    {evidenceLabel(evidence)}
                  </a>
                ) : (
                  <span className="font-mono">{evidenceLabel(evidence)}</span>
                )}
                {" — "}
                {evidence.how}
              </li>
            ))}
          </ul>
        </details>
      )}
      {premise.absence_checked && (
        <p className="border-t pt-2 text-[10px] text-muted-foreground">Absence checked: {premise.absence_checked}</p>
      )}
    </div>
  )
}

function HypothesisRow({ hypothesis, destination }: { hypothesis: GroundingHypothesis; destination?: string }) {
  return (
    <div className="space-y-3 rounded-lg border border-primary/30 bg-primary/[0.02] p-3">
      <div className="flex items-start gap-2">
        <Badge variant="outline" className="font-mono text-[10px]">
          {hypothesis.id}
        </Badge>
        <p className="text-xs font-semibold leading-snug">{hypothesis.statement}</p>
      </div>
      <TripleGraph triple={hypothesis} destination={destination} />
      <div className="grid gap-2 text-[10px] sm:grid-cols-3">
        <div className="rounded-md bg-muted/50 p-2">
          <span className="block text-muted-foreground">Intervention</span>
          <span className="font-medium">{hypothesis.intervention}</span>
        </div>
        <div className="rounded-md bg-muted/50 p-2">
          <span className="block text-muted-foreground">Readout</span>
          <span className="font-medium">{hypothesis.readout}</span>
        </div>
        <div className="rounded-md bg-muted/50 p-2">
          <span className="block text-muted-foreground">Model system</span>
          <span className="font-medium">{hypothesis.model_system}</span>
        </div>
      </div>
      {hypothesis.falsification && (
        <p className="text-[10px] leading-relaxed">
          <span className="text-muted-foreground">Rejected if: </span>
          {hypothesis.falsification}
        </p>
      )}
      {hypothesis.story && (
        <details className="border-t pt-2">
          <summary className="cursor-pointer text-[10px] font-medium">From your question to this experiment</summary>
          <p className="mt-1 text-[10px] leading-relaxed text-muted-foreground">{hypothesis.story}</p>
        </details>
      )}
    </div>
  )
}

/**
 * Drawn from the very first grounding event, before any verdict exists: the
 * stage rail lights up, the question's own claims appear as soon as L0
 * lands, every link appears when L1 lands, and each link turns colour as its
 * verdict arrives.
 */
export function GroundingLive({
  steps,
  question,
  status,
}: {
  steps: GroundingStepEvent[]
  question: string
  status: RunStatus
}) {
  if (status !== "running" && steps.length === 0) return null
  const l0 = steps.find((step) => step.stage === "L0")
  const l1 = steps.find((step) => step.stage === "L1")
  const l4 = steps.find((step) => step.stage === "L4")
  const verdicts = new Map<string, LinkVerdict>()
  for (const step of steps) {
    if (step.stage === "L2" && step.link && step.status) {
      verdicts.set(`${step.link.subject}|${step.link.object}`.toLowerCase(), step.status)
    }
  }
  const links = l1?.links ?? []
  const active = l4 ? undefined : links.length > 0 && verdicts.size === links.length ? "L3" : l1 ? "L2" : l0 ? "L1" : "L0"
  const destination = l0?.destination

  return (
    <section className="rounded-xl border bg-card p-4 shadow-sm" aria-live="polite">
      <div className="mb-4">
        <p className="text-sm font-semibold">Grounding the question</p>
        <p className="text-xs text-muted-foreground">
          {active === "L0" && "Splitting the question into its claims…"}
          {active === "L1" && "Expanding the causal chain…"}
          {active === "L2" && `Checking ${links.length} links against the literature — ${verdicts.size}/${links.length} verdicts in…`}
          {active === "L3" && "Assembling the premises…"}
          {!active && "Grounding complete."}
        </p>
      </div>
      <div className="space-y-4">
        <StageRail active={active} />
        <blockquote className="border-l-2 pl-3 text-xs leading-relaxed text-muted-foreground">{question}</blockquote>
        {l0 && (
          <div className="space-y-2">
            <p className="text-xs font-semibold">L0 · Claims stated by the question</p>
            {(l0.triples ?? []).map((triple, index) => (
              <TripleGraph key={`${triple.subject}-${index}`} triple={triple} destination={destination} />
            ))}
            {destination && (
              <p className="text-[10px] text-muted-foreground">
                Destination: <span className="font-medium text-foreground/80">{destination}</span> — hypotheses must end here.
              </p>
            )}
          </div>
        )}
        {links.length > 0 && (
          <div className="space-y-1.5">
            <p className="text-xs font-semibold">L2 · Links being verified</p>
            {links.map((link, index) => {
              const verdict = verdicts.get(`${link.subject}|${link.object}`.toLowerCase())
              return (
                <div key={`${link.subject}-${link.object}-${index}`} className="flex items-center justify-between gap-2 rounded-md border px-3 py-1.5">
                  <span className="text-xs">
                    {link.subject} <span className="text-primary">─{link.verb}→</span> {link.object}
                  </span>
                  {verdict ? (
                    <StatusBadge status={verdict} />
                  ) : (
                    <span className="flex items-center gap-1 text-[10px] text-muted-foreground">
                      <span className="size-2 animate-pulse rounded-full bg-primary/60" /> checking
                    </span>
                  )}
                </div>
              )
            })}
          </div>
        )}
      </div>
    </section>
  )
}

export function GroundingTrace({
  grounding,
  question,
  embedded = false,
}: {
  grounding: GroundingEvent
  question: string
  embedded?: boolean
}) {
  const destination = grounding.destination
  const gaps = grounding.premises.filter((premise) => premise.status === "UNVERIFIED").length
  const content =
    grounding.status !== "complete" ? (
      <div className="rounded-lg border border-dashed p-3 text-xs text-muted-foreground">
        Grounding {grounding.status}: {grounding.why}
      </div>
    ) : !grounding.coherent ? (
      <div className="rounded-lg border border-dashed p-3 text-xs text-muted-foreground">
        No premise graph was generated: {grounding.why}
      </div>
    ) : (
      <div className="space-y-5">
        <StageRail />

        <div className="space-y-2">
          <p className="text-xs font-semibold">L0 · Claims stated by the question</p>
          <blockquote className="border-l-2 pl-3 text-xs leading-relaxed text-muted-foreground">{question}</blockquote>
          {grounding.triples.map((triple, index) => (
            <TripleGraph key={`${triple.subject}-${triple.verb}-${triple.object}-${index}`} triple={triple} destination={destination} />
          ))}
          {destination && (
            <p className="text-[10px] text-muted-foreground">
              Destination (the outcome asked about):{" "}
              <span className="font-medium text-foreground/80">{destination}</span> — hypotheses must end here.
            </p>
          )}
          <details>
            <summary className="cursor-pointer text-[10px] text-muted-foreground">Why the question was judged coherent</summary>
            <p className="mt-1 text-[10px] text-muted-foreground">{grounding.why}</p>
          </details>
        </div>

        {grounding.hypotheses.length > 0 && (
          <div className="space-y-2">
            <div>
              <p className="text-xs font-semibold">L4 · Testable hypotheses</p>
              <p className="text-[10px] text-muted-foreground">
                One per weak link into the destination, each with an intervention, readout, model system and the observation that would reject it.
              </p>
            </div>
            {grounding.hypotheses.map((hypothesis, index) => (
              <HypothesisRow key={hypothesis.id || `hypothesis-${index}`} hypothesis={hypothesis} destination={destination} />
            ))}
          </div>
        )}

        <details className="space-y-2">
          <summary className="cursor-pointer text-xs font-semibold">
            L1–L3 · {grounding.premises.length} links checked · {gaps} unverified
          </summary>
          <div className="mt-2 space-y-2">
            {grounding.premises.map((premise, index) => (
              <PremiseRow key={`${premise.subject}-${premise.verb}-${premise.object}-${index}`} premise={premise} destination={destination} />
            ))}
          </div>
        </details>

        {grounding.rejected && grounding.rejected.length > 0 && (
          <details>
            <summary className="cursor-pointer text-[10px] text-muted-foreground">
              {grounding.rejected.length} candidate(s) rejected by the testability filter
            </summary>
            <div className="mt-1 space-y-1">
              {grounding.rejected.map((hypothesis, index) => (
                <p key={`${hypothesis.statement}-${index}`} className="text-[10px] text-muted-foreground">
                  <span className="line-through">{hypothesis.statement}</span> — {hypothesis.dropped}
                </p>
              ))}
            </div>
          </details>
        )}
      </div>
    )

  if (embedded) return content

  return (
    <section className="rounded-xl border bg-card p-4 shadow-sm" aria-labelledby="grounding-trace-title">
      <div className="mb-4">
        <p id="grounding-trace-title" className="text-sm font-semibold">
          Premise grounding trace
        </p>
        <p className="text-xs text-muted-foreground">
          How the question became the premises used to generate hypotheses{grounding.mode ? ` · ${grounding.mode} mode` : ""}.
        </p>
      </div>
      {content}
    </section>
  )
}
