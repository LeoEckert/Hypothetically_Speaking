# Deploy: two independent Vercel projects (frontend + backend)

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

- Frontend: `https://frontend-azure-two-37.vercel.app` (Vercel project `frontend`)
- Backend: `https://hypothetically-speaking-backend.vercel.app` (Vercel project `hypothetically-speaking-backend`)

Both are Vercel projects under the same team, deployed independently by
their own GitHub Actions workflow. Hostnames are worked examples, not
guaranteed-stable — if a project is ever renamed, update
`frontend/src/lib/api.ts`'s `PROD_API_BASE_FALLBACK` (or set
`VITE_API_BASE_URL` in the frontend project's Environment Variables, which
takes precedence).

## Why two separate projects, not one

Co-locating the backend inside the frontend's own Vercel project (adding a
Python function alongside the existing Vite static build, sharing one
`vercel.json`) was tried first and never worked: across three different
configurations (a hand-rolled `api/*.py` function two ways, then Vercel's
documented native `pyproject.toml` FastAPI entrypoint) the Python function
was never invoked for *any* request — consistently a platform-level
`NOT_FOUND` with zero runtime logs, most likely because the project's
existing Vite Framework Preset (a dashboard-only setting) prevented
Vercel's Python/FastAPI detection from engaging. A brand-new, backend-only
project immediately fixed that (confirmed: Vercel's build log explicitly
said "Detected FastAPI" on the very first build) — so the backend lives in
its own dedicated project, and the frontend calls it cross-origin (CORS via
`ALLOWED_ORIGIN_REGEX`, unchanged from the old Nebius-VM-era setup).

## A second, unrelated problem: broken native ASGI support on this account

Getting the dedicated project's Python function to actually *run* hit a
second, completely separate issue: this Vercel account's native
FastAPI/ASGI auto-detection consistently returns `FUNCTION_INVOCATION_FAILED`
on every request, with no retrievable traceback (`vercel logs` reports none
even seconds after a confirmed crash) — confirmed by elimination down to a
bare, dependency-free `app = FastAPI()` with one `@app.get("/")` route,
which still failed identically. A legacy `BaseHTTPRequestHandler`-style
Python function (Vercel's oldest, most basic function format, unrelated to
the FastAPI-specific integration) worked immediately on the same project.

**The fix**: `backend/server/app.py`'s FastAPI `app` is never exposed
directly to Vercel. The deploy stages a thin `api/index.py` that bridges it
through [`a2wsgi`](https://pypi.org/project/a2wsgi/)'s `ASGIMiddleware` onto
that working WSGI pathway instead:

```python
from a2wsgi import ASGIMiddleware
from backend.server.app import app as _asgi_app
app = ASGIMiddleware(_asgi_app)
```

Confirmed working end-to-end against the real deployment, including SSE:
`POST /api/run` returns `content-type: text/event-stream` and streams
correctly-framed `data: {...}` lines (start → phase/tool events → done →
stream_end) all the way through the WSGI bridge. If a future Vercel
platform update fixes native ASGI support on this account, `api/index.py`
can go back to exporting `backend.server.app:app` directly — but re-run the
elimination above against a real deployment before assuming it's fixed;
this bridge cost real time to find and there was no dashboard-visible
signal (build logs, deployment metadata) indicating anything was wrong.

## Setup: backend (dedicated Vercel project)

Deployed by `.github/workflows/deploy-backend-vercel.yml` on every push to
`main` (or manually via `workflow_dispatch`) — no manual first-time project
creation needed, the workflow creates the project itself on its first run
via `vercel deploy --yes` (naming it from `vercel.json`, or via
`VERCEL_PROJECT_ID` once known). What the workflow does:

1. Stages a **clean, backend-only directory** (`/tmp/backend-deploy`) containing just `backend/` (copied, not symlinked — the codebase's `from backend.xxx import ...` absolute imports need `backend/` to actually be a subdirectory of the deploy root), a trimmed `requirements.txt` (pytest excluded), and the `api/index.py` a2wsgi bridge shown above.
2. Deploys via the Vercel CLI with a personal access token (`vercel deploy --prod --token=...`) — **not** Vercel's native git integration, for the same reason as the frontend (see CI/CD below): this repo's git integration is fragile on this Hobby-plan team.
3. `vercel.json` sets `"functions": {"api/index.py": {"maxDuration": 300}}` — Fluid Compute is on by default for FastAPI-shaped Vercel projects, so this maxDuration is actually honored rather than capped at 60s.

**Environment variables**: leave `ANTHROPIC_API_KEY`/`OPENROUTER_API_KEY`
**unset** in this project's Environment Variables by design — every request
supplies its own via BYOK (see above); there is no platform key for the
LLM. Tool keys (`TAVILY_API_KEY`/`AMASS_API_KEY`/`NEBIUS_API_KEY`) are
optional platform fallbacks — set them here only if you want the platform
to fund those specific tools by default. `ADMIN_TOKEN` enables the admin
dashboard (see below, with a serverless-specific caveat).

**No manual dashboard configuration was needed** to get this working —
Root Directory stays at the project's default (repo root: the deploy
staging directory *is* the effective project root for this deploy, so
there's no "frontend"-style subfolder complication here). This differs
from the initial hope of co-locating with the frontend project, which
would have needed Root Directory / Framework Preset changes this session
had no access to check.

## Setup: frontend (Vercel)

**The programmatic path (Vercel MCP tools / API) had a persistent bug**
when this was set up: `create_git_project` and `deploy_to_vercel` each
report a successful project/deployment creation exactly once, but every
subsequent call on that same project (`get_project`, `get_deployment`, a
second deploy, `list_projects`) 404s or 403s, and the project never appears
in `list_projects` at all — reproduced across 5+ attempts, different
project names, both the git-linked and manual-file-upload flows. Separately
(confirmed later, while setting up the backend project): **the Vercel MCP
connector available in this environment can only see git-linked projects**
— neither the frontend project (git-disconnected on purpose, see CI/CD
below) nor the backend project (created via CLI, never git-linked) are
visible through it, even by exact project ID. If you hit either of these,
don't keep retrying against the API/MCP tools — use the dashboard directly,
or the CLI-token deploy pattern both projects actually use in production:

1. **vercel.com/new** → "Import Git Repository" → pick this repo. Vercel's
   import wizard auto-detects the Vite app inside `frontend/` and sets the
   project's **Root Directory to `frontend`** on its own.
2. Because Root Directory becomes `frontend`, the repo-root `vercel.json`'s
   `buildCommand`/`outputDirectory` must be written **relative to
   `frontend/`, not the repo root** — `"npm run build"` / `"dist"`, not
   `"cd frontend && npm run build"` / `"frontend/dist"`. (Vercel still reads
   `vercel.json` from the repo root even when Root Directory points at a
   subfolder; it just runs the configured commands with that subfolder as
   the working directory.)
3. Project Settings → Environment Variables → add `VITE_API_BASE_URL` =
   the backend project's URL, scoped to Production (and Preview too, if you
   want preview deploys to hit the same backend). Redeploy for it to take
   effect. Not required for a fresh deploy to work — `frontend/src/lib/api.ts`
   hardcodes the same URL as `PROD_API_BASE_FALLBACK`.
4. No CORS changes needed for the resulting `*.vercel.app` domain — it's
   already covered by the backend's `ALLOWED_ORIGIN_REGEX` default
   `https://.*\.vercel\.app$` (confirmed live: a CORS preflight with
   `Origin: https://frontend-azure-two-37.vercel.app` against the deployed
   backend returns the matching `Access-Control-Allow-Origin` header with
   no extra config).

## Admin dashboard

A `/api/admin/*` set of routes (`backend/agent/admin.py`) lets you monitor
paid-service usage over time and rotate provider API keys.

**Serverless caveat (new, since the Nebius VM retired)**: `set_key()`/
`rotate_admin_token()` persist a rotation by writing to
`ADMIN_OVERRIDES_PATH` (a file), on the theory that it survives a rebuild
because it's outside the main deploy artifact. On the old VM that file was
a bind-mounted volume that genuinely persisted. **On Vercel's serverless
functions, the filesystem is ephemeral per instance** — a rotation written
during one invocation has no guaranteed way to reach the *next* invocation,
which may be a completely fresh instance with no memory of that write. In
practice a rotation may appear to work (the response looks successful) and
then silently not be visible on a later request. This subsystem needs a
real persistent store (a small free-tier KV/Postgres) to actually work
here — not solved yet (see `CLAUDE.md`'s Open TODOs). Given Anthropic is
now user-supplied-only and the platform's only potential held secret
(`GROQ_API_KEY`/`OPENROUTER_API_KEY`) is a free-tier key with no billing
risk, key *rotation* specifically may not be worth fixing properly; the
dashboard's *usage monitoring* views (which just read `backend/reports/`
and call provider usage APIs directly) are unaffected by this caveat.

**Enabling it**: generate a token and set it as an Environment Variable on
the **backend** Vercel project (Project Settings → Environment Variables,
not a VM `.env` — there is no VM):

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

**Reaching it**: visit `https://<frontend-host>/#admin` — this opens a small
login prompt where you paste the token once per browser tab (kept in
`sessionStorage`, so a fresh tab or "Sign out" asks again). A
`https://<frontend-host>/#token=<ADMIN_TOKEN>` link also works as a
one-click shortcut: it stores the token the same way and immediately
rewrites the visible URL to plain `#admin`. Either way the token is passed
as a URL **fragment** (`#...`), never a query string, so it never appears in
a server or CDN access log — but it's still a bearer credential, so share it
only over a secure channel.

## CI/CD

Both projects deploy via the Vercel CLI with a personal access token,
**not** Vercel's native git integration.

This exists because Vercel's GitHub App auto-files a "request to join the
team" for any GitHub identity that pushes to a linked repo and isn't
already a team member — and the Hobby plan can neither add members nor
resolve/dismiss that request, so the pending request alone blocks *all*
deploys, even ones authored by the project owner (confirmed: this happened
after an external contributor pushed to `main`, and persisted even after
making the repo public). The fix, for the frontend project: git integration
disconnected (`vercel git disconnect`) and `vercel.json` sets
`git.deploymentEnabled: false` as a backstop. The backend project was
never git-linked at all, for the same reason.

**Frontend** — `.github/workflows/deploy-frontend.yml`: `vercel deploy --prod`
against the `frontend` project on every push to `main`. Requires
`VERCEL_TOKEN` (Account Settings → Tokens), `VERCEL_ORG_ID` and
`VERCEL_PROJECT_ID` (from `vercel link`'s `.vercel/project.json`, or
Project Settings → General).

**Backend** — `.github/workflows/deploy-backend-vercel.yml`: stages the
clean backend-only directory described above and runs `vercel deploy --prod`
against the `hypothetically-speaking-backend` project. Uses the same
`VERCEL_TOKEN`/`VERCEL_ORG_ID` secrets plus its own
`VERCEL_BACKEND_PROJECT_ID`. On a brand-new backend project (no
`VERCEL_BACKEND_PROJECT_ID` secret yet), the workflow leaves both
`VERCEL_ORG_ID`/`VERCEL_PROJECT_ID` unset for that one run — the CLI errors
if only one of the two is set — and `vercel deploy --yes` creates the
project fresh; set `VERCEL_BACKEND_PROJECT_ID` from the printed project ID
once, and every later run targets it explicitly.

**Limitation:** since git deploys are fully disabled for both projects,
Preview deployments for PRs/other branches don't happen automatically —
only pushes to `main` deploy anything. A manual `vercel deploy` (without
`--prod`) can still produce an ad hoc preview if ever needed, though raw
per-deployment preview URLs redirect to a Vercel Authentication gate on
this team (hitting the stable production alias is the reliable way to
smoke-test a deploy from CI).

## Local dev mode

`./dev.sh` from the repo root runs both the backend (`uvicorn --reload`)
and frontend (`vite dev`) together, Ctrl+C stops both. It's a convenience
wrapper — nothing it does is required; running the two `uvicorn`/`npm run
dev` commands from the Setup section in separate terminals is equivalent.
Either way, local dev is **fully independent** of Vercel: no network calls
to either deployed project happen unless you explicitly point
`VITE_API_BASE_URL` at one.

## Known limitation (pre-existing, resolved by the streaming rewrite)

`_run_events`/`_waiters`/`_results` in `backend/server/app.py` used to be
in-memory module-level dicts — a backend restart mid-run lost all in-flight
run state. That whole mechanism is gone: `POST /api/run` now runs a request
entirely within its own single response, so there's no cross-request state
left to lose. This is also what makes serverless hosting correct rather
than just convenient — a fresh, memoryless instance per request is exactly
what stateless serverless functions are.
