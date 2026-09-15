import type { GroundingEvent, GroundingHypothesis, GroundingPremise, GroundingTriple } from "@/types"

/** The knowledge trajectory of one run, rebuilt in the browser from the
 * `grounding` event the backend already streams and the run store already
 * persists. This is the same graph `backend/kgviz/graph.py` loads from
 * `runs/knowledge.db` — same node ids (`backend/grounding/domain.py`'s
 * `premise_id`/`concept_id`/`hypothesis_id`), same edge kinds, same virtual
 * subject/object/tested_by links, same deterministic BFS/DFS walk — minus
 * what only a persistent database can hold: other runs of the same question
 * and each link's verdict history. On a stateless serverless deployment
 * that database never exists, so this is what can be shown there. */

export type NodeKind = "question" | "premise" | "hypothesis" | "concept" | "record"
export type WalkMode = "bfs" | "dfs"

export interface TrajectoryNode {
  id: string
  kind: NodeKind
  name: string
  label?: string
  status?: GroundingPremise["status"]
  verb?: string
  subject?: string
  object?: string
  targets?: string
  dropped?: string | null
  evidenceCount?: number
  absenceChecked?: string | null
  intervention?: string
  readout?: string
  modelSystem?: string
  falsification?: string
}

export interface TrajectoryEdge {
  src: string
  dst: string
  kind: string
  virtual: boolean
}

export interface TrajectoryGraph {
  seed: string
  destination: string
  nodes: TrajectoryNode[]
  edges: TrajectoryEdge[]
}

export interface Visit {
  id: string
  depth: number
  order: number
}

export interface Walk {
  visited: Visit[]
  tree: Array<{ src: string; dst: string; kind: string }>
}

export const QUESTION_ID = "Q"
export const KIND_RANK: Record<NodeKind, number> = { question: 0, premise: 1, hypothesis: 2, concept: 3, record: 4 }

const fold = (value: string) => value.trim().toLowerCase()

export function conceptId(name: string): string {
  return "C:" + name.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "")
}

export function premiseId(triple: GroundingTriple): string {
  return "E:" + [triple.subject, triple.verb, triple.object].map(fold).join("|")
}

function hypothesisId(hypothesis: GroundingHypothesis): string {
  const base = "H:" + [hypothesis.subject, hypothesis.verb, hypothesis.object].map(fold).join("|")
  return (hypothesis.dropped ? "X:" : "") + base + "|" + hypothesis.statement.toLowerCase()
}

function recordLabel(evidence: GroundingPremise["evidence"][number]): string {
  return evidence.pmid ? `PMID:${evidence.pmid}` : evidence.nct_id ? `NCT:${evidence.nct_id}` : evidence.amass_id
}

export function buildGraph(grounding: GroundingEvent, question: string): TrajectoryGraph {
  const nodes = new Map<string, TrajectoryNode>()
  const edges: TrajectoryEdge[] = []
  const seen = new Set<string>()
  const edge = (src: string, dst: string, kind: string, virtual = false) => {
    const key = `${src}\t${dst}\t${kind}`
    if (seen.has(key)) return
    seen.add(key)
    edges.push({ src, dst, kind, virtual })
  }
  const put = (node: TrajectoryNode) => {
    if (!nodes.has(node.id)) nodes.set(node.id, node)
  }

  put({ id: QUESTION_ID, kind: "question", name: question })

  for (const premise of grounding.premises) {
    const id = premiseId(premise)
    const subject = conceptId(premise.subject)
    const object = conceptId(premise.object)
    put({ id: subject, kind: "concept", name: premise.subject })
    put({ id: object, kind: "concept", name: premise.object })
    put({
      id,
      kind: "premise",
      name: premise.statement,
      status: premise.status,
      verb: premise.verb,
      subject: premise.subject,
      object: premise.object,
      evidenceCount: premise.evidence.length,
      absenceChecked: premise.absence_checked,
    })
    edge(subject, object, premise.verb)
    edge(QUESTION_ID, id, "asks")
    for (const record of premise.evidence) {
      const recordId = `R:${record.amass_id}`
      put({ id: recordId, kind: "record", name: recordLabel(record) })
      edge(id, recordId, "evidence")
    }
    edge(id, subject, "subject", true)
    edge(id, object, "object", true)
  }

  for (const hypothesis of [...grounding.hypotheses, ...(grounding.rejected ?? [])]) {
    const id = hypothesisId(hypothesis)
    put({
      id,
      kind: "hypothesis",
      name: hypothesis.statement,
      label: hypothesis.id,
      targets: hypothesis.targets,
      dropped: hypothesis.dropped ?? null,
      intervention: hypothesis.intervention,
      readout: hypothesis.readout,
      modelSystem: hypothesis.model_system,
      falsification: hypothesis.falsification,
    })
    if (nodes.has(hypothesis.targets)) {
      edge(id, hypothesis.targets, "tests")
      edge(hypothesis.targets, id, "tested_by", true)
    }
  }

  return { seed: QUESTION_ID, destination: grounding.destination ?? "", nodes: [...nodes.values()], edges }
}

function adjacency(graph: TrajectoryGraph, includeRecords: boolean): Map<string, Array<[string, string]>> {
  const kinds = new Map(graph.nodes.map((node) => [node.id, node.kind]))
  const adj = new Map<string, Array<[string, string]>>()
  for (const e of graph.edges) {
    if (!includeRecords && (kinds.get(e.src) === "record" || kinds.get(e.dst) === "record")) continue
    if (!adj.has(e.src)) adj.set(e.src, [])
    adj.get(e.src)!.push([e.dst, e.kind])
  }
  const rank = (id: string) => KIND_RANK[kinds.get(id) ?? "record"] ?? 9
  for (const neighbours of adj.values()) {
    // Sorted neighbours make the visit order a function of the graph alone.
    neighbours.sort((a, b) => rank(a[0]) - rank(b[0]) || a[0].localeCompare(b[0]) || a[1].localeCompare(b[1]))
  }
  return adj
}

export function walk(graph: TrajectoryGraph, mode: WalkMode, depth: number, includeRecords: boolean): Walk {
  const adj = adjacency(graph, includeRecords)
  const visited: Visit[] = []
  const tree: Walk["tree"] = []
  const seen = new Set<string>([graph.seed])

  if (mode === "bfs") {
    const queue: Array<[string, number]> = [[graph.seed, 0]]
    while (queue.length) {
      const [id, at] = queue.shift()!
      visited.push({ id, depth: at, order: visited.length })
      if (at >= depth) continue
      for (const [neighbour, kind] of adj.get(id) ?? []) {
        if (seen.has(neighbour)) continue
        seen.add(neighbour)
        tree.push({ src: id, dst: neighbour, kind })
        queue.push([neighbour, at + 1])
      }
    }
    return { visited, tree }
  }

  const dfs = (id: string, at: number) => {
    visited.push({ id, depth: at, order: visited.length })
    if (at >= depth) return
    for (const [neighbour, kind] of adj.get(id) ?? []) {
      if (seen.has(neighbour)) continue
      seen.add(neighbour)
      tree.push({ src: id, dst: neighbour, kind })
      dfs(neighbour, at + 1)
    }
  }
  dfs(graph.seed, 0)
  return { visited, tree }
}

export interface Layout {
  positions: Map<string, { x: number; y: number }>
  width: number
  height: number
}

/** Columns by BFS distance from the question, rows evenly spaced — the
 * question on the left, its premises next, then the entities and
 * hypotheses they touch, records last. */
export function layout(graph: TrajectoryGraph, visibleIds: string[], includeRecords: boolean, width: number): Layout {
  const depthOf = new Map(walk(graph, "bfs", 32, includeRecords).visited.map((v) => [v.id, v.depth]))
  const kinds = new Map(graph.nodes.map((node) => [node.id, node.kind]))
  const layers = new Map<number, string[]>()
  for (const id of visibleIds) {
    const depth = depthOf.get(id) ?? 0
    if (!layers.has(depth)) layers.set(depth, [])
    layers.get(depth)!.push(id)
  }
  const depths = [...layers.keys()].sort((a, b) => a - b)
  const tallest = Math.max(1, ...[...layers.values()].map((ids) => ids.length))
  const height = Math.max(360, tallest * 34 + 80)
  const padX = 24
  const padY = 40
  const rank = (id: string) => KIND_RANK[kinds.get(id) ?? "record"] ?? 9
  const positions = new Map<string, { x: number; y: number }>()
  depths.forEach((depth, column) => {
    const ids = layers.get(depth)!.sort((a, b) => rank(a) - rank(b) || a.localeCompare(b))
    // Leave room on the right for the last column's text labels.
    const x = padX + (column * (width - padX - 270)) / Math.max(depths.length - 1, 1)
    ids.forEach((id, row) => {
      positions.set(id, { x, y: padY + ((row + 0.5) * (height - padY * 2)) / ids.length })
    })
  })
  return { positions, width, height }
}
