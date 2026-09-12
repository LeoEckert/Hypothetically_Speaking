import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from "@/components/ui/accordion"

const PHASES = [
  {
    title: "Plan",
    body: "Claude reads your question and proposes 2–4 candidate hypotheses, deciding which tools to check each against.",
  },
  {
    title: "Retrieve",
    body: "It calls live tools in a loop: literature, curated ageing databases, target–disease evidence, trial status.",
  },
  {
    title: "Compute",
    body: "It extracts a gene/protein set from the evidence and runs a real statistical gene/pathway enrichment analysis against it.",
  },
  {
    title: "Revise",
    body: "It critiques its own hypothesis ranking against all the combined evidence.",
  },
  {
    title: "Report",
    body: "A cited markdown report: hypothesis, evidence for/against, confidence, failure modes, and the next experiment, with every claim traceable to a source.",
  },
]

export function HowItWorksPanel() {
  return (
    <div className="border rounded-lg p-3 bg-card shadow-sm">
      <p className="text-sm font-semibold mb-2">How it works</p>
      <Accordion type="single" collapsible>
        {PHASES.map((phase, idx) => (
          <AccordionItem key={phase.title} value={`phase-${idx}`}>
            <AccordionTrigger className="text-sm">{phase.title}</AccordionTrigger>
            <AccordionContent className="text-xs text-muted-foreground">{phase.body}</AccordionContent>
          </AccordionItem>
        ))}
      </Accordion>
    </div>
  )
}
