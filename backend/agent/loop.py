"""The plan -> retrieve -> compute -> revise -> report agent loop.

A manual Anthropic Messages API tool-use loop (see docs/ARCHITECTURE.md for
why this was chosen over the Claude Agent SDK for this build). `on_event`
is called with small dicts describing each step, so a caller (the FastAPI
SSE endpoint, or scripts/run_demo.py) can stream/record the run live.
"""
from __future__ import annotations

import os
from typing import Callable, Optional

from anthropic import Anthropic

from backend.agent.prompts import (
    PARTIAL_RUN_NOTICE,
    REVISE_PROMPT,
    SYSTEM_PROMPT,
    final_report_prompt,
)
from backend.agent.costs import build_cost_summary
from backend.agent.state import RunState
from backend.tools import amass_tool
from backend.tools.registry import enabled_tool_names, get_specs, run_tool

EventCallback = Optional[Callable[[dict], None]]

_NUDGE_NO_TOOLS = (
    "You have not called any tools yet. Use the available tools now to "
    "gather real evidence (literature, databases, trial status) before "
    "writing anything else — do not answer from prior knowledge alone."
)
MAX_NO_TOOL_NUDGES = 2


def _emit(on_event: EventCallback, event: dict) -> None:
    if on_event:
        on_event(event)


def _text_of(content_blocks) -> str:
    return "".join(b.text for b in content_blocks if getattr(b, "type", None) == "text")


def _strip_empty_text_blocks(content_blocks):
    """Claude sometimes returns a text block with empty/whitespace-only text
    alongside a tool_use or thinking block in the same turn. Resending that
    verbatim on the next request gets rejected with a 400 ("text content
    blocks must be non-empty"), which otherwise aborts the whole run. Drop
    only truly empty text blocks; everything else (tool_use, thinking,
    non-empty text) passes through untouched."""
    return [
        b for b in content_blocks if not (getattr(b, "type", None) == "text" and not b.text.strip())
    ]


def run_agent(question: str, on_event: EventCallback = None, run_id: str | None = None) -> dict:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    model = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5")
    client = Anthropic(api_key=api_key)

    state = RunState(
        question=question,
        max_tool_calls=int(os.environ.get("MAX_TOOL_CALLS", 15)),
        max_run_seconds=int(os.environ.get("MAX_RUN_SECONDS", 1080)),
    )
    if run_id:
        state.run_id = run_id
    state.enabled_tools = set(enabled_tool_names())
    tools = get_specs()
    messages: list[dict] = [{"role": "user", "content": f"Research question: {question}"}]

    _emit(on_event, {"type": "start", "run_id": state.run_id, "question": question})
    _emit(on_event, {"type": "phase", "phase": "plan_and_gather"})

    no_tool_nudges = 0
    try:
        while True:
            if state.budget_exceeded():
                state.partial = True
                break

            response = client.messages.create(
                model=model,
                max_tokens=4096,
                system=SYSTEM_PROMPT,
                messages=messages,
                **({"tools": tools} if tools else {}),
            )
            state.record_anthropic_usage(response)
            messages.append({"role": "assistant", "content": _strip_empty_text_blocks(response.content)})

            text = _text_of(response.content)
            if text.strip():
                _emit(on_event, {"type": "assistant_text", "text": text})

            if response.stop_reason != "tool_use":
                if state.tool_calls_made == 0 and no_tool_nudges < MAX_NO_TOOL_NUDGES:
                    no_tool_nudges += 1
                    messages.append({"role": "user", "content": _NUDGE_NO_TOOLS})
                    continue
                break

            tool_results = []
            for block in response.content:
                if getattr(block, "type", None) != "tool_use":
                    continue
                if state.budget_exceeded():
                    tool_results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": "Tool budget exceeded for this run; call skipped.",
                        }
                    )
                    continue

                _emit(
                    on_event,
                    {"type": "tool_call", "tool": block.name, "args": block.input, "step": state.tool_calls_made + 1},
                )
                if block.name == "amass" and state.amass_credits_before is None:
                    state.amass_credits_before = amass_tool.get_credits()
                result = run_tool(block.name, block.input, enabled_names=state.enabled_tools)

                for item in result.get("items", []):
                    state.add_evidence(
                        item["id"], source=block.name, url=item.get("url", ""), summary=item["summary"], raw=item.get("raw", {})
                    )
                state.record_tool_call(
                    block.name, block.input, result.get("summary", ""), result.get("mock", False), usage=result.get("usage")
                )

                _emit(
                    on_event,
                    {
                        "type": "tool_result",
                        "tool": block.name,
                        "step": state.tool_calls_made,
                        "mock": result.get("mock", False),
                        "error": result.get("error"),
                        "summary": result.get("summary", ""),
                        "usage": result.get("usage"),
                    },
                )

                content_text = result.get("summary", "")
                if "genes" in result:
                    content_text += f"\n\nExtracted genes (use these for run_enrichment): {result['genes']}"

                tool_results.append({"type": "tool_result", "tool_use_id": block.id, "content": content_text})

            messages.append({"role": "user", "content": tool_results})

        # --- REVISE ---
        _emit(on_event, {"type": "phase", "phase": "revise"})
        messages.append({"role": "user", "content": REVISE_PROMPT})
        revise_resp = client.messages.create(model=model, max_tokens=2048, system=SYSTEM_PROMPT, messages=messages)
        state.record_anthropic_usage(revise_resp)
        messages.append({"role": "assistant", "content": _strip_empty_text_blocks(revise_resp.content)})
        revise_text = _text_of(revise_resp.content)
        if revise_text.strip():
            _emit(on_event, {"type": "assistant_text", "text": revise_text})

        # --- REPORT ---
        _emit(on_event, {"type": "phase", "phase": "report"})
        report_instructions = final_report_prompt(state.citation_index())
        if state.partial:
            report_instructions = PARTIAL_RUN_NOTICE + "\n\n" + report_instructions
        messages.append({"role": "user", "content": report_instructions})
        report_resp = client.messages.create(model=model, max_tokens=4096, system=SYSTEM_PROMPT, messages=messages)
        state.record_anthropic_usage(report_resp)
        report_text = _text_of(report_resp.content)

    except Exception as exc:
        state.partial = True
        report_text = (
            f"## Run Error\n\nThe agent run failed with an unrecoverable error: `{exc}`.\n\n"
            f"Evidence gathered before the failure ({len(state.evidence)} items) is listed below "
            "for debugging; no hypothesis ranking was completed.\n\n" + state.citation_index()
        )
        _emit(on_event, {"type": "error", "error": str(exc)})

    if state.amass_credits_before is not None:
        state.amass_credits_after = amass_tool.get_credits()
    cost_summary = build_cost_summary(state, model)
    evidence_dict = {k: vars(v) for k, v in state.evidence.items()}

    result = {
        "run_id": state.run_id,
        "question": question,
        "report": report_text,
        "partial": state.partial,
        "trace": [vars(t) for t in state.trace],
        "evidence": evidence_dict,
        "cost": cost_summary,
    }
    _emit(
        on_event,
        {
            "type": "done",
            "report": report_text,
            "partial": state.partial,
            "run_id": state.run_id,
            "cost": cost_summary,
            "evidence": evidence_dict,
        },
    )
    return result
