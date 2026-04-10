# Zettelkasten Capture Bot

A Telegram bot and web app that captures URLs from five content sources (Reddit, YouTube, GitHub, newsletters, and generic web articles) and writes AI-summarized Obsidian notes to your knowledge graph. Send a URL via Telegram or the web UI; get a structured Markdown note.

---

## Features

- **Auto-detect source type** - paste any URL and the bot picks the right extractor automatically
- **Five extractors**: Reddit threads (with top comments), YouTube videos (transcript + metadata), GitHub repos/issues/PRs, newsletter articles (Substack, Beehiiv, Buttondown, Mailchimp), and generic web pages
- **AI summarization** - Google Gemini produces a title, summary, and multi-dimensional tags for every capture
- **More reliable Gemini usage** - supports a comma-separated API key pool (`GEMINI_API_KEYS`) with key rotation plus a model fallback chain (graceful degradation to raw content when needed)
- **Web UI** - FastAPI-powered frontend with a URL summarizer and an interactive 3D knowledge graph (desktop + mobile)
- **Knowledge graph analytics** - enriches nodes with metrics (PageRank, communities, centrality) for better exploration
- **Graph search and Q&A (Supabase-backed)** - hybrid search and natural-language querying when Supabase is configured
- **Accounts (optional)** - Supabase Auth-backed user profiles (including avatar), plus a personal home page and zettels view
- **Cloud note storage (optional)** - push notes to a GitHub repo via the Contents API (useful when you do not want to rely on local disk)
- **Duplicate detection** - re-capture the same URL only when you explicitly use `/force`
- **SSRF protection** - URL validation blocks private/reserved IPs; tracking params are stripped for dedup consistency
- **Two run modes** - long-polling for development, webhook for production (bot + web UI share a single port)
- **Zero-downtime deploys** - production is designed around a blue/green Docker Compose stack with TLS termination, health checks, and rollback

---

## Quick Start

```bash
# 1. Clone
git clone https://github.com/chintanmehta21/Zettelkasten_KG.git
cd Zettelkasten_KG

# 2. Create a virtual environment
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

# 3. Install dependencies
pip install -r ops/requirements.txt
pip install -r ops/requirements-dev.txt

# 4. Configure
cp ops/.env.example .env
# Open .env and fill in TELEGRAM_BOT_TOKEN, ALLOWED_CHAT_ID, and GEMINI_API_KEYS (preferred) or GEMINI_API_KEY

# 5. Run (polling / development mode)
python run.py
```

The bot starts polling Telegram. Send it any URL to test.

---

## Configuration

Copy `ops/.env.example` to `.env` and fill in your credentials. Settings are loaded from env vars > `.env` > `ops/config.yaml`. See `ops/.env.example` for the canonical list.

---

## Bot Commands

| Command | Description |
|---|---|
| `/start` | Show the welcome message and command list |
| `/reddit <url>` | Capture a Reddit post or thread |
| `/yt <url>` | Capture a YouTube video |
| `/newsletter <url>` | Capture a newsletter article |
| `/github <url>` | Capture a GitHub repository, issue, or PR |
| `/force <url>` | Re-capture a URL even if already captured (skips deduplication) |
| *(bare URL)* | Paste any URL without a command - source type is auto-detected |

---

## Web UI

The FastAPI web frontend is served alongside the bot in webhook mode, with mobile routes under `/m/`:

| Page | URL | Description |
|---|---|---|
| **Summarizer** | `/` | Paste any URL, get an AI summary with tags |
| **Knowledge Graph** | `/knowledge-graph` | Interactive 3D graph of all summarized nodes |
| **Home (optional)** | `/home` | Signed-in home page (Supabase Auth) |
| **Zettels (optional)** | `/home/zettels` | Your captured notes view |
| **Nexus (optional)** | `/home/nexus` | Provider connections and bulk imports (experimental, Supabase required) |

### API Endpoints

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/summarize` | Summarize a URL (rate-limited: 10 req/min per IP) |
| `GET` | `/api/graph` | Return the current knowledge graph as JSON |
| `GET` | `/api/health` | Health check |
| `GET` | `/api/auth/config` | Public Supabase config for client-side auth init |
| `GET` | `/api/me` | Current user profile (auth required) |
| `POST` | `/api/graph/search` | Hybrid search (Supabase required) |
| `POST` | `/api/graph/query` | Natural-language Q&A over your graph (Supabase required) |

---

## Deployment

This repo includes several ways to run it locally, plus a production-oriented DigitalOcean droplet setup.

### Local Compose (recommended)

Dev mode (fast iteration):

```bash
docker compose -f ops/docker-compose.dev.yml up --build
```

Production-parity rehearsal (Caddy + blue/green + local TLS):

```bash
docker build -f ops/Dockerfile -t zettelkasten-kg-website:local .
docker compose -f ops/docker-compose.prod-local.yml up
```

### Docker (single container)

Build the production image:

```bash
docker build -f ops/Dockerfile -t zettelkasten-kg-website .
```

Polling (Telegram bot only):

```bash
docker run --env-file .env zettelkasten-kg-website
```

Webhook mode (web UI + API on port 10000):

```bash
docker run -p 10000:10000 --env-file .env ^
  -e WEBHOOK_MODE=true ^
  -e WEBHOOK_URL=http://localhost:10000 ^
  -e WEBHOOK_PORT=10000 ^
  zettelkasten-kg-website
```

### Production: DigitalOcean Droplet (blue/green)

Production deploys are automated from GitHub Actions. On pushes to `master`, `.github/workflows/deploy-droplet.yml` runs the mocked pytest suite, builds `ops/Dockerfile`, pushes `ghcr.io/chintanmehta21/zettelkasten-kg-website:<git-sha>`, then SSHes into the droplet and runs the blue/green deploy script.

### Note Storage Modes

| Mode | When | Notes survive redeploys? |
|---|---|---|
| **Local** | Default - writes to `KG_DIRECTORY` | Depends on host |
| **Cloud** | `GITHUB_TOKEN` + `GITHUB_REPO` set | Yes - pushed to GitHub via Contents API |

For cloud mode, clone the target repo into your Obsidian vault directory for automatic sync.

---

## Running Tests

```bash
# All tests
pytest

# Unit tests only (no network)
pytest tests/ --ignore=tests/integration_tests

# A specific test module
pytest tests/test_extractors.py -v

# With coverage
pytest --cov=telegram_bot --cov-report=term-missing

# Live integration tests (requires real API creds in .env)
pytest --live
```

---

## Adding a New Source

The extractor system uses auto-discovery - any `SourceExtractor` subclass in `telegram_bot/sources/` is registered automatically.

1. Add enum value to `SourceType` in `telegram_bot/models/capture.py`
2. Create extractor module in `telegram_bot/sources/` (subclass `SourceExtractor`, implement `async extract()`)
3. Add URL pattern to `telegram_bot/sources/registry.py`
4. Add bot command handler in `telegram_bot/bot/handlers.py` and wire in `telegram_bot/main.py`

---

## Project Structure

```
|-- run.py                     # Entry point
|-- pyproject.toml             # Project metadata + pytest config
|-- telegram_bot/              # Core bot application
|   |-- main.py                # App wiring: handlers, polling/webhook startup
|   |-- bot/                   # Telegram command handlers + chat-ID guard
|   |-- config/                # Pydantic settings (env + yaml)
|   |-- models/                # Shared data models (SourceType, ExtractedContent, etc.)
|   |-- pipeline/              # Orchestrator, Gemini summarizer, writers, dedup
|   |-- sources/               # Auto-discovered source extractors
|   `-- utils/                 # URL validation, SSRF protection
|-- website/                   # FastAPI web frontend
|   |-- api/                   # REST API routes (/api/*)
|   |-- core/                  # Web pipeline, graph store, Supabase KG integration
|   |-- features/              # Knowledge graph, auth, home, zettels, etc.
|   |-- mobile/                # Mobile UI (/m/*)
|   `-- static/                # Summarizer page assets
|-- ops/                       # Deployment + operations
|   |-- Dockerfile             # Multi-stage Docker build
|   |-- caddy/                 # Caddy TLS / reverse-proxy config
|   |-- deploy/                # Blue/green deploy, healthcheck, rollback scripts
|   |-- host/                  # Droplet bootstrap, firewall, sysctl, logrotate
|   |-- systemd/               # Service units
|   `-- requirements*.txt      # Runtime vs dev/test dependencies
|-- tests/                     # Unit + integration tests
|   `-- integration_tests/     # Live API tests (--live flag)
|-- supabase/                  # Supabase schema definitions
`-- docs/                      # Additional documentation
```

---

## Vault Sync

**GitHub (cloud mode):** Set `GITHUB_TOKEN` and `GITHUB_REPO` to push notes to a GitHub repository. Clone that repo into your Obsidian vault.

**SyncThing (self-hosted):** For syncing `KG_DIRECTORY` without a cloud service, see **[docs/SYNCTHING-ALTERNATIVES.md](docs/SYNCTHING-ALTERNATIVES.md)**.

