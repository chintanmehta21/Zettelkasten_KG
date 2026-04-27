# Render → DigitalOcean Migration Implementation Plan

> **ARCHIVED — Historical migration record (legacy, no longer used).** This plan tracked the one-time migration from Render.com to a DigitalOcean droplet. The migration is complete and the droplet (Premium Intel 2 GB RAM / 1 vCPU / 70 GB NVMe SSD with Reserved IP, blue/green Docker Compose + Caddy) is the canonical and only production environment. **Do not action any Render-related step in this file** — they are preserved for context only. See "Deployment Infrastructure (Canonical)" in the project root `CLAUDE.md` for the live setup.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Migrate the production `website/` FastAPI application from Render.com to a single DigitalOcean Droplet (Premium AMD $7/mo, BLR1) running Docker behind Caddy with zero-downtime blue-green deploys, persistent SSD storage, and 99.9%+ uptime hardening.

**Architecture:** Single Droplet hosts two app containers (`zettelkasten-blue:10000`, `zettelkasten-green:10001`) and one Caddy 2 container. Caddy reverse-proxies to whichever color is "live" via a hot-swappable `upstream.snippet` file. GitHub Actions builds a private image to GHCR, then SSHes to the droplet to flip colors with graceful Caddy reload (zero dropped connections). DNS sits at Cloudflare (delegated from GoDaddy registrar) for ~11 ms anycast performance.

**Tech Stack:** Python 3.12 + FastAPI + python-telegram-bot, Docker Compose, Caddy 2 (auto Let's Encrypt), GHCR private images, GitHub Actions CI/CD, Cloudflare DNS, BetterStack monitoring, Supabase Free (unchanged), DO Droplet `s-1vcpu-1gb` Premium AMD on BLR1.

**Source spec:** `docs/superpowers/specs/2026-04-09-render-to-digitalocean-migration-design.md`

---

## Reading order

Phases 1–7 are **code/config work in the repo** that can be implemented and tested locally. Phases 8–13 are **external/operational work** (buying domain, provisioning droplet, DNS cutover) and can only be done after Phases 1–7 are merged to `master`.

| Phase | Title | Tasks | Where |
|---|---|---|---|
| 1 | Application Code Refactors | 1–5 | repo, TDD with pytest |
| 2 | Container Packaging | 6–10 | repo |
| 3 | Caddy + Compose Stack | 11–15 | repo |
| 4 | Local Rehearsal | 16 | laptop |
| 5 | Host Bootstrap Scripts | 17–21 | repo |
| 6 | Deploy Automation Scripts | 22–24 | repo |
| 7 | GitHub Actions Workflows | 25–28 | repo |
| 8 | External Setup | 29–35 | browser, manual |
| 9 | Droplet Bootstrap | 36–38 | SSH, manual |
| 10 | First Deploy to Staging | 39–42 | CI + verification |
| 11 | Production Cutover | 43–47 | DNS + setWebhook |
| 12 | Post-Cutover Hardening | 48–52 | manual |
| 13 | Cleanup | 53 | T+7 days |

---

## File Structure

### New files (created by this plan)

```text
ops/
  Dockerfile                            # REWRITE — multi-stage, tini, non-root, healthcheck (Task 7)
  .dockerignore                         # CREATE/EXPAND (Task 8)
  requirements.txt                      # SPLIT — runtime only (Task 6)
  requirements-dev.txt                  # NEW — pytest + dev tools only (Task 6)
  caddy/
    Caddyfile                           # NEW (Task 11)
    upstream.snippet                    # NEW (Task 11)
  docker-compose.blue.yml               # NEW (Task 12)
  docker-compose.green.yml              # NEW (Task 12)
  docker-compose.caddy.yml              # NEW (Task 13)
  docker-compose.dev.yml                # NEW — hot-reload dev (Task 14)
  docker-compose.prod-local.yml         # NEW — strict prod parity (Task 15)
  deploy/
    deploy.sh                           # NEW (Task 22)
    rollback.sh                         # NEW (Task 23)
    healthcheck.sh                      # NEW (Task 24)
  host/
    bootstrap.sh                        # NEW (Task 18)
    sysctl-zettelkasten.conf            # NEW (Task 17)
    ufw-rules.sh                        # NEW (Task 19)
    logrotate-zettelkasten.conf         # NEW (Task 20)
  systemd/
    zettelkasten.service                # NEW (Task 21)
.github/workflows/
  ci.yml                                # NEW — pytest on PR + push (Task 25)
  deploy-droplet.yml                    # NEW — build, push GHCR, SSH deploy (Task 26)
  live-tests.yml                        # NEW — manual + weekly cron (Task 27)
  keep-alive.yml                        # DELETE (Task 28)
```

### Edited files

```text
website/features/api_key_switching/__init__.py
  # Add GEMINI_API_KEYS env var fallback in init_key_pool() (Task 1)

website/core/pipeline.py
  # Move heavy imports inside summarize_url() for lazy loading (Task 2)

website/experimental_features/nexus/service/persist.py
  # Move find_similar_nodes + generate_embedding imports inside
  # persist_summarized_result() for lazy loading (Task 3)

telegram_bot/main.py
  # Rename webhook path from /webhook to /telegram/webhook for namespacing
  # (Task 4) — header auth already exists

website/app.py
  # Add NEXUS_ENABLED env var feature flag around nexus router and routes (Task 5)

tests/test_api_key_pool_env.py             # NEW (Task 1)
tests/test_pipeline_lazy_imports.py        # NEW (Task 2)
tests/test_persist_lazy_imports.py         # NEW (Task 3)
tests/test_telegram_webhook_path.py        # NEW (Task 4)
tests/test_nexus_feature_flag.py           # NEW (Task 5)
```

### Created at runtime on droplet (not in repo)

```text
/opt/zettelkasten/
  compose/                              # bind-mounted from /opt/zettelkasten/...
    docker-compose.blue.yml
    docker-compose.green.yml
    docker-compose.caddy.yml
    .env                                  # written by deploy workflow, mode 0600
    ACTIVE_COLOR                          # contains "blue" or "green"
  caddy/
    Caddyfile
    upstream.snippet
    data/                                 # ACME state, persisted across restarts
    config/
  data/
    kg_output/                            # persistent KG notes (if local mode used)
    bot_data/                             # seen_urls.json, etc.
  logs/
    deploy.log
    caddy-access.log
  deploy/
    deploy.sh
    rollback.sh
    healthcheck.sh
```

---

# Phase 1: Application Code Refactors

These are real code changes with real pytest tests. They are independent of the droplet and can be merged to master before any infrastructure work.

---

## Task 1: Add `GEMINI_API_KEYS` env var fallback to key pool

**Files:**
- Modify: `website/features/api_key_switching/__init__.py:39-65` (the `init_key_pool` function)
- Test: `tests/test_api_key_pool_env.py` (new)

**Context:** The current loader reads `api_env` files at three known paths, then falls back to a single `GEMINI_API_KEY` from settings. On the DigitalOcean droplet there is no Render-style Secret File, so we need a `GEMINI_API_KEYS` env var (comma-separated) priority that sits between the file paths and the single-key fallback.

- [ ] **Step 1: Write the failing test**

Create `tests/test_api_key_pool_env.py`:

```python
"""Tests for the GEMINI_API_KEYS env var fallback in init_key_pool()."""
from __future__ import annotations

import importlib

import pytest


@pytest.fixture(autouse=True)
def reset_pool_singleton():
    """Reset the module-level _pool singleton between tests."""
    import website.features.api_key_switching as pkg
    pkg._pool = None
    yield
    pkg._pool = None


def test_loads_keys_from_env_var_when_no_file(monkeypatch, tmp_path):
    """GEMINI_API_KEYS env var (comma-separated) is used when no api_env file exists."""
    # Point all file paths at non-existent locations
    import website.features.api_key_switching as pkg
    monkeypatch.setattr(pkg, "_API_ENV_PATHS", [str(tmp_path / "no_such_file")])

    monkeypatch.setenv("GEMINI_API_KEYS", "key_alpha,key_beta,key_gamma")

    pool = pkg.init_key_pool()

    assert pool is not None
    assert pool._keys == ["key_alpha", "key_beta", "key_gamma"]


def test_env_var_strips_whitespace_and_skips_empty(monkeypatch, tmp_path):
    """Whitespace and empty entries are tolerated in GEMINI_API_KEYS."""
    import website.features.api_key_switching as pkg
    monkeypatch.setattr(pkg, "_API_ENV_PATHS", [str(tmp_path / "no_such_file")])

    monkeypatch.setenv("GEMINI_API_KEYS", " key_one , ,key_two,  ")

    pool = pkg.init_key_pool()

    assert pool._keys == ["key_one", "key_two"]


def test_file_takes_priority_over_env_var(monkeypatch, tmp_path):
    """If an api_env file exists, it wins over GEMINI_API_KEYS."""
    import website.features.api_key_switching as pkg

    api_env_file = tmp_path / "api_env"
    api_env_file.write_text("file_key_1\nfile_key_2\n", encoding="utf-8")

    monkeypatch.setattr(pkg, "_API_ENV_PATHS", [str(api_env_file)])
    monkeypatch.setenv("GEMINI_API_KEYS", "env_key_1,env_key_2,env_key_3")

    pool = pkg.init_key_pool()

    assert pool._keys == ["file_key_1", "file_key_2"]


def test_falls_back_to_single_key_when_env_var_empty(monkeypatch, tmp_path):
    """When GEMINI_API_KEYS is empty/missing, fall back to settings.gemini_api_key."""
    import website.features.api_key_switching as pkg
    monkeypatch.setattr(pkg, "_API_ENV_PATHS", [str(tmp_path / "no_such_file")])
    monkeypatch.delenv("GEMINI_API_KEYS", raising=False)

    class FakeSettings:
        gemini_api_key = "single_legacy_key"

    monkeypatch.setattr(pkg, "get_settings", lambda: FakeSettings())

    pool = pkg.init_key_pool()
    assert pool._keys == ["single_legacy_key"]


def test_raises_when_no_source_yields_keys(monkeypatch, tmp_path):
    """Empty file paths + empty env var + empty single-key → ValueError."""
    import website.features.api_key_switching as pkg
    monkeypatch.setattr(pkg, "_API_ENV_PATHS", [str(tmp_path / "no_such_file")])
    monkeypatch.delenv("GEMINI_API_KEYS", raising=False)

    class FakeSettings:
        gemini_api_key = ""

    monkeypatch.setattr(pkg, "get_settings", lambda: FakeSettings())

    with pytest.raises(ValueError, match="No Gemini API keys"):
        pkg.init_key_pool()
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
pytest tests/test_api_key_pool_env.py -v
```

Expected: 5 tests fail. The first one fails because `init_key_pool` does not currently look at `GEMINI_API_KEYS`. (Some may fail with `KeyError` or fall through to the existing single-key path.)

- [ ] **Step 3: Implement the env var fallback**

Edit `website/features/api_key_switching/__init__.py`. Add `import os` near the top, then insert the new "Source 2.5" block between the file-paths loop and the settings fallback. The full updated function:

```python
import os  # add at top of file alongside other imports


def init_key_pool() -> GeminiKeyPool:
    """Initialize the global key pool.

    Loader priority (first non-empty source wins):
      1. api_env file at one of _API_ENV_PATHS (one key per line)
      2. GEMINI_API_KEYS environment variable (comma-separated list)
      3. settings.gemini_api_key (backward compat with single-key)

    Raises ValueError if no source yields any keys.
    """
    global _pool  # noqa: PLW0603

    # Source 1: api_env file
    for path in _API_ENV_PATHS:
        keys = _load_keys_from_file(path)
        if keys:
            logger.info("Loaded %d Gemini API key(s) from %s", len(keys), path)
            _pool = GeminiKeyPool(keys)
            return _pool

    # Source 2: GEMINI_API_KEYS env var (comma-separated)
    env_csv = os.environ.get("GEMINI_API_KEYS", "").strip()
    if env_csv:
        env_keys = [k.strip() for k in env_csv.split(",") if k.strip()]
        if env_keys:
            logger.info(
                "Loaded %d Gemini API key(s) from GEMINI_API_KEYS env var",
                len(env_keys),
            )
            _pool = GeminiKeyPool(env_keys)
            return _pool

    # Source 3: backward compat — single key from settings
    settings = get_settings()
    if settings.gemini_api_key.strip():
        logger.info("Using single GEMINI_API_KEY from settings (backward compat)")
        _pool = GeminiKeyPool([settings.gemini_api_key.strip()])
        return _pool

    raise ValueError(
        "No Gemini API keys found. Provide keys via:\n"
        "  1. api_env file (one key per line) at project root or /etc/secrets/api_env\n"
        "  2. GEMINI_API_KEYS environment variable (comma-separated)\n"
        "  3. GEMINI_API_KEY environment variable (single key, legacy)"
    )
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
pytest tests/test_api_key_pool_env.py -v
```

Expected: 5 passed.

- [ ] **Step 5: Run the full test suite to confirm no regressions**

```bash
pytest -q
```

Expected: 305+ passed, 0 failed (any new tests added are additive).

- [ ] **Step 6: Commit**

```bash
git add website/features/api_key_switching/__init__.py tests/test_api_key_pool_env.py
git commit -m "feat(key-pool): add GEMINI_API_KEYS env var fallback for non-file deploys"
```

---

## Task 2: Lazy-import refactor in `website/core/pipeline.py`

**Files:**
- Modify: `website/core/pipeline.py:13-17` (the eager imports)
- Test: `tests/test_pipeline_lazy_imports.py` (new)

**Context:** Currently, `from telegram_bot.pipeline.summarizer import GeminiSummarizer, build_tag_list`, `from telegram_bot.sources import get_extractor`, and `from telegram_bot.sources.registry import detect_source_type` are all imported at module level. This drags `google-genai`, `trafilatura`, `lxml`, `praw`, `yt-dlp`, and the entire extractor plugin registry into memory the moment `website.core.pipeline` is touched — which happens at FastAPI startup. We want these imports moved inside `summarize_url()` so the cold-start RSS is dramatically lower.

- [ ] **Step 1: Write the failing test**

Create `tests/test_pipeline_lazy_imports.py`:

```python
"""Verify website.core.pipeline does NOT eagerly import heavy modules."""
from __future__ import annotations

import sys

import pytest


HEAVY_MODULES = [
    "telegram_bot.pipeline.summarizer",
    "telegram_bot.sources",
    "telegram_bot.sources.registry",
    "google.genai",
    "trafilatura",
    "yt_dlp",
    "praw",
]


def test_pipeline_module_does_not_import_heavy_deps():
    """Importing website.core.pipeline must not pull in heavy modules."""
    # Drop any pre-existing imports of heavy deps so we measure fresh
    for mod_name in HEAVY_MODULES + ["website.core.pipeline"]:
        sys.modules.pop(mod_name, None)
        # Also drop any submodules so a fresh import is forced
        for k in list(sys.modules.keys()):
            if k.startswith(mod_name + "."):
                sys.modules.pop(k, None)

    # Import the module under test
    import website.core.pipeline  # noqa: F401

    # None of the heavy modules should now be in sys.modules
    leaked = [m for m in HEAVY_MODULES if m in sys.modules]
    assert leaked == [], (
        f"website.core.pipeline eagerly imported: {leaked}. "
        f"Move these imports inside summarize_url()."
    )


def test_summarize_url_is_still_callable_after_lazy_refactor():
    """The lazy refactor must not break the public symbol."""
    import website.core.pipeline
    assert hasattr(website.core.pipeline, "summarize_url")
    assert callable(website.core.pipeline.summarize_url)
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
pytest tests/test_pipeline_lazy_imports.py -v
```

Expected: `test_pipeline_module_does_not_import_heavy_deps` FAILS — `leaked` is non-empty (likely contains `telegram_bot.pipeline.summarizer`, `telegram_bot.sources`, `trafilatura`, etc).

- [ ] **Step 3: Move the imports inside `summarize_url()`**

Edit `website/core/pipeline.py`. The full new file:

```python
"""Web-adapted pipeline wrapper.

Reuses the existing extraction and summarization pipeline but returns
structured data instead of sending Telegram messages.  Does NOT write
notes to disk or update the duplicate store — web requests are stateless.

All heavy imports (Gemini SDK, trafilatura, extractors) are lazy-loaded
inside summarize_url() so module-level import is cheap and FastAPI cold
start stays fast.
"""

from __future__ import annotations

import logging

from telegram_bot.config.settings import get_settings
from telegram_bot.utils.url_utils import normalize_url, resolve_redirects

logger = logging.getLogger("website.pipeline")


async def summarize_url(url: str) -> dict:
    """Run the extraction + summarization pipeline for a URL.

    Returns a dict with title, summary, brief_summary, tags, source_type,
    source_url, one_line_summary, and metadata about the processing.
    """
    # Lazy imports — keep module load cheap
    from telegram_bot.pipeline.summarizer import GeminiSummarizer, build_tag_list
    from telegram_bot.sources import get_extractor
    from telegram_bot.sources.registry import detect_source_type

    settings = get_settings()

    # Phase 1: resolve redirects
    logger.info("Web pipeline — resolving: %s", url)
    resolved = await resolve_redirects(url)

    # Phase 2: normalize
    normalized = normalize_url(resolved)

    # Phase 3: detect source type
    source_type = detect_source_type(normalized)
    logger.info("Web pipeline — detected source: %s", source_type.value)

    # Phase 4: extract content
    extractor = get_extractor(source_type, settings)
    extracted = await extractor.extract(normalized)
    logger.info(
        "Web pipeline — extracted: '%s' (%d chars)",
        extracted.title,
        len(extracted.body),
    )

    # Phase 5: summarize via Gemini
    summarizer = GeminiSummarizer(
        model_name=settings.model_name,
    )
    result = await summarizer.summarize(extracted)

    # Phase 6: build tags
    tags = build_tag_list(source_type, result.tags)
    if result.is_raw_fallback:
        tags = [t for t in tags if not t.startswith("status/")]
        tags.append("status/Raw")

    return {
        "title": extracted.title,
        "summary": result.summary,
        "brief_summary": result.brief_summary,
        "tags": tags,
        "source_type": source_type.value,
        "source_url": normalized,
        "one_line_summary": result.one_line_summary,
        "is_raw_fallback": result.is_raw_fallback,
        "tokens_used": result.tokens_used,
        "latency_ms": result.latency_ms,
        "metadata": extracted.metadata,
    }
```

Note: `from dataclasses import asdict` was unused; removed. `SourceType` was imported but unused at module level (only the `.value` accessor on a returned enum is used); removed.

- [ ] **Step 4: Run the test to verify it passes**

```bash
pytest tests/test_pipeline_lazy_imports.py -v
```

Expected: 2 passed.

- [ ] **Step 5: Run the full test suite to confirm no regressions**

```bash
pytest -q
```

Expected: all green. Pay attention to any test that imports `website.core.pipeline` directly or via `website.api.routes` — they should still work because the symbols are resolved when `summarize_url()` runs, not at import time.

- [ ] **Step 6: Commit**

```bash
git add website/core/pipeline.py tests/test_pipeline_lazy_imports.py
git commit -m "perf(pipeline): lazy-import gemini, trafilatura, extractors for fast cold start"
```

---

## Task 3: Lazy-import refactor in `nexus/service/persist.py`

**Files:**
- Modify: `website/experimental_features/nexus/service/persist.py:17` (eager import line)
- Test: `tests/test_persist_lazy_imports.py` (new)

**Context:** `from website.features.kg_features.embeddings import find_similar_nodes, generate_embedding` is currently at module top. This pulls in `numpy`, the embedding model code, and Gemini's embedding client at the moment any code touches the Nexus persist module. The two functions are only called inside `persist_summarized_result()` (lines 353 and 377), so they can move there.

- [ ] **Step 1: Write the failing test**

Create `tests/test_persist_lazy_imports.py`:

```python
"""Verify nexus persist does NOT eagerly import the embeddings module."""
from __future__ import annotations

import sys


HEAVY = "website.features.kg_features.embeddings"
TARGET = "website.experimental_features.nexus.service.persist"


def test_persist_module_does_not_import_embeddings():
    """Importing the persist module must not pull in kg_features.embeddings."""
    # Drop any cached imports
    for k in list(sys.modules.keys()):
        if k == HEAVY or k.startswith(HEAVY + ".") or k == TARGET:
            sys.modules.pop(k, None)

    import website.experimental_features.nexus.service.persist  # noqa: F401

    assert HEAVY not in sys.modules, (
        f"{TARGET} eagerly imported {HEAVY}. "
        "Move find_similar_nodes / generate_embedding imports inside "
        "persist_summarized_result()."
    )


def test_persist_summarized_result_is_still_exported():
    import website.experimental_features.nexus.service.persist as mod
    assert hasattr(mod, "persist_summarized_result")
    assert callable(mod.persist_summarized_result)
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
pytest tests/test_persist_lazy_imports.py -v
```

Expected: `test_persist_module_does_not_import_embeddings` FAILS — embeddings module is in `sys.modules`.

- [ ] **Step 3: Move the import inside the function**

Edit `website/experimental_features/nexus/service/persist.py`:

1. Delete line 17: `from website.features.kg_features.embeddings import find_similar_nodes, generate_embedding`
2. Inside `persist_summarized_result()`, add the lazy import on the first line of the function body:

Find this in `persist_summarized_result()`:

```python
async def persist_summarized_result(
    result: dict[str, Any],
    *,
    user_sub: str | None = None,
    captured_on: date | None = None,
) -> PersistenceOutcome:
    """Persist a summarize result using the same KG behavior as ``/api/summarize``."""

    payload = dict(result)
```

Replace it with:

```python
async def persist_summarized_result(
    result: dict[str, Any],
    *,
    user_sub: str | None = None,
    captured_on: date | None = None,
) -> PersistenceOutcome:
    """Persist a summarize result using the same KG behavior as ``/api/summarize``."""
    # Lazy imports — keep module load cheap by deferring numpy + embedding model
    from website.features.kg_features.embeddings import (
        find_similar_nodes,
        generate_embedding,
    )

    payload = dict(result)
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
pytest tests/test_persist_lazy_imports.py -v
```

Expected: 2 passed.

- [ ] **Step 5: Run the full suite to confirm no regressions**

```bash
pytest -q
```

Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add website/experimental_features/nexus/service/persist.py tests/test_persist_lazy_imports.py
git commit -m "perf(nexus): lazy-import embeddings to keep persist module load cheap"
```

---

## Task 4: Rename Telegram webhook path to `/telegram/webhook`

**Files:**
- Modify: `telegram_bot/main.py:131-176` (webhook URL derivation + route registration)
- Test: `tests/test_telegram_webhook_path.py` (new)

**Context:** The current code already uses `/webhook` (not the bot token in the path) and validates `X-Telegram-Bot-Api-Secret-Token`. The spec calls for `/telegram/webhook` for namespacing clarity (so a future API like `/api/webhook` for some other surface doesn't collide). This is a near-trivial rename touching two lines, plus adjusting the `setWebhook` call site.

- [ ] **Step 1: Write the failing test**

Create `tests/test_telegram_webhook_path.py`:

```python
"""Verify the Telegram webhook is mounted at /telegram/webhook (not /webhook)."""
from __future__ import annotations

import inspect

import telegram_bot.main as main_mod


def test_run_webhook_uses_namespaced_path():
    """The webhook path must be /telegram/webhook for namespace clarity."""
    src = inspect.getsource(main_mod._run_webhook)
    # New canonical path
    assert "/telegram/webhook" in src, (
        "telegram_bot.main._run_webhook must mount the webhook at /telegram/webhook"
    )
    # Old bare path must be gone
    assert '"/webhook"' not in src, (
        "Found bare '/webhook' string in _run_webhook. "
        "Update both the route registration and the setWebhook URL."
    )
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
pytest tests/test_telegram_webhook_path.py -v
```

Expected: FAIL — `/telegram/webhook` not found in source.

- [ ] **Step 3: Update both the URL derivation and the route registration**

Edit `telegram_bot/main.py`. In `_run_webhook()`, find these two locations and update them:

**Location A** (around line 132-138, inside `lifespan`):

```python
import urllib.parse as _urlparse
_parsed = _urlparse.urlparse(settings.webhook_url)
webhook_url = f"{_parsed.scheme}://{_parsed.netloc}/webhook"
await ptb_app.bot.set_webhook(
    url=webhook_url,
    secret_token=settings.webhook_secret or None,
)
```

Replace with:

```python
import urllib.parse as _urlparse
_parsed = _urlparse.urlparse(settings.webhook_url)
webhook_url = f"{_parsed.scheme}://{_parsed.netloc}/telegram/webhook"
await ptb_app.bot.set_webhook(
    url=webhook_url,
    secret_token=settings.webhook_secret or None,
)
```

**Location B** (around line 176, the route insertion):

```python
web_app.routes.insert(0, Route("/webhook", _telegram_webhook, methods=["POST"]))
```

Replace with:

```python
web_app.routes.insert(0, Route("/telegram/webhook", _telegram_webhook, methods=["POST"]))
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
pytest tests/test_telegram_webhook_path.py -v
```

Expected: 1 passed.

- [ ] **Step 5: Run the full test suite to confirm no regressions**

```bash
pytest -q
```

Expected: all green. Note: tests that don't mock `_run_webhook` won't trip on this; only the test we just wrote inspects the source.

- [ ] **Step 6: Commit**

```bash
git add telegram_bot/main.py tests/test_telegram_webhook_path.py
git commit -m "refactor(bot): namespace telegram webhook at /telegram/webhook"
```

---

## Task 5: Add `NEXUS_ENABLED` feature flag to `website/app.py`

**Files:**
- Modify: `website/app.py:17, 74, 157-164` (router include + route)
- Test: `tests/test_nexus_feature_flag.py` (new)

**Context:** The spec calls for a `NEXUS_ENABLED` env var that defaults to `true` so production behavior is unchanged, but exists as an emergency kill-switch without a redeploy. When `false`, the nexus router is not included and `/home/nexus` returns 404.

- [ ] **Step 1: Write the failing test**

Create `tests/test_nexus_feature_flag.py`:

```python
"""Verify NEXUS_ENABLED env var gates the nexus router and /home/nexus route."""
from __future__ import annotations

from fastapi.testclient import TestClient


def _build_app_with_nexus(monkeypatch, *, enabled: bool):
    """Build a fresh FastAPI app with NEXUS_ENABLED set."""
    monkeypatch.setenv("NEXUS_ENABLED", "true" if enabled else "false")
    # Force re-import of website.app so create_app reads fresh env
    import importlib
    import website.app as app_mod
    importlib.reload(app_mod)
    return app_mod.create_app()


def test_nexus_enabled_default_includes_route(monkeypatch):
    """With NEXUS_ENABLED unset (default true), /home/nexus should be reachable."""
    monkeypatch.delenv("NEXUS_ENABLED", raising=False)
    import importlib
    import website.app as app_mod
    importlib.reload(app_mod)
    app = app_mod.create_app()

    paths = {route.path for route in app.routes}
    assert "/home/nexus" in paths, "/home/nexus should be registered when NEXUS_ENABLED is unset"


def test_nexus_enabled_true_includes_route(monkeypatch):
    app = _build_app_with_nexus(monkeypatch, enabled=True)
    paths = {route.path for route in app.routes}
    assert "/home/nexus" in paths


def test_nexus_disabled_excludes_route(monkeypatch):
    app = _build_app_with_nexus(monkeypatch, enabled=False)
    paths = {route.path for route in app.routes}
    assert "/home/nexus" not in paths, "/home/nexus must not be registered when NEXUS_ENABLED=false"
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
pytest tests/test_nexus_feature_flag.py -v
```

Expected: `test_nexus_disabled_excludes_route` FAILS because `/home/nexus` is registered unconditionally today.

- [ ] **Step 3: Add the `NEXUS_ENABLED` gate to `website/app.py`**

Edit `website/app.py`:

1. At the top of the file, add `import os` if not already imported.
2. Inside `create_app()`, find the line `app.include_router(nexus_router)` (around line 74) and the `/home/nexus` route definition (around lines 157-164). Wrap both in a single feature flag check.

Replace the existing `app.include_router(nexus_router)` line with:

```python
    # Nexus is feature-flagged: default ON in production, OFF only as emergency kill-switch
    nexus_enabled = os.getenv("NEXUS_ENABLED", "true").strip().lower() == "true"
    if nexus_enabled:
        app.include_router(nexus_router)
```

Then find the `/home/nexus` route definition:

```python
    @app.get("/home/nexus")
    async def home_nexus(request: Request):
        if _is_mobile(request):
            return RedirectResponse(url="/m/", status_code=302)
        nexus_index = NEXUS_DIR / "index.html"
        if not nexus_index.exists():
            raise HTTPException(status_code=503, detail="Nexus UI assets are not available")
        return FileResponse(str(nexus_index))
```

Wrap it in the same flag:

```python
    if nexus_enabled:
        @app.get("/home/nexus")
        async def home_nexus(request: Request):
            if _is_mobile(request):
                return RedirectResponse(url="/m/", status_code=302)
            nexus_index = NEXUS_DIR / "index.html"
            if not nexus_index.exists():
                raise HTTPException(status_code=503, detail="Nexus UI assets are not available")
            return FileResponse(str(nexus_index))
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
pytest tests/test_nexus_feature_flag.py -v
```

Expected: 3 passed.

- [ ] **Step 5: Run the full test suite to confirm no regressions**

```bash
pytest -q
```

Expected: all green. The default-on behavior preserves prod parity.

- [ ] **Step 6: Commit**

```bash
git add website/app.py tests/test_nexus_feature_flag.py
git commit -m "feat(nexus): add NEXUS_ENABLED feature flag (default on)"
```

---

# Phase 2: Container Packaging

---

## Task 6: Split `requirements.txt` into runtime + dev

**Files:**
- Modify: `ops/requirements.txt`
- Create: `ops/requirements-dev.txt`

**Context:** The current `requirements.txt` includes `pytest`, `pytest-asyncio`, and `pytest-httpx`. These should not ship in the production Docker image. Splitting them out shrinks the image by ~10 MB and reduces attack surface.

- [ ] **Step 1: Write the runtime-only `ops/requirements.txt`**

Replace the entire file content with:

```text
# Telegram bot framework
python-telegram-bot>=21.0

# Settings / config management
pydantic-settings[yaml]>=2.0

# HTTP client (async, for redirect resolution and web scraping)
httpx>=0.28

# HTML parsing
beautifulsoup4>=4.12

# Article content extraction (readability-style)
trafilatura>=2.0

# Reddit API
praw>=7.0

# Google Gemini API
google-genai>=1.0
aiohttp>=3.10

# YouTube transcript extraction
youtube-transcript-api>=1.0

# YouTube metadata and audio (for yt-dlp based fallbacks)
yt-dlp>=2024.0

# Web frontend
fastapi>=0.115
uvicorn>=0.34

# Supabase (multi-user knowledge graph storage)
supabase>=2.0

# JWT validation (Supabase Auth token verification)
PyJWT>=2.8.0

# Encrypted Nexus OAuth token storage (Fernet)
cryptography>=43.0

# Graph algorithms (PageRank, community detection, centrality)
networkx>=3.2
scipy>=1.12

# Vector normalization for MRL-truncated embeddings
numpy>=1.26
```

- [ ] **Step 2: Create `ops/requirements-dev.txt`**

```text
# Development & testing dependencies — NOT installed into the production image.
# Install locally with: pip install -r ops/requirements.txt -r ops/requirements-dev.txt

-r requirements.txt

# Testing
pytest>=9.0
pytest-asyncio>=0.23
pytest-httpx>=0.30
```

- [ ] **Step 3: Verify both files install cleanly in a fresh venv**

```bash
python -m venv /tmp/zk-venv-test
/tmp/zk-venv-test/bin/pip install -r ops/requirements-dev.txt
```

Expected: clean install, no errors. (On Windows use `python -m venv $env:TEMP\zk-venv-test` and the equivalent path.)

- [ ] **Step 4: Run pytest using the new dev file**

```bash
pytest -q
```

Expected: all green.

- [ ] **Step 5: Commit**

```bash
git add ops/requirements.txt ops/requirements-dev.txt
git commit -m "chore(deps): split runtime and dev requirements files"
```

---

## Task 7: Rewrite `ops/Dockerfile` (multi-stage, tini, non-root, healthcheck)

**Files:**
- Modify: `ops/Dockerfile`

**Context:** The current Dockerfile is a workable multi-stage build but is missing tini (proper PID 1 for SIGTERM forwarding), non-root user, healthcheck, and OCI labels. We rewrite it to match §7.1 of the spec.

- [ ] **Step 1: Replace the entire `ops/Dockerfile` content**

```dockerfile
# syntax=docker/dockerfile:1.7

# ─── Stage 1: builder ────────────────────────────────────────────────────────
FROM python:3.12-slim AS builder

WORKDIR /app

# Install build deps for any wheels that need to compile
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

# Create a clean virtual env we can copy wholesale to the runtime stage
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Install runtime requirements only (not dev)
COPY ops/requirements.txt /tmp/requirements.txt
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --no-cache-dir -r /tmp/requirements.txt

# Pre-compile site-packages to .pyc for faster cold start
RUN python -m compileall -q /opt/venv

# ─── Stage 2: runtime ────────────────────────────────────────────────────────
FROM python:3.12-slim AS runtime

# OCI labels — populated at build time by --build-arg
ARG GIT_SHA=unknown
ARG BUILD_DATE=unknown
LABEL org.opencontainers.image.title="zettelkasten-kg-website" \
      org.opencontainers.image.description="Zettelkasten Capture Bot + Web UI" \
      org.opencontainers.image.source="https://github.com/chintanmehta21/Zettelkasten_KG" \
      org.opencontainers.image.revision="${GIT_SHA}" \
      org.opencontainers.image.created="${BUILD_DATE}" \
      org.opencontainers.image.licenses="MIT"

# Minimal runtime dependencies: ca-certs (for HTTPS), tini (proper PID 1),
# curl (for healthcheck and manual debugging).
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates tini curl \
    && rm -rf /var/lib/apt/lists/*

# Create a non-root user for runtime
RUN groupadd --gid 1000 appuser \
    && useradd  --uid 1000 --gid appuser --create-home --shell /bin/bash appuser

WORKDIR /app

# Copy the venv from the builder stage
COPY --from=builder /opt/venv /opt/venv

# Copy application code (chowned to appuser)
COPY --chown=appuser:appuser telegram_bot/ telegram_bot/
COPY --chown=appuser:appuser website/      website/
COPY --chown=appuser:appuser run.py        ./
COPY --chown=appuser:appuser pyproject.toml ./

# Pre-create writable directories the app may use at runtime, owned by appuser
RUN mkdir -p /app/kg_output /app/bot_data \
    && chown -R appuser:appuser /app/kg_output /app/bot_data

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    WEBHOOK_PORT=10000

EXPOSE 10000

USER appuser

HEALTHCHECK --interval=15s --timeout=3s --start-period=10s --retries=3 \
    CMD curl --silent --show-error --fail --max-time 2 http://127.0.0.1:10000/api/health || exit 1

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["python", "run.py"]
```

- [ ] **Step 2: Verify Dockerfile syntax with `docker build --check` (BuildKit)**

```bash
docker build --check -f ops/Dockerfile .
```

Expected: no errors. (If `--check` is unavailable on your Docker version, skip — Step 3 catches build errors.)

- [ ] **Step 3: Commit**

```bash
git add ops/Dockerfile
git commit -m "build(docker): rewrite Dockerfile with tini, non-root user, healthcheck, oci labels"
```

---

## Task 8: Create `.dockerignore` to shrink build context

**Files:**
- Create: `.dockerignore` at repo root

**Context:** Without a `.dockerignore`, every `docker build` ships the entire repo (including `.git`, tests, docs, worktrees) to the daemon. We want a build context under 10 MB.

- [ ] **Step 1: Create `.dockerignore` at the repo root**

```text
# Version control
.git
.gitignore
.gitattributes

# Docs and dev metadata (not needed at runtime)
docs/
*.md
!README.md

# CI / GitHub config (only needed for CI itself, not in image)
.github/

# Tests are not shipped in the production image
tests/

# Local Python venvs and caches
.venv/
venv/
env/
__pycache__/
*.pyc
*.pyo
*.pyd
.Python
.pytest_cache/
.mypy_cache/
.ruff_cache/
.tox/
.coverage
.coverage.*
htmlcov/
*.cover

# Editor / IDE
.vscode/
.idea/
*.swp
*.swo
.DS_Store
Thumbs.db

# Worktrees and Claude Code metadata
.worktrees/
.claude/
.code-build/

# Local data dirs that should never ship in the image
kg_output/
bot_data/
*.log
logs/

# Local environment files
.env
.env.*
ops/api_env
website/features/api_key_switching/api_env
supabase/.env

# Node tooling (if ever introduced)
node_modules/
```

- [ ] **Step 2: Verify the build context size**

```bash
docker build -f ops/Dockerfile --no-cache --progress=plain -t zettelkasten-kg-website:test . 2>&1 | grep "transferring context"
```

Expected: build context size under 10 MB (look for a line like `transferring context: 8.42MB`).

- [ ] **Step 3: Commit**

```bash
git add .dockerignore
git commit -m "build(docker): add .dockerignore to shrink build context under 10MB"
```

---

## Task 9: Build the image locally and verify size + healthcheck + non-root

**Files:** none modified (verification only)

- [ ] **Step 1: Build the image with both build args**

```bash
docker build \
  -f ops/Dockerfile \
  --build-arg GIT_SHA="$(git rev-parse HEAD)" \
  --build-arg BUILD_DATE="$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  -t zettelkasten-kg-website:test \
  .
```

Expected: build succeeds, final stage tagged as `zettelkasten-kg-website:test`.

- [ ] **Step 2: Inspect image size**

```bash
docker images zettelkasten-kg-website:test --format "{{.Size}}"
```

Expected: under 750 MB uncompressed (compressed will be ≤ 550 MB on GHCR after gzip).

- [ ] **Step 3: Verify the image runs as non-root**

```bash
docker run --rm --entrypoint id zettelkasten-kg-website:test
```

Expected output:
```
uid=1000(appuser) gid=1000(appuser) groups=1000(appuser)
```

- [ ] **Step 4: Verify tini is PID 1**

```bash
docker run --rm --entrypoint sh zettelkasten-kg-website:test -c "ps -p 1 -o comm="
```

Expected: outputs `tini` (or path containing `tini`).

- [ ] **Step 5: Smoke-test the healthcheck endpoint**

Run the container in the background. Note: this requires real env vars (or no-op stubs). For a smoke test we just need the FastAPI app to bind the port; we don't need bot tokens to be valid.

```bash
docker run -d \
  --name zk-smoketest \
  -p 10000:10000 \
  -e TELEGRAM_BOT_TOKEN=000:smoke \
  -e ALLOWED_CHAT_ID=0 \
  -e GEMINI_API_KEY=smoke \
  -e WEBHOOK_MODE=true \
  -e WEBHOOK_URL=http://localhost:10000 \
  -e WEBHOOK_PORT=10000 \
  zettelkasten-kg-website:test

sleep 8
curl -fsS http://127.0.0.1:10000/api/health
```

Expected: `{"status":"ok"}` — sub-second response.

- [ ] **Step 6: Verify the container's HEALTHCHECK status reaches `healthy`**

```bash
sleep 20
docker inspect --format '{{.State.Health.Status}}' zk-smoketest
```

Expected: `healthy`.

- [ ] **Step 7: Verify SIGTERM is propagated by tini**

```bash
time docker stop zk-smoketest
```

Expected: stops within 2 seconds (tini forwards SIGTERM, uvicorn drains gracefully). If it takes 10s, SIGTERM is not being forwarded — investigate.

- [ ] **Step 8: Cleanup**

```bash
docker rm -f zk-smoketest
```

- [ ] **Step 9: Commit (no file changes — checkpoint commit only if you added a verification log)**

This task is verification-only. No commit. Move to Task 10.

---

## Task 10: Verify build cache reuse

**Files:** none

**Context:** A code-only change (no `requirements.txt` change) should NOT re-install Python deps. We verify the layer ordering is correct.

- [ ] **Step 1: Touch a Python file to force a rebuild of the code layer only**

```bash
touch website/app.py
docker build -f ops/Dockerfile -t zettelkasten-kg-website:test . 2>&1 | tail -25
```

Expected: build output shows `CACHED` for the `pip install` layer and re-runs only the code `COPY` and downstream layers.

- [ ] **Step 2: Revert the touch**

```bash
git checkout website/app.py 2>/dev/null || git restore website/app.py
```

- [ ] **Step 3: Done — no commit**

---

# Phase 3: Caddy + Compose Stack

---

## Task 11: Create Caddyfile and upstream snippet

**Files:**
- Create: `ops/caddy/Caddyfile`
- Create: `ops/caddy/upstream.snippet`

**Context:** Caddy terminates TLS for `zettelkasten.in` (apex canonical), 301-redirects `www.zettelkasten.in`, sets security headers, caches static assets, gzip+zstd encodes, and reverse-proxies to whichever color is live based on the contents of `upstream.snippet`. The snippet is the **only** file that changes during a deploy; everything else is stable.

- [ ] **Step 1: Create `ops/caddy/upstream.snippet`**

```caddyfile
# This file is rewritten by deploy.sh to point at blue (10000) or green (10001).
# Caddy is reloaded gracefully when this changes — zero dropped connections.
reverse_proxy zettelkasten-blue:10000
```

- [ ] **Step 2: Create `ops/caddy/Caddyfile`**

```caddyfile
{
    # ACME account email (Let's Encrypt notifications only)
    email chintanoninternet@gmail.com

    # Listen on both IPv4 and IPv6
    default_bind tcp4/0.0.0.0 tcp6/[::]
}

# ─── www → apex 301 redirect ─────────────────────────────────────────────────
www.zettelkasten.in {
    redir https://zettelkasten.in{uri} permanent
}

# ─── apex (canonical) ────────────────────────────────────────────────────────
zettelkasten.in {
    encode zstd gzip

    # Security headers (applied to every response)
    header {
        Strict-Transport-Security "max-age=63072000; includeSubDomains; preload"
        X-Content-Type-Options "nosniff"
        X-Frame-Options "DENY"
        Referrer-Policy "strict-origin-when-cross-origin"
        Permissions-Policy "geolocation=(), camera=(), microphone=()"
        # Remove the default Server: Caddy banner
        -Server
    }

    # Long-lived cache for hashed static assets
    @static {
        path /css/* /js/*
        path /m/css/* /m/js/*
        path /kg/css/* /kg/js/*
        path /home/css/* /home/js/*
        path /home/zettels/css/* /home/zettels/js/*
        path /home/nexus/css/* /home/nexus/js/*
        path /about/css/* /about/js/*
        path /pricing/css/* /pricing/js/*
        path /auth/css/* /auth/js/*
        path /artifacts/*
        path /browser-cache/js/*
    }
    header @static Cache-Control "public, max-age=31536000, immutable"

    # 30s cache for the public KG endpoint (matches in-process TTL)
    @api_graph path /api/graph
    header @api_graph Cache-Control "public, max-age=30"

    # Skip access logging for the Telegram webhook (still proxied normally,
    # but the path is not written to disk to avoid leaking the URI in case
    # we ever change schemes).
    @telegram path /telegram/webhook
    log_skip @telegram

    # Application reverse proxy — upstream is hot-swappable
    import /etc/caddy/upstream.snippet

    # Access log (JSON, separate file for logrotate)
    log {
        output file /var/log/caddy/access.log {
            roll_size 10MiB
            roll_keep 5
            roll_keep_for 168h
        }
        format json
    }
}
```

- [ ] **Step 3: Verify Caddyfile syntax with the official linter**

```bash
docker run --rm \
  -v "$(pwd)/ops/caddy/Caddyfile:/etc/caddy/Caddyfile:ro" \
  -v "$(pwd)/ops/caddy/upstream.snippet:/etc/caddy/upstream.snippet:ro" \
  caddy:2 caddy validate --config /etc/caddy/Caddyfile
```

Expected: `Valid configuration`.

- [ ] **Step 4: Commit**

```bash
git add ops/caddy/Caddyfile ops/caddy/upstream.snippet
git commit -m "feat(caddy): add reverse proxy config with hot-swap upstream snippet"
```

---

## Task 12: Create blue and green compose files

**Files:**
- Create: `ops/docker-compose.blue.yml`
- Create: `ops/docker-compose.green.yml`

**Context:** Two near-identical compose files, one per color. Each defines a single FastAPI container on its own host port (10000 / 10001), with mem limits, healthchecks, shared bind mounts, hardening, and the shared external network `zettelnet`.

- [ ] **Step 1: Create `ops/docker-compose.blue.yml`**

```yaml
services:
  zettelkasten-blue:
    image: ghcr.io/chintanmehta21/zettelkasten-kg-website:${IMAGE_TAG:-latest}
    container_name: zettelkasten-blue
    hostname: zettelkasten-blue
    restart: unless-stopped
    env_file:
      - /opt/zettelkasten/compose/.env
    environment:
      WEBHOOK_PORT: "10000"
      NEXUS_ENABLED: "true"
    ports:
      - "127.0.0.1:10000:10000"
    networks:
      - zettelnet
    volumes:
      - /opt/zettelkasten/data/kg_output:/app/kg_output
      - /opt/zettelkasten/data/bot_data:/app/bot_data
    mem_limit: 768m
    memswap_limit: 768m
    pids_limit: 512
    stop_grace_period: 20s
    read_only: true
    tmpfs:
      - /tmp:size=64m
    cap_drop:
      - ALL
    security_opt:
      - no-new-privileges:true
    logging:
      driver: json-file
      options:
        max-size: "10m"
        max-file: "3"
    healthcheck:
      test: ["CMD", "curl", "--silent", "--fail", "--max-time", "2", "http://127.0.0.1:10000/api/health"]
      interval: 15s
      timeout: 3s
      start_period: 10s
      retries: 3

networks:
  zettelnet:
    external: true
```

- [ ] **Step 2: Create `ops/docker-compose.green.yml`**

Identical to blue except for the port and container/host name:

```yaml
services:
  zettelkasten-green:
    image: ghcr.io/chintanmehta21/zettelkasten-kg-website:${IMAGE_TAG:-latest}
    container_name: zettelkasten-green
    hostname: zettelkasten-green
    restart: unless-stopped
    env_file:
      - /opt/zettelkasten/compose/.env
    environment:
      WEBHOOK_PORT: "10000"
      NEXUS_ENABLED: "true"
    ports:
      - "127.0.0.1:10001:10000"
    networks:
      - zettelnet
    volumes:
      - /opt/zettelkasten/data/kg_output:/app/kg_output
      - /opt/zettelkasten/data/bot_data:/app/bot_data
    mem_limit: 768m
    memswap_limit: 768m
    pids_limit: 512
    stop_grace_period: 20s
    read_only: true
    tmpfs:
      - /tmp:size=64m
    cap_drop:
      - ALL
    security_opt:
      - no-new-privileges:true
    logging:
      driver: json-file
      options:
        max-size: "10m"
        max-file: "3"
    healthcheck:
      test: ["CMD", "curl", "--silent", "--fail", "--max-time", "2", "http://127.0.0.1:10000/api/health"]
      interval: 15s
      timeout: 3s
      start_period: 10s
      retries: 3

networks:
  zettelnet:
    external: true
```

Notes:
- `read_only: true` makes the container filesystem immutable except for `/tmp` (which is a 64 MB tmpfs).
- `cap_drop: [ALL]` removes all Linux capabilities — the container does not need any since it binds 10000 (unprivileged) and runs as UID 1000.
- The published port is bound to `127.0.0.1` only — Caddy reaches it via the docker network `zettelnet`, and it should never be reachable from the public internet.
- `IMAGE_TAG` defaults to `latest` but the deploy script always passes the explicit SHA.

- [ ] **Step 3: Lint with `docker compose config`**

```bash
docker compose -f ops/docker-compose.blue.yml config > /dev/null
docker compose -f ops/docker-compose.green.yml config > /dev/null
```

Expected: no output, exit code 0. (Errors here are typos.)

- [ ] **Step 4: Commit**

```bash
git add ops/docker-compose.blue.yml ops/docker-compose.green.yml
git commit -m "feat(compose): add blue and green app stack compose files"
```

---

## Task 13: Create Caddy compose file

**Files:**
- Create: `ops/docker-compose.caddy.yml`

- [ ] **Step 1: Create `ops/docker-compose.caddy.yml`**

```yaml
services:
  caddy:
    image: caddy:2
    container_name: caddy
    hostname: caddy
    restart: unless-stopped
    networks:
      - zettelnet
    ports:
      - "80:80"
      - "443:443"
      - "443:443/udp"  # HTTP/3 (QUIC)
    volumes:
      - /opt/zettelkasten/caddy/Caddyfile:/etc/caddy/Caddyfile:ro
      - /opt/zettelkasten/caddy/upstream.snippet:/etc/caddy/upstream.snippet:ro
      - /opt/zettelkasten/caddy/data:/data
      - /opt/zettelkasten/caddy/config:/config
      - /opt/zettelkasten/logs/caddy:/var/log/caddy
    mem_limit: 128m
    pids_limit: 256
    stop_grace_period: 10s
    cap_drop:
      - ALL
    cap_add:
      - NET_BIND_SERVICE
    security_opt:
      - no-new-privileges:true
    logging:
      driver: json-file
      options:
        max-size: "10m"
        max-file: "3"
    healthcheck:
      test: ["CMD", "wget", "--quiet", "--spider", "--no-check-certificate", "https://localhost/"]
      interval: 30s
      timeout: 5s
      start_period: 15s
      retries: 3

networks:
  zettelnet:
    external: true
```

Note: Caddy needs `NET_BIND_SERVICE` to bind ports 80/443 (privileged ports), even though the container itself is not privileged.

- [ ] **Step 2: Lint**

```bash
docker compose -f ops/docker-compose.caddy.yml config > /dev/null
```

Expected: no output, exit 0.

- [ ] **Step 3: Commit**

```bash
git add ops/docker-compose.caddy.yml
git commit -m "feat(compose): add caddy reverse proxy compose file"
```

---

## Task 14: Create `docker-compose.dev.yml` for hot-reload local dev

**Files:**
- Create: `ops/docker-compose.dev.yml`

**Context:** Lets the developer iterate on `website/` and `telegram_bot/` with hot-reload, no Caddy, no blue-green — just one container that mounts the source tree as a volume and runs uvicorn `--reload`.

- [ ] **Step 1: Create `ops/docker-compose.dev.yml`**

```yaml
# Development compose file — hot-reload, no Caddy, no blue-green.
# Use: docker compose -f ops/docker-compose.dev.yml up --build
#
# Mounts source code as volumes so edits trigger uvicorn --reload.
# Reads env vars from a local .env file at the repo root (gitignored).

services:
  zettelkasten-dev:
    build:
      context: ..
      dockerfile: ops/Dockerfile
    image: zettelkasten-kg-website:dev
    container_name: zettelkasten-dev
    restart: "no"
    env_file:
      - ../.env
    environment:
      WEBHOOK_MODE: "true"
      WEBHOOK_PORT: "10000"
      WEBHOOK_URL: "http://localhost:10000"
      NEXUS_ENABLED: "true"
    ports:
      - "10000:10000"
    volumes:
      # Bind-mount source for hot-reload
      - ../website:/app/website
      - ../telegram_bot:/app/telegram_bot
      - ../run.py:/app/run.py:ro
      # Persistent dev data
      - dev-kg-output:/app/kg_output
      - dev-bot-data:/app/bot_data
    # Override CMD to enable uvicorn --reload directly (skips run.py)
    command:
      - python
      - -m
      - uvicorn
      - website.app:create_app
      - --factory
      - --host
      - 0.0.0.0
      - --port
      - "10000"
      - --reload
      - --reload-dir
      - /app/website
      - --reload-dir
      - /app/telegram_bot

volumes:
  dev-kg-output:
  dev-bot-data:
```

Note: in dev mode the reload command runs `website.app:create_app` directly via `--factory`, so the Telegram bot lifespan does not run (dev mode only exercises the web UI; for full bot dev use `python run.py` outside docker).

- [ ] **Step 2: Lint**

```bash
docker compose -f ops/docker-compose.dev.yml config > /dev/null
```

Expected: no output, exit 0.

- [ ] **Step 3: Commit**

```bash
git add ops/docker-compose.dev.yml
git commit -m "feat(compose): add dev hot-reload compose file"
```

---

## Task 15: Create `docker-compose.prod-local.yml` for strict prod parity

**Files:**
- Create: `ops/docker-compose.prod-local.yml`

**Context:** Lets the developer rehearse a full production stack on their laptop — Caddy + blue + green, all reading from local config — before pushing to the real droplet. This is the safety net before any production deploy.

- [ ] **Step 1: Create `ops/docker-compose.prod-local.yml`**

```yaml
# Strict prod-parity compose file — runs Caddy + blue + green locally.
# Use: docker compose -f ops/docker-compose.prod-local.yml up
#
# Mounts ops/caddy/ directly as the Caddy config so you can rehearse
# blue-green flips by editing ops/caddy/upstream.snippet and reloading.
#
# Requires either:
#   - Local image build: docker build -f ops/Dockerfile -t zettelkasten-kg-website:local .
#     Then set IMAGE=zettelkasten-kg-website:local before `up`.
#   - GHCR pull: `docker login ghcr.io` first, then default IMAGE works.
#
# Caddy listens on 80/443 locally — for hostname-based testing, add
# `127.0.0.1 zettelkasten.local` to /etc/hosts and visit https://zettelkasten.local
# (cert will be self-signed via Caddy's internal CA in this profile).

services:
  zettelkasten-blue:
    image: ${IMAGE:-zettelkasten-kg-website:local}
    container_name: zettelkasten-blue
    restart: unless-stopped
    env_file:
      - ../.env
    environment:
      WEBHOOK_PORT: "10000"
      NEXUS_ENABLED: "true"
    networks:
      - zettelnet
    volumes:
      - prodlocal-kg-output:/app/kg_output
      - prodlocal-bot-data:/app/bot_data
    mem_limit: 768m
    healthcheck:
      test: ["CMD", "curl", "--silent", "--fail", "--max-time", "2", "http://127.0.0.1:10000/api/health"]
      interval: 15s
      timeout: 3s
      start_period: 10s
      retries: 3

  zettelkasten-green:
    image: ${IMAGE:-zettelkasten-kg-website:local}
    container_name: zettelkasten-green
    restart: unless-stopped
    env_file:
      - ../.env
    environment:
      WEBHOOK_PORT: "10000"
      NEXUS_ENABLED: "true"
    networks:
      - zettelnet
    volumes:
      - prodlocal-kg-output:/app/kg_output
      - prodlocal-bot-data:/app/bot_data
    mem_limit: 768m
    healthcheck:
      test: ["CMD", "curl", "--silent", "--fail", "--max-time", "2", "http://127.0.0.1:10000/api/health"]
      interval: 15s
      timeout: 3s
      start_period: 10s
      retries: 3

  caddy:
    image: caddy:2
    container_name: caddy
    restart: unless-stopped
    networks:
      - zettelnet
    ports:
      - "80:80"
      - "443:443"
      - "443:443/udp"
    volumes:
      - ./caddy/Caddyfile.local:/etc/caddy/Caddyfile:ro
      - ./caddy/upstream.snippet:/etc/caddy/upstream.snippet:ro
      - prodlocal-caddy-data:/data
      - prodlocal-caddy-config:/config

volumes:
  prodlocal-kg-output:
  prodlocal-bot-data:
  prodlocal-caddy-data:
  prodlocal-caddy-config:

networks:
  zettelnet:
    driver: bridge
```

- [ ] **Step 2: Create `ops/caddy/Caddyfile.local` (self-signed local cert variant)**

```caddyfile
{
    # Use Caddy's internal CA for local self-signed certs
    local_certs
    auto_https disable_redirects
}

# Local hostname — requires `127.0.0.1 zettelkasten.local` in /etc/hosts
zettelkasten.local {
    tls internal
    encode zstd gzip
    import /etc/caddy/upstream.snippet
}
```

- [ ] **Step 3: Lint both**

```bash
docker compose -f ops/docker-compose.prod-local.yml config > /dev/null
docker run --rm \
  -v "$(pwd)/ops/caddy/Caddyfile.local:/etc/caddy/Caddyfile:ro" \
  -v "$(pwd)/ops/caddy/upstream.snippet:/etc/caddy/upstream.snippet:ro" \
  caddy:2 caddy validate --config /etc/caddy/Caddyfile
```

Expected: both succeed.

- [ ] **Step 4: Commit**

```bash
git add ops/docker-compose.prod-local.yml ops/caddy/Caddyfile.local
git commit -m "feat(compose): add prod-local rehearsal stack with self-signed caddy"
```

---

# Phase 4: Local Rehearsal

---

## Task 16: Run the prod-local stack end-to-end and rehearse a blue-green flip

**Files:** none modified (verification only)

**Context:** This is the rehearsal that proves the entire stack works on a laptop before any droplet is provisioned. If this works, the droplet deploy is mostly a copy-paste of the same files.

- [ ] **Step 1: Build the local image**

```bash
docker build \
  -f ops/Dockerfile \
  --build-arg GIT_SHA="$(git rev-parse HEAD)" \
  --build-arg BUILD_DATE="$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  -t zettelkasten-kg-website:local \
  .
```

Expected: builds cleanly.

- [ ] **Step 2: Add the local hostname to /etc/hosts**

```bash
# Linux/macOS:
echo "127.0.0.1 zettelkasten.local" | sudo tee -a /etc/hosts
# Windows (PowerShell as Administrator):
# Add-Content C:\Windows\System32\drivers\etc\hosts "127.0.0.1 zettelkasten.local"
```

- [ ] **Step 3: Make sure `.env` exists at repo root with sane stub values**

```bash
cat > .env <<'EOF'
TELEGRAM_BOT_TOKEN=000:smoke
ALLOWED_CHAT_ID=0
WEBHOOK_MODE=true
WEBHOOK_URL=https://zettelkasten.local
WEBHOOK_PORT=10000
WEBHOOK_SECRET=local-rehearsal-secret
GEMINI_API_KEY=smoke
NEXUS_ENABLED=true
EOF
```

- [ ] **Step 4: Bring up the stack**

```bash
IMAGE=zettelkasten-kg-website:local docker compose -f ops/docker-compose.prod-local.yml up -d
sleep 15
docker compose -f ops/docker-compose.prod-local.yml ps
```

Expected: `caddy`, `zettelkasten-blue`, `zettelkasten-green` all running and `(healthy)`.

- [ ] **Step 5: Verify Caddy serves the blue upstream**

```bash
curl -k --resolve zettelkasten.local:443:127.0.0.1 https://zettelkasten.local/api/health
```

Expected: `{"status":"ok"}` (the `-k` flag accepts the self-signed cert).

- [ ] **Step 6: Rehearse the blue-green flip**

```bash
# Edit upstream.snippet to point at green
sed -i 's/zettelkasten-blue:10000/zettelkasten-green:10000/' ops/caddy/upstream.snippet
docker exec caddy caddy reload --config /etc/caddy/Caddyfile
sleep 2
curl -k --resolve zettelkasten.local:443:127.0.0.1 https://zettelkasten.local/api/health
```

Expected: still returns `{"status":"ok"}`. Tail Caddy logs to confirm requests now route to `zettelkasten-green`:

```bash
docker logs caddy 2>&1 | tail -5
```

- [ ] **Step 7: Flip back to blue and reload**

```bash
sed -i 's/zettelkasten-green:10000/zettelkasten-blue:10000/' ops/caddy/upstream.snippet
docker exec caddy caddy reload --config /etc/caddy/Caddyfile
sleep 2
curl -k --resolve zettelkasten.local:443:127.0.0.1 https://zettelkasten.local/api/health
```

Expected: still 200.

- [ ] **Step 8: Tear down**

```bash
docker compose -f ops/docker-compose.prod-local.yml down -v
```

- [ ] **Step 9: Done — no commit (verification only)**

If anything in this task fails, do NOT proceed. The droplet deploy will fail in the same way. Fix locally first.

---

# Phase 5: Host Bootstrap Scripts

---

## Task 17: Create `ops/host/sysctl-zettelkasten.conf`

**Files:**
- Create: `ops/host/sysctl-zettelkasten.conf`

- [ ] **Step 1: Create the file**

```text
# /etc/sysctl.d/99-zettelkasten.conf
# Kernel tuning for the Zettelkasten Droplet — single-node FastAPI workload.

# Connection backlog
net.core.somaxconn = 4096
net.ipv4.tcp_max_syn_backlog = 4096

# Ephemeral port range — give the box plenty of outbound sockets
net.ipv4.ip_local_port_range = 1024 65535

# File descriptor ceiling
fs.file-max = 1048576

# Reduce swap pressure (we have a 1 GiB swapfile but want to use it sparingly)
vm.swappiness = 10

# IPv6 sanity
net.ipv6.conf.all.disable_ipv6 = 0
net.ipv6.conf.default.disable_ipv6 = 0
```

- [ ] **Step 2: Commit**

```bash
git add ops/host/sysctl-zettelkasten.conf
git commit -m "feat(host): add sysctl tuning config for the droplet"
```

---

## Task 18: Create `ops/host/bootstrap.sh`

**Files:**
- Create: `ops/host/bootstrap.sh`

**Context:** This is the one-shot script run as root on a fresh DO Docker 1-Click droplet to install everything else (UFW, fail2ban, swap, deploy user, sysctl, logrotate, systemd unit). It must be idempotent so it's safe to re-run.

- [ ] **Step 1: Create the file**

```bash
#!/usr/bin/env bash
# ops/host/bootstrap.sh
#
# One-shot droplet bootstrap. Safe to re-run (idempotent).
# Run as root on a fresh DO Docker 1-Click Ubuntu 22.04 droplet.
#
# Required environment variables:
#   DEPLOY_PUBKEY — the SSH public key (one line) for the deploy user

set -euo pipefail

if [[ $EUID -ne 0 ]]; then
    echo "Must run as root" >&2
    exit 1
fi

if [[ -z "${DEPLOY_PUBKEY:-}" ]]; then
    echo "DEPLOY_PUBKEY env var is required (the deploy user's SSH public key)" >&2
    exit 1
fi

echo "[bootstrap] Updating apt index and installing security packages…"
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y --no-install-recommends \
    ufw fail2ban unattended-upgrades apt-listchanges \
    logrotate curl ca-certificates jq

echo "[bootstrap] Configuring unattended-upgrades (security only, no reboot)…"
cat > /etc/apt/apt.conf.d/20auto-upgrades <<'EOF'
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";
APT::Periodic::AutocleanInterval "7";
EOF
cat > /etc/apt/apt.conf.d/50unattended-upgrades <<'EOF'
Unattended-Upgrade::Allowed-Origins {
    "${distro_id}:${distro_codename}-security";
    "${distro_id}ESMApps:${distro_codename}-apps-security";
    "${distro_id}ESM:${distro_codename}-infra-security";
};
Unattended-Upgrade::Automatic-Reboot "false";
Unattended-Upgrade::MinimalSteps "true";
Unattended-Upgrade::Mail "";
EOF

echo "[bootstrap] Configuring UFW…"
ufw --force reset
ufw default deny incoming
ufw default allow outgoing
ufw allow 22/tcp comment 'SSH'
ufw allow 80/tcp comment 'HTTP'
ufw allow 443/tcp comment 'HTTPS'
ufw allow 443/udp comment 'HTTP/3 QUIC'
ufw --force enable
ufw status verbose

echo "[bootstrap] Enabling fail2ban with sshd jail…"
systemctl enable --now fail2ban

echo "[bootstrap] Creating 1 GiB swapfile…"
if [[ ! -f /swapfile ]]; then
    fallocate -l 1G /swapfile
    chmod 600 /swapfile
    mkswap /swapfile
    swapon /swapfile
    grep -q '^/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi
sysctl -w vm.swappiness=10

echo "[bootstrap] Installing kernel tuning…"
install -m 0644 /opt/zettelkasten/repo-cache/ops/host/sysctl-zettelkasten.conf \
    /etc/sysctl.d/99-zettelkasten.conf
sysctl --system

echo "[bootstrap] Configuring file descriptor limits…"
cat > /etc/security/limits.d/zettelkasten.conf <<'EOF'
*    soft nofile 65535
*    hard nofile 65535
root soft nofile 65535
root hard nofile 65535
EOF

echo "[bootstrap] Creating deploy user…"
if ! id deploy &>/dev/null; then
    useradd --create-home --shell /bin/bash --groups docker deploy
fi
usermod -aG docker deploy
mkdir -p /home/deploy/.ssh
echo "$DEPLOY_PUBKEY" > /home/deploy/.ssh/authorized_keys
chmod 700 /home/deploy/.ssh
chmod 600 /home/deploy/.ssh/authorized_keys
chown -R deploy:deploy /home/deploy/.ssh

echo "[bootstrap] Hardening sshd (key-only, no root login)…"
cat > /etc/ssh/sshd_config.d/99-zettelkasten.conf <<'EOF'
PermitRootLogin no
PasswordAuthentication no
ChallengeResponseAuthentication no
KbdInteractiveAuthentication no
UsePAM yes
X11Forwarding no
PermitEmptyPasswords no
MaxAuthTries 3
ClientAliveInterval 300
ClientAliveCountMax 2
EOF
systemctl restart ssh

echo "[bootstrap] Creating /opt/zettelkasten directory tree…"
install -d -o deploy -g deploy -m 0755 \
    /opt/zettelkasten \
    /opt/zettelkasten/compose \
    /opt/zettelkasten/caddy \
    /opt/zettelkasten/caddy/data \
    /opt/zettelkasten/caddy/config \
    /opt/zettelkasten/data \
    /opt/zettelkasten/data/kg_output \
    /opt/zettelkasten/data/bot_data \
    /opt/zettelkasten/logs \
    /opt/zettelkasten/logs/caddy \
    /opt/zettelkasten/deploy

# Default the active color to blue
echo blue > /opt/zettelkasten/ACTIVE_COLOR
chown deploy:deploy /opt/zettelkasten/ACTIVE_COLOR

echo "[bootstrap] Creating shared Docker network…"
docker network inspect zettelnet >/dev/null 2>&1 || docker network create zettelnet

echo "[bootstrap] Installing logrotate config for Caddy logs…"
install -m 0644 /opt/zettelkasten/repo-cache/ops/host/logrotate-zettelkasten.conf \
    /etc/logrotate.d/zettelkasten

echo "[bootstrap] Installing systemd unit…"
install -m 0644 /opt/zettelkasten/repo-cache/ops/systemd/zettelkasten.service \
    /etc/systemd/system/zettelkasten.service
systemctl daemon-reload
systemctl enable zettelkasten.service

echo "[bootstrap] DONE."
echo
echo "Next steps:"
echo "  1. Verify SSH as deploy user: ssh deploy@<droplet-ip>"
echo "  2. Trigger the GitHub Actions deploy workflow targeting stage.zettelkasten.in"
```

- [ ] **Step 2: Make it executable**

```bash
chmod +x ops/host/bootstrap.sh
```

- [ ] **Step 3: Verify with shellcheck**

```bash
docker run --rm -v "$(pwd):/mnt" koalaman/shellcheck:stable /mnt/ops/host/bootstrap.sh
```

Expected: clean (or minor SC2086-style warnings that are acceptable). Fix any errors.

- [ ] **Step 4: Commit**

```bash
git add ops/host/bootstrap.sh
git commit -m "feat(host): add idempotent droplet bootstrap script"
```

---

## Task 19: Create `ops/host/ufw-rules.sh` (standalone re-apply helper)

**Files:**
- Create: `ops/host/ufw-rules.sh`

**Context:** A small standalone script the operator can re-run if UFW rules ever drift. Most users won't run it; it exists as a known-good source of truth.

- [ ] **Step 1: Create the file**

```bash
#!/usr/bin/env bash
# ops/host/ufw-rules.sh
# Re-apply the canonical UFW rules. Run as root.
set -euo pipefail

if [[ $EUID -ne 0 ]]; then
    echo "Must run as root" >&2
    exit 1
fi

ufw --force reset
ufw default deny incoming
ufw default allow outgoing
ufw allow 22/tcp comment 'SSH'
ufw allow 80/tcp comment 'HTTP'
ufw allow 443/tcp comment 'HTTPS'
ufw allow 443/udp comment 'HTTP/3 QUIC'
ufw --force enable
ufw status verbose
```

- [ ] **Step 2: Make executable + lint**

```bash
chmod +x ops/host/ufw-rules.sh
docker run --rm -v "$(pwd):/mnt" koalaman/shellcheck:stable /mnt/ops/host/ufw-rules.sh
```

- [ ] **Step 3: Commit**

```bash
git add ops/host/ufw-rules.sh
git commit -m "feat(host): add ufw rules re-apply script"
```

---

## Task 20: Create logrotate config

**Files:**
- Create: `ops/host/logrotate-zettelkasten.conf`

- [ ] **Step 1: Create the file**

```text
# /etc/logrotate.d/zettelkasten
# Rotates Caddy access logs. Container logs are rotated by the docker
# json-file driver itself (max-size: 10m, max-file: 3 in compose).

/opt/zettelkasten/logs/caddy/*.log {
    daily
    rotate 7
    compress
    delaycompress
    missingok
    notifempty
    copytruncate
    su root root
    sharedscripts
    postrotate
        docker kill --signal=USR1 caddy 2>/dev/null || true
    endscript
}
```

- [ ] **Step 2: Commit**

```bash
git add ops/host/logrotate-zettelkasten.conf
git commit -m "feat(host): add logrotate config for caddy access logs"
```

---

## Task 21: Create systemd unit `zettelkasten.service`

**Files:**
- Create: `ops/systemd/zettelkasten.service`

**Context:** systemd starts Caddy + the active color (blue or green) on boot. The active color is read from `/opt/zettelkasten/ACTIVE_COLOR`.

- [ ] **Step 1: Create the file**

```ini
[Unit]
Description=Zettelkasten Caddy + active app stack
After=docker.service network-online.target
Requires=docker.service
Wants=network-online.target

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=/opt/zettelkasten/compose
EnvironmentFile=/opt/zettelkasten/compose/.env
ExecStartPre=/bin/bash -c '\
    ACTIVE=$(cat /opt/zettelkasten/ACTIVE_COLOR 2>/dev/null || echo blue); \
    test "$ACTIVE" = blue || test "$ACTIVE" = green'
ExecStart=/bin/bash -c '\
    ACTIVE=$(cat /opt/zettelkasten/ACTIVE_COLOR); \
    /usr/bin/docker compose \
        -f /opt/zettelkasten/compose/docker-compose.caddy.yml \
        -f /opt/zettelkasten/compose/docker-compose.${ACTIVE}.yml \
        up -d'
ExecStop=/bin/bash -c '\
    ACTIVE=$(cat /opt/zettelkasten/ACTIVE_COLOR); \
    /usr/bin/docker compose \
        -f /opt/zettelkasten/compose/docker-compose.caddy.yml \
        -f /opt/zettelkasten/compose/docker-compose.${ACTIVE}.yml \
        down --timeout 20'
TimeoutStartSec=180
TimeoutStopSec=60
Restart=on-failure
RestartSec=10
StartLimitIntervalSec=300
StartLimitBurst=5
LimitNOFILE=65535

[Install]
WantedBy=multi-user.target
```

- [ ] **Step 2: Commit**

```bash
git add ops/systemd/zettelkasten.service
git commit -m "feat(host): add systemd unit for caddy + active color stack"
```

---

# Phase 6: Deploy Automation Scripts

---

## Task 22: Create `ops/deploy/healthcheck.sh`

**Files:**
- Create: `ops/deploy/healthcheck.sh`

**Context:** Helper used by `deploy.sh` to wait until a freshly-started container is healthy on a given port.

- [ ] **Step 1: Create the file**

```bash
#!/usr/bin/env bash
# ops/deploy/healthcheck.sh
#
# Polls http://127.0.0.1:<port>/api/health and exits 0 once it returns 200.
# Exits 1 after 30 attempts (~30s total).
#
# Usage: healthcheck.sh <port>

set -euo pipefail

PORT="${1:-}"
if [[ -z "$PORT" ]]; then
    echo "usage: $0 <port>" >&2
    exit 2
fi

MAX_ATTEMPTS=30
for attempt in $(seq 1 "$MAX_ATTEMPTS"); do
    if curl --silent --fail --max-time 2 "http://127.0.0.1:${PORT}/api/health" >/dev/null; then
        echo "[healthcheck] Port ${PORT} healthy after ${attempt} attempt(s)"
        exit 0
    fi
    sleep 1
done

echo "[healthcheck] Port ${PORT} did NOT become healthy after ${MAX_ATTEMPTS} attempts" >&2
exit 1
```

- [ ] **Step 2: Make executable + lint**

```bash
chmod +x ops/deploy/healthcheck.sh
docker run --rm -v "$(pwd):/mnt" koalaman/shellcheck:stable /mnt/ops/deploy/healthcheck.sh
```

- [ ] **Step 3: Commit**

```bash
git add ops/deploy/healthcheck.sh
git commit -m "feat(deploy): add healthcheck helper script"
```

---

## Task 23: Create `ops/deploy/deploy.sh`

**Files:**
- Create: `ops/deploy/deploy.sh`

**Context:** The blue-green orchestrator. Reads the current active color, brings up the idle color with the new image, waits for healthcheck, atomically rewrites `upstream.snippet`, gracefully reloads Caddy, drains the old color, then stops it. On any failure invokes `rollback.sh` and exits non-zero.

- [ ] **Step 1: Create the file**

```bash
#!/usr/bin/env bash
# ops/deploy/deploy.sh <image_sha>
#
# Blue-green deploy of a new image SHA.
#
# Side effects:
#   - Pulls ghcr.io/chintanmehta21/zettelkasten-kg-website:<sha>
#   - Brings up the idle color with the new image
#   - Waits for /api/health on the idle color
#   - Rewrites /opt/zettelkasten/caddy/upstream.snippet to point at idle color
#   - Reloads Caddy gracefully
#   - Drains and stops the previously-active color
#   - Updates /opt/zettelkasten/ACTIVE_COLOR
#
# On failure: invokes rollback.sh and exits non-zero.

set -euo pipefail

SHA="${1:-}"
if [[ -z "$SHA" ]]; then
    echo "usage: $0 <image_sha>" >&2
    exit 2
fi

ROOT=/opt/zettelkasten
IMAGE="ghcr.io/chintanmehta21/zettelkasten-kg-website:${SHA}"
ACTIVE_FILE="$ROOT/ACTIVE_COLOR"
SNIPPET="$ROOT/caddy/upstream.snippet"
LOG="$ROOT/logs/deploy.log"

log() {
    echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] $*" | tee -a "$LOG"
}

trap 'on_error' ERR
on_error() {
    log "DEPLOY FAILED at line $LINENO. Invoking rollback…"
    "$ROOT/deploy/rollback.sh" || true
    exit 1
}

ACTIVE=$(cat "$ACTIVE_FILE")
if [[ "$ACTIVE" == "blue" ]]; then
    IDLE="green"
    IDLE_PORT=10001
else
    IDLE="blue"
    IDLE_PORT=10000
fi

log "Starting deploy: SHA=$SHA, ACTIVE=$ACTIVE, IDLE=$IDLE"

# 1. Pull the new image
log "Pulling $IMAGE…"
IMAGE_TAG="$SHA" docker compose \
    -f "$ROOT/compose/docker-compose.${IDLE}.yml" \
    pull

# 2. Bring up the idle color with the new image (Caddy is unaffected)
log "Starting $IDLE container with new image…"
IMAGE_TAG="$SHA" docker compose \
    -f "$ROOT/compose/docker-compose.${IDLE}.yml" \
    up -d --no-deps

# 3. Wait for /api/health on the idle color
log "Waiting for $IDLE healthcheck on port $IDLE_PORT…"
"$ROOT/deploy/healthcheck.sh" "$IDLE_PORT"

# 4. Atomically rewrite the upstream snippet
log "Flipping Caddy upstream to $IDLE…"
TMP=$(mktemp)
cat > "$TMP" <<EOF
# Updated by deploy.sh at $(date -u +%Y-%m-%dT%H:%M:%SZ) — SHA=$SHA
reverse_proxy zettelkasten-${IDLE}:10000
EOF
mv "$TMP" "$SNIPPET"

# 5. Reload Caddy gracefully (zero dropped connections)
log "Reloading Caddy…"
docker exec caddy caddy reload --config /etc/caddy/Caddyfile

# 6. Update ACTIVE_COLOR
echo "$IDLE" > "$ACTIVE_FILE"

# 7. Drain old color for 20 seconds (let in-flight requests finish)
log "Draining $ACTIVE for 20 seconds…"
sleep 20

# 8. Stop the old color
log "Stopping $ACTIVE container…"
docker compose \
    -f "$ROOT/compose/docker-compose.${ACTIVE}.yml" \
    down --timeout 20 || log "Warning: failed to stop $ACTIVE cleanly"

log "DEPLOY SUCCEEDED. New active color: $IDLE, image: $IMAGE"
```

- [ ] **Step 2: Make executable + lint**

```bash
chmod +x ops/deploy/deploy.sh
docker run --rm -v "$(pwd):/mnt" koalaman/shellcheck:stable /mnt/ops/deploy/deploy.sh
```

Expected: clean.

- [ ] **Step 3: Commit**

```bash
git add ops/deploy/deploy.sh
git commit -m "feat(deploy): add blue-green deploy script with caddy hot reload"
```

---

## Task 24: Create `ops/deploy/rollback.sh`

**Files:**
- Create: `ops/deploy/rollback.sh`

**Context:** Called by `deploy.sh` on any failure (and also runnable manually). Re-points Caddy at the last known good color, ensures it's running, tears down any half-started idle color.

- [ ] **Step 1: Create the file**

```bash
#!/usr/bin/env bash
# ops/deploy/rollback.sh
#
# Roll back to the last known good color.
# Reads /opt/zettelkasten/ACTIVE_COLOR as the canonical source of truth.

set -euo pipefail

ROOT=/opt/zettelkasten
ACTIVE_FILE="$ROOT/ACTIVE_COLOR"
SNIPPET="$ROOT/caddy/upstream.snippet"
LOG="$ROOT/logs/deploy.log"

log() {
    echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] [ROLLBACK] $*" | tee -a "$LOG"
}

ACTIVE=$(cat "$ACTIVE_FILE")
if [[ "$ACTIVE" == "blue" ]]; then
    OTHER="green"
    ACTIVE_PORT=10000
else
    OTHER="blue"
    ACTIVE_PORT=10001
fi

log "Restoring known-good color: $ACTIVE"

# Make sure the active color is up
log "Ensuring $ACTIVE is running…"
docker compose \
    -f "$ROOT/compose/docker-compose.${ACTIVE}.yml" \
    up -d --no-deps || true

# Wait briefly for it to be healthy
"$ROOT/deploy/healthcheck.sh" "$ACTIVE_PORT" || {
    log "FATAL: $ACTIVE is not healthy on rollback. Manual intervention required."
    exit 1
}

# Re-point Caddy at the active color
log "Rewriting upstream snippet → $ACTIVE…"
TMP=$(mktemp)
cat > "$TMP" <<EOF
# Updated by rollback.sh at $(date -u +%Y-%m-%dT%H:%M:%SZ)
reverse_proxy zettelkasten-${ACTIVE}:10000
EOF
mv "$TMP" "$SNIPPET"

log "Reloading Caddy…"
docker exec caddy caddy reload --config /etc/caddy/Caddyfile || {
    log "WARNING: Caddy reload failed. Run: docker exec caddy caddy reload --config /etc/caddy/Caddyfile"
}

# Tear down the (failed) other color if it's running
if docker ps --format '{{.Names}}' | grep -q "^zettelkasten-${OTHER}\$"; then
    log "Tearing down failed $OTHER container…"
    docker compose \
        -f "$ROOT/compose/docker-compose.${OTHER}.yml" \
        down --timeout 20 || true
fi

log "ROLLBACK COMPLETE. Active color: $ACTIVE"
```

- [ ] **Step 2: Make executable + lint**

```bash
chmod +x ops/deploy/rollback.sh
docker run --rm -v "$(pwd):/mnt" koalaman/shellcheck:stable /mnt/ops/deploy/rollback.sh
```

- [ ] **Step 3: Commit**

```bash
git add ops/deploy/rollback.sh
git commit -m "feat(deploy): add rollback script that restores active color"
```

---

# Phase 7: GitHub Actions Workflows

---

## Task 25: Create `.github/workflows/ci.yml`

**Files:**
- Create: `.github/workflows/ci.yml`

**Context:** The PR + push test gate. Runs `pytest` (mocked, no `--live`) on every PR open/synchronize and every push to `master`. Uses pip cache for speed.

- [ ] **Step 1: Create the file**

```yaml
name: CI

on:
  pull_request:
    types: [opened, synchronize, reopened]
  push:
    branches: [master]

concurrency:
  group: ci-${{ github.ref }}
  cancel-in-progress: true

permissions:
  contents: read

jobs:
  test:
    name: pytest (mocked)
    runs-on: ubuntu-latest
    timeout-minutes: 10
    steps:
      - name: Checkout
        uses: actions/checkout@v4

      - name: Set up Python 3.12
        uses: actions/setup-python@v5
        with:
          python-version: "3.12"
          cache: pip
          cache-dependency-path: |
            ops/requirements.txt
            ops/requirements-dev.txt

      - name: Install dependencies
        run: |
          python -m pip install --upgrade pip
          pip install -r ops/requirements-dev.txt

      - name: Run pytest
        env:
          # Stub env so get_settings() doesn't SystemExit
          TELEGRAM_BOT_TOKEN: "000:ci-stub"
          ALLOWED_CHAT_ID: "0"
          GEMINI_API_KEY: "ci-stub"
        run: |
          pytest -q --maxfail=5
```

- [ ] **Step 2: Commit**

```bash
git add .github/workflows/ci.yml
git commit -m "ci: add pytest gate workflow on PR and push to master"
```

---

## Task 26: Create `.github/workflows/deploy-droplet.yml`

**Files:**
- Create: `.github/workflows/deploy-droplet.yml`

**Context:** Builds image → pushes to GHCR (private) → SSHes to droplet → writes `.env` from secrets → runs `deploy.sh`. Uses `production` environment with manual approval. On failure, automatically calls `rollback.sh`.

- [ ] **Step 1: Create the file**

```yaml
name: Deploy to DigitalOcean Droplet

on:
  push:
    branches: [master]
  workflow_dispatch:
    inputs:
      target_hostname:
        description: "Caddy hostname to deploy (zettelkasten.in or stage.zettelkasten.in)"
        required: false
        default: "zettelkasten.in"

concurrency:
  group: deploy-prod
  cancel-in-progress: true

permissions:
  contents: read
  packages: write   # for GHCR push

jobs:
  test:
    name: pytest (mocked)
    runs-on: ubuntu-latest
    timeout-minutes: 10
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
          cache: pip
          cache-dependency-path: |
            ops/requirements.txt
            ops/requirements-dev.txt
      - name: Install
        run: |
          python -m pip install --upgrade pip
          pip install -r ops/requirements-dev.txt
      - name: pytest
        env:
          TELEGRAM_BOT_TOKEN: "000:ci-stub"
          ALLOWED_CHAT_ID: "0"
          GEMINI_API_KEY: "ci-stub"
        run: pytest -q --maxfail=5

  build-and-push:
    name: Build & push image
    needs: test
    runs-on: ubuntu-latest
    timeout-minutes: 20
    outputs:
      image_sha: ${{ github.sha }}
    steps:
      - name: Checkout
        uses: actions/checkout@v4

      - name: Set up Buildx
        uses: docker/setup-buildx-action@v3

      - name: Login to GHCR
        uses: docker/login-action@v3
        with:
          registry: ghcr.io
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}

      - name: Build & push
        uses: docker/build-push-action@v5
        with:
          context: .
          file: ops/Dockerfile
          platforms: linux/amd64
          push: true
          tags: |
            ghcr.io/chintanmehta21/zettelkasten-kg-website:${{ github.sha }}
            ghcr.io/chintanmehta21/zettelkasten-kg-website:latest
          build-args: |
            GIT_SHA=${{ github.sha }}
            BUILD_DATE=${{ github.event.repository.updated_at }}
          cache-from: type=gha
          cache-to: type=gha,mode=max
          provenance: false

  deploy:
    name: SSH deploy to droplet
    needs: build-and-push
    runs-on: ubuntu-latest
    environment: production    # requires manual approval
    timeout-minutes: 15
    steps:
      - name: Write .env on droplet and pull image
        uses: appleboy/ssh-action@v1
        with:
          host: ${{ secrets.DROPLET_HOST }}
          username: ${{ secrets.DROPLET_SSH_USER }}
          key: ${{ secrets.DROPLET_SSH_KEY }}
          port: ${{ secrets.DROPLET_SSH_PORT }}
          envs: GHCR_READ_PAT,TELEGRAM_BOT_TOKEN,ALLOWED_CHAT_ID,WEBHOOK_SECRET,GEMINI_API_KEYS,SUPABASE_URL,SUPABASE_ANON_KEY,GITHUB_TOKEN_FOR_NOTES,GITHUB_REPO_FOR_NOTES,NEXUS_GOOGLE_CLIENT_ID,NEXUS_GOOGLE_CLIENT_SECRET,NEXUS_GITHUB_CLIENT_ID,NEXUS_GITHUB_CLIENT_SECRET,NEXUS_REDDIT_CLIENT_ID,NEXUS_REDDIT_CLIENT_SECRET,NEXUS_TWITTER_CLIENT_ID,NEXUS_TWITTER_CLIENT_SECRET,NEXUS_TOKEN_ENCRYPTION_KEY,SHA,TARGET_HOST
          script: |
            set -euo pipefail

            # Authenticate to GHCR for private image pulls
            echo "$GHCR_READ_PAT" | sudo docker login ghcr.io -u chintanmehta21 --password-stdin

            # Write the runtime .env file (mode 0600, owned by deploy)
            sudo tee /opt/zettelkasten/compose/.env > /dev/null <<EOF
            TELEGRAM_BOT_TOKEN=${TELEGRAM_BOT_TOKEN}
            ALLOWED_CHAT_ID=${ALLOWED_CHAT_ID}
            WEBHOOK_MODE=true
            WEBHOOK_PORT=10000
            WEBHOOK_URL=https://${TARGET_HOST}
            WEBHOOK_SECRET=${WEBHOOK_SECRET}
            GEMINI_API_KEYS=${GEMINI_API_KEYS}
            SUPABASE_URL=${SUPABASE_URL}
            SUPABASE_ANON_KEY=${SUPABASE_ANON_KEY}
            GITHUB_TOKEN=${GITHUB_TOKEN_FOR_NOTES}
            GITHUB_REPO=${GITHUB_REPO_FOR_NOTES}
            NEXUS_ENABLED=true
            NEXUS_GOOGLE_CLIENT_ID=${NEXUS_GOOGLE_CLIENT_ID}
            NEXUS_GOOGLE_CLIENT_SECRET=${NEXUS_GOOGLE_CLIENT_SECRET}
            NEXUS_GITHUB_CLIENT_ID=${NEXUS_GITHUB_CLIENT_ID}
            NEXUS_GITHUB_CLIENT_SECRET=${NEXUS_GITHUB_CLIENT_SECRET}
            NEXUS_REDDIT_CLIENT_ID=${NEXUS_REDDIT_CLIENT_ID}
            NEXUS_REDDIT_CLIENT_SECRET=${NEXUS_REDDIT_CLIENT_SECRET}
            NEXUS_TWITTER_CLIENT_ID=${NEXUS_TWITTER_CLIENT_ID}
            NEXUS_TWITTER_CLIENT_SECRET=${NEXUS_TWITTER_CLIENT_SECRET}
            NEXUS_TOKEN_ENCRYPTION_KEY=${NEXUS_TOKEN_ENCRYPTION_KEY}
            EOF
            sudo chmod 600 /opt/zettelkasten/compose/.env
            sudo chown deploy:deploy /opt/zettelkasten/compose/.env

            # Run the blue-green deploy
            sudo /opt/zettelkasten/deploy/deploy.sh "$SHA"
        env:
          GHCR_READ_PAT: ${{ secrets.GHCR_READ_PAT }}
          TELEGRAM_BOT_TOKEN: ${{ secrets.TELEGRAM_BOT_TOKEN }}
          ALLOWED_CHAT_ID: ${{ secrets.ALLOWED_CHAT_ID }}
          WEBHOOK_SECRET: ${{ secrets.WEBHOOK_SECRET }}
          GEMINI_API_KEYS: ${{ secrets.GEMINI_API_KEYS }}
          SUPABASE_URL: ${{ secrets.SUPABASE_URL }}
          SUPABASE_ANON_KEY: ${{ secrets.SUPABASE_ANON_KEY }}
          GITHUB_TOKEN_FOR_NOTES: ${{ secrets.GITHUB_TOKEN_FOR_NOTES }}
          GITHUB_REPO_FOR_NOTES: ${{ secrets.GITHUB_REPO_FOR_NOTES }}
          NEXUS_GOOGLE_CLIENT_ID: ${{ secrets.NEXUS_GOOGLE_CLIENT_ID }}
          NEXUS_GOOGLE_CLIENT_SECRET: ${{ secrets.NEXUS_GOOGLE_CLIENT_SECRET }}
          NEXUS_GITHUB_CLIENT_ID: ${{ secrets.NEXUS_GITHUB_CLIENT_ID }}
          NEXUS_GITHUB_CLIENT_SECRET: ${{ secrets.NEXUS_GITHUB_CLIENT_SECRET }}
          NEXUS_REDDIT_CLIENT_ID: ${{ secrets.NEXUS_REDDIT_CLIENT_ID }}
          NEXUS_REDDIT_CLIENT_SECRET: ${{ secrets.NEXUS_REDDIT_CLIENT_SECRET }}
          NEXUS_TWITTER_CLIENT_ID: ${{ secrets.NEXUS_TWITTER_CLIENT_ID }}
          NEXUS_TWITTER_CLIENT_SECRET: ${{ secrets.NEXUS_TWITTER_CLIENT_SECRET }}
          NEXUS_TOKEN_ENCRYPTION_KEY: ${{ secrets.NEXUS_TOKEN_ENCRYPTION_KEY }}
          SHA: ${{ github.sha }}
          TARGET_HOST: ${{ inputs.target_hostname || 'zettelkasten.in' }}
```

- [ ] **Step 2: Commit**

```bash
git add .github/workflows/deploy-droplet.yml
git commit -m "ci: add blue-green deploy workflow with manual production approval"
```

---

## Task 27: Create `.github/workflows/live-tests.yml`

**Files:**
- Create: `.github/workflows/live-tests.yml`

- [ ] **Step 1: Create the file**

```yaml
name: Live integration tests

on:
  workflow_dispatch:
  schedule:
    # Sunday 21:00 UTC = Monday 02:30 IST
    - cron: "0 21 * * 0"

permissions:
  contents: read

jobs:
  live:
    name: pytest --live (real APIs)
    runs-on: ubuntu-latest
    environment: production    # for the real API secrets
    timeout-minutes: 25
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
          cache: pip
          cache-dependency-path: |
            ops/requirements.txt
            ops/requirements-dev.txt

      - name: Install
        run: |
          python -m pip install --upgrade pip
          pip install -r ops/requirements-dev.txt

      - name: pytest --live
        env:
          TELEGRAM_BOT_TOKEN: ${{ secrets.TELEGRAM_BOT_TOKEN }}
          ALLOWED_CHAT_ID: ${{ secrets.ALLOWED_CHAT_ID }}
          GEMINI_API_KEYS: ${{ secrets.GEMINI_API_KEYS }}
          SUPABASE_URL: ${{ secrets.SUPABASE_URL }}
          SUPABASE_ANON_KEY: ${{ secrets.SUPABASE_ANON_KEY }}
        run: pytest --live -q
```

- [ ] **Step 2: Commit**

```bash
git add .github/workflows/live-tests.yml
git commit -m "ci: add live integration tests workflow on manual + weekly cron"
```

---

## Task 28: Delete `.github/workflows/keep-alive.yml`

**Files:**
- Delete: `.github/workflows/keep-alive.yml`

**Context:** Render's free-tier sleep was the only reason this existed. The droplet never sleeps.

- [ ] **Step 1: Verify the file exists**

```bash
ls .github/workflows/keep-alive.yml
```

- [ ] **Step 2: Delete it**

```bash
git rm .github/workflows/keep-alive.yml
```

- [ ] **Step 3: Commit**

```bash
git commit -m "ci: remove render keep-alive workflow (droplet doesn't sleep)"
```

---

# Phase 8: External Setup (manual checklist)

This phase has no code commits. Each task is a real-world action with verification commands.

---

## Task 29: Buy `zettelkasten.in` at GoDaddy

**Files:** none

- [ ] **Step 1: Go to https://www.godaddy.com and search for `zettelkasten.in`**

- [ ] **Step 2: Add to cart, decline all upsells (privacy, email, hosting, etc.)**

- [ ] **Step 3: Complete purchase**

- [ ] **Step 4: Verify ownership in GoDaddy "My Products" → Domains**

- [ ] **Step 5: Done — no commit**

---

## Task 30: Set up Cloudflare account and add the site

**Files:** none

- [ ] **Step 1: Sign up for a free Cloudflare account at https://dash.cloudflare.com/sign-up**

- [ ] **Step 2: After login, click "Add a site" → enter `zettelkasten.in` → choose Free plan**

- [ ] **Step 3: Cloudflare will scan existing DNS records (there should be none)**

- [ ] **Step 4: Cloudflare will display two assigned nameservers**

Copy them — they look like `amy.ns.cloudflare.com` and `rick.ns.cloudflare.com`.

- [ ] **Step 5: Done — no commit**

---

## Task 31: Update GoDaddy nameservers

**Files:** none

- [ ] **Step 1: GoDaddy → My Products → Domains → `zettelkasten.in` → Manage**

- [ ] **Step 2: Find the "Nameservers" section, click "Change Nameservers"**

- [ ] **Step 3: Choose "I'll use my own nameservers"**

- [ ] **Step 4: Enter the two nameservers from Cloudflare (Task 30 step 4)**

- [ ] **Step 5: Save the change**

- [ ] **Step 6: Wait 1–4 hours (usually faster), then verify propagation**

```bash
dig NS zettelkasten.in +short
```

Expected: only the two `*.ns.cloudflare.com` nameservers in the response. If GoDaddy's `domaincontrol.com` nameservers still appear, propagation is incomplete — wait longer.

- [ ] **Step 7: Done — no commit**

---

## Task 32: Enable DNSSEC + add CAA record + provision DO Droplet (in parallel)

**Files:** none

This task has three sub-tracks. They can run in parallel because they're independent.

- [ ] **Step 1 (DNSSEC): In Cloudflare → SSL/TLS → Edge Certificates → DNSSEC → click "Enable DNSSEC"**

Cloudflare will display a DS record. Copy the values.

- [ ] **Step 2 (DNSSEC): In GoDaddy → domain settings → DNSSEC → Add new DS record**

Paste the values from Cloudflare.

- [ ] **Step 3 (DNSSEC): Verify**

```bash
dig zettelkasten.in +dnssec | grep -i 'ad\b'
```

Expected: response contains `ad` flag (Authenticated Data). May take 30 min to propagate.

- [ ] **Step 4 (CAA): In Cloudflare DNS → Records → Add record**

```
Type:    CAA
Name:    zettelkasten.in
Tag:     issue
Value:   letsencrypt.org
Flags:   0
TTL:     Auto
```

- [ ] **Step 5 (CAA): Verify**

```bash
dig zettelkasten.in CAA +short
```

Expected: `0 issue "letsencrypt.org"`.

- [ ] **Step 6 (Droplet): Log into https://cloud.digitalocean.com**

- [ ] **Step 7 (Droplet): Create → Droplets**

- [ ] **Step 8 (Droplet): Select these options exactly:**

```
Region:               Bangalore (BLR1)
Image:                Marketplace → Docker on Ubuntu 22.04
Size:                 Premium AMD → s-1vcpu-1gb-amd ($7/mo, 1 vCPU, 1 GB RAM, 25 GB NVMe SSD)
                      (FALLBACK: Premium Intel s-1vcpu-1gb-intel $7/mo if AMD unavailable)
Authentication:       SSH keys → upload your existing personal SSH key (this is the
                      ROOT SSH key for the one-time bootstrap, NOT the deploy user key)
Backups:              OFF (per spec §13)
IPv6:                 ON (free, required by spec §3.4)
Monitoring:           ON (free)
Hostname:             zettelkasten-prod
Tags:                 zettelkasten,production
```

- [ ] **Step 9 (Droplet): Create the Droplet. Wait ~60 seconds for it to boot.**

- [ ] **Step 10 (Droplet): Note the IPv4 and IPv6 addresses from the DO dashboard**

- [ ] **Step 11: Done — no commit**

---

## Task 33: Generate `deploy` user SSH keypair and store in GitHub secret

**Files:** none

**Context:** This is a SEPARATE keypair from your personal SSH key (which is what you used at droplet creation). The deploy user keypair is used by GitHub Actions to SSH into the droplet for blue-green deploys.

- [ ] **Step 1: On your local machine, generate a fresh ed25519 keypair**

```bash
ssh-keygen -t ed25519 -C "deploy@zettelkasten-prod" -f ~/.ssh/zettelkasten_deploy -N ""
```

This creates two files:
- `~/.ssh/zettelkasten_deploy` (private key — goes into GitHub secret)
- `~/.ssh/zettelkasten_deploy.pub` (public key — goes onto droplet via bootstrap)

- [ ] **Step 2: Print the public key for use in the next task**

```bash
cat ~/.ssh/zettelkasten_deploy.pub
```

Copy the entire single-line output (`ssh-ed25519 AAAA...`).

- [ ] **Step 3: Print the private key — you'll paste this into GitHub later**

```bash
cat ~/.ssh/zettelkasten_deploy
```

Copy the entire multi-line block including `-----BEGIN OPENSSH PRIVATE KEY-----` and `-----END OPENSSH PRIVATE KEY-----`.

- [ ] **Step 4: Store the private key in your password manager** as a backup

- [ ] **Step 5: Done — no commit (key files stay on your machine, never in git)**

---

## Task 34: Generate fine-grained `GHCR_READ_PAT`

**Files:** none

- [ ] **Step 1: Go to https://github.com/settings/tokens?type=beta**

- [ ] **Step 2: Click "Generate new token" → fine-grained**

- [ ] **Step 3: Configure exactly:**

```
Token name:           zettelkasten-droplet-ghcr-read
Expiration:           Custom → 365 days from today
Resource owner:       chintanmehta21
Repository access:    Only select repositories → Zettelkasten_KG
Permissions:
  - Account permissions:
      Packages → Read-only
  - Repository permissions:
      (none — leave defaults)
```

- [ ] **Step 4: Click "Generate token"**

- [ ] **Step 5: Copy the token immediately** — GitHub will only show it once. Save in your password manager.

- [ ] **Step 6: Done — no commit**

---

## Task 35: Configure GitHub `production` environment + secrets

**Files:** none

- [ ] **Step 1: Go to https://github.com/chintanmehta21/Zettelkasten_KG/settings/environments**

- [ ] **Step 2: Click "New environment" → name: `production` → Configure environment**

- [ ] **Step 3: Enable "Required reviewers"** → add yourself as the reviewer

This is the manual approval gate for every deploy.

- [ ] **Step 4: Set "Wait timer" to 0 minutes**

- [ ] **Step 5: Restrict deployment branches to `master` only**

- [ ] **Step 6: Add Environment secrets — click "Add secret" for each**

Required secrets (paste the value when prompted):

```
DROPLET_HOST              → <droplet IPv4 from Task 32 step 10>
DROPLET_SSH_USER          → deploy
DROPLET_SSH_KEY           → <full private key block from Task 33 step 3>
DROPLET_SSH_PORT          → 22
GHCR_READ_PAT             → <token from Task 34 step 5>

TELEGRAM_BOT_TOKEN        → <existing value from Render>
ALLOWED_CHAT_ID           → <existing value from Render>
WEBHOOK_SECRET            → <existing value from Render or generate fresh: openssl rand -hex 32>
GEMINI_API_KEYS           → <comma-separated list of 10 keys from your local api_env file>

SUPABASE_URL              → <existing value from Render>
SUPABASE_ANON_KEY         → <existing value from Render>

GITHUB_TOKEN_FOR_NOTES    → <existing GITHUB_TOKEN from Render — for note pushing>
GITHUB_REPO_FOR_NOTES     → <existing GITHUB_REPO from Render>

NEXUS_GOOGLE_CLIENT_ID
NEXUS_GOOGLE_CLIENT_SECRET
NEXUS_GITHUB_CLIENT_ID
NEXUS_GITHUB_CLIENT_SECRET
NEXUS_REDDIT_CLIENT_ID
NEXUS_REDDIT_CLIENT_SECRET
NEXUS_TWITTER_CLIENT_ID
NEXUS_TWITTER_CLIENT_SECRET
NEXUS_TOKEN_ENCRYPTION_KEY → <existing from Render>
```

CRITICAL: do **NOT** add `SUPABASE_SERVICE_ROLE_KEY` to this environment. It must never touch the droplet (per spec §3.6 / Q12).

- [ ] **Step 7: Verify all secrets are listed under environment `production`**

- [ ] **Step 8: Done — no commit**

---

# Phase 9: Droplet Bootstrap (manual SSH)

---

## Task 36: SCP the repo's ops/ tree to the droplet (one-shot)

**Files:** none

**Context:** The bootstrap script needs `ops/host/sysctl-zettelkasten.conf`, `ops/host/logrotate-zettelkasten.conf`, and `ops/systemd/zettelkasten.service` available on the droplet. We copy them once via scp before running bootstrap.

- [ ] **Step 1: SSH to droplet as root using the personal key from Task 32 step 8**

```bash
ssh root@<DROPLET_IPV4>
```

- [ ] **Step 2: Make a temporary directory for the repo cache**

```bash
mkdir -p /opt/zettelkasten/repo-cache
exit
```

- [ ] **Step 3: From your local machine, scp the relevant ops/ tree to the droplet**

```bash
cd "C:/Users/LENOVO/Documents/Claude_Code/Projects/Obsidian_Vault"
scp -r ops/host ops/systemd ops/caddy ops/deploy ops/docker-compose.blue.yml ops/docker-compose.green.yml ops/docker-compose.caddy.yml \
    root@<DROPLET_IPV4>:/opt/zettelkasten/repo-cache/ops/
```

Note: this creates `/opt/zettelkasten/repo-cache/ops/` containing all the files bootstrap.sh references.

- [ ] **Step 4: SSH back in and verify**

```bash
ssh root@<DROPLET_IPV4>
ls -R /opt/zettelkasten/repo-cache/ops/
```

Expected: see `host/`, `systemd/`, `caddy/`, `deploy/`, and the three compose files.

- [ ] **Step 5: Done — no commit (verification only)**

---

## Task 37: Run `bootstrap.sh` on the droplet

**Files:** none (manual execution)

- [ ] **Step 1: While SSHed in as root, set the `DEPLOY_PUBKEY` env var with the public key from Task 33 step 2**

```bash
export DEPLOY_PUBKEY='ssh-ed25519 AAAA...your full public key here... deploy@zettelkasten-prod'
```

- [ ] **Step 2: Run the bootstrap script**

```bash
bash /opt/zettelkasten/repo-cache/ops/host/bootstrap.sh
```

Expected: ~2 minutes of output, no errors. The final line is `[bootstrap] DONE.`.

- [ ] **Step 3: Copy the static config files to their permanent locations**

```bash
install -m 0644 /opt/zettelkasten/repo-cache/ops/caddy/Caddyfile /opt/zettelkasten/caddy/Caddyfile
install -m 0644 /opt/zettelkasten/repo-cache/ops/caddy/upstream.snippet /opt/zettelkasten/caddy/upstream.snippet
install -m 0644 /opt/zettelkasten/repo-cache/ops/docker-compose.blue.yml /opt/zettelkasten/compose/docker-compose.blue.yml
install -m 0644 /opt/zettelkasten/repo-cache/ops/docker-compose.green.yml /opt/zettelkasten/compose/docker-compose.green.yml
install -m 0644 /opt/zettelkasten/repo-cache/ops/docker-compose.caddy.yml /opt/zettelkasten/compose/docker-compose.caddy.yml
install -m 0755 /opt/zettelkasten/repo-cache/ops/deploy/deploy.sh /opt/zettelkasten/deploy/deploy.sh
install -m 0755 /opt/zettelkasten/repo-cache/ops/deploy/rollback.sh /opt/zettelkasten/deploy/rollback.sh
install -m 0755 /opt/zettelkasten/repo-cache/ops/deploy/healthcheck.sh /opt/zettelkasten/deploy/healthcheck.sh
chown -R deploy:deploy /opt/zettelkasten/caddy /opt/zettelkasten/compose /opt/zettelkasten/deploy
```

- [ ] **Step 4: Verify UFW, swap, and the deploy user**

```bash
ufw status verbose
swapon --show
id deploy
docker network ls | grep zettelnet
ls /opt/zettelkasten/
```

Expected:
- UFW shows `Status: active` with rules for 22, 80, 443/tcp, 443/udp
- swap shows `/swapfile  file  1024M  ...`
- `id deploy` shows uid=1001(deploy) gid=...(deploy) groups=...(deploy),...(docker)
- `zettelnet` network exists
- `/opt/zettelkasten/` contains `compose/`, `caddy/`, `data/`, `logs/`, `deploy/`, `ACTIVE_COLOR`, `repo-cache/`

- [ ] **Step 5: Test SSH as deploy user from your local machine**

```bash
ssh -i ~/.ssh/zettelkasten_deploy deploy@<DROPLET_IPV4> 'whoami && docker ps'
```

Expected: prints `deploy` and an empty docker ps table.

- [ ] **Step 6: Done — no commit**

---

## Task 38: Confirm root SSH is disabled

**Files:** none

- [ ] **Step 1: From your local machine, attempt to SSH as root with a password**

```bash
ssh -o PreferredAuthentications=password -o PubkeyAuthentication=no root@<DROPLET_IPV4>
```

Expected: `Permission denied (publickey)`. Password auth is OFF.

- [ ] **Step 2: Attempt to SSH as root with a key**

```bash
ssh root@<DROPLET_IPV4>
```

Expected: `Permission denied (publickey)`. Root login is OFF.

- [ ] **Step 3: Confirm `deploy` SSH still works**

```bash
ssh -i ~/.ssh/zettelkasten_deploy deploy@<DROPLET_IPV4> 'echo OK'
```

Expected: prints `OK`.

- [ ] **Step 4: Done — no commit**

---

# Phase 10: First Deploy to Staging

---

## Task 39: Add Cloudflare DNS records for `stage.zettelkasten.in`

**Files:** none

- [ ] **Step 1: In Cloudflare DNS, add an A record**

```
Type:   A
Name:   stage
IPv4:   <DROPLET_IPV4>
Proxy:  DNS only (grey cloud)
TTL:    Auto
```

- [ ] **Step 2: Add a matching AAAA record**

```
Type:   AAAA
Name:   stage
IPv6:   <DROPLET_IPV6>
Proxy:  DNS only (grey cloud)
TTL:    Auto
```

- [ ] **Step 3: Wait ~1 minute and verify**

```bash
dig stage.zettelkasten.in A    +short
dig stage.zettelkasten.in AAAA +short
```

Expected: the droplet's IPv4 and IPv6 respectively.

- [ ] **Step 4: Done — no commit**

---

## Task 40: Trigger the first deploy via `workflow_dispatch` against staging

**Files:** none

**Context:** The first deploy uses the `stage.zettelkasten.in` hostname so Caddy provisions a real Let's Encrypt cert for the staging hostname WITHOUT touching the production apex yet.

- [ ] **Step 1: Push all the Phase 1–7 commits to master**

```bash
git push origin master
```

Expected: `ci.yml` runs and goes green.

- [ ] **Step 2: GitHub repo → Actions tab → "Deploy to DigitalOcean Droplet" → Run workflow**

```
Branch:           master
target_hostname:  stage.zettelkasten.in
```

Click "Run workflow".

- [ ] **Step 3: Wait for the `test` and `build-and-push` jobs to complete (green)**

The `deploy` job will then enter `Waiting for review`.

- [ ] **Step 4: Click "Review pending deployments" → approve the production environment**

- [ ] **Step 5: Watch the `deploy` job logs**

Expected sequence in the logs:
- `docker login ghcr.io` succeeds
- `.env` file written
- `deploy.sh` runs:
  - Pulls the new image
  - Starts blue (since ACTIVE_COLOR was `blue` initially, idle is `green`)
  - Wait, correct: ACTIVE_COLOR=blue means idle=green. The first deploy ironically starts green (the idle color), waits for healthcheck on 10001, flips Caddy to green, drains and stops blue. After this, ACTIVE_COLOR=green.

  This is correct behavior — the first deploy treats the empty state as "blue is active but stopped" and brings up green as the new active color.
- Final line: `DEPLOY SUCCEEDED. New active color: green, image: ghcr.io/.../zettelkasten-kg-website:<sha>`

- [ ] **Step 6: From the droplet, verify both Caddy and the active color are running**

```bash
ssh -i ~/.ssh/zettelkasten_deploy deploy@<DROPLET_IPV4>
docker ps
cat /opt/zettelkasten/ACTIVE_COLOR
```

Expected: `caddy` and `zettelkasten-green` both running, ACTIVE_COLOR is `green`.

- [ ] **Step 7: Done — no commit**

---

## Task 41: Smoke-test `https://stage.zettelkasten.in`

**Files:** none

**Context:** Hit every public route to make sure the cert provisioned, the FastAPI app is wired up correctly, Supabase reads work, the bot webhook path is reachable, and HTTP/3 + IPv6 are functioning.

- [ ] **Step 1: TLS handshake + apex health endpoint**

```bash
curl -fsS -I https://stage.zettelkasten.in/api/health
```

Expected: `HTTP/2 200`. If you see `HTTP/1.1` something is wrong with Caddy's HTTP/2 negotiation.

- [ ] **Step 2: Health endpoint payload**

```bash
curl -fsS https://stage.zettelkasten.in/api/health
```

Expected: `{"status":"ok"}`.

- [ ] **Step 3: Home page**

```bash
curl -fsS -o /dev/null -w "%{http_code}\n" https://stage.zettelkasten.in/
```

Expected: `200`.

- [ ] **Step 4: Each major route**

```bash
for path in /api/graph /knowledge-graph /home /home/zettels /home/nexus /about /pricing /auth/callback; do
    code=$(curl -fsS -o /dev/null -w "%{http_code}" "https://stage.zettelkasten.in${path}")
    echo "${path} -> ${code}"
done
```

Expected: all `200` (some authed routes may return 200 with a login redirect HTML, which is acceptable).

- [ ] **Step 5: HTTP/3 (QUIC over UDP 443)**

```bash
curl --http3 -fsS -I https://stage.zettelkasten.in/api/health
```

Expected: `HTTP/3 200`. If your local curl doesn't have HTTP/3 support, skip this and verify from the browser DevTools instead (Network tab → Protocol column should show `h3`).

- [ ] **Step 6: IPv6**

```bash
curl -6 -fsS -I https://stage.zettelkasten.in/api/health
```

Expected: `HTTP/2 200`.

- [ ] **Step 7: HSTS header**

```bash
curl -fsS -I https://stage.zettelkasten.in/ | grep -i strict-transport-security
```

Expected: `strict-transport-security: max-age=63072000; includeSubDomains; preload`.

- [ ] **Step 8: Cache headers on a static asset**

```bash
curl -fsS -I https://stage.zettelkasten.in/css/style.css | grep -i cache-control
```

Expected: `cache-control: public, max-age=31536000, immutable`.

- [ ] **Step 9: Compression**

```bash
curl -fsS -I -H "Accept-Encoding: zstd" https://stage.zettelkasten.in/css/style.css | grep -i content-encoding
```

Expected: `content-encoding: zstd` (or `gzip` if your curl doesn't speak zstd).

- [ ] **Step 10: Submit a real test URL through `/api/summarize`**

```bash
curl -fsS -X POST https://stage.zettelkasten.in/api/summarize \
    -H 'Content-Type: application/json' \
    -d '{"url":"https://news.ycombinator.com"}' | head -50
```

Expected: a JSON response with `title`, `summary`, `tags`, etc. If you get 429 you hit the in-memory rate limiter — wait 60s and retry.

- [ ] **Step 11: Verify Supabase write happened**

```bash
curl -fsS https://stage.zettelkasten.in/api/graph | python -c "import sys,json; data=json.load(sys.stdin); print('nodes:',len(data.get('nodes',[])),'links:',len(data.get('links',[])))"
```

Expected: node count is at least one larger than before Step 10.

- [ ] **Step 12: Compare graph node count with the current Render production**

```bash
curl -fsS https://<your-render-url>/api/graph | python -c "import sys,json; data=json.load(sys.stdin); print('render nodes:',len(data.get('nodes',[])))"
```

Expected: similar count (drift of a few nodes is OK if Render had more recent activity).

- [ ] **Step 13: Done — no commit**

If any step fails, do NOT proceed to Task 42. Diagnose, fix, redeploy.

---

## Task 42: Rehearse a blue-green flip on the droplet with a no-op commit

**Files:** none

**Context:** Now that the first deploy is healthy on stage, do a trivial second deploy to verify the blue-green flip mechanism works on the real droplet.

- [ ] **Step 1: Make a no-op commit on master**

```bash
git commit --allow-empty -m "chore: rehearse blue-green flip"
git push origin master
```

- [ ] **Step 2: GitHub Actions auto-triggers `deploy-droplet.yml`**

Watch the workflow run. Approve the production environment when prompted.

- [ ] **Step 3: While the deploy is running, hit `/api/health` in a tight loop from a third terminal**

```bash
while true; do
    curl -fsS -w "%{http_code} " https://stage.zettelkasten.in/api/health
    sleep 0.2
done
```

Expected: a steady stream of `200`s with NO `502`, `503`, or `504` during the flip.

- [ ] **Step 4: Confirm the active color flipped on the droplet**

```bash
ssh -i ~/.ssh/zettelkasten_deploy deploy@<DROPLET_IPV4> 'cat /opt/zettelkasten/ACTIVE_COLOR && cat /opt/zettelkasten/caddy/upstream.snippet'
```

Expected: ACTIVE_COLOR is now `blue` (flipped from `green`), and `upstream.snippet` references `zettelkasten-blue:10000`.

- [ ] **Step 5: Stop the tight-loop curl**

- [ ] **Step 6: Done — no commit (already committed in Step 1)**

---

# Phase 11: Production Cutover

---

## Task 43: Add Cloudflare DNS records for the apex hostname

**Files:** none

- [ ] **Step 1: In Cloudflare DNS, add the apex A record**

```
Type:   A
Name:   @
IPv4:   <DROPLET_IPV4>
Proxy:  DNS only (grey cloud)
TTL:    60 (manually set, not Auto)
```

- [ ] **Step 2: Add the apex AAAA record**

```
Type:   AAAA
Name:   @
IPv6:   <DROPLET_IPV6>
Proxy:  DNS only (grey cloud)
TTL:    60
```

- [ ] **Step 3: Add the www CNAME**

```
Type:   CNAME
Name:   www
Target: zettelkasten.in
Proxy:  DNS only (grey cloud)
TTL:    60
```

- [ ] **Step 4: Verify resolution**

```bash
dig zettelkasten.in       A    +short
dig zettelkasten.in       AAAA +short
dig www.zettelkasten.in   +short
```

Expected: all three return values (the CNAME may resolve through to the A record).

- [ ] **Step 5: Done — no commit**

---

## Task 44: Trigger the first apex deploy

**Files:** none

**Context:** Caddy already has the staging cert. We deploy again with `target_hostname=zettelkasten.in` so the runtime `WEBHOOK_URL` env var on the droplet matches the apex hostname. Caddy will provision a fresh Let's Encrypt cert for the apex on first request.

- [ ] **Step 1: GitHub repo → Actions → "Deploy to DigitalOcean Droplet" → Run workflow**

```
Branch:           master
target_hostname:  zettelkasten.in
```

- [ ] **Step 2: Approve the deploy**

- [ ] **Step 3: Watch the deploy logs — must end with `DEPLOY SUCCEEDED`**

- [ ] **Step 4: Trigger the cert provisioning by hitting the apex**

```bash
curl -fsS https://zettelkasten.in/api/health
```

The first request takes ~10 seconds (Caddy completes the ACME challenge in the background). Subsequent requests are fast.

Expected: `{"status":"ok"}`.

- [ ] **Step 5: Verify the cert is from Let's Encrypt and covers both apex + www**

```bash
echo | openssl s_client -connect zettelkasten.in:443 -servername zettelkasten.in 2>/dev/null \
    | openssl x509 -noout -issuer -subject -dates
```

Expected: `issuer=C = US, O = Let's Encrypt, CN = R3` (or current LE intermediate). Subject CN is `zettelkasten.in`. SAN should include `www.zettelkasten.in`.

- [ ] **Step 6: Test the www → apex redirect**

```bash
curl -fsS -I https://www.zettelkasten.in/
```

Expected: `HTTP/2 301` with `location: https://zettelkasten.in/`.

- [ ] **Step 7: Done — no commit**

---

## Task 45: Run the full smoke test on production hostname

**Files:** none

- [ ] **Step 1: Re-run every command from Task 41 against `zettelkasten.in` instead of `stage.zettelkasten.in`**

(Steps 1–11 of Task 41, with the hostname swapped.)

Expected: every step returns the same successful result.

- [ ] **Step 2: Done — no commit**

---

## Task 46: Swap the Telegram webhook to the new host

**Files:** none

- [ ] **Step 1: Read your `WEBHOOK_SECRET` from the GitHub `production` environment** (or your password manager)

- [ ] **Step 2: Read your `TELEGRAM_BOT_TOKEN`**

- [ ] **Step 3: Call Telegram setWebhook with the new URL**

```bash
TOKEN=<your-bot-token>
SECRET=<your-webhook-secret>
curl -fsS "https://api.telegram.org/bot${TOKEN}/setWebhook" \
    --data-urlencode "url=https://zettelkasten.in/telegram/webhook" \
    --data-urlencode "secret_token=${SECRET}" \
    --data-urlencode "drop_pending_updates=false"
```

Expected: `{"ok":true,"result":true,"description":"Webhook was set"}`.

- [ ] **Step 4: Verify the webhook info**

```bash
curl -fsS "https://api.telegram.org/bot${TOKEN}/getWebhookInfo" | python -m json.tool
```

Expected:
```
"url": "https://zettelkasten.in/telegram/webhook",
"has_custom_certificate": false,
"pending_update_count": 0,
"last_error_message": (absent)
```

- [ ] **Step 5: Send a test command to the bot from Telegram (e.g., `/status`)**

Expected: bot responds within 2 seconds.

- [ ] **Step 6: Tail the droplet bot logs and confirm the request landed**

```bash
ssh -i ~/.ssh/zettelkasten_deploy deploy@<DROPLET_IPV4> 'docker logs $(cat /opt/zettelkasten/ACTIVE_COLOR | sed "s/^/zettelkasten-/") --tail 50 | grep -i webhook'
```

Expected: log line showing `Webhook update queued`.

- [ ] **Step 7: Done — no commit**

---

## Task 47: Pause Render service

**Files:** none

- [ ] **Step 1: Log into https://dashboard.render.com**

- [ ] **Step 2: Open the zettelkasten service → Settings → Suspend Web Service**

Confirm the suspension. Render keeps the service in pause state — instantly resumable for 7 days as a rollback target.

- [ ] **Step 3: Verify the Render service is no longer responding**

```bash
curl -fsS -m 5 https://<your-render-url>/api/health || echo "Render is paused (expected)"
```

Expected: connection refused or timeout (Render returns its "service is suspended" page).

- [ ] **Step 4: Verify the droplet is taking 100% of traffic by tailing Caddy logs**

```bash
ssh -i ~/.ssh/zettelkasten_deploy deploy@<DROPLET_IPV4> 'tail -20 /opt/zettelkasten/logs/caddy/access.log'
```

Expected: real user requests landing on the droplet.

- [ ] **Step 5: Done — no commit**

---

# Phase 12: Post-Cutover Hardening

---

## Task 48: Raise apex DNS TTLs from 60s to 3600s

**Files:** none

- [ ] **Step 1: In Cloudflare DNS, edit the apex A record**

Change TTL from `60` to `3600` (or use Auto, which Cloudflare manages well).

- [ ] **Step 2: Edit the apex AAAA record the same way**

- [ ] **Step 3: Edit the www CNAME the same way**

- [ ] **Step 4: Verify**

```bash
dig zettelkasten.in A | grep -A1 'ANSWER SECTION' | tail -1
```

Expected: TTL of ~3600 (it may decrement as caches age).

- [ ] **Step 5: Done — no commit**

---

## Task 49: Delete the staging hostname records

**Files:** none

- [ ] **Step 1: In Cloudflare DNS, delete the `stage` A and AAAA records**

- [ ] **Step 2: Verify**

```bash
dig stage.zettelkasten.in +short
```

Expected: empty (NXDOMAIN).

- [ ] **Step 3: Done — no commit**

---

## Task 50: Set up BetterStack monitors

**Files:** none

**Context:** You manage the BetterStack account directly (per spec §9.4). The plan does not script this.

- [ ] **Step 1: Log into your BetterStack account at https://uptime.betterstack.com**

- [ ] **Step 2: Monitors → Create monitor**

```
URL:                  https://zettelkasten.in/api/health
Check frequency:      30 seconds
Request method:       GET
Expected status code: 200
Regions:              US East, EU West, India (or closest 3)
Alert after:          2 consecutive failed checks
```

- [ ] **Step 3: Create a second monitor**

```
URL:                  https://zettelkasten.in/
Check frequency:      60 seconds
Request method:       GET
Expected status code: 200
Regions:              India primary
```

- [ ] **Step 4: Configure alert channels**

```
Email:    chintanoninternet@gmail.com
Telegram: <ALLOWED_CHAT_ID>
```

- [ ] **Step 5: Trigger a test alert** (BetterStack has a test button) and verify both channels receive it

- [ ] **Step 6: Done — no commit**

---

## Task 51: Run the post-cutover hardening checklist

**Files:** none

- [ ] **Step 1: DNSSEC active**

```bash
dig zettelkasten.in +dnssec | grep -i 'flags:.*ad'
```

Expected: response contains `ad` flag.

- [ ] **Step 2: CAA record active**

```bash
dig zettelkasten.in CAA +short
```

Expected: `0 issue "letsencrypt.org"`.

- [ ] **Step 3: HTTP/3 active**

```bash
curl --http3 -fsS -I https://zettelkasten.in/api/health 2>&1 | head -1
```

Expected: `HTTP/3 200`.

- [ ] **Step 4: IPv6 active**

```bash
curl -6 -fsS -I https://zettelkasten.in/api/health | head -1
```

Expected: `HTTP/2 200`.

- [ ] **Step 5: HSTS header present**

```bash
curl -fsS -I https://zettelkasten.in/ | grep -i strict-transport
```

- [ ] **Step 6: BetterStack monitors green** — check the BetterStack dashboard

- [ ] **Step 7: Telegram bot getWebhookInfo confirms new URL**

```bash
curl -fsS "https://api.telegram.org/bot${TOKEN}/getWebhookInfo" | python -m json.tool | grep -A1 url
```

Expected: `"url": "https://zettelkasten.in/telegram/webhook"`.

- [ ] **Step 8: systemd unit is enabled and active**

```bash
ssh -i ~/.ssh/zettelkasten_deploy deploy@<DROPLET_IPV4> 'sudo systemctl is-enabled zettelkasten.service && sudo systemctl is-active zettelkasten.service'
```

Expected: both `enabled` and `active`.

- [ ] **Step 9: Reboot test (proves systemd brings the stack back automatically)**

```bash
ssh -i ~/.ssh/zettelkasten_deploy deploy@<DROPLET_IPV4> 'sudo reboot'
```

Wait ~90 seconds, then:

```bash
curl -fsS https://zettelkasten.in/api/health
```

Expected: `{"status":"ok"}`. The site came back without manual intervention.

- [ ] **Step 10: Done — no commit**

---

## Task 52: Update README's deployment section

**Files:**
- Modify: `README.md`

**Context:** Users browsing the repo should know we're on DigitalOcean now. Per user preferences (no env var tables in README), keep the change minimal.

- [ ] **Step 1: Find the existing "Deployment" or "Render" section in `README.md`** and replace it with a one-paragraph pointer

```markdown
## Deployment

Production runs on a DigitalOcean Droplet (BLR1, Premium AMD $7/mo) behind
Caddy with blue-green deploys via GitHub Actions. See
[`docs/superpowers/specs/2026-04-09-render-to-digitalocean-migration-design.md`](docs/superpowers/specs/2026-04-09-render-to-digitalocean-migration-design.md)
for the architecture and
[`docs/superpowers/plans/2026-04-09-render-to-digitalocean-migration.md`](docs/superpowers/plans/2026-04-09-render-to-digitalocean-migration.md)
for the implementation steps.
```

Do not add any env var tables (per user preference).

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs(readme): point deployment section at digitalocean spec and plan"
git push origin master
```

This push will trigger a deploy. Approve it to verify the deploy pipeline still works after cutover.

---

# Phase 13: Cleanup (T+7 days)

---

## Task 53: Delete the Render service

**Files:** none

**Context:** After 7 days of stable operation on DigitalOcean, the Render service is no longer needed as a rollback target.

- [ ] **Step 1: Verify the droplet has been stable for 7+ days**

Check BetterStack uptime report for the past 7 days. Should show 99.9%+ uptime.

- [ ] **Step 2: Verify there's no recent traffic on Render**

```bash
# Render dashboard → service → Logs → confirm no recent requests
```

- [ ] **Step 3: In the Render dashboard, open the service → Settings → Delete Web Service**

Confirm the deletion. This is irreversible.

- [ ] **Step 4: Optionally remove Render-specific env vars from your local `.env.example` and `.gitignore`** as a follow-up cleanup

- [ ] **Step 5: Done — no commit (Render is gone, the migration is complete)**

---

## Self-Review (engineer should run this before starting Task 1)

This checklist mirrors the spec sections to confirm coverage.

| Spec § | Topic | Plan tasks |
|---|---|---|
| §3.1 | Premium AMD $7 BLR1 tier | Task 32 step 8 |
| §3.2 | Docker 1-Click image | Task 32 step 8 |
| §3.3 | Private GHCR + GHCR_READ_PAT | Tasks 26, 34, 35 |
| §3.4 | Caddy + apex canonical + IPv6 + HTTP/3 + HSTS | Tasks 11, 13, 41, 51 |
| §3.5 | Host directory layout | Task 18 (bootstrap.sh) |
| §3.6 | Supabase Free unchanged + no service_role on droplet | Tasks 26, 35 (no SUPABASE_SERVICE_ROLE_KEY in env list) |
| §3.7 | Bot in same process | Tasks 4, 26 (single image) |
| §5.2 | Blue-green deploy sequence | Task 23 (deploy.sh) |
| §6.4 | Two dev compose files | Tasks 14, 15 |
| §6.5 | Telegram webhook path refactor | Task 4 |
| §7.1 | Multi-stage Dockerfile + tini + non-root + healthcheck | Task 7 |
| §7.2 | Dependency split | Task 6 |
| §7.3 | .dockerignore | Task 8 |
| §7.4 | Per-feature optimizations (cache headers, encode, log_skip) | Task 11 (Caddyfile) |
| §8.1 | GEMINI_API_KEYS env var fallback | Task 1 |
| §8.2 | Lazy imports in pipeline.py + persist.py | Tasks 2, 3 |
| §8.3 | NEXUS_ENABLED feature flag | Task 5 |
| §9.1 | Host hardening (UFW, fail2ban, swap, sysctl) | Tasks 17, 18, 19, 20 |
| §9.2 | systemd unit | Task 21 |
| §9.3 | Container reliability (mem_limit, healthcheck, read_only) | Tasks 12, 13 |
| §9.4 | BetterStack monitors | Task 50 |
| §10.1 | Pre-cutover (DNS delegation, DNSSEC, CAA, staging) | Tasks 30, 31, 32, 39 |
| §10.2 | Cutover (apex DNS + setWebhook) | Tasks 43, 44, 46 |
| §10.3 | Post-cutover hardening checklist | Task 51 |
| §10.4 | Rollback path | Task 24 (rollback.sh) |
| §12 | CI/CD workflows | Tasks 25, 26, 27 |
| §12.3 | Annual PAT rotation runbook | Task 34 (calendar reminder) |
| §13 | Cost (no backups) | Task 32 step 8 (Backups: OFF) |
| §16 Q4 | Nexus default-on | Task 5 (default true) |
| §16 Q12 | service_role NEVER on droplet | Task 35 (excluded) |

---

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-04-09-render-to-digitalocean-migration.md`. Two execution options:**

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration. Best for the Phase 1–7 code/config tasks where TDD matters and you want catches between tasks.

**2. Inline Execution** — Execute tasks in this session using `executing-plans`, batch execution with checkpoints. Faster overall but less per-task review.

For Phases 8–13 (external setup, droplet bootstrap, cutover), neither subagent nor inline execution is appropriate — those require human action in the browser, GoDaddy, Cloudflare, DigitalOcean, GitHub, BetterStack, and Telegram. You'll execute those tasks manually following the plan.

**Which approach for Phases 1–7?**
