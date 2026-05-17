"""P1-2 + P1-7 correctness coverage for website.core.persist.

Covers:
- (i)  v2 attempted when is_v2_configured() true even if DB_SCHEMA_VERSION unset
- (ii) use_supabase_v2() semantics unchanged
- (iii) v2 failure -> surfaced SupabaseV2PersistError (not 200 + supabase=false)
- (iv) same URL + different LLM summary -> SAME content_hash -> dedup;
       different source raw_text -> different hash
- (v)  empty RPC result -> surfaced error, not swallowed

All Supabase access is mocked; no live network.
"""
from __future__ import annotations

from datetime import date
from uuid import UUID

import pytest

from website.core import db_version, persist
from website.core.supabase_v2.models import CanonicalUpsertResult
from website.core.supabase_v2.repositories.content_repository import (
    EmptyRpcResultError,
    _first,
)

_PROFILE = UUID("00000000-0000-0000-0000-000000000001")
_WORKSPACE = UUID("00000000-0000-0000-0000-000000000002")
_WZID = UUID("00000000-0000-0000-0000-000000000222")


# ---- (ii) use_supabase_v2() semantics unchanged ---------------------------


def test_use_supabase_v2_still_requires_flag_and_creds(monkeypatch) -> None:
    monkeypatch.setenv("DB_SCHEMA_VERSION", "v2")
    monkeypatch.setattr(db_version, "is_v2_configured", lambda: False)
    assert db_version.use_supabase_v2() is False

    monkeypatch.setattr(db_version, "is_v2_configured", lambda: True)
    assert db_version.use_supabase_v2() is True

    monkeypatch.setenv("DB_SCHEMA_VERSION", "v1")
    assert db_version.use_supabase_v2() is False  # creds alone never flip it


def test_db_schema_version_default_is_v1(monkeypatch) -> None:
    monkeypatch.delenv("DB_SCHEMA_VERSION", raising=False)
    assert db_version.get_db_schema_version() == "v1"


# ---- (i) v2 attempted when configured even if DB_SCHEMA_VERSION unset ------


def test_should_attempt_v2_when_configured_without_flag(monkeypatch) -> None:
    monkeypatch.delenv("DB_SCHEMA_VERSION", raising=False)
    monkeypatch.setattr(persist, "use_supabase_v2", lambda: False)
    monkeypatch.setattr(persist, "is_v2_configured", lambda: True)
    assert persist._persist_should_attempt_v2() is True


def test_should_not_attempt_v2_when_unconfigured(monkeypatch) -> None:
    monkeypatch.delenv("DB_SCHEMA_VERSION", raising=False)
    monkeypatch.setattr(persist, "use_supabase_v2", lambda: False)
    monkeypatch.setattr(persist, "is_v2_configured", lambda: False)
    assert persist._persist_should_attempt_v2() is False


def test_scope_resolves_when_configured_without_flag(monkeypatch) -> None:
    monkeypatch.delenv("DB_SCHEMA_VERSION", raising=False)
    monkeypatch.setattr(persist, "use_supabase_v2", lambda: False)
    monkeypatch.setattr(persist, "is_v2_configured", lambda: True)

    class _Core:
        def get_default_workspace_id(self, _pid):
            return _WORKSPACE

    monkeypatch.setattr(persist, "_v2_core_repo", _Core())
    monkeypatch.setattr(persist, "_v2_content_repo", object())

    scope = persist.get_supabase_v2_scope(str(_PROFILE))
    assert scope is not None
    _, profile_id, workspace_id = scope
    assert profile_id == _PROFILE
    assert workspace_id == _WORKSPACE


# ---- (iii) v2 failure surfaced, not swallowed -----------------------------


@pytest.mark.asyncio
async def test_v2_failure_surfaces_structured_error(monkeypatch) -> None:
    class _Repo:
        def upsert_canonical_zettel(self, *_a, **_k):
            raise RuntimeError("schema cache miss")

    monkeypatch.setattr(
        persist, "get_supabase_v2_scope", lambda _s: (_Repo(), _PROFILE, _WORKSPACE)
    )
    monkeypatch.setattr(persist, "_file_graph_contains_url", lambda _u: False)
    monkeypatch.setattr(persist, "_persist_file_node", lambda p, skip_duplicate: None)

    with pytest.raises(persist.SupabaseV2PersistError):
        await persist.persist_summarized_result(
            {
                "title": "X",
                "source_type": "web",
                "source_url": "https://example.com",
                "summary": "S",
                "tags": [],
            },
            user_sub=str(_PROFILE),
        )


@pytest.mark.asyncio
async def test_empty_rpc_result_surfaces_not_swallowed(monkeypatch) -> None:
    class _Repo:
        def upsert_canonical_zettel(self, *_a, **_k):
            return _first([])  # raises EmptyRpcResultError

    monkeypatch.setattr(
        persist, "get_supabase_v2_scope", lambda _s: (_Repo(), _PROFILE, _WORKSPACE)
    )
    monkeypatch.setattr(persist, "_file_graph_contains_url", lambda _u: False)
    monkeypatch.setattr(persist, "_persist_file_node", lambda p, skip_duplicate: None)

    with pytest.raises(persist.SupabaseV2PersistError):
        await persist.persist_summarized_result(
            {
                "title": "X",
                "source_type": "web",
                "source_url": "https://example.com",
                "summary": "S",
                "tags": [],
            },
            user_sub=str(_PROFILE),
        )


def test_first_raises_empty_rpc_result_error() -> None:
    with pytest.raises(EmptyRpcResultError):
        _first([])
    with pytest.raises(EmptyRpcResultError):
        _first(None)
    assert _first([{"id": 1}]) == {"id": 1}
    assert _first({"id": 2}) == {"id": 2}
    assert issubclass(EmptyRpcResultError, RuntimeError)


# ---- (iv) stable, change-sensitive content_hash ---------------------------


def test_content_hash_stable_across_llm_wording() -> None:
    url = "https://example.com/post"
    base = {"source_url": url, "raw_text": "RAW SOURCE TEXT"}
    h1 = persist._stable_content_hash({**base, "summary": "LLM wording A"}, url)
    h2 = persist._stable_content_hash({**base, "summary": "LLM wording B"}, url)
    assert h1 == h2  # LLM output non-determinism must NOT change the dedup key


def test_content_hash_changes_on_source_text_change() -> None:
    url = "https://example.com/post"
    h1 = persist._stable_content_hash({"source_url": url, "raw_text": "v1"}, url)
    h2 = persist._stable_content_hash({"source_url": url, "raw_text": "v2"}, url)
    assert h1 != h2  # genuine source drift -> new canonical row


def test_content_hash_stable_without_raw_text() -> None:
    url = "https://example.com/post"
    h1 = persist._stable_content_hash({"source_url": url, "summary": "A"}, url)
    h2 = persist._stable_content_hash({"source_url": url, "summary": "B"}, url)
    assert h1 == h2
    # different URL still separates rows
    h3 = persist._stable_content_hash({"source_url": url + "x"}, url + "x")
    assert h3 != h1


@pytest.mark.asyncio
async def test_persist_v2_hash_is_url_derived_not_summary(monkeypatch) -> None:
    captured = {}

    class _Repo:
        def upsert_canonical_zettel(self, zettel, *, workspace=None, chunks=None):
            captured["hash"] = zettel.content_hash
            return CanonicalUpsertResult(
                canonical_zettel_id=UUID("00000000-0000-0000-0000-000000000111"),
                workspace_zettel_id=_WZID,
                was_new=True,
            )

    returned, saved, dup = await persist._persist_supabase_v2_zettel(
        payload={
            "source_url": "https://example.com",
            "source_type": "web",
            "title": "T",
            "summary": "non-deterministic LLM body",
            "tags": [],
            "metadata": {},
        },
        repo=_Repo(),
        workspace_id=_WORKSPACE,
        captured_on=date.today(),
        detailed_summary="non-deterministic LLM body",
    )
    import hashlib

    expected = hashlib.sha256("https://example.com\x00".encode("utf-8")).digest()
    assert captured["hash"] == expected
    assert saved is True
