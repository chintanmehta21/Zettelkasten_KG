"""M1 — Entity Extraction tests.

Covers:
- Basic extraction from a mocked Gemini response.
- Dedup of similar-named entities of the same type (and keeping entities
  of different types separate even with similar names).
- Graceful timeout handling: returns empty ExtractionResult rather than
  raising.
"""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

from website.features.kg_features import entity_extractor as ext_mod
from website.features.kg_features.entity_extractor import (
    EntityExtractor,
    ExtractedEntity,
    ExtractionConfig,
    ExtractionResult,
    _deduplicate_entities,
)


# ── Test 1 ───────────────────────────────────────────────────────────────────

async def test_extract_entities_from_text(stub_settings):
    """Mock Gemini to return 2 entities + 1 relationship.  Assert the
    result has the expected shape after post-processing.
    """
    # Build fake Gemini responses for each of the 3 pipeline steps:
    # analysis, structured, gleaning.
    analysis_resp = MagicMock()
    analysis_resp.text = "Found: Python (language), TensorFlow (framework)."

    structured_payload = (
        '{"entities": ['
        ' {"id": "python", "type": "LANGUAGE", "description": "lang"},'
        ' {"id": "tensorflow", "type": "FRAMEWORK", "description": "ml"}'
        '], "relationships": ['
        ' {"source": "tensorflow", "target": "python", "type": "USES",'
        '  "strength": 9, "description": "runs on"}'
        ']}'
    )
    structured_resp = MagicMock()
    structured_resp.text = structured_payload

    # Gleaning returns empty so the loop exits after 1 iteration.
    glean_resp = MagicMock()
    glean_resp.text = '{"entities": [], "relationships": []}'

    # pool.generate_content is async and returns (response, model, key_idx)
    async def fake_generate(*args, **kwargs):
        return fake_generate._responses.pop(0)
    fake_generate._responses = [
        (analysis_resp, "gemini-2.5-flash", 0),
        (structured_resp, "gemini-2.5-flash", 0),
        (glean_resp, "gemini-2.5-flash", 0),
    ]

    fake_pool = MagicMock()
    fake_pool.generate_content = fake_generate

    with patch.object(ext_mod, "get_key_pool", return_value=fake_pool):
        extractor = EntityExtractor(ExtractionConfig(max_gleanings=1))
        result = await extractor.extract(
            summary="Python is used by TensorFlow.",
            title="ML Article",
        )

    assert isinstance(result, ExtractionResult)
    assert len(result.entities) == 2
    ids = {e.id for e in result.entities}
    assert ids == {"python", "tensorflow"}
    types = {e.type for e in result.entities}
    assert types == {"LANGUAGE", "FRAMEWORK"}
    assert len(result.relationships) == 1
    rel = result.relationships[0]
    assert rel.type == "USES"
    assert rel.source == "tensorflow"
    assert rel.target == "python"


# ── Test 2 ───────────────────────────────────────────────────────────────────

def test_deduplicate_entities_by_embedding():
    """Two similar-named same-type entities should dedup to 1.
    Two similar-named DIFFERENT-type entities should remain separate.
    """
    # Case A: same type, high similarity → dedup.
    ents_same_type = [
        ExtractedEntity(id="javascript", type="LANGUAGE"),
        ExtractedEntity(id="js", type="LANGUAGE"),
    ]
    # Near-identical embeddings (similarity ≈ 1.0).
    embed_fn_same = lambda texts: [  # noqa: E731
        [1.0, 0.0, 0.0],
        [0.99, 0.01, 0.0],
    ]
    deduped = _deduplicate_entities(ents_same_type, embed_fn_same, threshold=0.90)
    assert len(deduped) == 1, "Same-type similar entities should dedup"

    # Case B: different types, high similarity → both kept.
    ents_diff_type = [
        ExtractedEntity(id="python", type="LANGUAGE"),
        ExtractedEntity(id="python", type="PLATFORM"),
    ]
    embed_fn_diff = lambda texts: [  # noqa: E731
        [1.0, 0.0, 0.0],
        [1.0, 0.0, 0.0],
    ]
    kept = _deduplicate_entities(ents_diff_type, embed_fn_diff, threshold=0.90)
    assert len(kept) == 2, "Different-type entities should not dedup"


# ── Test 3 ───────────────────────────────────────────────────────────────────

async def test_extraction_returns_empty_on_timeout(stub_settings):
    """When Gemini hangs > 10s, extract() should catch the TimeoutError
    and return an empty ExtractionResult rather than raising.
    """
    async def hang_forever(*args, **kwargs):
        raise asyncio.TimeoutError()

    fake_pool = MagicMock()
    fake_pool.generate_content = hang_forever

    with patch.object(ext_mod, "get_key_pool", return_value=fake_pool):
        extractor = EntityExtractor(ExtractionConfig(max_gleanings=0))
        result = await extractor.extract(summary="Some content.", title="T")

    assert isinstance(result, ExtractionResult)
    assert result.entities == []
    assert result.relationships == []
