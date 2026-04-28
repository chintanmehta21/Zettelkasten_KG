# Render → DigitalOcean Migration Design Specification

> **ARCHIVED — Historical migration record.** This document describes a one-time migration from Render.com to a DigitalOcean droplet. The migration is complete and merged. The DigitalOcean droplet (Premium Intel 2 GB RAM / 1 vCPU / 70 GB NVMe SSD with Reserved IP, blue/green Docker Compose + Caddy) is the canonical and only production environment. **Do not treat any Render reference in this file as current; Render is no longer used.** See the "Deployment Infrastructure (Canonical)" section in the project root `CLAUDE.md` for the live setup.

**Date:** 2026-04-09
**Status:** Implemented and merged (archived for historical context)
**Owner:** Website infrastructure / deployment
**Scope:** `website/` application (FastAPI + static UI) — primary target. Telegram bot is secondary/future, mentioned only where its existing webhook coupling matters.

---

## 1. Objective

Migrate the production `website/` application (a FastAPI app that serves the Zettelkasten summarizer UI, the 3D knowledge graph, user auth, home, user zettels, and experimental Nexus) from Render.com to a single DigitalOcean Droplet running Docker, with:

1. A persistent SSD-backed host filesystem (eliminating Render's ephemeral `/tmp` pain).
2. Zero-downtime rolling deploys via blue-green containers behind Caddy.
3. Aggressive single-node hardening targeting 99.9%+ uptime.
4. Zero-downtime migration cutover from `*.onrender.com` to the new host.
5. A Docker image optimized for instant cold-start UX ("UX masterclass").
6. Supabase remains on its current Free tier, unchanged.

The end-user primarily interacts with the **website** (home page, summarizer, 3D KG, my zettels, nexus). The Telegram bot is currently shipped in the same process but is considered a secondary, future-facing surface; migration design must not break it, but all optimization and reliability decisions are made from the website's perspective first.

---

## 2. Hard Requirements (from product direction)

The user gave 15 explicit constraints. These are non-negotiable and each must be satisfied in the implementation plan:

1. **Region:** Use DigitalOcean `BLR1` (Bangalore) for the Droplet.
2. **Database:** Stay on Supabase **Free tier** until limits are actually hit. No migration of Supabase to DO in this phase.
3. **Lazy-imports refactor is critical.** Refactor eager imports in the website request paths so cold-start RAM and first-request latency drop sharply. This is mandatory engineering hygiene, not optional.
4. **Docker 1-Click marketplace image.** Use DO's Docker 1-Click Droplet image (Ubuntu 22.04 + Docker CE + Compose + BuildX) rather than bringing our own base OS.
5. **Container registry:** Use **GitHub Container Registry (GHCR)** — free, unlimited, public + private, deeply integrated with our GitHub Actions.
6. **No backups for now.** Skip DO weekly backups / snapshots in phase 1. Will be revisited later.
7. **Single-node with aggressive HA engineering** targeting **99.9%+ uptime**. Do not provision a 2-node HA pair yet. Reliability comes from container-level + host-level hardening, not horizontal redundancy.
8. **Zero-downtime deploys — blue-green behind Caddy.** Every production deploy must be hitless. No `docker compose down && up`.
9. **Container-level reliability:** automatic restart on crash, resource caps, graceful shutdown, health checks, log rotation.
10. **Host-level reliability:** systemd unit for the Docker stack, unattended security updates, kernel tuning for file descriptors, UFW firewall, automatic SSL renewal, log rotation, BetterStack external monitoring.
11. **Migration cutover via `setWebhook` + low-TTL DNS.** The Telegram bot webhook is URL-based so it can be swapped atomically with a single `setWebhook` API call. Web UI is moved via low-TTL DNS pre-flip. Telegram bot is *not* the critical endpoint — the **website** is.
12. **Docker optimization via subagent per feature.** Spin up one subagent per website feature area (home, summarizer, kg, user zettels, nexus, auth, footer) to find image-size / cold-start / first-paint wins. The image must feel like a "UX masterclass" for first visit.
13. **Website is PRIMARY. Telegram bot is secondary/future. Focus only on website.** Any trade-off between the two must be resolved in favor of website UX and reliability. Telegram bot gets minimal-downtime best effort as a side benefit.
14. **BetterStack over UptimeRobot** for external monitoring.
15. **Zero-downtime cutover** via Telegram `setWebhook` (atomic URL swap) combined with low-TTL DNS pre-flip for the web UI.

All 15 constraints are cross-referenced in Sections 4–12 below.

### 2.1 Post-brainstorming decisions (locked in during spec review)

Captured here so they override any earlier assumptions:

1. **Domain:** `zettelkasten.in` purchased at **GoDaddy** (GoDaddy sells `.in`, Cloudflare Registrar does not). GoDaddy is registrar only.
2. **DNS provider:** **Cloudflare Free** — domain's nameservers are delegated from GoDaddy to Cloudflare on day -1 so DNS queries hit Cloudflare's ~11 ms anycast network, not GoDaddy's slower servers. Cloudflare proxy (orange cloud) stays **OFF** for phase 1 because BLR1 + India users benefit more from direct paths than edge hops.
3. **Source repo:** `chintanmehta21/Zettelkasten_KG` (private). Note CLAUDE.md has a stale URL; not blocking, will be fixed separately.
4. **GHCR image:** private at `ghcr.io/chintanmehta21/zettelkasten-kg-website`, pulled on droplet via fine-grained `GHCR_READ_PAT` with `read:packages` scope, 365-day expiry, annual rotation.
5. **Secrets delivery:** all runtime secrets live in GitHub Actions Environment secrets under the `production` environment, with a protection rule requiring manual approval before every deploy. Droplet `.env` is (re)written by the deploy workflow on every deploy.
6. **`GEMINI_API_KEYS`:** canonical store is the GitHub `production` Environment secret; comma-separated list of up to 10 keys. Windows-local `api_env` file remains for local development only.
7. **`SUPABASE_SERVICE_ROLE_KEY`:** **never** touches the droplet. Only `SUPABASE_ANON_KEY` is deployed. Service-role operations (migration script, etc.) run from Windows-local with `supabase/.env`.
8. **CI test gate:** `pytest` (default, mocked, no network) runs on every `pull_request` open/synchronize and every `push` to `master`. Deploy job is gated on it. `pytest --live` runs only via `workflow_dispatch` (manual) and a weekly Sunday-03:00-IST `schedule` cron, so Gemini quota isn't burned on every keystroke.
9. **Let's Encrypt ACME account email:** `chintanoninternet@gmail.com`.
10. **Apex canonical, www 301:** `https://zettelkasten.in` is canonical, `https://www.zettelkasten.in` redirects.
11. **IPv6:** enabled. Droplet gets a free `/64`; Caddy listens on both IPv4 and IPv6; DNS has both A and AAAA records.
12. **Nexus:** `NEXUS_ENABLED=true` in production from day 1.
13. **Telegram webhook path refactor:** migrate from `/<bot_token>` to fixed `/telegram/webhook` + `X-Telegram-Bot-Api-Secret-Token` header validation, so the bot token never appears in Caddy access logs.
14. **Dev compose files (both):**
    - `ops/docker-compose.dev.yml` — dev mode, single container, volume-mounts `website/` + `telegram_bot/` for hot-reload.
    - `ops/docker-compose.prod-local.yml` — strict prod parity, pulls the real image from GHCR, runs full Caddy + blue + green stack on localhost for pre-deploy rehearsal.
15. **BetterStack account:** user-managed. Plan creates monitors via dashboard only; no IaC for BetterStack in phase 1.


---

## 3. Explicit Decisions

### 3.1 DigitalOcean tier: Premium AMD $7/mo

Chosen tier: **DO Droplet `s-1vcpu-1gb` Premium AMD** at **$7/mo**, BLR1 region.

Rationale (verified against DO "Choosing a plan" docs):

| Dimension | Regular Intel ($6) | Premium Intel ($7) | **Premium AMD ($7) ✅** |
|---|---|---|---|
| vCPU / RAM | 1 / 1 GiB | 1 / 1 GiB | 1 / 1 GiB |
| CPU generation | First-gen Xeon Scalable / older EPYC | Ice Lake+ (latest 2 gens) | EPYC (latest 2 gens) |
| Memory speed | ~2400–2666 MHz | 2933 MHz | **3200 MHz** |
| Storage | SATA SSD | NVMe SSD | **NVMe SSD** |
| AVX-512 | Varies | Yes | No |
| Bandwidth egress | 1 TB | 1 TB | 1 TB |
| Price | $6/mo | $7/mo | **$7/mo** |

Why Premium AMD wins for this workload:

1. **Memory bandwidth matters most.** `numpy`, `scipy`, `networkx` PageRank, embeddings, and FastAPI JSON serialization all hit DRAM hard. 3200 MHz > 2933 MHz > 2666 MHz. This directly improves `/api/graph` and `/api/summarize` tail latency.
2. **NVMe SSD** makes blue-green image pulls and container start ~5–10s faster than SATA, which compounds over many deploys and restart recovery.
3. **Latest-gen CPU** means better single-thread IPC, which is what a single-vCPU FastAPI worker actually cares about.
4. The $1/mo premium over Regular is trivial compared to the reliability + UX upside and is consistent with user constraint #8 (zero-downtime) and #12 (UX masterclass).
5. AVX-512 is not used by our current numpy/scipy wheels in any hot path, so Premium Intel offers no unique advantage for us.

**Fallback:** If `BLR1` does not offer Premium AMD at the 1 GiB tier at deploy time, fall back to **Premium Intel $7/mo** in the same region. Do not fall back to Regular; the UX goals depend on NVMe + latest-gen memory. Do not fall back to a different region; latency from India is critical.

### 3.2 OS base image: Docker 1-Click marketplace

Use the DO Docker 1-Click Droplet image (Ubuntu 22.04 LTS + Docker CE 28.1.1 + Docker Compose plugin 2.36.0 + BuildX 0.23.0 pre-installed). No self-rolled base. Marketplace link: `https://cloud.digitalocean.com/droplets/new?image=docker-20-04`.

### 3.3 Registry: GHCR (GitHub Container Registry) — private image

The source repository `chintanmehta21/Zettelkasten_KG` is **private**, so the GHCR image is also **private**.

All images are built by GitHub Actions on `master` push and pushed to `ghcr.io/chintanmehta21/zettelkasten-kg-website:<sha>` plus a `ghcr.io/chintanmehta21/zettelkasten-kg-website:latest` tag. Push from GitHub Actions uses the workflow-scoped `GITHUB_TOKEN` with `packages: write` — no extra secret needed.

Pull on the Droplet requires a long-lived **fine-grained GitHub Personal Access Token** named `GHCR_READ_PAT`:

- Scope: `read:packages` only
- Target: the single package `chintanmehta21/zettelkasten-kg-website`
- Expiry: 365 days, annual rotation
- Stored as a GitHub Actions **Environment secret** under the `production` environment (not as a repository secret)
- Pushed to the Droplet via the deploy workflow: `echo "$GHCR_READ_PAT" | docker login ghcr.io -u chintanmehta21 --password-stdin`
- Result: `/root/.docker/config.json` mode `0600`, readable only by root; no plaintext PAT on disk

Annual rotation runbook lives in §12.

### 3.4 Reverse proxy: Caddy with blue-green upstreams

A single Caddy 2 container terminates TLS via Let's Encrypt (automatic renewal, ACME account email `chintanoninternet@gmail.com`).

Public origin: **`https://zettelkasten.in`** (apex canonical). `https://www.zettelkasten.in` issues a permanent 301 redirect to the apex. Caddy binds both IPv4 and IPv6 (`bind tcp4 tcp6`) and serves HTTP/2 + HTTP/3 (QUIC over UDP 443) by default.

Caddy sends the following headers on all non-webhook responses:

- `Strict-Transport-Security: max-age=63072000; includeSubDomains; preload`
- `X-Content-Type-Options: nosniff`
- `X-Frame-Options: DENY`
- `Referrer-Policy: strict-origin-when-cross-origin`
- `Permissions-Policy: geolocation=(), camera=(), microphone=()`

It reverse-proxies to **exactly one of** two application containers:

- `zettelkasten-blue` on host port `10000`
- `zettelkasten-green` on host port `10001`

A hot-swappable `upstream.snippet` (included by `Caddyfile`) selects which color is "live". Deploy flips the snippet and sends `SIGUSR1` to Caddy for a graceful reload — no dropped connections.

### 3.5 Host directory layout

```
/opt/zettelkasten/
  compose/
    docker-compose.blue.yml
    docker-compose.green.yml
    docker-compose.caddy.yml
    .env                      # runtime env, 0600 root-only
  caddy/
    Caddyfile
    upstream.snippet          # points at blue or green
    data/                     # Caddy cert storage volume
    config/
  data/
    kg_output/                # shared persistent notes (if local mode ever used)
    bot_data/                 # seen_urls.json, rate_store.json, etc.
  logs/                       # bind-mounted container logs for logrotate
  deploy/
    deploy.sh
    rollback.sh
    healthcheck.sh
```

### 3.6 Supabase remains on Free tier

Existing `SUPABASE_URL`, `SUPABASE_ANON_KEY`, `SUPABASE_SERVICE_ROLE_KEY` are copied from Render to the Droplet's `.env`. No schema changes, no new Supabase project, no upgrade. Dual-write + read-first-from-Supabase behavior in `website/api/routes.py` is untouched.

### 3.7 Telegram bot: same process, same port, secondary priority

The Telegram bot continues to run inside the same FastAPI process via `telegram_bot/main.py` webhook mode on port 10000. Its webhook URL will be swapped to the new host via a single `setWebhook` API call at cutover. No architectural separation in phase 1.

---

## 4. Scope

### In scope (phase 1)

1. Provision the Droplet (Premium AMD $7, BLR1, Docker 1-Click).
2. Rewrite `ops/Dockerfile` for size, cold-start, non-root, tini, healthcheck, labels.
3. Update `.dockerignore` to shrink build context.
4. Lazy-import refactor across `website/core/pipeline.py`, `website/experimental_features/nexus/service/persist.py`, and any other eager heavy imports found during audit.
5. Add `GEMINI_API_KEYS` env-var fallback to `website/features/api_key_switching/key_pool.py` without removing the existing `/etc/secrets/api_env` file-based loader (backward compatible).
6. New `ops/caddy/Caddyfile` + `upstream.snippet` for blue-green.
7. New `ops/docker-compose.blue.yml`, `docker-compose.green.yml`, `docker-compose.caddy.yml`.
8. New `ops/deploy/deploy.sh`, `rollback.sh`, `healthcheck.sh`.
9. New `ops/systemd/zettelkasten.service` wrapping `docker compose up` on boot.
10. New `.github/workflows/deploy-droplet.yml` that builds → pushes to GHCR → SSHes to Droplet → runs `deploy.sh`.
11. Delete `.github/workflows/keep-alive.yml` (no longer needed; Droplet never sleeps).
12. Host hardening: UFW, unattended upgrades, fail2ban, sysctl tuning, logrotate, swap file.
13. BetterStack heartbeat + synthetic HTTPS monitor on `/api/health`.
14. Optional: `NEXUS_ENABLED` env-var feature flag around `nexus_router` include + `/home/nexus` route (since Nexus is experimental).
15. Cutover runbook: low-TTL DNS prep, DNS flip, `setWebhook` swap, rollback procedure.

### Out of scope (phase 1)

1. Multi-node HA, load balancer, managed Kubernetes, or 2+ Droplet deployments.
2. Migrating Supabase to self-hosted on DO.
3. Moving the Telegram bot to a separate process / separate container.
4. Rewriting the in-memory rate limiter (`_rate_store`) into Redis. It is acknowledged as process-local; good enough for phase 1 because blue/green overlap is short.
5. Introducing Redis, RabbitMQ, or any queueing infra.
6. Cloudflare, Fastly, or other CDN in front of Caddy.
7. Automated Droplet snapshots or off-site backups.
8. Migrating Gemini key storage to a secrets manager (Vault, DO-hosted, etc.).
9. Replacing Caddy with nginx or Traefik.
10. Any UI or feature redesign.

---

## 5. Architecture

### 5.1 Runtime topology

```text
                 ┌─────────────────────────────────────────┐
                 │            DO Droplet (BLR1)            │
                 │    Premium AMD 1 vCPU / 1 GiB / NVMe    │
                 │                                         │
 Internet ──443──┤ Caddy 2 ──┐                             │
   │             │           │                             │
   │             │           ├──▶ zettelkasten-blue:10000 │
   │             │           │     (FastAPI + bot)         │
   │             │           │                             │
   │             │           └──▶ zettelkasten-green:10001│
   │             │                 (FastAPI + bot)         │
   │             │                                         │
   │             │   Shared bind mounts:                   │
   │             │   /opt/zettelkasten/data/kg_output      │
   │             │   /opt/zettelkasten/data/bot_data       │
   │             │   /opt/zettelkasten/logs                │
   │             └─────────────────────────────────────────┘
   │
   └── setWebhook URL ─────▶ https://<host>/<bot_token>
```

Only one of `blue`/`green` is marked as live in `upstream.snippet` at any time. Caddy's reverse proxy dials only that one. Deploys flip the snippet atomically.

### 5.2 Blue-green deploy sequence (zero-downtime)

1. GitHub Actions pushes new image `ghcr.io/…:<new_sha>` and `latest`.
2. GitHub Actions SSHes to Droplet and invokes `deploy.sh <new_sha>`.
3. `deploy.sh` identifies the current live color by reading `upstream.snippet`.
4. It `docker compose -f docker-compose.<idle>.yml pull` to fetch the new image to the idle color.
5. It `docker compose -f docker-compose.<idle>.yml up -d` to start the new container on the idle port.
6. It waits up to 30s for `healthcheck.sh` to see `GET /api/health == 200` on the idle port.
7. On success, it rewrites `upstream.snippet` to point at the idle color and `docker exec caddy caddy reload --config /etc/caddy/Caddyfile`. Caddy reload is graceful and drops zero connections.
8. It waits 20s for in-flight requests on the former-live container to drain.
9. It `docker compose -f docker-compose.<old>.yml down` for the old color.
10. On failure at any point, `rollback.sh` keeps the old color live, tears down the failed idle color, and exits non-zero so GitHub Actions marks the workflow red.

### 5.3 Lifecycles and shutdown

- Container PID 1 is `tini` — ensures `SIGTERM` → uvicorn → FastAPI lifespan teardown propagates cleanly (current Dockerfile has no init, so SIGTERM currently kills uvicorn abruptly).
- uvicorn is launched with `--timeout-graceful-shutdown 15` so in-flight requests finish before exit.
- FastAPI lifespan context (from `create_app(lifespan=…)` in `website/app.py:54`) properly stops the PTB Application before process exit.
- Caddy's graceful reload keeps old upstream connections until they complete or time out.

### 5.4 Persistence model

Render's ephemeral disk problem is solved by bind-mounting two host directories into **both** blue and green:

- `/opt/zettelkasten/data/kg_output` → `/app/kg_output` (used only if local KG mode is enabled; GitHub mode still works identically).
- `/opt/zettelkasten/data/bot_data` → `/app/bot_data` (for `seen_urls.json`, future rate-store persistence).

Shared mounts across colors means a blue-green flip is transparent to files on disk.

### 5.5 State consistency during flip

Acknowledged trade-offs (acceptable in phase 1):

1. **In-memory rate limiter `_rate_store` in `website/api/routes.py:28`.** During the ~20s overlap when blue and green are both healthy, rate counting is per-color. Abuse windows are short and limits are per-IP per-minute; drift is tolerable for phase 1. Not-in-scope Redis migration covers the fix.
2. **Graph cache** (30s TTL) is per-process. After a flip the new color has a cold cache; first `/api/graph` hit pays a Supabase round-trip. Acceptable.
3. **Supabase Auth** tokens are stateless JWTs verified via JWKS — blue-green safe. `PyJWKClient` caches keys per-process; a cold green pays one JWKS fetch (~200–500ms) on first authed hit. Acceptable.

---

## 6. Planned File Changes

### 6.1 New files

```text
ops/
  Dockerfile                            # REWRITE (see §7)
  .dockerignore                         # EXPAND (see §7.3)
  caddy/
    Caddyfile
    upstream.snippet
  docker-compose.blue.yml
  docker-compose.green.yml
  docker-compose.caddy.yml
  deploy/
    deploy.sh
    rollback.sh
    healthcheck.sh
  systemd/
    zettelkasten.service
  host/
    bootstrap.sh                        # one-shot Droplet init
    sysctl-zettelkasten.conf
    ufw-rules.sh
    logrotate-docker.conf
.github/workflows/
  deploy-droplet.yml                    # NEW
  keep-alive.yml                        # DELETE
docs/superpowers/specs/
  2026-04-09-render-to-digitalocean-migration-design.md   # THIS FILE
```

### 6.2 Edited files

```text
website/features/api_key_switching/key_pool.py
  # Add GEMINI_API_KEYS env-var fallback (see §8.1)

website/features/api_key_switching/__init__.py
  # Mirror loader order if __init__ re-exports load logic

website/core/pipeline.py
  # Move `from telegram_bot.pipeline.summarizer import GeminiSummarizer`
  # and `from telegram_bot.sources import get_extractor` out of module scope
  # into `summarize_url()` body. (lines 15–16)

website/experimental_features/nexus/service/persist.py
  # Move `from website.features.kg_features.embeddings import …` out of
  # module scope into the function(s) that actually call it. (line 17)

website/app.py
  # Optional: gate `app.include_router(nexus_router)` and the `/home/nexus`
  # route on `os.getenv("NEXUS_ENABLED", "true").lower() == "true"`.
  # Default remains on to avoid behavior change.

website/core/supabase_kg/client.py
  # `_bootstrap_env()` at line ~71 must continue to work when /etc/secrets/
  # files do not exist. Verify no-op branch is clean. (No hard rewrite
  # planned; documented here so the lazy audit covers it.)

README.md
  # No env-var table additions (per user preference). Only update the
  # deployment section's one-line pointer from "Render.com" to
  # "DigitalOcean Droplet (see docs/superpowers/specs/...)".
```

### 6.3 Deleted files

```text
.github/workflows/keep-alive.yml       # Droplet never cold-starts from sleep.
```

### 6.4 New dev-parity compose files

```text
ops/docker-compose.dev.yml
  # Dev mode. Single container, volume-mounts website/ + telegram_bot/
  # for hot-reload via uvicorn --reload. No Caddy. Runs on localhost:10000.
  # Use: docker compose -f ops/docker-compose.dev.yml up

ops/docker-compose.prod-local.yml
  # Strict prod parity. Pulls ghcr.io/chintanmehta21/zettelkasten-kg-website:latest
  # (or builds locally with BuildKit cache), runs Caddy + blue + green stack
  # on localhost. Lets you rehearse a full blue-green flip before deploying.
  # Requires GHCR_READ_PAT locally OR builds the image from source.
  # Use: docker compose -f ops/docker-compose.prod-local.yml up
```

### 6.5 Telegram webhook path refactor (Q15 option c)

```text
telegram_bot/main.py
  # Change webhook path from f"/{settings.telegram_bot_token}" to a fixed
  # path like "/telegram/webhook". Continue to validate the secret header
  # X-Telegram-Bot-Api-Secret-Token (already supported via WEBHOOK_SECRET).
  # This removes the bot token from Caddy access logs, making phase-2 log
  # aggregation safe.

telegram_bot/ (setWebhook call site)
  # Update the setWebhook URL on startup to use the new path.

docs / runbook
  # Cutover includes a single manual setWebhook call with the new URL
  # + WEBHOOK_SECRET header.
```

---

## 7. Docker Image Optimization ("UX masterclass")

Per constraint #12, image size and cold-start must feel premium on first visit. Six feature-scoped subagent audits fed into the decisions below.

### 7.1 Multi-stage Dockerfile (rewrite)

Design intent (not literal file — exact syntax lives in the plan):

1. **Stage `builder`:** `python:3.12-slim`, install `build-essential`, create `/opt/venv`, `pip install --no-cache-dir -r ops/requirements.txt`, `python -m compileall /opt/venv`.
2. **Stage `runtime`:** `python:3.12-slim`, install only `ca-certificates`, `tini`, `curl` (for healthcheck debug), nothing else.
3. Create `appuser` UID 1000, `/app` owned by appuser.
4. `COPY --from=builder /opt/venv /opt/venv`.
5. `COPY --chown=appuser:appuser telegram_bot/ telegram_bot/`.
6. `COPY --chown=appuser:appuser website/ website/`.
7. `COPY --chown=appuser:appuser run.py pyproject.toml ./`.
8. `ENV PATH=/opt/venv/bin:$PATH PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1`.
9. `USER appuser`.
10. `EXPOSE 10000`.
11. `HEALTHCHECK --interval=15s --timeout=3s --start-period=10s --retries=3 CMD curl -fsS http://127.0.0.1:10000/api/health || exit 1`.
12. `ENTRYPOINT ["/usr/bin/tini", "--"]`.
13. `CMD ["python", "run.py"]`.
14. OCI labels: `org.opencontainers.image.source`, `.revision`, `.created`, `.title`, `.licenses`.

Layer ordering puts `requirements.txt` + venv install BEFORE app code copies, so code-only changes reuse the venv layer.

### 7.2 Dependency audit (`ops/requirements.txt`)

Move to a separate dev file (not installed in the image):

- `pytest`, `pytest-asyncio`, `pytest-httpx`

Keep in runtime (all confirmed used in request paths or orchestrator): `fastapi`, `uvicorn`, `python-telegram-bot`, `httpx`, `google-genai`, `trafilatura`, `lxml`, `praw`, `yt-dlp`, `youtube-transcript-api`, `pydantic`, `pydantic-settings`, `pyyaml`, `python-dotenv`, `jinja2`, `cryptography`, `supabase`, `PyJWT`, `networkx`, `numpy`, `scipy`.

Heavy hitters (will not remove, only justify): `google-genai` (~49 MB), `scipy` (~61 MB), `numpy` (~42 MB), `yt-dlp` (~28 MB). These are load-bearing and stay.

### 7.3 `.dockerignore` expansion

Add (beyond current):

```text
.git
.github
.venv
.worktrees
.vscode
.idea
.claude
.code-build
__pycache__
*.pyc
*.pyo
*.log
*.md
!README.md
docs/
tests/
node_modules/
.DS_Store
Thumbs.db
kg_output/
bot_data/
.env
.env.*
```

Target build context: < 10 MB.

### 7.4 Feature-scoped optimization findings

Each feature subagent delivered concrete wins; these are folded into the Dockerfile + Caddy + FastAPI app:

**Home + user_zettels + KG UI (static-asset heavy):**
- Caddy adds `Cache-Control: public, max-age=31536000, immutable` to `/css/*`, `/js/*`, `/kg/css/*`, `/kg/js/*`, `/home/css/*`, `/home/js/*`, `/home/zettels/css/*`, `/home/zettels/js/*`, `/about/css/*`, `/about/js/*`, `/pricing/css/*`, `/pricing/js/*`, `/artifacts/*` (SHA-busted or not — revisit busting in a later phase).
- Caddy enables `encode zstd gzip` for the above plus `/api/graph`.
- Caddy adds `Cache-Control: public, max-age=30` on `/api/graph` to align with the 30s in-memory TTL.
- `user_zettels.js` (45 KB) and `home.css` (29 KB) are the biggest single assets. Compression yields ~60–70% wire reduction.

**Summarizer `/api/summarize` (compute-heavy):**
- Lazy-import `GeminiSummarizer` and `get_extractor` — saves ~120 MB resident + ~1–2s first-request latency on cold start. See §8.2.
- Keep the in-memory rate limiter; explicitly documented as blue-green lossy but acceptable.

**KG Intelligence (NetworkX / scipy analytics):**
- Analytics functions already lazy-import `networkx` and `scipy` inside function bodies in `website/features/kg_features/analytics.py`. Verified OK.
- `embeddings.py` is eagerly pulled in by `persist.py` — that's the one bad chain; fixed in §8.2.

**Footer (about + pricing) + Auth:**
- Tiny surfaces, no refactor needed. Just ensure Caddy caches their assets like the rest. `auth.css` (8.6 KB), `auth.js` (13 KB), `callback.html` (4.6 KB) — all fast.
- `get_current_user` / `get_optional_user` dependencies are fine; JWKS client is lazily constructed on first use.

**Nexus (experimental):**
- Gate `include_router(nexus_router)` and `/home/nexus` route on `NEXUS_ENABLED`. Default `true` so prod behavior is unchanged, but the flag exists for emergency disable.
- Fix the `persist.py` eager import so importing the nexus router doesn't drag in embeddings + numpy.

**Docker image build itself:**
- Use BuildKit cache mount for `pip install`: `RUN --mount=type=cache,target=/root/.cache/pip pip install …` in CI. Saves ~40s per build.
- Use `buildx` with `linux/amd64` platform (Droplet is amd64). No multi-arch.
- Tag both `:<sha>` and `:latest` on every push; Droplet pulls `:<sha>`.

### 7.5 Target image metrics

- Compressed image size on GHCR: **≤ 550 MB** (down from current ~750 MB estimated).
- Cold `docker run` to healthcheck-passing: **≤ 6s** on NVMe (Premium AMD).
- First `/api/health` 200: **≤ 500ms** from `docker run`.
- First `/` (home HTML) response on a cold container: **≤ 800ms** p95.
- First `/api/summarize` on a cold container: **≤ 4s** p95 (Gemini + extractor initialization).

---

## 8. Application Code Changes

### 8.1 `GEMINI_API_KEYS` env-var fallback (backward compatible)

`website/features/api_key_switching/key_pool.py` currently loads keys from an `api_env` file at project root or `/etc/secrets/api_env` (Render Secret File). DO Droplets have no equivalent of Render's Secret Files, so an env-var fallback is required. The loader order becomes:

1. `api_env` file at existing paths (unchanged — so local dev and any future file-based deploy still work).
2. `GEMINI_API_KEYS` env var, comma-separated list of keys.
3. `GEMINI_API_KEY` single-key fallback (existing behavior).

If none yield any keys, the loader raises as today. This change is strictly additive; existing Render deploy would keep working unmodified.

### 8.2 Lazy-import refactor (critical path)

Two confirmed eager-import chains import ~120+ MB of runtime libs at module load, which `python run.py` pays before the first request is even routed. Both are in code paths that the website imports at startup:

1. `website/core/pipeline.py:15-16`
   - `from telegram_bot.pipeline.summarizer import GeminiSummarizer`
   - `from telegram_bot.sources import get_extractor`
   - These drag in `google-genai`, `trafilatura`, `lxml`, `praw`, `yt-dlp`, and the entire extractor plugin registry at *import time*.
   - Fix: move both imports inside `summarize_url()` (or the single internal helper that actually uses them).

2. `website/experimental_features/nexus/service/persist.py:17`
   - `from website.features.kg_features.embeddings import find_similar_nodes, generate_embedding`
   - This drags in `numpy` + embedding model initialization before any Nexus request is served.
   - Fix: move both names inside the function that calls them.

During the plan phase, a final audit pass must also check:
- `website/features/kg_features/analytics.py` (expected clean — already lazy inside functions)
- `website/features/kg_features/retrieval.py` (expected clean)
- `website/features/kg_features/entity_extractor.py` (expected clean)
- `website/features/kg_features/nl_query.py` (expected clean)
- `website/api/routes.py` (check for any top-level heavy imports)
- `website/api/nexus.py` (check for any top-level heavy imports)

Success criteria for this refactor:
- `python -c "from website.app import create_app; create_app()"` imports must stay under ~40 MB RSS delta from the interpreter baseline (measured via `resource.getrusage`).
- Time from `docker run` to Caddy forwarding the first `/api/health` must drop at least 1.5s.

### 8.3 Optional `NEXUS_ENABLED` feature flag

Add a single env-var gate to `website/app.py` in `create_app()`:

```
if os.getenv("NEXUS_ENABLED", "true").lower() == "true":
    app.include_router(nexus_router)
    # and enable /home/nexus route
```

Default is `true` so prod behavior is identical. The flag exists purely for emergency disable without a redeploy.

### 8.4 `run.py` launch flags

No file rewrite, but document the uvicorn launch parameters used inside the container:

- `--host 0.0.0.0`
- `--port 10000`
- `--workers 1` (single-vCPU Droplet; more workers on 1 GiB RAM just thrashes)
- `--timeout-graceful-shutdown 15`
- `--access-log` on (stdout → docker → logrotate)
- `--log-config` pointing at a small logging config (JSON-ish structured if easy, else default)

### 8.5 Delete `.github/workflows/keep-alive.yml`

No longer needed. Droplet always runs. The cron pings only existed to defeat Render's free-tier sleep. Remove the file and the `RENDER_URL` secret documentation line from README.

---

## 9. Host-Level Hardening

### 9.1 OS baseline (via `ops/host/bootstrap.sh`)

1. `apt-get update && apt-get -y dist-upgrade`.
2. `unattended-upgrades` enabled for security channels only; auto-reboot disabled (reboot only on-demand).
3. `fail2ban` installed with sshd jail.
4. UFW rules (`ops/host/ufw-rules.sh`):
   - `default deny incoming`
   - `default allow outgoing`
   - `allow 22/tcp` (SSH, optionally rate-limited)
   - `allow 80/tcp` (HTTP → Caddy redirect to 443)
   - `allow 443/tcp` (HTTPS)
5. Swap file: 1 GiB at `/swapfile`, `swappiness=10`. Protects against OOM on a 1 GiB box.
6. `/etc/security/limits.d/zettelkasten.conf`: `nofile 65535` for the docker user.
7. `/etc/sysctl.d/99-zettelkasten.conf`:
   - `net.core.somaxconn=4096`
   - `net.ipv4.tcp_max_syn_backlog=4096`
   - `net.ipv4.ip_local_port_range=1024 65535`
   - `fs.file-max=1048576`
   - `vm.swappiness=10`
8. Logrotate for docker json-file logs: 7 days, daily, compress, delaycompress, missingok, notifempty, copytruncate.

### 9.2 Systemd wrapper (`ops/systemd/zettelkasten.service`)

A single unit that:
1. `After=docker.service`, `Requires=docker.service`.
2. `WorkingDirectory=/opt/zettelkasten/compose`.
3. `ExecStart=/usr/bin/docker compose -f docker-compose.caddy.yml -f docker-compose.<live>.yml up`.
4. `ExecStop=/usr/bin/docker compose -f docker-compose.caddy.yml -f docker-compose.<live>.yml down --timeout 20`.
5. `Restart=always`, `RestartSec=5`.
6. `LimitNOFILE=65535`.
7. `StartLimitIntervalSec=300`, `StartLimitBurst=5`.
8. `WantedBy=multi-user.target`.

The `<live>` placeholder is resolved from a `ACTIVE_COLOR` file at boot by a small drop-in script; `deploy.sh` updates it as part of the flip.

### 9.3 Container-level reliability (in compose files)

For both blue and green:

1. `restart: unless-stopped`
2. `mem_limit: 768m` (leaves ~256 MB for Caddy + host)
3. `memswap_limit: 768m` (no swap for container)
4. `pids_limit: 512`
5. `healthcheck` matching Dockerfile (`/api/health`)
6. `stop_grace_period: 20s` (aligns with uvicorn `--timeout-graceful-shutdown 15`)
7. `logging.driver: json-file` with `max-size: 10m`, `max-file: 3`
8. `read_only: true` with explicit `tmpfs: [/tmp]` so the FS is immutable except `/tmp`
9. `cap_drop: [ALL]`, `cap_add: [NET_BIND_SERVICE]` (not strictly needed since container binds 10000, but cheap hardening)
10. `security_opt: [no-new-privileges:true]`

For Caddy:
1. `restart: unless-stopped`
2. `mem_limit: 128m`
3. Bind mount `/opt/zettelkasten/caddy/Caddyfile`, `upstream.snippet`, `data/`, `config/`.
4. Port `80:80` and `443:443`.

### 9.4 BetterStack monitoring (user-managed account)

The BetterStack account is owned and configured by the user via the BetterStack web dashboard. The plan does **not** include account creation, IaC, or API automation for BetterStack. The plan just lists the monitors the user should create after cutover.

Recommended monitors (user creates these in dashboard):

- One HTTPS monitor hitting `https://zettelkasten.in/api/health` every 30s from at least 3 regions (US East, EU, South Asia).
- One HTTPS monitor hitting `https://zettelkasten.in/` every 60s from South Asia region (user-facing path).
- Alert channels: email (`chintanoninternet@gmail.com`) + Telegram integration to `ALLOWED_CHAT_ID`.
- Alerting thresholds: 2 consecutive failed probes, p95 response time > 2s over 5 min.

The plan provides a one-paragraph "set up these 2 monitors in BetterStack" task, not a config file.

### 9.5 Uptime target math

99.9% = ≤ 43.8 min downtime/month. Reliability sources and their expected monthly impact:

- Host OS crash / kernel panic: Droplet watchdog reboots in < 2 min, systemd brings stack back up automatically. Budget: ≤ 5 min/month.
- Docker daemon restart: systemd brings stack back up. Budget: ≤ 2 min/month.
- App container OOM / crash: compose `restart: unless-stopped` + HEALTHCHECK kicks recovery in < 10s. Budget: ≤ 5 min/month cumulative.
- Blue-green deploy pathological failure: rollback in < 30s. Budget: ≤ 2 min/month.
- DO BLR1 platform incident: Outside our control. Budget (conservative): ≤ 20 min/month.
- Supabase Free tier incident: Graceful — API degrades, Caddy still serves static UI from the container. Not counted as full downtime.

Total budget headroom: ~34 min/month ≤ 43.8 min/month target. Matches 99.9%.

---

## 10. Zero-Downtime Migration Cutover

The migration from Render to the Droplet must not drop a single website request. Telegram bot downtime should be ≤ 10 seconds, but if the website needs longer, website wins.

### 10.1 Pre-cutover (day -3 to day -1)

**Day -3: Domain + DNS bootstrap**

1. Buy `zettelkasten.in` at **GoDaddy**.
2. Create a free **Cloudflare** account. Click "Add a site" → `zettelkasten.in` → choose the Free plan. Cloudflare imports any existing records (there should be none on a fresh domain).
3. Copy the 2 nameservers Cloudflare assigns (e.g., `amy.ns.cloudflare.com`, `rick.ns.cloudflare.com`).
4. Log into GoDaddy → Domain settings → Nameservers → switch from "GoDaddy defaults" to the 2 Cloudflare nameservers.
5. Wait for nameserver propagation (typically 1–4 hours, occasionally 24h). Verify with `dig NS zettelkasten.in +short` from multiple vantages — should return only the Cloudflare nameservers.
6. In Cloudflare DNS, enable **DNSSEC** (one-click). Copy the DS record Cloudflare shows and paste it into GoDaddy's DS record field. Verify with `dig zettelkasten.in +dnssec`.
7. In Cloudflare DNS, add a `CAA` record: `zettelkasten.in CAA 0 issue "letsencrypt.org"`. Locks cert issuance to Let's Encrypt.

**Day -1: Droplet bootstrap**

8. Provision DO Droplet `s-1vcpu-1gb` Premium AMD in BLR1 using the Docker 1-Click image. Enable free IPv6 at provision time.
9. SSH in as root, run `ops/host/bootstrap.sh` (installs UFW, fail2ban, unattended-upgrades, creates `deploy` user, sets swap, sysctl tuning, writes logrotate config, installs systemd unit).
10. UFW opens: 22/tcp (SSH), 80/tcp (HTTP redirect), 443/tcp (HTTPS), 443/udp (HTTP/3 QUIC).
11. In Cloudflare DNS, add a **temporary staging hostname** `stage.zettelkasten.in` with:
    - `A` record → Droplet IPv4
    - `AAAA` record → Droplet IPv6
    - Both with "DNS only" (grey cloud, not orange cloud).
    - TTL: auto (Cloudflare manages this).
12. Trigger the initial GitHub Actions deploy (via `workflow_dispatch`) targeting `stage.zettelkasten.in` as the Caddy hostname. Caddy completes its Let's Encrypt ACME flow for `stage.zettelkasten.in` and obtains a real cert. The whole stack comes up: blue + Caddy.
13. Smoke-test every route on `https://stage.zettelkasten.in`:
    - `GET /` → 200, home HTML
    - `GET /api/health` → 200
    - `GET /api/graph` → 200, JSON (node count matches Render)
    - `POST /api/summarize` with a throwaway URL → 200
    - `GET /knowledge-graph` → 200
    - `GET /home` (authed and unauthed)
    - `GET /home/zettels` (authed)
    - `GET /home/nexus` (authed, since `NEXUS_ENABLED=true`)
    - `GET /about`, `GET /pricing`
    - `GET /auth/callback`
    - Verify HTTP/3 is active: `curl --http3 -I https://stage.zettelkasten.in/`
    - Verify IPv6: `curl -6 -I https://stage.zettelkasten.in/`
    - Verify HSTS header present: `curl -I https://stage.zettelkasten.in/ | grep -i strict-transport-security`
14. Confirm Supabase reads/writes work from the new host (`/api/graph` returns the same node count as Render; submit a test URL through `/api/summarize` and confirm the new node appears).
15. Confirm the Gemini key pool loads from `GEMINI_API_KEYS` env var (check logs for `[KeyPool] loaded N keys from env var`).
16. Test a blue-green flip locally on the droplet: push a trivial no-op change, watch the deploy workflow promote green, verify zero 5xx during the flip.

### 10.2 Cutover (day 0)

1. **T-60 min:** Drop TTL on the eventual production records (apex + www) that will be added in step 4 below. Do this by adding the records *now* with TTL 60s pointing at the Droplet — but as **DNS records for a hostname nobody has yet**. Nothing hits them. This just pre-stages.

   *Actually, simpler:* since the apex and www are brand new (nobody has cached them), skip the pre-flip TTL drop. The pre-flip TTL drop is only needed when cutting over an *existing* hostname that resolvers have cached. For a brand-new hostname, the first resolver query IS the flip.

2. **T-10 min:** Final readiness check on `stage.zettelkasten.in` (§10.1 step 13 smoke tests).

3. **T-0:** In Cloudflare DNS, add the **production records** for the real hostname:
   - `zettelkasten.in` → `A` → Droplet IPv4, TTL 60s, DNS-only (grey cloud)
   - `zettelkasten.in` → `AAAA` → Droplet IPv6, TTL 60s, DNS-only
   - `www.zettelkasten.in` → `CNAME` → `zettelkasten.in`, TTL 60s, DNS-only
4. **T-0 + 30 s:** Caddy on the droplet sees a request to `zettelkasten.in` for the first time (from BetterStack, our smoke test, or the first real user) and kicks off the Let's Encrypt ACME challenge for `zettelkasten.in` + `www.zettelkasten.in`. Completes in ~10 s.
5. **T-0 + 1 min:** Site is live on `https://zettelkasten.in`. Render is still running in parallel but receives no traffic (no DNS points at it).
6. **T-0 + 2 min:** Call Telegram `setWebhook` with the new URL:
   ```
   curl "https://api.telegram.org/bot<BOT_TOKEN>/setWebhook" \
     -d "url=https://zettelkasten.in/telegram/webhook" \
     -d "secret_token=<WEBHOOK_SECRET>"
   ```
   This is **atomic** on Telegram's side — the very next Telegram update goes to the Droplet. This is the only bot downtime, measured in milliseconds.
7. **T+5 min:** Tail Caddy access logs on the droplet to confirm real end-user traffic and BetterStack probe traffic. Tail Render logs to confirm traffic has drained to zero (Render will still handle anyone with stale cached IPs, but for a brand-new hostname this is nobody).
4. **T+60s:** Most resolvers now point at the Droplet. Verify via `dig +short` from multiple vantage points.
5. **T+5 min:** Tail Caddy access logs on the Droplet to confirm real end-user traffic. Tail Render logs to confirm traffic has drained to near-zero.
8. **T+30 min:** Pause (but do not delete) the Render service. Keep it paused for 7 days as an emergency rollback target.
9. **T+1 hour:** If everything looks green, raise the TTL on the production DNS records from 60s to **3600s** (1 hour). Longer TTLs mean client resolvers cache longer, which measurably reduces DNS lookup latency for repeat visitors. Cloudflare honors both during propagation. Delete the temporary `stage.zettelkasten.in` records once the main hostname is fully verified.
10. **T+7 days:** Delete the Render service.

### 10.3 Post-cutover hardening checklist

- [ ] DNSSEC enabled in Cloudflare, DS record copied into GoDaddy (§10.1 day -3 step 6).
- [ ] CAA record present in Cloudflare locking cert issuance to Let's Encrypt (§10.1 day -3 step 7).
- [ ] HTTP/3 verified: `curl --http3 -I https://zettelkasten.in/` returns `HTTP/3 200`.
- [ ] IPv6 verified: `curl -6 -I https://zettelkasten.in/` returns 200.
- [ ] HSTS header present with `max-age=63072000; includeSubDomains; preload`.
- [ ] Cert transparency monitor (Cloudflare dashboard or crt.sh) confirms only Let's Encrypt certs for the hostname.
- [ ] BetterStack HTTPS monitor reports green.
- [ ] DNS TTL raised back to 3600s.
- [ ] Render service paused, not deleted.
- [ ] `setWebhook` response from Telegram confirms `"url": "https://zettelkasten.in/telegram/webhook"`, `"has_custom_certificate": false`, `"pending_update_count": 0`.

### 10.4 Rollback path (if something breaks mid-cutover)

1. **If Droplet is broken before DNS records are added:** Abort — do not add the production DNS records, do not call `setWebhook`. No user impact. Render keeps serving on its own hostname.
2. **If Droplet breaks after production DNS records are added but before propagation finishes:** Delete the production DNS records from Cloudflare. No cached resolvers exist for a brand-new hostname, so rollback is near-instant. Leave `setWebhook` pointing at Render if it's still healthy; otherwise call `setWebhook` back to the old Render URL.
3. **If a single feature on the Droplet breaks after cutover:** Flip Caddy upstream back to the last-known-good image via `rollback.sh` (it re-points `upstream.snippet` to the last-good color/tag and reloads Caddy). No DNS change required. ≤ 30 seconds.
4. **If the Droplet itself dies (host-level):** DO console → reboot Droplet. systemd brings the stack back automatically. ≤ 2 minutes.
5. **If the Droplet IP changes (rebuild from snapshot, etc.):** Update the Cloudflare A/AAAA records via the Cloudflare dashboard or API. Because of delegated Cloudflare DNS, propagation is ~5 seconds. `setWebhook` URL stays the same (it's hostname-based).

### 10.4 Success criteria

- Zero 5xx errors observed from the website during the cutover window in Caddy logs.
- BetterStack reports no incidents for the public hostname during T-0 to T+1 hour.
- `/api/summarize` round-trips work end-to-end within 10 minutes of cutover.
- Telegram bot responds to a `/ping` or test command within 30 seconds of the `setWebhook` call.
- `graph.json` / Supabase show writes landing from the new host.

---

## 11. Observability

### 11.1 Logs

- Container stdout/stderr → docker json-file → logrotate (10 MB × 3).
- `docker logs` from ops access; in the future move to Loki/Grafana Cloud if needed (out of scope phase 1).
- Caddy access log → `/opt/zettelkasten/logs/caddy-access.log`, separate logrotate rule.

### 11.2 Metrics

- Phase 1 intentionally **no** Prometheus / Grafana / node_exporter. The 1 GiB box cannot afford the overhead and the single-node topology doesn't justify it.
- BetterStack HTTPS monitor gives availability + response time.
- DO Droplet built-in metrics (CPU, RAM, disk, bandwidth) give host-level visibility for free.

### 11.3 Alerting

- BetterStack: alert on 2 consecutive failed `/api/health` probes (= ~60s outage).
- BetterStack: alert on p95 response time > 2s over 5 minutes.
- Optional phase 2: Telegram bot self-pings a BetterStack heartbeat every 60s from a background task.

---

## 12. CI/CD

### 12.1 GitHub Actions workflow layout

Two workflow files:

1. **`.github/workflows/ci.yml`** — runs on every `pull_request` (opened, synchronize) and every `push` to `master`. Single job: **`test`**
   - `actions/checkout@v4`
   - `actions/setup-python@v5` with Python 3.12
   - `pip install -r ops/requirements.txt -r ops/requirements-dev.txt`
   - `pytest -q` (mocked, no network, no `--live`)
   - Deploy workflow `needs: test` via `workflow_run` or by duplicating the same `test` job as the first step of `deploy-droplet.yml`. The plan phase picks the cleaner of the two.

2. **`.github/workflows/deploy-droplet.yml`** — runs on `push` to `master` (after `ci.yml` passes) and `workflow_dispatch`.
   - Environment: `production` (has protection rule requiring manual approval).
   - Jobs:
     - **`test`** (mirrors ci.yml for safety belt-and-suspenders)
     - **`build-and-push`** (`needs: test`)
       - `actions/checkout@v4`
       - `docker/setup-buildx-action@v3`
       - `docker/login-action@v3` → GHCR using `GITHUB_TOKEN` (has `packages: write`; this scope must be declared in the workflow `permissions:` block)
       - `docker/build-push-action@v5`
         - context: repo root
         - file: `ops/Dockerfile`
         - platforms: `linux/amd64`
         - tags: `ghcr.io/chintanmehta21/zettelkasten-kg-website:${{ github.sha }}`, `ghcr.io/chintanmehta21/zettelkasten-kg-website:latest`
         - cache-from: `type=gha`
         - cache-to: `type=gha,mode=max`
         - push: true
         - provenance: false (keeps image smaller)
     - **`deploy`** (`needs: build-and-push`, `environment: production`)
       - `appleboy/ssh-action@v1` SSHes into Droplet as `deploy` user.
       - Before running `deploy.sh`, the workflow runs a small inline script that:
         - Writes the `.env` file on the Droplet from Environment secrets (overwriting any previous version).
         - Runs `echo "$GHCR_READ_PAT" | docker login ghcr.io -u chintanmehta21 --password-stdin` so the Droplet can pull the private image.
       - Then runs: `/opt/zettelkasten/deploy/deploy.sh ${{ github.sha }}`
       - On failure: automatically invokes `rollback.sh` via `if: failure()`.

3. **`.github/workflows/live-tests.yml`** — runs on:
   - `workflow_dispatch` (manual button in Actions tab)
   - `schedule: cron: '0 21 * * 6'` (Sunday 21:00 UTC = Sunday 02:30 IST Monday; readable as "weekly Sunday night")
   - Single job: `pytest --live` with real API credentials from the `production` environment. Notifies via BetterStack / Telegram on failure.
   - This is the only place Gemini quota is burned by CI.

Workflow `concurrency` config on `deploy-droplet.yml`: `group: deploy-prod`, `cancel-in-progress: true` — a new push supersedes an in-flight deploy.

### 12.2 Required GitHub Environment secrets (under `production` environment)

Runtime secrets (written to Droplet `.env` on every deploy):

- `TELEGRAM_BOT_TOKEN`
- `ALLOWED_CHAT_ID`
- `WEBHOOK_SECRET`
- `GEMINI_API_KEYS` (comma-separated, up to 10)
- `SUPABASE_URL`, `SUPABASE_ANON_KEY` (**no** service role key — see §3.6 and Q12)
- `GITHUB_TOKEN_FOR_NOTES` (the token for pushing Obsidian notes; NOT to be confused with the workflow-scoped `GITHUB_TOKEN`)
- `GITHUB_REPO_FOR_NOTES`
- `NEXUS_GOOGLE_CLIENT_ID`, `NEXUS_GOOGLE_CLIENT_SECRET`
- `NEXUS_GITHUB_CLIENT_ID`, `NEXUS_GITHUB_CLIENT_SECRET`
- `NEXUS_REDDIT_CLIENT_ID`, `NEXUS_REDDIT_CLIENT_SECRET`
- `NEXUS_TWITTER_CLIENT_ID`, `NEXUS_TWITTER_CLIENT_SECRET`
- `NEXUS_TOKEN_ENCRYPTION_KEY` (Fernet key)

Deploy plumbing:

- `DROPLET_HOST` — public IPv4 of Droplet
- `DROPLET_SSH_USER` — `deploy`
- `DROPLET_SSH_KEY` — private ed25519 key for the `deploy` user
- `DROPLET_SSH_PORT` — `22`
- `GHCR_READ_PAT` — fine-grained PAT with `read:packages` scope, scoped to the single package `chintanmehta21/zettelkasten-kg-website`, 365-day expiry. Used by the Droplet to pull the private image. **Not** used by GitHub Actions itself for pushing (the workflow-scoped `GITHUB_TOKEN` handles that).

Protection rule on the `production` environment: **manual approval required** (you click "Review pending deployment" in GitHub Actions before each deploy runs).

### 12.3 Annual PAT rotation runbook

Once a year (reminder in BetterStack calendar or Google Calendar):

1. GitHub → Settings → Developer settings → Personal access tokens → Fine-grained tokens → create new token, same config as the expiring one, 365-day expiry.
2. Copy the new token.
3. GitHub → Repo → Settings → Environments → `production` → edit `GHCR_READ_PAT` → paste new value.
4. Trigger a `workflow_dispatch` deploy. The deploy script writes `/root/.docker/config.json` on the droplet with the new token.
5. Verify the droplet can pull the latest image: `docker pull ghcr.io/chintanmehta21/zettelkasten-kg-website:latest`.
6. Revoke the old PAT in GitHub → Developer settings → Personal access tokens.

### 12.4 Droplet-side `deploy.sh` responsibilities

1. Accept new image sha as arg.
2. Verify `/root/.docker/config.json` has valid GHCR credentials (the deploy workflow writes it fresh each run).
3. Identify current live color.
4. Pull new image for the idle color.
5. Start idle color with new image.
6. Wait for healthcheck (`healthcheck.sh` polls `/api/health` on idle port up to 30 tries × 1s).
7. Atomically rewrite `upstream.snippet` to idle color's port.
8. `docker exec caddy caddy reload --config /etc/caddy/Caddyfile`.
9. Sleep 20s for drain.
10. Stop old color.
11. Log success line with sha + timestamp to `/opt/zettelkasten/logs/deploy.log`.
12. On any failure, call `rollback.sh` and exit non-zero.

### 12.5 `rollback.sh` responsibilities

1. Detect which color should be live (last known good from `/opt/zettelkasten/ACTIVE_COLOR`).
2. Ensure live color is still up; if not, start it with the previous image.
3. Rewrite `upstream.snippet` back to live color.
4. Reload Caddy.
5. Tear down any half-started idle color.
6. Log rollback with reason.

---

## 13. Cost Summary

| Item | Provider | Monthly | Annual |
|---|---|---|---|
| Droplet `s-1vcpu-1gb` Premium AMD, BLR1 | DigitalOcean | **$7.00** | $84.00 |
| Domain `zettelkasten.in` registration | GoDaddy | ~$0.20 | ~₹200 y1 / ~₹1,400 renewal ≈ $2.50 y1 / $17 renewal |
| DNS (delegated from GoDaddy) | Cloudflare Free | $0 | $0 |
| Firewall (UFW on-host) | — | $0 | $0 |
| Container registry (private images) | GHCR | $0 | $0 |
| TLS certificates | Let's Encrypt via Caddy | $0 | $0 |
| External monitoring | BetterStack Free | $0 | $0 |
| Database + auth + storage | Supabase Free | $0 | $0 |
| Backups | None in phase 1 (per constraint #6) | $0 | $0 |
| **Total** | | **~$7.20/mo** | **~$86/y1, ~$101/renewal** |

Current Render cost baseline is comparable, but the Droplet buys **persistent disk**, **zero-downtime deploys**, **no cold starts**, and **full control of the stack**.

Year 2+ cost watch: GoDaddy's `.in` renewal is ~₹1,400 (roughly $17/y). If that becomes objectionable, the domain can be **transferred** to Cloudflare Registrar later if/when Cloudflare adds `.in` to their supported TLD list, or to Namecheap for ~₹900/y. Transfer does not affect the running deployment because DNS is already delegated to Cloudflare — only the billing relationship moves.

---

## 14. Risks and Mitigations

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| 1 GiB RAM OOM under concurrent summarize + graph load | Medium | Container restart, brief 503s | `mem_limit: 768m`, swap file, memory-aware Caddy concurrency, aggressive lazy-imports, BetterStack alert on p95 latency |
| Premium AMD not available in BLR1 at provision time | Low | None — falls back to Premium Intel $7 | Fallback documented in §3.1 |
| BLR1 region incident | Low | Full site down for incident duration | Accepted for phase 1 single-node; phase 2 can add a standby region |
| Supabase Free tier hits limits (bandwidth or rows) | Medium (grows with usage) | Writes fail, reads degrade | Monitor via Supabase dashboard; upgrade to Pro when it happens (not pre-emptively per constraint #2) |
| Blue-green deploy overlap causes duplicated work in bot handlers | Low | Duplicate Telegram message processing for a few seconds | Telegram update IDs dedupe inside PTB; acceptable for phase 1 |
| In-memory rate limiter bypass during blue-green overlap | Low | A determined attacker could ~2x their rate-limited traffic for ~20s per deploy | Accepted phase-1 trade-off; Redis migration is phase-2 work |
| Let's Encrypt rate limits hit during cert provisioning | Low | Caddy keeps using existing cert | Use `/config` volume to persist ACME state; deploy staging on temp hostname first per §10.1 |
| GHCR outage blocks deploy | Low | Cannot deploy new code; existing site keeps running | Rollback script is local to Droplet and doesn't need GHCR |
| DNS propagation lag leaves some users on Render post-cutover | None (new hostname, no cache to invalidate) | None | Brand-new hostname means no resolver has cached anything; first resolution lands on Droplet |
| GoDaddy → Cloudflare nameserver delegation misconfigured | Low | Domain unresolvable until fixed | Verify NS via `dig NS zettelkasten.in +short` before touching production records; day -3 buffer before cutover |
| Droplet SSH key compromise | Low | Full host takeover | UFW, fail2ban, SSH key-only auth, no password, rotate on suspicion |
| `GHCR_READ_PAT` expires unnoticed | Medium (annual) | Droplet cannot pull new images; existing container stays alive | Calendar reminder 30 days before expiry; §12.3 rotation runbook |
| Cloudflare DNS outage | Very Low (Cloudflare has 100% SLA DNS) | Domain unresolvable | Out of scope phase 1; phase 2 can add secondary DNS (e.g., Route 53 as failover) |

---

## 15. Success Metrics (post-migration, measured week 1)

1. Website uptime (BetterStack) ≥ 99.9% over the first 7 days.
2. `/api/health` p95 latency ≤ 100 ms from BLR1-adjacent vantage.
3. `/` (home) TTFB p95 ≤ 500 ms from the user's region.
4. `/api/graph` p95 ≤ 400 ms (Supabase read path) or ≤ 50 ms (cache hit).
5. `/api/summarize` p95 ≤ 6 s (Gemini + extractor variance dominates; this is a sanity bound, not a regression gate).
6. Zero user-reported outages during cutover.
7. Zero 5xx spikes visible in Caddy logs during cutover window.
8. Image size on GHCR ≤ 550 MB compressed.
9. Cold `docker run` → `/api/health 200` ≤ 6 s.
10. At least one zero-downtime blue-green deploy verified in production within week 1 (push a trivial change, observe zero 5xx).

---

## 16. Decisions Log (all resolved during brainstorming + spec review)

All questions raised during brainstorming are resolved. Kept here as an audit trail so the implementation plan can reference the decision rationale if needed.

| # | Question | Resolution |
|---|---|---|
| 1 | Final production hostname + DNS provider | `zettelkasten.in` purchased at GoDaddy; DNS delegated to Cloudflare Free (grey cloud / DNS only) |
| 2 | `deploy` SSH user bootstrap | Manual SSH as root on first boot, run `ops/host/bootstrap.sh`, which creates `deploy` user, installs public key from GitHub secret, disables root SSH after. One-time manual step. |
| 3 | BetterStack account | User-managed via dashboard. Plan does not include account creation or IaC for BetterStack. |
| 4 | Nexus default state | `NEXUS_ENABLED=true` in production from day 1. Flag exists as emergency kill-switch only. |
| 5 | Bot token in Caddy logs | Fix is Q15 option (c): change webhook path from `/<bot_token>` to fixed `/telegram/webhook` + `X-Telegram-Bot-Api-Secret-Token` header validation. Requires small code edit in `telegram_bot/main.py` + one `setWebhook` call at cutover. |
| 6 | `/etc/secrets/` file paths | Keep the file-path loader code in `supabase_kg/client.py` and `api_key_switching/key_pool.py` for local-dev backward compatibility. Don't populate the paths on the Droplet. Env-var fallbacks do the real work in prod. |
| 7 | Initial secrets delivery | GitHub Actions Environment secrets under `production` environment with manual approval protection rule. Deploy workflow writes `.env` on Droplet each deploy. |
| 8 | `GEMINI_API_KEYS` canonical store | GitHub Environment secret (comma-separated list of up to 10 keys). Windows `api_env` file for local dev only. |
| 9 | CI test gate | `pytest` (mocked) required on every `pull_request` and every `push` to `master`, gates deploy. `pytest --live` runs only on `workflow_dispatch` and weekly Sunday cron. |
| 10 | Let's Encrypt ACME email | `chintanoninternet@gmail.com` |
| 11 | `www` handling | Apex canonical: `https://zettelkasten.in` is real site, `https://www.zettelkasten.in` 301 redirects. |
| 12 | `SUPABASE_SERVICE_ROLE_KEY` on Droplet | **Never.** Only `SUPABASE_ANON_KEY` on Droplet. Service-role operations (migration script) run from Windows-local only. |
| 13 | IPv6 | Enabled. Droplet gets free `/64`, Caddy binds both IPv4+IPv6, Cloudflare DNS has A+AAAA records. |
| 14 | Dev compose files | Both. `ops/docker-compose.dev.yml` for hot-reload dev, `ops/docker-compose.prod-local.yml` for strict prod parity. |
| 15 | Bot token log mitigation | Option (c) — code refactor in `telegram_bot/main.py` to use fixed webhook path `/telegram/webhook` + header auth. |
| 16 | `pytest --live` in CI | Option (a) — only on manual dispatch and weekly cron, not on every push. Quota-preserving. |
| 17 | `docker-compose.dev.yml` mode | Option (c) — two files: dev mode and strict prod parity. |
| 18 | Source repo visibility | Private (`chintanmehta21/Zettelkasten_KG`). GHCR image also private. Droplet authenticates via fine-grained `GHCR_READ_PAT` with `read:packages` scope, annual rotation. |
| 19 | PR-level CI | Yes. `pytest` runs on `pull_request` events in addition to `push` to `master`. |

### Remaining implementation-detail defaults (not questions, just documented)

- **Droplet host directory:** `/opt/zettelkasten/`
- **SSH password auth:** disabled after bootstrap
- **Root SSH login:** disabled after bootstrap
- **Caddy log format:** JSON
- **Log rotation:** 10 MB × 3 files per container
- **Unattended upgrades:** security channel only, no auto-reboot
- **Swap file:** 1 GiB at `/swapfile`, `swappiness=10`
- **Container `mem_limit`:** 768 MB (app), 128 MB (Caddy)
- **Concurrency on deploys:** `cancel-in-progress: true`
- **Image tag scheme:** `ghcr.io/chintanmehta21/zettelkasten-kg-website:<git-sha>` + `:latest`; Droplet pulls by SHA
- **Render service retention post-cutover:** paused for 7 days, then deleted
- **DNS TTL pre-cutover:** not needed (new hostname); post-cutover TTL raised from 60s to 3600s once stable
- **Bootstrap execution:** manual one-shot SSH as root

---

## 17. Acceptance checklist for this design

Before moving to `writing-plans`:

- [x] All 15 hard constraints in §2 are directly addressed in §3–§12.
- [x] §2.1 locks the 19 follow-up decisions made during spec review.
- [x] Premium AMD $7 BLR1 tier choice explicitly justified (§3.1).
- [x] Docker 1-Click marketplace image used (§3.2).
- [x] GHCR **private** image + `GHCR_READ_PAT` annual rotation spec'd (§3.3, §12.2, §12.3).
- [x] Caddy apex canonical + www 301, IPv6, HTTP/3, HSTS, CAA, DNSSEC (§3.4, §10.1, §10.3).
- [x] GoDaddy registrar + Cloudflare DNS delegation for performance parity with Cloudflare Registrar (§10.1 day -3).
- [x] No backups in phase 1 (§13, §4 out of scope).
- [x] Single-node 99.9% uptime math shown (§9.5).
- [x] Zero-downtime deploy mechanism fully specified (§5.2, §12.4).
- [x] Container-level reliability specified (§9.3).
- [x] Host-level reliability specified (§9.1–§9.2).
- [x] Zero-downtime cutover via DNS record add (new hostname) + atomic `setWebhook` on new `/telegram/webhook` path (§10.2).
- [x] Per-feature Docker optimization findings folded in (§7.4).
- [x] Website-primary / Telegram-secondary framing is consistent throughout (§1, §3.7, §10).
- [x] BetterStack (user-managed) specified (§9.4, §11.3).
- [x] Lazy-imports refactor targets named by file + line (§8.2).
- [x] Supabase Free tier preserved with no changes (§3.6).
- [x] `SUPABASE_SERVICE_ROLE_KEY` NEVER on Droplet (§12.2, §16 Q12).
- [x] Telegram webhook path refactored to `/telegram/webhook` with header auth (§6.5, §16 Q15).
- [x] Both dev compose files spec'd (§6.4, §16 Q17).
- [x] CI pytest gate on PR + push, `--live` on manual/cron only (§12.1, §16 Q9 + Q16).
- [x] All 19 decisions in §16 Decisions Log resolved; no open questions remaining.

---

**End of design specification.**
