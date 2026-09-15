"""The plan -> retrieve -> compute -> revise -> report agent loop.

A manual, provider-agnostic tool-use loop (see docs/ARCHITECTURE.md for why
this was chosen over the Claude Agent SDK for this build). Every LLM call
goes through backend.agent.providers.get_provider(), which picks Anthropic
or OpenRouter depending on which key was supplied (BYOK from the frontend's
required onboarding popup, or a local-dev env var) — loop.py itself never
branches on which provider is in use. `on_event` is called with small dicts describing each
step, so a caller (the FastAPI SSE endpoint, or scripts/run_demo.py) can
stream/record the run live.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Optional

import anthropic
import openai

from backend.agent.prompts import (
    CANCELLED_RUN_NOTICE,
    PARTIAL_RUN_NOTICE,
    REVISE_PROMPT,
    SYSTEM_PROMPT,
    final_report_prompt,
    plan_prompt,
)
from backend.agent.env import env_int
from backend.agent.costs import build_cost_summary
from backend.agent.providers import NoProviderAvailable, ToolResult, Transcript, get_provider
from backend.agent.state import RunState
from backend.tools import amass_tool
from backend.tools.registry import enabled_tool_names, get_specs, run_tool

EventCallback = Optional[Callable[[dict], None]]
CancelCheck = Optional[Callable[[], bool]]

# Absolute ceiling on tool calls for any run, regardless of what a caller
# (the API's max_tool_calls request field, MAX_TOOL_CALLS env var, or a
# future caller) asks for — protects against runaway cost/time no matter
# where a request originates.
#
# Sized for a hard 300s-per-run external platform ceiling (Vercel Fluid
# Compute), not the old 1080s VM budget. Raised from 12 (initial scaled-down
# guess) to 25 after real runs kept legitimately wanting more tool calls
# than that for thorough questions.
HARD_MAX_TOOL_CALLS = 25

# REVISE (~2048 max_tokens) and REPORT (~8192 max_tokens) run unconditionally
# once the ACT loop exits — neither is bounded by max_run_seconds on its own —
# so the ACT loop must stop early enough to leave room for both. Sized for
# Anthropic's slower streaming case; OpenRouter's actual latency depends on
# which underlying free model it routes to, so re-verify this reserve is
# still enough once real timed runs exist (see CLAUDE.md).
REPORT_RESERVE_SECONDS = 100

_NUDGE_NO_TOOLS = (
    "You have not called any tools yet. Use the available tools now to "
    "gather real evidence (literature, databases, trial status) before "
    "writing anything else — do not answer from prior knowledge alone."
)
MAX_NO_TOOL_NUDGES = 2

# Auth/permission errors from either SDK mean "this key was rejected" —
# distinct from NoProviderAvailable ("no key was ever configured") and worth
# a clearer message than the generic catch-all.
_KEY_INVALID_ERRORS = (
    anthropic.AuthenticationError,
    anthropic.PermissionDeniedError,
    openai.AuthenticationError,
    openai.PermissionDeniedError,
)


def _emit(on_event: EventCallback, event: dict) -> None:
    if on_event:
        on_event(event)


_env_int = env_int  # blank-but-set env vars fall back to the default; see backend/agent/env.py


def _has_llm_key(api_keys: dict) -> bool:
    return bool(
        api_keys.get("ANTHROPIC_API_KEY")
        or os.environ.get("ANTHROPIC_API_KEY")
        or api_keys.get("OPENROUTER_API_KEY")
        or os.environ.get("OPENROUTER_API_KEY")
    )


def _resolve_amass_credits_before(
    state: RunState, thread: threading.Thread | None, box: list, user_api_key: str | None = None
) -> None:
    """Amass's account-wide balance only needs to be sampled once, before any
    Amass call this run makes — it doesn't need to happen synchronously right
    at that call site. `thread`/`box` are the background prefetch started at
    run start (see run_agent); this just waits for it instead of making a
    fresh blocking call, so the ~10s request never sits on the critical path."""
    if state.amass_credits_before is not None:
        return
    if thread is not None:
        thread.join()
        state.amass_credits_before = box[0] if box else None
    else:
        state.amass_credits_before = amass_tool.get_credits(user_api_key)


def _grounding_payload(
    question: str,
    state: RunState | None = None,
    on_event=None,
    mode: str = "normal",
    amass_credits_thread: threading.Thread | None = None,
    amass_credits_box: list | None = None,
    api_keys: dict | None = None,
) -> dict:
    """Run L0-L4 and return the same structured payload sent to the UI.

    Every Amass and LLM call the grounding makes is streamed as a
    tool_call/tool_result pair and recorded on the run state (trace, LLM
    tokens, Amass credits) so the trace and cost panel show the whole run —
    without counting against the agent's tool budget."""
    api_keys = api_keys or {}
    amass_key = api_keys.get("AMASS_API_KEY") or os.environ.get("AMASS_API_KEY")
    empty = {"coherent": None, "triples": [], "destination": "", "premises": [], "knowledge_graph": "", "hypotheses": [], "rejected": []}
    # AMASS_API_KEY is deliberately not required: without one, ground() falls
    # back to keyless PubMed/ClinicalTrials.gov sources instead of skipping
    # (Amass has no free tier, so requiring it would block every BYOK user
    # who only has a free LLM key). An LLM key is still mandatory — grounding
    # is nothing but LLM-backed judgment calls over retrieved literature.
    if not _has_llm_key(api_keys):
        return {"status": "skipped", "why": "Missing an LLM provider key (Anthropic or OpenRouter, from Settings)", **empty}
    try:
        from backend.grounding.adapters import Ledger
        from backend.grounding.runner import ground

        def record(entry: dict) -> None:
            if state is None:
                return
            step = state.record_external_call(entry["tool"], entry["args"], entry["summary"])
            if entry["tool"] == "grounding" and entry.get("usage"):
                state.record_anthropic_tokens(entry["usage"], entry["args"].get("model", ""))
            _emit(on_event, {"type": "tool_call", "tool": entry["tool"], "args": entry["args"], "step": step})
            _emit(on_event, {"type": "tool_result", "tool": entry["tool"], "step": step, "mock": False, "error": None, "summary": entry["summary"], "usage": None})

        if state is not None:
            _resolve_amass_credits_before(state, amass_credits_thread, amass_credits_box or [], amass_key)
        grounding = ground(
            question,
            ledger=Ledger(record),
            fast=mode == "fast",
            on_progress=lambda event: _emit(on_event, {"type": "grounding_step", **event}),
            api_keys=api_keys,
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
            "kept as written. Do not add hypotheses of your own; this overrides the 2-4 range in the system instructions.",
        )
    return (
        "Grounding context from a prior extraction step. Use this when "
        "proposing hypotheses; do not treat it as already-verified evidence.\n\n"
        f"{grounding_text}\n\n"
        + prompt
    )


def _adopt_candidates(raw_plan: list, candidates: list[dict]) -> list[dict]:
    """When the grounding produced candidates, the PLAN roster is exactly those,
    in order. PLAN's own additions are dropped (its system prompt still says
    "2-4", and the model pads the list with compound, ungrounded hypotheses);
    only its seed_question is kept where it wrote about the same statement."""
    def norm(text: str) -> str:
        return re.sub(r"[^a-z0-9 ]", "", str(text).lower()).strip()

    by_statement = {norm(h.get("statement", "")): h for h in raw_plan if isinstance(h, dict)}
    adopted = []
    for candidate in candidates:
        planned = by_statement.get(norm(candidate["statement"]), {})
        seed = str(planned.get("seed_question") or "").strip() or (
            f"Does {candidate['intervention']} change {candidate['readout']} in {candidate['model_system']}?"
        )
        adopted.append({"statement": candidate["statement"], "seed_question": seed})
    return adopted


REPORT_SECTIONS = [
    "Hypothesis",
    "Evidence That Supports It",
    "Evidence That Doesn't / Contradicts It",
    "Confidence & Uncertainty",
    "Failure Modes",
    "Next Experiment To Run",
    "Tool Trace",
]
_HEADING_RE = re.compile(r"^## +(.+?)\s*$", re.M)


def _stream_message(provider, on_event, phase: str, detail: dict, transcript: Transcript, max_tokens: int):
    """Stream one call and emit a `progress` event about once a second:
    characters written so far and, for the report, which of the fixed
    sections is being written. PLAN, REVISE and REPORT are each a single long
    call with nothing else to show, so this is what keeps the status bar
    moving. Returns the normalized LLMResponse."""
    buffer: list[str] = []
    last_emit = 0.0

    def on_chunk(chunk: str) -> None:
        buffer.append(chunk)
        emit()

    def emit(force: bool = False) -> None:
        nonlocal last_emit
        now = time.time()
        if not force and now - last_emit < 1.0:
            return
        last_emit = now
        text = "".join(buffer)
        headings = _HEADING_RE.findall(text)
        _emit(
            on_event,
            {
                "type": "progress",
                "phase": phase,
                "chars": len(text),
                "section": headings[-1] if headings else None,
                "sections_done": len(headings),
                **detail,
            },
        )

    response = provider.stream(system=SYSTEM_PROMPT, transcript=transcript, max_tokens=max_tokens, on_chunk=on_chunk)
    emit(force=True)
    return response


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


def run_agent(
    question: str,
    on_event: EventCallback = None,
    run_id: str | None = None,
    max_tool_calls: int | None = None,
    should_cancel: CancelCheck = None,
    mode: str = "normal",
    api_keys: dict | None = None,
) -> dict:
    api_keys = api_keys or {}

    requested_max = max_tool_calls if max_tool_calls is not None else _env_int("MAX_TOOL_CALLS", 15)
    state = RunState(
        question=question,
        max_tool_calls=min(requested_max, HARD_MAX_TOOL_CALLS),
        # Default kept safely under Vercel Fluid Compute's hard 300s ceiling —
        # see REPORT_RESERVE_SECONDS above and CLAUDE.md.
        max_run_seconds=_env_int("MAX_RUN_SECONDS", 260),
    )
    if run_id:
        state.run_id = run_id
    state.enabled_tools = set(enabled_tool_names())
    tools = get_specs(api_keys)
    messages_seed = f"Research question: {question}"
    transcript = Transcript()
    transcript.add_user_text(messages_seed)

    # Amass's account-wide credit balance only needs to be sampled once
    # before this run's first Amass call — fire it off the critical path now
    # instead of blocking on it right before whichever call needs it first.
    amass_key = api_keys.get("AMASS_API_KEY") or os.environ.get("AMASS_API_KEY")
    amass_credits_box: list = []
    amass_credits_thread: threading.Thread | None = None
    if amass_key:
        amass_credits_thread = threading.Thread(
            target=lambda: amass_credits_box.append(amass_tool.get_credits(amass_key)), daemon=True
        )
        amass_credits_thread.start()

    _emit(on_event, {"type": "start", "run_id": state.run_id, "question": question})

    try:
        provider = get_provider(api_keys, tier="main")
    except NoProviderAvailable as exc:
        state.partial = True
        report_text = (
            "## No LLM Provider Available\n\n"
            f"{exc}\n\n"
            "No report could be generated."
        )
        _emit(on_event, {"type": "error", "error": str(exc), "error_code": "no_llm_key_configured"})
        cost_summary = build_cost_summary(state, None, api_keys)
        result = {
            "run_id": state.run_id, "question": question, "report": report_text,
            "partial": True, "cancelled": False, "trace": [], "evidence": {},
            "cost": cost_summary, "hypotheses": [],
        }
        _emit(on_event, {"type": "done", "report": report_text, "partial": True, "cancelled": False,
                          "run_id": state.run_id, "cost": cost_summary, "evidence": {}, "hypotheses": []})
        return result

    _emit(on_event, {"type": "phase", "phase": "grounding"})
    grounding = _grounding_payload(question, state, on_event, mode, amass_credits_thread, amass_credits_box, api_keys)
    grounding_text = _grounding_text(grounding)
    _emit(on_event, {"type": "grounding", **grounding})

    no_tool_nudges = 0
    try:
        # --- PLAN ---
        candidate_count = len(grounding.get("hypotheses") or [])
        _emit(on_event, {"type": "phase", "phase": "plan", "detail": {"candidates": candidate_count}})
        transcript.add_user_text(_plan_message(grounding_text, candidate_count))
        plan_resp = _stream_message(
            provider, on_event, "plan", {"candidates": candidate_count},
            transcript=transcript, max_tokens=1536,
        )
        state.record_anthropic_tokens(plan_resp.usage, plan_resp.model)
        transcript.add_assistant(plan_resp)
        raw_plan_hyps = _parse_hypotheses(plan_resp.text)
        if grounding.get("hypotheses"):
            raw_plan_hyps = _adopt_candidates(raw_plan_hyps, grounding["hypotheses"])
        state.hypotheses = _normalize_hypotheses(raw_plan_hyps, "plan", {}, set(state.evidence))
        _emit(on_event, {"type": "hypotheses", "stage": "plan", "hypotheses": state.hypotheses})
        transcript.add_user_text(_PLAN_TO_ACT_NUDGE)

        _emit(on_event, {"type": "phase", "phase": "plan_and_gather"})

        while True:
            if should_cancel and should_cancel():
                state.cancelled = True
                state.partial = True
                break
            if state.budget_exceeded(reserve_seconds=REPORT_RESERVE_SECONDS):
                state.partial = True
                break

            response = provider.create(system=SYSTEM_PROMPT, transcript=transcript, tools=tools, max_tokens=4096)
            state.record_anthropic_tokens(response.usage, response.model)
            transcript.add_assistant(response)

            text = response.text
            if text.strip():
                _emit(on_event, {"type": "assistant_text", "text": text})

            if response.stop_reason != "tool_use":
                if state.tool_calls_made == 0 and no_tool_nudges < MAX_NO_TOOL_NUDGES:
                    no_tool_nudges += 1
                    transcript.add_user_text(_NUDGE_NO_TOOLS)
                    continue
                break

            tool_use_blocks = response.tool_calls

            # Cancel/budget are evaluated once for the whole batch rather than
            # per block: the calls below run concurrently, so there is no
            # meaningful "already dispatched vs. not yet" boundary mid-batch
            # to check between them the way there was in sequential dispatch.
            cancelled_now = bool(should_cancel and should_cancel())
            if cancelled_now:
                state.cancelled = True
            budget_exhausted = state.budget_exceeded(reserve_seconds=REPORT_RESERVE_SECONDS)
            remaining_budget = max(0, state.max_tool_calls - state.tool_calls_made)

            to_run: list[int] = []
            skip_reason: dict[int, str] = {}
            for i, block in enumerate(tool_use_blocks):
                if cancelled_now:
                    skip_reason[i] = "Run cancelled by the user; call skipped."
                elif budget_exhausted or len(to_run) >= remaining_budget:
                    skip_reason[i] = "Tool budget exceeded for this run; call skipped."
                else:
                    to_run.append(i)

            # Announce every call that will actually run, in original order,
            # before dispatching — the step numbers assigned here are exactly
            # the trace positions they'll land on below (trace insertion
            # happens in this same order), so tool_call/tool_result SSE
            # events always agree on `step` regardless of completion order.
            base_step = len(state.trace)
            for position, i in enumerate(to_run):
                block = tool_use_blocks[i]
                _emit(
                    on_event,
                    {"type": "tool_call", "tool": block.name, "args": block.input, "step": base_step + 1 + position},
                )
                if block.name == "amass":
                    _resolve_amass_credits_before(state, amass_credits_thread, amass_credits_box, amass_key)

            # Independent tool calls requested in one turn are run side by
            # side instead of one after another — this is the same reasoning
            # (and the same ThreadPoolExecutor pattern) already used for
            # grounding link verification, backend/grounding/premises.py.
            # Results are gathered back in original block order below, so the
            # trace/evidence/report content is identical to running them
            # sequentially; only the wall-clock time changes (bounded by the
            # slowest call in the batch instead of their sum).
            run_results: dict[int, dict] = {}
            if to_run:
                with ThreadPoolExecutor(max_workers=len(to_run)) as pool:
                    futures = {
                        pool.submit(
                            run_tool, tool_use_blocks[i].name, tool_use_blocks[i].input,
                            enabled_names=state.enabled_tools, api_keys=api_keys,
                        ): i
                        for i in to_run
                    }
                    for future, i in futures.items():
                        run_results[i] = future.result()

            tool_results: list[ToolResult] = []
            for i, block in enumerate(tool_use_blocks):
                if i in skip_reason:
                    tool_results.append(ToolResult(tool_call_id=block.id, content=skip_reason[i]))
                    continue

                result = run_results[i]
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

                tool_results.append(ToolResult(tool_call_id=block.id, content=content_text))

            transcript.add_tool_results(tool_results)

        # --- REVISE ---
        revise_detail = {"hypotheses": len(state.hypotheses), "evidence": len(state.evidence), "tool_calls": state.tool_calls_made}
        _emit(on_event, {"type": "phase", "phase": "revise", "detail": revise_detail})
        transcript.add_user_text(REVISE_PROMPT)
        revise_resp = _stream_message(
            provider, on_event, "revise", revise_detail, transcript=transcript, max_tokens=2048,
        )
        state.record_anthropic_tokens(revise_resp.usage, revise_resp.model)
        transcript.add_assistant(revise_resp)
        revise_text, raw_revise_hyps = _extract_hypotheses(revise_resp.text)
        if revise_text.strip():
            _emit(on_event, {"type": "assistant_text", "text": revise_text})
        normalized_revise = _normalize_hypotheses(
            raw_revise_hyps, "revise", {h["id"]: h for h in state.hypotheses}, set(state.evidence)
        )
        if normalized_revise:
            state.hypotheses = normalized_revise
        _emit(on_event, {"type": "hypotheses", "stage": "revise", "hypotheses": state.hypotheses})

        # --- REPORT ---
        report_detail = {"sections_total": len(REPORT_SECTIONS), "evidence": len(state.evidence), "hypotheses": len(state.hypotheses)}
        _emit(on_event, {"type": "phase", "phase": "report", "detail": report_detail})
        report_instructions = final_report_prompt(state.citation_index())
        if state.cancelled:
            report_instructions = CANCELLED_RUN_NOTICE + "\n\n" + report_instructions
        elif state.partial:
            report_instructions = PARTIAL_RUN_NOTICE + "\n\n" + report_instructions
        transcript.add_user_text(report_instructions)
        report_resp = _stream_message(
            provider, on_event, "report", report_detail, transcript=transcript, max_tokens=8192,
        )
        state.record_anthropic_tokens(report_resp.usage, report_resp.model)
        report_text, raw_final_hyps = _extract_hypotheses(report_resp.text)
        normalized_final = _normalize_hypotheses(
            raw_final_hyps, "final", {h["id"]: h for h in state.hypotheses}, set(state.evidence)
        )
        if normalized_final:
            state.hypotheses = normalized_final
        _emit(on_event, {"type": "hypotheses", "stage": "final", "hypotheses": state.hypotheses})

    except _KEY_INVALID_ERRORS as exc:
        state.partial = True
        report_text = (
            "## LLM Key Invalid\n\n"
            f"The API key in Settings was rejected by the provider (`{exc}`). "
            "Double-check it, or generate a fresh one (Anthropic Console, or "
            "openrouter.ai/keys for a free OpenRouter key) and paste it into Settings.\n\n"
            f"Evidence gathered before the failure ({len(state.evidence)} items) is listed below "
            "for debugging; no hypothesis ranking was completed.\n\n" + state.citation_index()
        )
        _emit(on_event, {"type": "error", "error": str(exc), "error_code": "llm_key_invalid"})
    except Exception as exc:
        state.partial = True
        report_text = (
            f"## Run Error\n\nThe agent run failed with an unrecoverable error: `{exc}`.\n\n"
            f"Evidence gathered before the failure ({len(state.evidence)} items) is listed below "
            "for debugging; no hypothesis ranking was completed.\n\n" + state.citation_index()
        )
        _emit(on_event, {"type": "error", "error": str(exc)})

    if state.amass_credits_before is not None:
        state.amass_credits_after = amass_tool.get_credits(amass_key)
    cost_summary = build_cost_summary(state, provider, api_keys)
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
