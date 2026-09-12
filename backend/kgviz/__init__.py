"""Side module: knowledge-graph trajectory for premises / hypotheses.

Reads `runs/knowledge.db` only. Adds virtual premise→concept edges so a walk
from the question node is the activation path L0–L3 actually used. Same
question hash, same neighbour order, same trajectory.
"""

from backend.kgviz.graph import load_graph, resolve_seed, snapshot, walk

__all__ = ["load_graph", "resolve_seed", "snapshot", "walk"]
