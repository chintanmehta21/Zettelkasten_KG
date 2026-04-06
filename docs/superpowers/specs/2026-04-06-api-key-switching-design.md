# API Key Switching — Multi-Key Rotation + Content-Aware Model Routing

**Date**: 2026-04-06
**Status**: Draft — pending user approval
**Approach**: A (Centralized Key Pool Manager)
**Research basis**: 2 research subagents (Gemini rate limits, architecture patterns), source code analysis of all 5 Gemini API consumers

---

## Executive Summary

Replace the single `GEMINI_API_KEY` with a pool of up to 10 API keys, rotated automatically on 429 rate-limit errors using key-first traversal (all keys tried for best model before downgrading to next model). Add content-aware routing to direct simple/short content to lighter models and preserve best-model quota for complex content. Deploy keys via a single `api_env` file uploaded to Render's Secret Files feature.

**Capacity improvement** (3 keys, 2 models):
- Before: ~250 RPD (gemini-2.5-flash, single key)
- After: ~750 RPD flash + ~3,000 RPD flash-lite = **~3,750 total RPD**

**New dependencies**: None.
**New files**: 4 files in `website/features/api_key_switching/` (~200 lines total)
**Breaking changes**: None. Single-key setup continues to work unchanged.

---

## Problem Statement

### Current Limitations

1. **Single API key**: All 5 Gemini consumers share one `gemini_api_key` from settings. One rate-limit event throttles the entire system.

2. **Lost cooldown state**: The web pipeline (`website/core/pipeline.py:52`) creates a **new `GeminiSummarizer` per request**, so the `self._cooldowns` dict is discarded after each request. If request A gets rate-limited and sets a cooldown, request B (1 second later) has no idea and hits the same rate limit again.

3. **No content-aware routing**: A 500-word Reddit post and a 15,000-word YouTube transcript both start with `gemini-2.5-flash` (250 RPD limit), wasting premium quota on content that `flash-lite` (1,000 RPD) handles equally well.

4. **Deprecated model in chain**: `gemini-2.0-flash` was deprecated in February 2026 and is being retired. It still sits in `_MODEL_FALLBACK_CHAIN` at position 2.

5. **No embedding fallback**: `embeddings.py` uses a single key with a global cooldown. On a 429, it returns empty vectors (`[]`) silently — the node gets stored without an embedding, losing semantic search capability for that node permanently.

6. **No NL query / entity extractor fallback**: Both use the single key with zero retry/fallback logic. Rate limits cause immediate silent failures.

### Consumers Affected

| # | Consumer | File | Current Key Source | Fallback |
|---|----------|------|--------------------|----------|
| 1 | Summarizer | `telegram_bot/pipeline/summarizer.py` | `api_key` constructor arg | 3-model chain, per-instance cooldowns |
| 2 | Orchestrator | `telegram_bot/pipeline/orchestrator.py:125` | `settings.gemini_api_key` | Delegates to summarizer |
| 3 | Web Pipeline | `website/core/pipeline.py:53` | `settings.gemini_api_key` | Creates fresh summarizer per request (cooldowns lost) |
| 4 | Embeddings | `website/features/kg_features/embeddings.py:36` | `settings.gemini_api_key` | Global cooldown, returns `[]` on failure |
| 5 | NL Query | `website/features/kg_features/nl_query.py:50` | `settings.gemini_api_key` | None — silent failure |
| 6 | Entity Extractor | `website/features/kg_features/entity_extractor.py:82` | `settings.gemini_api_key` | None — silent failure |

---

## Research Findings

### Critical: Quotas Are Per-Project, Not Per-Key

Gemini API rate limits are applied **per Google Cloud project**, not per API key. Multiple API keys within the same GCP project share a single quota bucket. The 3 keys in the pool **must** come from 3 separate Google Cloud projects (or AI Studio accounts) to get independent quota pools.

**Source**: [Gemini API Rate Limits](https://ai.google.dev/gemini-api/docs/rate-limits), [Google Cloud Community discussions](https://support.google.com/gemini/thread/340231779)

### Free-Tier Rate Limits (Post-Dec 2025 Quota Reduction)

| Model | RPM | RPD | TPM | Notes |
|-------|-----|-----|-----|-------|
| `gemini-2.5-flash` | 10 | 250 | 250,000 | Best quality, tightest quota |
| `gemini-2.0-flash` | 5 | ~250 | 250,000 | **Deprecated Feb 2026** — remove from chain |
| `gemini-2.5-flash-lite` | 15 | 1,000 | 250,000 | Good quality, 4x more RPD |
| `gemini-embedding-001` | 100 | 1,000 | batch | Separate quota from generative models |

RPD resets at **midnight Pacific Time**.

Google reduced free-tier quotas by 50-80% on December 6-7, 2025 without prominent announcement.

### Updated Model Fallback Chain

Remove deprecated `gemini-2.0-flash`. New chain:

```
gemini-2.5-flash  →  gemini-2.5-flash-lite
```

Two models instead of three. With key rotation, this gives 2 × N_keys = 6 fallback paths (for 3 keys).

### Embedding Model Determinism

`gemini-embedding-001` is deterministic: identical input text produces **identical 768-dim vectors** regardless of which API key makes the request. The model weights are shared infrastructure — the key is only an authentication credential. Using multiple keys for embeddings has **zero impact** on vector quality or cosine similarity consistency.

Embedding quotas are tracked in a **separate bucket** from generative model quotas. A 429 on `gemini-2.5-flash` does NOT mean `gemini-embedding-001` is also exhausted.

### Key-First Traversal Is Optimal

Research confirms key-first traversal maximizes quality:

```
For each model tier (best → acceptable):
    For each key (key1 → key2 → key3):
        Try (key, model) — skip if on cooldown
```

**Why not model-first?** Model-first (`key1/best → key1/lite → key2/best → key2/lite`) wastes key2's best-model quota. You downgrade quality prematurely when another key's best-model quota is still available.

### Render Secret Files

- Secret Files are uploaded via the Render Dashboard: Service → Environment → Secret Files
- Non-Docker services (our case): the file appears at **both** `/etc/secrets/<filename>` and the **service root directory** (repo root)
- Combined size limit: 1 MB across all secret files per service
- The file named `api_env` will appear as `<repo_root>/api_env` at runtime

### Existing Render Environment Variables (Unchanged)

These remain exactly as-is in the Render dashboard. Nothing changes for them:

| Env Var | Purpose | Status |
|---------|---------|--------|
| `ALLOWED_CHAT_ID` | Telegram chat filter | **Unchanged** |
| `DATA_DIR` | Ephemeral data directory | **Unchanged** |
| `KG_DIRECTORY` | KG output path | **Unchanged** |
| `MODEL_NAME` | Primary model name | **Unchanged** |
| `SUPABASE_ANON_KEY` | Supabase client auth | **Unchanged** |
| `SUPABASE_SERVICE_ROLE_KEY` | Supabase admin auth | **Unchanged** |
| `SUPABASE_URL` | Supabase project URL | **Unchanged** |
| `TELEGRAM_BOT_TOKEN` | Bot authentication | **Unchanged** |
| `WEBHOOK_MODE` | Enable webhook mode | **Unchanged** |
| `WEBHOOK_URL` | Webhook endpoint URL | **Unchanged** |
| `WEBHOOK_PORT` | Server port (10000) | **Unchanged** |
| `WEBHOOK_SECRET` | Webhook validation | **Unchanged** |
| `GITHUB_TOKEN` | GitHub note storage | **Unchanged** |
| `GITHUB_REPO` | GitHub repo for notes | **Unchanged** |
| `GEMINI_API_KEY` | **REMOVED** — replaced by `api_env` Secret File | **Removed** |

---

## Architecture Overview

```
                     Request arrives
                          |
            +-------------+-------------+
            |                           |
    Telegram Bot                  Web UI / API
    (orchestrator)               (routes.py)
            |                           |
            +-------------+-------------+
                          |
                   GeminiKeyPool (singleton)
                   ========================
                   - Owns N genai.Client instances (one per key)
                   - Tracks (key, model) cooldown state globally
                   - Content-aware starting model selection
                   - Key-first traversal across all keys × models
                          |
            +------+------+------+------+
            |      |      |      |      |
         Summ.  Embed.  NL Q.  Entity  Retrieval
         (gen)  (emb)   (gen)  (gen)   (indirect
            |      |      |      |      via embed)
            +------+------+------+------+
                          |
                   Gemini API (via google-genai SDK)
                   Keys from separate GCP projects
```

### Attempt Chain Visualization

For a **long YouTube transcript** (>8000 chars) with 3 keys:

```
1. key1 / gemini-2.5-flash      ← best quality, try first
2. key2 / gemini-2.5-flash      ← same model, different project quota
3. key3 / gemini-2.5-flash      ← third project
4. key1 / gemini-2.5-flash-lite ← downgrade model only after all keys exhausted
5. key2 / gemini-2.5-flash-lite
6. key3 / gemini-2.5-flash-lite
→ If ALL 6 fail: graceful degradation (raw content fallback)
```

For a **short Reddit post** (<2000 chars) with 3 keys:

```
1. key1 / gemini-2.5-flash-lite ← start with efficient model (preserves flash quota)
2. key2 / gemini-2.5-flash-lite
3. key3 / gemini-2.5-flash-lite
4. key1 / gemini-2.5-flash      ← upgrade if all lite quota exhausted
5. key2 / gemini-2.5-flash
6. key3 / gemini-2.5-flash
→ If ALL 6 fail: graceful degradation
```

For **embeddings** (single model, key rotation only):

```
1. key1 / gemini-embedding-001
2. key2 / gemini-embedding-001
3. key3 / gemini-embedding-001
→ If ALL 3 fail: return [] (existing behavior)
```

---

## Module Design

### File Structure

```
website/features/api_key_switching/
├── __init__.py          # exports get_key_pool(), init_key_pool()
├── key_pool.py          # GeminiKeyPool singleton — the core module
├── routing.py           # Content-aware starting model selection
└── api_env.example      # Template for Render Secret File upload
```

At runtime, the actual keys file lives at the **project root** (not inside the feature dir):

```
<project_root>/
└── api_env              # Actual keys file (in .gitignore, NOT committed)
                         # Created by copying api_env.example and filling in real keys
                         # On Render: uploaded as Secret File, appears at repo root automatically
```

### M1: `api_env` File Format

The `api_env` file uses the simplest possible format: **one API key per line**, with `#` comments and blank lines ignored. No JSON, no commas, no dotenv syntax — just raw keys.

```
# Gemini API Key Pool
# One key per line. Each key should be from a SEPARATE Google Cloud project.
# Quotas are per-project, not per-key — same-project keys share quota.
#
# Upload this file as a Secret File named "api_env" on Render.
# It will be available at /etc/secrets/api_env and at the repo root.

AIzaSyA_your_first_project_key_here
AIzaSyB_your_second_project_key_here
AIzaSyC_your_third_project_key_here
```

**Why not dotenv format?** Dotenv requires `KEY=value` syntax, and multi-line values need quoting hacks. Since this file contains ONLY API keys (no variable names, no other config), a simpler one-per-line format is cleaner and less error-prone. The key pool module reads this file directly — it does not go through Pydantic's env file loading.

**File search order** (first found wins):

1. `<project_root>/api_env` — local development
2. `/etc/secrets/api_env` — Render Secret File (Docker path)

### M2: `key_pool.py` — GeminiKeyPool

The central module. A singleton class that all consumers import.

```python
"""Centralized Gemini API key pool with multi-key rotation and model fallback.

Manages N API keys (from separate GCP projects) with per-(key, model) cooldown
tracking. Provides two entry points:

  - generate_content() — for summarization, NL query, entity extraction
  - embed_content()    — for embedding generation (single model, key rotation)

Traversal order is key-first: all keys are tried for the best model before
falling back to the next model tier. This maximizes summary quality.

Cooldown state is global (singleton), so all consumers — including per-request
web pipeline instances — share the same rate-limit awareness.
"""
```

#### Class Interface

```python
class GeminiKeyPool:
    """Pool of Gemini API clients with automatic key/model rotation."""

    def __init__(self, api_keys: list[str]) -> None:
        """Initialize with a list of API keys from separate GCP projects.

        Creates one genai.Client per key, lazily (on first use).
        Raises ValueError if api_keys is empty.
        """

    # ── Generative (summarization, NL query, entity extraction) ──────

    async def generate_content(
        self,
        contents,
        *,
        config: dict | None = None,
        starting_model: str | None = None,
        label: str = "",
    ) -> tuple[response, str, int]:
        """Generate content with automatic key/model fallback.

        Args:
            contents: Prompt content (string, list of Parts, etc.)
            config: Generation config (temperature, max_tokens, etc.)
            starting_model: Override the first model to try.
                If None, starts with the best model (gemini-2.5-flash).
            label: Logging label for this request.

        Returns:
            (response, model_used, key_index) on success.

        Raises:
            Last exception if ALL (key, model) combinations fail.
        """

    # ── Embedding (single model, key rotation only) ──────────────────

    def embed_content(
        self,
        contents,
        *,
        config: dict | None = None,
    ) -> response:
        """Embed content with automatic key rotation.

        Tries all keys for gemini-embedding-001. Returns the first
        successful response. Raises on total failure.
        """

    def embed_content_safe(
        self,
        contents,
        *,
        config: dict | None = None,
    ) -> response | None:
        """Like embed_content, but returns None instead of raising.

        Preserves current behavior where embeddings fail silently.
        """

    # ── Internal ─────────────────────────────────────────────────────

    def _get_client(self, key_index: int) -> genai.Client:
        """Return (lazily create) the genai.Client for key at index."""

    def _build_attempt_chain(
        self,
        starting_model: str | None = None,
    ) -> list[tuple[int, str]]:
        """Build the (key_index, model) attempt chain.

        Key-first traversal: for each model tier, try all keys before
        moving to the next model.

        Skips (key, model) pairs currently on cooldown.
        If ALL pairs are on cooldown, returns the full chain anyway.
        """

    def _mark_cooldown(self, key_index: int, model: str) -> None:
        """Put (key_index, model) on cooldown for 60 seconds."""
```

#### State Tracking

```python
@dataclass
class _SlotState:
    """Cooldown state for one (key, model) combination."""
    cooldown_expires: float = 0.0  # time.monotonic() value

# Internal state: dict[(key_index, model_name)] → _SlotState
# Example with 3 keys, 2 generative models, 1 embedding model:
#   (0, "gemini-2.5-flash")      → _SlotState(cooldown_expires=0.0)
#   (0, "gemini-2.5-flash-lite") → _SlotState(cooldown_expires=0.0)
#   (0, "gemini-embedding-001")  → _SlotState(cooldown_expires=0.0)
#   (1, "gemini-2.5-flash")      → _SlotState(...)
#   ... total: 3 keys × 3 models = 9 slots
```

Thread-safety note: In single-threaded asyncio (our case), dict mutations between `await` points are safe without locks. No `asyncio.Lock` needed for the cooldown dict — the GIL + cooperative scheduling guarantees atomicity of dict operations between suspension points.

#### Cooldown Mechanics

- On a 429 response: `_mark_cooldown(key_index, model)` sets `cooldown_expires = time.monotonic() + 60`
- On next request: `_build_attempt_chain()` skips slots where `cooldown_expires > now`
- Expired cooldowns are purged lazily during chain building
- If ALL slots are on cooldown: return the full chain anyway (better to retry than refuse)
- Cooldown duration: 60 seconds (matches existing `_RATE_LIMIT_COOLDOWN_SECS`)

#### Rate-Limit Detection

Reuse the existing detection logic from `summarizer.py`:

```python
def _is_rate_limited(exc: Exception) -> bool:
    """Return True if exc is a Gemini 429 rate-limit error."""
    if isinstance(exc, ClientError) and getattr(exc, "code", None) == 429:
        return True
    return "429" in str(exc) and "RESOURCE_EXHAUSTED" in str(exc)
```

#### Generative Model Chain

```python
_GENERATIVE_MODEL_CHAIN = [
    "gemini-2.5-flash",       # best quality, 250 RPD / 10 RPM per project
    "gemini-2.5-flash-lite",  # good quality, 1000 RPD / 15 RPM per project
]
# gemini-2.0-flash REMOVED — deprecated Feb 2026
```

#### Embedding Model

```python
_EMBEDDING_MODEL = "gemini-embedding-001"  # 1000 RPD / 100 RPM per project
```

No model fallback for embeddings — only key rotation.

### M3: `routing.py` — Content-Aware Model Selection

Determines which model tier to start with based on content characteristics. This is a **starting point**, not a hard assignment — if the starting model is rate-limited, the pool falls through to the next model.

```python
"""Content-aware starting model selection.

Routes content to the most appropriate starting model tier based on:
  - Content length (body character count)
  - Source type (YouTube, GitHub, newsletter → complex; Reddit, generic → simple)

This is a suggestion, not a constraint. The key pool still falls through
the full attempt chain on rate limits.
"""

def select_starting_model(
    content_length: int,
    source_type: str | None = None,
) -> str:
    """Select the starting model based on content characteristics.

    Routing matrix:
    ┌─────────────────────────┬───────────────────┬─────────────────────────────┐
    │ Content Profile         │ Starting Model    │ Rationale                   │
    ├─────────────────────────┼───────────────────┼─────────────────────────────┤
    │ Long (>8000 chars)      │ gemini-2.5-flash  │ Needs strong summarization  │
    │ YouTube (any length)    │ gemini-2.5-flash  │ Complex video/transcript    │
    │ Newsletter (any length) │ gemini-2.5-flash  │ Long-form, nuanced content  │
    │ GitHub (any length)     │ gemini-2.5-flash  │ Code-heavy, needs precision │
    │ Medium (2000-8000)      │ gemini-2.5-flash  │ Moderate complexity         │
    │ Short (<2000 chars)     │ flash-lite        │ Simple, preserves quota     │
    │ Reddit (short)          │ flash-lite        │ Usually brief discussions   │
    │ Generic web (short)     │ flash-lite        │ Short articles              │
    └─────────────────────────┴───────────────────┴─────────────────────────────┘

    The threshold of 2000 chars (~500 words) was chosen because:
    - Below this, both models produce near-identical summary quality
    - flash-lite has 4x the RPD quota (1000 vs 250)
    - Routing short content to flash-lite preserves flash quota for complex content

    Returns:
        Model name string.
    """
```

The routing function is called by the consumer (summarizer, NL query, etc.) and passed to `pool.generate_content(starting_model=...)`. Consumers that don't have content metadata (like NL query, which processes user questions) can omit `starting_model` to default to the best model.

### M4: `__init__.py` — Module Interface

```python
"""API Key Switching — multi-key rotation for Gemini API.

Usage:
    from website.features.api_key_switching import get_key_pool

    pool = get_key_pool()
    response, model, key_idx = await pool.generate_content(prompt)
"""

_pool: GeminiKeyPool | None = None

def init_key_pool() -> GeminiKeyPool:
    """Initialize the global key pool. Called once at app startup.

    Key loading priority (first non-empty source wins):
      1. api_env file at <project_root>/api_env (local dev)
      2. api_env file at /etc/secrets/api_env (Render Secret File)
      3. settings.gemini_api_key (backward compat with single key)

    Returns the initialized pool.
    Raises ValueError if no keys found from any source.
    """

def get_key_pool() -> GeminiKeyPool:
    """Return the global key pool singleton.

    Auto-initializes on first call if init_key_pool() hasn't been called.
    """
```

---

## Integration Changes

### 1. `telegram_bot/pipeline/summarizer.py`

**Changes:**
- Import `get_key_pool` from `website.features.api_key_switching`
- Import `select_starting_model` from `website.features.api_key_switching.routing`
- `GeminiSummarizer.__init__()`: Replace `self._client = genai.Client(api_key=api_key)` with `self._pool = get_key_pool()`. Remove `api_key` parameter.
- `GeminiSummarizer._generate_with_fallback()`: Delegate to `self._pool.generate_content()` instead of iterating models internally. Pass `starting_model` based on content.
- Remove `self._cooldowns` dict — the pool tracks cooldowns globally.
- Remove `_build_model_chain()` — the pool builds the attempt chain.
- Remove `_MODEL_FALLBACK_CHAIN` constant — moved to pool.
- Keep `_is_rate_limited()` — moved to pool (or shared utility).
- Keep `_SYSTEM_PROMPT`, `_USER_PROMPT_TEMPLATE`, `_parse_response()`, `build_tag_list()` — unchanged.
- Constructor signature: `GeminiSummarizer(api_key: str = "", model_name: str = "gemini-2.5-flash")` — `api_key` kept for backward compatibility (tests pass it) but ignored internally. The pool handles key management. A deprecation log is emitted if `api_key` is passed.

### 2. `telegram_bot/pipeline/orchestrator.py`

**Changes:**
- Remove `api_key=settings.gemini_api_key` from `GeminiSummarizer()` constructor call.
- Pass `source_type` to summarizer so it can compute content-aware routing.
- Everything else unchanged.

### 3. `website/core/pipeline.py`

**Changes:**
- Remove `api_key=settings.gemini_api_key` from `GeminiSummarizer()` constructor call.
- The critical fix: since the pool is a singleton, cooldown state is now **shared across all web requests**. No more lost cooldown tracking per-request.
- Pass `content_length=len(extracted.body)` and `source_type=source_type.value` for routing.

### 4. `website/features/kg_features/embeddings.py`

**Changes:**
- Remove `_get_genai_client()` function (cached single-key client).
- Remove `_last_rate_limit_ts` global variable and cooldown logic.
- Import `get_key_pool` from `website.features.api_key_switching`.
- `generate_embedding()`: Call `pool.embed_content_safe()` instead of `client.models.embed_content()`. The pool handles key rotation and cooldowns.
- `generate_embeddings_batch()`: Same — delegate to pool.
- `find_similar_nodes()` and `should_create_semantic_link()`: **Unchanged** — these don't use the API directly.

### 5. `website/features/kg_features/nl_query.py`

**Changes:**
- Remove `_get_genai_client()` function.
- Import `get_key_pool`.
- Replace `client.models.generate_content(model=model, ...)` calls with `pool.generate_content(contents, starting_model=model, ...)`.
- The pool handles retries across keys — NL query no longer fails silently on a single 429.

### 6. `website/features/kg_features/entity_extractor.py`

**Changes:**
- Remove `_get_genai_client()` function.
- Import `get_key_pool`.
- Replace `client.models.generate_content(model=model, ...)` calls with `pool.generate_content()`.
- Entity extraction has 3 sequential Gemini calls (analysis → structured → gleaning). Each call independently uses the pool, so a rate limit mid-extraction can recover by switching keys.

### 7. `telegram_bot/config/settings.py`

**Changes**: **None.**

The `gemini_api_key: str = ""` field remains for backward compatibility. If no `api_env` file exists, the pool falls back to `settings.gemini_api_key`. All existing env var loading, validation, and config sources work identically.

No new fields added to Settings. The key pool reads its own `api_env` file independently.

### 8. `.gitignore`

**Changes**: Add `api_env` entry to ignore the actual secrets file.

```gitignore
# API key switching — actual keys file (never commit)
api_env
```

The `.env` / `.env.*` patterns in gitignore already cover dotenv files, but `api_env` doesn't match those patterns, so it needs an explicit entry.

### 9. App Startup (webhook mode)

The pool auto-initializes on first `get_key_pool()` call. No explicit startup wiring needed. However, for early failure detection (e.g., missing keys), `init_key_pool()` can be called in the FastAPI lifespan:

```python
# website/app.py (existing lifespan context manager)
from website.features.api_key_switching import init_key_pool

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_key_pool()  # Fail fast if no keys configured
    # ... existing startup code ...
```

---

## Configuration

### Key Loading — Priority Order

The pool uses a clear priority chain. The **first non-empty source wins**:

```
1. api_env file at <project_root>/api_env     ← local development
2. api_env file at /etc/secrets/api_env        ← Render Secret File
3. settings.gemini_api_key (single key)        ← backward compatibility
```

This means:
- **Render deployment**: Upload `api_env` as a Secret File. Remove `GEMINI_API_KEY` from env vars. Done.
- **Local development**: Place `api_env` in the project root (gitignored). Or keep using `.env` with `GEMINI_API_KEY=...` — works as before.
- **Tests**: Mock `get_key_pool()` — no real keys needed.
- **CI**: Set `GEMINI_API_KEY=test-key` in env — backward compat path.

### Render Deployment Steps

1. Go to Render Dashboard → your service → Environment
2. **Remove** `GEMINI_API_KEY` from Environment Variables
3. Under **Secret Files**, click "+ Add file"
4. Filename: `api_env`
5. Paste your keys (one per line):
   ```
   AIzaSyA_first_project_key
   AIzaSyB_second_project_key
   AIzaSyC_third_project_key
   ```
6. Click "Save Changes" (triggers redeploy)
7. All other env vars remain unchanged

### Backward Compatibility Matrix

| Setup | Behavior |
|-------|----------|
| `api_env` file with 3 keys | Pool uses 3 keys with rotation |
| `api_env` file with 1 key | Pool uses 1 key (equivalent to current) |
| No `api_env`, `GEMINI_API_KEY` set | Pool uses single key (backward compat) |
| No `api_env`, no `GEMINI_API_KEY` | `ValueError` at pool init (same as current `GeminiSummarizer`) |
| `api_env` exists AND `GEMINI_API_KEY` set | `api_env` wins (priority 1 > priority 3) |

---

## Error Handling & Graceful Degradation

### Hierarchy of Fallback

```
Level 1: Try next key (same model)
    ↓ all keys exhausted for this model
Level 2: Try next model tier (reset keys)
    ↓ all models exhausted across all keys
Level 3: Graceful degradation
```

### Per-Consumer Degradation

| Consumer | On Total Failure | Behavior |
|----------|-----------------|----------|
| Summarizer | Returns raw content | `is_raw_fallback=True`, content saved for manual review |
| Embeddings | Returns `[]` | Node stored without embedding, loses semantic search for that node |
| NL Query | Returns error message | User sees "query failed" in UI |
| Entity Extractor | Skips extraction | Node stored without entity metadata |

These match existing degradation behaviors — the pool doesn't change failure semantics, it just makes failures much less likely by providing more fallback paths.

### Logging

Every key/model switch is logged at WARNING level:

```
WARNING: Summarization rate-limited on key[0]/gemini-2.5-flash — cooldown 60s, trying key[1]/gemini-2.5-flash
WARNING: Summarization rate-limited on key[1]/gemini-2.5-flash — cooldown 60s, trying key[2]/gemini-2.5-flash
WARNING: Summarization rate-limited on key[2]/gemini-2.5-flash — cooldown 60s, trying key[0]/gemini-2.5-flash-lite
INFO: Summarization succeeded on key[0]/gemini-2.5-flash-lite (tokens: 1523, latency: 2340ms)
```

Key indices (not actual key values) are logged to avoid leaking secrets.

---

## Testing Strategy

### Unit Tests

1. **Key pool initialization**: Test all 3 key sources (api_env file, single key, no keys)
2. **Attempt chain building**: Verify key-first traversal order with 1, 2, 3 keys
3. **Cooldown tracking**: Mark slots on cooldown, verify they're skipped in chain
4. **All-on-cooldown**: Verify full chain returned when everything is on cooldown
5. **Content-aware routing**: Verify model selection for various content lengths and source types
6. **Rate-limit detection**: Verify `_is_rate_limited()` catches both ClientError and string-match cases
7. **Backward compatibility**: Verify single-key fallback from settings

### Integration Points

8. **Summarizer integration**: Verify `GeminiSummarizer` delegates to pool correctly
9. **Embedding integration**: Verify `generate_embedding()` uses pool
10. **Web pipeline**: Verify cooldown state is shared across requests (the critical fix)

### Mocking Strategy

All tests mock `genai.Client` — no real API calls. The pool creates clients lazily, so tests inject mock clients via a test helper:

```python
def _make_pool_with_mocks(n_keys: int = 3) -> GeminiKeyPool:
    pool = GeminiKeyPool(["fake-key"] * n_keys)
    pool._clients = {i: Mock() for i in range(n_keys)}
    return pool
```

---

## Migration Path

### Phase 1: Add Key Pool (non-breaking)

1. Create `website/features/api_key_switching/` with all 4 files
2. Add `api_env` to `.gitignore`
3. Create `api_env.example` template
4. No consumer changes yet — pool exists but isn't used

### Phase 2: Integrate Consumers

5. Update `summarizer.py` to use pool
6. Update `orchestrator.py` (remove `api_key` arg)
7. Update `website/core/pipeline.py` (remove `api_key` arg)
8. Update `embeddings.py` to use pool
9. Update `nl_query.py` to use pool
10. Update `entity_extractor.py` to use pool

### Phase 3: Deploy

11. Create `api_env` with actual keys
12. Upload to Render as Secret File
13. Remove `GEMINI_API_KEY` from Render env vars
14. Deploy and verify via logs

---

## Capacity Planning

### With 3 Keys (Current Plan)

| Model | Per-Key RPD | 3 Keys RPD | Per-Key RPM | 3 Keys RPM |
|-------|-------------|------------|-------------|------------|
| gemini-2.5-flash | 250 | **750** | 10 | 30 |
| gemini-2.5-flash-lite | 1,000 | **3,000** | 15 | 45 |
| gemini-embedding-001 | 1,000 | **3,000** | 100 | 300 |

**Total generative capacity**: ~3,750 RPD (vs current ~250 RPD = **15x improvement**)

With content-aware routing sending ~70% of content to flash-lite:
- flash: ~225 requests/day (30% of traffic × 750 RPD budget)
- flash-lite: ~2,100 requests/day (70% of traffic × 3000 RPD budget)
- **Effective daily throughput: ~2,325 summarizations/day**

### With 10 Keys (Maximum Supported)

| Model | 10 Keys RPD | 10 Keys RPM |
|-------|-------------|-------------|
| gemini-2.5-flash | **2,500** | 100 |
| gemini-2.5-flash-lite | **10,000** | 150 |
| gemini-embedding-001 | **10,000** | 1,000 |

---

## Open Questions (Resolved)

| Question | Resolution |
|----------|-----------|
| Will different keys produce different embeddings? | No — deterministic model, identical vectors regardless of key |
| Should we use LiteLLM? | No — overkill for Gemini-only; ~200 lines on existing code suffices |
| Comma-separated vs JSON vs one-per-line for keys? | One-per-line in api_env file (simplest, most readable) |
| Should settings.py change? | No — pool reads api_env independently; settings unchanged |
| How to handle deprecated gemini-2.0-flash? | Remove from chain entirely |
| async safety for cooldown dict? | Safe in single-threaded asyncio (no Lock needed) |
