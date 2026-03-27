# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

Zettelkasten Capture Bot — a Telegram bot that captures URLs (Reddit, YouTube, GitHub, newsletters, generic web) and writes AI-summarised Obsidian notes to a local knowledge graph. Python 3, async, uses python-telegram-bot v21+.

**Status**: Production-ready, verified end-to-end (2026-03-28). 259 tests passing.
**Repo**: https://github.com/chintanmehta21/zettelkasten-telegram-bot
**Obsidian KG**: `C:\Users\LENOVO\Documents\Syncthing\Obsidian\KG`
**Verified sources**: YouTube, GitHub, Newsletter (Substack), Generic (HN/web)

## Commands

```bash
# Run the bot (polling/dev mode)
python run.py
# or
python -m zettelkasten_bot

# Run all tests
pytest

# Run a single test file
pytest tests/test_extractors.py -v

# Run unit tests only (skip integration)
pytest tests/ --ignore=tests/integration_tests

# Run live integration tests (requires real API creds in .env)
pytest --live

# Coverage
pytest --cov=zettelkasten_bot --cov-report=term-missing

# Install dependencies
pip install -r requirements.txt
# or editable install:
pip install -e .
```

## Configuration

Settings are loaded by `zettelkasten_bot/config/settings.py` (Pydantic BaseSettings) from three sources in priority order: env vars > `.env` file > `config/config.yaml`. Secrets (TELEGRAM_BOT_TOKEN, GEMINI_API_KEY, REDDIT_CLIENT_*) must be in env vars or `.env`, never in config.yaml. Copy `.env.example` to `.env` to get started.

The `Settings` singleton is accessed everywhere via `get_settings()` (lru_cache). Tests that need settings without valid credentials should be careful — `get_settings()` calls `_validate_settings()` which does `SystemExit(1)` on missing required fields.

## Architecture

### Pipeline (the core flow)

`orchestrator.process_url` sequences the full capture: resolve redirects -> normalize URL -> detect source type -> dedup check -> extract content -> Gemini summarise -> build tags -> write Obsidian note -> mark seen.

Key modules in `zettelkasten_bot/pipeline/`:
- `orchestrator.py` — top-level pipeline entry point
- `summarizer.py` — Gemini API integration (GeminiSummarizer + tag building)
- `writer.py` — writes Markdown notes to KG_DIRECTORY
- `duplicate.py` — JSON-file-based seen-URL deduplication store

### Source Extractors (plugin pattern)

Extractors live in `zettelkasten_bot/sources/`. **Auto-discovery**: `__init__.py` scans the package at import time, finds all `SourceExtractor` subclasses with a `source_type` attribute, and registers them in `_REGISTRY`. No manual wiring needed.

To add a new source: (1) add enum value to `SourceType` in `models/capture.py`, (2) create extractor module in `sources/`, (3) add URL pattern to `sources/registry.py`, (4) add handler in `bot/handlers.py` + wire in `main.py`.

`get_extractor(source_type, settings)` returns an instantiated extractor, injecting credentials for sources that need them (currently only Reddit).

### Bot Layer

`main.py` wires everything: builds the PTB Application, registers CommandHandlers and MessageHandlers with a chat-ID allow-list filter (`bot/guards.py`), then starts polling or webhook mode.

`bot/handlers.py` contains all Telegram command handlers. They extract the URL from the message and delegate to `orchestrator.process_url`.

### Data Models

`models/capture.py` defines the shared Pydantic models: `SourceType` (enum), `CaptureRequest`, `ExtractedContent`, `ProcessedNote`. All pipeline stages communicate through these.

## Testing

- pytest with `asyncio_mode = auto` (pytest.ini)
- Custom `--live` flag: tests marked `@pytest.mark.live` are skipped by default; pass `--live` to run them (they hit real APIs and need `.env` credentials)
- `conftest.py` provides sample URL fixtures (`sample_reddit_url`, `sample_youtube_url`, etc.)
- Integration tests in `tests/integration_tests/` make real network calls
