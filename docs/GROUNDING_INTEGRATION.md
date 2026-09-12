# Grounding integration entry point

Hook **unverified premises + knowledge graph** extraction into this repo
*before* hypothesis generation (PLAN). The extractor lives in another
repo; this file is the map of where it should land here.

Do not hook `on_event`. That callback is one-way (`None` return) and is
not read by the loop. PLAN never sees the `start` SSE payload.

## Insert here

File: [`backend/agent/loop.py`](../backend/agent/loop.py)
Function: `run_agent`

The gap is after the first `_emit` and before the `PLAN` block:

```python
messages: list[dict] = [{"role": "user", "content": f"Research question: {question}"}]

_emit(on_event, {"type": "start", "run_id": state.run_id, "question": question})

# === INTEGRATE HERE ===
# premises, graph = <other-repo extractor>(question)
# state.unverified_premises = premises
# state.knowledge_graph = graph
# optional: _emit(on_event, {"type": "grounding", "premises": premises, "knowledge_graph": graph})

# --- PLAN ---
_emit(on_event, {"type": "phase", "phase": "plan"})
messages.append({"role": "user", "content": plan_prompt()})
```

Input to the extractor: `question` (`str`), already on `RunState.question`
and in `messages[0]`.

Output must reach PLAN by changing `plan_prompt()` — do not rely on the
`start` event.

## Pass into PLAN

File: [`backend/agent/prompts.py`](../backend/agent/prompts.py)
Function: `plan_prompt() -> str`  (no args today)

Change the signature so PLAN is grounded on the extractor output, e.g.
`plan_prompt(premises, graph) -> str`. Keep the existing fenced
`{"hypotheses": [{statement, seed_question}]}` schema; `_parse_hypotheses`
/ `_normalize_hypotheses` in `backend/agent/loop.py` depend on it.

Persist on [`backend/agent/state.py`](../backend/agent/state.py)
`RunState` (fields `unverified_premises`, `knowledge_graph`) if REVISE /
REPORT should see the same graph later.

## Do not use these as the entry point

| Path | Symbol | Why not |
|---|---|---|
| [`backend/server/app.py`](../backend/server/app.py) | `start_run` → inner `on_event` | Appends to `_run_events` and wakes SSE. Return value is discarded. CLI never hits this. |
| [`backend/agent/loop.py`](../backend/agent/loop.py) | `_emit` / first `{"type": "start", ...}` | Notification only. PLAN does not read it. |
| [`scripts/run_demo.py`](../scripts/run_demo.py) | `on_event` | Prints phase/tool events; ignores `start`. |
| [`frontend/src/lib/runStream.ts`](../frontend/src/lib/runStream.ts) | `ensureStream` | UI subscriber, after the fact. |
| [`frontend/src/types.ts`](../frontend/src/types.ts) | `SseEvent` `type: "start"` | `{ run_id, question }` only. Extend only if the UI should show grounding. |

## Callers of `run_agent` (no change required)

Both already pass `question` through. Hooking inside `run_agent` covers both.

- [`backend/server/app.py`](../backend/server/app.py) — `start_run` → `run_agent(req.question, on_event=..., run_id=...)`
- [`scripts/run_demo.py`](../scripts/run_demo.py) — `run_agent(question, on_event=...)`

UI question box (not an integration point):
[`frontend/src/components/ComposeBox.tsx`](../frontend/src/components/ComposeBox.tsx)
→ [`frontend/src/App.tsx`](../frontend/src/App.tsx) `handleRun` → `POST /api/run`.

## Optional UI event

If the SPA should render premises / the graph, emit a new event after
extraction (prefer `type: "grounding"` over stuffing `start`) and add it
to `SseEvent` in [`frontend/src/types.ts`](../frontend/src/types.ts).
Event inventory lives in [`docs/UX_SPEC.md`](UX_SPEC.md).
This is display-only and is not how PLAN receives the data.

## Shape to implement (other repo)

```
question: str
    → unverified_premises
    → knowledge_graph
    → plan_prompt(premises, graph)   # hypothesis generation (h1..hN)
```
