# Zettelkasten Capture Bot

A Telegram bot and web app that captures URLs from five content sources — Reddit, YouTube, GitHub, newsletters, and generic web articles — and writes AI-summarised Obsidian notes to your knowledge graph. Send a URL via Telegram or the web UI; get a structured Markdown note.

---

## Features

- **Auto-detect source type** — paste any URL and the bot picks the right extractor automatically
- **Five extractors**: Reddit threads (with top comments), YouTube videos (transcript + metadata), GitHub repos/issues/PRs, newsletter articles (Substack, Beehiiv, Buttondown, Mailchimp), and generic web pages
- **AI summarisation** — Google Gemini produces a title, summary, and multi-dimensional tags for every capture
- **Model fallback chain** — cascades through `gemini-2.5-flash` → `gemini-2.0-flash` → `gemini-2.5-flash-lite` on 429 rate limits, with 60-second per-model cooldown. If all models fail, returns raw content (graceful degradation)
- **Web UI** — FastAPI-powered frontend with a URL summarizer and an interactive 3D knowledge graph visualizer (Three.js / 3D Force Graph)
- **Knowledge graph** — summarized URLs are added as nodes with tag-based auto-linking to existing nodes
- **Cloud note storage** — optionally push notes to a GitHub repo via the Contents API (for deployments without persistent disk)
- **Duplicate detection** — re-capture the same URL only when you explicitly use `/force`
- **SSRF protection** — URL validation blocks private/reserved IPs; tracking params are stripped for dedup consistency
- **Extensible** — drop a new file in `telegram_bot/sources/` and it is picked up automatically
- **Two run modes** — long-polling for development, webhook for production (bot + web UI share a single port)
- **Docker-ready** — multi-stage build with pre-compiled `.pyc` for fast cold starts

---

## Quick Start

```bash
# 1. Clone
git clone https://github.com/chintanmehta21/zettelkasten-telegram-bot.git
cd zettelkasten-telegram-bot

# 2. Create a virtual environment
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

# 3. Install dependencies
pip install -r ops/requirements.txt

# 4. Configure
cp ops/.env.example .env
# Open .env and fill in TELEGRAM_BOT_TOKEN, ALLOWED_CHAT_ID, and GEMINI_API_KEY

# 5. Run (polling / development mode)
python run.py
```

The bot starts polling Telegram. Send it any URL to test.

---

## Configuration

Copy `ops/.env.example` to `.env` and fill in your credentials. Settings are loaded from env vars > `.env` > `ops/config.yaml`. See `ops/.env.example` for the full list.

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
| *(bare URL)* | Paste any URL without a command — source type is auto-detected |

---

## Web UI

The FastAPI web frontend is served alongside the bot in webhook mode:

| Page | URL | Description |
|---|---|---|
| **Summarizer** | `/` | Paste any URL, get an AI summary with tags |
| **Knowledge Graph** | `/knowledge-graph` | Interactive 3D graph of all summarized nodes with search and filtering |

### API Endpoints

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/summarize` | Summarize a URL (rate-limited: 10 req/min per IP) |
| `GET` | `/api/graph` | Return the current knowledge graph as JSON |
| `GET` | `/api/health` | Health check |

---

## Deployment

### Self-hosted (VPS)

See **[ops/deploy/DEPLOY.md](ops/deploy/DEPLOY.md)** for the full guide covering systemd, nginx TLS termination, and webhook registration.

### Docker

```bash
docker build -f ops/Dockerfile -t zettelkasten-bot .
docker run -p 10000:10000 --env-file .env zettelkasten-bot
```

Base image: `python:3.12-slim`. Multi-stage build with pre-compiled `.pyc` for fast cold starts.

### Note Storage Modes

| Mode | When | Notes survive redeploys? |
|---|---|---|
| **Local** | Default — writes to `KG_DIRECTORY` | Depends on host |
| **Cloud** | `GITHUB_TOKEN` + `GITHUB_REPO` set | Yes — pushed to GitHub via Contents API |

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

The extractor system uses auto-discovery — any `SourceExtractor` subclass in `telegram_bot/sources/` is registered automatically.

1. Add enum value to `SourceType` in `telegram_bot/models/capture.py`
2. Create extractor module in `telegram_bot/sources/` (subclass `SourceExtractor`, implement `async extract()`)
3. Add URL pattern to `telegram_bot/sources/registry.py`
4. Add bot command handler in `telegram_bot/bot/handlers.py` and wire in `telegram_bot/main.py`

---

## Project Structure

```
├── run.py                     # Entry point
├── pyproject.toml             # Project metadata + pytest config
├── telegram_bot/              # Core bot application
│   ├── main.py                # App wiring: handlers, polling/webhook startup
│   ├── bot/                   # Telegram command handlers + chat-ID guard
│   ├── config/                # Pydantic settings (env + yaml)
│   ├── models/                # Shared data models (SourceType, ExtractedContent, etc.)
│   ├── pipeline/              # Orchestrator, Gemini summarizer, writers, dedup
│   ├── sources/               # Auto-discovered source extractors (Reddit, YouTube, etc.)
│   └── utils/                 # URL validation, SSRF protection
├── website/                   # FastAPI web frontend
│   ├── api/                   # REST API routes (/api/summarize, /api/graph)
│   ├── core/                  # Web pipeline, graph store, Supabase KG integration
│   ├── features/              # Deployed features (knowledge graph, user auth)
│   └── static/                # Summarizer page (HTML/CSS/JS)
├── ops/                       # Operational configs
│   ├── Dockerfile             # Multi-stage Docker build
│   ├── deploy/                # VPS deployment (systemd, nginx)
│   ├── scripts/               # Migration and utility scripts
│   └── requirements.txt       # All dependencies
├── tests/                     # Unit + integration tests
│   └── integration_tests/     # Live API tests (--live flag)
├── supabase/                  # Supabase schema definitions
└── docs/                      # Additional documentation
```

---

## Vault Sync

**GitHub (cloud mode):** Set `GITHUB_TOKEN` and `GITHUB_REPO` to push notes to a GitHub repository. Clone that repo into your Obsidian vault.

**SyncThing (self-hosted):** For syncing `KG_DIRECTORY` without a cloud service, see **[docs/SYNCTHING-ALTERNATIVES.md](docs/SYNCTHING-ALTERNATIVES.md)**.
