# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

Zettelkasten Capture Bot — a Telegram bot that captures URLs (Reddit, YouTube, GitHub, newsletters, generic web) and writes AI-summarised Obsidian notes to a local knowledge graph. Python 3, async, uses python-telegram-bot v21+.

**Status**: Production-ready. ~530 tests passing (CI). DigitalOcean blue/green deploy stack merged: 2026-04-10.
**Repo**: https://github.com/chintanmehta21/Zettelkasten_KG
**Obsidian KG**: `C:\Users\LENOVO\Documents\Syncthing\Obsidian\KG`
**Verified sources**: YouTube, GitHub, Newsletter (Substack), Generic (HN/web)

Two interfaces: Telegram bot (primary) and a FastAPI web UI (`website/`) with REST API at `/api/summarize` and an interactive 3D knowledge graph at `/knowledge-graph`.

## Production Change Discipline

This is a live production web application with active users across frontend, backend/API, and database layers. Every change has immediate real-world impact, and anything that cannot scale with user growth is unacceptable.

**Before any change:**
- Read and understand the full in-scope code path. Verify behavior from code, docs, tests, and existing patterns; do not assume.
- Identify every touched component, dependency, integration point, and side effect before editing.
- Reason through edge cases up front, including empty states, invalid inputs, concurrent requests, simultaneous writes, race conditions, auth failures, upstream/network timeouts, and data inconsistency risks.

**When implementing:**
- Ship complete, self-contained changes only. No TODOs, placeholders, stubs, or partial follow-ups.
- Preserve backward compatibility unless the user explicitly approves a breaking change.
- If a change has meaningful production risk, stop and ask for confirmation before proceeding. State the risk clearly and propose the safest path.
- Do not treat ambiguous behavior as settled. Resolve ambiguity explicitly from code or docs, or surface the uncertainty.

**Testing requirements:**
- Add or update tests for happy paths, edge cases, boundary/invalid inputs, and relevant scale/concurrency scenarios.
- For stateful or shared-resource paths, cover high concurrency, simultaneous writes, race conditions, and session collision risks where the code path can plausibly fail under load.
- Run the relevant test suite and verify existing tests still pass. If anything fails, diagnose and fix the regression before considering the task complete.

**Communication style:**
- Be concise and technical. State what changed, why, impact, and any residual risk.
- Use bullet points only for major tasks; keep smaller updates brief.
- Ask for confirmation before risky changes.
- State uncertainty explicitly. Never present assumptions as facts.
- Cite relevant documentation, specifications, or library behavior when correctness depends on those details.
- Flag the conditions under which the implementation could break.

**Never:**
- Leave the codebase in a broken, partial, or knowingly fragile state.
- Skip tests because a change appears simple.
- Ignore scalability, concurrency, or failure-mode analysis.
- Proceed through ambiguity without acknowledging it.
- Present assumptions as verified facts.

## Commands

```bash
# Run the bot (polling/dev mode)
python run.py
# or
python -m telegram_bot

# Run all tests
pytest

# Run a single test file
pytest tests/test_extractors.py -v

# Run unit tests only (skip network-dependent tests)
pytest tests/ --ignore=tests/integration_tests

# Run live integration tests (requires real API creds in .env)
pytest --live

# Coverage
pytest --cov=telegram_bot --cov-report=term-missing

# Install runtime dependencies only
pip install -r ops/requirements.txt

# Install dev/test dependencies (includes pytest, pytest-asyncio, pytest-httpx)
pip install -r ops/requirements-dev.txt

# Editable install (optional)
pip install -e .
```

## Deployment (DigitalOcean Droplet)

Production deploys are automated via GitHub Actions and a blue/green Docker Compose stack on a DigitalOcean droplet.

### GitHub Actions

`.github/workflows/deploy-droplet.yml` runs on pushes to `master`:
- Runs `pytest` with stubbed env vars (no real secrets required for unit tests).
- Builds and pushes `ghcr.io/chintanmehta21/zettelkasten-kg-website` using `ops/Dockerfile`.
- SSH deploys to the droplet and runs `/opt/zettelkasten/deploy/deploy.sh <git-sha>`.

### Blue/Green Compose

Compose files live in `ops/`:
- `docker-compose.blue.yml` binds `127.0.0.1:10000`.
- `docker-compose.green.yml` binds `127.0.0.1:10001`.
- Caddy terminates TLS and proxies to the active color (see `ops/caddy/`).

### Secrets / Env Vars

See `ops/.env.example` for the canonical list. Common ones:
- Required: `TELEGRAM_BOT_TOKEN`, `ALLOWED_CHAT_ID`, `WEBHOOK_SECRET`, `GEMINI_API_KEYS` (preferred) or `GEMINI_API_KEY`
- Optional: `SUPABASE_URL`, `SUPABASE_ANON_KEY` (Supabase KG), `GITHUB_TOKEN`, `GITHUB_REPO` (push notes to GitHub)

### Note Storage
- **Local mode:** Notes written to `KG_DIRECTORY` (default `./kg_output`). In production droplet deploys this is backed by a host volume.
- **Cloud mode:** When `GITHUB_TOKEN` and `GITHUB_REPO` are set, notes are pushed via GitHub Contents API (base64-encoded PUT). `settings.github_enabled` returns True when both are set. `GITHUB_BRANCH` defaults to `main`.

## Configuration

Settings are loaded by `telegram_bot/config/settings.py` (Pydantic BaseSettings) from three sources in priority order: env vars > `.env` file > `ops/config.yaml`. Secrets (TELEGRAM_BOT_TOKEN, GEMINI_API_KEY, REDDIT_CLIENT_*) must be in env vars or `.env`, never in config.yaml. Copy `ops/.env.example` to `.env` to get started.

The `Settings` singleton is accessed everywhere via `get_settings()` (lru_cache). Tests that need settings without valid credentials should be careful — `get_settings()` calls `_validate_settings()` which does `SystemExit(1)` on missing required fields.

### Reddit credentials and RAG chunk density

`REDDIT_CLIENT_ID` and `REDDIT_CLIENT_SECRET` are **required for OAuth-backed Reddit extraction** (used by the website `RedditIngestor` and by `ops/scripts/backfill_chunks.py --refetch-source` when it encounters `/r/` URLs). Without them the ingestor degrades to the public JSON endpoint + HTML scraping, which often returns thin content for Reddit's anti-bot walls and caps RAG chunk density at ~1 chunk per post. Set both in the production container's env or `/etc/secrets/api_env`. See `ops/.env.example` for the template.

## Architecture

### Pipeline (the core flow)

`orchestrator.process_url` sequences the full capture: resolve redirects -> normalize URL -> detect source type -> dedup check -> extract content -> Gemini summarise -> build tags -> write Obsidian note -> mark seen.

Key modules in `telegram_bot/pipeline/`:
- `orchestrator.py` — top-level pipeline entry point
- `summarizer.py` — Gemini API integration (GeminiSummarizer + tag building)
- `writer.py` — writes Markdown notes to KG_DIRECTORY (local mode)
- `github_writer.py` — pushes notes to GitHub repo via Contents API (cloud mode, base64-encoded PUT)
- `duplicate.py` — JSON-file-based seen-URL deduplication store

#### API Key Pool & Model Fallback

A centralized `GeminiKeyPool` (`website/features/api_key_switching/`) manages up to 10 API keys with key-first traversal: `key1/gemini-2.5-flash` → `key2/gemini-2.5-flash` → ... → `key1/gemini-2.5-flash-lite` → `key2/gemini-2.5-flash-lite`. On a 429 rate-limit, it tries the next key (same model) before downgrading to the next model tier. Content-aware routing sends short/simple content to `flash-lite` first to preserve `flash` quota for complex content. Keys are loaded from an `api_env` file (one key per line) at project root or `/etc/secrets/api_env` (Render-compatible secret-file path), with fallback to `GEMINI_API_KEY` for backward compatibility. If ALL keys/models fail, the pipeline degrades gracefully — returns raw extracted content with `is_raw_fallback=True`. For YouTube, it can bypass transcript extraction and send the video URL directly to Gemini's video understanding API.

### Source Extractors (plugin pattern)

Extractors live in `telegram_bot/sources/`. **Auto-discovery**: `__init__.py` scans the package at import time, finds all `SourceExtractor` subclasses with a `source_type` attribute, and registers them in `_REGISTRY`. No manual wiring needed.

To add a new source: (1) add enum value to `SourceType` in `models/capture.py`, (2) create extractor module in `sources/`, (3) add URL pattern to `sources/registry.py`, (4) add handler in `bot/handlers.py` + wire in `main.py`.

`get_extractor(source_type, settings)` returns an instantiated extractor, injecting credentials for sources that need them (currently only Reddit).

### Bot Layer

`main.py` wires everything: builds the PTB Application, registers CommandHandlers and MessageHandlers with a chat-ID allow-list filter (`bot/guards.py`), then starts polling or webhook mode.

- **Polling mode** (dev): PTB's built-in `run_polling()` with long-poll loop.
- **Webhook mode** (prod): FastAPI + Uvicorn serve both the web UI and Telegram webhook on a single port (10000). The webhook route is inserted at position 0 in FastAPI routes to match before API/static routes. PTB Application lifecycle is managed via FastAPI's lifespan context manager. Validates `X-Telegram-Bot-Api-Secret-Token` header when `webhook_secret` is set.

`bot/handlers.py` contains all Telegram command handlers. They extract the URL from the message and delegate to `orchestrator.process_url`.

### Web UI (`website/`)

FastAPI app mounted alongside the bot in webhook mode. Two main pages: a URL summarizer at `/` and a 3D knowledge graph visualizer at `/knowledge-graph`. Mobile browsers auto-redirect to `/m/` (detected via user-agent regex in `website/app.py`).

- `website/api/routes.py` — `POST /api/summarize` with in-memory rate limiting (10 req/min per IP); `GET /api/graph` returns KG data (Supabase-first with 30s TTL cache, file-store fallback); `GET /api/health` (used by container / load balancer health checks)
- `website/core/pipeline.py` — reuses the bot's extraction/summarization pipeline but is **stateless**: no disk writes, no dedup updates. Returns a structured dict with title, summary, tags, latency_ms, etc.
- `website/core/graph_store.py` — thread-safe in-memory store backed by `website/features/knowledge_graph/content/graph.json`. Auto-links new nodes to existing ones based on shared normalized tags. Node IDs use source-type prefixes (`yt-`, `gh-`, `rd-`, `ss-`, `md-`, `web-`) + slugified title.

#### Supabase Knowledge Graph (`website/core/supabase_kg/`)

Optional Supabase-backed KG that replaces the file-based `graph.json` store. When `SUPABASE_URL` and `SUPABASE_ANON_KEY` are set (`is_supabase_configured()` returns True), the API dual-writes: every `POST /api/summarize` writes to both the file store and Supabase, and `GET /api/graph` reads from Supabase first.

- `client.py` — Supabase client init via `get_supabase_client()`, gated by `is_supabase_configured()`
- `models.py` — Pydantic models: `KGNode`, `KGLink`, `KGUser`, `KGGraph` (with Create variants)
- `repository.py` — `KGRepository` with CRUD: `get_or_create_user()`, `add_node()`, `node_exists()`, `get_graph()`
- Schema: `supabase/website/kg_public/schema.sql` (tables: `kg_users`, `kg_nodes`, `kg_links`)
- Migration: `python ops/scripts/migrate_graph_to_supabase.py` — migrates `graph.json` data to Supabase (requires `supabase/.env` with `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY`)

### URL Utilities (`utils/url_utils.py`)

Security-conscious URL handling: `validate_url()` blocks private/reserved IPs (SSRF protection), `normalize_url()` strips tracking params (utm_*, fbclid, etc.) and sorts query params for dedup consistency, `resolve_redirects()` follows chains async with HEAD-first strategy, `is_shortener()` detects 16 known shortener domains.

### Data Models

`models/capture.py` defines the shared Pydantic models: `SourceType` (enum), `CaptureRequest`, `ExtractedContent`, `ProcessedNote`. All pipeline stages communicate through these.

## Code Navigation (smart-explore is the default)

For **any code file in this repo** (`*.py`, `*.ts`, `*.tsx`, `*.js`, `*.jsx`, `*.go`, `*.rs`, `*.java`, `*.cs`, etc.), always prefer the claude-mem `smart-explore` skill over `Read` / `Grep` / `Glob`:

1. **Discover** with `smart_search(query=..., path="./telegram_bot")` — replaces the Glob → Grep → Read cycle.
2. **Map a file** with `smart_outline(file_path=...)` — replaces reading a full file.
3. **Zoom to one symbol** with `smart_unfold(file_path=..., symbol_name=...)` — replaces reading a range.

**Fallback ladder** (use standard tools *only* when smart-explore can't handle the task):
- File is <100 lines, a non-code file (JSON/YAML/TOML/Markdown/config), or `.env*` → use `Read`.
- Need exact string / regex match (e.g., hunting `TODO`, a log string, a specific import path) → use `Grep`.
- Need filesystem path patterns (e.g., all test files, all Dockerfiles) → use `Glob`.
- Need cross-file narrative synthesis across 6+ files → dispatch the `Explore` agent.
- `smart_search` returns zero hits *and* the target is known to exist → fall back to `Grep` with the same query, then `Read` the single matching file.

Rule of thumb: **the question before every code-file read is "can I get a structural overview first?"** If yes, smart-explore.

## Multi-phase Work (make-plan → do)

Any task that spans **2+ phases, 3+ files, or requires verification gates** must be driven by the `make-plan` → `do` skill pair from claude-mem:

1. **`make-plan`** — Phase 0 is always Documentation Discovery (no implementation until docs/APIs are confirmed). Each subsequent phase has: what to implement, documentation references, verification checklist, anti-pattern guards.
2. **`do`** — executes the plan via subagents: one Implementation subagent per phase, then Verification, Anti-pattern, Code Quality, and Commit subagents. Never advance a phase until verification passes.

Single-file tweaks, typo fixes, and isolated bug patches do **not** need this pipeline — go direct.

## Secrets Handling (`<private>` tags)

claude-mem's hook layer strips `<private>...</private>` tags **before** observations reach the worker/DB. Wrap every secret value or file excerpt in these tags whenever it appears in assistant output, plan text, tool arguments, or commit descriptions.

**Always wrap content from:**
- `new_envs.txt` (project root — untracked)
- `.env` (project root)
- `supabase/.env`
- Any other `.env*` file in this repo except `ops/.env.example` (which is a template with no real values)
- Any file under `~/.ssh/`, droplet SSH private keys, or key material pasted into the chat

**Always wrap values of:**
- `GEMINI_API_KEY`, `GEMINI_API_KEYS`
- `TELEGRAM_BOT_TOKEN`, `WEBHOOK_SECRET`
- `SUPABASE_SERVICE_ROLE_KEY`, `SUPABASE_ANON_KEY`, `SUPABASE_URL` (project ref is sensitive)
- `GITHUB_TOKEN`
- `REDDIT_CLIENT_ID`, `REDDIT_CLIENT_SECRET`
- Any droplet IP, hostname, or SSH key fingerprint

**Example:** `GEMINI_API_KEY=<private>AIzaSy...redacted</private>`.

**Never** echo full `.env` file contents into assistant output without wrapping. **Never** commit secrets — and if you read one into context, treat the memory record as contaminated and flag it.

## Memory Tagging (claude-mem observation types)

claude-mem captures every session under the `code` mode with 6 observation types: `bugfix`, `feature`, `refactor`, `change`, `discovery`, `decision`. Frame prompts and response openings so the observer tool tags them correctly — this makes future `search(obs_type=...)` queries sharp.

**Deliberate framing (state the type in the first sentence when ambiguous):**
- Bug fixes → "Fixing X which was broken because Y" → tagged `bugfix`
- New capability → "Adding X feature that now supports Y" → tagged `feature`
- Restructure with same behavior → "Refactoring X to separate Y from Z" → tagged `refactor`
- Docs/config/misc → "Updating X config" → tagged `change`
- Reading existing code to understand → "Discovering how X works" → tagged `discovery`
- **Architectural/design choice with rationale** → always prefix with **"This is a decision because..."** → tagged `decision`

**Non-negotiable: any of the following must be captured as a `decision` observation with explicit rationale**, even if the user frames it casually:
- GeminiKeyPool traversal order (key-first vs model-first), new model tier additions, content-aware routing thresholds
- Supabase vs file-store precedence, dual-write toggles, schema migrations
- Blue/green cutover trigger, rollback criteria, Caddy upstream changes
- Any new source extractor (plugin vs monkey-patch vs external service)
- Any change to the `orchestrator.process_url` sequence
- Auth/secret-handling model changes
- Dependency additions/removals or Python-version bumps
- Test strategy shifts (live vs stubbed, new marker, new fixture tier)

**Going forward, apply this rule dynamically: whenever you pick between two or more viable approaches for anything not in the list above, announce "this is a decision because..." and record the rationale inline.** The observer will tag it correctly and the narrative will be retrievable via `search(obs_type="decision")` in future sessions.

## Cross-Agent Memory (Claude Code CLI + Claude Code Desktop + Codex Desktop)

Three agents can edit this repo on this machine, plus the non-Claude-Code Claude Desktop chat app as a read-only memory consumer. The system is designed so all four see the same claude-mem brain with zero data duplication.

### Agent topology

| Agent | Binary / config root | Identifies itself via | Write path to claude-mem | Read path from claude-mem |
|---|---|---|---|---|
| **Claude Code CLI** | `~/.local/bin/claude.exe` + `~/.claude/` | `CLAUDECODE=1`, `CLAUDE_CODE_ENTRYPOINT=cli` | Native PostToolUse hook from `thedotmack/claude-mem` plugin (per-tool-use granularity) | claude-mem plugin in `~/.claude/plugins/cache/thedotmack/claude-mem/` |
| **Claude Code Desktop** (embedded in Claude Desktop) | `%APPDATA%\Claude\claude-code\<ver>\claude.exe` | `CLAUDECODE=1`, `CLAUDE_CODE_ENTRYPOINT=claude-desktop` | Same PostToolUse hook as CLI — Claude Desktop's embedded Claude Code shares `~/.claude/` plugins and settings | Same plugin cache as CLI |
| **Codex Desktop** (OpenAI, Appx-installed) | `C:\Program Files\WindowsApps\OpenAI.Codex_<ver>\app\Codex.exe` (Electron) + `app\resources\codex.exe` (engine) with `~/.codex/` as data root | Process-tree walk finds `WindowsApps\OpenAI.Codex` ancestor | Git post-commit hook → `.claude-mem-queue/` → drained by Claude Code at next session start | MCP server `claude_mem` registered in `~/.codex/config.toml` `[mcp_servers.claude_mem]` — same `mcp-server.cjs`, same DB |
| **Claude Desktop** (Electron chat, non-Claude-Code mode) | `%APPDATA%\Claude\` + `claude_desktop_config.json` | N/A (chat, doesn't commit) | None — Claude Desktop chat conversations aren't captured as code work | MCP server `claude_mem` registered in `claude_desktop_config.json` `mcpServers.claude_mem` |

### Five shared layers

1. **Code state** — shared git checkout. No config needed. All three agents edit the same working tree.
2. **Rules** — `CLAUDE.md` (this file) is canonical. `AGENTS.md` at the project root is an auto-synced mirror regenerated by `ops/git-hooks/pre-commit` on every commit that stages `CLAUDE.md` — never edit it by hand. Codex Desktop auto-loads `AGENTS.md` at every session start (project root + walks down from cwd). User-global Codex rules live at `~/.codex/AGENTS.md`. Claude Code (CLI and Desktop) auto-loads `CLAUDE.md` and `~/.claude/CLAUDE.md`.
3. **Folder timelines** — claude-mem writes per-folder `CLAUDE.md` activity files automatically (flag `CLAUDE_MEM_FOLDER_CLAUDEMD_ENABLED=true` in `~/.claude-mem/settings.json`). All three agents read these via their normal `Read` tool — no special integration needed.
4. **Historical memory (claude-mem DB)** — all four clients point at the same SQLite DB at `~/.claude-mem/claude-mem.db` (~109 MB) via the same `mcp-server.cjs` at `~/.claude/plugins/cache/thedotmack/claude-mem/10.5.6/scripts/`. Zero data duplication: Codex Desktop, Claude Desktop, and Claude Code all share one on-disk database.
5. **Write capture** — only Claude Code CLI / Claude Code Desktop have per-tool-use PostToolUse hooks that write observations directly to the DB. Codex Desktop captures commit-granularity via `ops/git-hooks/post-commit`, which writes queue files that Claude Code drains at next session start.

### Write path: the git post-commit queue

`ops/git-hooks/post-commit` fires on every `git commit` regardless of the tool. Its tool-detection chain is (first hit wins):

1. `CLAUDE_MEM_AUTHOR_TOOL` env var — manual override.
2. Tool-set env vars that propagate into git's environment (`CLAUDECODE`, `CLAUDE_CODE_ENTRYPOINT`, `CURSOR_TRACE_ID`, `TERM_PROGRAM=vscode`, `JETBRAINS_IDE`, `CODEX_HOME`/`OPENAI_CODEX`).
3. PowerShell single-shot process-tree walk (`Get-CimInstance Win32_Process`, 8 ancestors) — catches GUI agents that don't set env vars. Recognizes `claude-code (desktop)` via the `AppData\Roaming\Claude\claude-code` path, `codex-desktop` via the `WindowsApps\OpenAI.Codex` path, and `cursor` / `vscode` / `jetbrains` / `github-desktop` / `sourcetree` by process name.
4. Fallback: `unknown` — entry still lands in queue, tool can be re-tagged manually.

Activation (run once per clone): `git config core.hooksPath ops/git-hooks`. Already set on the current clone; verify with `git config --get core.hooksPath`.

### Queue-drain protocol (Claude Code CLI or Desktop, at every session start)

1. Check if `.claude-mem-queue/` has any `*.md` files.
2. For each file, read its frontmatter + body, then infer the observation type from the conventional-commit prefix (`feat:` → `feature`, `fix:` → `bugfix`, `refactor:` → `refactor`, `docs:`/`test:`/`chore:`/`style:` → `change`, anything else → `discovery`). Decisions are only tagged when the body contains `"This is a decision because"`.
3. Emit a short chat message per queued entry in the form *"Recording from &lt;tool&gt; commit &lt;sha&gt;: &lt;subject&gt;"* — this triggers the claude-mem observer via normal PostToolUse capture. Use the `tool:` frontmatter value so the observer knows the origin.
4. After the entry is processed, delete the queue file.
5. If a file is >7 days old, archive it to `.claude-mem-queue/archived/` instead of deleting, in case it wasn't ingested correctly.

This turns commits-from-anywhere — CLI, Desktop, Codex, GUI editors — into observations-in-the-DB with zero manual effort.

### Forward-looking: Codex Desktop plugin hooks

Codex Desktop supports a plugin hook system with the same schema as Claude Code plugins: `hooks/hooks.json` + `hooks/scripts/` inside a plugin with both `.claude-plugin/plugin.json` and `.codex-plugin/plugin.json` marker files. Hook commands can reference `${CLAUDE_PLUGIN_ROOT}`. At least the `Stop` event is supported; `PostToolUse` coverage is unverified. This means a future tighter capture path is possible: install a minimal claude-mem shim plugin into `~/.codex/plugins/` with a Stop hook that writes per-task entries to `.claude-mem-queue/`, giving sub-commit granularity for Codex Desktop. Not yet wired — the git post-commit path is sufficient for now.

## Git Commits

- **5–10 words max in the commit subject.** Accurately showcase the changes made. No body paragraphs, no bullet lists, no explanations.
- **No tool or author names.** Never mention `Claude`, `Codex`, `Copilot`, `ChatGPT`, or any AI tool / assistant / human author anywhere in the message.
- **No `Co-Authored-By` trailers.** Never append `Co-Authored-By:` lines.
- **Prefix tags** (always use one; the prefix counts toward the word budget):
  - `build:` — Releases only. **Never** use autonomously; only when the user explicitly asks. (e.g., `build: v0.0.1`)
  - `feat:` — Major feature builds. (e.g., `feat: migrate reranker`)
  - `fix:` — Minor fixes or loop deploys. (e.g., `fix: stabilize streaming token test for CI timing`)
  - `chore:` — Ad-hoc tasks; use as "others" when nothing else fits. (e.g., `chore: aggressive Docker prune to reclaim 8.5GB`)
  - `ci:` — Changes to CI/CD pipelines. (e.g., `ci: SHA-pin SCP action in deploy workflow`)
  - `ops:` — Infrastructure and deployment operational tasks. (e.g., `ops: sync deploy scripts to droplet`)
  - `refactor:` — Restructure with same behavior. (e.g., `refactor: extract key pool into module`)
  - `docs:` — Documentation only. (e.g., `docs: update CLAUDE.md commit tags`)
  - `test:` — Test additions or changes only. (e.g., `test: add KG node dedup coverage`)
- When a commit implements a prior-session decision, append the observation ID in parentheses: e.g., `feat(engine): key-first rotation (#S155)`. The `(#S...)` token does not count toward the word budget.

## Testing

- pytest with `asyncio_mode = auto` (`pyproject.toml`)
- Custom `--live` flag: tests marked `@pytest.mark.live` are skipped by default; pass `--live` to run them (they hit real APIs and need `.env` credentials)
- `conftest.py` provides sample URL fixtures (`sample_reddit_url`, `sample_youtube_url`, etc.)
- Integration tests in `tests/integration_tests/` make real network calls
- **Settings in tests**: Always mock `get_settings()` via `@patch` — calling it without valid env vars triggers `SystemExit(1)` from `_validate_settings()`

## UI Design

- **No purple.** Never use purple, violet, or lavender (`hsl(250–290)`, `#A78BFA`, etc.) anywhere in the UI. The Knowledge Graph accent is amber/gold (`#D4A024`); the main site accent is teal.

## Docker

Multi-stage build (`ops/Dockerfile`): Stage 1 installs `ops/requirements.txt` into `/opt/venv` and pre-compiles `.pyc` files for cold-start optimization. Stage 2 copies only the venv and compiled code. Base image: `python:3.12-slim`. Exposes port 10000 (production default). Entry point: `python run.py`. Build with `docker build -f ops/Dockerfile -t zettelkasten-bot .` from the repo root.
