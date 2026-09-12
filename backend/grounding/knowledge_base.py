"""SQLite knowledge base: nodes, an append-only evidence log, and reasoning.

Four tables, no ORM, no new dependency — `sqlite3` is stdlib:

    nodes         concepts, papers and claims
    edges         mentions (paper -> concept)
    observations  one row per paper that witnessed a concept pair
    steps         one row per judgement about a node, never rewritten
    llm_cache     prompt hash -> response, so identical inputs replay exactly

`observations` is append-only on purpose. Co-occurrence weight is `COUNT(*)`,
never an overwritten counter, which is what lets the graph keep accumulating
across runs while any past run's graph stays reconstructible via `as_of`.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
from pathlib import Path

from backend.grounding.domain import (
    MAX_GAP_CHECKS,
    MIN_BRIDGES,
    BiologicalEntity,
    ConceptPair,
    Evidence,
    Hypothesis,
    Paper,
    Premise,
    ReasoningStep,
    concept_id,
    hypothesis_id,
    paper_id,
    premise_id,
    utcnow,
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS nodes (
    id         TEXT PRIMARY KEY,
    kind       TEXT NOT NULL,
    name       TEXT NOT NULL,
    payload    TEXT NOT NULL DEFAULT '{}',
    first_seen TEXT NOT NULL,
    run_id     TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS edges (
    src        TEXT NOT NULL,
    dst        TEXT NOT NULL,
    kind       TEXT NOT NULL,
    run_id     TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (src, dst, kind)
);
CREATE TABLE IF NOT EXISTS observations (
    paper_node TEXT NOT NULL,
    a_node     TEXT NOT NULL,
    c_node     TEXT NOT NULL,
    run_id     TEXT NOT NULL,
    at         TEXT NOT NULL,
    PRIMARY KEY (paper_node, a_node, c_node)
);
CREATE TABLE IF NOT EXISTS steps (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    node_id     TEXT NOT NULL,
    stage       TEXT NOT NULL,
    verdict     TEXT NOT NULL,
    rationale   TEXT NOT NULL,
    run_id      TEXT NOT NULL,
    at          TEXT NOT NULL,
    prompt_hash TEXT
);
CREATE TABLE IF NOT EXISTS llm_cache (
    prompt_hash TEXT PRIMARY KEY,
    model       TEXT NOT NULL,
    response    TEXT NOT NULL,
    at          TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS steps_node ON steps (node_id);
CREATE INDEX IF NOT EXISTS observations_at ON observations (at);
"""

# Concept pairs with no direct co-occurrence but at least `min_bridges` shared
# neighbours — Swanson's ABC gap. The `co` CTE derives the undirected graph from
# the observation log, optionally as it stood at `as_of`.
#
# `ab.src < bc.dst` canonicalises the pair (reported once, not twice) and
# excludes A == C. The ORDER BY breaks ties on the ids so the LIMIT always cuts
# the same pairs — without it SQLite may reorder equal-bridge pairs freely.
GAP_SQL = """
WITH co AS (
    SELECT a_node AS src, c_node AS dst FROM observations WHERE at <= :as_of
    UNION
    SELECT c_node AS src, a_node AS dst FROM observations WHERE at <= :as_of
)
SELECT ab.src                        AS a_id,
       bc.dst                        AS c_id,
       COUNT(DISTINCT ab.dst)        AS bridges,
       group_concat(DISTINCT ab.dst) AS bridge_ids
FROM co ab
JOIN co bc ON ab.dst = bc.src
WHERE ab.src < bc.dst
  AND NOT EXISTS (
      SELECT 1 FROM co direct
      WHERE direct.src = ab.src AND direct.dst = bc.dst
  )
GROUP BY a_id, c_id
HAVING bridges >= :min_bridges
ORDER BY bridges DESC, a_id, c_id
LIMIT :limit
"""

# One knowledge base per project by default; GROUNDING_KB points a run (or the
# API) at another file, e.g. a fresh one for a clean-room reproducibility check.
DEFAULT_PATH = Path(os.environ.get("GROUNDING_KB", "runs/knowledge.db"))
FOREVER = "9999-12-31"  # ISO timestamps sort lexically, so this means "all evidence"


class SqliteKnowledgeBase:
    """Implements the `KnowledgeBase` port (and `LLMCache` with it)."""

    def __init__(self, path: Path | str = DEFAULT_PATH) -> None:
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        # L2 verifies links in a thread pool; only the cache methods are
        # reached from those threads, and the lock serialises them.
        self.connection = sqlite3.connect(path, check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript(SCHEMA)
        self._lock = threading.Lock()

    # --- nodes -------------------------------------------------------------

    def _upsert_node(self, node_id: str, kind: str, name: str, payload: dict, run_id: str) -> str:
        self.connection.execute(
            "INSERT OR IGNORE INTO nodes (id, kind, name, payload, first_seen, run_id) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (node_id, kind, name, json.dumps(payload), utcnow(), run_id),
        )
        self.connection.commit()
        return node_id

    def upsert_concept(self, entity: BiologicalEntity, run_id: str) -> str:
        return self._upsert_node(
            concept_id(entity.name), "concept", entity.name, {"kind": entity.kind}, run_id
        )

    def upsert_paper(self, paper: Paper, run_id: str) -> str:
        payload = paper.model_dump(exclude={"abstract"})
        return self._upsert_node(paper_id(paper.amass_id), "paper", paper.title, payload, run_id)

    # --- evidence ----------------------------------------------------------

    def link_mentions(self, paper_node: str, concept_node: str, run_id: str) -> None:
        self.connection.execute(
            "INSERT OR IGNORE INTO edges (src, dst, kind, run_id, created_at) "
            "VALUES (?, ?, 'mentions', ?, ?)",
            (paper_node, concept_node, run_id, utcnow()),
        )
        self.connection.commit()

    def observe_co_occurrence(self, paper_node: str, a_node: str, c_node: str, run_id: str) -> None:
        first, second = sorted([a_node, c_node])
        self.connection.execute(
            "INSERT OR IGNORE INTO observations (paper_node, a_node, c_node, run_id, at) "
            "VALUES (?, ?, ?, ?, ?)",
            (paper_node, first, second, run_id, utcnow()),
        )
        self.connection.commit()

    # --- queries -----------------------------------------------------------

    def _entities(self, node_ids: list[str]) -> dict[str, BiologicalEntity]:
        if not node_ids:
            return {}
        placeholders = ",".join("?" * len(node_ids))
        rows = self.connection.execute(
            f"SELECT id, name, payload FROM nodes WHERE id IN ({placeholders})", node_ids
        ).fetchall()
        return {
            row["id"]: BiologicalEntity(
                name=row["name"], kind=json.loads(row["payload"]).get("kind", "pathway")
            )
            for row in rows
        }

    def gap_candidates(
        self,
        limit: int = MAX_GAP_CHECKS,
        min_bridges: int = MIN_BRIDGES,
        as_of: str | None = None,
    ) -> list[ConceptPair]:
        rows = self.connection.execute(
            GAP_SQL, {"as_of": as_of or FOREVER, "min_bridges": min_bridges, "limit": limit}
        ).fetchall()
        wanted = {row[column] for row in rows for column in ("a_id", "c_id")}
        wanted |= {node for row in rows for node in row["bridge_ids"].split(",")}
        entities = self._entities(sorted(wanted))
        pairs = []
        for row in rows:
            # group_concat order is unspecified — sort so the bridge list, which
            # reaches the output, is identical for identical evidence.
            bridge_ids = sorted(node for node in row["bridge_ids"].split(",") if node in entities)
            pairs.append(
                ConceptPair(
                    a=entities[row["a_id"]],
                    c=entities[row["c_id"]],
                    bridges=[entities[node] for node in bridge_ids],
                )
            )
        return pairs

    # --- premises (L0-L3) --------------------------------------------------

    def upsert_premise(self, premise: Premise, question_node: str, run_id: str, why: str, prompt_hash: str | None) -> str:
        """Persist one verified link so a scientist can audit it later.

        Nodes: both entities, the premise itself, every evidence record.
        Edges: subject -verb-> object, premise -evidence-> record,
        question -asks-> premise. One `verify` step per run carries the
        rationale, so re-running the same question appends history rather
        than overwriting the earlier judgement.
        """
        node = premise_id(premise)
        subject = self._upsert_node(concept_id(premise.subject), "concept", premise.subject, {"kind": "entity"}, run_id)
        obj = self._upsert_node(concept_id(premise.object), "concept", premise.object, {"kind": "entity"}, run_id)
        self._upsert_node(node, "premise", premise.statement, premise.model_dump(mode="json"), run_id)
        self._edge(subject, obj, premise.verb, run_id)
        self._edge(question_node, node, "asks", run_id)
        for evidence in premise.evidence:
            record = self._upsert_node(
                f"R:{evidence.amass_id}", "record", evidence.label(), evidence.model_dump(mode="json"), run_id
            )
            self._edge(node, record, "evidence", run_id)
        self.record_step(
            ReasoningStep(
                node_id=node, stage="verify", verdict=premise.status.value, rationale=why,
                run_id=run_id, at=utcnow(), prompt_hash=prompt_hash,
            )
        )
        return node

    def upsert_hypothesis(self, hypothesis: Hypothesis, run_id: str) -> str:
        node = hypothesis_id(hypothesis)
        self._upsert_node(node, "hypothesis", hypothesis.statement, hypothesis.model_dump(mode="json"), run_id)
        self._edge(node, hypothesis.targets, "tests", run_id)
        return node

    def _edge(self, src: str, dst: str, kind: str, run_id: str) -> None:
        self.connection.execute(
            "INSERT OR IGNORE INTO edges (src, dst, kind, run_id, created_at) VALUES (?, ?, ?, ?, ?)",
            (src, dst, kind, run_id, utcnow()),
        )
        self.connection.commit()

    def describe(self) -> str:
        """Everything the base knows, readable: questions, their links, each
        link's verdict history and evidence. The audit view behind the graph."""
        lines: list[str] = []
        questions = self.connection.execute(
            "SELECT id, name FROM nodes WHERE kind = 'question' ORDER BY first_seen"
        ).fetchall()
        for question in questions:
            lines.append(f"Q {question['name']}")
            for step in self.steps_for(question["id"]):
                lines.append(f"    {step.stage}: {step.rationale}")
            premises = self.connection.execute(
                "SELECT n.id, n.name, n.payload FROM edges e JOIN nodes n ON n.id = e.dst "
                "WHERE e.src = ? AND e.kind = 'asks' ORDER BY n.first_seen",
                (question["id"],),
            ).fetchall()
            for premise in premises:
                payload = json.loads(premise["payload"])
                lines.append(f"  - {premise['name']}  [{payload['status']}]")
                for evidence in payload["evidence"]:
                    lines.append(f"        {Evidence(**evidence).label()}  {evidence['how']}")
                if payload.get("absence_checked"):
                    lines.append(f"        absence checked: {payload['absence_checked']}")
                for step in self.steps_for(premise["id"]):
                    lines.append(f"        {step.at[:19]} run {step.run_id} -> {step.verdict}: {step.rationale}")
                hypotheses = self.connection.execute(
                    "SELECT n.payload FROM edges e JOIN nodes n ON n.id = e.src "
                    "WHERE e.dst = ? AND e.kind = 'tests' ORDER BY n.first_seen",
                    (premise["id"],),
                ).fetchall()
                for row in hypotheses:
                    h = json.loads(row["payload"])
                    lines.append(f"        hypothesis: {h['statement']}")
                    lines.append(f"            do: {h['intervention']} | measure: {h['readout']} | in: {h['model_system']}")
                    if h.get("falsification"):
                        lines.append(f"            rejected if: {h['falsification']}")
        counts = self.connection.execute(
            "SELECT kind, COUNT(*) AS n FROM nodes GROUP BY kind ORDER BY kind"
        ).fetchall()
        lines.append("nodes: " + ", ".join(f"{row['kind']}={row['n']}" for row in counts))
        return "\n".join(lines)

    # --- reasoning log -----------------------------------------------------

    def record_step(self, step: ReasoningStep) -> None:
        self.connection.execute(
            "INSERT INTO steps (node_id, stage, verdict, rationale, run_id, at, prompt_hash) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                step.node_id,
                step.stage,
                step.verdict,
                step.rationale,
                step.run_id,
                step.at,
                step.prompt_hash,
            ),
        )
        self.connection.commit()

    def steps_for(self, node_id: str) -> list[ReasoningStep]:
        rows = self.connection.execute(
            "SELECT node_id, stage, verdict, rationale, run_id, at, prompt_hash FROM steps "
            "WHERE node_id = ? ORDER BY id",
            (node_id,),
        ).fetchall()
        return [ReasoningStep(**dict(row)) for row in rows]

    def already_checked(self, node_id: str) -> bool:
        """Loop guard for stage 6: has any round judged this node before?

        Unused by stages 0-4, which is deliberate — it is the hook the
        iteration loop needs so round 2 does not re-ask round 1's questions.
        """
        row = self.connection.execute(
            "SELECT 1 FROM steps WHERE node_id = ? LIMIT 1", (node_id,)
        ).fetchone()
        return row is not None

    # --- LLM cache ---------------------------------------------------------

    def cached_response(self, prompt_hash: str) -> str | None:
        with self._lock:
            row = self.connection.execute(
                "SELECT response FROM llm_cache WHERE prompt_hash = ?", (prompt_hash,)
            ).fetchone()
        return row["response"] if row else None

    def store_response(self, prompt_hash: str, model: str, response: str) -> None:
        with self._lock:
            self.connection.execute(
                "INSERT OR REPLACE INTO llm_cache (prompt_hash, model, response, at) "
                "VALUES (?, ?, ?, ?)",
                (prompt_hash, model, response, utcnow()),
            )
            self.connection.commit()
