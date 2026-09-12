# Deploy: Vercel (frontend) + Nebius (backend)

## Why split like this

Vercel Functions cap at 300 seconds max duration, even on paid tiers. A full
agent run targets up to 18 minutes. So Vercel can only serve the built
frontend as static assets — it cannot host the agent loop, and cannot even
proxy the SSE stream (any Vercel function in that path would time out well
before a run finishes). Everything that actually runs the agent lives on a
Nebius VM instead, reachable directly from the browser (CORS-enabled), where
Nebius compute credits cover the cost.

```
Vercel (free/Hobby tier)          Nebius VM
  frontend/ (Vite build)   --->   Caddy (TLS) --> Docker: FastAPI backend
  static assets only               reverse proxy      (the agent loop, all
                                                        tool integrations)
```

## The sslip.io placeholder

The backend's public hostname is `api-<vm-ip-with-dashes>.sslip.io` — a free
wildcard DNS service that resolves any `<ip-with-dashes>.sslip.io` name to
that literal IP, with zero domain purchase or DNS setup. Caddy uses it to get
a real Let's Encrypt certificate automatically. This is an explicit
placeholder, not a permanent choice.

**Swapping in a real domain later:**
1. Buy/point a domain's A record at the Nebius VM's reserved IP.
2. Edit `Caddyfile`'s site block from the sslip.io hostname to the real domain.
3. `docker compose restart caddy` (issues a fresh cert automatically).
4. Update the Vercel project's `VITE_API_BASE_URL` env var to the new URL, redeploy.
5. Update the backend's `ALLOWED_ORIGINS`/`ALLOWED_ORIGIN_REGEX` env vars if the frontend's origin also changed.

## First-time setup

### 1. Backend: Nebius VM (not yet provisioned — do this deliberately, it creates billed cloud resources)

1. **Reserve a static public IP first**, not an ephemeral one — an ephemeral IP
   silently changes on VM stop/start, which breaks both the frontend's
   configured backend URL and invalidates Caddy's certificate. Use `nebius vpc
   --help` to find the allocation subcommand.
2. Confirm/open a firewall rule for `tcp/22`, `tcp/80`, `tcp/443` on the VM's
   subnet (`nebius vpc --help`, exact subcommand name not pre-verified).
3. `nebius compute instance create` with `--resources-platform cpu-d3` and a
   small preset (2 vCPU / 8 GB is plenty — this app's actual heavy lifting is
   external hosted APIs, not local compute), the subnet + static IP from
   steps 1–2, and `--cloud-init-user-data` pointing at a script that installs
   Docker + the Compose plugin and writes `Caddyfile`/`docker-compose.yml`
   onto the boot disk. Cloud-init does **not** clone the repo or write `.env`
   (see below) and does not start the app.
4. Once the instance has a public IP:
   ```bash
   scp .env root@<vm-ip>:/opt/app/.env
   ssh root@<vm-ip> 'cd /opt/app && git clone <repo-url> repo && cd repo && cp ../.env . && docker compose up -d --build'
   ```
5. Edit `Caddyfile` on the VM (`/opt/app/repo/Caddyfile`) to use the real
   sslip.io hostname derived from the reserved IP, then
   `docker compose restart caddy`.
6. Verify: `curl -v https://api-<ip>.sslip.io/api/config`.

**Secrets are never baked into cloud-init/instance metadata** — metadata is
retrievable indefinitely and rotating a key would mean recreating the VM.
`.env` only ever reaches the VM via the manual `scp` step above. Rotating a
key later: edit local `.env`, `scp` again, `ssh ... docker compose restart app`.

### 2. Frontend: Vercel

1. Connect the repo to a new Vercel project — `vercel.json` at the repo root
   already tells Vercel how to build (`cd frontend && npm install && npm run
   build`, output `frontend/dist`), so no dashboard configuration is needed.
2. Set the `VITE_API_BASE_URL` environment variable (Vercel dashboard, or
   `vercel env add VITE_API_BASE_URL production`) to `https://api-<ip>.sslip.io`.
3. Deploy. Once you know the resulting Vercel production domain, set the
   backend's `ALLOWED_ORIGINS` env var to include it (comma-separated) and
   restart the backend container — Vercel *preview* deployments (per branch)
   are already covered by `ALLOWED_ORIGIN_REGEX`'s default
   `https://.*\.vercel\.app$`.

## Known limitation (pre-existing, unrelated to this split)

`_runs`/`_results`/`_run_events` in `backend/server/app.py` are in-memory —
a backend container restart mid-run loses all in-flight run state. This was
true before this deployment split and isn't addressed by it.
