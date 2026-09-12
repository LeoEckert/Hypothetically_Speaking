"""Run state: evidence registry, citation IDs, budget tracking."""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field


@dataclass
class EvidenceItem:
    id: str
    source: str          # tool name that produced this, e.g. "pubmed", "open_targets"
    url: str
    summary: str
    raw: dict = field(default_factory=dict)


@dataclass
class ToolCallRecord:
    step: int
    tool_name: str
    args: dict
    result_summary: str
    mock: bool
    timestamp: float = field(default_factory=time.time)
    usage: dict | None = None  # e.g. Nebius {"prompt_tokens": int, "completion_tokens": int}


@dataclass
class RunState:
    question: str
    run_id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    started_at: float = field(default_factory=time.time)
    max_tool_calls: int = 15
    max_run_seconds: int = 1080
    tool_calls_made: int = 0
    evidence: dict[str, EvidenceItem] = field(default_factory=dict)
    trace: list[ToolCallRecord] = field(default_factory=list)
    partial: bool = False  # set True if we hit a budget limit and force-finalized
    cancelled: bool = False  # set True if the user cancelled the run (also implies partial)

    # Tools allowed for this run, snapshotted once at start — toggling tools
    # mid-run must not change an in-flight run's behavior or cost accounting.
    enabled_tools: set[str] = field(default_factory=set)

    # Anthropic usage, accumulated across every messages.create() call this run.
    anthropic_calls: int = 0
    anthropic_input_tokens: int = 0
    anthropic_output_tokens: int = 0
    anthropic_cache_creation_input_tokens: int = 0
    anthropic_cache_read_input_tokens: int = 0

    # Nebius usage, accumulated from extract_genes tool calls this run.
    nebius_calls: int = 0
    nebius_prompt_tokens: int = 0
    nebius_completion_tokens: int = 0

    # Amass account-wide credit balance, sampled once before and once after
    # this run's Amass calls (if any) — a real, verifiable number.
    amass_credits_before: float | None = None
    amass_credits_after: float | None = None

    def add_evidence(self, evidence_id: str, source: str, url: str, summary: str, raw: dict) -> str:
        """Store an evidence item; returns the citation id to use inline in the report."""
        self.evidence[evidence_id] = EvidenceItem(
            id=evidence_id, source=source, url=url, summary=summary, raw=raw
        )
        return evidence_id

    def record_tool_call(
        self, tool_name: str, args: dict, result_summary: str, mock: bool, usage: dict | None = None
    ) -> None:
        self.tool_calls_made += 1
        self.trace.append(
            ToolCallRecord(
                step=self.tool_calls_made,
                tool_name=tool_name,
                args=args,
                result_summary=result_summary,
                mock=mock,
                usage=usage,
            )
        )
        if usage and tool_name == "extract_genes":
            self.nebius_calls += 1
            self.nebius_prompt_tokens += usage.get("prompt_tokens", 0) or 0
            self.nebius_completion_tokens += usage.get("completion_tokens", 0) or 0

    def record_anthropic_usage(self, response) -> None:
        """Accumulate token usage from an Anthropic Messages API response.
        Guards missing/None fields since some usage fields are SDK-version-dependent."""
        usage = getattr(response, "usage", None)
        if usage is None:
            return
        self.anthropic_calls += 1
        self.anthropic_input_tokens += getattr(usage, "input_tokens", 0) or 0
        self.anthropic_output_tokens += getattr(usage, "output_tokens", 0) or 0
        self.anthropic_cache_creation_input_tokens += getattr(usage, "cache_creation_input_tokens", 0) or 0
        self.anthropic_cache_read_input_tokens += getattr(usage, "cache_read_input_tokens", 0) or 0

    def budget_exceeded(self) -> bool:
        elapsed = time.time() - self.started_at
        return self.tool_calls_made >= self.max_tool_calls or elapsed >= self.max_run_seconds

    def citation_index(self) -> str:
        """Render the evidence registry as a citation appendix for the report prompt."""
        lines = []
        for item in self.evidence.values():
            lines.append(f"[{item.id}] ({item.source}) {item.summary} — {item.url}")
        return "\n".join(lines)
