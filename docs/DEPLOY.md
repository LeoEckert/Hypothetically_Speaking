# Deploy: one Vercel project (static frontend + Python serverless function)

## Free-tier-by-default, BYOK, no platform-held LLM key

The platform runs on free services with **no platform-held LLM key at
all**: every visitor brings their own — a free OpenRouter key (real signup at
openrouter.ai/keys, no card) or their own Anthropic key — guided by a
required first-run onboarding popup in the frontend
(`frontend/src/components/OnboardingDialog.tsx`). This isn't a soft default;
a platform-wide key for either provider was tried and rejected, since it's a
shared resource a handful of concurrent visitors can exhaust (OpenRouter's
free tier is 50 requests/day *per account* — worse to share across every
visitor than to hand out individually). The three paid tool APIs
(Tavily/Amass/Nebius) are unaffected — still all-optional BYOK, every tool
already degrades to a mock/heuristic result without a key, and an operator
*can* still optionally set any of these five (including the two LLM keys)
as a platform fallback through the admin dashboard's key rotation
(`backend/agent/admin.py`'s `ROTATABLE_KEYS`) if they want one — it's just
not required or set by default (and see the admin dashboard section below
for a real caveat about that mechanism on serverless). See `CLAUDE.md`'s
"Tools wired into the loop" and "The agent loop" sections for the
code-level detail.

Every run budget (`MAX_TOOL_CALLS`, `MAX_RUN_SECONDS`, grounding depth) is
sized to fit inside a **hard 300-second-per-run ceiling** — the limit
Vercel Fluid Compute imposes even on its free Hobby plan (standard
functions cap at 60s; Fluid Compute raises that to 300s on Hobby, 800s on
Pro — there is no way to raise it further, and no chunked/resumable
workaround survives Vercel's 4.5MB request/response payload cap combined
with this app's fully in-memory run state, so that path was considered and
dropped, not overlooked). `backend/server/app.py`'s `POST /api/run` runs
the whole agent loop and streams its trace as SSE within **one**
request/response — there is no separate start/stream/cancel endpoint and no
server-side run cache, so this app has no state that needs to survive
between requests, which is exactly what makes it deployable as a stateless
serverless function at all.

## Current live deployment (example — yours will differ)

- `https://hypothetically-speaking.vercel.app` — one Vercel project, serving both the static frontend and `/api/*` as a Python serverless function. (`frontend-azure-two-37.vercel.app` is the same project/deployment — a leftover auto-generated alias from before the project was named — and still resolves too.)

If this project is ever renamed, update `frontend/src/lib/api.ts`'s
`PROD_API_BASE_FALLBACK` (empty string = same-origin; only needs a value if
the backend is ever split back out to its own host) or set
`VITE_API_BASE_URL` in the project's Environment Variables, which takes
precedence.

## One project, not two — and the three real bugs it took to get there

An earlier version of this setup used **two** separate Vercel projects (one
static, one backend-only), specifically to work around what looked like a
routing failure in the shared project. That diagnosis turned out to be
incomplete — merging back into one project (per explicit direction: two
projects for one small app was overkill) surfaced the *real*, fixable bugs
underneath, all three confirmed via a temporary traceback-catching
diagnostic function (wrap the real import in `try`/`except`, serve the
traceback as the HTTP response — necessary because `vercel logs` reliably
reports no logs for this account even seconds after a confirmed crash):

1. **This Vercel account's native FastAPI/ASGI auto-detection is broken.**
   Confirmed by elimination down to a bare, dependency-free `app = FastAPI()`
   with one route, which still `FUNCTION_INVOCATION_FAILED` on every
   request — while a legacy `BaseHTTPRequestHandler`-style function (Vercel's
   oldest, most basic Python function format) worked immediately on the same
   project. **Fix**: never expose the FastAPI `app` directly; bridge it
   through [`a2wsgi`](https://pypi.org/project/a2wsgi/)'s `ASGIMiddleware`
   onto the working WSGI pathway instead:
   ```python
   from a2wsgi import ASGIMiddleware
   from backend.server.app import app as _asgi_app
   app = ASGIMiddleware(_asgi_app)
   ```
2. **`backend/` staged in the wrong place relative to the function file**
   produced `ModuleNotFoundError: No module named 'backend'` — Vercel's
   Python function root is the *deploy root*, not the function file's own
   directory, so `backend/` must be staged as the function file's *sibling*
   (`frontend/backend/`), not nested inside `frontend/api/`.
3. **`MAX_TOOL_CALLS` was set to an empty string** in this project's
   Environment Variables (not absent — `os.environ.get(name, default)`'s
   default only applies when the key is *missing entirely*, not when it's
   set to `""`), which crashed `int(os.environ.get("MAX_TOOL_CALLS", 8))`
   with `ValueError: invalid literal for int() with base 10: ''`. **Fix**:
   `backend/agent/loop.py`'s `_env_int()` helper treats a blank env var as
   unset everywhere this pattern is used, rather than assuming any set env
   var is well-formed.

None of these three were about "two projects vs. one" at all — the
two-project split just happened to dodge all three simultaneously by
accident (a clean project with no stray Environment Variables, and enough
trial-and-error by then to have already found the `a2wsgi`/staging fixes).
**If a fresh deploy of this repo ever breaks again, check these three
first** — a traceback-catching diagnostic function is the fastest way back
to a real Python exception when `vercel logs` comes up empty.

## Routing: KNOWN UNRESOLVED BUG — multi-segment `/api/*` routes 404

A plain `api/index.py` in this project only auto-routes the *literal* `/api`
path, not the whole `/api/*` prefix (confirmed: `/api` reached the function,
`/api/config` got a platform-level 404 with zero function invocations). The
function file is currently named with Vercel's catch-all convention,
**`api/[...path].py`**, which fixes this for **single-segment** sub-paths
only: `/api/config`, `/api/tools`, `/api/run` all work. **Any path two or
more segments deep still 404s at the platform level** —
`/api/run/<id>/evaluate`, `/api/admin/usage`, `PUT /api/tools/<name>` — this
is exactly what silently broke "Evaluate with AI" until a user report caught
it, and the tool-toggle switch may have the same problem (never confirmed
either way once this was found).

Two separate attempts at a `vercel.json` **`rewrites`** fix
(`{"source": "/api/:path*", "destination": "/api"}`, meant to forward every
sub-path to the function regardless of depth) have **both failed**, in two
different sessions:
- First attempt: sub-paths still 404'd at the platform level, with the
  ASGI/module-staging bugs (#1/#2 above) also unresolved at the time —
  plausibly confounded, but never re-isolated.
- Second attempt (after #1/#2 were fixed): made things *worse* — it broke
  even the single-segment paths that the catch-all filename had working
  (`/api/config` started 404ing too). Reverted immediately.

**Do not re-attempt the `rewrites` fix without testing in a disposable
preview deployment first** (`vercel deploy` without `--prod`, or a scratch
project) — pushing straight to `--prod` twice now has taken working
endpoints down. Untried candidates worth investigating: a dashboard-level
routing override left over from the many manual experiments during initial
setup (not visible to this session — the project is deliberately
git-disconnected, so the Vercel MCP connector can't see it either, and
there's no local `vercel` CLI login); multiple fixed-depth catch-all files
(`api/[a].py`, `api/[a]/[b].py`, `api/[a]/[b]/[c].py`) as an uglier but
possibly-working alternative if dynamic depth genuinely isn't supported
here; or asking Vercel support directly, since a single-segment-only catch
-all match is not documented/expected behavior for a generic (non-Next.js)
Python Function.

## Setup

Deployed by `.github/workflows/deploy-frontend.yml` on every push to `main`
(or manually via `workflow_dispatch`). What it does:

1. **Stages the backend into place** right before deploy, rather than
   duplicating it permanently in the repo: copies `backend/` to
   `frontend/backend/` (a sibling of `frontend/api/`, not nested inside it
   — see bug #2 above), a trimmed `requirements.txt` (pytest excluded) to
   `frontend/requirements.txt`, and writes the `a2wsgi`-bridged function to
   `frontend/api/[...path].py` (bug #1's fix — see the Routing section above
   for this filename's own known limitation).
2. **Deploys via the Vercel CLI with a personal access token**
   (`vercel deploy --prod --token=...`), **not** Vercel's native git
   integration — see CI/CD below for why.
3. `vercel.json` sets `"functions": {"api/[...path].py": {"maxDuration": 300}}`.
   Fluid Compute is on by default for this kind of function, so 300s is
   actually honored rather than capped at 60s.

**Environment variables** (Project Settings → Environment Variables): leave
`ANTHROPIC_API_KEY`/`OPENROUTER_API_KEY` **unset** by design — every request
supplies its own via BYOK; there is no platform key for the LLM. Tool keys
(`TAVILY_API_KEY`/`AMASS_API_KEY`/`NEBIUS_API_KEY`) are optional platform
fallbacks. `ADMIN_TOKEN` enables the admin dashboard (below, with a
serverless-specific caveat). **Double-check any numeric env var
(`MAX_TOOL_CALLS`, `MAX_RUN_SECONDS`) is either genuinely unset or has a
real value** — an empty string crashed the whole app once already (bug #3
above); `_env_int()` now guards against this specific case, but there's no
guarantee every future numeric env var read gets the same treatment.

**Project Root Directory** stays at its existing value (`frontend`) — no
dashboard change was needed once the three bugs above were fixed. This
project's Framework Preset (Vite, auto-detected) coexists fine with the
Python function; it was never actually the blocker it first looked like.

## CI/CD

Deploys via the Vercel CLI with a personal access token, **not** Vercel's
native git integration.

This exists because Vercel's GitHub App auto-files a "request to join the
team" for any GitHub identity that pushes to a linked repo and isn't
already a team member — and the Hobby plan can neither add members nor
resolve/dismiss that request, so the pending request alone blocks *all*
deploys, even ones authored by the project owner (confirmed: this happened
after an external contributor pushed to `main`, and persisted even after
making the repo public). The fix: git integration disconnected
(`vercel git disconnect`) and `vercel.json` sets `git.deploymentEnabled: false`
as a backstop, so `.github/workflows/deploy-frontend.yml` is the only thing
that deploys anything.

Requires three repository secrets (Settings → Secrets and variables →
Actions): `VERCEL_TOKEN` (Account Settings → Tokens), `VERCEL_ORG_ID` and
`VERCEL_PROJECT_ID` (from `vercel link`'s `.vercel/project.json`, or Project
Settings → General).

**Limitation:** since git deploys are fully disabled, Preview deployments
for PRs/other branches don't happen automatically — only pushes to `main`
deploy anything. A manual `vercel deploy` (without `--prod`) can still
produce an ad hoc preview if ever needed, though raw per-deployment preview
URLs redirect to a Vercel Authentication gate on this team (hitting the
stable production alias is the reliable way to smoke-test a deploy from CI
or a script).

## Admin dashboard

A `/api/admin/*` set of routes (`backend/agent/admin.py`) lets you monitor
paid-service usage over time and rotate provider API keys.

**Serverless caveat**: `set_key()`/`rotate_admin_token()` persist a
rotation by writing to `ADMIN_OVERRIDES_PATH` (a file). **On Vercel's
serverless functions, the filesystem is ephemeral per instance** — a
rotation written during one invocation has no guaranteed way to reach the
*next* invocation, which may be a completely fresh instance with no memory
of that write. In practice a rotation may appear to work (the response
looks successful) and then silently not be visible on a later request.
This subsystem needs a real persistent store (a small free-tier
KV/Postgres) to actually work here — not solved yet (see `CLAUDE.md`'s Open
TODOs). Given Anthropic is now user-supplied-only and the platform's only
potential held secret is a free-tier key with no billing risk, key
*rotation* specifically may not be worth fixing properly; the dashboard's
*usage monitoring* views (which just read `backend/reports/` and call
provider usage APIs directly) are unaffected by this caveat.

**Enabling it**: generate a token and set it as an Environment Variable on
the Vercel project:

```bash
openssl rand -hex 32   # -> ADMIN_TOKEN value
```

The dashboard fails **closed**, not open: every `/api/admin/*` route
returns 503 while `ADMIN_TOKEN` is unset, rather than being reachable with
no auth.

**`ANTHROPIC_ADMIN_KEY`** (optional) is a separate, org-level Admin API key
— **not** `ANTHROPIC_API_KEY` — used for two things: the live "Anthropic
spend, last 7 days" figure in the usage snapshot, and the real hour-by-hour
Anthropic series in the usage-history graph's **24h** view (sourced from
Anthropic's own Usage API, priced with our confirmed rate table — genuinely
fetched, not locally estimated). It's unavailable on individual/non-org
Console accounts; if unset (or the account doesn't support it), both of
those fall back gracefully — the 7-day figure shows "not configured," and
the 24h graph uses the same locally-computed per-run costs the 7d/30d views
already use.

**No remaining-credit-balance API exists.** Anthropic's Admin API exposes
usage and spend *reporting* only (Usage API, Cost API) — there is no
endpoint for how much prepaid credit is left on the account. That figure is
Console-UI-only (the billing page). This dashboard tracks usage/spend, not
a balance, for that reason.

**Reaching it**: visit `https://<host>/#admin` — this opens a small login
prompt where you paste the token once per browser tab (kept in
`sessionStorage`, so a fresh tab or "Sign out" asks again). A
`https://<host>/#token=<ADMIN_TOKEN>` link also works as a one-click
shortcut: it stores the token the same way and immediately rewrites the
visible URL to plain `#admin`. Either way the token is passed as a URL
**fragment** (`#...`), never a query string, so it never appears in a
server or CDN access log — but it's still a bearer credential, so share it
only over a secure channel.

## Local dev mode

`./dev.sh` from the repo root runs both the backend (`uvicorn --reload`)
and frontend (`vite dev`) together, Ctrl+C stops both. It's a convenience
wrapper — nothing it does is required; running the two `uvicorn`/`npm run
dev` commands from the Setup section in separate terminals is equivalent.
Either way, local dev is **fully independent** of Vercel: no network calls
to the deployed project happen unless you explicitly point
`VITE_API_BASE_URL` at it.

## Known limitation (pre-existing, resolved by the streaming rewrite)

`_run_events`/`_waiters`/`_results` in `backend/server/app.py` used to be
in-memory module-level dicts — a backend restart mid-run lost all in-flight
run state. That whole mechanism is gone: `POST /api/run` now runs a request
entirely within its own single response, so there's no cross-request state
left to lose. This is also what makes serverless hosting correct rather
than just convenient — a fresh, memoryless instance per request is exactly
what stateless serverless functions are.
