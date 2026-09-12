# qa/ — Playwright harness

Deliberately a **separate npm workspace** from `frontend/`: Vercel builds with
Root Directory `frontend`, so putting Playwright in `frontend/package.json`
would make every production deploy download a browser driver it never uses.

## Setup

```bash
cd qa && npm install && npx playwright install chromium
```

## Running

Needs both servers up, and `ANTHROPIC_API_KEY` in the repo-root `.env`
(every other tool degrades to a mock, so that is the only required key):

```bash
# terminal 1
.venv/bin/uvicorn backend.server.app:app --port 8000
# terminal 2
npm --prefix frontend run dev
# terminal 3
cd qa && npm test                      # against localhost:5173
HS_BASE_URL=https://<deploy>.vercel.app npm test   # against a deployment
```

`workers: 1` is not a performance concession — the backend holds all run state
in module-level dicts in one process and `PUT /api/tools/{name}` is a global
toggle, so parallel workers corrupt each other's runs.

## Cost

Each spec that starts a real run spends Anthropic tokens (~$0.15 at budget 30,
less at lower budgets). `regressions.spec.ts` uses the lowest budget that still
reproduces each bug. Nothing here mocks the agent loop.
