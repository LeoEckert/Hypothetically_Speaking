"""The plan -> retrieve -> compute -> revise -> report agent loop.

A manual Anthropic Messages API tool-use loop (see docs/ARCHITECTURE.md for
why this was chosen over the Claude Agent SDK for this build). `on_event`
is called with small dicts describing each step, so a caller (the FastAPI
SSE endpoint, or scripts/run_demo.py) can stream/record the run live.
"""
from __future__ import annotations

import json
import os
import re
from typing import Callable, Optional

from anthropic import Anthropic

from backend.agent.prompts import (
    CANCELLED_RUN_NOTICE,
    PARTIAL_RUN_NOTICE,
    REVISE_PROMPT,
    SYSTEM_PROMPT,
    final_report_prompt,
    plan_prompt,
)
from backend.agent.costs import build_cost_summary
from backend.agent.state import RunState
from backend.tools import amass_tool
from backend.tools.registry import enabled_tool_names, get_specs, run_tool

EventCallback = Optional[Callable[[dict], None]]
CancelCheck = Optional[Callable[[], bool]]

# Absolute ceiling on tool calls for any run, regardless of what a caller
# (the API's max_tool_calls request field, MAX_TOOL_CALLS env var, or a
# future caller) asks for — protects against runaway cost/time no matter
# where a request originates.
HARD_MAX_TOOL_CALLS = 40

_NUDGE_NO_TOOLS = (
    "You have not called any tools yet. Use the available tools now to "
    "gather real evidence (literature, databases, trial status) before "
    "writing anything else — do not answer from prior knowledge alone."
)
MAX_NO_TOOL_NUDGES = 2


def _emit(on_event: EventCallback, event: dict) -> None:
    if on_event:
        on_event(event)


_GROUNDING_KEYS = ("ANTHROPIC_API_KEY", "AMASS_API_KEY")


def _grounding_payload(question: str, state: RunState | None = None, on_event=None, mode: str = "normal") -> dict:
    """Run L0-L4 and return the same structured payload sent to the UI.

    Every Amass and Claude call the grounding makes is streamed as a
    tool_call/tool_result pair and recorded on the run state (trace, Anthropic
    tokens, Amass credits) so the trace and cost panel show the whole run —
    without counting against the agent's tool budget."""
    missing = [name for name in _GROUNDING_KEYS if not os.environ.get(name)]
    empty = {"coherent": None, "triples": [], "destination": "", "premises": [], "knowledge_graph": "", "hypotheses": [], "rejected": []}
    if missing:
        return {"status": "skipped", "why": f"Missing {', '.join(missing)}", **empty}
    try:
        from backend.grounding.adapters import Ledger
        from scripts.run_grounding import ground

        def record(entry: dict) -> None:
            if state is None:
                return
            step = state.record_external_call(entry["tool"], entry["args"], entry["summary"])
            if entry["tool"] == "grounding" and entry.get("usage"):
                state.record_anthropic_tokens(entry["usage"], entry["args"].get("model", ""))
            _emit(on_event, {"type": "tool_call", "tool": entry["tool"], "args": entry["args"], "step": step})
            _emit(on_event, {"type": "tool_result", "tool": entry["tool"], "step": step, "mock": False, "error": None, "summary": entry["summary"], "usage": None})

        if state is not None and state.amass_credits_before is None:
            state.amass_credits_before = amass_tool.get_credits()
        grounding = ground(
            question,
            ledger=Ledger(record),
            fast=mode == "fast",
            on_progress=lambda event: _emit(on_event, {"type": "grounding_step", **event}),
        )
        return {
            "status": "complete",
            "mode": mode,
            "coherent": grounding.coherent,
            "why": grounding.why,
            "triples": [triple.model_dump(mode="json") for triple in grounding.triples],
            "destination": grounding.destination,
            "premises": [premise.model_dump(mode="json") for premise in grounding.premises],
            "knowledge_graph": grounding.knowledge_graph,
            "hypotheses": [hypothesis.model_dump(mode="json") for hypothesis in grounding.hypotheses],
            "rejected": [hypothesis.model_dump(mode="json") for hypothesis in grounding.rejected],
        }
    except Exception as exc:
        return {"status": "failed", "why": str(exc), **empty}


def _grounding_text(payload: dict) -> str:
    """Dump structured grounding as text for the PLAN prompt."""
    if payload["status"] != "complete":
        return f"(grounding {payload['status']}: {payload['why']})"
    if not payload["coherent"]:
        return f"(grounding: question judged not coherent — {payload['why']})"
    unverified = [
        premise for premise in payload["premises"] if premise["status"] == "UNVERIFIED"
    ]
    candidates = "\n".join(
        f"- {h['statement']}  (tests: {h['targets']}; do: {h['intervention']}; "
        f"measure: {h['readout']}; in: {h['model_system']})\n  why: {h.get('story', '')}"
        for h in payload.get("hypotheses", [])
    )
    return (
        f"Knowledge graph:\n{payload['knowledge_graph']}\n\n"
        f"Unverified premises (the gaps hypotheses should target):\n"
        f"{json.dumps(unverified, indent=2)}"
        + (
            "\n\nCandidate hypotheses, already filtered to one testable claim each. "
            "Use these as your hypotheses, in this order, keeping each statement as "
            "written or shorter — never merge, extend or qualify them:\n" + candidates
            if candidates else ""
        )
    )


def _plan_message(grounding_text: str, n_candidates: int = 0) -> str:
    """PLAN's prompt asks for 2-4 hypotheses; when the grounding already
    produced candidates, PLAN's job is to adopt exactly those — padding the
    list with its own would reintroduce ungrounded, compound hypotheses."""
    prompt = plan_prompt()
    if n_candidates:
        prompt = prompt.replace(
            "propose 2-4 concrete, testable hypotheses\nthat could answer the research question, each grounded in a plausible\nageing-biology mechanism.",
            f"propose exactly {n_candidates} hypothes{'is' if n_candidates == 1 else 'es'}: the grounded "
            f"candidate{'' if n_candidates == 1 else 's'} listed above, statement{'' if n_candidates == 1 else 's'} "
            "kept as written. Do not add hypotheses of your own.",
        )
    return (
        "Grounding context from a prior extraction step. Use this when "
        "proposing hypotheses; do not treat it as already-verified evidence.\n\n"
        f"{grounding_text}\n\n"
        + prompt
    )


def _text_of(content_blocks) -> str:
    return "".join(b.text for b in content_blocks if getattr(b, "type", None) == "text")


_HYPOTHESES_FENCE_RE = re.compile(r"```json\s*(\{.*?\"hypotheses\".*?\})\s*```", re.DOTALL)

_PLAN_TO_ACT_NUDGE = (
    "Now gather evidence for these hypotheses using the available tools."
)

_CONFIDENCE_VALUES = ("high", "medium", "low")


def _parse_hypotheses(text: str) -> list[dict]:
    """Pull the raw hypotheses list out of a trailing ```json fence, if
    present and parseable. Never raises; returns [] on any failure."""
    match = _HYPOTHESES_FENCE_RE.search(text)
    if not match:
        return []
    try:
        payload = json.loads(match.group(1))
    except json.JSONDecodeError:
        return []
    hyps = payload.get("hypotheses", [])
    return hyps if isinstance(hyps, list) else []


def _extract_hypotheses(report_text: str) -> tuple[str, list[dict]]:
    """Split a trailing ```json {"hypotheses": [...]} fence off the end of
    free-text prose. The fence region is always stripped once found, even
    if it fails to parse — a broken/dangling code block must never leak
    into what's shown to the user."""
    match = _HYPOTHESES_FENCE_RE.search(report_text)
    if not match:
        return report_text, []
    stripped = report_text[: match.start()].rstrip()
    return stripped, _parse_hypotheses(report_text)


def _normalize_hypotheses(
    raw: list[dict], stage: str, known: dict[str, dict], evidence_ids: set[str]
) -> list[dict]:
    """Coerce a model-supplied hypotheses list into the canonical shape.
    Never raises regardless of what the model sent.

    - stage "plan" (or any stage when `known` is empty, i.e. PLAN never
      produced anything to recover from): mints fresh stable ids h1..hN.
    - stage "revise"/"final" with an established `known` roster: matches
      incoming items by id against it, drops anything with an
      unrecognized id (ids are never renumbered or invented once PLAN has
      assigned them), dedupes, and enforces exactly one `selected`.
    """
    if not isinstance(raw, list):
        return []

    if stage == "plan" or not known:
        # At the real PLAN stage nothing has been evaluated yet, so never
        # force a "selected" hypothesis — only revise/final (including the
        # bootstrap-recovery case where PLAN produced nothing) represent an
        # actual evaluation and must guarantee exactly one selected.
        force_selection = stage != "plan"
        normalized: list[dict] = []
        seen_selected = False
        for h in raw:
            if not isinstance(h, dict):
                continue
            statement = str(h.get("statement", "")).strip()
            if not statement:
                continue
            confidence = h.get("confidence")
            if confidence not in _CONFIDENCE_VALUES:
                confidence = None
            ev_ids = [e for e in (h.get("evidence_ids") or []) if isinstance(e, str) and e in evidence_ids]
            contra_ids = [
                e for e in (h.get("contradicting_ids") or []) if isinstance(e, str) and e in evidence_ids
            ]
            selected = bool(h.get("selected")) and not seen_selected
            if selected:
                seen_selected = True
            normalized.append(
                {
                    "id": f"h{len(normalized) + 1}",
                    "rank": len(normalized) + 1,
                    "statement": statement,
                    "confidence": confidence,
                    "rationale": str(h.get("rationale", "")).strip(),
                    "selected": selected,
                    "evidence_ids": ev_ids,
                    "contradicting_ids": contra_ids,
                    "seed_question": str(h.get("seed_question", "")).strip(),
                }
            )
        if normalized and force_selection and not seen_selected:
            normalized[0]["selected"] = True
        return normalized

    # Ids are matched case-insensitively: PLAN mints h1..hN, but the model
    # sometimes echoes the H1..HN labels it saw in the grounding candidates.
    candidates = []
    for h in raw:
        if not isinstance(h, dict):
            continue
        hid = str(h.get("id", "")).strip().lower()
        if hid in known:
            candidates.append({**h, "id": hid})

    def _rank_key(pair: tuple[int, dict]) -> tuple[float, int]:
        idx, h = pair
        r = h.get("rank")
        return (r, idx) if isinstance(r, (int, float)) else (idx + 1, idx)

    ordered = sorted(enumerate(candidates), key=_rank_key)

    normalized = []
    seen_ids: set[str] = set()
    seen_selected = False
    for _, h in ordered:
        hid = h["id"]
        if hid in seen_ids:
            continue
        seen_ids.add(hid)
        base = known[hid]
        confidence = h.get("confidence")
        if confidence not in _CONFIDENCE_VALUES:
            confidence = None
        ev_ids = [e for e in (h.get("evidence_ids") or []) if isinstance(e, str) and e in evidence_ids]
        contra_ids = [
            e for e in (h.get("contradicting_ids") or []) if isinstance(e, str) and e in evidence_ids
        ]
        selected = bool(h.get("selected")) and not seen_selected
        if selected:
            seen_selected = True
        normalized.append(
            {
                "id": hid,
                "rank": len(normalized) + 1,
                "statement": str(h.get("statement") or base.get("statement", "")).strip(),
                "confidence": confidence,
                "rationale": str(h.get("rationale", "")).strip(),
                "selected": selected,
                "evidence_ids": ev_ids,
                "contradicting_ids": contra_ids,
                "seed_question": str(h.get("seed_question") or base.get("seed_question", "")).strip(),
            }
        )

    if normalized and not seen_selected:
        normalized[0]["selected"] = True

    return normalized


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


def run_agent(
    question: str,
    on_event: EventCallback = None,
    run_id: str | None = None,
    max_tool_calls: int | None = None,
    should_cancel: CancelCheck = None,
    mode: str = "normal",
) -> dict:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    model = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5")
    client = Anthropic(api_key=api_key)

    requested_max = max_tool_calls if max_tool_calls is not None else int(os.environ.get("MAX_TOOL_CALLS", 30))
    state = RunState(
        question=question,
        max_tool_calls=min(requested_max, HARD_MAX_TOOL_CALLS),
        max_run_seconds=int(os.environ.get("MAX_RUN_SECONDS", 1080)),
    )
    if run_id:
        state.run_id = run_id
    state.enabled_tools = set(enabled_tool_names())
    tools = get_specs()
    messages: list[dict] = [{"role": "user", "content": f"Research question: {question}"}]

    _emit(on_event, {"type": "start", "run_id": state.run_id, "question": question})

    _emit(on_event, {"type": "phase", "phase": "grounding"})
    grounding = _grounding_payload(question, state, on_event, mode)
    grounding_text = _grounding_text(grounding)
    _emit(on_event, {"type": "grounding", **grounding})

    no_tool_nudges = 0
    try:
        # --- PLAN ---
        _emit(on_event, {"type": "phase", "phase": "plan"})
        messages.append({"role": "user", "content": _plan_message(grounding_text, len(grounding.get("hypotheses") or []))})
        plan_resp = client.messages.create(model=model, max_tokens=1536, system=SYSTEM_PROMPT, messages=messages)
        state.record_anthropic_usage(plan_resp)
        messages.append({"role": "assistant", "content": _strip_empty_text_blocks(plan_resp.content)})
        raw_plan_hyps = _parse_hypotheses(_text_of(plan_resp.content))
        state.hypotheses = _normalize_hypotheses(raw_plan_hyps, "plan", {}, set(state.evidence))
        _emit(on_event, {"type": "hypotheses", "stage": "plan", "hypotheses": state.hypotheses})
        messages.append({"role": "user", "content": _PLAN_TO_ACT_NUDGE})

        _emit(on_event, {"type": "phase", "phase": "plan_and_gather"})

        while True:
            if should_cancel and should_cancel():
                state.cancelled = True
                state.partial = True
                break
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
                if should_cancel and should_cancel():
                    state.cancelled = True
                    tool_results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": "Run cancelled by the user; call skipped.",
                        }
                    )
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
                    {"type": "tool_call", "tool": block.name, "args": block.input, "step": len(state.trace) + 1},
                )
                if block.name == "amass" and state.amass_credits_before is None:
                    state.amass_credits_before = amass_tool.get_credits()
                result = run_tool(block.name, block.input, enabled_names=state.enabled_tools)

                for item in result.get("items", []):
                    state.add_evidence(
                        item["id"],
                        source=block.name,
                        url=item.get("url", ""),
                        summary=item["summary"],
                        title=item.get("title", ""),
                        raw=item.get("raw", {}),
                    )
                state.record_tool_call(
                    block.name, block.input, result.get("summary", ""), result.get("mock", False), usage=result.get("usage")
                )

                _emit(
                    on_event,
                    {
                        "type": "tool_result",
                        "tool": block.name,
                        "step": len(state.trace),
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
        revise_text, raw_revise_hyps = _extract_hypotheses(_text_of(revise_resp.content))
        if revise_text.strip():
            _emit(on_event, {"type": "assistant_text", "text": revise_text})
        normalized_revise = _normalize_hypotheses(
            raw_revise_hyps, "revise", {h["id"]: h for h in state.hypotheses}, set(state.evidence)
        )
        if normalized_revise:
            state.hypotheses = normalized_revise
        _emit(on_event, {"type": "hypotheses", "stage": "revise", "hypotheses": state.hypotheses})

        # --- REPORT ---
        _emit(on_event, {"type": "phase", "phase": "report"})
        report_instructions = final_report_prompt(state.citation_index())
        if state.cancelled:
            report_instructions = CANCELLED_RUN_NOTICE + "\n\n" + report_instructions
        elif state.partial:
            report_instructions = PARTIAL_RUN_NOTICE + "\n\n" + report_instructions
        messages.append({"role": "user", "content": report_instructions})
        report_resp = client.messages.create(model=model, max_tokens=8192, system=SYSTEM_PROMPT, messages=messages)
        state.record_anthropic_usage(report_resp)
        report_text, raw_final_hyps = _extract_hypotheses(_text_of(report_resp.content))
        normalized_final = _normalize_hypotheses(
            raw_final_hyps, "final", {h["id"]: h for h in state.hypotheses}, set(state.evidence)
        )
        if normalized_final:
            state.hypotheses = normalized_final
        _emit(on_event, {"type": "hypotheses", "stage": "final", "hypotheses": state.hypotheses})

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
        "cancelled": state.cancelled,
        "trace": [vars(t) for t in state.trace],
        "evidence": evidence_dict,
        "cost": cost_summary,
        "hypotheses": state.hypotheses,
    }
    _emit(
        on_event,
        {
            "type": "done",
            "report": report_text,
            "partial": state.partial,
            "cancelled": state.cancelled,
            "run_id": state.run_id,
            "cost": cost_summary,
            "evidence": evidence_dict,
            "hypotheses": state.hypotheses,
        },
    )
    return result
