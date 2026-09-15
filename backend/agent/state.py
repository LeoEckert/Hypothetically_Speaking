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
    title: str = ""
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

    # Structured hypotheses, updated monotonically at PLAN/REVISE/REPORT —
    # a stage overwrites this only when it produces a non-empty parse, so a
    # malformed fence at a later stage never erases an earlier good result.
    hypotheses: list[dict] = field(default_factory=list)

    # Tools allowed for this run, snapshotted once at start — toggling tools
    # mid-run must not change an in-flight run's behavior or cost accounting.
    enabled_tools: set[str] = field(default_factory=set)

    # Anthropic usage, accumulated across every messages.create() call this run.
    anthropic_calls: int = 0
    anthropic_input_tokens: int = 0
    anthropic_output_tokens: int = 0
    anthropic_cache_creation_input_tokens: int = 0
    anthropic_cache_read_input_tokens: int = 0
    # Per-model token counts: the grounding stage runs on Haiku while the loop
    # runs on ANTHROPIC_MODEL, and each must be priced at its own rate.
    anthropic_by_model: dict = field(default_factory=dict)

    # Nebius usage, accumulated from extract_genes tool calls this run.
    nebius_calls: int = 0
    nebius_prompt_tokens: int = 0
    nebius_completion_tokens: int = 0

    # Amass account-wide credit balance, sampled once before and once after
    # this run's Amass calls (if any) — a real, verifiable number.
    amass_credits_before: float | None = None
    amass_credits_after: float | None = None

    def add_evidence(
        self, evidence_id: str, source: str, url: str, summary: str, raw: dict, title: str = ""
    ) -> str:
        """Store an evidence item; returns the citation id to use inline in the report."""
        self.evidence[evidence_id] = EvidenceItem(
            id=evidence_id, source=source, url=url, summary=summary, title=title, raw=raw
        )
        return evidence_id

    def record_tool_call(
        self, tool_name: str, args: dict, result_summary: str, mock: bool, usage: dict | None = None
    ) -> None:
        self.tool_calls_made += 1
        self.trace.append(
            ToolCallRecord(
                step=len(self.trace) + 1,
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

    def record_external_call(self, tool_name: str, args: dict, result_summary: str, mock: bool = False) -> int:
        """A call made outside the agent's tool budget (the grounding stage's
        Amass and Claude calls): it appears in the trace and the cost summary
        but does not count against max_tool_calls. Returns its step number."""
        step = len(self.trace) + 1
        self.trace.append(
            ToolCallRecord(step=step, tool_name=tool_name, args=args, result_summary=result_summary, mock=mock, usage=None)
        )
        return step

    def record_anthropic_tokens(self, usage: dict, model: str = "") -> None:
        self.anthropic_calls += 1
        self.anthropic_input_tokens += usage.get("input_tokens", 0) or 0
        self.anthropic_output_tokens += usage.get("output_tokens", 0) or 0
        self.anthropic_cache_creation_input_tokens += usage.get("cache_creation_input_tokens", 0) or 0
        self.anthropic_cache_read_input_tokens += usage.get("cache_read_input_tokens", 0) or 0
        bucket = self.anthropic_by_model.setdefault(
            model or "unknown",
            {"calls": 0, "input_tokens": 0, "output_tokens": 0, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0},
        )
        bucket["calls"] += 1
        for key in ("input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens"):
            bucket[key] += usage.get(key, 0) or 0

    def record_anthropic_usage(self, response) -> None:
        """Accumulate token usage from an Anthropic Messages API response.
        Guards missing/None fields since some usage fields are SDK-version-dependent."""
        usage = getattr(response, "usage", None)
        if usage is None:
            return
        self.record_anthropic_tokens(
            {
                key: getattr(usage, key, 0) or 0
                for key in ("input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")
            },
            getattr(response, "model", "") or "",
        )

    def budget_exceeded(self, reserve_seconds: float = 0) -> bool:
        """`reserve_seconds`, when given, holds back that much wall-clock time
        for phases after this check (REVISE + REPORT) — those run unconditionally
        once entered, so the ACT loop must stop early enough that they still fit
        inside `max_run_seconds` instead of running past it."""
        elapsed = time.time() - self.started_at
        return self.tool_calls_made >= self.max_tool_calls or elapsed >= (self.max_run_seconds - reserve_seconds)

    def citation_index(self) -> str:
        """Render the evidence registry as a citation appendix for the report prompt."""
        lines = []
        for item in self.evidence.values():
            lines.append(f"[{item.id}] ({item.source}) {item.summary} — {item.url}")
        return "\n".join(lines)
