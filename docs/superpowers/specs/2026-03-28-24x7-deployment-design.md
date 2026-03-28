# 24/7 Telegram Bot Deployment — Design Spec

**Date:** 2026-03-28
**Status:** Approved
**Goal:** Deploy the Zettelkasten Capture Bot to run 24/7 on a free hosting provider with webhook mode, add Telegram command menu, and solve cloud note storage.

## 1. Hosting: Render.com (Free Tier)

**Why Render:** The codebase already has full webhook support. Render provides a free HTTPS URL, auto-deploys from GitHub, and Telegram's webhook retry mechanism handles cold starts gracefully (~30s delay after 15 min idle).

**Mode:** Webhook (not polling). Render wakes the service on each incoming webhook request from Telegram.

### New files

- `Dockerfile` — Python 3.12, installs deps, runs `python -m zettelkasten_bot`
- `render.yaml` — Render blueprint: web service, free plan, env var references

### Environment variables on Render

All existing `.env` vars plus:
- `WEBHOOK_MODE=true`
- `WEBHOOK_URL=https://<render-app>.onrender.com/<bot-token>`
- `WEBHOOK_PORT=8443`
- `WEBHOOK_SECRET=<random-string>`
- `GITHUB_TOKEN=ghp_...`
- `GITHUB_REPO=chintanmehta21/obsidian-kg`
- `GITHUB_BRANCH=main`

## 2. Telegram Command Menu

Register commands with Telegram via `bot.set_my_commands()` during the `post_init` callback of the PTB Application. This makes the command list appear when users type `/` in the chat.

Commands to register:
```
start      - Welcome message and usage guide
help       - Show available commands
status     - Bot health and statistics
reddit     - Capture a Reddit post
yt         - Capture a YouTube video
newsletter - Capture a newsletter or article
github     - Capture a GitHub repo or issue
force      - Re-capture a URL (skip duplicate check)
```

### Implementation

In `main.py`, add a `post_init` callback:
```python
async def _post_init(application: Application) -> None:
    await application.bot.set_my_commands([
        BotCommand("start", "Welcome message and usage guide"),
        BotCommand("help", "Show available commands"),
        BotCommand("status", "Bot health and statistics"),
        BotCommand("reddit", "Capture a Reddit post"),
        BotCommand("yt", "Capture a YouTube video"),
        BotCommand("newsletter", "Capture a newsletter or article"),
        BotCommand("github", "Capture a GitHub repo or issue"),
        BotCommand("force", "Re-capture a URL (skip duplicate check)"),
    ])
```

Wire it: `Application.builder().token(...).post_init(_post_init).build()`

## 3. Cloud Note Storage: GitHub API

### Problem

The bot writes Obsidian notes to `KG_DIRECTORY` (local filesystem). On Render, there's no persistent storage and no access to the user's local Obsidian vault.

### Solution

New module `zettelkasten_bot/pipeline/github_writer.py` that pushes notes to a GitHub repo via the REST API using `httpx` (already a dependency).

**Behavior:**
- If `GITHUB_TOKEN` and `GITHUB_REPO` are set: push note to GitHub repo
- If not set: fall back to local `ObsidianWriter` (existing behavior)
- Both modes: the Telegram response includes the one-line summary (enhancing current terse confirmation)

### GitHubWriter interface

```python
class GitHubWriter:
    def __init__(self, token: str, repo: str, branch: str = "main"):
        ...

    async def write_note(
        self,
        content: ExtractedContent,
        result: SummarizationResult,
        tags: list[str],
    ) -> str:
        """Push note to GitHub repo. Returns the file URL."""
        # Build frontmatter + body (reuse existing _build_frontmatter, _build_body)
        # PUT /repos/{owner}/{repo}/contents/{path}
        # Returns commit URL
```

### User workflow for syncing

User creates a GitHub repo (e.g., `obsidian-kg`), then either:
1. Clones it into their Obsidian vault directory
2. Sets up a scheduled `git pull` (cron or Task Scheduler)
3. Or uses a tool like Syncthing + git

## 4. Enhanced Telegram Response

Currently the bot sends: `"title" + "Note saved to KG" + tags`

Change to include the one-line summary:
```
"title"
> one-line summary
Note saved (tokens, latency)
Tags: ...
```

This gives the user immediate value even before they open Obsidian.

## 5. Health Check

Add a simple health endpoint for Render monitoring. PTB's webhook mode already runs an HTTP server; we add a custom route:

```python
# In webhook config, use a custom ASGI/WSGI wrapper or PTB's built-in
# webhook custom path for health checks
```

Alternatively, Render can use the webhook endpoint itself (it returns 200 for non-Telegram requests).

## 6. Settings Changes

Add to `Settings` class in `settings.py`:
```python
# GitHub note storage (optional — for cloud deployment)
github_token: str = ""
github_repo: str = ""      # e.g., "user/repo"
github_branch: str = "main"
```

Add to `.env.example`:
```
# GITHUB_TOKEN=ghp_your-github-pat
# GITHUB_REPO=your-username/obsidian-kg
# GITHUB_BRANCH=main
```

## 7. Orchestrator Changes

In `orchestrator.py`, Phase 9 (write note):
```python
if settings.github_token and settings.github_repo:
    from zettelkasten_bot.pipeline.github_writer import GitHubWriter
    writer = GitHubWriter(settings.github_token, settings.github_repo, settings.github_branch)
    note_url = await writer.write_note(extracted, result, tags)
else:
    writer = ObsidianWriter(settings.kg_directory)
    note_path = writer.write_note(extracted, result, tags)
    note_url = None
```

## 8. Files Changed/Created

| File | Action | Purpose |
|------|--------|---------|
| `Dockerfile` | Create | Container for Render deployment |
| `render.yaml` | Create | Render blueprint config |
| `zettelkasten_bot/pipeline/github_writer.py` | Create | Push notes to GitHub via API |
| `zettelkasten_bot/main.py` | Modify | Add command menu + post_init |
| `zettelkasten_bot/pipeline/orchestrator.py` | Modify | GitHub writer integration + enhanced response |
| `zettelkasten_bot/config/settings.py` | Modify | Add github_* fields |
| `.env.example` | Modify | Add GitHub env var templates |
| `tests/test_github_writer.py` | Create | Unit tests for GitHub writer |
| `tests/test_bot_menu.py` | Create | Test command menu registration |

## 9. What Stays the Same

- All existing commands, handlers, extractors
- Local development workflow (polling mode, local KG write)
- Full test suite (259 tests)
- Config priority hierarchy
- Dedup store, guards, URL utilities

## 10. Verification Plan

1. Run existing test suite — all 259 pass
2. New tests for GitHubWriter (mocked HTTP)
3. New test for command menu registration
4. Deploy to Render
5. Send a link from Telegram → verify bot responds with summary
6. Check GitHub repo → verify .md note was pushed
7. Confirm bot stays responsive over time (survives cold starts)
