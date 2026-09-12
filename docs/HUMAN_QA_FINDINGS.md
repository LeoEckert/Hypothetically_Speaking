# Human QA findings

Bugs found by a person using the app, reported with screenshots and
annotations. Each entry is then traced to the responsible code and given a
suggested fix.

Companion to `docs/QA_FINDINGS.md`, which covers the automated Playwright
pass. That file's findings are `HS-nn`; this file's are `HQ-nn`.

> **Note:** `docs/QA_FINDINGS.md` is not on `main` yet — it arrives with PR
> #1 (branch `claude/qa-playwright`). The `HS-nn` references below resolve
> once that merges.

The two are complementary — exploratory human use keeps surfacing
interaction bugs that scripted runs don't, because a script does one thing
at a time and a person does not.

This file is appended to as more findings come in.

## Index

| ID | Severity | Finding | Verified against |
|---|---|---|---|
| HQ-01 | High | Cancel is not bound to a run — it always cancels the newest one | `main` @ `c3a958e` |
| HQ-02 | High | Starting a second run silently orphans the first, which sticks at "running" forever | `main` @ `c3a958e` |
| HQ-03 | Medium | Report sections render as bullets in one run and a prose wall in the next | `main` @ `c3a958e` |

---

## HQ-01 — Cancel is not bound to a run; it always cancels the newest

**Severity:** high. **Reported:** screenshot, two runs live at once.

**What the tester saw.** With more than one run in a non-terminal state,
clicking Cancel while looking at an older run cancelled the *most recent*
run instead. In the screenshot the newest run ("Is it probable that a
consumer taking many supplements…", 15:21:32) carries the `cancelling`
badge, while an older SIRT1 run (14:14:52) is still `running`.

A second symptom in the same screenshot: the live run bar shows the **SIRT1**
question text while the hypotheses panel below shows the **supplements**
hypotheses. The header and the body are describing two different runs.

**Confirmed in code.** `frontend/src/App.tsx:92-96`:

```js
function handleCancel() {
  if (!liveRunId) return
  markCancelling(liveRunId)
  cancelRun(liveRunId)
}
```

This is not mis-targeting by list position — Cancel is not bound to a row at
all. There is exactly one Cancel button, inside `LiveRunBar`
(`LiveRunBar.tsx:84`), and it always acts on `liveRunId`, which `handleRun`
sets to the last run started (`App.tsx:85`). Which run the user is *viewing*
(`viewedRunId`) never enters the decision.

History rows offer only `onSelect` and `onDelete` (`HistoryList.tsx:50,65`) —
there is no per-row cancel to bind to.

The backend is not at fault: `POST /api/run/{run_id}/cancel`
(`app.py:172-177`) resolves `_cancel_events[run_id]` correctly per run. It
cancels exactly the run it is told to. It is told the wrong one.

**Suggested fix.** Pass the run id explicitly rather than reading ambient
state:

```js
function handleCancel(runId: string) {
  markCancelling(runId)
  cancelRun(runId)
}
```

Have `LiveRunBar` pass the id of the run it is actually displaying, and add a
per-row cancel control in `HistoryList` for any row whose status is
`running`/`cancelling`. While the single-live-run assumption holds (HQ-02),
also make the live bar and the results body render the *same* run, so the
mismatched header/body state cannot appear.

---

## HQ-02 — Starting a second run silently orphans the first

**Severity:** high. **Reported:** same screenshot — an older run stuck at
`running` indefinitely.

**What the tester saw.** A run from 14:14:52 sitting at `running` long after
newer runs had completed, and the question *"maybe we cannot actually do
several runs at once right?"*

**Answer: the backend can, the frontend cannot.**

*Backend — fully concurrent.* `POST /api/run` starts a daemon thread per run
(`app.py:167`), and `_run_events`, `_wakeups` and `_cancel_events` are each
keyed by `run_id` (`app.py:140-143`). Tool toggles are process-global, but
`run_tool` takes a snapshot of `enabled_tools` at run start, so concurrent
runs do not corrupt each other's tool roster.

*Frontend — single-slot throughout.* `frontend/src/lib/runStream.ts` holds
one `currentRunId` and one `currentSource` (lines 9-10), and `App.tsx` holds
a single `liveRunId` (line 22). `ensureStream` (lines 18-24):

```js
if (currentRunId === runId && currentSource) return
currentSource?.close()
currentRunId = runId
```

Starting run B therefore **closes run A's EventSource**. Critically, a manual
`.close()` does not fire `onerror`, so the `es.onerror` handler
(`runStream.ts:46-49`) never runs for A — no `markErrored`, no `finish()`,
no `stream_end`. Run A is silently orphaned and its store record stays
`running` forever, which is exactly the 14:14:52 row.

**How two runs became live at all.** `runDisabled={liveRunId !== null}`
(`App.tsx:166`) is meant to prevent it, but `liveRunId` is cleared whenever
`onStreamFinished` fires — and `finish()` fires it on **both** `stream_end`
*and* `es.onerror` (`runStream.ts:43,48`) — or by any page reload, since
`currentRunId` is module state that resets. So a single stream hiccup or one
reload re-enables the Run button while the backend run continues, and keeps
billing.

This is downstream of `HS-02`/`HS-03` in `docs/QA_FINDINGS.md`: the same missing
re-attach path that loses finished reports is what lets unintended
concurrency happen.

**Suggested fix.** This needs a product decision first, because the two
halves currently disagree about whether concurrency exists.

*Option A — honour the single-run assumption.* Make the guard authoritative:
derive "is a run live" from the store (any record with status
`running`/`cancelling`) rather than from module state that resets on reload,
and refuse to start a second run while one is live, with a visible reason.
Cheapest, and removes the orphaning entirely.

*Option B — support concurrency properly.* Replace the two singletons with a
`Map<runId, EventSource>`, let `liveRunId` become a set, and give each
history row its own status and cancel control. More work, but it is what the
backend already supports and what the tester intuitively expected.

Either way, `ensureStream` should never close a stream for a run that has not
reached a terminal state without marking that run — an orphaned `running`
record is the worst outcome, since it is indistinguishable from a healthy
in-flight run.

---

## HQ-03 — Report sections render as bullets in one run and a prose wall in the next

**Severity:** medium (readability). **Reported:** side-by-side screenshot of
"Confidence & Uncertainty" from two different runs.

**What the tester saw.** The same section, same product, two runs:

- **Left run** — four scannable bullets, each opening with a bolded
  confidence level ("**High confidence** that shared CYP450/P-glycoprotein
  machinery…", "**Moderate confidence** that…", "**Low confidence, not
  stated as established fact**…").
- **Right run** — one unbroken ~200-word paragraph carrying the same kind of
  content ("I have **medium-high** confidence that… I have **medium**
  confidence in h1… I have **low** confidence in h4…").

Tester's note: *"different formats of the same section in different runs ->
enforce bullets - it's easier to read"*.

The right-hand version is not worse *reasoning* — it is arguably richer. It
is worse *reading*: a per-hypothesis confidence breakdown is a list by
nature, and rendering it as a wall of prose forces the reader to parse
sentences to recover a structure that was already there.

**Confirmed in code.** The report contract lives in
`backend/agent/prompts.py:38-44` (`SYSTEM_PROMPT`) and specifies the six
section *headings* exactly:

```
5. REPORT: write the final answer as markdown with these exact sections:
   ## Hypothesis
   ## Evidence That Supports It
   ## Evidence That Doesn't / Contradicts It
   ## Confidence & Uncertainty
   ## Failure Modes
   ## Next Experiment To Run
```

Nothing anywhere specifies the *body* format of any section. The only style
guidance in the whole prompt is a single line — "Be concise and precise —
this report should be readable in one pass by a clinician or investor, not a
literature dump" (`prompts.py:57-58`). `final_report_prompt`
(`prompts.py:135-147`) adds nothing either: it says to follow "the exact
section structure and citation rules from your system prompt", and
"structure" there means headings only.

So the heading set is pinned and the body format is entirely unconstrained.
Run-to-run variation is the expected outcome, not a glitch — the model is
free to choose, and it does, differently each time.

This is a determinism problem as much as a style one: two runs of the same
product produce visibly different-looking documents, which undercuts the
"defensible report" framing.

**Suggested fix.** Add an explicit body-format rule to the section spec in
`SYSTEM_PROMPT`. For example, after the section list:

```
   Body format, so reports read the same way every run:
   - Confidence & Uncertainty, Failure Modes, Evidence That Supports It,
     and Evidence That Doesn't / Contradicts It: markdown bullets, one
     claim per bullet, each ending in its citation marker.
   - Confidence & Uncertainty: open each bullet with a bolded confidence
     level, e.g. "**High confidence** that …".
   - Hypothesis and Next Experiment To Run: prose, at most one short
     paragraph each.
```

Two judgement calls worth making deliberately rather than inheriting:

1. **Not every section wants bullets.** `## Hypothesis` is a single claim and
   reads better as one sentence; `## Next Experiment To Run` is a narrative
   recommendation. The tester's "enforce bullets" is clearly aimed at the
   list-like sections — applying it everywhere would make the report choppy.
2. **Bullets must not cost the citation discipline.** Every factual sentence
   still has to end in a resolvable `[citation-id]`
   (`scripts/validate_citations.py` enforces ≥95% coverage). Whichever
   wording is adopted, re-run that validator afterwards — a format change to
   the prompt is exactly the kind of edit that can quietly drop citation
   markers.

---

## Related: findings status on `main` @ `c3a958e`

Re-checked while verifying the above, since 17 commits landed after the
Playwright audit:

- **HS-13 (deployment pinned to the old branch) is fixed.** Both
  `deploy-backend.yml` and the new `deploy-frontend.yml` now trigger on
  `push: branches: [main]`.
- **HS-01 still stands.** `LiveRunBar.tsx:63` retains
  `if (!isRunning && !showLiveBanner) return null`, and `App.tsx:128-130`
  still builds the three terminal strings that nothing renders. Line numbers
  have shifted from those quoted in `QA_FINDINGS.md`.
