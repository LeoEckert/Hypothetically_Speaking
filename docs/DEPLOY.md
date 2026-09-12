# Deploy: Vercel (frontend) + Nebius (backend)

## Why split like this

Vercel Functions cap at 300 seconds max duration, even on paid tiers. A full
agent run targets up to 18 minutes. So Vercel can only serve the built
frontend as static assets — it cannot host the agent loop, and cannot even
proxy the SSE stream (any Vercel function in that path would time out well
before a run finishes). Everything that actually runs the agent lives on a
Nebius VM instead, reachable directly from the browser (CORS-enabled), where
Nebius compute credits cover the cost. See `docs/ARCHITECTURE.md`'s System
diagram for the full picture.

## Current live deployment (example — yours will differ)

- Backend: `https://api-185-175-110-142.sslip.io` (Nebius VM, `eu-west1`)
- Frontend: `https://frontend-azure-two-37.vercel.app` (Vercel)

Both hostnames are placeholders that change if the VM is recreated or the
Vercel project is renamed — treat them as worked examples, not stable URLs.

## The sslip.io placeholder

The backend's public hostname is `api-<vm-ip-with-dashes>.sslip.io` — a free
wildcard DNS service that resolves any `<ip-with-dashes>.sslip.io` name to
that literal IP, with zero domain purchase or DNS setup. Caddy uses it to get
a real Let's Encrypt certificate automatically (confirmed: no `-k`/insecure
flag needed, it's a real trusted cert).

**Swapping in a real domain later:**
1. Buy/point a domain's A record at the Nebius VM's reserved IP.
2. Edit `Caddyfile`'s site block from the sslip.io hostname to the real domain.
3. `sudo docker compose restart caddy` on the VM (issues a fresh cert automatically).
4. Update the Vercel project's `VITE_API_BASE_URL` env var to the new URL, redeploy.
5. `ALLOWED_ORIGIN_REGEX`'s default already matches any `*.vercel.app` origin, so the frontend side usually needs no backend change.

## First-time setup

### 1. Backend: Nebius VM

**Check vCPU quota before picking a region.** New Nebius accounts often get
`0` for `compute.instance.non-gpu.vcpu` in some regions and `200` in others
— region choice is not just about latency:

```bash
export PATH="$HOME/.nebius/bin:$PATH"
nebius quotas quota-allowance list --parent-id <tenant-id> --format json \
  | python3 -c "
import json,sys
for i in json.load(sys.stdin)['items']:
    if i['metadata']['name'] == 'compute.instance.non-gpu.vcpu':
        print(i['spec']['region'], i['spec']['limit'])
"
```
Pick a region with a non-zero limit (e.g. `eu-west1` had 200 when this was
written; `eu-north1` and `us-central1` had 0).

**Images and platform IDs are region-scoped.** `computeplatform-*` and
`computeimage-*` IDs from one project/region don't work in another — look
them up fresh per region:

```bash
PROJECT=<the region's default project id>
nebius compute platform list --parent-id $PROJECT --format json   # find the cpu-d3 platform id for this region
nebius compute image list --parent-id project-e0<N>public-images --format json   # e00/e01/... prefix varies by region
```

**Steps:**
1. Reserve a **static** public IP first, not ephemeral (`nebius vpc allocation create --parent-id $PROJECT --name hs-backend-ip --ipv4-public-pool-id <pool-id>` — get the pool id from `nebius vpc network list`/`subnet list`). An ephemeral IP would silently change on VM stop/start, breaking both the frontend's configured backend URL and Caddy's certificate.
2. The default security group already had an `ALLOW ANY` ingress/egress rule in testing — check with `nebius vpc security-rule list --parent-id <security-group-id>` before adding a redundant one.
3. `nebius compute instance create` — **all of these flags are required**, several aren't obvious from the top-level `--help` and only surface as `InvalidArgument` errors if omitted or wrong:
   - `--boot-disk-attach-mode read_write`
   - `--boot-disk-managed-disk-name <any-name>` and `--boot-disk-managed-disk-type network_ssd` (both required, not just the size)
   - `--boot-disk-managed-disk-source-image-id <region-specific image id>`
   - `--boot-disk-managed-disk-size-gibibytes <N>` — **must meet the image's minimum** (the error message states the exact minimum in bytes if you get it wrong, e.g. 40 GiB for the Ubuntu 24.04 CUDA image used here — CUDA is preinstalled on every available Ubuntu image in this account, it's not something we opted into and isn't needed for this workload)
   - `--network-interfaces '[{"name":"eth0","ip_address":{},"public_ip_address":{"allocation_id":"<allocation-id-from-step-1>","static":true},"subnet_id":"<subnet-id>"}]'`
   - `--cloud-init-user-data "$(cat cloud-init.yaml)"` (see below)
4. Cloud-init (a `#cloud-config` — installs Docker + Compose plugin, creates `/opt/app/repo`, injects an SSH key). **In testing, the `disable_root: false` + explicit `users: - name: root` approach did not actually enable root SSH login** — only the top-level `ssh_authorized_keys:` (which lands on the distro's default user, `ubuntu` on this image) worked. Use `ubuntu` + `sudo`, not `root`, unless you've separately confirmed root login works on your image:
   ```yaml
   #cloud-config
   ssh_authorized_keys:
     - ssh-ed25519 AAAA... your-key
   package_update: true
   packages: [ca-certificates, curl, rsync]
   runcmd:
     - install -m 0755 -d /etc/apt/keyrings
     - curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
     - chmod a+r /etc/apt/keyrings/docker.asc
     - echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo $VERSION_CODENAME) stable" > /etc/apt/sources.list.d/docker.list
     - apt-get update
     - apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
     - systemctl enable --now docker
     - mkdir -p /opt/app/repo
   ```
5. Once the instance is `RUNNING` and `cloud-init status --wait` returns `done` over SSH as `ubuntu`:
   ```bash
   ssh ubuntu@<vm-ip> 'sudo chown -R ubuntu:ubuntu /opt/app'
   rsync -az --delete \
     --exclude='.git' --exclude='.venv' --exclude='__pycache__' \
     --exclude='frontend/node_modules' --exclude='frontend/dist' \
     --exclude='backend/reports/*.json' --exclude='backend/reports/*.md' \
     --exclude='.env' --exclude='.pytest_cache' --exclude='admin_overrides.env' \
     ./ ubuntu@<vm-ip>:/opt/app/repo/
   scp .env ubuntu@<vm-ip>:/opt/app/repo/.env
   ```
   `rsync` from the local machine directly, rather than `git clone` on the VM — this repo is private, and rsync avoids ever needing a GitHub credential (deploy key or PAT) on the VM at all. Re-run the same `rsync` command to push any future code change; it's idempotent (`--delete` keeps the VM's copy exactly in sync). `admin_overrides.env` is excluded deliberately — it doesn't exist locally (gitignored, VM-only) and `--delete` would otherwise erase any dashboard-rotated keys on every deploy.
6. Edit `Caddyfile` on the VM to the real sslip.io hostname derived from the reserved IP (`api-<ip-with-dashes>.sslip.io`), then:
   ```bash
   ssh ubuntu@<vm-ip> 'cd /opt/app/repo && touch admin_overrides.env && sudo docker compose up -d --build'
   ```
   The `touch` matters on a fresh VM: `admin_overrides.env` is bind-mounted into the container (`docker-compose.yml`), and Docker silently creates a **directory** at that path instead of an empty file if nothing exists there yet — which then breaks the first key rotation from the admin dashboard.
7. Verify: `curl -v https://api-<ip>.sslip.io/api/config` — should return real JSON over a trusted cert with no `-k` needed.

**Secrets are never baked into cloud-init/instance metadata** — metadata is
retrievable indefinitely and rotating a key would mean recreating the VM.
`.env` only ever reaches the VM via the `scp` step above. Rotating a key
later: edit local `.env`, `scp` again, `ssh ... sudo docker compose restart app`.

### 2. Frontend: Vercel

**The programmatic path (Vercel MCP tools / API) had a persistent bug** when
this was set up: `create_git_project` and `deploy_to_vercel` each report a
successful project/deployment creation exactly once, but every subsequent
call on that same project (`get_project`, `get_deployment`, a second
deploy, `list_projects`) 404s or 403s, and the project never appears in
`list_projects` at all — reproduced across 5+ attempts, different project
names, both the git-linked and manual-file-upload flows. If you hit the
same thing, don't keep retrying — use the dashboard instead:

1. **vercel.com/new** → "Import Git Repository" → pick this repo. Vercel's
   import wizard auto-detects the Vite app inside `frontend/` and sets the
   project's **Root Directory to `frontend`** on its own.
2. Because Root Directory becomes `frontend`, the repo-root `vercel.json`'s
   `buildCommand`/`outputDirectory` must be written **relative to
   `frontend/`, not the repo root** — `"npm run build"` / `"dist"`, not
   `"cd frontend && npm run build"` / `"frontend/dist"`. (Vercel still reads
   `vercel.json` from the repo root even when Root Directory points at a
   subfolder; it just runs the configured commands with that subfolder as
   the working directory. Getting this wrong fails the build with `cd:
   frontend: No such file or directory` — the working directory is already
   `frontend/`, so `cd frontend` doesn't exist relative to it.)
3. Project Settings → Environment Variables → add `VITE_API_BASE_URL` =
   `https://api-<vm-ip-with-dashes>.sslip.io`, scoped to Production (and
   Preview too, if you want preview deploys to hit the same backend).
   Redeploy for it to take effect.
4. No CORS changes needed for the resulting `*.vercel.app` domain — it's
   already covered by `ALLOWED_ORIGIN_REGEX`'s default
   `https://.*\.vercel\.app$` (confirmed: a live `curl` with `Origin:
   https://<project>.vercel.app` against the deployed backend returns the
   matching `Access-Control-Allow-Origin` header with no extra config).

## Admin dashboard

A `/api/admin/*` set of routes (`backend/agent/admin.py`) lets you monitor
paid-service usage over time and rotate provider API keys without SSH-ing
into the VM for routine key changes.

**Enabling it**: generate a token and set it on the backend:

```bash
openssl rand -hex 32   # -> ADMIN_TOKEN value
```

Set `ADMIN_TOKEN=<value>` in the VM's `.env`, then
`ssh ubuntu@<vm-ip> 'cd /opt/app/repo && sudo docker compose restart app'`.
The dashboard fails **closed**, not open: every `/api/admin/*` route returns
503 while `ADMIN_TOKEN` is unset, rather than being reachable with no auth.

**`ANTHROPIC_ADMIN_KEY`** (optional) is a separate, org-level Admin API key —
**not** `ANTHROPIC_API_KEY` — used only for the live "Anthropic spend, last 7
days" figure in the usage snapshot. It's unavailable on individual/non-org
Console accounts; if unset (or the account doesn't support it), that one
figure just shows "not configured" — the usage-history graph doesn't need it
at all, since it's computed from already-priced local run reports instead.

**`ADMIN_OVERRIDES_PATH`** defaults to `<repo-root>/admin_overrides.env`,
already bind-mounted into the `app` container by `docker-compose.yml` and
already gitignored. It's created lazily the first time you rotate a key from
the dashboard — nothing to set up in advance.

**Interaction with manual key rotation** (see "Rotating a key later" under
the Nebius VM section above): a key rotated through the dashboard is written
to `admin_overrides.env` on the VM, which is loaded with `override=True`
*after* `.env` at process start (`app.py`) — so a dashboard rotation wins
over whatever is in `.env`, including a `.env` you `scp` up *after* the
dashboard rotation, unless you also update/clear the corresponding line in
`admin_overrides.env`. If you use both rotation paths, know that the
dashboard's value wins by default.

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

**Frontend** — `.github/workflows/deploy-frontend.yml`: on every push to
`main` (or manually via `workflow_dispatch`), a
GitHub Actions job runs `vercel deploy --prod` against the existing Vercel
project (`frontend`), authenticated with a personal access token rather
than Vercel's native git integration.

This exists because Vercel's GitHub App auto-files a "request to join the
team" for any GitHub identity that pushes to a linked repo and isn't
already a team member — and the Hobby plan can neither add members nor
resolve/dismiss that request, so the pending request alone blocks *all*
deploys, even ones authored by the project owner (confirmed: this happened
after an external contributor pushed to `main`, and persisted even after
making the repo public — visibility isn't the trigger, the git integration
itself is). The fix: the git integration is disconnected
(`vercel git disconnect`, confirmed under Project Settings → Git in the
dashboard, for both the `frontend` project and a stray duplicate project
`hypothetically-speaking` that was also git-linked to this repo) and
`vercel.json` sets `git.deploymentEnabled: false` as a backstop, so this
workflow is now the only thing that deploys the frontend. A CLI/token
deploy authenticates by the token's own project permissions, not by
pushing GitHub identity, so it isn't subject to the same restriction —
confirmed working directly against the `frontend` project.

Requires three repository secrets (Settings → Secrets and variables →
Actions), obtained once by the project owner and not derivable by an
agent: `VERCEL_TOKEN` (Account Settings → Tokens), `VERCEL_ORG_ID` and
`VERCEL_PROJECT_ID` (from `vercel link`'s `.vercel/project.json`, or
Project Settings → General) — the same pattern as `NEBIUS_SSH_KEY`/
`NEBIUS_VM_HOST` above. `frontend/src/lib/api.ts` also hardcodes a
production fallback backend URL (`PROD_API_BASE_FALLBACK`), so a fresh
deploy works even without `VITE_API_BASE_URL` set in the Vercel dashboard —
that env var only needs setting if the backend URL ever changes, and it's
still applied correctly since the workflow uses Vercel's remote build
(`vercel deploy` uploads source and lets Vercel build it against the
dashboard-configured project settings, rather than building locally in
Actions where that dashboard-only env var wouldn't be visible).

**Limitation:** since git deploys are fully disabled repo-wide, Preview
deployments for PRs/other branches no longer happen automatically — only
pushes to `main` deploy anything now. A manual
`vercel deploy` (without `--prod`) can still produce an ad hoc preview if
ever needed.

**Note:** a "sujoung requests to join your team" entry may still be
visible in the Vercel dashboard from before this fix. It's a harmless
leftover — once the git integration is disconnected it can't block
anything or recur, and Hobby still doesn't expose a way to dismiss it.
Ignore it, or clean it up later if Vercel ever adds that ability.

**Backend** — `.github/workflows/deploy-backend.yml`: on every push to
`main` (or manually via `workflow_dispatch`), a
GitHub Actions job rsyncs the repo to the VM and runs `docker compose up -d
--build app` over SSH — the same two commands as the manual first-time
setup above, just automated. It deliberately only rebuilds the `app`
service, not `caddy` (whose config is static once set up), and `.env` is
excluded from the rsync (secrets stay VM-only, CI never sees them).

Requires two repository secrets (Settings → Secrets and variables →
Actions): `NEBIUS_SSH_KEY` (a **dedicated** deploy keypair generated for
CI — not any developer's personal key — with its public half appended to
the VM's `ubuntu` user's `~/.ssh/authorized_keys`) and `NEBIUS_VM_HOST`
(the VM's IP). Rotate by generating a new keypair, appending the new
public key to the VM, replacing the `NEBIUS_SSH_KEY` secret, then removing
the old public key from the VM's `authorized_keys`.

## Local dev mode

`./dev.sh` from the repo root runs both the backend (`uvicorn --reload`)
and frontend (`vite dev`) together, Ctrl+C stops both. It's a convenience
wrapper — nothing it does is required; running the two `uvicorn`/`npm run
dev` commands from the Setup section in separate terminals is equivalent.
Either way, local dev is **fully independent** of Vercel/Nebius: no
network calls to either happen unless you explicitly point
`VITE_API_BASE_URL` at a deployed backend.

## Known limitation (pre-existing, unrelated to this split)

`_run_events`/`_wakeups`/`_results` in `backend/server/app.py` are
in-memory — a backend container restart mid-run loses all in-flight run
state. This was true before this deployment split and isn't addressed by
it.
