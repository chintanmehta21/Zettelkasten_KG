"""Tests for GeminiKeyPool: initialization, attempt chain, cooldowns, generate, embed."""

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from google.genai.errors import ClientError


# ── Key loading tests ───────────────────────────────────────────────────────


def test_pool_init_with_keys():
    """Pool initializes successfully with a list of API keys."""
    from website.features.api_key_switching.key_pool import GeminiKeyPool
    pool = GeminiKeyPool(["key-a", "key-b", "key-c"])
    assert pool._keys == ["key-a", "key-b", "key-c"]
    assert pool._clients == {}


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
        (0, "gemini-2.5-flash"), (1, "gemini-2.5-flash"), (2, "gemini-2.5-flash"),
        (0, "gemini-2.5-flash-lite"), (1, "gemini-2.5-flash-lite"), (2, "gemini-2.5-flash-lite"),
    ]


def test_chain_key_first_traversal_1_key():
    """With 1 key, chain degrades to model-only fallback."""
    from website.features.api_key_switching.key_pool import GeminiKeyPool
    pool = GeminiKeyPool(["k0"])
    chain = pool._build_attempt_chain()
    assert chain == [(0, "gemini-2.5-flash"), (0, "gemini-2.5-flash-lite")]


def test_chain_lite_starting_model():
    """Starting with flash-lite reverses the model order."""
    from website.features.api_key_switching.key_pool import GeminiKeyPool
    pool = GeminiKeyPool(["k0", "k1"])
    chain = pool._build_attempt_chain(starting_model="gemini-2.5-flash-lite")
    assert chain == [
        (0, "gemini-2.5-flash-lite"), (1, "gemini-2.5-flash-lite"),
        (0, "gemini-2.5-flash"), (1, "gemini-2.5-flash"),
    ]


def test_chain_skips_cooled_down_slots():
    """Slots on cooldown are excluded from the chain."""
    from website.features.api_key_switching.key_pool import GeminiKeyPool
    pool = GeminiKeyPool(["k0", "k1", "k2"])
    pool._mark_cooldown(0, "gemini-2.5-flash")
    pool._mark_cooldown(1, "gemini-2.5-flash")
    chain = pool._build_attempt_chain()
    assert chain == [
        (2, "gemini-2.5-flash"),
        (0, "gemini-2.5-flash-lite"), (1, "gemini-2.5-flash-lite"), (2, "gemini-2.5-flash-lite"),
    ]


def test_chain_expired_cooldown_restored():
    """Slots whose cooldown has expired are included again."""
    from website.features.api_key_switching.key_pool import GeminiKeyPool
    pool = GeminiKeyPool(["k0", "k1"])
    pool._cooldowns[(0, "gemini-2.5-flash")] = time.monotonic() - 1
    chain = pool._build_attempt_chain()
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
    assert len(chain) == 4


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
    pool._clients[1].aio.models.generate_content = AsyncMock(side_effect=_make_429_error())
    response, model, key_idx = await pool.generate_content("test")
    assert model == "gemini-2.5-flash-lite"
    assert key_idx == 0


async def test_generate_all_exhausted_raises():
    """429 on every key/model → raises the last exception."""
    pool = _make_pool_with_mocks(2)
    for i in range(2):
        pool._clients[i].aio.models.generate_content = AsyncMock(side_effect=_make_429_error(f"key-{i}"))
    with pytest.raises(ClientError):
        await pool.generate_content("test")


async def test_generate_non_429_raises_immediately():
    """Non-rate-limit error raises immediately without trying other keys."""
    pool = _make_pool_with_mocks(2)
    pool._clients[0].aio.models.generate_content = AsyncMock(side_effect=Exception("403 Permission Denied"))
    with pytest.raises(Exception, match="403 Permission Denied"):
        await pool.generate_content("test")
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
