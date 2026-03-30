# KG Intelligence Layer — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add 6 intelligence modules (entity extraction, semantic embeddings, graph analytics, NL queries, graph traversal RPCs, hybrid retrieval) to the Supabase KG — zero LangChain, zero Neo4j.

**Architecture:** Native Gemini API (existing `google-genai`) + pgvector (Supabase extension) + NetworkX (new) + PostgreSQL recursive CTEs (Supabase RPCs). All new Python under `website/core/supabase_kg/`. Single consolidated SQL migration. Spec: `docs/superpowers/specs/2026-03-30-kg-intelligence-design.md` (v5).

**Tech Stack:** Python 3.12, google-genai, supabase-py, networkx>=3.2, numpy>=1.26, FastAPI, pgvector, pytest

**Performance constraints:** Graph load <2s, full workflow <30s, cold start <500ms

---

## File Map

| File | Action | Module | Responsibility |
|------|--------|--------|----------------|
| `supabase/website/kg_public/002_add_intelligence.sql` | CREATE | All | pgvector, link columns, FTS, 9 RPCs, permissions |
| `website/core/supabase_kg/embeddings.py` | CREATE | M2 | Gemini embedding generation + similarity search |
| `website/core/supabase_kg/analytics.py` | CREATE | M3 | NetworkX PageRank, Louvain, centrality |
| `website/core/supabase_kg/entity_extractor.py` | CREATE | M1 | Two-step extraction + gleaning + dedup |
| `website/core/supabase_kg/nl_query.py` | CREATE | M4 | NL-to-SQL engine with safety + retry |
| `website/core/supabase_kg/retrieval.py` | CREATE | M6 | Hybrid 3-stream RRF search |
| `scripts/backfill_embeddings.py` | CREATE | M2 | One-time embedding backfill |
| `website/core/supabase_kg/models.py` | MODIFY | M2 | Add `embedding` field to KGNodeCreate |
| `website/core/supabase_kg/repository.py` | MODIFY | M2,M5 | Add `_semantic_link`, 6 RPC wrappers |
| `website/core/supabase_kg/__init__.py` | MODIFY | All | Export new modules |
| `website/api/routes.py` | MODIFY | M3,M4,M6 | Enrich /api/graph, add /graph/query, /graph/search, wire M1+M2 into /summarize |
| `website/features/knowledge_graph/js/app.js` | MODIFY | M3 | PageRank sizing replaces degree-based |
| `requirements.txt` | MODIFY | M3 | Add networkx, numpy |
| `tests/test_embeddings.py` | CREATE | M2 | 3 tests |
| `tests/test_analytics.py` | CREATE | M3 | 3 tests |
| `tests/test_entity_extractor.py` | CREATE | M1 | 3 tests |
| `tests/test_nl_query.py` | CREATE | M4 | 5 tests |
| `tests/test_graph_rpcs.py` | CREATE | M5 | 3 tests |
| `tests/test_hybrid_retrieval.py` | CREATE | M6 | 3 tests |

---

## Phase 1 — Foundation (Tasks 1-5, parallelizable)

### Task 1: Schema Migration + Dependencies

**Files:**
- Create: `supabase/website/kg_public/002_add_intelligence.sql`
- Modify: `requirements.txt`

- [ ] **Step 1: Create the migration SQL**

Create `supabase/website/kg_public/002_add_intelligence.sql` by copying the full SQL block from the design spec (lines 73-396). This includes:
- pgvector extension + `embedding vector(768)` column
- `weight`, `link_type`, `description` columns on `kg_links`
- `fts` tsvector GENERATED ALWAYS AS column + GIN index
- Updated `kg_graph_view` with new link fields
- 9 RPC functions with `SECURITY DEFINER SET search_path = '' SET statement_timeout = '5s'`
- `execute_kg_query` with SELECT-only allowlist + user_id enforcement + result truncation
- REVOKE/GRANT permissions for all 9 functions

Verify:
```bash
grep -c "CREATE OR REPLACE FUNCTION" supabase/website/kg_public/002_add_intelligence.sql
# Expected: 9
```

- [ ] **Step 2: Add dependencies to requirements.txt**

Append to `requirements.txt` after line 39:
```
# Graph algorithms (PageRank, community detection, centrality)
networkx>=3.2

# Vector normalization for MRL-truncated embeddings
numpy>=1.26
```

- [ ] **Step 3: Install and verify**

```bash
pip install networkx>=3.2 numpy>=1.26
python -c "import networkx; print(networkx.__version__)"
python -c "import numpy; print(numpy.__version__)"
```
Expected: version numbers printed, no errors.

- [ ] **Step 4: Apply migration to Supabase**

Run the migration SQL in Supabase SQL Editor (or via MCP `mcp__supabase__apply_migration`). Verify:
```sql
SELECT * FROM pg_extension WHERE extname = 'vector';
SELECT column_name FROM information_schema.columns WHERE table_name = 'kg_nodes' AND column_name IN ('embedding', 'fts');
SELECT column_name FROM information_schema.columns WHERE table_name = 'kg_links' AND column_name IN ('weight', 'link_type', 'description');
SELECT routine_name FROM information_schema.routines WHERE routine_schema = 'public' AND routine_name LIKE 'find_%' OR routine_name LIKE 'match_%' OR routine_name LIKE 'top_%' OR routine_name LIKE 'isolated_%' OR routine_name LIKE 'similar_%' OR routine_name = 'execute_kg_query' OR routine_name = 'hybrid_kg_search' OR routine_name = 'shortest_path';
```

- [ ] **Step 5: Commit**

```bash
git add supabase/website/kg_public/002_add_intelligence.sql requirements.txt
git commit -m "feat: add KG intelligence schema migration + dependencies"
```

---

### Task 2: M2 — Semantic Embeddings

**Files:**
- Create: `website/core/supabase_kg/embeddings.py`
- Create: `tests/test_embeddings.py`
- Modify: `website/core/supabase_kg/models.py:51-60`

- [ ] **Step 1: Write 3 failing tests**

Create `tests/test_embeddings.py`:
```python
"""Tests for semantic embedding generation and similarity linking."""
from __future__ import annotations

import math
from unittest.mock import MagicMock, patch

import pytest


class TestGenerateEmbedding:
    @patch("website.core.supabase_kg.embeddings._get_genai_client")
    def test_returns_normalized_768_floats(self, mock_get_client):
        from website.core.supabase_kg.embeddings import generate_embedding

        raw_values = [0.1 * i for i in range(768)]
        mock_result = MagicMock()
        mock_result.embeddings = [MagicMock(values=raw_values)]
        mock_client = MagicMock()
        mock_client.models.embed_content.return_value = mock_result
        mock_get_client.return_value = mock_client

        result = generate_embedding("test text")

        assert len(result) == 768
        norm = math.sqrt(sum(x * x for x in result))
        assert abs(norm - 1.0) < 0.01

    @patch("website.core.supabase_kg.embeddings._get_genai_client")
    def test_graceful_degradation_on_429(self, mock_get_client):
        from google.genai.errors import ClientError
        from website.core.supabase_kg.embeddings import generate_embedding

        mock_client = MagicMock()
        error = ClientError("rate limited")
        error.code = 429
        mock_client.models.embed_content.side_effect = error
        mock_get_client.return_value = mock_client

        result = generate_embedding("test text")
        assert result == []


class TestSemanticLinkDecision:
    def test_above_threshold_creates_link(self):
        from website.core.supabase_kg.embeddings import should_create_semantic_link
        assert should_create_semantic_link(0.85, threshold=0.75) is True

    def test_at_threshold_no_link(self):
        from website.core.supabase_kg.embeddings import should_create_semantic_link
        assert should_create_semantic_link(0.75, threshold=0.75) is False

    def test_below_threshold_no_link(self):
        from website.core.supabase_kg.embeddings import should_create_semantic_link
        assert should_create_semantic_link(0.50, threshold=0.75) is False
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_embeddings.py -v
```
Expected: FAIL — `ModuleNotFoundError: No module named 'website.core.supabase_kg.embeddings'`

- [ ] **Step 3: Add embedding field to KGNodeCreate**

Edit `website/core/supabase_kg/models.py`. Add after line 60 (`metadata` field):
```python
    embedding: list[float] | None = None  # 768-dim Gemini embedding vector
```

- [ ] **Step 4: Implement embeddings.py**

Create `website/core/supabase_kg/embeddings.py`:
```python
"""Gemini embedding generation + pgvector similarity search.

Model: gemini-embedding-001 (GA). text-embedding-004 is DEPRECATED.
Dimensions: 768 via MRL truncation. L2-normalization REQUIRED.
PostgREST does NOT support pgvector <=> operator — use RPC functions.
"""
from __future__ import annotations

import logging
import time
from functools import lru_cache
from uuid import UUID

import numpy as np
from google import genai
from google.genai import types
from google.genai.errors import ClientError

logger = logging.getLogger(__name__)

_EMBEDDING_MODEL = "gemini-embedding-001"
_EMBEDDING_DIMS = 768
_COOLDOWN_SECS = 60
_cooldown_until: float = 0


@lru_cache(maxsize=1)
def _get_genai_client() -> genai.Client:
    from telegram_bot.config.settings import get_settings
    return genai.Client(api_key=get_settings().gemini_api_key)


def _is_rate_limited(exc: Exception) -> bool:
    if isinstance(exc, ClientError) and getattr(exc, "code", None) == 429:
        return True
    return "429" in str(exc) and "RESOURCE_EXHAUSTED" in str(exc)


def generate_embedding(
    text: str,
    task_type: str = "RETRIEVAL_DOCUMENT",
) -> list[float]:
    """Generate 768-dim L2-normalized embedding. Returns [] on failure."""
    global _cooldown_until
    if time.monotonic() < _cooldown_until:
        return []
    try:
        client = _get_genai_client()
        result = client.models.embed_content(
            model=_EMBEDDING_MODEL,
            contents=[text],
            config=types.EmbedContentConfig(
                task_type=task_type,
                output_dimensionality=_EMBEDDING_DIMS,
            ),
        )
        arr = np.array(result.embeddings[0].values, dtype=np.float32)
        norm = np.linalg.norm(arr)
        if norm > 0:
            arr = arr / norm
        return arr.tolist()
    except Exception as exc:
        if _is_rate_limited(exc):
            _cooldown_until = time.monotonic() + _COOLDOWN_SECS
            logger.warning("Embedding rate-limited, cooldown %ds", _COOLDOWN_SECS)
        else:
            logger.error("Embedding failed: %s", exc)
        return []


def generate_embeddings_batch(
    texts: list[str],
    task_type: str = "RETRIEVAL_DOCUMENT",
) -> list[list[float]]:
    """Batch embedding. Up to 250 texts, 20K tokens, 2048 tokens/text max."""
    try:
        client = _get_genai_client()
        result = client.models.embed_content(
            model=_EMBEDDING_MODEL,
            contents=texts,
            config=types.EmbedContentConfig(
                task_type=task_type,
                output_dimensionality=_EMBEDDING_DIMS,
            ),
        )
        out = []
        for emb in result.embeddings:
            arr = np.array(emb.values, dtype=np.float32)
            norm = np.linalg.norm(arr)
            if norm > 0:
                arr = arr / norm
            out.append(arr.tolist())
        return out
    except Exception as exc:
        logger.error("Batch embedding failed: %s", exc)
        return [[] for _ in texts]


def should_create_semantic_link(similarity: float, threshold: float = 0.75) -> bool:
    """True if similarity strictly exceeds threshold."""
    return similarity > threshold


def find_similar_nodes(
    supabase_client,
    user_id: UUID,
    embedding: list[float],
    threshold: float = 0.75,
    limit: int = 10,
) -> list[dict]:
    """Find similar nodes via match_kg_nodes RPC. Returns [] on failure."""
    if not embedding:
        return []
    try:
        resp = supabase_client.rpc("match_kg_nodes", {
            "query_embedding": embedding,
            "match_threshold": threshold,
            "match_count": limit,
            "target_user_id": str(user_id),
        }).execute()
        return resp.data or []
    except Exception as exc:
        logger.error("Similarity search failed: %s", exc)
        return []
```

- [ ] **Step 5: Run tests**

```bash
pytest tests/test_embeddings.py -v
```
Expected: 3 passed (technically 5 test functions — 2 in class + 3 in class)

- [ ] **Step 6: Commit**

```bash
git add website/core/supabase_kg/embeddings.py website/core/supabase_kg/models.py tests/test_embeddings.py
git commit -m "feat(M2): add Gemini embedding generation + pgvector similarity"
```

---

### Task 3: M5 — Graph Traversal RPC Wrappers

**Files:**
- Modify: `website/core/supabase_kg/repository.py` (append after `_auto_link`)
- Create: `tests/test_graph_rpcs.py`

- [ ] **Step 1: Write 3 failing tests**

Create `tests/test_graph_rpcs.py`:
```python
"""Tests for graph traversal RPC wrapper methods."""
from __future__ import annotations

from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest


@patch("website.core.supabase_kg.repository.get_supabase_client")
class TestGraphRPCs:
    def test_find_neighbors(self, mock_client):
        from website.core.supabase_kg.repository import KGRepository

        mock_rpc = MagicMock()
        mock_rpc.execute.return_value = MagicMock(data=[
            {"node_id": "B", "name": "B", "source_type": "generic",
             "summary": "", "tags": [], "url": "http://b", "depth": 1},
            {"node_id": "C", "name": "C", "source_type": "generic",
             "summary": "", "tags": [], "url": "http://c", "depth": 2},
        ])
        mock_client.return_value.rpc.return_value = mock_rpc

        repo = KGRepository()
        result = repo.find_neighbors(uuid4(), "A", depth=2)

        assert len(result) == 2
        assert result[0]["node_id"] == "B"
        assert result[1]["node_id"] == "C"

    def test_shortest_path(self, mock_client):
        from website.core.supabase_kg.repository import KGRepository

        mock_rpc = MagicMock()
        mock_rpc.execute.return_value = MagicMock(data=[
            {"path": ["A", "B", "C", "D", "E"], "depth": 4}
        ])
        mock_client.return_value.rpc.return_value = mock_rpc

        repo = KGRepository()
        result = repo.shortest_path(uuid4(), "A", "E")

        assert result is not None
        assert result["path"] == ["A", "B", "C", "D", "E"]
        assert result["depth"] == 4

    def test_isolated_nodes(self, mock_client):
        from website.core.supabase_kg.repository import KGRepository

        mock_rpc = MagicMock()
        mock_rpc.execute.return_value = MagicMock(data=[
            {"node_id": "orphan", "name": "Orphan", "source_type": "generic",
             "url": "http://orphan", "node_date": None}
        ])
        mock_client.return_value.rpc.return_value = mock_rpc

        repo = KGRepository()
        result = repo.isolated_nodes(uuid4())

        assert len(result) == 1
        assert result[0]["node_id"] == "orphan"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_graph_rpcs.py -v
```
Expected: FAIL — `AttributeError: 'KGRepository' object has no attribute 'find_neighbors'`

- [ ] **Step 3: Add RPC wrappers to KGRepository**

Append to `website/core/supabase_kg/repository.py` inside the `KGRepository` class, after `_auto_link` method (after line 385):

```python
    # ── Graph Traversal RPCs ────────────────────────────────────────────

    def find_neighbors(self, user_id: UUID, node_id: str, depth: int = 2) -> list[dict]:
        """K-hop neighbors via find_neighbors RPC."""
        depth = min(depth, 8)  # API-layer cap
        resp = self._client.rpc("find_neighbors", {
            "p_user_id": str(user_id), "p_node_id": node_id, "p_depth": depth,
        }).execute()
        return resp.data or []

    def shortest_path(self, user_id: UUID, source_id: str, target_id: str, max_depth: int = 10) -> dict | None:
        """Shortest path via shortest_path RPC."""
        resp = self._client.rpc("shortest_path", {
            "p_user_id": str(user_id), "p_source_id": source_id,
            "p_target_id": target_id, "p_max_depth": min(max_depth, 10),
        }).execute()
        return resp.data[0] if resp.data else None

    def top_connected(self, user_id: UUID, limit: int = 20) -> list[dict]:
        """Most connected nodes via top_connected_nodes RPC."""
        resp = self._client.rpc("top_connected_nodes", {
            "p_user_id": str(user_id), "p_limit": limit,
        }).execute()
        return resp.data or []

    def isolated_nodes(self, user_id: UUID) -> list[dict]:
        """Nodes with zero links via isolated_nodes RPC."""
        resp = self._client.rpc("isolated_nodes", {
            "p_user_id": str(user_id),
        }).execute()
        return resp.data or []

    def top_tags(self, user_id: UUID, limit: int = 20) -> list[dict]:
        """Most frequent tags via top_tags RPC."""
        resp = self._client.rpc("top_tags", {
            "p_user_id": str(user_id), "p_limit": limit,
        }).execute()
        return resp.data or []

    def similar_by_tags(self, user_id: UUID, node_id: str, limit: int = 10) -> list[dict]:
        """Nodes sharing most tags via similar_nodes RPC."""
        resp = self._client.rpc("similar_nodes", {
            "p_user_id": str(user_id), "p_node_id": node_id, "p_limit": limit,
        }).execute()
        return resp.data or []
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_graph_rpcs.py -v
```
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add website/core/supabase_kg/repository.py tests/test_graph_rpcs.py
git commit -m "feat(M5): add graph traversal RPC wrappers to KGRepository"
```

---

### Task 4: M1 — Entity Extraction

**Files:**
- Create: `website/core/supabase_kg/entity_extractor.py`
- Create: `tests/test_entity_extractor.py`

- [ ] **Step 1: Write 3 failing tests**

Create `tests/test_entity_extractor.py`:
```python
"""Tests for entity-relationship extraction."""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest


class TestEntityExtractionBasic:
    @pytest.mark.asyncio
    @patch("website.core.supabase_kg.entity_extractor._get_genai_client")
    async def test_extracts_entities_with_correct_types(self, mock_get_client):
        from website.core.supabase_kg.entity_extractor import EntityExtractor, ExtractionConfig

        step1_resp = MagicMock()
        step1_resp.text = "Entities: Python (Language), TensorFlow (Framework), Google (Organization)"
        step2_resp = MagicMock()
        step2_resp.text = json.dumps({
            "entities": [
                {"id": "python", "type": "Language", "description": "Programming language"},
                {"id": "tensorflow", "type": "Framework", "description": "ML framework"},
                {"id": "google", "type": "Organization", "description": "Tech company"},
            ],
            "relationships": [
                {"source": "google", "target": "tensorflow", "type": "CREATED_BY",
                 "strength": 9, "description": "Google created TF"}
            ],
        })
        mock_client = MagicMock()
        mock_client.models.generate_content.side_effect = [step1_resp, step2_resp]
        mock_get_client.return_value = mock_client

        extractor = EntityExtractor(config=ExtractionConfig(max_gleanings=0))
        result = await extractor.extract("TensorFlow by Google uses Python", "Test")

        assert len(result.entities) == 3
        assert all(e.type in ExtractionConfig().allowed_entity_types for e in result.entities)
        assert len(result.relationships) >= 1
        # Grounding instruction must be in Step 1 prompt
        call_args = str(mock_client.models.generate_content.call_args_list[0])
        assert "Do NOT" in call_args


class TestGleaning:
    @pytest.mark.asyncio
    @patch("website.core.supabase_kg.entity_extractor._get_genai_client")
    async def test_gleaning_adds_missed_entities(self, mock_get_client):
        from website.core.supabase_kg.entity_extractor import EntityExtractor, ExtractionConfig

        step1_resp = MagicMock()
        step1_resp.text = "Entities: React (Framework), Meta (Organization)"
        step2_resp = MagicMock()
        step2_resp.text = json.dumps({
            "entities": [
                {"id": "react", "type": "Framework", "description": "UI library"},
                {"id": "meta", "type": "Organization", "description": "Tech co"},
            ],
            "relationships": [],
        })
        gleaning_resp = MagicMock()
        gleaning_resp.text = json.dumps({
            "entities": [
                {"id": "javascript", "type": "Language", "description": "JS lang"},
            ],
            "relationships": [
                {"source": "react", "target": "javascript", "type": "USES",
                 "strength": 10, "description": "React uses JS"},
            ],
        })
        mock_client = MagicMock()
        mock_client.models.generate_content.side_effect = [step1_resp, step2_resp, gleaning_resp]
        mock_get_client.return_value = mock_client

        extractor = EntityExtractor(config=ExtractionConfig(max_gleanings=1))
        result = await extractor.extract("React by Meta uses JavaScript", "Test")

        assert len(result.entities) == 3
        assert "javascript" in {e.id for e in result.entities}


class TestEntityDedup:
    def test_type_matching_prevents_false_merge(self):
        from website.core.supabase_kg.entity_extractor import _deduplicate_entities, ExtractedEntity

        entities = [
            ExtractedEntity(id="javascript", type="Language", description="JS lang"),
            ExtractedEntity(id="js", type="Language", description="JavaScript"),
            ExtractedEntity(id="python", type="Language", description="Python"),
            ExtractedEntity(id="react", type="Framework", description="UI lib"),
        ]

        def mock_embed(name, **kwargs):
            vecs = {
                "javascript": [1.0, 0.0, 0.0],
                "js": [0.98, 0.1, 0.05],
                "python": [0.0, 1.0, 0.0],
                "react": [0.0, 0.0, 1.0],
            }
            return vecs.get(name, [0.0, 0.0, 0.0])

        result = _deduplicate_entities(entities, mock_embed, threshold=0.90)
        ids = {e.id for e in result}

        # JS + JavaScript merge (same type + high similarity)
        assert len(result) == 3
        assert "python" in ids
        assert "react" in ids
        assert not ("javascript" in ids and "js" in ids)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_entity_extractor.py -v
```
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement entity_extractor.py**

Create `website/core/supabase_kg/entity_extractor.py`. The full implementation must include:

- `ExtractedEntity(BaseModel)`: fields `id`, `type`, `description`
- `ExtractedRelationship(BaseModel)`: fields `source`, `target`, `type`, `strength` (1-10), `description`
- `ExtractionResult(BaseModel)`: fields `entities`, `relationships`
- `ExtractionConfig` dataclass with allowed types, `max_gleanings` (default 1, hard cap `min(val, 3)`), `dedup_similarity_threshold` (0.90), `model`
- `EntityExtractor` class with async `extract(summary: str, title: str) -> ExtractionResult`:
  - Step 1: Free-form analysis with grounding instruction + tech-article few-shot example
  - Step 2: Structured JSON via `response_mime_type="application/json"` + Pydantic `model_json_schema()`
  - Step 3: Gleaning loop (multi-turn conversation context, zero-new-entities termination)
  - 10s timeout per Gemini call
- `_deduplicate_entities(entities, embed_fn, threshold)`: cosine similarity check with **type-matching guard** (only merge when `type_a.lower() == type_b.lower()`)
- Post-processing: normalize IDs (lowercase, strip special chars), UPPER_SNAKE_CASE relationships, validate against allowed types
- Graceful degradation: return empty `ExtractionResult` on total failure

Key detail: the Step 1 prompt MUST contain `"Do NOT add any entity or relationship that is not explicitly mentioned in the content. Do NOT infer or hallucinate connections."` and the React/Meta/Andrew Clark few-shot example from the spec.

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_entity_extractor.py -v
```
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add website/core/supabase_kg/entity_extractor.py tests/test_entity_extractor.py
git commit -m "feat(M1): add entity extraction with gleaning + type-aware dedup"
```

---

### Task 5: M4 — NL Graph Query

**Files:**
- Create: `website/core/supabase_kg/nl_query.py`
- Create: `tests/test_nl_query.py`

- [ ] **Step 1: Write 5 failing tests**

Create `tests/test_nl_query.py`:
```python
"""Tests for NL-to-SQL graph query engine."""
from __future__ import annotations

import re
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest


@patch("website.core.supabase_kg.nl_query._get_genai_client")
class TestNLQuery:
    @pytest.mark.asyncio
    async def test_basic_query(self, mock_get_client):
        from website.core.supabase_kg.nl_query import NLGraphQuery

        uid = uuid4()
        sql = f"SELECT id, name FROM public.kg_nodes WHERE user_id = '{uid}' LIMIT 10"
        mock_client = MagicMock()
        mock_client.models.generate_content.side_effect = [
            MagicMock(text=sql),
            MagicMock(text="You have articles."),
        ]
        mock_get_client.return_value = mock_client

        mock_sb = MagicMock()
        mock_sb.rpc.return_value.execute.return_value = MagicMock(
            data=[{"id": "yt-test", "name": "Test"}]
        )

        query = NLGraphQuery(mock_sb)
        result = await query.ask("How many articles?", uid)

        assert result.sql == sql
        assert len(result.raw_result) == 1
        assert result.retries == 0

    @pytest.mark.asyncio
    async def test_rejects_mutations(self, mock_get_client):
        from website.core.supabase_kg.nl_query import NLGraphQuery, NLQueryError

        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = MagicMock(
            text="DELETE FROM kg_nodes"
        )
        mock_get_client.return_value = mock_client

        query = NLGraphQuery(MagicMock())
        with pytest.raises(NLQueryError, match="only answer questions"):
            await query.ask("Delete everything", uuid4())

    @pytest.mark.asyncio
    async def test_strips_markdown_fences(self, mock_get_client):
        from website.core.supabase_kg.nl_query import NLGraphQuery

        uid = uuid4()
        fenced = f"```sql\nSELECT id FROM public.kg_nodes WHERE user_id = '{uid}'\n```"
        mock_client = MagicMock()
        mock_client.models.generate_content.side_effect = [
            MagicMock(text=fenced),
            MagicMock(text="Results."),
        ]
        mock_get_client.return_value = mock_client
        mock_sb = MagicMock()
        mock_sb.rpc.return_value.execute.return_value = MagicMock(data=[{"id": "x"}])

        query = NLGraphQuery(mock_sb)
        result = await query.ask("Show articles", uid)
        assert "```" not in result.sql

    @pytest.mark.asyncio
    async def test_error_retry(self, mock_get_client):
        from website.core.supabase_kg.nl_query import NLGraphQuery

        uid = uuid4()
        bad = f"SELECTT id FROM kg_nodes WHERE user_id = '{uid}'"
        good = f"SELECT id FROM public.kg_nodes WHERE user_id = '{uid}'"
        mock_client = MagicMock()
        mock_client.models.generate_content.side_effect = [
            MagicMock(text=bad), MagicMock(text=good), MagicMock(text="Done."),
        ]
        mock_get_client.return_value = mock_client
        mock_sb = MagicMock()
        mock_sb.rpc.return_value.execute.side_effect = [
            Exception("syntax error"), MagicMock(data=[]), MagicMock(data=[{"id": "x"}]),
        ]

        query = NLGraphQuery(mock_sb)
        result = await query.ask("Show articles", uid)
        assert result.retries == 1

    @pytest.mark.asyncio
    async def test_timeout_returns_504(self, mock_get_client):
        from website.core.supabase_kg.nl_query import NLGraphQuery, NLQueryError

        uid = uuid4()
        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = MagicMock(
            text=f"SELECT * FROM public.kg_nodes WHERE user_id = '{uid}'"
        )
        mock_get_client.return_value = mock_client
        mock_sb = MagicMock()
        mock_sb.rpc.return_value.execute.side_effect = [
            MagicMock(data=[]),
            Exception("canceling statement due to statement timeout"),
        ]

        query = NLGraphQuery(mock_sb)
        with pytest.raises(NLQueryError) as exc_info:
            await query.ask("Complex query", uid)
        assert exc_info.value.status_code == 504
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_nl_query.py -v
```
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement nl_query.py**

Create `website/core/supabase_kg/nl_query.py` with:

- `NLQueryResult(BaseModel)`: `question`, `sql`, `raw_result`, `answer`, `latency_ms`, `retries`
- `NLQueryError(Exception)`: `status_code`, `user_message`
- `NLGraphQuery` class:
  - System prompt with schema + `VALID source_type VALUES` + domain vocabulary + RULES + 5 few-shot examples (from spec)
  - `_strip_sql_artifacts(text)`: `re.sub(r'^```(?:sql)?\s*|\s*```$', '', text.strip(), flags=re.MULTILINE).strip()`
  - `_safety_check(sql)`: **SELECT-only allowlist** — `re.match(r'^\s*SELECT\b', sql, re.IGNORECASE)` + reject if `;` found
  - `ask(question, user_id)` async method:
    1. Generate SQL via Gemini
    2. Strip artifacts
    3. Safety check (raise `NLQueryError(400, "I can only answer questions...")`)
    4. EXPLAIN validation via RPC. On failure, guided retry with COMMON_MISTAKES
    5. Execute via `execute_kg_query` RPC
    6. Python-side cap: `results = results[:50]`
    7. Format with second Gemini call
    8. Return `NLQueryResult`
  - Error handling: timeout → `NLQueryError(504, "too complex")`, generic → `NLQueryError(500, "Something went wrong")`

Key detail: The retry prompt MUST include COMMON_MISTAKES section: "tags is ARRAY, use unnest(); source_type values must be quoted; use node_date not date; kg_links uses source_node_id/target_node_id; qualify with public. prefix."

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_nl_query.py -v
```
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add website/core/supabase_kg/nl_query.py tests/test_nl_query.py
git commit -m "feat(M4): add NL-to-SQL query engine with SELECT allowlist + guided retry"
```

---

## Phase 2 — Analytics & Retrieval (after Task 2)

### Task 6: M3 — Graph Intelligence (NetworkX)

**Files:**
- Create: `website/core/supabase_kg/analytics.py`
- Create: `tests/test_analytics.py`

- [ ] **Step 1: Write 3 failing tests**

Create `tests/test_analytics.py`:
```python
"""Tests for NetworkX graph analytics."""
from __future__ import annotations

import pytest
from website.core.supabase_kg.models import KGGraph, KGGraphNode, KGGraphLink


def _graph(nodes, links):
    return KGGraph(
        nodes=[KGGraphNode(id=n, name=n, group="generic", url=f"http://{n}") for n in nodes],
        links=[KGGraphLink(source=s, target=t, relation=r) for s, t, r in links],
    )


class TestGraphMetrics:
    def test_basic_graph(self):
        from website.core.supabase_kg.analytics import compute_graph_metrics

        g = _graph(
            ["A", "B", "C", "D", "E"],
            [("A","B","t1"), ("B","C","t2"), ("A","C","t3"),
             ("C","D","t4"), ("D","E","t5"), ("A","E","t6")],
        )
        m = compute_graph_metrics(g)

        assert len(m.pagerank) == 5
        assert all(v > 0 for v in m.pagerank.values())
        assert m.num_communities >= 1
        assert len(m.betweenness) == 5
        assert len(m.closeness) == 5
        assert m.num_components == 1

    def test_empty_graph(self):
        from website.core.supabase_kg.analytics import compute_graph_metrics

        m = compute_graph_metrics(KGGraph(nodes=[], links=[]))
        assert m.pagerank == {}
        assert m.num_communities == 0

    def test_single_node(self):
        from website.core.supabase_kg.analytics import compute_graph_metrics

        m = compute_graph_metrics(_graph(["A"], []))
        assert m.pagerank.get("A", 0) > 0
        assert m.num_communities == 1
        assert m.num_components == 1
```

- [ ] **Step 2: Run to verify fail**

```bash
pytest tests/test_analytics.py -v
```
Expected: FAIL

- [ ] **Step 3: Implement analytics.py**

Create `website/core/supabase_kg/analytics.py`:
```python
"""NetworkX graph analytics — PageRank, Louvain communities, centrality."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

import networkx as nx

from .models import KGGraph


@dataclass
class GraphMetrics:
    pagerank: dict[str, float] = field(default_factory=dict)
    communities: dict[str, int] = field(default_factory=dict)
    betweenness: dict[str, float] = field(default_factory=dict)
    closeness: dict[str, float] = field(default_factory=dict)
    num_communities: int = 0
    num_components: int = 0
    computed_at: str = ""


def _build_graph(graph: KGGraph) -> nx.Graph:
    """Undirected — KG links are bidirectional (source/target arbitrary)."""
    G = nx.Graph()
    node_ids = {n.id for n in graph.nodes}
    for node in graph.nodes:
        G.add_node(node.id, name=node.name, group=node.group, tags=node.tags)
    for link in graph.links:
        if link.source in node_ids and link.target in node_ids:
            G.add_edge(link.source, link.target, relation=link.relation)
    return G


def compute_graph_metrics(graph: KGGraph) -> GraphMetrics:
    if not graph.nodes:
        return GraphMetrics()

    G = _build_graph(graph)
    n = len(G)

    if n < 2:
        nid = graph.nodes[0].id
        return GraphMetrics(
            pagerank={nid: 1.0}, communities={nid: 0},
            betweenness={nid: 0.0}, closeness={nid: 0.0},
            num_communities=1, num_components=1,
            computed_at=datetime.now(timezone.utc).isoformat(),
        )

    pr = nx.pagerank(G, alpha=0.85)

    # seed=42 for deterministic assignments (prevents color flicker)
    community_sets = list(nx.community.louvain_communities(G, resolution=1.0, seed=42))
    # Normalize: sort by size descending for stable color mapping
    community_sets.sort(key=len, reverse=True)
    communities = {}
    for idx, comm in enumerate(community_sets):
        for node_id in comm:
            communities[node_id] = idx

    betweenness = nx.betweenness_centrality(G, k=min(100, n))
    closeness = nx.closeness_centrality(G, wf_improved=True)

    return GraphMetrics(
        pagerank=pr, communities=communities,
        betweenness=betweenness, closeness=closeness,
        num_communities=len(community_sets),
        num_components=nx.number_connected_components(G),
        computed_at=datetime.now(timezone.utc).isoformat(),
    )
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_analytics.py -v
```
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add website/core/supabase_kg/analytics.py tests/test_analytics.py
git commit -m "feat(M3): add NetworkX graph analytics with deterministic Louvain"
```

---

### Task 7: M6 — Hybrid Retrieval

**Files:**
- Create: `website/core/supabase_kg/retrieval.py`
- Create: `tests/test_hybrid_retrieval.py`

- [ ] **Step 1: Write 3 failing tests**

Create `tests/test_hybrid_retrieval.py`:
```python
"""Tests for hybrid 3-stream RRF retrieval."""
from __future__ import annotations

from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest


@patch("website.core.supabase_kg.retrieval.generate_embedding")
class TestHybridSearch:
    def test_returns_ranked_results(self, mock_embed):
        from website.core.supabase_kg.retrieval import hybrid_search

        mock_embed.return_value = [0.1] * 768
        mock_sb = MagicMock()
        mock_sb.rpc.return_value.execute.return_value = MagicMock(data=[
            {"id": "n1", "name": "Node 1", "source_type": "generic",
             "summary": "test", "tags": ["python"], "url": "http://1", "score": 0.85},
            {"id": "n2", "name": "Node 2", "source_type": "youtube",
             "summary": "test", "tags": ["ml"], "url": "http://2", "score": 0.72},
        ])

        results = hybrid_search(mock_sb, "python ml", uuid4(), seed_node_id="n1")
        assert len(results) == 2
        assert results[0]["score"] >= results[1]["score"]

    def test_works_without_embeddings(self, mock_embed):
        from website.core.supabase_kg.retrieval import hybrid_search

        mock_embed.return_value = []
        mock_sb = MagicMock()
        mock_sb.rpc.return_value.execute.return_value = MagicMock(data=[])

        results = hybrid_search(mock_sb, "python", uuid4())
        assert results == []  # No crash

    def test_works_without_seed_node(self, mock_embed):
        from website.core.supabase_kg.retrieval import hybrid_search

        mock_embed.return_value = [0.1] * 768
        mock_sb = MagicMock()
        mock_sb.rpc.return_value.execute.return_value = MagicMock(data=[])

        results = hybrid_search(mock_sb, "test", uuid4(), seed_node_id=None)
        assert results == []
```

- [ ] **Step 2: Run to verify fail**

```bash
pytest tests/test_hybrid_retrieval.py -v
```
Expected: FAIL

- [ ] **Step 3: Implement retrieval.py**

Create `website/core/supabase_kg/retrieval.py`:
```python
"""Hybrid 3-stream RRF retrieval (semantic + fulltext + graph).

RRF: score = sum(1/(k+rank) * weight) per stream. k=60 (Cormack et al.)
Superior to LangChain's naive string concatenation.
"""
from __future__ import annotations

import logging
from uuid import UUID

from .embeddings import generate_embedding

logger = logging.getLogger(__name__)


def hybrid_search(
    supabase_client,
    query: str,
    user_id: UUID,
    seed_node_id: str | None = None,
    semantic_weight: float = 0.5,
    fulltext_weight: float = 0.3,
    graph_weight: float = 0.2,
    limit: int = 20,
) -> list[dict]:
    """3-stream RRF search. seed_node_id optional — graph stream skipped when None."""
    embedding = generate_embedding(query, task_type="RETRIEVAL_QUERY")
    if not embedding:
        embedding = [0.0] * 768
        logger.warning("Embedding failed, semantic stream disabled")

    try:
        resp = supabase_client.rpc("hybrid_kg_search", {
            "query_text": query,
            "query_embedding": embedding,
            "p_user_id": str(user_id),
            "p_seed_node_id": seed_node_id,
            "semantic_weight": semantic_weight,
            "fulltext_weight": fulltext_weight,
            "graph_weight": graph_weight,
            "match_count": limit,
            "k": 60,
        }).execute()
        return resp.data or []
    except Exception as exc:
        logger.error("Hybrid search failed: %s", exc)
        return []
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_hybrid_retrieval.py -v
```
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add website/core/supabase_kg/retrieval.py tests/test_hybrid_retrieval.py
git commit -m "feat(M6): add hybrid 3-stream RRF retrieval"
```

---

## Phase 3 — Integration

### Task 8: Wire Everything into API Routes + Exports

**Files:**
- Modify: `website/core/supabase_kg/__init__.py`
- Modify: `website/api/routes.py`

- [ ] **Step 1: Update __init__.py exports**

Replace `website/core/supabase_kg/__init__.py` contents:
```python
from .client import get_supabase_client, is_supabase_configured
from .models import (
    KGGraph, KGGraphLink, KGGraphNode,
    KGLink, KGLinkCreate, KGNode, KGNodeCreate,
    KGUser, KGUserCreate,
)
from .repository import KGRepository
from .analytics import compute_graph_metrics, GraphMetrics
from .embeddings import generate_embedding, find_similar_nodes, should_create_semantic_link
from .entity_extractor import EntityExtractor, ExtractionConfig, ExtractionResult
from .nl_query import NLGraphQuery, NLQueryError
from .retrieval import hybrid_search

__all__ = [
    "get_supabase_client", "is_supabase_configured",
    "KGGraph", "KGGraphLink", "KGGraphNode",
    "KGLink", "KGLinkCreate", "KGNode", "KGNodeCreate",
    "KGRepository", "KGUser", "KGUserCreate",
    "compute_graph_metrics", "GraphMetrics",
    "generate_embedding", "find_similar_nodes", "should_create_semantic_link",
    "EntityExtractor", "ExtractionConfig", "ExtractionResult",
    "NLGraphQuery", "NLQueryError",
    "hybrid_search",
]
```

- [ ] **Step 2: Enrich GET /api/graph with analytics (M3)**

In `website/api/routes.py`, modify `graph_data()` (line 83-108). After `result = graph.model_dump()` (line 98), add before caching:

```python
            from website.core.supabase_kg.analytics import compute_graph_metrics
            metrics = compute_graph_metrics(graph)
            for node in result["nodes"]:
                nid = node["id"]
                node["pagerank"] = metrics.pagerank.get(nid, 0)
                node["community"] = metrics.communities.get(nid, 0)
                node["betweenness"] = metrics.betweenness.get(nid, 0)
                node["closeness"] = metrics.closeness.get(nid, 0)
            result["meta"] = {
                "communities": metrics.num_communities,
                "components": metrics.num_components,
                "computed_at": metrics.computed_at,
            }
```

- [ ] **Step 3: Add embedding + entity extraction to POST /api/summarize**

In `website/api/routes.py`, in the `summarize()` handler (line 111-172), after `result = await summarize_url(body.url)` (line 123) and before the file-store `add_node()` call (line 127), add:

```python
        # Intelligence layer: embedding + entity extraction (parallel)
        import asyncio
        from website.core.supabase_kg.embeddings import generate_embedding
        from website.core.supabase_kg.entity_extractor import EntityExtractor

        brief = result.get("brief_summary") or result["summary"][:500]
        embedding_task = asyncio.to_thread(generate_embedding, brief)
        extractor = EntityExtractor()
        entity_task = extractor.extract(brief, result["title"])

        embedding_result, entity_result = await asyncio.gather(
            embedding_task, entity_task, return_exceptions=True,
        )
        if isinstance(embedding_result, Exception):
            embedding_result = []
        if isinstance(entity_result, Exception):
            entity_result = None
```

Then pass `embedding_result` to the Supabase `KGNodeCreate` (around line 151):
```python
                node_create = KGNodeCreate(
                    id=sb_node_id,
                    name=result["title"],
                    source_type=result["source_type"],
                    tags=result.get("tags", []),
                    url=result["source_url"],
                    summary=result.get("brief_summary") or result["summary"][:200],
                    embedding=embedding_result if embedding_result else None,
                    metadata={"entities": [e.model_dump() for e in entity_result.entities]} if entity_result else {},
                )
```

- [ ] **Step 4: Add POST /graph/query endpoint (M4)**

Append to `website/api/routes.py`:

```python
class NLQueryRequest(BaseModel):
    question: str

    @field_validator("question")
    @classmethod
    def validate_question(cls, v: str) -> str:
        v = v.strip()
        if not v or len(v) > 1000:
            raise ValueError("Question must be 1-1000 characters")
        return v


# Separate rate limit bucket for NL queries: 5/min
_nl_rate_store: dict[str, list[float]] = defaultdict(list)
_NL_RATE_LIMIT = 5


@router.post("/graph/query")
async def nl_graph_query(body: NLQueryRequest, request: Request):
    """Natural language query against the knowledge graph."""
    ip = request.client.host if request.client else "unknown"
    now = time.time()
    _nl_rate_store[ip] = [t for t in _nl_rate_store[ip] if now - t < _RATE_WINDOW]
    if len(_nl_rate_store[ip]) >= _NL_RATE_LIMIT:
        raise HTTPException(429, "Too many queries. Please wait a minute.")
    _nl_rate_store[ip].append(now)

    sb = _get_supabase()
    if not sb:
        raise HTTPException(503, "Knowledge graph not configured")
    repo, user_id = sb

    from uuid import UUID
    from website.core.supabase_kg.nl_query import NLGraphQuery, NLQueryError

    query_engine = NLGraphQuery(repo._client)
    try:
        result = await query_engine.ask(body.question, UUID(user_id))
        return result.model_dump()
    except NLQueryError as e:
        raise HTTPException(e.status_code, e.user_message)
```

- [ ] **Step 5: Add POST /graph/search endpoint (M6)**

Append to `website/api/routes.py`:

```python
class SearchRequest(BaseModel):
    query: str
    seed_node_id: str | None = None

    @field_validator("query")
    @classmethod
    def validate_query(cls, v: str) -> str:
        v = v.strip()
        if not v or len(v) > 500:
            raise ValueError("Query must be 1-500 characters")
        return v


@router.post("/graph/search")
async def graph_search(body: SearchRequest, request: Request):
    """Hybrid semantic + fulltext + graph search."""
    ip = request.client.host if request.client else "unknown"
    if not _check_rate_limit(ip):
        raise HTTPException(429, "Rate limit exceeded.")

    sb = _get_supabase()
    if not sb:
        raise HTTPException(503, "Knowledge graph not configured")
    repo, user_id = sb

    from uuid import UUID
    from website.core.supabase_kg.retrieval import hybrid_search

    results = hybrid_search(repo._client, body.query, UUID(user_id), body.seed_node_id)
    return {"results": results}
```

- [ ] **Step 6: Run all tests for regressions**

```bash
pytest tests/ -v --ignore=tests/integration_tests
```
Expected: All existing + new tests pass

- [ ] **Step 7: Commit**

```bash
git add website/core/supabase_kg/__init__.py website/api/routes.py
git commit -m "feat: wire all intelligence modules into API routes"
```

---

### Task 9: Frontend — PageRank Sizing

**Files:**
- Modify: `website/features/knowledge_graph/js/app.js:205-208`

- [ ] **Step 1: Replace degree-based sizing**

In `website/features/knowledge_graph/js/app.js`, find the node sizing code (around line 205-208):
```javascript
        const deg = nodeDegrees[node.id] || 1;
        const isSpotlight = spotlightId && spotlightId === node.id;
        const baseRadius = Math.min(2 + deg * 0.3, 5);
```

Replace with:
```javascript
        // PageRank-based sizing (fallback to degree if pagerank missing)
        const pr = node.pagerank || 0;
        const isSpotlight = spotlightId && spotlightId === node.id;
        const baseRadius = pr > 0
          ? 2 + (pr / (window._maxPagerank || 0.001)) * 4
          : Math.min(2 + (nodeDegrees[node.id] || 1) * 0.3, 5);
```

Also add after graph data loads (near the `computeDegrees()` call or data fetch callback):
```javascript
      window._maxPagerank = Math.max(...graphData.nodes.map(n => n.pagerank || 0), 0.001);
```

- [ ] **Step 2: Verify graph renders**

Open the KG page in browser. Nodes should be sized by PageRank when available, fallback to degree for old data.

- [ ] **Step 3: Commit**

```bash
git add website/features/knowledge_graph/js/app.js
git commit -m "feat(M3): PageRank-based node sizing in 3D graph"
```

---

## Phase 4 — Verification

### Task 10: Full Test Suite + Backfill + Latency Check

- [ ] **Step 1: Run complete test suite**

```bash
pytest tests/ -v --ignore=tests/integration_tests
```
Expected: 20+ new tests pass alongside all existing tests. Zero failures.

- [ ] **Step 2: Create backfill script**

Create `scripts/backfill_embeddings.py`:
```python
"""One-time backfill: generate embeddings for existing nodes missing them."""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from website.core.supabase_kg import get_supabase_client, is_supabase_configured
from website.core.supabase_kg.embeddings import generate_embeddings_batch


def main():
    if not is_supabase_configured():
        print("Supabase not configured. Set SUPABASE_URL and SUPABASE_ANON_KEY.")
        return

    client = get_supabase_client()
    resp = client.table("kg_nodes").select("id, summary").is_("embedding", "null").execute()
    nodes = resp.data or []
    print(f"Found {len(nodes)} nodes missing embeddings")

    batch_size = 50  # Conservative for rate-limiting (API supports 250)
    for i in range(0, len(nodes), batch_size):
        batch = nodes[i:i + batch_size]
        texts = [n.get("summary") or "" for n in batch]
        embeddings = generate_embeddings_batch(texts)

        for node, emb in zip(batch, embeddings):
            if emb:
                client.table("kg_nodes").update(
                    {"embedding": emb}
                ).eq("id", node["id"]).execute()

        done = min(i + batch_size, len(nodes))
        print(f"Embedded {done}/{len(nodes)} nodes")

    print("Backfill complete.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Run backfill** (if Supabase is configured)

```bash
python scripts/backfill_embeddings.py
```

- [ ] **Step 4: Spawn latency verification subagent**

Spawn a subagent to measure all endpoint latencies against deployed Render instance:
- `GET /api/graph`: budget <2s
- `POST /api/summarize`: budget <30s
- `POST /api/graph/query`: budget <5s
- `POST /api/graph/search`: budget <1s

10 calls each, measure p50/p95/p99. Flag any endpoint exceeding budget.

- [ ] **Step 5: Final commit**

```bash
git add scripts/backfill_embeddings.py
git commit -m "feat: add embedding backfill script + verify all tests pass"
```

---

## Summary

| Task | Module | Tests | Phase | Parallel? |
|------|--------|-------|-------|-----------|
| 1 | Schema + Deps | 0 | 1 | Yes |
| 2 | M2 Embeddings | 3 | 1 | Yes |
| 3 | M5 Graph RPCs | 3 | 1 | Yes |
| 4 | M1 Entity Extraction | 3 | 1 | Yes |
| 5 | M4 NL Query | 5 | 1 | Yes |
| 6 | M3 Graph Analytics | 3 | 2 | After T2 |
| 7 | M6 Hybrid Retrieval | 3 | 2 | After T2 |
| 8 | Integration | 0 (regression) | 3 | Sequential |
| 9 | Frontend | 0 (visual) | 3 | After T6 |
| 10 | Verification | 0 (latency) | 4 | Sequential |
| **Total** | **6 modules** | **20 tests** | **4 phases** | |
