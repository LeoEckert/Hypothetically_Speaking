# QA findings: browser-driven audit, 2026-09-12

Fourteen findings from driving the real agent loop through Chromium with
Playwright. Audited `main` @ `8967e8a`; harness committed on branch
`claude/qa-playwright` as [`qa/`](../qa/README.md).

Nothing here is fixed. This file exists so the fixes get made deliberately,
with the evidence attached. See [`docs/UX_SPEC.md`](UX_SPEC.md) for the
intended progress/results behaviour that several of these violate.

**Method.** Local backend (`uvicorn`) + local `vite dev`, real
`ANTHROPIC_API_KEY`, every other tool on its documented mock fallback.
Seven runs at tool budgets 2–30. No part of the agent loop was mocked.
Findings were read out of the persisted store (`localStorage` key
`hs_history_v3`) rather than scraped from rendered text, since the page
copy is itself under test.

**Reproducing.** See [`qa/README.md`](../qa/README.md). Five specs in
`qa/tests/regressions.spec.ts` encode HS-01 through HS-04 and are expected
to fail until fixed — they are the regression net, not a green baseline.

## Does this apply to production?

Testing ran against local `main`, while Vercel serves a different branch
(HS-13), so this was checked rather than assumed. The deployed branch is an
*ancestor* of `main` (5 behind, 0 ahead), so `main` cannot have introduced
these bugs.

| Check | Result |
|---|---|
| Source diff of the three files carrying HS-01..03 | `App.tsx`, `LiveRunBar.tsx`, `runStream.ts` byte-identical between deployed branch and `main` |
| The two files that *do* differ | `runsStore.ts`, `app.py` — additive grounding/trajectory code only; never touch `markErrored`, the status transitions, or `get_result` |
| Dead status strings in the live bundle | all four present (`"partial run"`, `"budget limit reached"`, `"cancelled by you"`, `"run failed"`) |
| Watchdog in the live bundle | zero occurrences of `keepalive` / `watchdog` / `lastMessage` |
| Recovery path in the live bundle | references `/cancel`, `/evaluate`, `/stream` — **never** `/result` |

**Net: 10 of 14 findings apply to production unchanged, including all three
criticals.** The exception is the grounding work — HS-06 exercises code
production does not ship yet.

Caveat, stated plainly: the *behaviour* was reproduced on `main` and the
prod *code* verified identical. The browser tests were not re-run against
the live site. `HS_BASE_URL=https://<deploy>.vercel.app npm test` would
settle it directly, at the cost of some Anthropic/Tavily credit per run.

## Index

| ID | Severity | Finding | In prod |
|---|---|---|---|
| HS-01 | Critical | Every terminal run state is computed and thrown away | yes |
| HS-02 | Critical | Reloading mid-run abandons a healthy run and marks it failed | yes |
| HS-03 | High | No client-side liveness watchdog — a dead backend reads as "still running" | yes |
| HS-04 | Medium | Tool budget under ~10 silently skips the one mandatory computed step | yes |
| HS-05 | Medium | Cancel takes ~90s behind an unexplained "cancelling…" | yes |
| HS-06 | Low | Grounding pipeline no-ops without an Amass key | `main` only |
| HS-07 | Low | `.env.example` is a 0-byte file | yes |
| HS-08 | Low | Human-facing UI shows model-facing tool descriptions verbatim | yes |
| HS-09 | Low | Empty search results become citable evidence | yes |
| HS-10 | Low | Cost panel files Anthropic under "Tool activity" | yes |
| HS-11 | Low | Partial-run caveat hides in a collapsed accordion | yes |
| HS-12 | Low | Budget field resists editing | yes |
| HS-13 | Note | The live deployment is a different app than `main` | n/a |
| HS-14 | Note | Finished reports are on disk but unreachable after a restart | yes |

## HS-01 — Every terminal run state is computed and thrown away

**Severity:** critical. **Files:** `frontend/src/App.tsx:122-131`,
`frontend/src/components/LiveRunBar.tsx:19`.

`App.tsx` builds exactly the right copy for every terminal state:

```
if (viewedRun.status === "done")      return "done"
if (viewedRun.status === "partial")   return "done (partial run — budget limit reached)"
if (viewedRun.status === "cancelled") return "done (cancelled by you)"
if (viewedRun.status === "error")     return "run failed — see trace"
```

Its only consumer is `LiveRunBar`, which opens with:

```
if (!isRunning && !showLiveBanner) return null
```

`isRunning` is true only for `running`/`cancelling`, so the component
unmounts at exactly the moment those four strings become true. All four are
dead code.

**Observed.** A budget-exhausted run (`status: "partial"`) and a run
cancelled by hand (`status: "cancelled"`) both rendered a results view with
no mention of either fact. The only matching string on the page was the
cost panel's `partial estimate` badge — which refers to the cost estimate,
not the run.

**Impact.** A truncated run, a cancelled run, and a **failed** run are
visually identical to a clean success, hypotheses still carrying confidence
badges. Only the history panel's amber border (`HistoryList.tsx:14`)
survives as a signal.

**Fix direction.** Render terminal status in the results view, not the live
bar. One-line stopgap: drop the early return when `statusText` is non-empty.

## HS-02 — Reloading mid-run abandons a healthy run and marks it failed

**Severity:** critical. **Files:** `frontend/src/App.tsx:88`,
`frontend/src/lib/runStream.ts:46-48`, `frontend/src/store/runsStore.ts:162`.

Two independent gaps:

1. `ensureStream()` is called from exactly one place — `App.tsx:88`, inside
   `handleRun`. Nothing re-attaches on mount.
2. The page-unload teardown fires `es.onerror` → `markErrored` → `save()`
   before navigation, so the reload itself writes the `error` status that
   the fresh page then reads back.

**Observed.** Run `e6354f5b`, budget 30, reloaded at 24 events. The store
flipped `running` → `error` and never recovered. The backend finished the
run anyway: `backend/reports/e6354f5b.json` is 276 KB, `partial: false`, a
full six-section report, with `extract_genes` and `run_enrichment` both
called. The user paid for that report and never saw it.

**Contradicts documented behaviour.** `CLAUDE.md` states the stream
"replays everything so far … so a reload or a late 'view live run' attach
never misses or double-delivers events." The backend honours that fully
(`app.py:166-198`, per-connection read position). The frontend never asks.

**Fix direction.** On mount, re-attach to any run still `running`; fall
back to `GET /api/run/{run_id}/result`. Don't mark errored during
`pagehide`/`beforeunload`.

## HS-03 — No client-side liveness watchdog

**Severity:** high. **File:** `frontend/src/lib/runStream.ts:46-48`.

The client's only failure path is `es.onerror`. It never fires when the
server process dies.

**Observed.** Killed the `uvicorn` process mid-run (verified: no process,
nothing listening on port 8000). For 60+ seconds the instrumented
`EventSource` held `readyState === 1` (OPEN), fired **zero** error events,
logged nothing to the console, and the UI sat on "Report — writing the final
report…" with a live Cancel button.

**Why.** The backend emits `: keepalive` every 15s precisely because
multi-minute gaps between events are normal (`app.py:186-196`). Nothing on
the client checks that keepalives still arrive, so a slow agent and a dead
backend are indistinguishable.

**Fix direction.** Track last-message time; if it exceeds ~45s (three
missed keepalives), show a reconnecting state and re-open the stream. The
server-side replay makes reconnection safe. Shares the re-attach path with
HS-02.

## HS-04 — Tool budget under ~10 silently skips the mandatory computed step

**Severity:** medium. **Files:** `backend/agent/loop.py:335,374-379`,
`frontend/src/components/ComposeDialog.tsx:57-71`.

Measured across four budgets:

| Budget | Tool calls used | `partial` | Enrichment ran |
|---|---|---|---|
| 30 (default) | 20 | `false` | yes |
| 10 | 10 | `true` | no |
| 6 | 6 | `true` | no |
| 3 | 2 | `true` | no |

`extract_genes` → `run_enrichment` is what `CLAUDE.md` calls the one
required "real computed result, not summarization" step. Below ~10 the
agent spends its whole budget on retrieval and never arrives. At budget 6
the agent's own top recommendation became *"complete the in-silico pipeline
that this run did not finish."*

**Root cause.** `loop.py` never tells Claude how much budget remains. It
only checks `state.budget_exceeded()` after the fact and injects
`"Tool budget exceeded for this run; call skipped."` The model spends
freely, then gets cut off.

**Fix direction.** Warn in the compose controls below ~12 — they currently
read only `"Run / Tool budget: / (max 40)"` — and surface remaining budget
to the model so it can reserve two calls for compute. Note the default path
is safe; this is a guardrail gap, not a broken happy path.

## HS-05 — Cancel takes ~90s behind an unexplained "cancelling…"

**Severity:** medium. **File:** `backend/agent/loop.py` (`should_cancel`).

Clicked Cancel at t+25s; status reached `cancelled` at t+115s. Ninety
seconds of "cancelling…" with no indication that a wait is expected.
`should_cancel` is only checked between turns, so an in-flight Anthropic
call must finish first — correct behaviour, unexplained to the user. Then
HS-01 means the cancellation is never confirmed either.

**Fix direction.** Say what's happening: "finishing the current step — up
to ~90s".

## HS-06 — Grounding pipeline no-ops without an Amass key

**Severity:** low (but see note). **`main` only.** **File:**
`backend/agent/loop.py:52-67`.

Every data tool degrades to a mock when its key is missing — the documented
tool contract. Grounding instead skips wholesale: `_grounding_payload`
checks `_GROUNDING_KEYS = ("ANTHROPIC_API_KEY", "AMASS_API_KEY")` and, if
either is absent, returns `status: "skipped"` with `why: "Missing …"` and
empty triples/premises/hypotheses. The UI renders that as
`Grounding skipped: Missing AMASS_API_KEY` — a small grey line inside a
collapsed panel.

The L0–L4 pipeline is the largest thing on `main` (~1,800 new lines across
`backend/grounding/`, `backend/kgviz/`, `GroundingTrace.tsx`) and is
invisible in the default local setup. It is also, consequently, the surface
this audit could not exercise at all — worth a dedicated pass once a key is
available and the deploy is reconciled.

## HS-07 — `.env.example` is a 0-byte file

**Severity:** low. **File:** `.env.example`.

`CLAUDE.md` instructs `cp .env.example .env` then "fill in
`ANTHROPIC_API_KEY`, `TAVILY_API_KEY`, `AMASS_API_KEY`, `NEBIUS_API_KEY`",
but the file is empty — a new contributor gets no scaffold and no hint
which keys are optional. (`frontend/.env.example` is well commented by
contrast.) Worth recording that `ANTHROPIC_API_KEY` alone is sufficient for
a working local run, since everything else mock-falls-back.

## HS-08 — Human-facing UI shows model-facing tool descriptions verbatim

**Severity:** low. **Files:** `backend/tools/*.py` (`SPEC["description"]`),
surfaced by `ToolsPanel`.

The Tools panel prints each tool's Claude prompt text, internal names and
all: "call it once you have a candidate gene list from `extract_genes`",
"g:Profiler g:GOSt", "treat the result as computed evidence, not text".
These are instructions to a model, addressed to a person.

Each row also pairs an `enabled` badge with an already-on toggle, saying
the same thing twice.

**Fix direction.** A separate short `ui_description` on `SPEC`, or a
display-name/blurb map in the frontend.

## HS-09 — Empty search results become citable evidence

**Severity:** low. **Files:** `backend/tools/pubmed_tool.py`,
`backend/agent/state.py` (evidence registry).

"No PubMed results for 'resveratrol SIRT1 AMPK off-target mechanism'." was
registered as evidence item #3 with its own citation ID. A null result is a
fact about the search, not evidence about biology, and it inflates the
evidence count (35 items from 10 tool calls in one run).

## HS-10 — Cost panel files Anthropic under "Tool activity"

**Severity:** low. **File:** `frontend/src/components/CostPanel.tsx`.

"Anthropic — 5 calls" sits in the same list as PubMed and Open Targets.
Anthropic is the agent, not a tool it called; listing them together makes
the tool trace read as five more retrievals.

## HS-11 — Partial-run caveat hides in a collapsed accordion

**Severity:** low.

On a truncated run, the "Confidence & Uncertainty" section contains the
entire disclosure: *"This was a partial run."* Four words, collapsed by
default, while a `medium confidence` badge sits prominently at the top.
Compounds HS-01.

## HS-12 — Budget field resists editing

**Severity:** low. **File:**
`frontend/src/components/ComposeDialog.tsx:64-67`.

Clearing the field to retype snaps back to the last clamped value: the
`Number.isNaN` guard skips the state update on an empty string while the
input stays controlled. Clamping itself is correct (`0` → `1`, `999` → `40`).

## HS-13 — The live deployment is a different app than `main`

**Severity:** note. See [`docs/DEPLOY.md`](DEPLOY.md).

Vercel's production branch is `claude/gracious-curie-lkjlq1`. The deployed
bundle contains zero occurrences of grounding/premise/trajectory, and the
deployed backend's OpenAPI has no `/api/trajectory` endpoints. Anything
tested against the live URLs is testing the previous app.

Production **redeployed during this audit** — the bundle hash moved from
`index-CMNwUzlh.js` to `index-h6DvIYDP.js`. The new bundle still has zero
grounding references, so it redeployed the same non-`main` branch. The
branch is evidently still receiving deploys.

Reconciling this is a deploy change on a live URL, so it is left as a
decision rather than a fix. Worth settling before any demo, or the
grounding work is not in what people see.

## HS-14 — Finished reports are on disk but unreachable after a restart

**Severity:** note; pre-existing and already documented. **File:**
`backend/server/app.py:199-201`.

`get_result` is `_results.get(run_id, {"status": "not_ready"})` — memory
only, though the worker already wrote `backend/reports/{run_id}.json`.
`CLAUDE.md` documents the in-memory limitation, so this is not new. Flagged
because the fix is now a two-line disk fallback, and it is also the cheapest
half of an HS-02 fix.

Related shape mismatch: the not-ready sentinel returns a `status` key, but a
real result object has no `status` field at all (it carries `partial` and
`cancelled` booleans instead).

## Verified working

Checked deliberately, held up under real runs. Recorded so fixes aren't
aimed at the wrong layer.

- **Citation resolution** — zero raw `[PMID:…]`-style markers left
  unresolved in rendered reports.
- **The default path completes** — budget 30 finishes `partial: false` with
  a genuine g:Profiler enrichment.
- **Responsive at 390px** — no horizontal overflow; the report reflows
  cleanly.
- **Zero console or page errors** — across seven runs, including the crash
  and cancel scenarios.
- **Input validation** — whitespace-only questions disable Run; budget
  clamps at both ends.
- **Server-side SSE replay** — the per-connection read position works
  exactly as documented.
- **History migration and quota handling** — the v2→v3 backfill and the
  quota-shedding `save()` are sound.
- **Report structure** — all six prose sections present, including
  "Evidence That Doesn't / Contradicts It".

## Suspected and ruled out

Recorded so they aren't re-investigated.

1. **Unlabelled header icon buttons.** They carry `title` attributes
   ("History", "How it works"), which serves as a last-resort accessible
   name. Weak, not broken.
2. **Hypotheses stuck "unevaluated".** They do get re-ranked and scored —
   `h3` was promoted to rank 1 and selected. The earlier observation was a
   mid-REPORT snapshot.
3. **Missing "Evidence Against" section.** Present as "Evidence That
   Doesn't / Contradicts It"; an exact-string probe missed it.
4. **Report omits the "Tool Trace" section** `CLAUDE.md` specifies. True,
   but the UI provides a Tool-call trace panel instead, so this looks
   deliberate rather than a defect.

## Suggested order of work

1. **Render terminal status in the results view** (HS-01) — smallest diff,
   largest honesty gain; it currently hides failure, cancellation and
   truncation at once.
2. **Re-attach to in-flight runs on mount, with a result fallback**
   (HS-02 + HS-14) — the backend already supports both halves; stops losing
   finished reports.
3. **Add a keepalive watchdog and a reconnecting state** (HS-03) — depends
   on the same re-attach path, so it lands cheaply once that exists.
4. **Warn on low budgets; tell the model what's left** (HS-04) — prevents
   structurally incomplete runs being presented as confident ones.
5. **Reconcile the Vercel deployment with `main`** (HS-13) — before any
   demo, or the grounding work isn't in what people see.
