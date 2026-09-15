import { useEffect, useMemo, useRef, useState } from "react"
import type { GroundingEvent, GroundingStepEvent } from "@/types"
import {
  buildGraph,
  layout,
  walk,
  type NodeKind,
  type TrajectoryNode,
  type WalkMode,
} from "@/lib/trajectory"

const NODE_COLOR: Record<Exclude<NodeKind, "premise">, string> = {
  question: "text-sky-800 dark:text-sky-300",
  concept: "text-stone-600 dark:text-stone-300",
  hypothesis: "text-violet-700 dark:text-violet-300",
  record: "text-muted-foreground",
}
const STATUS_COLOR = {
  ESTABLISHED: "text-green-700 dark:text-green-300",
  CONTESTED: "text-amber-700 dark:text-amber-300",
  UNVERIFIED: "text-primary",
}

function colorOf(node: TrajectoryNode): string {
  if (node.kind === "premise") return STATUS_COLOR[node.status ?? "UNVERIFIED"]
  return NODE_COLOR[node.kind]
}

function clip(text: string | undefined | null, n: number): string {
  if (!text) return ""
  return text.length > n ? text.slice(0, n - 1) + "…" : text
}

const FIELD =
  "rounded-md border bg-background px-2 py-1 text-xs text-foreground"

export function KnowledgeTrajectory({
  grounding,
  question,
  steps = [],
}: {
  grounding: GroundingEvent
  question: string
  steps?: GroundingStepEvent[]
}) {
  const [mode, setMode] = useState<WalkMode>("bfs")
  const [depth, setDepth] = useState(3)
  const [showRecords, setShowRecords] = useState(false)
  const [focus, setFocus] = useState<string | null>(null)
  const frame = useRef<HTMLDivElement>(null)
  const [width, setWidth] = useState(900)

  useEffect(() => {
    const el = frame.current
    if (!el) return
    const observer = new ResizeObserver(([entry]) => setWidth(Math.max(560, Math.floor(entry.contentRect.width))))
    observer.observe(el)
    return () => observer.disconnect()
  }, [])

  const graph = useMemo(() => buildGraph(grounding, question), [grounding, question])
  const activation = useMemo(() => walk(graph, mode, depth, showRecords), [graph, mode, depth, showRecords])
  const active = useMemo(() => new Set(activation.visited.map((v) => v.id)), [activation])
  const treeKeys = useMemo(() => new Set(activation.tree.map((e) => `${e.src}\t${e.dst}\t${e.kind}`)), [activation])

  const byId = useMemo(() => new Map(graph.nodes.map((node) => [node.id, node])), [graph])
  const visible = useMemo(
    () => graph.nodes.filter((node) => showRecords || node.kind !== "record"),
    [graph, showRecords]
  )
  const visibleIds = useMemo(() => new Set(visible.map((node) => node.id)), [visible])
  const { positions, height } = useMemo(
    () => layout(graph, [...visibleIds], showRecords, width),
    [graph, visibleIds, showRecords, width]
  )
  const edges = graph.edges.filter((e) => visibleIds.has(e.src) && visibleIds.has(e.dst))
  const destination = graph.destination.toLowerCase()

  const l0 = steps.find((s) => s.stage === "L0")
  const l1 = steps.find((s) => s.stage === "L1")
  const verdictWhy = new Map<string, string>()
  for (const step of steps) {
    if (step.stage === "L2" && step.link && step.why) {
      verdictWhy.set(`${step.link.subject}|${step.link.object}`.toLowerCase(), step.why)
    }
  }

  const premises = graph.nodes.filter((node) => node.kind === "premise")
  const hypotheses = graph.nodes.filter((node) => node.kind === "hypothesis")
  const kept = hypotheses.filter((h) => !h.dropped)
  const rejected = hypotheses.filter((h) => h.dropped)

  let n = 0
  const next = () => String(n++).padStart(2, "0")

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-end gap-3 text-xs">
        <p className="mr-auto text-muted-foreground">
          Activated walk over this run&apos;s premise graph. Same question, same path. Hover a step to find it in the graph.
        </p>
        <label className="flex flex-col gap-1 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
          Walk
          <select className={FIELD} value={mode} onChange={(e) => setMode(e.target.value as WalkMode)}>
            <option value="bfs">bfs</option>
            <option value="dfs">dfs</option>
          </select>
        </label>
        <label className="flex flex-col gap-1 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
          Depth
          <input
            className={`${FIELD} w-16`}
            type="number"
            min={0}
            max={8}
            value={depth}
            onChange={(e) => setDepth(Math.max(0, Math.min(8, Number(e.target.value) || 0)))}
          />
        </label>
        <label className="flex flex-col gap-1 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
          Records
          <select className={FIELD} value={showRecords ? "1" : "0"} onChange={(e) => setShowRecords(e.target.value === "1")}>
            <option value="0">hide</option>
            <option value="1">show</option>
          </select>
        </label>
      </div>

      <div className="flex flex-wrap gap-x-3 gap-y-1 text-[11px] text-muted-foreground">
        <LegendDot className={NODE_COLOR.question}>question</LegendDot>
        <LegendDot className={NODE_COLOR.concept}>entity</LegendDot>
        <LegendDot className={NODE_COLOR.concept} thick>destination (outcome asked about)</LegendDot>
        <LegendDot className={STATUS_COLOR.ESTABLISHED}>established link</LegendDot>
        <LegendDot className={STATUS_COLOR.CONTESTED}>contested link</LegendDot>
        <LegendDot className={STATUS_COLOR.UNVERIFIED}>unverified link</LegendDot>
        <LegendDot className={NODE_COLOR.hypothesis}>hypothesis kept</LegendDot>
        <LegendDot className={NODE_COLOR.hypothesis} dashed>hypothesis rejected</LegendDot>
        <LegendDot className="text-muted-foreground/50">outside this walk</LegendDot>
      </div>

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_320px]">
        <div ref={frame} className="min-w-0 self-start overflow-x-auto rounded-lg border bg-background">
          <svg viewBox={`0 0 ${width} ${height}`} width={width} height={height} className="block max-w-full" role="img" aria-label="Knowledge trajectory graph">
            {edges.map((e) => {
              const a = positions.get(e.src)
              const b = positions.get(e.dst)
              if (!a || !b) return null
              const midX = (a.x + b.x) / 2
              const on = active.has(e.src) && active.has(e.dst)
              const tree = treeKeys.has(`${e.src}\t${e.dst}\t${e.kind}`)
              const src = byId.get(e.src)
              return (
                <g key={`${e.src}-${e.dst}-${e.kind}`} className={on ? "" : "opacity-20"}>
                  <path
                    d={`M ${a.x} ${a.y} C ${midX} ${a.y}, ${midX} ${b.y}, ${b.x} ${b.y}`}
                    fill="none"
                    className={tree ? "stroke-orange-600 dark:stroke-orange-400" : "stroke-border"}
                    strokeWidth={tree ? 2 : 1.1}
                  />
                  {/* The premise node stands for the link; its verb rides the edge to the object. */}
                  {e.kind === "object" && src?.verb && (
                    <text x={midX} y={(a.y + b.y) / 2 - 4} textAnchor="middle" className="fill-muted-foreground text-[9px]">
                      {src.verb}
                    </text>
                  )}
                </g>
              )
            })}
            {visible.map((node) => {
              const p = positions.get(node.id)
              if (!p) return null
              const on = active.has(node.id)
              const isRejected = node.kind === "hypothesis" && Boolean(node.dropped)
              const isDestination = node.kind === "concept" && destination !== "" && node.name.toLowerCase() === destination
              const r = node.kind === "question" ? 9 : node.kind === "record" ? 4 : isDestination ? 9 : 7
              const raw = node.kind === "hypothesis" ? (isRejected ? `✕ ${node.name}` : node.label || node.name) : node.name
              // The question sits at the far left with every edge leaving to
              // the right, so its label goes underneath instead of across them.
              const below = node.kind === "question"
              return (
                <g key={node.id} className={`${colorOf(node)} ${on ? "" : "opacity-30"}`}>
                  <circle
                    cx={p.x}
                    cy={p.y}
                    r={r}
                    stroke="currentColor"
                    strokeWidth={focus === node.id || isDestination ? 4 : 2}
                    strokeDasharray={isRejected ? "3 2" : undefined}
                    className={isRejected ? "fill-background" : "fill-card"}
                  />
                  <text
                    x={below ? p.x - r : p.x + 12}
                    y={below ? p.y + r + 14 : p.y + 4}
                    className={`text-[11px] ${on ? "fill-foreground" : "fill-muted-foreground"}`}
                  >
                    {clip(raw, below ? 60 : 36)}
                  </text>
                </g>
              )
            })}
          </svg>
        </div>

        <aside className="min-w-0 text-xs">
          <p className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">Activation path</p>
          <Stage>Question</Stage>
          <Row index={next()} onFocus={setFocus} node={graph.seed} name={question} meta={grounding.destination ? `destination: ${grounding.destination}` : "seed"} />
          <Stage>L0 · split into claims</Stage>
          <Row index={next()} onFocus={setFocus} node={graph.seed}
            name={l0 ? (l0.coherent ? "coherent" : "incoherent") : grounding.coherent ? "coherent" : "incoherent"}
            meta="coherence"
            why={clip(
              [(l0?.why ?? grounding.why), ...grounding.triples.map((t) => `${t.subject} ${t.verb} ${t.object}`)].filter(Boolean).join(" | "),
              260
            )}
          />
          {l1 && (
            <>
              <Stage>L1 · links to check</Stage>
              <Row index={next()} onFocus={setFocus} node={graph.seed}
                name={`${l1.links?.length ?? 0} links`}
                meta="probe"
                why={clip(
                  (l1.links ?? []).map((t) => `${t.subject} ${t.verb} ${t.object}`).join("; ") +
                    (l1.cut ? ` || not checked (over the link cap): ${l1.cut}` : ""),
                  260
                )}
              />
            </>
          )}
          {premises.length > 0 && <Stage>L2 · verdict per link</Stage>}
          {premises.map((p) => (
            <Row
              key={p.id} index={next()} onFocus={setFocus} node={p.id}
              name={p.name}
              meta={
                <>
                  <span className={`font-semibold uppercase ${colorOf(p)}`}>{p.status}</span>
                  {p.evidenceCount ? ` · ${p.evidenceCount} records` : p.absenceChecked ? ` · ${p.absenceChecked}` : ""}
                  {active.has(p.id) ? "" : " · outside walk"}
                </>
              }
              why={clip(verdictWhy.get(`${p.subject}|${p.object}`.toLowerCase()), 260)}
            />
          ))}
          {kept.length > 0 && <Stage>L4 · hypotheses aimed at the gaps</Stage>}
          {kept.map((h) => (
            <Row
              key={h.id} index={next()} onFocus={setFocus} node={h.id}
              name={h.name}
              meta={`${h.label ?? ""} → tests: ${byId.get(h.targets ?? "")?.name ?? h.targets}`}
              why={[
                h.intervention ? `do: ${h.intervention}` : "",
                h.readout ? `measure: ${h.readout}` : "",
                h.modelSystem ? `in: ${h.modelSystem}` : "",
                h.falsification ? `rejected if: ${h.falsification}` : "",
              ]
                .filter(Boolean)
                .join(" · ")}
            />
          ))}
          {rejected.length > 0 && <Stage>L4 · candidates rejected by the testability filter</Stage>}
          {rejected.map((h) => (
            <Row
              key={h.id} index={next()} onFocus={setFocus} node={h.id}
              name={h.name}
              meta={`tests: ${byId.get(h.targets ?? "")?.name ?? h.targets}`}
              why={`rejected: ${h.dropped}`}
              struck
            />
          ))}
        </aside>
      </div>
    </div>
  )
}

function Row({
  index,
  node,
  name,
  meta,
  why,
  struck = false,
  onFocus,
}: {
  index: string
  node: string
  name: string
  meta: React.ReactNode
  why?: string
  struck?: boolean
  onFocus: (id: string | null) => void
}) {
  return (
    <div
      className="grid grid-cols-[28px_1fr] gap-2 border-b py-1.5 hover:bg-muted/40"
      onMouseEnter={() => onFocus(node)}
      onMouseLeave={() => onFocus(null)}
    >
      <div className="font-semibold tabular-nums text-orange-600 dark:text-orange-400">{index}</div>
      <div className="min-w-0">
        <div className={`text-xs font-medium ${struck ? "line-through text-muted-foreground" : ""}`}>{name}</div>
        <div className="text-[11px] text-muted-foreground">{meta}</div>
        {why && <div className="mt-0.5 text-[11px] leading-snug text-muted-foreground">{why}</div>}
      </div>
    </div>
  )
}

function Stage({ children }: { children: React.ReactNode }) {
  return (
    <p className="mt-3 mb-1 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">{children}</p>
  )
}

function LegendDot({
  children,
  className,
  dashed = false,
  thick = false,
}: {
  children: React.ReactNode
  className: string
  dashed?: boolean
  thick?: boolean
}) {
  return (
    <span className={`flex items-center gap-1.5 ${className}`}>
      <span
        className={`inline-block size-2.5 rounded-full border-current ${dashed ? "border-dashed border-2" : thick ? "border-[3px]" : "border-2"}`}
      />
      <span className="text-muted-foreground">{children}</span>
    </span>
  )
}
