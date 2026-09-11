"""Unit tests for the tool wrapper contract: every tool must degrade to a
mock result rather than raising, and every mock result must satisfy the
shared {summary, items, mock, error} shape the agent loop depends on.
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

os.environ.pop("TAVILY_API_KEY", None)
os.environ.pop("AMASS_API_KEY", None)
os.environ.pop("NEBIUS_API_KEY", None)

from backend.tools import (  # noqa: E402
    amass_tool,
    enrichment_tool,
    extract_genes_tool,
    genage_drugage_tool,
    tavily_tool,
)
from backend.tools.registry import enabled_tool_names, get_specs, run_tool  # noqa: E402


def _assert_contract(result: dict) -> None:
    assert "summary" in result and isinstance(result["summary"], str)
    assert "items" in result and isinstance(result["items"], list)
    assert "mock" in result and isinstance(result["mock"], bool)
    assert "error" in result
    for item in result["items"]:
        assert {"id", "url", "summary"} <= item.keys()


def test_tavily_mock_without_key():
    result = tavily_tool.run({"query": "sirtuin ageing"})
    _assert_contract(result)
    assert result["mock"] is True


def test_amass_mock_without_config():
    result = amass_tool.run({"query": "sirtuin ageing"})
    _assert_contract(result)
    assert result["mock"] is True


def test_genage_drugage_missing_data_is_non_fatal():
    result = genage_drugage_tool.run({"query": "SIRT1"})
    _assert_contract(result)


def test_extract_genes_heuristic_fallback_without_key():
    result = extract_genes_tool.run({"text": "SIRT1 and FOXO3 regulate mitochondrial biogenesis via PGC1A."})
    assert result["mock"] is True
    assert "SIRT1" in result["genes"]


def test_enrichment_empty_gene_list_is_handled():
    result = enrichment_tool.run({"genes": []})
    _assert_contract(result)
    assert result["error"] == "empty_gene_list"


def test_registry_respects_enabled_tools(monkeypatch):
    monkeypatch.setenv("ENABLED_TOOLS", "tavily,pubmed")
    assert set(enabled_tool_names()) == {"tavily", "pubmed"}
    specs = get_specs()
    assert {s["name"] for s in specs} == {"tavily", "pubmed"}

    disabled_result = run_tool("open_targets", {"target_symbol": "SIRT1"})
    assert disabled_result["error"] == "tool_disabled"


def test_registry_tool_exception_is_caught(monkeypatch):
    def boom(_args):
        raise RuntimeError("simulated failure")

    monkeypatch.setattr(tavily_tool, "run", boom)
    from backend.tools import registry

    monkeypatch.setattr(registry, "_ALL_TOOLS", {**registry._ALL_TOOLS, "tavily": tavily_tool})
    result = registry.run_tool("tavily", {"query": "x"})
    assert result["mock"] is True
    assert "simulated failure" in result["error"]
