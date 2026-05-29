"""Tests for ``ops/scripts/lib/gemini_factory.py``.

The factory is the bridge between the operator-facing ``api_env`` / CSV env
sources and the singleton ``GeminiKeyPool`` used by every ops/eval script.
Prior to 2026-05-28 the CSV path hardcoded ``role="free"`` for every key,
which silently dropped the ``role=billing`` tag operators expect to embed
inline. These tests pin the parser parity invariant: the CSV form
``"AIzaA role=free,AIzaB role=billing"`` MUST produce the same pool shape
as the file form with the same two lines.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from ops.scripts.lib import gemini_factory
from ops.scripts.lib.gemini_factory import _parse_csv_key_spec, make_client


# ---------------------------------------------------------------------------
# _parse_csv_key_spec — direct unit coverage
# ---------------------------------------------------------------------------


def test_parse_csv_key_spec_bare_defaults_to_free():
    assert _parse_csv_key_spec("AIzaBare") == ("AIzaBare", "free")


def test_parse_csv_key_spec_explicit_billing():
    assert _parse_csv_key_spec("AIzaPaid role=billing") == ("AIzaPaid", "billing")


def test_parse_csv_key_spec_explicit_free():
    assert _parse_csv_key_spec("AIzaFree role=free") == ("AIzaFree", "free")


def test_parse_csv_key_spec_whitespace_tolerance():
    # The CSV split on "," leaves leading/trailing whitespace on each element;
    # the helper must strip it before delegating to parse_api_env_line.
    assert _parse_csv_key_spec("  AIzaTrim  role=billing  ") == (
        "AIzaTrim",
        "billing",
    )
    assert _parse_csv_key_spec("\tAIzaTab\trole=free\t") == ("AIzaTab", "free")


def test_parse_csv_key_spec_empty_returns_none():
    # Empty / whitespace-only entries are silently skipped — operators may
    # paste a trailing comma without intending to add a key slot.
    assert _parse_csv_key_spec("") is None
    assert _parse_csv_key_spec("   ") is None
    assert _parse_csv_key_spec("\t\n") is None


def test_parse_csv_key_spec_unknown_role_raises():
    # Defensive: an operator pasting `role=enterprise` should surface a
    # ValueError at startup rather than silently drop the tag.
    with pytest.raises(ValueError, match="invalid role"):
        _parse_csv_key_spec("AIzaBad role=enterprise")


# ---------------------------------------------------------------------------
# make_client — env-var CSV path with mixed roles
# ---------------------------------------------------------------------------


@pytest.fixture
def _clean_gemini_env(monkeypatch):
    """Strip every Gemini-related env var so each test starts from a clean slate."""
    for name in (
        "GEMINI_API_KEY",
        "GEMINI_API_KEY_1",
        "GEMINI_API_KEY_2",
        "GEMINI_API_KEYS",
        "GEMINI_KEY_ROLE_FILTER",
        "RAG_BILLING_KEY_INDEX",
    ):
        monkeypatch.delenv(name, raising=False)
    yield


def _patched_make_client():
    """Wrap make_client so the TieredGeminiClient ctor & load_config are no-ops.

    The factory's sole side-effect we care about under test is the
    ``GeminiKeyPool`` it constructs — config loading and the surrounding
    TieredGeminiClient wrapper are orthogonal. Patching them out keeps the
    test hermetic (no YAML I/O) and lets us inspect the pool keys/roles
    directly via the captured constructor args.
    """
    captured: dict = {}

    class _FakeTiered:
        def __init__(self, pool, config) -> None:
            captured["pool"] = pool
            captured["config"] = config

    with patch.object(gemini_factory, "TieredGeminiClient", _FakeTiered), patch.object(
        gemini_factory, "load_config", return_value=object()
    ):
        client = make_client()
    return client, captured


def test_make_client_csv_mixed_roles(_clean_gemini_env, monkeypatch):
    # GEMINI_API_KEYS with one free + one billing key — the role tags must
    # propagate into the resulting pool. This is the regression fix for the
    # 2026-05-28 discovery that the CSV path hardcoded role="free".
    monkeypatch.setenv(
        "GEMINI_API_KEYS",
        "AIzaA role=free,AIzaB role=billing",
    )
    _, captured = _patched_make_client()

    pool = captured["pool"]
    assert pool._keys == ["AIzaA", "AIzaB"]
    assert pool._key_roles == ["free", "billing"]


def test_make_client_csv_whitespace_padded_elements(_clean_gemini_env, monkeypatch):
    # Operators commonly format the CSV with spaces around commas for
    # readability; whitespace MUST NOT change the parsed roles.
    monkeypatch.setenv(
        "GEMINI_API_KEYS",
        "  AIzaA role=free  ,  AIzaB role=billing  ",
    )
    _, captured = _patched_make_client()

    pool = captured["pool"]
    assert pool._keys == ["AIzaA", "AIzaB"]
    assert pool._key_roles == ["free", "billing"]


def test_make_client_csv_trailing_comma_ignored(_clean_gemini_env, monkeypatch):
    # A trailing comma is a common copy-paste artifact — it should not
    # crash the factory or add an empty slot to the pool.
    monkeypatch.setenv("GEMINI_API_KEYS", "AIzaA role=billing,,")
    _, captured = _patched_make_client()

    pool = captured["pool"]
    assert pool._keys == ["AIzaA"]
    assert pool._key_roles == ["billing"]


def test_make_client_csv_bare_keys_default_to_free(_clean_gemini_env, monkeypatch):
    # Backward-compat invariant: legacy CSV values without role tokens must
    # continue to be tagged free.
    monkeypatch.setenv("GEMINI_API_KEYS", "AIzaLegacyA,AIzaLegacyB")
    _, captured = _patched_make_client()

    pool = captured["pool"]
    assert pool._keys == ["AIzaLegacyA", "AIzaLegacyB"]
    assert pool._key_roles == ["free", "free"]


# ---------------------------------------------------------------------------
# make_client — single-key legacy fallback
# ---------------------------------------------------------------------------


def test_make_client_legacy_single_gemini_api_key(_clean_gemini_env, monkeypatch):
    # GEMINI_API_KEY (no plural) is the oldest single-key form. It has no
    # role-token syntax, so the resulting key must be tagged free.
    monkeypatch.setenv("GEMINI_API_KEY", "AIzaLegacy")
    _, captured = _patched_make_client()

    pool = captured["pool"]
    assert pool._keys == ["AIzaLegacy"]
    assert pool._key_roles == ["free"]


# ---------------------------------------------------------------------------
# make_client — file fallback path with mixed roles
# ---------------------------------------------------------------------------


def test_make_client_file_fallback_mixed_roles(
    _clean_gemini_env, monkeypatch, tmp_path: Path
):
    # When no env vars supply keys, the factory walks candidate_api_env_paths()
    # and uses the first file it finds. Roles tagged in the file must reach
    # the pool unmodified.
    api_env = tmp_path / "api_env"
    api_env.write_text(
        "AIzaFileA role=free\nAIzaFileB role=billing\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        gemini_factory,
        "candidate_api_env_paths",
        lambda: [api_env],
    )
    _, captured = _patched_make_client()

    pool = captured["pool"]
    assert pool._keys == ["AIzaFileA", "AIzaFileB"]
    assert pool._key_roles == ["free", "billing"]


def test_make_client_csv_and_file_produce_identical_pools(
    _clean_gemini_env, monkeypatch, tmp_path: Path
):
    # The core parity invariant: feeding the same two key+role specs through
    # the CSV path and through the file path MUST produce the same pool
    # shape (same keys list, same roles list, same ordering after the
    # free-before-billing sort applied in normalize_api_keys).

    # First: env-var CSV path.
    monkeypatch.setenv(
        "GEMINI_API_KEYS",
        "AIzaA role=free,AIzaB role=billing",
    )
    _, captured_csv = _patched_make_client()
    monkeypatch.delenv("GEMINI_API_KEYS", raising=False)

    # Second: file path with identical content.
    api_env = tmp_path / "api_env"
    api_env.write_text(
        "AIzaA role=free\nAIzaB role=billing\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        gemini_factory,
        "candidate_api_env_paths",
        lambda: [api_env],
    )
    _, captured_file = _patched_make_client()

    assert captured_csv["pool"]._keys == captured_file["pool"]._keys
    assert captured_csv["pool"]._key_roles == captured_file["pool"]._key_roles


# ---------------------------------------------------------------------------
# make_client — error path
# ---------------------------------------------------------------------------


def test_make_client_raises_when_no_keys_available(
    _clean_gemini_env, monkeypatch, tmp_path: Path
):
    # No env vars, no file at any candidate path → RuntimeError per the
    # factory's existing contract.
    monkeypatch.setattr(
        gemini_factory,
        "candidate_api_env_paths",
        lambda: [tmp_path / "missing_api_env"],
    )
    with pytest.raises(RuntimeError, match="No Gemini API keys found"):
        _patched_make_client()
