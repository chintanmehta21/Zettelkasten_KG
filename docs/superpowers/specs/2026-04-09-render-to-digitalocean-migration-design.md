# Render → DigitalOcean Migration Design Specification

**Date:** 2026-04-09
**Status:** Proposed and approved for implementation planning
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

### 3.3 Registry: GHCR (GitHub Container Registry)

All images are built by GitHub Actions on `master` push and pushed to `ghcr.io/chintanmehta21/zettelkasten-website:<sha>` plus a `ghcr.io/chintanmehta21/zettelkasten-website:latest` tag. The Droplet authenticates once using a long-lived read-only `GHCR_PAT` stored in root-only `/root/.docker/config.json`.

### 3.4 Reverse proxy: Caddy with blue-green upstreams

A single Caddy 2 container terminates TLS via Let's Encrypt (automatic renewal), serves the public origin (`zettel.chintanmehta.dev` or equivalent), and reverse-proxies to **exactly one of** two application containers:

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

### 9.4 BetterStack monitoring

- One HTTPS monitor hitting `https://<public-host>/api/health` every 30s from at least 3 regions.
- One heartbeat monitor the app pings every 60s from a background task (optional phase 1).
- Alert channels: email + Telegram message to `ALLOWED_CHAT_ID`.

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

### 10.1 Pre-cutover (day -1)

1. Drop DNS TTL on the website hostname (e.g., `zettel.chintanmehta.dev`) to **60s** at the DNS provider. Wait ≥ current TTL before touching anything else so the low TTL actually propagates.
2. Provision Droplet, run `bootstrap.sh`, pull image, bring up blue, bring up Caddy.
3. Use a temporary hostname (e.g., `zettel-new.chintanmehta.dev`) pointing at the Droplet IP, with a full production-valid cert, so Caddy has already completed its Let's Encrypt dance before cutover.
4. Smoke-test every route on the temp hostname:
   - `GET /` → 200, home HTML
   - `GET /api/health` → 200
   - `GET /api/graph` → 200, JSON
   - `POST /api/summarize` with a throwaway URL → 200
   - `GET /knowledge-graph` → 200
   - `GET /home` (authed and unauthed)
   - `GET /home/zettels` (authed)
   - `GET /home/nexus` (authed, if `NEXUS_ENABLED=true`)
   - `GET /about`, `GET /pricing`
   - `GET /auth/callback`
5. Confirm Supabase reads/writes work from the new host (check `/api/graph` returns the same node count as Render).
6. Confirm Gemini key pool loads from `GEMINI_API_KEYS` env var.

### 10.2 Cutover (day 0)

1. **T-0:** Flip the DNS A (or CNAME) record for the real hostname from Render's IP to the Droplet IP. Because TTL is 60s, propagation completes in roughly 60s.
2. **T-0:** Immediately call Telegram `setWebhook` with the new URL (`https://<real-host>/<bot-token>`). This swap is atomic on Telegram's side — the very next update goes to the Droplet. **This is the only bot downtime**, measured in milliseconds.
3. **T+0 to T+60s:** Both Render and Droplet are still running; user traffic gradually shifts as resolvers refresh. Any request that still lands on Render works normally (Render is still alive during this window).
4. **T+60s:** Most resolvers now point at the Droplet. Verify via `dig +short` from multiple vantage points.
5. **T+5 min:** Tail Caddy access logs on the Droplet to confirm real end-user traffic. Tail Render logs to confirm traffic has drained to near-zero.
6. **T+30 min:** Pause (but do not delete) the Render service. Keep it paused for 7 days as an emergency rollback target.
7. **T+7 days:** Delete the Render service.

### 10.3 Rollback path (if something breaks mid-cutover)

1. **If Droplet is broken before DNS flip:** Abort — do not flip DNS, do not call `setWebhook`. No user impact.
2. **If Droplet breaks after DNS flip, during propagation:** Flip DNS back to Render IP. Call `setWebhook` back to the old Render URL. Wait 60s. Both surfaces return to pre-cutover state.
3. **If a single feature on the Droplet breaks after cutover:** Flip Caddy upstream back to a known-good image via `rollback.sh` (it re-points `upstream.snippet` to the last-good tag and reloads Caddy). No DNS change required.
4. **If the Droplet itself dies (host-level):** DO console → reboot Droplet. systemd brings the stack back automatically. Budget: ≤ 2 min.

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

### 12.1 GitHub Actions workflow `deploy-droplet.yml`

Triggers: `push` to `master`, `workflow_dispatch`.

Jobs:

1. **`build-and-push`**
   - `actions/checkout@v4`
   - `docker/setup-buildx-action@v3`
   - `docker/login-action@v3` → GHCR with `GITHUB_TOKEN` (has `write:packages`)
   - `docker/build-push-action@v5`
     - context: repo root
     - file: `ops/Dockerfile`
     - platforms: `linux/amd64`
     - tags: `ghcr.io/chintanmehta21/zettelkasten-website:${{ github.sha }}`, `ghcr.io/chintanmehta21/zettelkasten-website:latest`
     - cache-from: `type=gha`
     - cache-to: `type=gha,mode=max`
     - push: true
     - provenance: false (keeps image smaller)
2. **`deploy`** (`needs: build-and-push`)
   - `appleboy/ssh-action@v1` to SSH into Droplet as `deploy` user.
   - Runs: `/opt/zettelkasten/deploy/deploy.sh ${{ github.sha }}`
   - On failure: automatically invokes `rollback.sh` via `if: failure()`.

### 12.2 Required GitHub secrets

- `DROPLET_HOST` — public IP or hostname of Droplet
- `DROPLET_SSH_USER` — `deploy`
- `DROPLET_SSH_KEY` — private key for `deploy` user
- `DROPLET_SSH_PORT` — `22` (or custom)
- `GHCR_PAT` — only if we ever need a non-`GITHUB_TOKEN` read path; normally unused

### 12.3 Droplet-side `deploy.sh` responsibilities

1. Accept new image sha as arg.
2. `docker login ghcr.io` using stored PAT (or rely on already-cached creds).
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

### 12.4 `rollback.sh` responsibilities

1. Detect which color should be live (last known good from `/opt/zettelkasten/ACTIVE_COLOR`).
2. Ensure live color is still up; if not, start it with the previous image.
3. Rewrite `upstream.snippet` back to live color.
4. Reload Caddy.
5. Tear down any half-started idle color.
6. Log rollback with reason.

---

## 13. Cost Summary

| Item | Provider | Monthly |
|---|---|---|
| Droplet `s-1vcpu-1gb` Premium AMD, BLR1 | DigitalOcean | **$7.00** |
| DNS | (existing provider, free) | $0 |
| Firewall (DO cloud FW optional, UFW is on-host) | DigitalOcean | $0 |
| Container registry | GHCR (free unlimited) | $0 |
| TLS certificates | Let's Encrypt via Caddy | $0 |
| External monitoring | BetterStack Free tier | $0 |
| Database + auth + storage | Supabase Free tier | $0 |
| Backups | None in phase 1 (per constraint #6) | $0 |
| **Total** | | **$7.00/mo** |

Current Render cost baseline is comparable, but the Droplet buys **persistent disk**, **zero-downtime deploys**, **no cold starts**, and **full control of the stack**.

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
| DNS propagation lag leaves some users on Render post-cutover | Expected | None — Render is still up during window | Pre-lower TTL to 60s day -1, keep Render paused 7 days |
| Droplet SSH key compromise | Low | Full host takeover | UFW, fail2ban, SSH key-only auth, no password, rotate on suspicion |

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

## 16. Open Questions (must be resolved before plan execution begins)

1. **Public hostname.** What is the final production hostname? Is DNS currently at Cloudflare, Namecheap, or another provider? The TTL-drop step needs the concrete provider.
2. **`deploy` SSH user bootstrap.** Who holds the private key for the first SSH login? Does the user want GitHub Actions to create the user via a one-shot cloud-init, or will they create it manually on first login?
3. **BetterStack account.** Does the user already have a BetterStack account, or does the plan need to include account creation as a step?
4. **Nexus in production?** Constraint #13 says website is primary. Is Nexus meant to be live on the new host from day 1, or should `NEXUS_ENABLED=false` be the initial value until it's ready for end users?
5. **Telegram bot public token exposure.** The current webhook path includes the raw bot token (`/<bot_token>`). Caddy will log this path unless we strip it. Add a Caddy rewrite/log filter to hash it? Phase-1 nice-to-have or blocker?
6. **Supabase env vars on the Droplet.** The existing `_bootstrap_env()` in `supabase_kg/client.py` reads from `/etc/secrets/api_env` and `/etc/secrets/nexus_env`. On the Droplet these become `/opt/zettelkasten/compose/.env` loaded by docker-compose. Do we still need the `/etc/secrets/` paths or can they be removed entirely? (Recommendation: keep the file-path code so local dev and Render remain buildable, just don't populate the path on Droplet.)

---

## 17. Acceptance checklist for this design

Before moving to `writing-plans`:

- [ ] All 15 hard constraints in §2 are directly addressed in §3–§12.
- [ ] Premium AMD $7 BLR1 tier choice explicitly justified (§3.1).
- [ ] Docker 1-Click marketplace image used (§3.2).
- [ ] GHCR chosen for registry (§3.3, §12).
- [ ] No backups step explicitly called out (§13, §6 out of scope).
- [ ] Single-node 99.9% uptime math shown (§9.5).
- [ ] Zero-downtime deploy mechanism fully specified (§5.2, §12.3).
- [ ] Container-level reliability specified (§9.3).
- [ ] Host-level reliability specified (§9.1–§9.2).
- [ ] Cutover via `setWebhook` + low-TTL DNS specified with rollback (§10).
- [ ] Per-feature Docker optimization findings folded in (§7.4).
- [ ] Website-primary / Telegram-secondary framing is consistent throughout (§1, §3.7, §10).
- [ ] BetterStack (not UptimeRobot) specified (§9.4, §11.3).
- [ ] Lazy-imports refactor targets named by file + line (§8.2).
- [ ] Supabase Free tier preserved with no changes (§3.6).

---

**End of design specification.**
