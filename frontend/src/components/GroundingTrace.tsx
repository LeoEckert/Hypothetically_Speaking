import { Badge } from "@/components/ui/badge"
import type {
  GroundingEvent,
  GroundingHypothesis,
  GroundingPremise,
  GroundingTriple,
} from "@/types"

const STATUS_STYLES: Record<GroundingPremise["status"], string> = {
  ESTABLISHED:
    "border-green-300 bg-green-50 text-green-700 dark:border-green-800 dark:bg-green-950/40 dark:text-green-300",
  CONTESTED:
    "border-amber-300 bg-amber-50 text-amber-700 dark:border-amber-800 dark:bg-amber-950/40 dark:text-amber-300",
  UNVERIFIED: "border-primary/40 bg-primary/5 text-primary",
}

function StageRail() {
  return (
    <div className="grid grid-cols-5 gap-1" aria-label="Grounding stages L0 through L4">
      {[
        ["L0", "Split"],
        ["L1", "Probe"],
        ["L2", "Verify"],
        ["L3", "Premises"],
        ["L4", "Hypotheses"],
      ].map(([layer, label], index) => (
        <div key={layer} className="relative flex flex-col items-center text-center">
          {index > 0 && <div className="absolute right-1/2 top-3 h-px w-full bg-border" />}
          <span className="relative z-10 grid size-6 place-items-center rounded-full border bg-card font-mono text-[10px] font-semibold">
            {layer.slice(1)}
          </span>
          <span className="mt-1 text-[10px] font-medium text-muted-foreground">{label}</span>
        </div>
      ))}
    </div>
  )
}

function TripleGraph({ triple }: { triple: GroundingTriple }) {
  return (
    <div className="grid grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)] items-center gap-2">
      <div className="rounded-md border bg-muted/30 px-3 py-2 text-center text-xs font-medium">
        {triple.subject}
      </div>
      <div className="flex min-w-16 flex-col items-center text-primary">
        <span className="max-w-24 text-center text-[10px] font-medium leading-tight">{triple.verb}</span>
        <span className="font-mono text-sm leading-none" aria-hidden="true">
          ──→
        </span>
      </div>
      <div className="rounded-md border bg-muted/30 px-3 py-2 text-center text-xs font-medium">
        {triple.object}
      </div>
    </div>
  )
}

function PremiseRow({ premise }: { premise: GroundingPremise }) {
  return (
    <div className="space-y-2 rounded-lg border p-3">
      <div className="flex items-start justify-between gap-2">
        <p className="text-xs font-medium leading-snug">{premise.statement}</p>
        <Badge variant="outline" className={`text-[10px] ${STATUS_STYLES[premise.status]}`}>
          {premise.status.toLowerCase()}
        </Badge>
      </div>
      <TripleGraph triple={premise} />
      <p className="text-[10px] text-muted-foreground">
        Derived from: <span className="font-medium text-foreground/70">{premise.derived_from}</span>
      </p>
      {premise.evidence.length > 0 && (
        <ul className="space-y-1 border-t pt-2">
          {premise.evidence.map((evidence) => {
            const label = evidence.pmid
              ? `PMID:${evidence.pmid}`
              : evidence.nct_id
                ? `NCT:${evidence.nct_id}`
                : evidence.amass_id
            return (
              <li key={evidence.amass_id} className="text-[10px] text-muted-foreground">
                {evidence.url ? (
                  <a href={evidence.url} target="_blank" rel="noreferrer" className="font-mono hover:underline">
                    {label}
                  </a>
                ) : (
                  <span className="font-mono">{label}</span>
                )}
                {" — "}
                {evidence.how}
              </li>
            )
          })}
        </ul>
      )}
      {premise.absence_checked && (
        <p className="border-t pt-2 text-[10px] text-muted-foreground">
          Absence checked: {premise.absence_checked}
        </p>
      )}
    </div>
  )
}

function HypothesisRow({ hypothesis }: { hypothesis: GroundingHypothesis }) {
  return (
    <div className="space-y-3 rounded-lg border border-primary/30 bg-primary/[0.02] p-3">
      <div className="flex items-start gap-2">
        <Badge variant="outline" className="font-mono text-[10px]">
          {hypothesis.id}
        </Badge>
        <p className="text-xs font-semibold leading-snug">{hypothesis.statement}</p>
      </div>
      <TripleGraph triple={hypothesis} />
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
      <p className="text-[10px] text-muted-foreground">
        Tests premise: <span className="font-mono">{hypothesis.targets}</span>
        {hypothesis.supported_by && hypothesis.supported_by.length > 0 && (
          <> · rests on {hypothesis.supported_by.length} established link(s)</>
        )}
        {hypothesis.conflicts_with && hypothesis.conflicts_with.length > 0 && (
          <> · {hypothesis.conflicts_with.length} contested neighbour(s)</>
        )}
      </p>
      {hypothesis.missing && (
        <p className="text-[10px] text-muted-foreground">Missing evidence: {hypothesis.missing}</p>
      )}
      {hypothesis.rationale && (
        <p className="border-t pt-2 text-[10px] leading-relaxed text-muted-foreground">
          {hypothesis.rationale}
        </p>
      )}
    </div>
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

        <div>
          <p className="mb-1 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
            Original question
          </p>
          <blockquote className="border-l-2 pl-3 text-xs leading-relaxed text-muted-foreground">
            {question}
          </blockquote>
        </div>

        <div className="space-y-2">
          <div>
            <p className="text-xs font-semibold">L0 · Claims stated by the question</p>
            <p className="text-[10px] text-muted-foreground">{grounding.why}</p>
          </div>
          {grounding.triples.map((triple, index) => (
            <TripleGraph key={`${triple.subject}-${triple.verb}-${triple.object}-${index}`} triple={triple} />
          ))}
          {grounding.destination && (
            <p className="text-[10px] text-muted-foreground">
              Destination (the outcome asked about):{" "}
              <span className="font-medium text-foreground/80">{grounding.destination}</span> — hypotheses must end here.
            </p>
          )}
        </div>

        <div className="space-y-2">
          <div className="flex items-baseline justify-between gap-2">
            <p className="text-xs font-semibold">L1–L3 · Expanded and checked premises</p>
            <span className="text-[10px] text-muted-foreground">
              {grounding.premises.filter((premise) => premise.status === "UNVERIFIED").length} gaps
            </span>
          </div>
          {grounding.premises.map((premise, index) => (
            <PremiseRow
              key={`${premise.subject}-${premise.verb}-${premise.object}-${index}`}
              premise={premise}
            />
          ))}
        </div>

        {grounding.hypotheses.length > 0 && (
          <div className="space-y-2">
            <div>
              <p className="text-xs font-semibold">L4 · Testable hypothesis candidates</p>
              <p className="text-[10px] text-muted-foreground">
                Each candidate targets one weak premise and carries an intervention, readout, and model system.
              </p>
            </div>
            {grounding.hypotheses.map((hypothesis) => (
              <HypothesisRow key={hypothesis.id} hypothesis={hypothesis} />
            ))}
          </div>
        )}

        {grounding.rejected && grounding.rejected.length > 0 && (
          <div className="space-y-1">
            <p className="text-xs font-semibold text-muted-foreground">Rejected candidates</p>
            {grounding.rejected.map((hypothesis, index) => (
              <p key={`${hypothesis.statement}-${index}`} className="text-[10px] text-muted-foreground">
                <span className="line-through">{hypothesis.statement}</span> — {hypothesis.dropped}
              </p>
            ))}
          </div>
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
          How the question became the premises used to generate hypotheses.
        </p>
      </div>
      {content}
    </section>
  )
}
