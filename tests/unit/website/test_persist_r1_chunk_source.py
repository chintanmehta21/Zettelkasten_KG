"""R1 + D4 + D10 persist-path contract.

R1 (chunk-source = SUMMARY primary): the corpus is curated and our
``body_md`` summaries are dense + self-contained (numbers, entities,
attributed quotes survive). Citations resolve to the zettel = the
summary; chunking the summary keeps citation/faithfulness coherent.
``raw_text`` is only a FALLBACK when the summary is empty / a known stub
(transcript-unavailable / paywall). This file pins the precedence FLIP
(old contract was raw-primary).

D4: ``RagSourceType`` must be a superset of summarization ``SourceType``
(drift guard) and an unknown source-type coerces to WEB *with a logged
warning* (not silently).

D10: a non-empty source that yields ZERO chunks must surface a degraded
signal on the PersistenceOutcome / result payload — the zettel still
saves (no 500) but it must NOT report a clean success.

All Supabase / Gemini access mocked; no live network.
"""
from __future__ import annotations

import logging
from datetime import date
from uuid import UUID

import pytest

from website.core import persist
from website.core.supabase_v2.models import CanonicalUpsertResult

_PROFILE = UUID("00000000-0000-0000-0000-000000000001")
_WORKSPACE = UUID("00000000-0000-0000-0000-000000000002")
_WZID = UUID("00000000-0000-0000-0000-000000000222")
_CANON = UUID("00000000-0000-0000-0000-000000000111")


class _CaptureRepo:
    def __init__(self) -> None:
        self.chunks = None
        self.zettel = None

    def upsert_canonical_zettel(self, zettel, *, workspace=None, chunks=None):
        self.zettel = zettel
        self.chunks = chunks
        return CanonicalUpsertResult(
            canonical_zettel_id=_CANON,
            workspace_zettel_id=_WZID,
            was_new=True,
        )


def _payload(*, raw_text=None, summary="S", source_type="web") -> dict:
    p = {
        "source_url": "https://example.com/post",
        "source_type": source_type,
        "title": "Naruto Uzumaki",
        "summary": summary,
        "tags": ["anime"],
        "metadata": {},
    }
    if raw_text is not None:
        p["raw_text"] = raw_text
    return p


# --------------------------------------------------------------------------
# R1 — summary is PRIMARY, raw only a fallback
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_r1_summary_chosen_over_raw_when_both_present(monkeypatch):
    """CONTRACT FLIP (old raw-primary -> new summary-primary): when BOTH a
    real raw body and a real summary exist, the chunker is fed the SUMMARY."""

    async def _fake_embed(texts):
        return [[0.01] * 768 for _ in texts]

    monkeypatch.setattr(persist, "embed_chunk_texts", _fake_embed)
    monkeypatch.setattr(persist, "_schedule_kg_population", lambda **_k: None)

    repo = _CaptureRepo()
    await persist._persist_supabase_v2_zettel(
        payload=_payload(raw_text="RAW_BODY_TOKEN appears only in raw text."),
        repo=repo,
        workspace_id=_WORKSPACE,
        captured_on=date.today(),
        detailed_summary="SUMMARY_TOKEN is the dense curated summary body.",
        profile_id=_PROFILE,
    )
    joined = " ".join(c.content for c in repo.chunks)
    assert "SUMMARY_TOKEN" in joined
    assert "RAW_BODY_TOKEN" not in joined


@pytest.mark.asyncio
async def test_r1_raw_fallback_when_summary_empty(monkeypatch):
    """Summary empty -> raw body is the fallback source (not zero chunks)."""

    async def _fake_embed(texts):
        return [[0.01] * 768 for _ in texts]

    monkeypatch.setattr(persist, "embed_chunk_texts", _fake_embed)
    monkeypatch.setattr(persist, "_schedule_kg_population", lambda **_k: None)

    repo = _CaptureRepo()
    p = _payload(raw_text="RAW_BODY_TOKEN is the only available body.", summary="")
    await persist._persist_supabase_v2_zettel(
        payload=p,
        repo=repo,
        workspace_id=_WORKSPACE,
        captured_on=date.today(),
        detailed_summary="",
        profile_id=_PROFILE,
    )
    joined = " ".join(c.content for c in repo.chunks)
    assert "RAW_BODY_TOKEN" in joined


@pytest.mark.asyncio
async def test_r1_raw_fallback_when_summary_is_stub(monkeypatch):
    """Summary is a known stub marker -> raw body wins as fallback."""

    async def _fake_embed(texts):
        return [[0.01] * 768 for _ in texts]

    monkeypatch.setattr(persist, "embed_chunk_texts", _fake_embed)
    monkeypatch.setattr(persist, "_schedule_kg_population", lambda **_k: None)

    repo = _CaptureRepo()
    p = _payload(raw_text="RAW_BODY_TOKEN real article text here.")
    await persist._persist_supabase_v2_zettel(
        payload=p,
        repo=repo,
        workspace_id=_WORKSPACE,
        captured_on=date.today(),
        detailed_summary="transcript not available",
        profile_id=_PROFILE,
    )
    joined = " ".join(c.content for c in repo.chunks)
    assert "RAW_BODY_TOKEN" in joined


# --------------------------------------------------------------------------
# D4 — RagSourceType drift guard + coercion logs a warning
# --------------------------------------------------------------------------


def test_rag_source_type_superset_of_summarization_source_type():
    """Drift guard: every summarization SourceType value must exist in the
    RAG SourceType enum (silent WEB coercion otherwise loses provenance)."""
    from website.features.rag_pipeline.types import SourceType as RagST
    from website.features.summarization_engine.core.models import (
        SourceType as SummST,
    )

    rag_values = {m.value for m in RagST}
    summ_values = {m.value for m in SummST}
    missing = summ_values - rag_values
    assert not missing, f"RagSourceType missing summarization members: {missing}"


@pytest.mark.asyncio
async def test_unknown_source_type_logs_warning_then_maps_to_web(
    monkeypatch, caplog
):
    """An unrecognised source-type must coerce to WEB *observably* (warning),
    never silently."""

    async def _fake_embed(texts):
        return [[0.01] * 768 for _ in texts]

    monkeypatch.setattr(persist, "embed_chunk_texts", _fake_embed)
    monkeypatch.setattr(persist, "_schedule_kg_population", lambda **_k: None)

    with caplog.at_level(logging.WARNING, logger="website.core.persist"):
        chunks = await persist.build_canonical_chunks(
            payload=_payload(
                summary="Body with enough text to chunk once.",
                source_type="totally-unknown-source",
            ),
            detailed_summary="Body with enough text to chunk once.",
        )
    assert chunks  # still produced chunks via WEB fallback
    assert any(
        "totally-unknown-source" in r.getMessage()
        for r in caplog.records
    ), "coercion to WEB must emit a warning naming the bad source_type"


# --------------------------------------------------------------------------
# D10 — zero chunks on non-empty source -> degraded signal
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_d10_zero_chunks_nonempty_source_sets_degraded_flag(monkeypatch):
    """A non-empty source whose batch embed fails -> zettel still saved but
    the PersistenceOutcome carries a degraded signal (NOT clean success)."""

    async def _fail_embed(texts):
        return None

    monkeypatch.setattr(persist, "embed_chunk_texts", _fail_embed)
    monkeypatch.setattr(persist, "_schedule_kg_population", lambda **_k: None)
    monkeypatch.setattr(
        persist, "get_supabase_v2_scope",
        lambda _s: (_CaptureRepo(), _PROFILE, _WORKSPACE),
    )
    monkeypatch.setattr(persist, "_persist_file_node", lambda *a, **k: None)
    monkeypatch.setattr(persist, "_file_graph_contains_url", lambda _u: False)

    outcome = await persist.persist_summarized_result(
        {
            "source_url": "https://example.com/post",
            "source_type": "web",
            "title": "Naruto",
            "summary": "A real non-empty summary about Naruto Uzumaki training.",
            "brief_summary": "Naruto trains.",
            "detailed_summary": "A real non-empty summary about Naruto Uzumaki training.",
            "tags": ["anime"],
            "metadata": {},
        },
        user_sub=str(_PROFILE),
    )
    assert outcome.supabase_saved is True  # zettel still persisted
    assert outcome.degraded is True
    assert outcome.quality_flag == "no_chunks"
    assert outcome.result.get("quality_flag") == "no_chunks"


@pytest.mark.asyncio
async def test_d10_chunks_present_is_not_degraded(monkeypatch):
    """Happy path: chunks produced -> no degraded flag, clean success."""

    async def _fake_embed(texts):
        return [[0.01] * 768 for _ in texts]

    monkeypatch.setattr(persist, "embed_chunk_texts", _fake_embed)
    monkeypatch.setattr(persist, "_schedule_kg_population", lambda **_k: None)
    monkeypatch.setattr(
        persist, "get_supabase_v2_scope",
        lambda _s: (_CaptureRepo(), _PROFILE, _WORKSPACE),
    )
    monkeypatch.setattr(persist, "_persist_file_node", lambda *a, **k: None)
    monkeypatch.setattr(persist, "_file_graph_contains_url", lambda _u: False)

    outcome = await persist.persist_summarized_result(
        {
            "source_url": "https://example.com/post",
            "source_type": "web",
            "title": "Naruto",
            "summary": "A real non-empty summary about Naruto Uzumaki training hard.",
            "brief_summary": "Naruto trains.",
            "detailed_summary": "A real non-empty summary about Naruto Uzumaki training hard.",
            "tags": ["anime"],
            "metadata": {},
        },
        user_sub=str(_PROFILE),
    )
    assert outcome.supabase_saved is True
    assert outcome.degraded is False
    assert outcome.quality_flag is None
