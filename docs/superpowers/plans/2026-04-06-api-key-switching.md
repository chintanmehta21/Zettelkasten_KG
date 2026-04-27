# API Key Switching Implementation Plan

> **ARCHIVED CONTEXT — pre-migration plan.** Written while the app was hosted on Render.com (legacy, no longer used). Any "Render Secret Files" / Render-dashboard step is historical. The `api_env` file format and `/etc/secrets/api_env` path are still used, but mounted into the DigitalOcean droplet container today, not Render. See "Deployment Infrastructure (Canonical)" in the project root `CLAUDE.md` for the live setup.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the single Gemini API key with a pool of up to 10 keys, rotated automatically on rate limits using key-first traversal, with content-aware model routing.

**Architecture:** A centralized `GeminiKeyPool` singleton in `website/features/api_key_switching/` manages N `genai.Client` instances with per-(key, model) cooldown tracking. All 6 Gemini API consumers (summarizer, orchestrator, web pipeline, embeddings, NL query, entity extractor) are rewired to use the pool. Keys are loaded from a simple one-per-line `api_env` file.

**Tech Stack:** Python 3.12, google-genai SDK, Pydantic, pytest, asyncio. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-04-06-api-key-switching-design.md`

---

## File Map

| Action | File | Responsibility |
|--------|------|----------------|
| Create | `website/features/api_key_switching/__init__.py` | Module interface: `get_key_pool()`, `init_key_pool()` |
| Create | `website/features/api_key_switching/key_pool.py` | `GeminiKeyPool` class: key rotation, model fallback, cooldowns |
| Create | `website/features/api_key_switching/routing.py` | `select_starting_model()`: content-aware model selection |
| Create | `tests/test_key_pool.py` | Tests for pool init, attempt chain, cooldowns, key rotation |
| Create | `tests/test_routing.py` | Tests for content-aware model selection |
| Modify | `telegram_bot/pipeline/summarizer.py` | Replace self-managed client/cooldowns with pool delegation |
| Modify | `telegram_bot/pipeline/orchestrator.py:124-127` | Remove `api_key=` arg from GeminiSummarizer constructor |
| Modify | `website/core/pipeline.py:52-55` | Remove `api_key=` arg, pass routing hints |
| Modify | `website/features/kg_features/embeddings.py` | Replace `_get_genai_client()` + global cooldown with pool |
| Modify | `website/features/kg_features/nl_query.py:46-50` | Replace `_get_genai_client()` with pool |
| Modify | `website/features/kg_features/entity_extractor.py:78-82` | Replace `_get_genai_client()` with pool |
| Modify | `tests/test_model_fallback.py` | Update tests for new summarizer interface |
| Modify | `tests/test_gemini.py` | Update mock target for new summarizer interface |
| Already done | `.gitignore` | `api_env` entry already added |
| Already done | `website/features/api_key_switching/api_env.example` | Template already created |

---

## Task 1: Content-Aware Routing Module

**Files:**
- Create: `website/features/api_key_switching/routing.py`
- Create: `tests/test_routing.py`

This is a pure function with zero dependencies — ideal to start with.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_routing.py
"""Tests for content-aware starting model selection."""

from website.features.api_key_switching.routing import select_starting_model

# ── Best model for complex/long content ─────────────────────────────────────


def test_long_content_uses_flash():
    """Content >8000 chars always routes to gemini-2.5-flash."""
    assert select_starting_model(content_length=9000) == "gemini-2.5-flash"


def test_youtube_always_uses_flash():
    """YouTube content routes to flash regardless of length."""
    assert select_starting_model(content_length=500, source_type="youtube") == "gemini-2.5-flash"


def test_newsletter_always_uses_flash():
    """Newsletter content routes to flash regardless of length."""
    assert select_starting_model(content_length=1000, source_type="newsletter") == "gemini-2.5-flash"


def test_github_always_uses_flash():
    """GitHub content routes to flash regardless of length."""
    assert select_starting_model(content_length=800, source_type="github") == "gemini-2.5-flash"


def test_medium_content_uses_flash():
    """Content between 2000-8000 chars routes to flash."""
    assert select_starting_model(content_length=5000) == "gemini-2.5-flash"


# ── Lite model for simple/short content ─────────────────────────────────────


def test_short_content_uses_lite():
    """Content <2000 chars routes to flash-lite."""
    assert select_starting_model(content_length=500) == "gemini-2.5-flash-lite"


def test_short_reddit_uses_lite():
    """Short Reddit content routes to flash-lite."""
    assert select_starting_model(content_length=800, source_type="reddit") == "gemini-2.5-flash-lite"


def test_short_web_uses_lite():
    """Short generic web content routes to flash-lite."""
    assert select_starting_model(content_length=1500, source_type="web") == "gemini-2.5-flash-lite"


# ── Edge cases ──────────────────────────────────────────────────────────────


def test_exactly_2000_uses_flash():
    """Boundary: exactly 2000 chars routes to flash (>= 2000 threshold)."""
    assert select_starting_model(content_length=2000) == "gemini-2.5-flash"


def test_no_source_type_short():
    """No source type + short content → flash-lite."""
    assert select_starting_model(content_length=100, source_type=None) == "gemini-2.5-flash-lite"


def test_no_source_type_long():
    """No source type + long content → flash."""
    assert select_starting_model(content_length=10000, source_type=None) == "gemini-2.5-flash"
```

- [ ] **Step 2: Create the routing module (make tests pass)**

```python
# website/features/api_key_switching/routing.py
"""Content-aware starting model selection.

Routes content to the most appropriate starting model tier based on
content length and source type. This is a suggestion, not a constraint —
the key pool still falls through the full attempt chain on rate limits.
"""

from __future__ import annotations

# Models available in the generative fallback chain.
_BEST_MODEL = "gemini-2.5-flash"
_LITE_MODEL = "gemini-2.5-flash-lite"

# Source types that always warrant the best model.
_COMPLEX_SOURCES = frozenset({"youtube", "newsletter", "github"})

# Content shorter than this (chars) uses the lite model when the source
# type doesn't force the best model.
_SHORT_THRESHOLD = 2000


def select_starting_model(
    content_length: int,
    source_type: str | None = None,
) -> str:
    """Select the starting model based on content characteristics.

    Returns the model name to try first.  The key pool will fall through
    to the other model if this one is rate-limited.
    """
    # Complex sources always get the best model.
    if source_type in _COMPLEX_SOURCES:
        return _BEST_MODEL

    # Long or medium content gets the best model.
    if content_length >= _SHORT_THRESHOLD:
        return _BEST_MODEL

    # Short, non-complex content uses the lite model.
    return _LITE_MODEL
```

- [ ] **Step 3: Run tests**

Run: `pytest tests/test_routing.py -v`
Expected: All 12 tests PASS.

- [ ] **Step 4: Commit**

```bash
git add website/features/api_key_switching/routing.py tests/test_routing.py
git commit -m "feat(api-keys): add content-aware model routing"
```

---

## Task 2: GeminiKeyPool Core — File Loading + Attempt Chain

**Files:**
- Create: `website/features/api_key_switching/key_pool.py`
- Create: `tests/test_key_pool.py` (first batch: init + chain building)

- [ ] **Step 1: Write the failing tests for key loading and attempt chain**

```python
# tests/test_key_pool.py
"""Tests for GeminiKeyPool: initialization, attempt chain, cooldowns."""

import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from google.genai.errors import ClientError


# ── Key loading tests ───────────────────────────────────────────────────────


def test_pool_init_with_keys():
    """Pool initializes successfully with a list of API keys."""
    from website.features.api_key_switching.key_pool import GeminiKeyPool

    pool = GeminiKeyPool(["key-a", "key-b", "key-c"])
    assert pool._keys == ["key-a", "key-b", "key-c"]
    assert pool._clients == {}  # lazily created


def test_pool_init_empty_list_raises():
    """Pool raises ValueError if no keys are provided."""
    from website.features.api_key_switching.key_pool import GeminiKeyPool

    with pytest.raises(ValueError, match="at least one"):
        GeminiKeyPool([])


def test_pool_init_max_10_keys():
    """Pool accepts up to 10 keys."""
    from website.features.api_key_switching.key_pool import GeminiKeyPool

    pool = GeminiKeyPool([f"key-{i}" for i in range(10)])
    assert len(pool._keys) == 10


def test_pool_init_over_10_raises():
    """Pool raises ValueError if more than 10 keys are provided."""
    from website.features.api_key_switching.key_pool import GeminiKeyPool

    with pytest.raises(ValueError, match="maximum.*10"):
        GeminiKeyPool([f"key-{i}" for i in range(11)])


def test_load_keys_from_file(tmp_path):
    """Keys are loaded from a one-per-line api_env file."""
    from website.features.api_key_switching.key_pool import _load_keys_from_file

    env_file = tmp_path / "api_env"
    env_file.write_text(
        "# comment line\n"
        "AIzaSyA_key_one\n"
        "\n"
        "  AIzaSyB_key_two  \n"
        "# another comment\n"
        "AIzaSyC_key_three\n"
    )
    keys = _load_keys_from_file(str(env_file))
    assert keys == ["AIzaSyA_key_one", "AIzaSyB_key_two", "AIzaSyC_key_three"]


def test_load_keys_from_file_nonexistent():
    """Returns empty list for a nonexistent file."""
    from website.features.api_key_switching.key_pool import _load_keys_from_file

    keys = _load_keys_from_file("/nonexistent/path/api_env")
    assert keys == []


def test_load_keys_from_file_empty(tmp_path):
    """Returns empty list for an empty file (only comments/blanks)."""
    from website.features.api_key_switching.key_pool import _load_keys_from_file

    env_file = tmp_path / "api_env"
    env_file.write_text("# only comments\n\n")
    keys = _load_keys_from_file(str(env_file))
    assert keys == []


# ── Attempt chain building ──────────────────────────────────────────────────


def test_chain_key_first_traversal_3_keys():
    """With 3 keys and default (best) starting model, chain is key-first."""
    from website.features.api_key_switching.key_pool import GeminiKeyPool

    pool = GeminiKeyPool(["k0", "k1", "k2"])
    chain = pool._build_attempt_chain()
    assert chain == [
        (0, "gemini-2.5-flash"),
        (1, "gemini-2.5-flash"),
        (2, "gemini-2.5-flash"),
        (0, "gemini-2.5-flash-lite"),
        (1, "gemini-2.5-flash-lite"),
        (2, "gemini-2.5-flash-lite"),
    ]


def test_chain_key_first_traversal_1_key():
    """With 1 key, chain degrades to model-only fallback."""
    from website.features.api_key_switching.key_pool import GeminiKeyPool

    pool = GeminiKeyPool(["k0"])
    chain = pool._build_attempt_chain()
    assert chain == [
        (0, "gemini-2.5-flash"),
        (0, "gemini-2.5-flash-lite"),
    ]


def test_chain_lite_starting_model():
    """Starting with flash-lite reverses the model order."""
    from website.features.api_key_switching.key_pool import GeminiKeyPool

    pool = GeminiKeyPool(["k0", "k1"])
    chain = pool._build_attempt_chain(starting_model="gemini-2.5-flash-lite")
    assert chain == [
        (0, "gemini-2.5-flash-lite"),
        (1, "gemini-2.5-flash-lite"),
        (0, "gemini-2.5-flash"),
        (1, "gemini-2.5-flash"),
    ]


def test_chain_skips_cooled_down_slots():
    """Slots on cooldown are excluded from the chain."""
    from website.features.api_key_switching.key_pool import GeminiKeyPool

    pool = GeminiKeyPool(["k0", "k1", "k2"])
    pool._mark_cooldown(0, "gemini-2.5-flash")
    pool._mark_cooldown(1, "gemini-2.5-flash")

    chain = pool._build_attempt_chain()
    # Only key2 should remain for flash; all keys for lite
    assert chain == [
        (2, "gemini-2.5-flash"),
        (0, "gemini-2.5-flash-lite"),
        (1, "gemini-2.5-flash-lite"),
        (2, "gemini-2.5-flash-lite"),
    ]


def test_chain_expired_cooldown_restored():
    """Slots whose cooldown has expired are included again."""
    from website.features.api_key_switching.key_pool import GeminiKeyPool

    pool = GeminiKeyPool(["k0", "k1"])
    # Expired cooldown (in the past)
    pool._cooldowns[(0, "gemini-2.5-flash")] = time.monotonic() - 1

    chain = pool._build_attempt_chain()
    # key0/flash should be back in the chain
    assert (0, "gemini-2.5-flash") in chain


def test_chain_all_on_cooldown_returns_full():
    """If every slot is on cooldown, the full chain is returned anyway."""
    from website.features.api_key_switching.key_pool import GeminiKeyPool

    pool = GeminiKeyPool(["k0", "k1"])
    far_future = time.monotonic() + 9999
    pool._cooldowns[(0, "gemini-2.5-flash")] = far_future
    pool._cooldowns[(1, "gemini-2.5-flash")] = far_future
    pool._cooldowns[(0, "gemini-2.5-flash-lite")] = far_future
    pool._cooldowns[(1, "gemini-2.5-flash-lite")] = far_future

    chain = pool._build_attempt_chain()
    assert len(chain) == 4  # full chain returned


def test_chain_embedding_model():
    """Embedding chain is key-rotation only (single model)."""
    from website.features.api_key_switching.key_pool import GeminiKeyPool

    pool = GeminiKeyPool(["k0", "k1", "k2"])
    chain = pool._build_embedding_chain()
    assert chain == [(0, "gemini-embedding-001"), (1, "gemini-embedding-001"), (2, "gemini-embedding-001")]


def test_chain_embedding_skips_cooldown():
    """Embedding chain skips cooled-down key/model slots."""
    from website.features.api_key_switching.key_pool import GeminiKeyPool

    pool = GeminiKeyPool(["k0", "k1"])
    pool._mark_cooldown(0, "gemini-embedding-001")

    chain = pool._build_embedding_chain()
    assert chain == [(1, "gemini-embedding-001")]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_key_pool.py -v`
Expected: FAIL — `ImportError: cannot import name 'GeminiKeyPool'`

- [ ] **Step 3: Implement key_pool.py**

```python
# website/features/api_key_switching/key_pool.py
"""Centralized Gemini API key pool with multi-key rotation and model fallback.

Manages N API keys (from separate GCP projects) with per-(key, model) cooldown
tracking.  Provides two entry points:

  - generate_content() — for summarization, NL query, entity extraction
  - embed_content()    — for embedding generation (single model, key rotation)

Traversal order is key-first: all keys are tried for the best model before
falling back to the next model tier.  This maximizes summary quality.

Cooldown state is global (singleton), so all consumers — including per-request
web pipeline instances — share the same rate-limit awareness.
"""

from __future__ import annotations

import logging
import time

from google import genai
from google.genai.errors import ClientError

logger = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────────────────

_MAX_KEYS = 10
_RATE_LIMIT_COOLDOWN_SECS = 60

_GENERATIVE_MODEL_CHAIN = [
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
]

_EMBEDDING_MODEL = "gemini-embedding-001"


# ── Helpers ──────────────────────────────────────────────────────────────────

def _is_rate_limited(exc: Exception) -> bool:
    """Return True if *exc* is a Gemini 429 rate-limit error."""
    if isinstance(exc, ClientError) and getattr(exc, "code", None) == 429:
        return True
    return "429" in str(exc) and "RESOURCE_EXHAUSTED" in str(exc)


def _load_keys_from_file(path: str) -> list[str]:
    """Read API keys from an api_env file.  One key per line, # comments ignored."""
    try:
        with open(path) as f:
            keys = []
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                keys.append(line)
            return keys
    except FileNotFoundError:
        return []


# ── GeminiKeyPool ────────────────────────────────────────────────────────────

class GeminiKeyPool:
    """Pool of Gemini API clients with automatic key/model rotation."""

    def __init__(self, api_keys: list[str]) -> None:
        if not api_keys:
            raise ValueError("GeminiKeyPool requires at least one API key")
        if len(api_keys) > _MAX_KEYS:
            raise ValueError(f"GeminiKeyPool supports a maximum of {_MAX_KEYS} keys")

        self._keys = list(api_keys)
        self._clients: dict[int, genai.Client] = {}
        # (key_index, model_name) → cooldown expiry (monotonic timestamp)
        self._cooldowns: dict[tuple[int, str], float] = {}

    # ── Client management ────────────────────────────────────────────

    def _get_client(self, key_index: int) -> genai.Client:
        """Return (lazily create) the genai.Client for key at *key_index*."""
        if key_index not in self._clients:
            self._clients[key_index] = genai.Client(api_key=self._keys[key_index])
        return self._clients[key_index]

    # ── Cooldown management ──────────────────────────────────────────

    def _mark_cooldown(self, key_index: int, model: str) -> None:
        """Put (key_index, model) on cooldown for 60 seconds."""
        self._cooldowns[(key_index, model)] = (
            time.monotonic() + _RATE_LIMIT_COOLDOWN_SECS
        )

    def _purge_expired(self) -> None:
        """Remove expired cooldown entries."""
        now = time.monotonic()
        self._cooldowns = {
            slot: exp for slot, exp in self._cooldowns.items() if exp > now
        }

    # ── Chain building ───────────────────────────────────────────────

    def _build_attempt_chain(
        self,
        starting_model: str | None = None,
    ) -> list[tuple[int, str]]:
        """Build the (key_index, model) attempt chain.

        Key-first traversal: for each model tier, try all keys before
        moving to the next model.
        """
        self._purge_expired()

        # Build model order: starting model first, then remaining.
        if starting_model and starting_model in _GENERATIVE_MODEL_CHAIN:
            models = [starting_model] + [
                m for m in _GENERATIVE_MODEL_CHAIN if m != starting_model
            ]
        else:
            models = list(_GENERATIVE_MODEL_CHAIN)

        key_indices = list(range(len(self._keys)))

        # Key-first: for each model, try all keys.
        full_chain = [
            (ki, model) for model in models for ki in key_indices
        ]

        filtered = [
            slot for slot in full_chain if slot not in self._cooldowns
        ]

        if not filtered:
            logger.warning("All key/model slots on cooldown — retrying full chain")
            return full_chain

        return filtered

    def _build_embedding_chain(self) -> list[tuple[int, str]]:
        """Build the embedding attempt chain (key rotation only, single model)."""
        self._purge_expired()

        key_indices = list(range(len(self._keys)))
        full_chain = [(ki, _EMBEDDING_MODEL) for ki in key_indices]

        filtered = [
            slot for slot in full_chain if slot not in self._cooldowns
        ]

        if not filtered:
            logger.warning("All embedding key slots on cooldown — retrying full chain")
            return full_chain

        return filtered

    # ── Generative API ───────────────────────────────────────────────

    async def generate_content(
        self,
        contents,
        *,
        config: dict | None = None,
        starting_model: str | None = None,
        label: str = "",
    ):
        """Generate content with automatic key/model fallback.

        Returns (response, model_used, key_index) on success.
        Raises the last exception if ALL (key, model) combinations fail.
        """
        chain = self._build_attempt_chain(starting_model=starting_model)
        last_exc: Exception | None = None

        for key_index, model in chain:
            try:
                client = self._get_client(key_index)
                response = await client.aio.models.generate_content(
                    model=model,
                    contents=contents,
                    config=config or {},
                )
                return response, model, key_index
            except Exception as exc:
                last_exc = exc
                if _is_rate_limited(exc):
                    self._mark_cooldown(key_index, model)
                    logger.warning(
                        "%s rate-limited on key[%d]/%s — cooldown %ds, trying next",
                        label or "Gemini",
                        key_index,
                        model,
                        _RATE_LIMIT_COOLDOWN_SECS,
                    )
                    continue
                raise

        raise last_exc  # type: ignore[misc]

    # ── Embedding API ────────────────────────────────────────────────

    def embed_content(self, contents, *, config: dict | None = None):
        """Embed content with automatic key rotation.

        Tries all keys for gemini-embedding-001.  Returns the response
        on first success.  Raises the last exception on total failure.
        """
        chain = self._build_embedding_chain()
        last_exc: Exception | None = None

        for key_index, model in chain:
            try:
                client = self._get_client(key_index)
                response = client.models.embed_content(
                    model=model,
                    contents=contents,
                    config=config or {},
                )
                return response
            except Exception as exc:
                last_exc = exc
                if _is_rate_limited(exc):
                    self._mark_cooldown(key_index, model)
                    logger.warning(
                        "Embedding rate-limited on key[%d] — cooldown %ds, trying next",
                        key_index,
                        _RATE_LIMIT_COOLDOWN_SECS,
                    )
                    continue
                raise

        raise last_exc  # type: ignore[misc]

    def embed_content_safe(self, contents, *, config: dict | None = None):
        """Like embed_content, but returns None instead of raising.

        Preserves existing behavior where embeddings fail silently.
        """
        try:
            return self.embed_content(contents, config=config)
        except Exception as exc:
            logger.error("All embedding keys exhausted: %s", exc)
            return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_key_pool.py -v`
Expected: All 16 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add website/features/api_key_switching/key_pool.py tests/test_key_pool.py
git commit -m "feat(api-keys): add GeminiKeyPool with key-first traversal and cooldowns"
```

---

## Task 3: Key Pool generate_content / embed_content Tests

**Files:**
- Modify: `tests/test_key_pool.py` (add generate/embed tests)

- [ ] **Step 1: Add generate_content and embed_content tests**

Append to `tests/test_key_pool.py`:

```python
# ── generate_content tests ──────────────────────────────────────────────────


def _make_pool_with_mocks(n_keys: int = 3):
    """Create a GeminiKeyPool with mocked genai.Clients."""
    from website.features.api_key_switching.key_pool import GeminiKeyPool

    pool = GeminiKeyPool([f"fake-key-{i}" for i in range(n_keys)])
    for i in range(n_keys):
        mock_client = MagicMock()
        mock_client.aio = MagicMock()
        mock_client.models = MagicMock()
        pool._clients[i] = mock_client
    return pool


def _make_429_error(msg: str = "RESOURCE_EXHAUSTED") -> ClientError:
    """Build a ClientError that looks like a Gemini 429."""
    return ClientError(
        code=429,
        response_json={"error": {"message": msg, "status": "RESOURCE_EXHAUSTED"}},
    )


async def test_generate_succeeds_on_first_slot():
    """First key/model succeeds → returns response, model, key_index."""
    pool = _make_pool_with_mocks(2)
    mock_response = MagicMock()

    pool._clients[0].aio.models.generate_content = AsyncMock(return_value=mock_response)

    response, model, key_idx = await pool.generate_content("test prompt")
    assert response is mock_response
    assert model == "gemini-2.5-flash"
    assert key_idx == 0


async def test_generate_rotates_keys_on_429():
    """429 on key0/flash → tries key1/flash → succeeds."""
    pool = _make_pool_with_mocks(2)
    mock_response = MagicMock()

    pool._clients[0].aio.models.generate_content = AsyncMock(side_effect=_make_429_error())
    pool._clients[1].aio.models.generate_content = AsyncMock(return_value=mock_response)

    response, model, key_idx = await pool.generate_content("test")
    assert model == "gemini-2.5-flash"
    assert key_idx == 1


async def test_generate_falls_to_lite_after_all_keys_exhausted():
    """429 on all keys for flash → falls through to key0/flash-lite."""
    pool = _make_pool_with_mocks(2)
    mock_response = MagicMock()

    pool._clients[0].aio.models.generate_content = AsyncMock(
        side_effect=[_make_429_error(), mock_response]
    )
    pool._clients[1].aio.models.generate_content = AsyncMock(
        side_effect=_make_429_error()
    )

    response, model, key_idx = await pool.generate_content("test")
    assert model == "gemini-2.5-flash-lite"
    assert key_idx == 0


async def test_generate_all_exhausted_raises():
    """429 on every key/model → raises the last exception."""
    pool = _make_pool_with_mocks(2)

    for i in range(2):
        pool._clients[i].aio.models.generate_content = AsyncMock(
            side_effect=_make_429_error(f"key-{i}")
        )

    with pytest.raises(ClientError):
        await pool.generate_content("test")


async def test_generate_non_429_raises_immediately():
    """Non-rate-limit error raises immediately without trying other keys."""
    pool = _make_pool_with_mocks(2)

    pool._clients[0].aio.models.generate_content = AsyncMock(
        side_effect=Exception("403 Permission Denied")
    )

    with pytest.raises(Exception, match="403 Permission Denied"):
        await pool.generate_content("test")

    # key1 was never called
    pool._clients[1].aio.models.generate_content.assert_not_called()


async def test_generate_with_starting_model():
    """starting_model parameter changes the model order."""
    pool = _make_pool_with_mocks(1)
    mock_response = MagicMock()

    pool._clients[0].aio.models.generate_content = AsyncMock(return_value=mock_response)

    _, model, _ = await pool.generate_content("test", starting_model="gemini-2.5-flash-lite")
    assert model == "gemini-2.5-flash-lite"


async def test_generate_records_cooldown():
    """After a 429, the (key, model) slot is on cooldown for the next call."""
    pool = _make_pool_with_mocks(2)
    mock_response = MagicMock()

    pool._clients[0].aio.models.generate_content = AsyncMock(side_effect=_make_429_error())
    pool._clients[1].aio.models.generate_content = AsyncMock(return_value=mock_response)

    await pool.generate_content("test")
    assert (0, "gemini-2.5-flash") in pool._cooldowns


# ── embed_content tests ─────────────────────────────────────────────────────


def test_embed_succeeds_on_first_key():
    """First key succeeds → returns response."""
    pool = _make_pool_with_mocks(2)
    mock_response = MagicMock()

    pool._clients[0].models.embed_content = MagicMock(return_value=mock_response)

    response = pool.embed_content("test text")
    assert response is mock_response


def test_embed_rotates_keys_on_429():
    """429 on key0 → tries key1 → succeeds."""
    pool = _make_pool_with_mocks(2)
    mock_response = MagicMock()

    pool._clients[0].models.embed_content = MagicMock(side_effect=_make_429_error())
    pool._clients[1].models.embed_content = MagicMock(return_value=mock_response)

    response = pool.embed_content("test text")
    assert response is mock_response


def test_embed_safe_returns_none_on_failure():
    """embed_content_safe returns None when all keys fail."""
    pool = _make_pool_with_mocks(2)

    for i in range(2):
        pool._clients[i].models.embed_content = MagicMock(side_effect=_make_429_error())

    result = pool.embed_content_safe("test text")
    assert result is None
```

- [ ] **Step 2: Run tests**

Run: `pytest tests/test_key_pool.py -v`
Expected: All 27 tests PASS (16 from Task 2 + 11 new).

- [ ] **Step 3: Commit**

```bash
git add tests/test_key_pool.py
git commit -m "test(api-keys): add generate_content and embed_content pool tests"
```

---

## Task 4: Module __init__.py — Singleton + Key Discovery

**Files:**
- Create: `website/features/api_key_switching/__init__.py`
- Modify: `tests/test_key_pool.py` (add init/singleton tests)

- [ ] **Step 1: Add tests for init_key_pool and get_key_pool**

Append to `tests/test_key_pool.py`:

```python
# ── Module init / singleton tests ───────────────────────────────────────────


def test_init_key_pool_from_file(tmp_path, monkeypatch):
    """init_key_pool reads keys from api_env file."""
    import website.features.api_key_switching as mod

    mod._pool = None  # reset singleton

    env_file = tmp_path / "api_env"
    env_file.write_text("key-from-file-a\nkey-from-file-b\n")
    monkeypatch.setattr(mod, "_API_ENV_PATHS", [str(env_file)])

    pool = mod.init_key_pool()
    assert pool._keys == ["key-from-file-a", "key-from-file-b"]
    mod._pool = None  # cleanup


def test_init_key_pool_fallback_to_settings(monkeypatch):
    """Falls back to settings.gemini_api_key when no api_env file exists."""
    import website.features.api_key_switching as mod

    mod._pool = None

    monkeypatch.setattr(mod, "_API_ENV_PATHS", ["/nonexistent/api_env"])

    mock_settings = MagicMock()
    mock_settings.gemini_api_key = "single-key-from-settings"
    monkeypatch.setattr(
        "website.features.api_key_switching.get_settings",
        lambda: mock_settings,
    )

    pool = mod.init_key_pool()
    assert pool._keys == ["single-key-from-settings"]
    mod._pool = None


def test_init_key_pool_no_keys_raises(monkeypatch):
    """Raises ValueError when no keys found from any source."""
    import website.features.api_key_switching as mod

    mod._pool = None

    monkeypatch.setattr(mod, "_API_ENV_PATHS", ["/nonexistent/api_env"])

    mock_settings = MagicMock()
    mock_settings.gemini_api_key = ""
    monkeypatch.setattr(
        "website.features.api_key_switching.get_settings",
        lambda: mock_settings,
    )

    with pytest.raises(ValueError, match="No Gemini API keys"):
        mod.init_key_pool()
    mod._pool = None


def test_get_key_pool_auto_init(monkeypatch):
    """get_key_pool auto-initializes on first call."""
    import website.features.api_key_switching as mod

    mod._pool = None

    mock_settings = MagicMock()
    mock_settings.gemini_api_key = "auto-init-key"
    monkeypatch.setattr(mod, "_API_ENV_PATHS", ["/nonexistent/api_env"])
    monkeypatch.setattr(
        "website.features.api_key_switching.get_settings",
        lambda: mock_settings,
    )

    pool = mod.get_key_pool()
    assert pool._keys == ["auto-init-key"]
    mod._pool = None


def test_get_key_pool_returns_same_instance(monkeypatch):
    """get_key_pool returns the same singleton on repeated calls."""
    import website.features.api_key_switching as mod

    mod._pool = None

    mock_settings = MagicMock()
    mock_settings.gemini_api_key = "singleton-key"
    monkeypatch.setattr(mod, "_API_ENV_PATHS", ["/nonexistent/api_env"])
    monkeypatch.setattr(
        "website.features.api_key_switching.get_settings",
        lambda: mock_settings,
    )

    pool1 = mod.get_key_pool()
    pool2 = mod.get_key_pool()
    assert pool1 is pool2
    mod._pool = None
```

- [ ] **Step 2: Create __init__.py**

```python
# website/features/api_key_switching/__init__.py
"""API Key Switching — multi-key rotation for Gemini API.

Usage::

    from website.features.api_key_switching import get_key_pool

    pool = get_key_pool()
    response, model, key_idx = await pool.generate_content(prompt)

Key loading priority (first non-empty source wins):
  1. api_env file at <project_root>/api_env
  2. api_env file at /etc/secrets/api_env
  3. settings.gemini_api_key (backward compat with single key)
"""

from __future__ import annotations

import logging
from pathlib import Path

from website.features.api_key_switching.key_pool import GeminiKeyPool, _load_keys_from_file

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).parent.parent.parent.parent  # website/features/api_key_switching → project root

_API_ENV_PATHS = [
    str(_PROJECT_ROOT / "api_env"),
    "/etc/secrets/api_env",
]

_pool: GeminiKeyPool | None = None


def init_key_pool() -> GeminiKeyPool:
    """Initialize the global key pool.

    Raises ValueError if no keys found from any source.
    """
    global _pool  # noqa: PLW0603

    # Source 1 & 2: api_env file
    for path in _API_ENV_PATHS:
        keys = _load_keys_from_file(path)
        if keys:
            logger.info("Loaded %d Gemini API key(s) from %s", len(keys), path)
            _pool = GeminiKeyPool(keys)
            return _pool

    # Source 3: backward compat — single key from settings
    from telegram_bot.config.settings import get_settings

    settings = get_settings()
    if settings.gemini_api_key.strip():
        logger.info("Using single GEMINI_API_KEY from settings (backward compat)")
        _pool = GeminiKeyPool([settings.gemini_api_key.strip()])
        return _pool

    raise ValueError(
        "No Gemini API keys found. Provide keys via:\n"
        "  1. api_env file (one key per line) at project root or /etc/secrets/api_env\n"
        "  2. GEMINI_API_KEY environment variable"
    )


def get_key_pool() -> GeminiKeyPool:
    """Return the global key pool singleton.

    Auto-initializes on first call if init_key_pool() hasn't been called.
    """
    global _pool  # noqa: PLW0603
    if _pool is None:
        init_key_pool()
    return _pool  # type: ignore[return-value]
```

- [ ] **Step 3: Run tests**

Run: `pytest tests/test_key_pool.py -v`
Expected: All 32 tests PASS (27 + 5 new).

- [ ] **Step 4: Commit**

```bash
git add website/features/api_key_switching/__init__.py tests/test_key_pool.py
git commit -m "feat(api-keys): add key pool singleton with file/settings discovery"
```

---

## Task 5: Integrate Summarizer with Key Pool

**Files:**
- Modify: `telegram_bot/pipeline/summarizer.py`
- Modify: `tests/test_model_fallback.py`
- Modify: `tests/test_gemini.py`

This is the largest integration task. The summarizer drops its own client/cooldown management and delegates to the pool.

- [ ] **Step 1: Modify summarizer.py**

Replace the imports and constants at the top (lines 1-35):

```python
"""Gemini AI summarization and multi-dimensional tagging.

Uses the google-genai SDK (NOT the deprecated google-generativeai) to
send extracted content to Gemini and receive structured summaries with
intelligent tags across 6 axes.

Model fallback and key rotation are handled by the centralized
GeminiKeyPool in website.features.api_key_switching.  The summarizer
delegates all API calls to the pool.

Graceful degradation (R022): if ALL models/keys fail, returns raw content
with status=raw so it can still be saved to Obsidian for manual review.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field

from telegram_bot.models.capture import ExtractedContent, SourceType
from website.features.api_key_switching import get_key_pool
from website.features.api_key_switching.routing import select_starting_model

logger = logging.getLogger(__name__)
```

Remove the old constants and helper that are now in the pool (delete lines 31-50 of the original):
- `_RATE_LIMIT_COOLDOWN_SECS`
- `_MODEL_FALLBACK_CHAIN`
- `_is_rate_limited()`

Keep `_SYSTEM_PROMPT` and `_USER_PROMPT_TEMPLATE` unchanged (lines 54-88 in original).

Keep `SummarizationResult` unchanged (lines 92-101 in original).

Replace the `GeminiSummarizer` class (lines 104-196 in original):

```python
class GeminiSummarizer:
    """Summarize and tag content using Google Gemini.

    Delegates all API calls to the centralized GeminiKeyPool,
    which handles multi-key rotation and model fallback.

    Args:
        api_key: Deprecated — ignored.  Keys are managed by the pool.
        model_name: Primary model preference (used as starting_model hint).
    """

    def __init__(self, api_key: str = "", model_name: str = "gemini-2.5-flash") -> None:
        if api_key:
            logger.debug("api_key parameter is deprecated — keys are managed by GeminiKeyPool")
        self._pool = get_key_pool()
        self._model = model_name

    async def _generate_with_fallback(
        self,
        contents,
        *,
        starting_model: str | None = None,
        config: dict | None = None,
        label: str = "",
    ):
        """Call generate_content via the key pool with automatic fallback.

        Returns (response, model_used) on success, raises on total failure.
        """
        if config is None:
            config = {
                "system_instruction": _SYSTEM_PROMPT,
                "temperature": 0.3,
                "max_output_tokens": 4096,
            }
        response, model_used, _key_idx = await self._pool.generate_content(
            contents,
            config=config,
            starting_model=starting_model or self._model,
            label=label,
        )
        return response, model_used
```

Keep `_is_youtube_without_transcript`, `_summarize_youtube_video`, `summarize`, and `_parse_response` methods, but update `_summarize_youtube_video` and `summarize` to pass content-aware `starting_model`:

In `_summarize_youtube_video` (around original line 231), change the `_generate_with_fallback` call:

```python
            response, model_used = await self._generate_with_fallback(
                contents,
                starting_model="gemini-2.5-flash",  # video understanding needs best model
                label="Video understanding",
            )
```

In `summarize` (around original line 293), add content-aware routing:

```python
        start = time.monotonic()
        try:
            starting_model = select_starting_model(
                content_length=len(content.body),
                source_type=content.source_type.value,
            )
            response, model_used = await self._generate_with_fallback(
                prompt,
                starting_model=starting_model,
                label="Summarization",
            )
```

Keep `_parse_response`, `_ensure_list`, and `build_tag_list` completely unchanged.

- [ ] **Step 2: Update test_model_fallback.py**

The tests need to mock the pool instead of the old internal client. Replace the full file:

```python
# tests/test_model_fallback.py
"""Tests for summarizer integration with GeminiKeyPool.

Verifies that GeminiSummarizer correctly delegates to the pool and
handles responses and failures as expected.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from google.genai.errors import ClientError

from telegram_bot.models.capture import ExtractedContent, SourceType
from telegram_bot.pipeline.summarizer import GeminiSummarizer


def _make_content(body_len: int = 500, source_type: SourceType = SourceType.WEB) -> ExtractedContent:
    return ExtractedContent(
        url="https://example.com/test",
        source_type=source_type,
        title="Test",
        body="x" * body_len,
    )


def _make_mock_pool():
    """Create a mock key pool."""
    pool = MagicMock()
    pool.generate_content = AsyncMock()
    return pool


@patch("telegram_bot.pipeline.summarizer.get_key_pool")
def test_summarizer_uses_pool(mock_get_pool):
    """GeminiSummarizer delegates to get_key_pool()."""
    mock_pool = _make_mock_pool()
    mock_get_pool.return_value = mock_pool

    s = GeminiSummarizer()
    assert s._pool is mock_pool


@patch("telegram_bot.pipeline.summarizer.get_key_pool")
async def test_summarizer_passes_starting_model(mock_get_pool):
    """Summarizer passes content-aware starting_model to pool."""
    mock_pool = _make_mock_pool()
    mock_get_pool.return_value = mock_pool

    mock_response = MagicMock()
    mock_response.text = '{"detailed_summary":"s","brief_summary":"b","tags":{},"one_line_summary":"o"}'
    mock_response.usage_metadata = MagicMock(total_token_count=100)
    mock_pool.generate_content.return_value = (mock_response, "gemini-2.5-flash-lite", 0)

    s = GeminiSummarizer()
    content = _make_content(body_len=500, source_type=SourceType.WEB)
    result = await s.summarize(content)

    # Short web content → flash-lite starting model
    call_kwargs = mock_pool.generate_content.call_args
    assert call_kwargs.kwargs["starting_model"] == "gemini-2.5-flash-lite"
    assert not result.is_raw_fallback


@patch("telegram_bot.pipeline.summarizer.get_key_pool")
async def test_summarizer_raw_fallback_on_pool_failure(mock_get_pool):
    """When pool raises (all keys/models exhausted), returns raw fallback."""
    mock_pool = _make_mock_pool()
    mock_get_pool.return_value = mock_pool

    mock_pool.generate_content.side_effect = ClientError(
        code=429,
        response_json={"error": {"message": "all exhausted"}},
    )

    s = GeminiSummarizer()
    content = _make_content(body_len=100)
    result = await s.summarize(content)

    assert result.is_raw_fallback is True
    assert result.summary == content.body[:5000]


@patch("telegram_bot.pipeline.summarizer.get_key_pool")
async def test_summarizer_deprecated_api_key_ignored(mock_get_pool):
    """Passing api_key is accepted but ignored (backward compat)."""
    mock_pool = _make_mock_pool()
    mock_get_pool.return_value = mock_pool

    s = GeminiSummarizer(api_key="old-key-ignored")
    assert s._pool is mock_pool
```

- [ ] **Step 3: Update test_gemini.py mock target**

In `tests/test_gemini.py`, the `_PATCH_TARGET` and `make_mock_client` helper need updating. Change the mock approach: instead of mocking `genai.Client`, mock `get_key_pool`.

Replace line 29 and the `make_mock_client` helper (lines 47-67):

```python
_PATCH_TARGET = "telegram_bot.pipeline.summarizer.get_key_pool"


def make_mock_pool(response_text: str, token_count: int = 500):
    """Return a mock key pool configured to return a specific response."""
    mock_response = MagicMock()
    mock_response.text = response_text
    mock_response.usage_metadata = MagicMock()
    mock_response.usage_metadata.total_token_count = token_count

    mock_pool = MagicMock()
    mock_pool.generate_content = AsyncMock(
        return_value=(mock_response, "gemini-2.5-flash", 0)
    )

    return mock_pool, mock_response
```

Update every test that uses `make_mock_client` to use `make_mock_pool` instead, and change the `@patch(_PATCH_TARGET)` decorator to inject the pool mock.

This is a mechanical replacement: wherever you see `mock_instance, mock_response = make_mock_client(...)`, replace with `mock_pool, mock_response = make_mock_pool(...)` and update the `with patch(...)` block to inject `mock_pool` via `mock_get_pool.return_value = mock_pool`.

- [ ] **Step 4: Run all summarizer tests**

Run: `pytest tests/test_model_fallback.py tests/test_gemini.py -v`
Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add telegram_bot/pipeline/summarizer.py tests/test_model_fallback.py tests/test_gemini.py
git commit -m "refactor(summarizer): delegate to GeminiKeyPool for key/model rotation"
```

---

## Task 6: Integrate Orchestrator + Web Pipeline

**Files:**
- Modify: `telegram_bot/pipeline/orchestrator.py:124-127`
- Modify: `website/core/pipeline.py:52-55`

- [ ] **Step 1: Update orchestrator.py**

At `telegram_bot/pipeline/orchestrator.py:124-127`, change the `GeminiSummarizer` construction:

```python
        # ── Phase 7: summarize via Gemini ─────────────────────────────────
        logger.info("Phase summarize — sending to Gemini")
        summarizer = GeminiSummarizer(
            model_name=settings.model_name,
        )
        result = await summarizer.summarize(extracted)
```

Remove the `api_key=settings.gemini_api_key` argument. The pool handles keys.

- [ ] **Step 2: Update website/core/pipeline.py**

At `website/core/pipeline.py:52-55`, change:

```python
    # Phase 5: summarize via Gemini
    summarizer = GeminiSummarizer(
        model_name=settings.model_name,
    )
    result = await summarizer.summarize(extracted)
```

Remove `api_key=settings.gemini_api_key`. Remove the `from telegram_bot.config.settings import get_settings` import if it's no longer needed — but check: `get_settings()` is still used at line 29 for `resolve_redirects`. Actually it's used for `settings.model_name` too. Keep the import but remove the `api_key=` arg only.

- [ ] **Step 3: Run existing orchestrator/website tests**

Run: `pytest tests/test_orchestrator.py tests/test_website.py -v`
Expected: All tests PASS. (These tests mock `get_settings()` and `GeminiSummarizer`, so the removal of `api_key=` should be transparent.)

- [ ] **Step 4: Commit**

```bash
git add telegram_bot/pipeline/orchestrator.py website/core/pipeline.py
git commit -m "refactor(pipeline): remove api_key arg from summarizer construction"
```

---

## Task 7: Integrate Embeddings with Key Pool

**Files:**
- Modify: `website/features/kg_features/embeddings.py`

- [ ] **Step 1: Rewrite embeddings.py to use pool**

Replace the client/cooldown logic. Keep `find_similar_nodes` and `should_create_semantic_link` unchanged:

```python
"""M2 — Semantic Embeddings via Gemini embedding model.

Generates vector embeddings for KG node content and provides
similarity-based linking and search helpers using cosine distance.

Key rotation is handled by the centralized GeminiKeyPool.
"""

from __future__ import annotations

import logging

import numpy as np

from website.features.api_key_switching import get_key_pool

logger = logging.getLogger(__name__)

# ── Constants ───────────────────────────────────────────────────────────────

_EMBEDDING_DIMS = 768


# ── Single embedding ────────────────────────────────────────────────────────

def generate_embedding(
    text: str,
    task_type: str = "RETRIEVAL_DOCUMENT",
) -> list[float]:
    """Generate an L2-normalised embedding vector for *text*.

    Returns an empty list on any failure (rate-limit, network, etc.).
    The key pool handles key rotation on 429 errors automatically.
    """
    if not text or not text.strip():
        return []

    try:
        pool = get_key_pool()
        response = pool.embed_content_safe(
            text,
            config={"task_type": task_type, "output_dimensionality": _EMBEDDING_DIMS},
        )

        if response is None:
            return []

        raw = response.embeddings[0].values
        if len(raw) != _EMBEDDING_DIMS:
            logger.warning("Embedding returned %d dims, expected %d", len(raw), _EMBEDDING_DIMS)
        vec = np.array(raw, dtype=np.float64)
        norm = np.linalg.norm(vec)
        if norm > 0:
            vec = vec / norm
        return vec.tolist()

    except Exception as exc:
        logger.error("Embedding generation failed: %s", exc)
        return []


# ── Batch embeddings ────────────────────────────────────────────────────────

def generate_embeddings_batch(
    texts: list[str],
    task_type: str = "RETRIEVAL_DOCUMENT",
) -> list[list[float]]:
    """Generate L2-normalised embeddings for a list of texts.

    Returns a list the same length as *texts*; failed items are [].
    """
    if not texts:
        return []

    try:
        pool = get_key_pool()
        response = pool.embed_content_safe(
            texts,
            config={"task_type": task_type, "output_dimensionality": _EMBEDDING_DIMS},
        )

        if response is None:
            return [[] for _ in texts]

        results: list[list[float]] = []
        for emb in response.embeddings:
            raw = emb.values
            if len(raw) != _EMBEDDING_DIMS:
                logger.warning("Embedding returned %d dims, expected %d", len(raw), _EMBEDDING_DIMS)
            vec = np.array(raw, dtype=np.float64)
            norm = np.linalg.norm(vec)
            if norm > 0:
                vec = vec / norm
            results.append(vec.tolist())
        return results

    except Exception as exc:
        logger.error("Batch embedding failed: %s", exc)
        return [[] for _ in texts]


# ── Similarity helpers ──────────────────────────────────────────────────────

def should_create_semantic_link(similarity: float, threshold: float = 0.75) -> bool:
    """Return True if *similarity* is strictly above *threshold*."""
    return similarity > threshold


def find_similar_nodes(
    supabase_client,
    user_id: str,
    embedding: list[float],
    threshold: float = 0.75,
    limit: int = 10,
) -> list[dict]:
    """Find nodes similar to *embedding* via the ``match_kg_nodes`` RPC.

    Calls the Supabase ``match_kg_nodes`` Postgres function which performs
    a vector similarity search using pgvector's cosine distance operator.

    Returns a list of dicts with ``id``, ``name``, ``similarity``, etc.
    Returns an empty list on failure.
    """
    if not embedding:
        return []

    try:
        response = supabase_client.rpc(
            "match_kg_nodes",
            {
                "query_embedding": embedding,
                "target_user_id": user_id,
                "match_threshold": threshold,
                "match_count": limit,
            },
        ).execute()
        return response.data or []
    except Exception as exc:
        logger.error("find_similar_nodes RPC failed: %s", exc)
        return []
```

Changes from original:
- Removed `_get_genai_client()`, `_last_rate_limit_ts`, `_RATE_LIMIT_COOLDOWN_SECS`, `_EMBEDDING_MODEL`
- Removed `from google import genai` and `from telegram_bot.config.settings import get_settings`
- `generate_embedding()` calls `pool.embed_content_safe()` instead of `client.models.embed_content()`
- `generate_embeddings_batch()` calls `pool.embed_content_safe()` instead of `client.models.embed_content()`
- Removed per-function cooldown checks (pool handles this)
- `find_similar_nodes()` and `should_create_semantic_link()` unchanged

- [ ] **Step 2: Run existing KG tests (if any)**

Run: `pytest tests/ -k "embedding or kg" -v`
Expected: PASS (existing tests either mock the embedding functions or don't call the API).

- [ ] **Step 3: Commit**

```bash
git add website/features/kg_features/embeddings.py
git commit -m "refactor(embeddings): delegate to GeminiKeyPool for key rotation"
```

---

## Task 8: Integrate NL Query with Key Pool

**Files:**
- Modify: `website/features/kg_features/nl_query.py:14-15,46-50,181,191-196,244-248,269-272`

- [ ] **Step 1: Update nl_query.py**

Replace import + client function (lines 14-15, 46-50):

```python
# Replace:
#   from google import genai
# With:
from website.features.api_key_switching import get_key_pool
```

Remove `_get_genai_client()` function entirely (lines 46-50).

In `NLGraphQuery.ask()` (line 181), replace `client = _get_genai_client()` with `pool = get_key_pool()`.

Replace the three `client.models.generate_content()` calls with `pool.generate_content()`. Since `nl_query.py` uses `asyncio.to_thread(lambda: client.models.generate_content(...))`, and the pool's `generate_content()` is already async, we can simplify.

Replace the SQL generation call (lines 190-198):

```python
            response, _, _ = await pool.generate_content(
                question,
                config={"system_instruction": system},
                starting_model=model,
                label="NL query SQL",
            )
            sql_raw = response.text
```

Replace the retry call (lines 244-253):

```python
                response2, _, _ = await pool.generate_content(
                    retry_prompt,
                    config={"system_instruction": retry_system},
                    starting_model=model,
                    label="NL query retry",
                )
                sql_raw2 = response2.text
```

Replace the answer formatting call (lines 269-280):

```python
            answer_response, _, _ = await pool.generate_content(
                _ANSWER_PROMPT.format(
                    question=question,
                    results=json.dumps(raw_result, default=str)[:4000],
                ),
                starting_model=model,
                label="NL query answer",
            )
            answer_text = answer_response.text
```

Remove the `asyncio.wait_for` + `asyncio.to_thread` wrappers around each call — the pool's `generate_content` is already async and handles timeouts via the underlying SDK. Keep the `timeout=10.0` by wrapping the pool call in `asyncio.wait_for`:

```python
            response, _, _ = await asyncio.wait_for(
                pool.generate_content(
                    question,
                    config={"system_instruction": system},
                    starting_model=model,
                    label="NL query SQL",
                ),
                timeout=10.0,
            )
            sql_raw = response.text
```

Apply the same pattern to all three calls.

Also remove the `from functools import lru_cache` import (no longer needed after removing `_get_genai_client`).

- [ ] **Step 2: Run NL query tests (if any)**

Run: `pytest tests/kg_intelligence/ -v`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add website/features/kg_features/nl_query.py
git commit -m "refactor(nl-query): delegate to GeminiKeyPool for key rotation"
```

---

## Task 9: Integrate Entity Extractor with Key Pool

**Files:**
- Modify: `website/features/kg_features/entity_extractor.py:16,78-82,224,241-249,263-275,296-308`

- [ ] **Step 1: Update entity_extractor.py**

Replace import (line 16):

```python
# Replace:
#   from google import genai
# With (keep google.genai.types for Content/Part):
from google.genai import types
```

Add pool import after the existing imports:

```python
from website.features.api_key_switching import get_key_pool
```

Remove `_get_genai_client()` function (lines 78-82).

Remove `from functools import lru_cache` (line 18).

In `EntityExtractor.extract()` (line 224), replace `client = _get_genai_client()` with `pool = get_key_pool()`.

Replace Step 1's `client.models.generate_content` call (lines 241-249):

```python
            analysis_response, _, _ = await asyncio.wait_for(
                pool.generate_content(
                    analysis_prompt,
                    starting_model=model,
                    label="Entity analysis",
                ),
                timeout=10.0,
            )
            analysis_text = analysis_response.text
```

Replace Step 2's call (lines 263-275):

```python
            structured_response, _, _ = await asyncio.wait_for(
                pool.generate_content(
                    structured_prompt,
                    config={
                        "response_mime_type": "application/json",
                        "response_schema": ExtractionResult,
                    },
                    starting_model=model,
                    label="Entity structured",
                ),
                timeout=10.0,
            )
            structured_text = structured_response.text
```

Replace Step 3 gleaning loop's call (lines 296-308):

```python
                glean_response, _, _ = await asyncio.wait_for(
                    pool.generate_content(
                        conversation_contents,
                        config={
                            "response_mime_type": "application/json",
                            "response_schema": ExtractionResult,
                        },
                        starting_model=model,
                        label="Entity gleaning",
                    ),
                    timeout=10.0,
                )
                glean_text = glean_response.text
```

Note: The entity extractor uses `types.GenerateContentConfig(response_mime_type=..., response_schema=...)` in the original. The pool's `generate_content` accepts a `config` dict. The pool passes `config` directly to the SDK, so we can pass these config fields as a dict instead:

```python
config={"response_mime_type": "application/json", "response_schema": ExtractionResult}
```

However, checking the pool's implementation — it passes `config=config or {}` directly. The google-genai SDK accepts both dict and `GenerateContentConfig`. A dict should work. If not, we can wrap it in `types.GenerateContentConfig(...)` at the caller site.

- [ ] **Step 2: Run entity extractor tests**

Run: `pytest tests/kg_intelligence/ -v`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add website/features/kg_features/entity_extractor.py
git commit -m "refactor(entity-extractor): delegate to GeminiKeyPool for key rotation"
```

---

## Task 10: Full Test Suite Verification

**Files:** None (verification only)

- [ ] **Step 1: Run the complete test suite**

Run: `pytest tests/ --ignore=tests/integration_tests -v`
Expected: All tests PASS. Watch for:
- Import errors from removed symbols (`_MODEL_FALLBACK_CHAIN`, `_is_rate_limited`, etc.)
- Mock target mismatches in `test_gemini.py`
- Settings-dependent tests that call `get_settings()` without mocking

- [ ] **Step 2: Fix any failures**

Common fixes:
- If a test imports `_MODEL_FALLBACK_CHAIN` from summarizer: import from `key_pool.py` instead, or inline the values.
- If a test imports `_is_rate_limited` from summarizer: import from `key_pool.py` instead.
- If a test creates `GeminiSummarizer(api_key=...)` and the pool can't init: mock `get_key_pool` in the test.

- [ ] **Step 3: Commit any fixes**

```bash
git add -A
git commit -m "fix(tests): update imports and mocks for key pool integration"
```

---

## Task 11: Final Cleanup + api_env Template

**Files:**
- Verify: `.gitignore` already has `api_env`
- Verify: `website/features/api_key_switching/api_env.example` exists
- Remove: deprecated `gemini-2.0-flash` references anywhere in codebase

- [ ] **Step 1: Search for remaining gemini-2.0-flash references**

Run: `grep -r "gemini-2.0-flash" --include="*.py" .`

If found in production code (not test expectations), remove. Test files may reference it in historical assertions — update those too.

- [ ] **Step 2: Verify .gitignore**

Run: `git check-ignore api_env`
Expected: `api_env` (confirms it's ignored).

Run: `git check-ignore website/features/api_key_switching/api_env.example`
Expected: no output (confirms it's NOT ignored — will be committed).

- [ ] **Step 3: Run full test suite one final time**

Run: `pytest tests/ --ignore=tests/integration_tests -v`
Expected: All tests PASS.

- [ ] **Step 4: Final commit**

```bash
git add -A
git commit -m "feat(api-keys): complete API key switching system

Multi-key rotation with key-first traversal, content-aware model
routing, and centralized cooldown tracking. Supports 1-10 keys
from separate GCP projects via api_env file."
```
