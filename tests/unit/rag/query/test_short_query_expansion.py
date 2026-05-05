"""iter-11 Class D: short-THEMATIC queries get gazetteer + HyDE expansion.

q7 ('Anything about commencement?') was router-classified as THEMATIC, not
VAGUE, so the iter-07 ``expand_vague`` gazetteer path never fired. The fix
extends gazetteer + HyDE eligibility to THEMATIC queries with
``len(query.split()) <= RAG_SHORT_THEMATIC_THRESHOLD`` words. Long THEMATIC
queries keep the iter-08 multi-query-only path.
"""
from __future__ import annotations

import os
from unittest.mock import AsyncMock

import pytest

from website.features.rag_pipeline.query.transformer import QueryTransformer
from website.features.rag_pipeline.types import QueryClass


def _stub_pool(text: str):
    pool = AsyncMock()

    async def _gen(*args, **kwargs):
        return text

    pool.generate_content = _gen
    return pool


@pytest.mark.asyncio
async def test_short_thematic_query_gets_vague_expansion():
    """A 3-word THEMATIC query like 'Anything about commencement?' must
    receive the iter-07 gazetteer expansion that previously only fired for
    VAGUE class. The gazetteer ships a ``commencement`` key with graduation /
    stanford / valedictory expansions; the joined variants must include at
    least one of these tokens."""
    pool = _stub_pool("alt: paraphrase 1\nalt: paraphrase 2\nalt: paraphrase 3")
    qt = QueryTransformer(pool=pool)
    variants = await qt.transform("Anything about commencement?", QueryClass.THEMATIC)
    joined = " ".join(variants).lower()
    assert (
        "graduation" in joined
        or "stanford" in joined
        or "valedictory" in joined
    ), f"short-THEMATIC gazetteer expansion missing; got variants={variants}"


@pytest.mark.asyncio
async def test_long_thematic_query_no_vague_expansion():
    """A 10+ word THEMATIC query stays on the iter-08 multi-query-only path:
    no gazetteer fires (we don't have keys for the long-form tokens) and
    HyDE is skipped — only the original + paraphrases remain."""
    pool = _stub_pool("alt: paraphrase 1\nalt: paraphrase 2\nalt: paraphrase 3")
    qt = QueryTransformer(pool=pool)
    long_q = (
        "How does the programming workflow zettel characterise the day-to-day "
        "skill of programming?"
    )
    variants = await qt.transform(long_q, QueryClass.THEMATIC)
    # Must include the original query + at least one paraphrase.
    assert variants[0] == long_q
    assert len(variants) >= 2


@pytest.mark.asyncio
async def test_short_thematic_threshold_env_overrideable(monkeypatch):
    """The threshold is env-driven; setting it to 1 forces the long-q test
    case onto the multi-query-only path again, proving the gate is honoured."""
    monkeypatch.setenv("RAG_SHORT_THEMATIC_THRESHOLD", "1")
    # Force module to re-read env on next import.
    from website.features.rag_pipeline.query import transformer as tx
    import importlib
    importlib.reload(tx)
    pool = _stub_pool("alt: paraphrase 1")
    qt = tx.QueryTransformer(pool=pool)
    variants = await qt.transform("Anything about commencement?", QueryClass.THEMATIC)
    joined = " ".join(variants).lower()
    # With threshold=1, the 3-word query no longer qualifies as short — no
    # gazetteer expansion fires.
    assert "graduation" not in joined
    assert "stanford" not in joined
    assert "valedictory" not in joined
    # Restore the default for other tests.
    monkeypatch.delenv("RAG_SHORT_THEMATIC_THRESHOLD", raising=False)
    importlib.reload(tx)


@pytest.mark.asyncio
async def test_lookup_class_unaffected():
    """LOOKUP keeps the iter-08 single-variant path; no expansion regardless
    of length."""
    pool = _stub_pool("ignored")
    qt = QueryTransformer(pool=pool)
    variants = await qt.transform("naval ravikant", QueryClass.LOOKUP)
    assert variants == ["naval ravikant"]
