# Zettelkasten Capture Bot

A Telegram bot that captures URLs from five content sources — Reddit, YouTube, GitHub, newsletters, and generic web articles — and writes AI-summarised Obsidian notes to your local knowledge graph. Send a URL; get a structured Markdown note.

---

## Features

- **Auto-detect source type** — paste any URL and the bot picks the right extractor automatically
- **Five extractors**: Reddit threads (with top comments), YouTube videos (transcript + metadata), GitHub repos/issues/PRs, newsletter articles (Substack, Beehiiv, Buttondown, Mailchimp), and generic web pages
- **AI summarisation** — Google Gemini produces a title, summary, and tags for every capture
- **Duplicate detection** — re-capture the same URL only when you explicitly use `/force`
- **Extensible** — drop a new file in `zettelkasten_bot/sources/` and it is picked up automatically
- **Two run modes** — long-polling for development, webhook for production

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

## Production Deployment

See **[deploy/DEPLOY.md](deploy/DEPLOY.md)** for the full step-by-step guide covering:

- systemd service setup
- nginx TLS termination with certbot
- Webhook registration with Telegram
- Verification commands and troubleshooting table

Switch to webhook mode by setting `WEBHOOK_MODE=true` and `WEBHOOK_URL` in `.env`.

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
├── requirements.txt
├── .env.example                    # ← copy to .env and fill in secrets
├── config/
│   └── config.yaml                 # Non-secret defaults
├── deploy/
│   ├── DEPLOY.md                   # Production deployment guide
│   ├── zettelkasten-bot.service    # systemd unit file
│   └── nginx.conf                  # nginx reverse proxy config
├── docs/
│   ├── SYNCTHING-ALTERNATIVES.md   # Vault sync options
│   └── VPS-RECOMMENDATIONS.md      # Hosting recommendations
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
│   │   ├── summarizer.py           # Gemini summarisation
│   │   ├── writer.py               # Obsidian note writer
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
│       └── url_utils.py            # URL validation helpers
└── tests/
    ├── conftest.py
    ├── test_extractors.py
    ├── test_handlers.py
    ├── test_orchestrator.py
    ├── test_source_registry.py
    ├── test_duplicate.py
    ├── test_gemini.py
    ├── test_writer.py
    ├── test_url_utils.py
    └── integration_tests/
        └── test_live_pipeline.py
```

---

## SyncThing Setup

For syncing your Obsidian vault (`KG_DIRECTORY`) across devices without a cloud service, see **[docs/SYNCTHING-ALTERNATIVES.md](docs/SYNCTHING-ALTERNATIVES.md)**.

The recommended setup is a three-node SyncThing network: VPS → desktop → mobile. Notes written by the bot on the VPS propagate to all devices automatically.

---

## VPS Recommendations

This bot runs comfortably on a free-tier VPS. For hosting options — including the Oracle Cloud Always Free tier (4 vCPUs, 24 GB RAM, permanently free) — see **[docs/VPS-RECOMMENDATIONS.md](docs/VPS-RECOMMENDATIONS.md)**.
