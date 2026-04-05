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

    fake_client = MagicMock()
    fake_client.models.generate_content.side_effect = [
        analysis_resp, structured_resp, glean_resp,
    ]

    with patch.object(ext_mod, "_get_genai_client", return_value=fake_client), \
         patch.object(ext_mod, "get_settings", return_value=stub_settings):
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
    def hang_forever(*args, **kwargs):
        # Sleep longer than the 10s timeout in extract().
        import time
        time.sleep(30)
        return MagicMock(text="never reached")

    fake_client = MagicMock()
    fake_client.models.generate_content.side_effect = hang_forever

    with patch.object(ext_mod, "_get_genai_client", return_value=fake_client), \
         patch.object(ext_mod, "get_settings", return_value=stub_settings), \
         patch.object(asyncio, "wait_for",
                      side_effect=asyncio.TimeoutError()):
        extractor = EntityExtractor(ExtractionConfig(max_gleanings=0))
        result = await extractor.extract(summary="Some content.", title="T")

    assert isinstance(result, ExtractionResult)
    assert result.entities == []
    assert result.relationships == []
