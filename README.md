# Zettelkasten Capture Bot

A Telegram bot and web app that captures URLs from five content sources — Reddit, YouTube, GitHub, newsletters, and generic web articles — and writes AI-summarised Obsidian notes to your knowledge graph. Send a URL via Telegram or the web UI; get a structured Markdown note.

---

## Features

- **Auto-detect source type** — paste any URL and the bot picks the right extractor automatically
- **Five extractors**: Reddit threads (with top comments), YouTube videos (transcript + metadata), GitHub repos/issues/PRs, newsletter articles (Substack, Beehiiv, Buttondown, Mailchimp), and generic web pages
- **AI summarisation** — Google Gemini produces a title, summary, and multi-dimensional tags for every capture
- **Model fallback chain** — cascades through `gemini-2.5-flash` → `gemini-2.0-flash` → `gemini-2.5-flash-lite` on 429 rate limits, with 60-second per-model cooldown. If all models fail, returns raw content for manual review (graceful degradation)
- **Web UI** — FastAPI-powered frontend with a URL summarizer and an interactive 3D knowledge graph visualizer (Three.js / 3D Force Graph)
- **Knowledge graph** — summarized URLs are added as nodes with tag-based auto-linking to existing nodes; persisted to `graph.json`
- **Cloud note storage** — optionally push notes to a GitHub repo via the Contents API (for deployments without persistent disk, e.g. Render free tier)
- **Duplicate detection** — re-capture the same URL only when you explicitly use `/force`
- **SSRF protection** — URL validation blocks private/reserved IPs; tracking params are stripped for dedup consistency
- **Extensible** — drop a new file in `zettelkasten_bot/sources/` and it is picked up automatically
- **Two run modes** — long-polling for development, webhook for production (bot + web UI share a single port)
- **Docker-ready** — multi-stage build with pre-compiled `.pyc` for fast cold starts
- **Render.com deploy** — `render.yaml` Blueprint for one-click deploy with GitHub Actions keep-alive to prevent free-tier cold starts

---

## Quick Start

```bash
# 1. Clone
git clone https://github.com/your-org/zettelkasten-bot.git
cd zettelkasten-bot

# 2. Create a virtual environment
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt
# or, for an editable install:
pip install -e .

# 4. Configure
cp .env.example .env
# Open .env and fill in TELEGRAM_BOT_TOKEN, ALLOWED_CHAT_ID, and GEMINI_API_KEY

# 5. Run (polling / development mode)
python run.py
```

The bot starts polling Telegram. Send it any URL to test.

---

## Configuration

Settings are loaded from three places in priority order:

1. Environment variables (highest priority)
2. `.env` file in the project root
3. `config/config.yaml` (non-secret defaults)

> **Secrets** (`TELEGRAM_BOT_TOKEN`, API keys) must be set via environment variables or `.env` — never commit them to `config.yaml`.

### Environment Variable Reference

| Variable | Required | Default | Description |
|---|---|---|---|
| `TELEGRAM_BOT_TOKEN` | ✅ Yes | — | Bot token from @BotFather |
| `ALLOWED_CHAT_ID` | ✅ Yes | — | Numeric chat ID allowed to use the bot |
| `GEMINI_API_KEY` | ✅ Yes | — | Google Gemini API key for summarisation |
| `REDDIT_CLIENT_ID` | For Reddit | — | Reddit OAuth app client ID |
| `REDDIT_CLIENT_SECRET` | For Reddit | — | Reddit OAuth app client secret |
| `REDDIT_USER_AGENT` | No | `ZettelkastenBot/1.0` | Reddit API user-agent string |
| `REDDIT_COMMENT_DEPTH` | No | `10` | Number of top-level comments to fetch per thread |
| `WEBHOOK_MODE` | No | `false` | Set `true` to use webhooks instead of polling |
| `WEBHOOK_URL` | If webhook | — | Public URL for the webhook endpoint (e.g. `https://example.com/TOKEN`) |
| `WEBHOOK_PORT` | No | `8443` | Port the bot listens on for webhook requests |
| `WEBHOOK_SECRET` | No | — | Secret token Telegram includes in every webhook request |
| `KG_DIRECTORY` | No | `./kg_output` | Directory where Obsidian notes are written |
| `DATA_DIR` | No | `./data` | Internal data directory (duplicate store, caches) |
| `MODEL_NAME` | No | `gemini-2.5-flash` | Gemini model to use for summarisation |
| `LOG_LEVEL` | No | `INFO` | Logging verbosity: `DEBUG`, `INFO`, `WARNING`, `ERROR` |
| `GITHUB_TOKEN` | For cloud mode | — | GitHub PAT with `repo` scope — enables pushing notes to a GitHub repo |
| `GITHUB_REPO` | For cloud mode | — | Target repo in `owner/repo` format |
| `GITHUB_BRANCH` | No | `main` | Branch to push notes to |

---

## Commands Reference

| Command | Description |
|---|---|
| `/start` | Show the welcome message and command list |
| `/reddit <url>` | Capture a Reddit post or thread |
| `/yt <url>` | Capture a YouTube video |
| `/newsletter <url>` | Capture a newsletter article |
| `/github <url>` | Capture a GitHub repository, issue, or PR |
| `/force <url>` | Re-capture a URL even if already captured (skips deduplication) |
| *(bare URL)* | Paste any URL without a command — source type is auto-detected |

**Auto-detection rules** (checked in order):
1. `reddit.com` / `redd.it` → Reddit
2. `youtube.com` / `youtu.be` → YouTube
3. `github.com` → GitHub
4. Matches `NEWSLETTER_DOMAINS` list → Newsletter
5. Anything else → Generic

---

## Web UI

The project includes a FastAPI web frontend served alongside the bot in webhook mode. Two pages:

| Page | URL | Description |
|---|---|---|
| **Summarizer** | `/` | Paste any URL, get an AI summary with tags — no Telegram required |
| **Knowledge Graph** | `/knowledge-graph` | Interactive 3D graph of all summarized nodes (Three.js / 3D Force Graph), with search, filtering by source type, and click-to-open source links |

### API Endpoints

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/summarize` | Summarize a URL (rate-limited: 10 req/min per IP) |
| `GET` | `/api/graph` | Return the current knowledge graph as JSON |
| `GET` | `/api/health` | Health check (used by Render) |

Summaries submitted via the web UI are automatically added as nodes to the knowledge graph with tag-based auto-linking to existing nodes.

---

## Deployment

### Self-hosted (VPS)

See **[deploy/DEPLOY.md](deploy/DEPLOY.md)** for the full step-by-step guide covering:

- systemd service setup
- nginx TLS termination with certbot
- Webhook registration with Telegram
- Verification commands and troubleshooting table

Switch to webhook mode by setting `WEBHOOK_MODE=true` and `WEBHOOK_URL` in `.env`.

### Render.com (Free Tier)

One-click deploy using the included `render.yaml` Blueprint:

1. Push to GitHub: `git push origin master`
2. On Render: **New** → **Blueprint** → select repo → it reads `render.yaml`
3. Set env vars in Render dashboard: `TELEGRAM_BOT_TOKEN`, `ALLOWED_CHAT_ID`, `GEMINI_API_KEY`, `WEBHOOK_URL`
4. Optionally set `GITHUB_TOKEN` and `GITHUB_REPO` for persistent note storage via GitHub

A GitHub Actions workflow (`.github/workflows/keep-alive.yml`) pings the Render URL every 14 minutes to prevent cold starts. Requires the `RENDER_URL` secret in your GitHub repo settings.

#### Note Storage Modes

| Mode | When | Notes survive redeploys? |
|---|---|---|
| **Local** | Default — writes to `KG_DIRECTORY` | No (ephemeral on Render) |
| **Cloud** | `GITHUB_TOKEN` + `GITHUB_REPO` set | Yes — pushed to GitHub via Contents API |

For cloud mode, clone the target repo into your Obsidian vault directory for automatic sync.

### Docker

Multi-stage build for minimal image size:

```bash
docker build -t zettelkasten-bot .
docker run -p 10000:10000 --env-file .env zettelkasten-bot
```

Base image: `python:3.12-slim`. Pre-compiles `.pyc` files for ~1-2s faster cold starts.

---

## Adding a New Source

The extractor system uses auto-discovery: any `SourceExtractor` subclass placed in the `zettelkasten_bot/sources/` package is registered automatically on startup.

### Step-by-step guide

**1. Add a new value to the `SourceType` enum** (`zettelkasten_bot/models/capture.py`):

```python
class SourceType(str, Enum):
    REDDIT      = "reddit"
    YOUTUBE     = "youtube"
    NEWSLETTER  = "newsletter"
    GITHUB      = "github"
    GENERIC     = "generic"
    HACKERNEWS  = "hackernews"  # ← new
```

**2. Create the extractor module** (`zettelkasten_bot/sources/hackernews.py`):

```python
from zettelkasten_bot.models.capture import ExtractedContent, SourceType
from zettelkasten_bot.sources.base import SourceExtractor

class HackerNewsExtractor(SourceExtractor):
    source_type = SourceType.HACKERNEWS   # must match the enum value

    async def extract(self, url: str) -> ExtractedContent:
        # fetch and parse content …
        return ExtractedContent(
            url=url,
            source_type=SourceType.HACKERNEWS,
            title="Post title",
            body="Post content and top comments …",
            metadata={"score": 123},
        )
```

The `SourceExtractor` ABC requires only one method:

```python
class SourceExtractor(ABC):
    source_type: SourceType          # class-level attribute

    @abstractmethod
    async def extract(self, url: str) -> ExtractedContent:
        ...
```

**3. Register the URL pattern** (`zettelkasten_bot/sources/registry.py`) — add a detection block before the Generic fallback:

```python
if "news.ycombinator.com" in host:
    return SourceType.HACKERNEWS
```

**4. Add a bot command** (`zettelkasten_bot/bot/handlers.py`) — follow the pattern of `handle_reddit` / `handle_github` to create `handle_hackernews` and wire it in `zettelkasten_bot/main.py`.

**5. Write tests** — add a test module `tests/test_hackernews_extractor.py` following the pattern in `tests/test_extractors.py`.

> **That's it.** The auto-discovery loop in `zettelkasten_bot/sources/__init__.py` finds any `SourceExtractor` subclass with a `source_type` attribute and adds it to the registry — no manual wiring needed.

---

## Running Tests

```bash
# All tests (unit + integration)
pytest

# Unit tests only (no network)
pytest tests/ --ignore=tests/integration_tests

# A specific test module
pytest tests/test_extractors.py -v

# With coverage
pytest --cov=zettelkasten_bot --cov-report=term-missing
```

Integration tests in `tests/integration_tests/` make real network calls and require valid API credentials in `.env`.

---

## Project Structure

```
zettelkasten-bot/
├── run.py                          # Entry point: starts the bot
├── Dockerfile                      # Multi-stage Docker build
├── render.yaml                     # Render.com Blueprint (one-click deploy)
├── requirements.txt                # Dev dependencies (includes pytest, etc.)
├── requirements-prod.txt           # Production-only dependencies
├── .env.example                    # ← copy to .env and fill in secrets
├── .github/
│   └── workflows/
│       └── keep-alive.yml          # Pings Render every 14 min to prevent cold starts
├── config/
│   └── config.yaml                 # Non-secret defaults
├── deploy/
│   ├── DEPLOY.md                   # VPS deployment guide
│   ├── zettelkasten-bot.service    # systemd unit file
│   └── nginx.conf                  # nginx reverse proxy config
├── docs/
│   ├── SYNCTHING-ALTERNATIVES.md   # Vault sync options
│   └── VPS-RECOMMENDATIONS.md      # Hosting recommendations
├── website/                        # FastAPI web frontend
│   ├── app.py                      # App factory (serves UI + API on one port)
│   ├── api/
│   │   └── routes.py               # REST API: /api/summarize, /api/graph, /api/health
│   ├── core/
│   │   ├── pipeline.py             # Stateless web pipeline wrapper
│   │   └── graph_store.py          # Thread-safe in-memory graph with tag-based linking
│   ├── static/                     # Summarizer page (HTML/CSS/JS)
│   └── knowledge_graph/            # 3D knowledge graph visualizer
│       ├── index.html
│       ├── css/style.css
│       ├── js/app.js               # Three.js / 3D Force Graph
│       └── content/graph.json      # Persisted graph data
├── zettelkasten_bot/
│   ├── main.py                     # App wiring: registers handlers, starts bot
│   ├── bot/
│   │   ├── guards.py               # Chat-ID allow-list middleware
│   │   └── handlers.py             # Telegram command + message handlers
│   ├── config/
│   │   └── settings.py             # Pydantic settings (env + yaml)
│   ├── models/
│   │   └── capture.py              # Shared data models (SourceType, ExtractedContent, …)
│   ├── pipeline/
│   │   ├── orchestrator.py         # Top-level pipeline: extract → summarise → write
│   │   ├── summarizer.py           # Gemini summarisation + model fallback chain
│   │   ├── writer.py               # Local Obsidian note writer
│   │   ├── github_writer.py        # Cloud note writer (GitHub Contents API)
│   │   └── duplicate.py            # Seen-URL deduplication
│   ├── sources/
│   │   ├── base.py                 # SourceExtractor ABC
│   │   ├── __init__.py             # Auto-discovery registry
│   │   ├── registry.py             # URL → SourceType detection
│   │   ├── reddit.py               # Reddit extractor (PRAW)
│   │   ├── youtube.py              # YouTube extractor (transcript + yt-dlp)
│   │   ├── newsletter.py           # Newsletter extractor (trafilatura)
│   │   ├── github.py               # GitHub extractor (REST API)
│   │   └── generic.py              # Generic web extractor (trafilatura)
│   └── utils/
│       └── url_utils.py            # URL validation + SSRF protection
└── tests/
    ├── conftest.py
    ├── test_extractors.py
    ├── test_handlers.py
    ├── test_orchestrator.py
    ├── test_source_registry.py
    ├── test_duplicate.py
    ├── test_gemini.py
    ├── test_model_fallback.py
    ├── test_writer.py
    ├── test_github_writer.py
    ├── test_settings_github.py
    ├── test_website.py
    ├── test_youtube_urls.py
    ├── test_main.py
    ├── test_url_utils.py
    └── integration_tests/
        └── test_live_pipeline.py
```

---

## Vault Sync

**Option A — GitHub (cloud mode):** Set `GITHUB_TOKEN` and `GITHUB_REPO` to push notes to a GitHub repository. Clone that repo into your Obsidian vault for automatic sync across devices.

**Option B — SyncThing (self-hosted):** For syncing `KG_DIRECTORY` without a cloud service, see **[docs/SYNCTHING-ALTERNATIVES.md](docs/SYNCTHING-ALTERNATIVES.md)**. Recommended: three-node SyncThing network (VPS → desktop → mobile).

---

## VPS Recommendations

This bot runs comfortably on a free-tier VPS. For hosting options — including the Oracle Cloud Always Free tier (4 vCPUs, 24 GB RAM, permanently free) — see **[docs/VPS-RECOMMENDATIONS.md](docs/VPS-RECOMMENDATIONS.md)**.
