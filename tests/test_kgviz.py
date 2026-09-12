"""Trajectory walk: deterministic activation from the knowledge base."""

from backend.grounding.domain import Hypothesis, Premise, PremiseStatus, premise_id, question_id
from backend.grounding.knowledge_base import SqliteKnowledgeBase
from backend.kgviz.graph import load_graph, resolve_seed, walk


def _kb():
    knowledge_base = SqliteKnowledgeBase(":memory:")
    question = "Does SIRT1 extend healthspan via mitochondrial biogenesis?"
    node = question_id(question)
    knowledge_base._upsert_node(node, "question", question, {}, "r1")
    premises = [
        Premise(
            subject="SIRT1", verb="deacetylates", object="PGC-1alpha",
            statement="SIRT1 deacetylates PGC-1alpha", status=PremiseStatus.ESTABLISHED,
            derived_from="SIRT1 extends healthspan via mitochondrial biogenesis",
        ),
        Premise(
            subject="PGC-1alpha", verb="triggers", object="mitochondrial biogenesis",
            statement="PGC-1alpha triggers mitochondrial biogenesis",
            status=PremiseStatus.ESTABLISHED,
            derived_from="SIRT1 extends healthspan via mitochondrial biogenesis",
        ),
        Premise(
            subject="mitochondrial biogenesis", verb="extends", object="human healthspan",
            statement="mitochondrial biogenesis extends human healthspan",
            status=PremiseStatus.UNVERIFIED,
            derived_from="SIRT1 extends healthspan via mitochondrial biogenesis",
        ),
    ]
    for premise in premises:
        knowledge_base.upsert_premise(premise, node, "r1", "stub", None)
    return knowledge_base, question, node


def test_same_question_same_trajectory():
    knowledge_base, question, seed = _kb()
    graph = load_graph(knowledge_base.connection)
    first = walk(graph, seed, mode="bfs", depth=2)
    second = walk(graph, seed, mode="bfs", depth=2)
    assert first == second
    assert resolve_seed(graph, question) == seed
    assert resolve_seed(graph, question) == resolve_seed(graph, question)


def test_depth_one_is_only_the_premises():
    knowledge_base, _, seed = _kb()
    graph = load_graph(knowledge_base.connection)
    activation = walk(graph, seed, mode="bfs", depth=1)
    kinds = {node["id"]: node["kind"] for node in graph["nodes"]}
    visited_kinds = {kinds[item["id"]] for item in activation["visited"]}
    assert visited_kinds == {"question", "premise"}
    assert activation["visited"][0]["id"] == seed


def test_bfs_reaches_concepts_at_depth_two():
    knowledge_base, _, seed = _kb()
    graph = load_graph(knowledge_base.connection)
    activation = walk(graph, seed, mode="bfs", depth=2)
    names = {node["id"]: node["name"] for node in graph["nodes"]}
    visited_names = {names[item["id"]] for item in activation["visited"]}
    assert "SIRT1" in visited_names
    assert "human healthspan" in visited_names


def test_hypothesis_lights_up_from_the_premise_it_tests():
    knowledge_base, _, seed = _kb()
    gap = Premise(
        subject="mitochondrial biogenesis", verb="extends", object="human healthspan",
        statement="mitochondrial biogenesis extends human healthspan",
        status=PremiseStatus.UNVERIFIED,
        derived_from="SIRT1 extends healthspan via mitochondrial biogenesis",
    )
    knowledge_base.upsert_hypothesis(
        Hypothesis(
            subject="mitochondrial biogenesis", verb="extends", object="human healthspan",
            statement="Exercise raises mtDNA copy number in older adults",
            targets=premise_id(gap),
            intervention="endurance training",
            readout="mtDNA copy number",
            model_system="older adults",
            falsification="mtDNA copy number unchanged",
            id="H1",
        ),
        "r1",
    )
    graph = load_graph(knowledge_base.connection)
    activation = walk(graph, seed, mode="bfs", depth=2)
    names = {node["id"]: node["name"] for node in graph["nodes"]}
    visited = {names[item["id"]] for item in activation["visited"]}
    assert "Exercise raises mtDNA copy number in older adults" in visited


def test_dfs_visit_order_differs_but_set_matches_bfs():
    knowledge_base, _, seed = _kb()
    graph = load_graph(knowledge_base.connection)
    bfs = walk(graph, seed, mode="bfs", depth=3)
    dfs = walk(graph, seed, mode="dfs", depth=3)
    assert {item["id"] for item in bfs["visited"]} == {item["id"] for item in dfs["visited"]}
    assert [item["id"] for item in bfs["visited"]] != [item["id"] for item in dfs["visited"]]


def test_missing_knowledge_base_is_a_value_error_not_a_crash(tmp_path):
    import pytest
    from backend.kgviz.graph import snapshot

    with pytest.raises(ValueError, match="no knowledge base"):
        snapshot(path=tmp_path / "absent.db")
