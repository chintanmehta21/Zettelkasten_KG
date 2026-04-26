# RAG Improvements iter-01 & iter-02 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Apply all four RAG-improvement phases (metadata layer, cross-encoder header, context distillation, KG-RAG coupling) wide-net across two iterations, each gated by deploy + Claude-in-Chrome browser verification on `www.zettelkasten.in`. iter-02 refines based on iter-01 measurements.

**Architecture:** Each iter applies all 4 phases. iter-01 adds Phase 0 prerequisites (fix iter-06 leftover prod bugs, add deps). Each phase is feature-flag-gated where it touches the request path. Eval runs on a freshly-created Kasten of a different topic from AI/ML Foundations. Composite-score regression gate (>5% drop = auto-revert).

**Tech Stack:** Python 3.12, FastAPI, Supabase (Postgres + RLS + RPC), pgvector, BGE bi-encoder + BGE cross-encoder ONNX, FlashRank, Gemini 2.5 (Flash / Flash-Lite / Pro via key pool), GitHub Actions cron, DigitalOcean blue/green Docker Compose. New deps: `dateparser>=1.2`, `tldextract>=5.1`.

**Source spec:** `docs/superpowers/specs/2026-04-26-rag-improvements-iter-01-02-design.md`

---

## File Structure

### iter-01 — Phase 0
- Create: `supabase/website/kg_public/migrations/2026-04-26_fix_rag_bulk_add_to_sandbox.sql`
- Modify: `website/api/routes.py` — assert `added_count == len(requested)` post-RPC
- Modify: `website/features/user_home/js/index.js` (or equivalent; verify path) — rebind Add button via event delegation
- Modify: `website/features/user_kastens/js/index.js` (or equivalent; verify path) — rebind Create button via event delegation
- Modify: `ops/requirements.txt` — add `dateparser>=1.2`, `tldextract>=5.1`
- Test: `tests/integration_tests/test_rag_sandbox_rpc.py`

### iter-01 — Phase 1 (metadata layer)
- Create: `website/features/rag_pipeline/query/metadata.py` — `QueryMetadata`, `QueryMetadataExtractor`
- Create: `website/features/rag_pipeline/ingest/metadata_enricher.py`
- Create: `ops/scripts/backfill_metadata.py`
- Modify: `website/features/rag_pipeline/retrieval/hybrid.py` — add boosts in `_dedup_and_fuse`
- Modify: `website/features/rag_pipeline/orchestrator.py` — wire extractor into `_prepare_query`
- Modify: `website/features/rag_pipeline/service.py` — instantiate extractor at startup
- Modify: `supabase/website/kg_public/schema.sql` — add `metadata_enriched_at` column to `kg_node_chunks`
- Test: `tests/unit/rag/test_query_metadata.py`, `tests/unit/rag/test_recency_boost.py`

### iter-01 — Phase 2 (cross-encoder header)
- Modify: `website/features/rag_pipeline/rerank/cascade.py` — enrich `_passage_text`
- Test: `tests/unit/rag/test_passage_text.py`

### iter-01 — Phase 3 (context distillation)
- Create: `website/features/rag_pipeline/context/distiller.py` — `EvidenceCompressor`
- Modify: `website/features/rag_pipeline/context/assembler.py` — wire compressor + per-LLM-tier budget
- Modify: `website/features/rag_pipeline/orchestrator.py` — pass model to assembler
- Test: `tests/unit/rag/test_evidence_compressor.py`

### iter-01 — Phase 4 (KG-RAG coupling)
- Create: `website/features/rag_pipeline/retrieval/planner.py` — `RetrievalPlanner` adapter
- Modify: `website/features/kg_features/retrieval.py` — add `expand_subgraph(node_ids, depth)` if absent
- Create: `supabase/website/kg_public/migrations/2026-04-26_kg_usage_edges.sql`
- Create: `ops/scripts/recompute_usage_edges.py`
- Create: `.github/workflows/recompute_usage_edges.yml`
- Modify: `website/features/rag_pipeline/retrieval/graph_score.py` — read usage-edge weights
- Modify: `website/features/rag_pipeline/orchestrator.py` — wire planner before retrieve
- Test: `tests/unit/rag/test_retrieval_planner.py`, `tests/integration_tests/test_kg_usage_edges.py`

### iter-01 — Eval
- Create: `docs/rag_eval/<kasten-slug>/iter-01/{README.md,queries.json,qa_pairs.md,answers.json,eval.json,scores.md,ablation_eval.json,atomic_facts.json,ingest.json,kasten.json,kg_snapshot.json,kg_changes.md,kg_recommendations.json,diff.md,improvement_delta.json,manual_review.md,next_actions.md,screenshots/}`

### iter-02
- Conditional refinements per `next_actions.md`; same eval folder shape under `iter-02/`
- Create: `website/features/rag_pipeline/query/metadata_cache_supabase.py` — Supabase write-through escalation

---

# ITERATION 01

## Phase 0a — Topic discovery (main Claude, parallel)

### Task 1: Discover Naruto's topic clusters via Claude-in-Chrome

**Files:**
- Create: `docs/rag_eval/_kasten_topic_discovery.json` (working artifact, moved into iter-01 folder later)

- [ ] **Step 1: Open Chrome via mcp__Claude_in_Chrome MCP, navigate to `https://www.zettelkasten.in`, log in as Naruto.** Verify the displayed user matches `naruto@zettelkasten.local`. Take screenshot, save as `naruto-login-confirmed.png`.

- [ ] **Step 2: Read Naruto's full graph.** Run in browser console:
```js
fetch('/api/graph', {credentials: 'include'}).then(r => r.json()).then(d => copy(JSON.stringify(d, null, 2)))
```
Save clipboard contents to `docs/rag_eval/_kasten_topic_discovery.json`.

- [ ] **Step 3: Cluster nodes by topic.** Read the JSON, group nodes by overlapping `tags` and `source_type`. Exclude nodes already in AI/ML Foundations Kasten (member node_ids from iter-06 README). Rank topics by `(zettel_count >= 7) AND (distinct_source_types >= 3)`.

- [ ] **Step 4: Pick the topic.**
- If a cluster qualifies → use it. Record kasten-slug (kebab-case from topic name).
- If 5-6 nodes qualify, pick that cluster + plan to add 2-3 fresh Zettels via Chrome to balance source types.
- If no cluster qualifies → fallback topic = `"Knowledge Management & Personal Productivity"`, slug = `knowledge-management`.

- [ ] **Step 5: Write decisions.** Append to `_kasten_topic_discovery.json`:
```json
{
  "selected_topic": "...",
  "kasten_slug": "...",
  "existing_node_ids": [...],
  "fresh_zettels_needed": [{"url": "...", "rationale": "..."}, ...],
  "source_type_breakdown": {"youtube": N, "reddit": N, ...}
}
```

- [ ] **Step 6: Commit.**
```bash
git add docs/rag_eval/_kasten_topic_discovery.json
git commit -m "chore: kasten topic discovery for iter-01"
```

---

## Phase 0b — Bug #2 fix (subagent-dispatchable)

### Task 2: Reproduce `rag_bulk_add_to_sandbox` silent no-op

**Files:**
- Test: `tests/integration_tests/test_rag_sandbox_rpc.py`

- [ ] **Step 1: Locate the SQL function definition.**
```bash
grep -rn "rag_bulk_add_to_sandbox" supabase/
```
Read the resulting file(s). Note the function signature (param types, RLS-relevant clauses).

- [ ] **Step 2: Write the failing test.**
```python
# tests/integration_tests/test_rag_sandbox_rpc.py
import os, pytest
from website.core.supabase_kg.client import get_supabase_client

@pytest.mark.live
def test_rag_bulk_add_to_sandbox_inserts_rows():
    sb = get_supabase_client()
    user_id = os.environ["NARUTO_USER_ID"]
    sandbox_id = os.environ["TEST_SANDBOX_ID"]
    node_ids = ["yt-andrej-karpathy-s-llm-in", "yt-transformer-architecture"]
    res = sb.rpc("rag_bulk_add_to_sandbox", {
        "p_user_id": user_id,
        "p_sandbox_id": sandbox_id,
        "p_node_ids": node_ids,
    }).execute()
    assert res.data["added_count"] == len(node_ids), f"silent no-op: {res.data}"
```

- [ ] **Step 3: Run the test against staging Supabase to confirm it fails.**
Run: `pytest tests/integration_tests/test_rag_sandbox_rpc.py --live -v`
Expected: FAIL with `added_count == 0`.

- [ ] **Step 4: Diagnose root cause.** Check (in order): RLS policy on `rag_sandbox_members` (does it require `auth.uid()` and is the function `SECURITY DEFINER`?); parameter types (`text[]` vs `uuid[]`); `ON CONFLICT` clause silently skipping legitimate inserts; missing user-sandbox ownership check.

- [ ] **Step 5: Patch the SQL.** Create `supabase/website/kg_public/migrations/2026-04-26_fix_rag_bulk_add_to_sandbox.sql` with `CREATE OR REPLACE FUNCTION` that fixes the identified root cause. Mark `SECURITY DEFINER` if the function needs to bypass RLS for cross-table inserts. Cast param types correctly.

- [ ] **Step 6: Apply migration to staging Supabase.**
```bash
psql $SUPABASE_DB_URL -f supabase/website/kg_public/migrations/2026-04-26_fix_rag_bulk_add_to_sandbox.sql
```

- [ ] **Step 7: Re-run test, confirm PASS.**

- [ ] **Step 8: Add Python-side assertion.** In `website/api/routes.py`, find the route that calls `rag_bulk_add_to_sandbox`. After the RPC call:
```python
result = sb.rpc("rag_bulk_add_to_sandbox", {...}).execute()
added = result.data.get("added_count", 0)
if added != len(requested_node_ids):
    raise HTTPException(500, detail=f"Sandbox bulk-add silently dropped rows: requested={len(requested_node_ids)} added={added}")
```

- [ ] **Step 9: Commit.**
```bash
git add supabase/website/kg_public/migrations/2026-04-26_fix_rag_bulk_add_to_sandbox.sql tests/integration_tests/test_rag_sandbox_rpc.py website/api/routes.py
git commit -m "fix: rag_bulk_add_to_sandbox silent no-op + assertion"
```

---

## Phase 0c — Bug #4 fix

### Task 3: Rebind form-submit handlers via event delegation

**Files:**
- Modify: `website/features/user_home/js/*.js`, `website/features/user_kastens/js/*.js` (verify exact paths)

- [ ] **Step 1: Locate the click handlers.**
```bash
grep -rn "addEventListener.*click" website/features/user_home/js/ website/features/user_kastens/js/
```
Read the matched files. Identify the Add and Create button handlers and their attachment timing.

- [ ] **Step 2: Identify the stale-ref pattern.** Look for handlers attached to elements that may be replaced after async auth lands (similar pattern to commit `72a1fcf`). Look for `document.getElementById(...)` followed by `.addEventListener(...)` at top-level script load.

- [ ] **Step 3: Switch to event delegation.** For each affected button, attach the click listener to a stable parent (e.g., the page container) and filter via `event.target.closest('[data-action="add-zettel"]')` or similar. The relevant data-action attributes already exist OR add them to the button HTML in the template.

```js
// Pattern:
document.body.addEventListener('click', (e) => {
  const btn = e.target.closest('[data-action="add-zettel"]');
  if (btn) handleAddZettel(e);
  const create = e.target.closest('[data-action="create-kasten"]');
  if (create) handleCreateKasten(e);
});
```

- [ ] **Step 4: Verify in dev.** Run the local server, open `/home`, click Add — verify network request fires. Same for `/home/kastens` Create.

- [ ] **Step 5: Commit.**
```bash
git add website/features/user_home/js/ website/features/user_kastens/js/
git commit -m "fix: rebind home and kastens buttons via event delegation"
```

---

## Phase 0d — Dependencies

### Task 4: Add metadata-extraction Python deps

**Files:**
- Modify: `ops/requirements.txt`

- [ ] **Step 1: Append to `ops/requirements.txt`:**
```
# Query metadata extraction (Phase 1)
dateparser>=1.2
tldextract>=5.1
cachetools>=5.3
```

- [ ] **Step 2: Install locally and verify imports.**
```bash
pip install -r ops/requirements.txt
python -c "import dateparser, tldextract, cachetools; print('ok')"
```
Expected: `ok`

- [ ] **Step 3: Run unit suite to confirm no breakage.**
```bash
pytest tests/unit/ -q
```
Expected: all pass.

- [ ] **Step 4: Commit.**
```bash
git add ops/requirements.txt
git commit -m "chore: add dateparser tldextract cachetools deps"
```

---

## Phase 1 — Metadata layer

### Task 5: `QueryMetadata` dataclass + `QueryMetadataExtractor` (C-pass only)

**Files:**
- Create: `website/features/rag_pipeline/query/metadata.py`
- Test: `tests/unit/rag/test_query_metadata.py`

- [ ] **Step 1: Write failing test for C-pass only.**
```python
# tests/unit/rag/test_query_metadata.py
import pytest
from website.features.rag_pipeline.query.metadata import QueryMetadataExtractor, QueryMetadata
from website.features.rag_pipeline.types import QueryClass, SourceType

@pytest.mark.asyncio
async def test_c_pass_extracts_time_and_domain():
    ext = QueryMetadataExtractor(key_pool=None, cache=None)  # A-pass disabled when no key_pool
    meta = await ext.extract("Last year's youtube talk on transformers from karpathy.com", query_class=QueryClass.LOOKUP)
    assert meta.start_date is not None
    assert meta.end_date is not None
    assert "karpathy.com" in meta.domains
    assert SourceType.YOUTUBE in meta.preferred_sources
```

- [ ] **Step 2: Run test to verify it fails.**
```bash
pytest tests/unit/rag/test_query_metadata.py -v
```
Expected: FAIL (module not found).

- [ ] **Step 3: Implement the module.**
```python
# website/features/rag_pipeline/query/metadata.py
from __future__ import annotations
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
import dateparser
import tldextract
from cachetools import TTLCache
from website.features.rag_pipeline.types import QueryClass, SourceType

# Static keyword map for source-type hints
_SOURCE_KEYWORDS = {
    SourceType.YOUTUBE: ("youtube", "yt", "video", "talk", "lecture", "podcast"),
    SourceType.REDDIT:  ("reddit", "subreddit", "r/", "thread", "comment"),
    SourceType.GITHUB:  ("github", "repo", "repository", "pull request", "issue"),
    SourceType.SUBSTACK: ("substack", "newsletter"),
    SourceType.WEB:     ("article", "blog", "post"),
}

# Top-author seed list (extend from existing graph as discovered)
_KNOWN_AUTHORS = ("karpathy", "lecun", "hinton", "bengio", "ng", "vaswani")

@dataclass
class QueryMetadata:
    start_date: datetime | None = None
    end_date: datetime | None = None
    authors: list[str] = field(default_factory=list)
    channels: list[str] = field(default_factory=list)
    domains: list[str] = field(default_factory=list)
    preferred_sources: list[SourceType] = field(default_factory=list)
    entities: list[str] = field(default_factory=list)
    confidence: float = 0.0  # raised when A-pass confirms

class QueryMetadataExtractor:
    def __init__(self, *, key_pool, cache: TTLCache | None = None):
        self._key_pool = key_pool
        self._cache = cache if cache is not None else TTLCache(maxsize=1024, ttl=3600)

    async def extract(self, text: str, *, query_class: QueryClass) -> QueryMetadata:
        key = self._normalize(text)
        if key in self._cache:
            return self._cache[key]
        meta = self._c_pass(text)
        if self._key_pool and self._needs_a_pass(meta):
            meta = await self._a_pass(text, meta)
        self._cache[key] = meta
        return meta

    @staticmethod
    def _normalize(text: str) -> str:
        return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", "", text.lower())).strip()

    def _c_pass(self, text: str) -> QueryMetadata:
        meta = QueryMetadata()
        # Time expressions
        parsed = dateparser.parse(text, settings={"RETURN_AS_TIMEZONE_AWARE": True})
        if parsed:
            meta.start_date = parsed
            meta.end_date = parsed
        # Domains
        for token in re.findall(r"\b[\w\-]+\.[a-z]{2,}\b", text.lower()):
            ext = tldextract.extract(token)
            if ext.domain and ext.suffix:
                meta.domains.append(f"{ext.domain}.{ext.suffix}")
        # Source-type keywords
        text_lower = text.lower()
        for src, keywords in _SOURCE_KEYWORDS.items():
            if any(k in text_lower for k in keywords):
                meta.preferred_sources.append(src)
        # Known authors (cheap)
        for author in _KNOWN_AUTHORS:
            if author in text_lower:
                meta.authors.append(author)
        return meta

    def _needs_a_pass(self, meta: QueryMetadata) -> bool:
        # Skip A-pass if C-pass already filled author AND domain AND date
        return not (meta.authors and meta.domains and meta.start_date)

    async def _a_pass(self, text: str, meta: QueryMetadata) -> QueryMetadata:
        # Stub for now — A-pass added in Task 6
        return meta
```

- [ ] **Step 4: Run test, verify PASS.**
```bash
pytest tests/unit/rag/test_query_metadata.py -v
```

- [ ] **Step 5: Commit.**
```bash
git add website/features/rag_pipeline/query/metadata.py tests/unit/rag/test_query_metadata.py
git commit -m "feat: query metadata extractor c-pass"
```

### Task 6: Add A-pass (Gemini entity extraction)

**Files:**
- Modify: `website/features/rag_pipeline/query/metadata.py`
- Test: `tests/unit/rag/test_query_metadata.py`

- [ ] **Step 1: Add failing A-pass test (mocked Gemini).**
```python
# Append to tests/unit/rag/test_query_metadata.py
from unittest.mock import AsyncMock

@pytest.mark.asyncio
async def test_a_pass_populates_entities():
    fake_pool = AsyncMock()
    fake_pool.generate_structured = AsyncMock(return_value={
        "entities": ["LangChain", "vector database"],
        "authors": [],
        "channels": [],
    })
    ext = QueryMetadataExtractor(key_pool=fake_pool)
    meta = await ext.extract("How does LangChain integrate vector databases?", query_class=QueryClass.LOOKUP)
    assert "LangChain" in meta.entities
    assert "vector database" in meta.entities
    assert meta.confidence >= 0.5
```

- [ ] **Step 2: Run, verify FAIL.**

- [ ] **Step 3: Implement A-pass.** Replace the `_a_pass` stub:
```python
import json

_QUERY_ENTITY_PROMPT = """Extract structured metadata from this user query.
Return strict JSON: {"entities": [...], "authors": [...], "channels": [...]}.
- entities: technical concepts, tools, frameworks, named systems (max 5)
- authors: people mentioned (max 3)
- channels: YouTube channels, podcasts, subreddits, newsletters mentioned (max 3)
Query: {query}"""

async def _a_pass(self, text: str, meta: QueryMetadata) -> QueryMetadata:
    try:
        response = await self._key_pool.generate_structured(
            prompt=_QUERY_ENTITY_PROMPT.replace("{query}", text),
            response_schema={"type": "object", "properties": {
                "entities": {"type": "array", "items": {"type": "string"}},
                "authors": {"type": "array", "items": {"type": "string"}},
                "channels": {"type": "array", "items": {"type": "string"}},
            }},
            model_preference="flash-lite",
        )
        if isinstance(response, str):
            response = json.loads(response)
        meta.entities.extend(response.get("entities", []))
        for a in response.get("authors", []):
            if a.lower() not in [x.lower() for x in meta.authors]:
                meta.authors.append(a)
        meta.channels.extend(response.get("channels", []))
        meta.confidence = 0.7
    except Exception:
        # Graceful degradation: keep C-pass result
        pass
    return meta
```

NOTE: `key_pool.generate_structured` is the existing entry point on `GeminiKeyPool`; verify its signature matches by reading `website/features/api_key_switching/__init__.py`. If the actual method name differs (e.g., `generate_with_schema`), use that.

- [ ] **Step 4: Run test, verify PASS.**

- [ ] **Step 5: Commit.**
```bash
git add website/features/rag_pipeline/query/metadata.py tests/unit/rag/test_query_metadata.py
git commit -m "feat: query metadata a-pass gemini entities"
```

### Task 7: Wire `QueryMetadataExtractor` into orchestrator

**Files:**
- Modify: `website/features/rag_pipeline/orchestrator.py`
- Modify: `website/features/rag_pipeline/service.py`

- [ ] **Step 1: Read current `orchestrator.py` `_PreparedQuery` dataclass and `_prepare_query` method.**

- [ ] **Step 2: Add `metadata: QueryMetadata | None` field to `_PreparedQuery`.**

- [ ] **Step 3: In `RAGOrchestrator.__init__`, accept new `metadata_extractor` parameter (default `None` for backward compat in tests).**

- [ ] **Step 4: In `_prepare_query`, after computing `query_class` and `variants`:**
```python
metadata = None
if self._metadata_extractor is not None:
    metadata = await self._metadata_extractor.extract(standalone, query_class=query_class)
return _PreparedQuery(..., metadata=metadata)
```

- [ ] **Step 5: In `service.py` (the orchestrator factory), instantiate `QueryMetadataExtractor` once at startup and pass into `RAGOrchestrator`.**
```python
from website.features.rag_pipeline.query.metadata import QueryMetadataExtractor
from website.features.api_key_switching import get_key_pool
metadata_extractor = QueryMetadataExtractor(key_pool=get_key_pool())
orchestrator = RAGOrchestrator(..., metadata_extractor=metadata_extractor)
```

- [ ] **Step 6: Run existing orchestrator tests.**
```bash
pytest tests/unit/rag/test_orchestrator.py -v
```
Expected: all pass (the extractor is optional, backward-compat preserved).

- [ ] **Step 7: Commit.**
```bash
git add website/features/rag_pipeline/orchestrator.py website/features/rag_pipeline/service.py
git commit -m "feat: wire query metadata extractor into orchestrator"
```

### Task 8: Retrieval-side recency boost

**Files:**
- Modify: `website/features/rag_pipeline/retrieval/hybrid.py`
- Test: `tests/unit/rag/test_recency_boost.py`

- [ ] **Step 1: Write failing test.**
```python
# tests/unit/rag/test_recency_boost.py
from datetime import datetime, timezone, timedelta
from website.features.rag_pipeline.retrieval.hybrid import _recency_boost
from website.features.rag_pipeline.types import QueryClass

def test_lookup_recent_doc_high_boost():
    md = {"timestamp": datetime.now(timezone.utc).isoformat()}
    assert _recency_boost(md, QueryClass.LOOKUP) > 0.09

def test_step_back_old_doc_zero_boost():
    md = {"timestamp": (datetime.now(timezone.utc) - timedelta(days=800)).isoformat()}
    assert _recency_boost(md, QueryClass.STEP_BACK) == 0.0

def test_no_timestamp_zero_boost():
    assert _recency_boost({}, QueryClass.LOOKUP) == 0.0
```

- [ ] **Step 2: Run, verify FAIL.**

- [ ] **Step 3: Implement `_recency_boost` at module level in `hybrid.py`.**
```python
from datetime import datetime, timezone

def _recency_boost(metadata: dict | None, query_class: QueryClass) -> float:
    if not metadata:
        return 0.0
    ts = metadata.get("timestamp") or (metadata.get("time_span") or {}).get("end")
    if not ts:
        return 0.0
    try:
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except Exception:
        return 0.0
    age_days = (datetime.now(timezone.utc) - dt).days
    if age_days < 0:
        return 0.0
    scale = 0.10 if query_class in (QueryClass.LOOKUP, QueryClass.VAGUE) else 0.05
    return scale * max(0.0, 1.0 - age_days / 730.0)
```

- [ ] **Step 4: Run test, verify PASS.**

- [ ] **Step 5: Commit.**
```bash
git add website/features/rag_pipeline/retrieval/hybrid.py tests/unit/rag/test_recency_boost.py
git commit -m "feat: recency boost in hybrid retriever"
```

### Task 9: Source-type and author-match boosts

**Files:**
- Modify: `website/features/rag_pipeline/retrieval/hybrid.py`
- Test: `tests/unit/rag/test_recency_boost.py`

- [ ] **Step 1: Append failing tests.**
```python
from website.features.rag_pipeline.retrieval.hybrid import _source_type_boost, _author_match_boost
from website.features.rag_pipeline.types import RetrievalCandidate, SourceType
from website.features.rag_pipeline.query.metadata import QueryMetadata

def _make_cand(source_type: SourceType, author: str | None = None):
    md = {"author": author} if author else {}
    return RetrievalCandidate(
        node_id="x", chunk_id="x", name="x", content="", source_type=source_type,
        kind=None, semantic_score=0, fulltext_score=0, graph_score=0, rrf_score=0,
        rerank_score=None, final_score=None, metadata=md, tags=[]
    )

def test_thematic_youtube_boost():
    c = _make_cand(SourceType.YOUTUBE)
    assert _source_type_boost(c, QueryClass.THEMATIC) >= 0.03

def test_lookup_reddit_boost():
    c = _make_cand(SourceType.REDDIT)
    assert _source_type_boost(c, QueryClass.LOOKUP) >= 0.02

def test_author_match_substring():
    c = _make_cand(SourceType.YOUTUBE, author="Andrej Karpathy")
    qm = QueryMetadata(authors=["karpathy"])
    assert _author_match_boost(c, qm) == 0.05

def test_no_author_match():
    c = _make_cand(SourceType.YOUTUBE, author="Yann LeCun")
    qm = QueryMetadata(authors=["karpathy"])
    assert _author_match_boost(c, qm) == 0.0
```

(Adapt `_make_cand` if `RetrievalCandidate` constructor has different/required fields — read `website/features/rag_pipeline/types.py` first.)

- [ ] **Step 2: Run, verify FAIL.**

- [ ] **Step 3: Implement.** Append to `hybrid.py`:
```python
def _source_type_boost(candidate: RetrievalCandidate, query_class: QueryClass) -> float:
    st = getattr(candidate.source_type, "value", str(candidate.source_type or "")).lower()
    if query_class in (QueryClass.THEMATIC, QueryClass.STEP_BACK) and st == "youtube":
        return 0.03
    if query_class is QueryClass.LOOKUP and st == "reddit":
        return 0.02
    return 0.0

def _author_match_boost(candidate: RetrievalCandidate, query_meta) -> float:
    if not query_meta or not query_meta.authors:
        return 0.0
    cand_author = (candidate.metadata or {}).get("author") or (candidate.metadata or {}).get("channel")
    if not cand_author:
        return 0.0
    cand_lower = str(cand_author).lower()
    for qa in query_meta.authors:
        if qa.lower() in cand_lower:
            return 0.05
    return 0.0
```

- [ ] **Step 4: Run, verify PASS.**

- [ ] **Step 5: Commit.**
```bash
git add website/features/rag_pipeline/retrieval/hybrid.py tests/unit/rag/test_recency_boost.py
git commit -m "feat: source-type and author-match boosts"
```

### Task 10: Apply boosts in `_dedup_and_fuse`

**Files:**
- Modify: `website/features/rag_pipeline/retrieval/hybrid.py`

- [ ] **Step 1: Locate `_dedup_and_fuse` method, add `query_meta` parameter (default None for backward compat).**

- [ ] **Step 2: Inside the candidate loop, after existing boosts:**
```python
candidate.rrf_score += _recency_boost(candidate.metadata, query_class)
candidate.rrf_score += _source_type_boost(candidate, query_class)
candidate.rrf_score += _author_match_boost(candidate, query_meta)
```

- [ ] **Step 3: Update `retrieve()` to thread `query_meta` to `_dedup_and_fuse`.** Add `query_meta: QueryMetadata | None = None` as a kwarg on `retrieve()`.

- [ ] **Step 4: Update orchestrator call site** in `_retrieve_context` (or equivalent) to pass `prepared.metadata` as `query_meta`.

- [ ] **Step 5: Run existing hybrid retriever tests + new boost tests.**
```bash
pytest tests/unit/rag/ tests/unit/rag_pipeline/ -q
```

- [ ] **Step 6: Commit.**
```bash
git add website/features/rag_pipeline/retrieval/hybrid.py website/features/rag_pipeline/orchestrator.py
git commit -m "feat: thread query metadata through dedup and fuse"
```

### Task 11: Ingest-side metadata enricher

**Files:**
- Create: `website/features/rag_pipeline/ingest/metadata_enricher.py`
- Test: `tests/unit/rag/test_metadata_enricher.py`

- [ ] **Step 1: Write failing test.**
```python
# tests/unit/rag/test_metadata_enricher.py
import pytest
from unittest.mock import AsyncMock
from website.features.rag_pipeline.ingest.metadata_enricher import MetadataEnricher

@pytest.mark.asyncio
async def test_enrich_extracts_domain_and_time():
    enricher = MetadataEnricher(key_pool=None)  # disable Gemini for this test
    out = await enricher.enrich_chunks([
        {"id": "c1", "content": "Posted on October 12, 2023 at karpathy.com about transformers"},
    ])
    md = out[0]["metadata"]
    assert "karpathy.com" in md.get("domains", [])
    assert md.get("time_span", {}).get("end") is not None
```

- [ ] **Step 2: Implement.**
```python
# website/features/rag_pipeline/ingest/metadata_enricher.py
from __future__ import annotations
import re
import dateparser
import tldextract
import json

class MetadataEnricher:
    def __init__(self, *, key_pool):
        self._key_pool = key_pool

    async def enrich_chunks(self, chunks: list[dict]) -> list[dict]:
        enriched = []
        # Cheap deterministic pass first
        for chunk in chunks:
            md = chunk.get("metadata") or {}
            content = chunk.get("content", "")
            md["domains"] = sorted({
                f"{tldextract.extract(t).domain}.{tldextract.extract(t).suffix}"
                for t in re.findall(r"\b[\w\-]+\.[a-z]{2,}\b", content.lower())
                if tldextract.extract(t).suffix
            })
            parsed = dateparser.parse(content[:500])  # head only — body dates are noisy
            if parsed:
                md["time_span"] = {"end": parsed.isoformat()}
            chunk["metadata"] = md
            enriched.append(chunk)
        # A-pass: batched Gemini entity extraction (5 chunks/call)
        if self._key_pool:
            for batch_start in range(0, len(enriched), 5):
                batch = enriched[batch_start:batch_start+5]
                try:
                    results = await self._extract_entities_batch(batch)
                    for chunk, ent in zip(batch, results):
                        chunk["metadata"]["entities"] = ent
                except Exception:
                    continue  # graceful skip — domain/time still applied
        return enriched

    async def _extract_entities_batch(self, batch: list[dict]) -> list[list[str]]:
        prompt = "Extract top-5 named entities (people, orgs, technical concepts) from each numbered chunk.\nReturn JSON: {\"results\": [[\"e1\",\"e2\"], ...]}.\n\n"
        for i, c in enumerate(batch):
            prompt += f"### Chunk {i+1}\n{c['content'][:1500]}\n\n"
        response = await self._key_pool.generate_structured(
            prompt=prompt,
            response_schema={"type": "object", "properties": {
                "results": {"type": "array", "items": {"type": "array", "items": {"type": "string"}}}
            }},
            model_preference="flash-lite",
        )
        if isinstance(response, str):
            response = json.loads(response)
        return response.get("results", [[] for _ in batch])
```

- [ ] **Step 3: Run, verify PASS.**
```bash
pytest tests/unit/rag/test_metadata_enricher.py -v
```

- [ ] **Step 4: Commit.**
```bash
git add website/features/rag_pipeline/ingest/metadata_enricher.py tests/unit/rag/test_metadata_enricher.py
git commit -m "feat: ingest metadata enricher"
```

### Task 12: Backfill script + schema column

**Files:**
- Create: `supabase/website/kg_public/migrations/2026-04-26_chunk_metadata_enriched_at.sql`
- Create: `ops/scripts/backfill_metadata.py`

- [ ] **Step 1: Write SQL migration.**
```sql
-- supabase/website/kg_public/migrations/2026-04-26_chunk_metadata_enriched_at.sql
ALTER TABLE kg_node_chunks
  ADD COLUMN IF NOT EXISTS metadata_enriched_at timestamptz;
CREATE INDEX IF NOT EXISTS idx_kg_node_chunks_meta_enriched
  ON kg_node_chunks (metadata_enriched_at NULLS FIRST);
```

- [ ] **Step 2: Apply migration to staging Supabase.**
```bash
psql $SUPABASE_DB_URL -f supabase/website/kg_public/migrations/2026-04-26_chunk_metadata_enriched_at.sql
```

- [ ] **Step 3: Write backfill script.**
```python
# ops/scripts/backfill_metadata.py
"""Auto-backfill kg_node_chunks.metadata for chunks where metadata_enriched_at IS NULL.

Run: python ops/scripts/backfill_metadata.py [--dry-run] [--batch-size 5]
Idempotent: skips chunks already enriched.
"""
from __future__ import annotations
import argparse, asyncio, sys
from website.core.supabase_kg.client import get_supabase_client
from website.features.api_key_switching import get_key_pool
from website.features.rag_pipeline.ingest.metadata_enricher import MetadataEnricher

async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--batch-size", type=int, default=5)
    args = parser.parse_args()

    sb = get_supabase_client()
    key_pool = get_key_pool()
    enricher = MetadataEnricher(key_pool=key_pool)

    page = 0
    PAGE_SIZE = 50
    total_done = 0
    while True:
        rows = sb.table("kg_node_chunks").select("id,content,metadata") \
            .is_("metadata_enriched_at", None).range(page*PAGE_SIZE, (page+1)*PAGE_SIZE - 1).execute()
        chunks = rows.data or []
        if not chunks:
            break
        if args.dry_run:
            print(f"DRY: would enrich {len(chunks)} chunks (page {page})")
            page += 1
            continue
        enriched = await enricher.enrich_chunks(chunks)
        for chunk in enriched:
            sb.table("kg_node_chunks").update({
                "metadata": chunk["metadata"],
                "metadata_enriched_at": "now()",
            }).eq("id", chunk["id"]).execute()
        total_done += len(enriched)
        page += 1
        # Circuit breaker on billing-key burn (read pool stats if available)
        # Simple: bail if any single batch errors >50%
    print(f"Backfill complete: {total_done} chunks")

if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 4: Smoke-run with `--dry-run` against staging.**
```bash
python ops/scripts/backfill_metadata.py --dry-run
```
Expected: prints planned counts, exits 0.

- [ ] **Step 5: Commit.**
```bash
git add supabase/website/kg_public/migrations/2026-04-26_chunk_metadata_enriched_at.sql ops/scripts/backfill_metadata.py
git commit -m "feat: chunk metadata backfill script + schema"
```

### Task 13: Wire backfill into deploy hook

**Files:**
- Modify: `ops/Dockerfile` OR `ops/deploy/deploy.sh` (verify which exists; the deploy script is canonical per CLAUDE.md)

- [ ] **Step 1: Locate the deploy script** referenced in CLAUDE.md (`/opt/zettelkasten/deploy/deploy.sh`). Find a corresponding repo file.

- [ ] **Step 2: Add post-cutover hook.** After the "color is green and traffic switched" step:
```bash
# ops/deploy/deploy.sh — append after cutover
echo "Running metadata backfill (idempotent)..."
docker compose -f docker-compose.${ACTIVE_COLOR}.yml exec -T app \
  python ops/scripts/backfill_metadata.py || echo "WARN: backfill failed but cutover succeeded"
```

- [ ] **Step 3: Commit.**
```bash
git add ops/deploy/deploy.sh
git commit -m "ops: post-cutover metadata backfill hook"
```

---

## Phase 2 — Cross-encoder structured header

### Task 14: Enrich `_passage_text` with metadata header

**Files:**
- Modify: `website/features/rag_pipeline/rerank/cascade.py`
- Test: `tests/unit/rag/test_passage_text.py`

- [ ] **Step 1: Write failing test.**
```python
# tests/unit/rag/test_passage_text.py
from website.features.rag_pipeline.rerank.cascade import _passage_text
from website.features.rag_pipeline.types import RetrievalCandidate, SourceType

def _make(source, author, ts, tags, name, content):
    return RetrievalCandidate(
        node_id="n", chunk_id="c", name=name, content=content,
        source_type=source, kind=None,
        semantic_score=0, fulltext_score=0, graph_score=0, rrf_score=0,
        rerank_score=None, final_score=None,
        metadata={"author": author, "timestamp": ts}, tags=tags,
    )

def test_header_includes_source_author_date_tags():
    c = _make(SourceType.YOUTUBE, "Andrej Karpathy", "2023-10-12", ["transformers", "vision"], "AKL Talk", "Body content here.")
    text = _passage_text(c)
    first_line = text.split("\n")[0]
    assert first_line.startswith("[")
    assert "source=youtube" in first_line
    assert "author=Andrej Karpathy" in first_line
    assert "date=2023-10-12" in first_line
    assert "tags=transformers,vision" in first_line

def test_header_present_with_minimal_metadata():
    c = _make(SourceType.WEB, None, None, [], "Page", "x")
    text = _passage_text(c)
    assert text.split("\n")[0].startswith("[source=web")
```

- [ ] **Step 2: Run, verify FAIL.**

- [ ] **Step 3: Locate and rewrite `_passage_text` in `cascade.py`.**
```python
def _passage_text(candidate: RetrievalCandidate) -> str:
    content = (candidate.content or "")[:4000]
    name = (candidate.name or "").strip()
    parts: list[str] = []

    meta_pieces: list[str] = []
    src = getattr(candidate.source_type, "value", str(candidate.source_type or "unknown"))
    meta_pieces.append(f"source={src}")
    md = candidate.metadata or {}
    author = md.get("author") or md.get("channel")
    if author:
        meta_pieces.append(f"author={author}")
    ts = md.get("timestamp") or (md.get("time_span") or {}).get("end")
    if ts:
        meta_pieces.append(f"date={str(ts)[:10]}")
    if candidate.tags:
        meta_pieces.append("tags=" + ",".join(candidate.tags[:5]))
    parts.append("[" + "; ".join(meta_pieces) + "]")

    if name:
        head = content.lstrip()[:120].lower()
        if name.lower() not in head:
            parts.append(name)
    parts.append(content)
    return "\n\n".join(parts)
```

- [ ] **Step 4: Run, verify PASS. Run full unit suite to confirm no regression.**
```bash
pytest tests/unit/rag/ tests/unit/rag_pipeline/ -q
```

- [ ] **Step 5: Commit.**
```bash
git add website/features/rag_pipeline/rerank/cascade.py tests/unit/rag/test_passage_text.py
git commit -m "feat: structured metadata header in cascade reranker"
```

---

## Phase 3 — Context distillation

### Task 15: `EvidenceCompressor` with bi-encoder cascade

**Files:**
- Create: `website/features/rag_pipeline/context/distiller.py`
- Test: `tests/unit/rag/test_evidence_compressor.py`

- [ ] **Step 1: Write failing test (bi-encoder happy path).**
```python
# tests/unit/rag/test_evidence_compressor.py
import pytest
import numpy as np
from unittest.mock import AsyncMock
from website.features.rag_pipeline.context.distiller import EvidenceCompressor
from website.features.rag_pipeline.types import RetrievalCandidate, SourceType

def _cand(content):
    return RetrievalCandidate(
        node_id="n", chunk_id="c", name="N", content=content, source_type=SourceType.WEB,
        kind=None, semantic_score=0, fulltext_score=0, graph_score=0, rrf_score=0,
        rerank_score=None, final_score=None, metadata={}, tags=[],
    )

@pytest.mark.asyncio
async def test_keeps_top_k_relevant_sentences():
    fake_embedder = AsyncMock()
    fake_embedder.embed_query_with_cache = AsyncMock(return_value=[1.0, 0.0])
    fake_embedder.embed_texts = AsyncMock(return_value=[
        [1.0, 0.0],   # very relevant
        [0.0, 1.0],   # irrelevant
        [0.9, 0.1],   # relevant
    ])
    comp = EvidenceCompressor(embedder=fake_embedder, cross_encoder=None)
    cands = [_cand("Sentence one. Sentence two. Sentence three.")]
    out = await comp.compress(user_query="q", grouped=[cands], target_budget_tokens=1000)
    body = out[0][0].content
    assert "Sentence one" in body
    assert "Sentence three" in body
    assert "Sentence two" not in body
```

- [ ] **Step 2: Run, verify FAIL.**

- [ ] **Step 3: Implement.**
```python
# website/features/rag_pipeline/context/distiller.py
from __future__ import annotations
import re
import numpy as np
from website.features.rag_pipeline.types import RetrievalCandidate

_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")
_TOP_K = 5
_SCAFFOLD_NEIGHBOURS = 1
_LOW_CONFIDENCE_FLOOR = 0.55
_TIE_CLUSTER_DELTA = 0.05


class EvidenceCompressor:
    def __init__(self, *, embedder, cross_encoder=None):
        self._embedder = embedder
        self._ce = cross_encoder  # may be None; cross-encoder is optional fallback

    async def compress(
        self,
        *,
        user_query: str,
        grouped: list[list[RetrievalCandidate]],
        target_budget_tokens: int,
    ) -> list[list[RetrievalCandidate]]:
        if not grouped:
            return grouped
        q_vec = await self._embedder.embed_query_with_cache(user_query)
        q_arr = np.array(q_vec, dtype=np.float32)
        q_norm = q_arr / (np.linalg.norm(q_arr) + 1e-9)
        out: list[list[RetrievalCandidate]] = []
        for group in grouped:
            new_group = []
            for cand in group:
                body = cand.content or ""
                sentences = [s.strip() for s in _SENTENCE_RE.split(body) if s.strip()]
                if len(sentences) <= _TOP_K:
                    new_group.append(cand)
                    continue
                vecs = await self._embedder.embed_texts(sentences)
                arr = np.array(vecs, dtype=np.float32)
                arr_n = arr / (np.linalg.norm(arr, axis=1, keepdims=True) + 1e-9)
                cosines = (arr_n @ q_norm).tolist()
                ranked = sorted(enumerate(cosines), key=lambda x: x[1], reverse=True)
                top3_scores = [s for _, s in ranked[:3]]
                escalate = (
                    all(s < _LOW_CONFIDENCE_FLOOR for s in top3_scores)
                    or (max(top3_scores) - min(top3_scores) <= _TIE_CLUSTER_DELTA and len(top3_scores) >= 3)
                )
                if escalate and self._ce is not None:
                    cosines = await self._ce.score_pairs(user_query, sentences)
                    ranked = sorted(enumerate(cosines), key=lambda x: x[1], reverse=True)
                top_idx = sorted({i for i, _ in ranked[:_TOP_K]})
                # Add scaffold neighbours
                kept = set(top_idx)
                for i in top_idx:
                    for j in range(max(0, i-_SCAFFOLD_NEIGHBOURS), min(len(sentences), i+_SCAFFOLD_NEIGHBOURS+1)):
                        kept.add(j)
                kept_sorted = sorted(kept)
                cand_copy = RetrievalCandidate(**{**cand.__dict__, "content": " ".join(sentences[k] for k in kept_sorted)})
                new_group.append(cand_copy)
            out.append(new_group)
        return out
```

- [ ] **Step 4: Run, verify PASS.**

- [ ] **Step 5: Add cross-encoder escalation test.**
```python
@pytest.mark.asyncio
async def test_low_confidence_triggers_cross_encoder():
    fake_embedder = AsyncMock()
    fake_embedder.embed_query_with_cache = AsyncMock(return_value=[1.0, 0.0])
    # All cosines below 0.55 → escalate
    fake_embedder.embed_texts = AsyncMock(return_value=[[0.5, 0.5]] * 4)
    fake_ce = AsyncMock()
    fake_ce.score_pairs = AsyncMock(return_value=[0.9, 0.1, 0.5, 0.3])
    comp = EvidenceCompressor(embedder=fake_embedder, cross_encoder=fake_ce)
    cands = [_cand("A. B. C. D.")]
    await comp.compress(user_query="q", grouped=[cands], target_budget_tokens=1000)
    fake_ce.score_pairs.assert_awaited_once()
```

- [ ] **Step 6: Run, verify PASS.**

- [ ] **Step 7: Commit.**
```bash
git add website/features/rag_pipeline/context/distiller.py tests/unit/rag/test_evidence_compressor.py
git commit -m "feat: evidence compressor with cross-encoder cascade"
```

### Task 16: Wire compressor into `ContextAssembler`

**Files:**
- Modify: `website/features/rag_pipeline/context/assembler.py`
- Modify: `website/features/rag_pipeline/service.py`

- [ ] **Step 1: In `ContextAssembler.build`, after grouping but before `_fit_within_budget`:**
```python
if self._compressor is not None:
    grouped = await self._compressor.compress(
        user_query=user_query, grouped=grouped, target_budget_tokens=budget,
    )
```
Place this immediately before the existing `_fit_within_budget` call so compressed content drives token packing.

- [ ] **Step 2: In `service.py`, instantiate `EvidenceCompressor` and pass to `ContextAssembler`.**
```python
from website.features.rag_pipeline.context.distiller import EvidenceCompressor
compressor = EvidenceCompressor(embedder=embedder, cross_encoder=reranker)  # reranker exposes BGE-CE scoring
assembler = ContextAssembler(compressor=compressor)
```
NOTE: verify the reranker exposes a `score_pairs(query, passages) -> list[float]` API. If not, expose a thin method on `CascadeReranker` that wraps the BGE-CE ONNX session for sentence-pair scoring (separate sub-step before this one).

- [ ] **Step 3: Run integration smoke.**
```bash
pytest tests/unit/rag_pipeline/ -q
```

- [ ] **Step 4: Commit.**
```bash
git add website/features/rag_pipeline/context/assembler.py website/features/rag_pipeline/service.py
git commit -m "feat: wire evidence compressor into context assembler"
```

### Task 17: Per-LLM-tier dynamic budget

**Files:**
- Modify: `website/features/rag_pipeline/context/assembler.py`
- Modify: `website/features/rag_pipeline/orchestrator.py`

- [ ] **Step 1: Replace `_BUDGET_BY_QUALITY` with a layered lookup at module top of `assembler.py`.**
```python
_BUDGET_BY_QUALITY = {"fast": 6000, "high": 12000}
_BUDGET_BY_LLM_TIER = {
    "gemini-2.5-flash":      6000,
    "gemini-2.5-flash-lite": 4000,
    "gemini-2.5-pro":        8000,
}
```

- [ ] **Step 2: Update `build()` signature to accept optional `model: str | None = None`.**
```python
async def build(self, *, candidates, quality="fast", user_query, model=None):
    budget = _BUDGET_BY_LLM_TIER.get(model) if model else None
    if budget is None:
        budget = _BUDGET_BY_QUALITY[quality]
    ...
```

- [ ] **Step 3: In orchestrator, pass the chosen model into the assembler call.**
```python
context_xml, used = await self._assembler.build(
    candidates=reranked, quality=quality, user_query=standalone, model=chosen_model,
)
```

- [ ] **Step 4: Run unit suite.**

- [ ] **Step 5: Commit.**
```bash
git add website/features/rag_pipeline/context/assembler.py website/features/rag_pipeline/orchestrator.py
git commit -m "feat: per-llm-tier context budget"
```

---

## Phase 4 — KG-RAG coupling

### Task 18: `expand_subgraph` on `kg_features/retrieval.py`

**Files:**
- Modify: `website/features/kg_features/retrieval.py`
- Test: `tests/unit/kg_features/test_expand_subgraph.py`

- [ ] **Step 1: Read `kg_features/retrieval.py` fully to confirm `expand_subgraph` is absent.** If it already exists with matching semantics, skip to Task 19.

- [ ] **Step 2: Write failing test using fake Supabase client.**
```python
# tests/unit/kg_features/test_expand_subgraph.py
from unittest.mock import MagicMock
from website.features.kg_features.retrieval import expand_subgraph

def test_expand_returns_neighbours_within_depth():
    sb = MagicMock()
    sb.rpc.return_value.execute.return_value.data = [
        {"id": "n1"}, {"id": "n2"}, {"id": "n3"}
    ]
    result = expand_subgraph(sb, user_id="u", node_ids=["n0"], depth=1)
    assert set(result) == {"n1", "n2", "n3"}
    sb.rpc.assert_called_once()
```

- [ ] **Step 3: Implement (Supabase recursive-CTE wrapped in an RPC).** First add the SQL:
```sql
-- supabase/website/kg_public/migrations/2026-04-26_expand_subgraph.sql
CREATE OR REPLACE FUNCTION kg_expand_subgraph(
  p_user_id uuid, p_node_ids text[], p_depth int DEFAULT 1
) RETURNS TABLE(id text) LANGUAGE sql SECURITY DEFINER AS $$
WITH RECURSIVE walk AS (
  SELECT unnest(p_node_ids) AS id, 0 AS d
  UNION ALL
  SELECT l.target_node_id, w.d+1
  FROM kg_links l JOIN walk w ON l.source_node_id = w.id
  WHERE w.d < p_depth AND l.user_id = p_user_id
  UNION ALL
  SELECT l.source_node_id, w.d+1
  FROM kg_links l JOIN walk w ON l.target_node_id = w.id
  WHERE w.d < p_depth AND l.user_id = p_user_id
)
SELECT DISTINCT id FROM walk WHERE id <> ALL(p_node_ids);
$$;
```
Apply: `psql $SUPABASE_DB_URL -f ...`

- [ ] **Step 4: Add Python wrapper in `retrieval.py`:**
```python
def expand_subgraph(supabase_client, *, user_id: str, node_ids: list[str], depth: int = 1) -> list[str]:
    if not node_ids:
        return []
    res = supabase_client.rpc("kg_expand_subgraph", {
        "p_user_id": str(user_id), "p_node_ids": node_ids, "p_depth": depth,
    }).execute()
    return [row["id"] for row in (res.data or [])]
```

- [ ] **Step 5: Run, verify PASS.**

- [ ] **Step 6: Commit.**
```bash
git add supabase/website/kg_public/migrations/2026-04-26_expand_subgraph.sql website/features/kg_features/retrieval.py tests/unit/kg_features/test_expand_subgraph.py
git commit -m "feat: kg expand subgraph rpc"
```

### Task 19: `RetrievalPlanner` adapter

**Files:**
- Create: `website/features/rag_pipeline/retrieval/planner.py`
- Test: `tests/unit/rag/test_retrieval_planner.py`

- [ ] **Step 1: Write failing test.**
```python
# tests/unit/rag/test_retrieval_planner.py
import pytest
from unittest.mock import MagicMock, AsyncMock
from website.features.rag_pipeline.retrieval.planner import RetrievalPlanner
from website.features.rag_pipeline.query.metadata import QueryMetadata
from website.features.rag_pipeline.types import QueryClass, ScopeFilter

@pytest.mark.asyncio
async def test_lookup_with_entities_narrows_scope():
    fake_kg = MagicMock()
    fake_kg.expand_subgraph = MagicMock(return_value=["n1","n2","n3"])
    fake_kg.hybrid_search = MagicMock(return_value=[
        MagicMock(id="seed1"), MagicMock(id="seed2"),
    ])
    planner = RetrievalPlanner(kg_module=fake_kg)
    qm = QueryMetadata(entities=["transformer"])
    sf = ScopeFilter()
    out = await planner.plan(user_id="u", query_meta=qm, query_class=QueryClass.LOOKUP, scope_filter=sf)
    assert set(out.node_ids) >= {"n1","n2","n3"}

@pytest.mark.asyncio
async def test_thematic_no_change():
    fake_kg = MagicMock()
    planner = RetrievalPlanner(kg_module=fake_kg)
    qm = QueryMetadata(entities=["x"])
    sf = ScopeFilter()
    out = await planner.plan(user_id="u", query_meta=qm, query_class=QueryClass.THEMATIC, scope_filter=sf)
    assert out.node_ids is None or out.node_ids == sf.node_ids
```

- [ ] **Step 2: Implement.**
```python
# website/features/rag_pipeline/retrieval/planner.py
from __future__ import annotations
from website.features.rag_pipeline.query.metadata import QueryMetadata
from website.features.rag_pipeline.types import QueryClass, ScopeFilter

class RetrievalPlanner:
    def __init__(self, *, kg_module):
        self._kg = kg_module

    async def plan(self, *, user_id: str, query_meta: QueryMetadata, query_class: QueryClass, scope_filter: ScopeFilter) -> ScopeFilter:
        if query_class not in (QueryClass.LOOKUP, QueryClass.MULTI_HOP):
            return scope_filter
        if not query_meta or not query_meta.entities:
            return scope_filter
        # Resolve entities to node ids (best-effort name match) — use existing kg_features hybrid_search
        seed_ids = []
        for entity in query_meta.entities:
            try:
                hits = self._kg.hybrid_search(self._kg._supabase if hasattr(self._kg, "_supabase") else None,
                                              user_id=self._user_id, query=entity, limit=3)
                seed_ids.extend([h.id for h in hits])
            except Exception:
                continue
        if not seed_ids:
            return scope_filter
        try:
            expanded = self._kg.expand_subgraph(
                self._kg._supabase if hasattr(self._kg, "_supabase") else None,
                user_id=user_id, node_ids=seed_ids, depth=1,
            )
        except Exception:
            return scope_filter
        if not expanded:
            return scope_filter
        new_node_ids = list(set(expanded) | set(seed_ids))
        if scope_filter.node_ids:
            new_node_ids = list(set(new_node_ids) & set(scope_filter.node_ids))
            if not new_node_ids:
                return scope_filter  # don't narrow to empty — fall back
        return scope_filter.model_copy(update={"node_ids": new_node_ids})
```

- [ ] **Step 3: Run, verify PASS.** Adapt test mocking to actual `kg_module` signature observed in Task 18.

- [ ] **Step 4: Commit.**
```bash
git add website/features/rag_pipeline/retrieval/planner.py tests/unit/rag/test_retrieval_planner.py
git commit -m "feat: retrieval planner kg-first adapter"
```

### Task 20: Wire `RetrievalPlanner` into orchestrator

**Files:**
- Modify: `website/features/rag_pipeline/orchestrator.py`
- Modify: `website/features/rag_pipeline/service.py`

- [ ] **Step 1: Add `RAG_KG_FIRST_ENABLED` env flag check to orchestrator.**
```python
import os
_KG_FIRST_ENABLED = os.environ.get("RAG_KG_FIRST_ENABLED", "true").lower() == "true"
```

- [ ] **Step 2: In orchestrator, pass `planner` via __init__ (default None for backward compat).**

- [ ] **Step 3: In `_retrieve_context` (or wherever the scope_filter is built), before calling `self._retriever.retrieve(...)`:**
```python
if _KG_FIRST_ENABLED and self._planner is not None and prepared.metadata is not None:
    scope_filter = await self._planner.plan(
        query_meta=prepared.metadata,
        query_class=prepared.query_class,
        scope_filter=scope_filter,
    )
```

- [ ] **Step 4: In `service.py`, instantiate planner and pass to orchestrator.**
```python
from website.features.rag_pipeline.retrieval.planner import RetrievalPlanner
from website.features.kg_features import retrieval as kg_retrieval
planner = RetrievalPlanner(kg_module=kg_retrieval)
orchestrator = RAGOrchestrator(..., planner=planner)
```
The planner accepts `user_id` per call (in `plan()`); it is not stored at construction.

- [ ] **Step 5: In orchestrator `_retrieve_context` (or wherever scope_filter is built), pass user_id to plan():**
```python
scope_filter = await self._planner.plan(
    user_id=user_id, query_meta=prepared.metadata,
    query_class=prepared.query_class, scope_filter=scope_filter,
)
```

- [ ] **Step 6: Run unit suite.**

- [ ] **Step 7: Commit.**
```bash
git add website/features/rag_pipeline/orchestrator.py website/features/rag_pipeline/service.py website/features/rag_pipeline/retrieval/planner.py tests/unit/rag/test_retrieval_planner.py
git commit -m "feat: wire retrieval planner into orchestrator"
```

### Task 21: `kg_usage_edges` schema migration

**Files:**
- Create: `supabase/website/kg_public/migrations/2026-04-26_kg_usage_edges.sql`

- [ ] **Step 1: Write the migration.**
```sql
-- supabase/website/kg_public/migrations/2026-04-26_kg_usage_edges.sql
CREATE TABLE IF NOT EXISTS kg_usage_edges (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  source_node_id text NOT NULL,
  target_node_id text NOT NULL,
  query_class text NOT NULL,
  verdict text NOT NULL CHECK (verdict IN ('supported','retried_supported')),
  delta float NOT NULL DEFAULT 1.0,
  created_at timestamptz DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_kg_usage_edges_user_target ON kg_usage_edges (user_id, target_node_id);
CREATE INDEX IF NOT EXISTS idx_kg_usage_edges_class ON kg_usage_edges (query_class);

ALTER TABLE kg_usage_edges ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "user_owns_usage_edge_select" ON kg_usage_edges;
CREATE POLICY "user_owns_usage_edge_select" ON kg_usage_edges
  FOR SELECT USING (user_id = auth.uid());
DROP POLICY IF EXISTS "user_owns_usage_edge_insert" ON kg_usage_edges;
CREATE POLICY "user_owns_usage_edge_insert" ON kg_usage_edges
  FOR INSERT WITH CHECK (user_id = auth.uid());

CREATE MATERIALIZED VIEW IF NOT EXISTS kg_usage_edges_agg AS
  SELECT user_id, source_node_id, target_node_id, query_class,
         SUM(delta * exp(-EXTRACT(epoch FROM (now()-created_at))/2592000.0)) AS weight
  FROM kg_usage_edges
  GROUP BY user_id, source_node_id, target_node_id, query_class;
CREATE UNIQUE INDEX IF NOT EXISTS uq_usage_edges_agg
  ON kg_usage_edges_agg (user_id, source_node_id, target_node_id, query_class);

CREATE TABLE IF NOT EXISTS recompute_runs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  ran_at timestamptz DEFAULT now(),
  job_name text NOT NULL,
  rows_inserted int DEFAULT 0,
  rows_aggregated int DEFAULT 0,
  status text NOT NULL,
  error_message text
);
```

- [ ] **Step 2: Apply migration to staging.**
```bash
psql $SUPABASE_DB_URL -f supabase/website/kg_public/migrations/2026-04-26_kg_usage_edges.sql
```
Verify: `\d kg_usage_edges` shows the table; `SELECT * FROM kg_usage_edges_agg LIMIT 1;` returns 0 rows but no error.

- [ ] **Step 3: Commit.**
```bash
git add supabase/website/kg_public/migrations/2026-04-26_kg_usage_edges.sql
git commit -m "feat: kg usage edges schema and aggregate view"
```

### Task 22: `recompute_usage_edges.py` script

**Files:**
- Create: `ops/scripts/recompute_usage_edges.py`
- Test: `tests/integration_tests/test_kg_usage_edges.py`

- [ ] **Step 1: Write the script.**
```python
# ops/scripts/recompute_usage_edges.py
"""Nightly recompute of kg_usage_edges from supported QA turns.

Reads chat_messages + rag_turns from last 24h, computes per-edge deltas,
upserts kg_usage_edges, refreshes kg_usage_edges_agg MV, writes audit row.

Run: python ops/scripts/recompute_usage_edges.py
"""
from __future__ import annotations
import os, sys, traceback
from datetime import datetime, timedelta, timezone
from supabase import create_client

VERDICT_DELTA = {"supported": 1.0, "retried_supported": 0.5}

def main() -> int:
    url = os.environ["SUPABASE_URL"]
    key = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
    sb = create_client(url, key)
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()

    rows_inserted = 0
    error_msg = None
    try:
        # rag_turns shape assumption: id, user_id, query_class, verdict, retrieved_node_ids[], query_entities[], created_at
        turns = sb.table("rag_turns") \
            .select("user_id, query_class, verdict, retrieved_node_ids, query_entities, created_at") \
            .gte("created_at", cutoff) \
            .in_("verdict", list(VERDICT_DELTA.keys())) \
            .execute().data or []

        rows = []
        for t in turns:
            delta = VERDICT_DELTA[t["verdict"]]
            entities = t.get("query_entities") or []
            nodes = t.get("retrieved_node_ids") or []
            # If we don't have entity-level mapping, derive a global "any-entity" usage
            # by recording self-edges (node→node within the same retrieved set) — this
            # captures co-cited node clusters even without entity ids.
            for src in (entities or [None]):
                for tgt in nodes:
                    rows.append({
                        "user_id": t["user_id"],
                        "source_node_id": src or tgt,  # fall back to self-edge
                        "target_node_id": tgt,
                        "query_class": t["query_class"],
                        "verdict": t["verdict"],
                        "delta": delta,
                    })

        if rows:
            sb.table("kg_usage_edges").insert(rows).execute()
            rows_inserted = len(rows)

        # Refresh MV
        sb.rpc("kg_refresh_usage_edges_agg").execute()
        status = "ok"
    except Exception as exc:
        status = "error"
        error_msg = f"{exc}\n{traceback.format_exc()}"
        print(error_msg, file=sys.stderr)

    sb.table("recompute_runs").insert({
        "job_name": "recompute_usage_edges",
        "rows_inserted": rows_inserted,
        "status": status,
        "error_message": error_msg,
    }).execute()

    return 0 if status == "ok" else 1

if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Add the refresh RPC** in the same migration file as Task 21 (append):
```sql
CREATE OR REPLACE FUNCTION kg_refresh_usage_edges_agg() RETURNS void
LANGUAGE sql SECURITY DEFINER AS $$
  REFRESH MATERIALIZED VIEW CONCURRENTLY kg_usage_edges_agg;
$$;
```
Apply with `psql -f`.

- [ ] **Step 3: Smoke-run locally with staging Supabase.**
```bash
SUPABASE_URL=... SUPABASE_SERVICE_ROLE_KEY=... python ops/scripts/recompute_usage_edges.py
```
Expected: exit 0; one row in `recompute_runs`.

- [ ] **Step 4: Commit.**
```bash
git add ops/scripts/recompute_usage_edges.py supabase/website/kg_public/migrations/2026-04-26_kg_usage_edges.sql
git commit -m "feat: nightly recompute usage edges script"
```

### Task 23: GitHub Actions cron workflow

**Files:**
- Create: `.github/workflows/recompute_usage_edges.yml`

- [ ] **Step 1: Write the workflow.**
```yaml
name: Recompute KG Usage Edges
on:
  schedule:
    - cron: '0 2 * * *'  # 2am UTC nightly
  workflow_dispatch:

jobs:
  recompute:
    runs-on: ubuntu-latest
    timeout-minutes: 10
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install -r ops/requirements.txt
      - name: Run recompute
        env:
          SUPABASE_URL: ${{ secrets.SUPABASE_URL }}
          SUPABASE_SERVICE_ROLE_KEY: ${{ secrets.SUPABASE_SERVICE_ROLE_KEY }}
        run: python ops/scripts/recompute_usage_edges.py
```

- [ ] **Step 2: Verify GH secrets `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY` exist.**
```bash
gh secret list
```
Expected: both present. If not, add them: `gh secret set SUPABASE_URL`.

- [ ] **Step 3: Commit.**
```bash
git add .github/workflows/recompute_usage_edges.yml
git commit -m "ci: nightly cron for kg usage edges recompute"
```

### Task 24: Read usage-edge weights in `graph_score.py`

**Files:**
- Modify: `website/features/rag_pipeline/retrieval/graph_score.py`

- [ ] **Step 1: Read current `graph_score.py` to understand the existing scoring function signature.**

- [ ] **Step 2: Add an env-flag-gated bonus.**
```python
import os, math
_USAGE_EDGES_ENABLED = os.environ.get("RAG_USAGE_EDGES_ENABLED", "true").lower() == "true"

def _usage_weight_bonus(supabase, *, user_id, target_node_id, query_class) -> float:
    if not _USAGE_EDGES_ENABLED:
        return 0.0
    try:
        res = supabase.table("kg_usage_edges_agg") \
            .select("weight") \
            .eq("user_id", str(user_id)) \
            .eq("target_node_id", target_node_id) \
            .eq("query_class", query_class.value if hasattr(query_class, "value") else query_class) \
            .execute()
        weight = sum(r["weight"] for r in (res.data or []))
        # Sigmoid-bounded bonus 0..0.10
        return 0.10 / (1.0 + math.exp(-weight / 5.0)) - 0.05
    except Exception:
        return 0.0
```

- [ ] **Step 3: Add the bonus to existing graph_score computation** at the appropriate point (verify by reading the existing scorer).

- [ ] **Step 4: Run unit tests.**
```bash
pytest tests/unit/rag/ -q
```

- [ ] **Step 5: Commit.**
```bash
git add website/features/rag_pipeline/retrieval/graph_score.py
git commit -m "feat: usage edge bonus in graph score"
```

---

## iter-01 Verification

### Task 25: Pre-deploy test sweep

**Files:** none (verification only)

- [ ] **Step 1: Run full unit suite.**
```bash
pytest tests/unit/ -q
```
Expected: all pass.

- [ ] **Step 2: Run integration suite (non-live).**
```bash
pytest tests/integration_tests/ -q -m 'not live'
```
Expected: all pass.

- [ ] **Step 3: Run live integration tests against staging.**
```bash
pytest tests/integration_tests/test_rag_sandbox_rpc.py --live -v
```
Expected: PASS (Task 2 fix verified).

- [ ] **Step 4: Push to master.**
```bash
git push origin master
```

### Task 26: Deploy + wait for prod cutover

**Files:** none

- [ ] **Step 1: Watch the deploy workflow.**
```bash
gh run list --branch master --limit 1 --json databaseId,name --jq '.[0].databaseId' | xargs gh run watch --exit-status
```
Expected: workflow completes with success.

- [ ] **Step 2: Poll prod health until new SHA reports.**
```bash
EXPECTED_SHA=$(git rev-parse HEAD)
for i in $(seq 1 18); do
  HEALTH=$(curl -s https://www.zettelkasten.in/api/health)
  echo "$HEALTH" | grep -q "$EXPECTED_SHA" && echo "deployed" && break
  sleep 5
done
```
Expected: prints `deployed` within 90s. If not, investigate via `gh run view --log` and resolve.

- [ ] **Step 3: Verify backfill ran on cutover.** Check droplet logs:
```bash
ssh deploy@<droplet> "docker logs zettelkasten-app | grep 'metadata backfill'"
```
Expected: backfill reported as `complete: N chunks`.

### Task 27: Claude-in-Chrome verification flow

**Files:**
- Create: `docs/rag_eval/<kasten-slug>/iter-01/screenshots/`

- [ ] **Step 1: Open Chrome, navigate to https://www.zettelkasten.in. Confirm logged-in user is Naruto.** Screenshot → `01-naruto-confirmed.png`.

- [ ] **Step 2: Create the new Kasten via UI.** Navigate to `/home/kastens`, click Create button, fill name (kasten-slug + display title), submit. Verify network tab shows `/api/rag/sandboxes` request with 200 response and `sandbox_id` returned (Phase 0 bug #4 fix proof). Screenshot → `02-kasten-created.png`.

- [ ] **Step 3: Add member Zettels via UI.** From `/home/kastens/<sandbox_id>`, add each existing-Zettel from `_kasten_topic_discovery.json`. Verify each add succeeds (`added_count` > 0 — Phase 0 bug #2 fix proof). Screenshot → `03-members-added.png`.

- [ ] **Step 4: If `fresh_zettels_needed` is non-empty, add them via `/home`** Add button. For each: paste URL, submit, wait for summarization to complete, verify chunks ingested (`/api/graph` shows new node + `kg_node_chunks` count > 0). Screenshot → `04-fresh-zettel-added.png`.

- [ ] **Step 5: Open chat for the new Kasten via `/home/rag`.** Screenshot → `05-chat-open.png`.

- [ ] **Step 6: Run gold-set queries (7-10 questions).** For each query:
  - Send via the chat UI
  - Wait for full SSE stream
  - Capture from DevTools network tab: the SSE message containing `retrieved_node_ids` and `rerank_scores`
  - Save into `answers.json` (append mode):
    ```json
    {"query": "...", "expected_node_id": "...", "actual_top_node_id": "...", "rerank_score": 0.X, "answer": "...", "citations": [...]}
    ```
  - Screenshot → `06-q{N}-answered.png`

- [ ] **Step 7: Run ablation pass.** Replay each query with `?graph_weight=0.0` query param (or via internal API if the route supports override). Save into `ablation_eval.json`.

- [ ] **Step 8: Run KG-first ablation.** SSH to droplet, edit the inactive (idle) color's `.env` file in `/opt/zettelkasten/deploy/` to add `RAG_KG_FIRST_ENABLED=false`, run `docker compose -f docker-compose.<idle>.yml up -d --force-recreate`, swap Caddy upstream to the idle color via `caddy reload`, re-run 3 queries via Chrome, swap back, restore env.

### Task 28: Compute eval artifacts via existing eval_runner

**Files:**
- Create: all `docs/rag_eval/<kasten-slug>/iter-01/*` artifacts

- [ ] **Step 1: Write `queries.json`** with the 7-10 gold-set queries used in Task 27.

- [ ] **Step 2: Run the existing eval pipeline locally against the recorded answers.**
```bash
python -m website.features.rag_pipeline.evaluation.eval_runner \
  --queries docs/rag_eval/<kasten-slug>/iter-01/queries.json \
  --answers docs/rag_eval/<kasten-slug>/iter-01/answers.json \
  --output docs/rag_eval/<kasten-slug>/iter-01/eval.json
```
NOTE: verify the exact CLI signature by reading `eval_runner.py`. Adjust if needed.

- [ ] **Step 3: Compute composite scores via existing composite scorer.** Output `scores.md`.

- [ ] **Step 4: Compute `improvement_delta.json`** comparing iter-01 composite to iter-06 baseline (composite ~85, retrieval 100, reranking 95, synthesis 92).
```json
{"baseline_iter": "iter-06", "composite_delta": {"iter-01": +X.X, "previous": 85}, "per_stage_delta": {...}}
```

- [ ] **Step 5: Write `README.md`** following iter-06 format: per-query results table, success summary, prod issues surfaced.

- [ ] **Step 6: Write `next_actions.md`** with iter-02 priorities based on weakest scoring stage.

- [ ] **Step 7: Move topic discovery JSON.**
```bash
git mv docs/rag_eval/_kasten_topic_discovery.json docs/rag_eval/<kasten-slug>/iter-01/kasten.json
```

- [ ] **Step 8: Commit eval bundle.**
```bash
git add docs/rag_eval/<kasten-slug>/iter-01/
git commit -m "feat: rag_eval <kasten-slug> iter-01 wide-net all-phases"
```

### Task 29: Regression gate

**Files:** none (decision step)

- [ ] **Step 1: Read `improvement_delta.json`.**

- [ ] **Step 2: Apply gate.** If composite < 85 * 0.95 = 80.75:
  - Auto-revert: identify all iter-01 commits since the spec commit
  - `git revert --no-commit <range>; git commit -m "ops: auto-revert iter-01 regression"`
  - Push, redeploy
  - Document failure mode in `manual_review.md`
  - STOP — do not proceed to iter-02

- [ ] **Step 3: If composite ≥ 80.75:** proceed to iter-02. Push final iter-01.

---

# ITERATION 02

iter-02 reads `iter-01/next_actions.md` to drive specific refinements. The shape below is the always-on baseline; the conditional refinements are listed under §iter-02 conditional refinements.

## Phase 1' — Re-run all 4 phases against new gold set

### Task 30: Re-baseline against AI/ML Foundations Kasten (regression guard)

- [ ] **Step 1: Open Chrome, switch to AI/ML Foundations Kasten.**

- [ ] **Step 2: Re-run iter-06 gold queries** (4 successful + 2 quota-failed re-attempted now that billing-key escalation is live).

- [ ] **Step 3: Capture results** to `docs/rag_eval/<kasten-slug>/iter-02/regression_aimL.json`.

- [ ] **Step 4: Assert composite on AI/ML ≥ iter-06 baseline (~85).** If lower, root-cause before proceeding.

### Task 31: Iter-02 conditional refinement — chunking

**Files:** depend on iter-01 next_actions.md

- [ ] **Step 1: Read `iter-01/next_actions.md`.** If chunking score ≥ 70, skip this task.

- [ ] **Step 2: Else, widen ingest enrichment.** In `metadata_enricher.py`, add (a) more entity types (`technical_concepts`, `methods`, `datasets`), (b) finer time-span granularity (per-paragraph instead of per-chunk-head), (c) explicit chunk-position metadata (`is_intro`, `is_conclusion`).

- [ ] **Step 3: Re-run backfill.** `python ops/scripts/backfill_metadata.py --force` (add a `--force` flag that ignores `metadata_enriched_at`).

- [ ] **Step 4: Commit.**
```bash
git commit -m "feat: iter-02 widen chunking metadata"
```

### Task 32: Iter-02 conditional refinement — reranking

- [ ] **Step 1: If reranking score ≥ 75, skip.**

- [ ] **Step 2: Else tune `_passage_text` header.** Drop low-signal fields (e.g., `tags=` if iter-01 ablation showed no lift). Add `position=intro|body|conclusion` from the chunk-position metadata added in Task 31.

- [ ] **Step 3: Add unit test asserting new header shape.**

- [ ] **Step 4: Commit.**

### Task 33: Iter-02 conditional refinement — synthesis

- [ ] **Step 1: If synthesis score ≥ 75, skip.**

- [ ] **Step 2: Else tune sentence distillation.** In `distiller.py`: increase `_TOP_K` to 7 for THEMATIC, decrease to 3 for LOOKUP. Set `_SCAFFOLD_NEIGHBOURS = 2` for STEP_BACK.

- [ ] **Step 3: Add summary-vs-chunk mix.** For THEMATIC queries, prepend the node's `SUMMARY` chunk (when `ChunkKind.SUMMARY` exists) ahead of selected sentences.

- [ ] **Step 4: Commit.**

### Task 34: Iter-02 conditional refinement — KG-first expansion

- [ ] **Step 1: If KG-first ablation in iter-01 showed lift > 5%, expand triggers.**

- [ ] **Step 2: In `RetrievalPlanner.plan`, add THEMATIC to KG-first trigger set.**

- [ ] **Step 3: Increase expand depth to 2 for MULTI_HOP.**

- [ ] **Step 4: Add unit tests for the new triggers.**

- [ ] **Step 5: Commit.**

### Task 35: Iter-02 conditional refinement — usage-edge integration

- [ ] **Step 1: Query `kg_usage_edges_agg` row count.**
```bash
psql $SUPABASE_DB_URL -c "SELECT count(*) FROM kg_usage_edges_agg"
```

- [ ] **Step 2: If count > 100,** raise the `_usage_weight_bonus` ceiling from 0.10 to 0.15 in `graph_score.py`. Add an ablation test that sets `RAG_USAGE_EDGES_ENABLED=false` and re-runs queries.

- [ ] **Step 3: If count ≤ 100,** keep at 0.10 — note in `next_actions.md` that more user volume is needed.

- [ ] **Step 4: Commit if changes made.**

### Task 36: Always-on — Supabase write-through metadata cache

**Files:**
- Create: `website/features/rag_pipeline/query/metadata_cache_supabase.py`
- Create: `supabase/website/kg_public/migrations/2026-04-26_query_metadata_cache.sql`
- Modify: `website/features/rag_pipeline/query/metadata.py`

- [ ] **Step 1: Schema migration.**
```sql
CREATE TABLE IF NOT EXISTS query_metadata_cache (
  query_hash text PRIMARY KEY,
  metadata_json jsonb NOT NULL,
  created_at timestamptz DEFAULT now(),
  ttl_seconds int DEFAULT 3600
);
CREATE INDEX IF NOT EXISTS idx_qmc_recent ON query_metadata_cache (created_at DESC);
```
Apply.

- [ ] **Step 2: Write `metadata_cache_supabase.py` with write-through wrapper.**
```python
import hashlib, json
from datetime import datetime, timezone, timedelta

class SupabaseQueryMetadataCache:
    def __init__(self, supabase):
        self._sb = supabase
    def _hash(self, key: str) -> str:
        return hashlib.sha256(key.encode("utf-8")).hexdigest()
    def get(self, key: str):
        h = self._hash(key)
        res = self._sb.table("query_metadata_cache").select("*").eq("query_hash", h).execute()
        rows = res.data or []
        if not rows: return None
        row = rows[0]
        age = (datetime.now(timezone.utc) - datetime.fromisoformat(row["created_at"])).total_seconds()
        if age > row["ttl_seconds"]:
            return None
        return row["metadata_json"]
    def set(self, key: str, value):
        h = self._hash(key)
        self._sb.table("query_metadata_cache").upsert({
            "query_hash": h, "metadata_json": value, "created_at": "now()",
        }).execute()
```

- [ ] **Step 3: Wire into `QueryMetadataExtractor`** with cache-fallthrough: in-process LRU first, then Supabase, then compute. On compute, write to both.

- [ ] **Step 4: Add unit test (mock supabase).**

- [ ] **Step 5: Commit.**
```bash
git commit -m "feat: supabase write-through query metadata cache"
```

### Task 37: iter-02 verification cycle

Identical to Tasks 25-29 but pointing at `iter-02/` folder, with `iter-01/improvement_delta.json` composite as the regression baseline (gate = composite < iter01 * 0.95 → auto-revert).

- [ ] **Step 1:** Pre-deploy tests, push.
- [ ] **Step 2:** Deploy + wait + prod-health poll.
- [ ] **Step 3:** Claude-in-Chrome verification on the SAME Kasten (different queries to test no-overfit) + AI/ML Foundations regression check.
- [ ] **Step 4:** Compute `iter-02/eval.json`, `scores.md`, `improvement_delta.json` (vs iter-01).
- [ ] **Step 5:** Apply regression gate.
- [ ] **Step 6:** Commit `feat: rag_eval <kasten-slug> iter-02 refinement`.

---

## Closing checklist (post iter-02)

- [ ] Worktree branch merged into master via PR (or merged directly per maintainer call).
- [ ] All Phase 0 prod bugs verified fixed in production.
- [ ] iter-01 and iter-02 folder content fully populated with no placeholder strings.
- [ ] `next_actions.md` in iter-02 lists carry-forward items for a future iter-03 (if any).
- [ ] Memory observation saved via mem-vault marking iter-01+iter-02 outcome (composite scores, what worked, what didn't).

End of plan.
