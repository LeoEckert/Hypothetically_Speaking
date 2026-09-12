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
| HQ-04 | Medium | The original research question disappears from both the results and full-report views | `main` @ `c3a958e` |
| HQ-05 | Medium | Collapsed section preview shows only the list marker ("1.") and no text | `main` @ `c3a958e` |
| HQ-06 | Low | "partial estimate" collides with the `partial` run status and is unexplained at the point of use | `main` @ `c3a958e` |

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

**This is a presentation change only.** The right-hand prose version is not
worse *reasoning* — it is arguably richer, carrying per-hypothesis
confidence and an explicit argument for why h4 is weak. The goal is to pin
how that content is laid out, not to shorten or simplify it. A fix that
produces tidy bullets by dropping the reasoning would be a regression.

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

## HQ-04 — The original research question disappears once the run finishes

**Severity:** medium. **Reported:** two screenshots — the ranked-hypotheses
overview, and the full report view.

**What the tester saw.** *"Original research question missing once candidate
hypotheses are listed"* and *"The original question is missing from full
report view as well."*

Both are correct, and they have different causes.

**Cause 1 — the results overview.** The question is rendered in
`LiveRunBar.tsx:81`:

```jsx
<p className="text-sm truncate">{question}</p>
```

but that sits inside `{isRunning && (…)}`, behind the same early return that
hides terminal status (`LiveRunBar.tsx:63`, see `HS-01`). So the question is
visible for exactly as long as the run is in flight, and vanishes at the
moment the results appear — precisely when the reader needs it to judge
whether the hypotheses answer what was asked.

It does survive in two places, neither of them adequate:

- `HistoryList.tsx:51` — but that is the history panel, a slide-out that is
  closed by default.
- `GroundingTrace.tsx:214` — as an 11px muted blockquote (`text-xs
  text-muted-foreground`), nested inside the "Premise grounding trace"
  accordion in `ResultsView.tsx:49-56`, which is **collapsed by default**.

That second one has a further catch: it renders only when `run.grounding`
exists. Grounding silently no-ops without an `AMASS_API_KEY` (see `HS-06`),
so on a run without it the question is **nowhere in the results view at
all**.

**Cause 2 — the full report view.** This one is structural, not a styling
accident. `HypothesisDetailsView` is passed `hypothesis`, `report`,
`evidence`, `evaluations`, `onIterate`, `onEvaluate`, `onBack`
(`HypothesisDetailsView.tsx:9-26`) — there is **no `question` prop at all**.
The component could not display the question even if asked to.

The only `question` reference inside it is `h.seed_question`
(`HypothesisDetailsView.tsx:42-43`), which is the follow-up question used by
"Iterate on this hypothesis" — a *different* string from the run's original
question.

**Why this matters more than it looks.** The report opens with
"## Hypothesis", stating a refined claim ("The best-supported hypothesis is
H1: controlled, donor-screened FMT — not raw fecal ingestion — …"). Without
the original question on screen, a reader cannot tell whether that refined
claim still answers what was asked, or has drifted. For a tool whose pitch
is a *defensible, cited* report, the question under examination is arguably
the single most important piece of context, and it is the one piece that is
not displayed.

It also makes shared screenshots ambiguous — as this very screenshot
demonstrates.

**Suggested fix.**

1. Render the question as a persistent header in `ResultsView`, above
   "Candidate hypotheses (ranked)", independent of `isRunning` and of
   whether grounding ran. This is the main fix; it needs no new plumbing,
   since `ResultsView` already receives `run`.
2. Pass `question={run.question}` into `HypothesisDetailsView` and show it
   above the `#1 …` hypothesis line, so the report view is self-contained.
3. Treat the question as run-level chrome rather than live-run chrome —
   `LiveRunBar` is the wrong owner for it, exactly as it is the wrong owner
   for terminal status in `HS-01`. Both are the same underlying mistake:
   information that belongs to the run is being rendered by a component
   scoped to the run's *in-flight* state.

Fixing `HS-01` and `HQ-04` together is natural — they are one refactor.

---

## HQ-05 — Collapsed section preview shows only the list marker, no text

**Severity:** medium. **Reported:** screenshot of "Failure Modes" collapsed
vs expanded.

**What the tester saw.** *"Collapsed failure mode just shows the bullet (1
in this case) and not any text."* The collapsed "Failure Modes" section
renders a preview consisting entirely of `1.` — expanding it reveals four
substantial, well-written failure modes.

**Confirmed in code, and reproduced.** The preview comes from `teaser()` in
`frontend/src/lib/reportSections.ts:41-45`, rendered at
`ReportView.tsx:40`. Two bugs compound:

1. **`stripMarkdown` handles unordered lists but not ordered ones**
   (`reportSections.ts:28`):

   ```js
   .replace(/^[-*]\s+/, "")
   ```

   `-` and `*` markers are stripped; `1.` is not, so the marker survives
   into the preview string.

2. **The sentence-boundary regex then treats that marker's dot as the end of
   the sentence** (`reportSections.ts:43`):

   ```js
   const sentenceMatch = firstLine.match(/^.*?[.!?](?=\s|$)/)
   ```

   It is non-greedy, so it stops at the *first* `.` followed by whitespace —
   which is the `.` in `1. `. The teaser becomes exactly `"1."`.

Running the shipped functions against the screenshot's content confirms it:

| Section body starts with | `teaser()` returns |
|---|---|
| `1. **Species/model mismatch**: progeroid and dwarf-mouse models…` | `"1."` |
| `- **High confidence** that shared CYP450 machinery…` | `"High confidence that shared CYP450 machinery is real."` |
| `The best-supported hypothesis is H1: controlled FMT…` | `"The best-supported hypothesis is H1: controlled FMT can reduce inflammaging."` |
| `1) First failure mode is species mismatch.` | `"1) First failure mode is species mismatch."` |
| `Trials e.g. PEARL have not reported healthspan endpoints yet.` | `"Trials e.g."` |

So unordered lists and plain prose work; `1.` ordered lists collapse to the
marker. `1)` happens to survive only because it contains no dot.

The last row is the same bug in a different disguise: **any** sentence whose
first abbreviation contains a dot — `e.g.`, `i.e.`, `vs.`, `Fig.`, `no.` —
truncates there. Common in this domain.

**Interaction with HQ-03 — fix this one first.** HQ-03 proposes enforcing
bullets in `Failure Modes`, `Confidence & Uncertainty` and both Evidence
sections. If the model renders those as `1.` numbered lists — which is
exactly what it did in this screenshot's Failure Modes — enforcing lists
will make this bug appear in *more* sections, not fewer. Landing HQ-03
without HQ-05 would visibly regress the collapsed view.

**Suggested fix.** Strip ordered-list markers alongside unordered ones, in
`stripMarkdown`:

```js
.replace(/^[-*]\s+/, "")
.replace(/^\d+[.)]\s+/, "")   // 1. / 2) ordered-list markers
```

That alone resolves the reported bug: with the marker gone, the sentence
match lands on the real first sentence.

For the abbreviation case, require that the terminator not be part of a
short lowercase abbreviation — e.g. reject a match whose final token before
the dot is 1-2 characters — or fall back to the whole line when the match is
suspiciously short (say under ~15 characters), which also guards against any
future marker style. A cheap belt-and-braces rule: if the matched sentence
is shorter than a threshold, use the full line instead.

Worth adding a unit test for `teaser()` covering these five inputs — it is a
pure function with no dependencies, so the test is trivial and this is
plainly a class of bug that recurs.

---

## HQ-06 — "partial estimate" collides with the `partial` run status

**Severity:** low. **Reported:** *"What does partial estimate mean?"* —
correctly flagged by the tester as unclear UX rather than a bug. Agreed: the
behaviour is correct, the wording is not.

**What it actually means.** The badge is gated on `cost.total_usd_is_partial`
(`CostPanel.tsx:83-87`), which the backend sets as
`total_usd_is_partial = bool(unpriced)` (`backend/agent/costs.py:189`), where
`unpriced` collects whichever of `nebius`, `amass` and `tavily` have no
configured price rate (`costs.py:136-142`).

So it means: **the dollar total leaves out providers whose price is not
configured.** In the screenshot, `$0.2702` is Anthropic alone; the Nebius,
Amass and Tavily calls really happened, they just are not costed. This is
deliberate and good — `costs.py:1-4` states the rule that every figure is
"either computed from a real, confirmed rate or explicitly marked unpriced
… never silently invented."

**Why the wording is a real problem, not just vague.** `partial` already
means something else in this application: `RunStatus` includes `"partial"`
(`frontend/src/types.ts`), meaning *the run was cut short before evidence
gathering finished*. Both meanings appear in the same results view, and they
are unrelated:

| Phrase | Means |
|---|---|
| run status `partial` | the run hit its tool/time budget and stopped early |
| cost badge `partial estimate` | the money total omits unpriced providers |

A reader who has seen one meaning will reasonably assume the other. This is
not hypothetical — during the automated audit this badge was initially read
as a run-status signal, and it is currently the *only* thing on a truncated
run's results page containing the word "partial" (see `HS-01`, where the
terminal status is never rendered). So on a budget-truncated run the one
visible "partial" refers to something else entirely.

**The explanation exists but is nowhere near the badge.** `CostPanel.tsx:103-105`
does render "Not priced: nebius, amass, tavily — set their price env vars to
include them." But it sits *below the entire "Cost by provider" bar list* —
four provider rows away from the badge it explains — and the badge itself
carries no tooltip (the tooltips at `CostPanel.tsx:36,43,50,60` are on the
provider bars).

**Suggested fix.** Cheapest first:

1. **Rename the badge** to something that cannot be confused with run state:
   `excludes unpriced providers`, or `Anthropic only`, or simply
   `incomplete pricing`. Avoid the word "partial" in the cost panel entirely
   while `RunStatus.partial` exists.
2. **Attach the explanation to the badge** as a tooltip, so the answer is
   where the question is asked. The string already exists at
   `CostPanel.tsx:103-105` and can be reused verbatim.
3. Optionally show which providers are covered inline, e.g.
   `$0.2702 · Anthropic only`, which answers the question without needing
   any interaction at all.

Note this is a distinct fix from `HS-01`. Renaming the cost badge does not
give a truncated run its missing status message — it only stops the cost
badge from being mistaken for one.

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
