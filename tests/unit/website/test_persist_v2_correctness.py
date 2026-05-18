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

import re as _re
from datetime import date
from pathlib import Path as _Path
from uuid import UUID

import pytest

from website.core import db_version, persist
from website.core.supabase_v2.models import CanonicalUpsertResult
from website.core.supabase_v2.repositories.content_repository import (
    EmptyRpcResultError,
    _first,
)
from website.features.summarization_engine.core.models import SourceType as _ST

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


# ---- P1-7(b): real extracted source text threaded into the dedup hash -----


def test_dedicated_key_drives_hash_same_source_same_hash() -> None:
    url = "https://example.com/post"
    src = "Extracted article body paragraph one. Paragraph two."
    h1 = persist._stable_content_hash(
        {"source_url": url, "source_fingerprint_text": src, "summary": "LLM A"}, url
    )
    h2 = persist._stable_content_hash(
        {"source_url": url, "source_fingerprint_text": src, "summary": "LLM B"}, url
    )
    assert h1 == h2  # same URL + unchanged source -> dedup despite LLM drift


def test_dedicated_key_material_source_change_new_hash() -> None:
    url = "https://example.com/post"
    h1 = persist._stable_content_hash(
        {"source_url": url, "source_fingerprint_text": "original body text"}, url
    )
    h2 = persist._stable_content_hash(
        {"source_url": url, "source_fingerprint_text": "materially rewritten body"},
        url,
    )
    assert h1 != h2  # genuine source change -> new canonical row


def test_dedicated_key_whitespace_noise_is_normalized() -> None:
    url = "https://example.com/post"
    clean = persist._stable_content_hash(
        {"source_url": url, "source_fingerprint_text": "alpha beta gamma"}, url
    )
    noisy = persist._stable_content_hash(
        {"source_url": url, "source_fingerprint_text": "  alpha\n\tbeta   gamma \n"},
        url,
    )
    assert clean == noisy  # re-wrap / trailing-newline churn must NOT change hash


def test_dedicated_key_overrides_legacy_raw_text() -> None:
    url = "https://example.com/post"
    only_new = persist._stable_content_hash(
        {"source_url": url, "source_fingerprint_text": "SRC"}, url
    )
    with_both = persist._stable_content_hash(
        {"source_url": url, "source_fingerprint_text": "SRC", "raw_text": "STALE"},
        url,
    )
    assert only_new == with_both  # dedicated key wins over raw_text fallback


def test_missing_source_text_falls_back_to_url_only_hash() -> None:
    url = "https://example.com/post"
    import hashlib as _h

    expected = _h.sha256(f"{url}\x00".encode("utf-8")).digest()
    assert (
        persist._stable_content_hash({"source_url": url, "summary": "x"}, url)
        == expected
    )
    # explicit None must not crash and must match the empty fallback
    assert (
        persist._stable_content_hash(
            {"source_url": url, "source_fingerprint_text": None}, url
        )
        == expected
    )


def test_summary_dto_threads_ingest_raw_text_into_payload() -> None:
    """run_add_zettel chain: bundle.ingest_result.raw_text -> DTO ->
    model_dump payload -> _stable_content_hash. Verified without network."""
    from website.api.module_runners import summarization as mod

    class _Meta:
        def __init__(self) -> None:
            from website.features.summarization_engine.core.models import SourceType

            self.source_type = SourceType.WEB
            self.url = "https://example.com/post"
            self.total_tokens_used = 1
            self.total_latency_ms = 1

        def model_dump(self, **_):
            return {}

    class _SummaryResult:
        mini_title = "Title"
        brief_summary = "brief"
        detailed_summary: list = []  # empty -> render falls back to brief
        tags: list[str] = []
        metadata = _Meta()

    class _Ingest:
        raw_text = "  Extracted   source\n\nbody.  "
        metadata: dict = {}

    class _Bundle:
        summary_result = _SummaryResult()
        ingest_result = _Ingest()

    dto = mod.summary_dto(_Bundle())
    assert dto.source_fingerprint_text == "  Extracted   source\n\nbody.  "
    payload = dto.model_dump(mode="json")
    assert payload["source_fingerprint_text"] == "  Extracted   source\n\nbody.  "
    url = payload["source_url"]
    # The threaded source now drives the hash; whitespace-normalized so a
    # trivially re-wrapped re-extraction dedups to the same canonical row.
    h_via_payload = persist._stable_content_hash(payload, url)
    h_normalized = persist._stable_content_hash(
        {"source_url": url, "source_fingerprint_text": "Extracted source body."}, url
    )
    assert h_via_payload == h_normalized


def test_summary_dto_none_raw_text_yields_url_only_hash() -> None:
    from website.api.module_runners import summarization as mod

    class _Meta:
        def __init__(self) -> None:
            from website.features.summarization_engine.core.models import SourceType

            self.source_type = SourceType.WEB
            self.url = "https://example.com/empty"
            self.total_tokens_used = 0
            self.total_latency_ms = 0

        def model_dump(self, **_):
            return {}

    class _SummaryResult:
        mini_title = "T"
        brief_summary = "b"
        detailed_summary: list = []
        tags: list[str] = []
        metadata = _Meta()

    class _Ingest:
        raw_text = ""  # ingest produced nothing
        metadata: dict = {}

    class _Bundle:
        summary_result = _SummaryResult()
        ingest_result = _Ingest()

    dto = mod.summary_dto(_Bundle())
    assert dto.source_fingerprint_text is None  # empty -> None, safe fallback
    payload = dto.model_dump(mode="json")
    import hashlib as _h

    url = payload["source_url"]
    expected = _h.sha256(f"{url}\x00".encode("utf-8")).digest()
    assert persist._stable_content_hash(payload, url) == expected


# ---- DEFECT 2: arxiv (and every emitted SourceType) must persist ----------
#
# Live evidence: arxiv abstract URLs failed with "Knowledge-graph write
# failed; the zettel was not saved." ROOT CAUSE: content.canonical_zettels'
# source_type CHECK only allowed
#   youtube,reddit,github,twitter,substack,newsletter,medium,web,generic
# but SourceType emits arxiv/hackernews/linkedin/podcast too. The INSERT in
# content.upsert_canonical_zettel raised a CHECK violation -> caught by
# persist.persist_summarized_result's generic handler -> SupabaseV2PersistError
# -> the WHOLE canonical zettel write aborts. KG enrichment is fire-and-forget
# and never on this path; the canonical write itself failed the constraint.

_V2_DIR = _Path(__file__).resolve().parents[3] / "supabase" / "website" / "_v2"


def _check_allowed_source_types() -> set[str]:
    """Parse the live CHECK value set from 02_content_schema.sql."""
    sql = (_V2_DIR / "02_content_schema.sql").read_text(encoding="utf-8")
    m = _re.search(
        r"source_type\s+text\s+NOT NULL\s+CHECK\s*\(\s*source_type\s+IN\s*\((.*?)\)\s*\)",
        sql,
        _re.DOTALL | _re.IGNORECASE,
    )
    assert m, "could not locate canonical_zettels source_type CHECK"
    return set(_re.findall(r"'([a-z]+)'", m.group(1)))


def test_schema_check_allows_every_emitted_source_type() -> None:
    """Regression guard: the CHECK must list EVERY value SourceType can emit
    so no source can ever fail the canonical-zettel write again."""
    allowed = _check_allowed_source_types()
    emitted = {st.value for st in _ST}
    missing = emitted - allowed
    assert not missing, (
        f"source_type CHECK is missing emitted SourceType value(s): {missing}. "
        f"allowed={sorted(allowed)} emitted={sorted(emitted)}"
    )
    # arxiv specifically (the live failure) must be present.
    assert "arxiv" in allowed


def test_migration_47_widens_check_to_arxiv() -> None:
    """The forward migration must (a) exist in apply order and (b) re-add the
    widened CHECK including arxiv/hackernews/linkedin/podcast."""
    mig = _V2_DIR / "47_canonical_source_type_arxiv.sql"
    assert mig.exists(), "migration 47 missing"
    body = mig.read_text(encoding="utf-8")
    for v in ("arxiv", "hackernews", "linkedin", "podcast"):
        assert f"'{v}'" in body, f"migration 47 must add '{v}'"
    assert "DROP CONSTRAINT IF EXISTS canonical_zettels_source_type_check" in body
    assert "ADD CONSTRAINT canonical_zettels_source_type_check" in body


@pytest.mark.asyncio
async def test_arxiv_zettel_persists_when_check_is_correct(monkeypatch) -> None:
    """End-to-end: with the corrected CHECK an arxiv zettel persists (the
    repo's INSERT no longer raises). The DB CHECK is modelled by a fake repo
    that enforces exactly the (now-correct) allowed set parsed from schema."""
    allowed = _check_allowed_source_types()

    class _CheckEnforcingRepo:
        def upsert_canonical_zettel(self, zettel, *, workspace=None, chunks=None):
            # Model the Postgres CHECK constraint precisely.
            if zettel.source_type not in allowed:
                raise RuntimeError(
                    'new row for relation "canonical_zettels" violates '
                    "check constraint "
                    '"canonical_zettels_source_type_check"'
                )
            return CanonicalUpsertResult(
                canonical_zettel_id=UUID(
                    "00000000-0000-0000-0000-0000000000aa"
                ),
                workspace_zettel_id=_WZID,
                was_new=True,
            )

    monkeypatch.setattr(
        persist,
        "get_supabase_v2_scope",
        lambda _s: (_CheckEnforcingRepo(), _PROFILE, _WORKSPACE),
    )
    monkeypatch.setattr(persist, "_file_graph_contains_url", lambda _u: False)
    monkeypatch.setattr(persist, "_persist_file_node", lambda p, skip_duplicate: "web-x")
    # Keep KG enrichment a pure no-op so this test isolates the canonical
    # write (KG is fire-and-forget and explicitly out of the persist contract).
    monkeypatch.setattr(persist, "_schedule_kg_population", lambda **_k: None)

    outcome = await persist.persist_summarized_result(
        {
            "title": "Attention Is All You Need",
            "source_type": "arxiv",
            "source_url": "https://arxiv.org/abs/2011.08892",
            "summary": "An arXiv paper abstract.",
            "tags": ["ml"],
            "metadata": {},
        },
        user_sub=str(_PROFILE),
    )
    assert outcome.supabase_saved is True
    assert outcome.supabase_node_id is not None


@pytest.mark.asyncio
async def test_arxiv_would_have_failed_under_old_check(monkeypatch) -> None:
    """Proves the diagnosed mechanism: under the OLD allowed set, an arxiv
    zettel raises SupabaseV2PersistError (exactly the live symptom). This is
    the negative control for the fix above."""
    old_allowed = {
        "youtube", "reddit", "github", "twitter", "substack",
        "newsletter", "medium", "web", "generic",
    }

    class _OldRepo:
        def upsert_canonical_zettel(self, zettel, *, workspace=None, chunks=None):
            if zettel.source_type not in old_allowed:
                raise RuntimeError(
                    "violates check constraint "
                    '"canonical_zettels_source_type_check"'
                )
            return CanonicalUpsertResult(
                canonical_zettel_id=UUID("00000000-0000-0000-0000-0000000000bb"),
                workspace_zettel_id=_WZID,
                was_new=True,
            )

    monkeypatch.setattr(
        persist,
        "get_supabase_v2_scope",
        lambda _s: (_OldRepo(), _PROFILE, _WORKSPACE),
    )
    monkeypatch.setattr(persist, "_file_graph_contains_url", lambda _u: False)
    monkeypatch.setattr(persist, "_persist_file_node", lambda p, skip_duplicate: None)

    with pytest.raises(persist.SupabaseV2PersistError):
        await persist.persist_summarized_result(
            {
                "title": "X",
                "source_type": "arxiv",
                "source_url": "https://arxiv.org/abs/1812.01047",
                "summary": "S",
                "tags": [],
                "metadata": {},
            },
            user_sub=str(_PROFILE),
        )
