# Deploy — Hostinger VPS (halovisionai.cloud)

This follows the exact pattern already used by the other sites in this repo
(seelenhafen, halo4, hydron-one, Myriam-Website, school-ai-2/LG KI): shared
Traefik reverse proxy on the external `traefik-proxy` Docker network, TLS
via the `letsencrypt` certresolver, routing to `*.halovisionai.cloud`. See
`docker-compose.yml`'s header comment for the exact port/subdomain map.

## 1. Prerequisites (should already be true on this VPS)

- Docker + the `traefik-proxy` external network already exist (every other
  site here depends on it). Verify: `docker network ls | grep traefik-proxy`.
  If it's genuinely missing: `docker network create traefik-proxy` — but
  that would mean Traefik itself isn't running either, which would also
  break every other site, so this should never actually be needed.
- DNS: `factory.halovisionai.cloud`, `factory-api.halovisionai.cloud`, and
  `factory-n8n.halovisionai.cloud` need to resolve to the VPS. If
  `jayden-mikus.halovisionai.cloud` already works, you likely have a
  wildcard `*.halovisionai.cloud` A record and these will just work with no
  new DNS entry. If not, add three A records (or one wildcard) pointing at
  the VPS IP.

## 2. Get the code onto the server

```bash
git clone <your-repo-url> ai-company   # or scp the ai-company/ folder up
cd ai-company
```

## 3. Configure secrets

```bash
cp .env.example .env
nano .env
```

At minimum: `OPENROUTER_API_KEY` (free at https://openrouter.ai/keys, no
card needed), `POSTGRES_PASSWORD`, `N8N_BASIC_AUTH_PASSWORD` — real values,
not the placeholders. Leave `DASHBOARD_PUBLIC_API_URL`/`N8N_HOST` commented
out unless you're testing without Traefik (see the comments in `.env.example`).

## 4. Build and start

```bash
docker compose up -d --build
docker compose ps        # everything "healthy"/"running" within ~60s
```

Reachable at:
- Dashboard: `https://factory.halovisionai.cloud` (or `http://<VPS-IP>:47831` direct)
- Backend API: `https://factory-api.halovisionai.cloud` (or `http://<VPS-IP>:47832` direct)
- n8n: `https://factory-n8n.halovisionai.cloud` (or `http://<VPS-IP>:47833` direct)

Postgres/Redis/Celery are on the `internal` Docker network only — no host
port, no Traefik label, not reachable from outside the container network at
all. That's intentional, not an oversight.

## 5. Lock it down — the API and dashboard have no auth yet

Unlike n8n (which has `N8N_BASIC_AUTH_ACTIVE` built in), the FastAPI backend
and Next.js dashboard have zero authentication in v1. Anyone who finds
`factory-api.halovisionai.cloud` can trigger agent runs and approve/reject
opportunities. `docker-compose.yml` already has commented-out Traefik
basicauth middleware on both — enable it:

```bash
# generate the password hash (needs apache2-utils: apt install apache2-utils)
htpasswd -nB admin
# copy the output, e.g. admin:$2y$05$abc123...
```

Then in `docker-compose.yml`, uncomment the two `factory-api-auth` lines
under `backend.labels` and the two `factory-dashboard-auth` lines under
`dashboard.labels`, pasting your hash in place of `admin:$$2y$$...` (note
the doubled `$$` — that's Compose's escaping for a literal `$`, required
because htpasswd hashes are full of them). Then:

```bash
docker compose up -d
```

Do this before telling anyone else the URL exists.

## 6. Automated backups

```bash
chmod +x scripts/backup_postgres.sh
crontab -e
# add:
15 3 * * * /home/<you>/ai-company/scripts/backup_postgres.sh >> /var/log/factory-backup.log 2>&1
```

Dumps go to `ai-company/backups/`, gzip-compressed, pruned after 14 days
(override with `RETENTION_DAYS=30 ./scripts/backup_postgres.sh`). Copy them
off-box periodically — a backup on the same disk as the database survives a
bad `git push`, not a bad disk.

## 7. Day-to-day updates

```bash
cd ai-company
git pull
docker compose up -d --build   # only rebuilds services whose code changed
docker compose logs -f backend celery_worker   # tail if something looks off
```

`restart: unless-stopped` means a server reboot brings the whole stack back
automatically — no manual step after a crash or `sudo reboot`.

## 8. Verifying it's actually working

```bash
curl https://factory-api.halovisionai.cloud/health     # {"status":"ok","database":true}
docker compose exec backend python -c "from app.tasks import run_scout_cycle; run_scout_cycle.run()"
docker compose logs -f celery_worker                    # watch the Scout agent think
curl https://factory-api.halovisionai.cloud/api/opportunities
```

Open `https://factory.halovisionai.cloud` — Overview should show
`active_agents: 3` (ceo, scout, research), `spend_usd: 0`, and growing model
call counts as the loop runs.

## Port/subdomain registry for this VPS (avoid future collisions)

| Site | Port | Subdomain/path |
|---|---|---|
| h4h | 8082 (direct only, no Traefik) | — |
| LG KI (school-ai-2) | 47821 | `halovisionai.cloud/lgai` |
| **ai-company dashboard** | **47831** | **`factory.halovisionai.cloud`** |
| **ai-company backend** | **47832** | **`factory-api.halovisionai.cloud`** |
| **ai-company n8n** | **47833** | **`factory-n8n.halovisionai.cloud`** |
| Sable2 n8n (existing, separate instance) | — | `n8n.halovisionai.cloud` |
| seelenhafen / hydron-one / Myriam / halo4 / sable(sidequest) | Traefik-only, no host port | path-based on `halovisionai.cloud` |
| jayden-portfolio | Traefik-only, no host port | `jayden-mikus.halovisionai.cloud` |

Next new service on this VPS: use `4784x`.
