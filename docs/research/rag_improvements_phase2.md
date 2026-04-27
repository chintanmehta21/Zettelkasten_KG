<img src="https://r2cdn.perplexity.ai/pplx-full-logo-primary-dark%402x.png" style="height:64px;margin-right:32px"/>

# Go ahead!

Choose the most optimum free option for all the improvements you suggested and fit them accurately in my system

Here’s a concrete, “free‑first” design that plugs directly into your current modules (no new paid infra), with specific model/library choices and where they slot into your pipeline. I’ll keep it implementation‑oriented.

***

## 1. Query‑side metadata extractor

### Model/library choice (free)

- Use the open GLiNER / “gliner‑base” or a comparable open NER model from Hugging Face, run locally in Python.
- For temporal expressions, use `dateparser` or `sutime`‑style parsing; both are free Python libs.


### Integration point

Hook into `_prepare_query` / `HybridRetriever.retrieve` by adding a small adapter that translates extracted metadata into richer `ScopeFilter` and extra preferences, but without breaking existing calls.

**API sketch** (new module `website/features/rag_pipeline/query/metadata.py`):

```python
# metadata.py
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from website.features.rag_pipeline.types import ScopeFilter, SourceType

@dataclass
class QueryMetadata:
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    authors: list[str] = None
    channels: list[str] = None
    domains: list[str] = None
    preferred_sources: list[SourceType] = None

class QueryMetadataExtractor:
    def __init__(self, ner_model):
        self._ner = ner_model  # GLiNER or similar

    async def extract(self, text: str) -> QueryMetadata:
        # 1) Run NER
        # 2) Heuristics to map entities -> authors/channels/domains
        # 3) Use dateparser on time expressions ("last year", "2020 talk")
        ...
```

In `RAGOrchestrator._prepare_query`, after you compute `standalone` and `query_class`, call the extractor:

```python
# orchestrator.py (inside _prepare_query)
metadata = await self._metadata_extractor.extract(standalone)
# store on PreparedQuery if you like
return _PreparedQuery(
    session_id=session_id,
    trace_id=trace_id,
    standalone=standalone,
    query_class=query_class,
    variants=variants,
    metadata=metadata,  # new field if you extend the dataclass
)
```

Then, in `HybridRetriever.retrieve`, add an optional `metadata: QueryMetadata | None` parameter and convert that into more precise `ScopeFilter` / RPC args.

***

## 2. Index‑side metadata augmentation

### Free tools

- Use the same GLiNER model (shared instance) plus:
    - `tldextract` to normalize domains
    - `dateparser` for dates inside Zettels (transcripts, posts, etc.).


### Integration point

In your ingest pipeline (not shown here, but wherever you create Zettel nodes in Supabase):

- After summarizing/embedding content, run an offline enrichment step:
    - Extract person/organization names → `tags` and/or `metadata["entities"]`.
    - Detect channel/author names (e.g., from YouTube API metadata) → `metadata["author"]` / `metadata["channel"]`.
    - Extract and resolve time spans inside the content → `metadata["time_span"] = {"start": "...", "end": "..."}`.

You already read `metadata` from `rag_hybrid_search` into `RetrievalCandidate`, so nothing changes in your Python pipeline.

***

## 3. Metadata‑aware retrieval and heuristics

You already have `_dedupe_variants`, title boosts, and kind‑based boosts in `HybridRetriever._dedup_and_fuse`.  We can extend this without touching Supabase right away.

### 3.1. Time‑decay and recency

Add a simple time‑decay function using `metadata["timestamp"]` or `metadata["time_span"]`.

```python
# hybrid.py (new helper)
from datetime import datetime, timezone

def _recency_boost(metadata: dict, query_class: QueryClass) -> float:
    # Stronger boost for LOOKUP; weaker for STEP_BACK/THEMATIC
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
    # Simple: 0.1 boost for very recent, decaying to ~0 beyond 2 years
    if query_class in (QueryClass.LOOKUP, QueryClass.VAGUE):
        scale = 0.1
    else:
        scale = 0.05
    return scale * max(0.0, 1.0 - age_days / 730.0)
```

Then inside `_dedup_and_fuse`, after existing boosts:

```python
# inside for key, candidate in by_key.items():
    candidate.rrf_score += 0.05 * (variant_hits[key] - 1)
    boost = _title_match_boost(candidate.name, normalized_variants)
    if boost > 0:
        candidate.rrf_score += boost
    if len(kinds_by_node.get(candidate.node_id, set())) > 1:
        candidate.rrf_score += 0.03
    candidate.rrf_score += _recency_boost(candidate.metadata, query_class)
```

(You can pass `query_class` into `_dedup_and_fuse`, or store it on the retriever instance.)

### 3.2. Source‑type preferences

Use `SourceType` to cheaply favor long‑form or certain platforms depending on query class.

```python
def _source_type_boost(candidate: RetrievalCandidate, query_class: QueryClass) -> float:
    if query_class in (QueryClass.THEMATIC, QueryClass.STEP_BACK):
        if candidate.source_type.value == "youtube":
            return 0.03
    if query_class is QueryClass.LOOKUP and candidate.source_type.value == "reddit":
        # Often short factual answers
        return 0.02
    return 0.0
```

Then:

```python
candidate.rrf_score += _source_type_boost(candidate, query_class)
```

This keeps everything local, free, and reversible.

***

## 4. Metadata‑aware cross‑encoder input (no new model)

You already use FlashRank and a BGE cross‑encoder ONNX in `CascadeReranker`, and reranking text is defined by `_passage_text(candidate)`.  We can enrich the text with a short metadata header, which is free and backward‑compatible.

### Implementation

Change `_passage_text` to include a structured header line:

```python
# cascade.py
def _passage_text(candidate: RetrievalCandidate) -> str:
    content = (candidate.content or "")[:4000]
    name = (candidate.name or "").strip()
    parts = []

    # Metadata header
    meta_pieces = []
    if candidate.source_type:
        meta_pieces.append(f"source={candidate.source_type.value}")
    if candidate.metadata:
        author = candidate.metadata.get("author") or candidate.metadata.get("channel")
        if author:
            meta_pieces.append(f"author={author}")
        ts = candidate.metadata.get("timestamp")
        if ts:
            meta_pieces.append(f"date={ts}")
    if candidate.tags:
        meta_pieces.append("tags=" + ",".join(candidate.tags[:5]))
    if meta_pieces:
        parts.append("[" + "; ".join(meta_pieces) + "]")

    # Title + body (your existing logic)
    if name:
        head = content.lstrip()[:120].lower()
        if name.lower() not in head:
            parts.append(name)
    parts.append(content)

    return "\n\n".join(parts)
```

This gives the cross‑encoder extra discrimination power with zero change to the ONNX graph or Ranker APIs.

***

## 5. Context distillation and compression

Your `ContextAssembler` already does sophisticated grouping, overlap trimming, budget packing, and stub filtering.  We can add a lightweight sentence‑level evidence selector that reuses existing embeddings to avoid new paid models.

### 5.1. Free models

- Use your current embedder (BGE / whatever you already use in Supabase) by exposing an `embed_texts` endpoint in Python (or reuse the RPC) to score sentences locally.
- Alternatively, use a small open bi‑encoder like `bge-small-en` locally if you want to keep it independent of DB, but that’s still free.


### 5.2. Integration point

Add an optional `compressor` implementation and plug it into `ContextAssembler._fit_within_budget`, which already receives `user_query` and `grouped` candidates.

**Interface**:

```python
# context/compressor.py
from typing import List
from website.features.rag_pipeline.types import RetrievalCandidate

class EvidenceCompressor:
    async def compress(
        self,
        *,
        user_query: str,
        grouped: list[list[RetrievalCandidate]],
        target_budget_tokens: int,
    ) -> list[list[RetrievalCandidate]]:
        ...
```

**Usage** in `_fit_within_budget` (early in the method):

```python
async def _fit_within_budget(...):
    used_tokens = 0
    fitted = []
    used = []

    # New: optional pre-compression
    if self._compressor is not None:
        grouped = await self._compressor.compress(
            user_query=user_query,
            grouped=grouped,
            target_budget_tokens=budget,
        )

    # existing logic continues...
```

For a first version, you can keep compression trivial (e.g., truncate long `candidate.content` to the top N sentences ranked by local similarity using your embedder). Because you already maintain node IDs and chunk IDs, citations remain intact.

***

## 6. KG–RAG routing and coupling (using what you already have)

You already pass `graph_depth` and per‑class graph weights into `rag_hybrid_search`, and you have a `QueryClass` router.  You also mentioned GraphRAG is implemented in‑house, so we’ll just add a thin planner that toggles “KG‑first” vs “RAG‑first” behavior without new infra.

### 6.1. Free KG‑first planner

Assume you expose a KG client with two free operations:

- `kg.resolve_entities(query_text) -> list[node_id]`
- `kg.expand(nodes, depth) -> list[node_id]`

Add a `RetrievalPlanner` that sits in front of `HybridRetriever`:

```python
# backends/planner.py
from website.features.rag_pipeline.types import QueryClass, ScopeFilter

class RetrievalPlanner:
    def __init__(self, kg_client):
        self._kg = kg_client

    async def plan(
        self,
        *,
        query_text: str,
        query_class: QueryClass,
        scope_filter: ScopeFilter,
    ) -> ScopeFilter:
        # Start from existing scope filter
        effective_filter = scope_filter

        # KG-first for entity-heavy lookup / multi-hop
        if query_class in (QueryClass.LOOKUP, QueryClass.MULTI_HOP):
            entities = await self._kg.resolve_entities(query_text)
            if entities:
                expanded = await self._kg.expand(entities, depth=1)
                if expanded:
                    # Intersect with existing node_ids if present, else override
                    node_ids = effective_filter.node_ids or []
                    if node_ids:
                        node_ids = list(set(node_ids) & set(expanded))
                    else:
                        node_ids = expanded
                    effective_filter = effective_filter.model_copy(update={"node_ids": node_ids})

        # THEME/STEP_BACK: keep your current hybrid behavior
        return effective_filter
```

Then in `HybridRetriever.retrieve`, call the planner first to get an adjusted `ScopeFilter` (free, in‑process), and pass that into `_resolve_nodes` as usual.

### 6.2. Usage edges from Q\&A traces

Your `AnswerTurn` already stores `retrieved_node_ids` and you know critic verdicts.  Periodically (offline), you can:

- For turns with verdict in `("supported", "retried_supported")`, increment an “edge weight” in your KG from query entities to these nodes.
- Store that as a field in the graph and use it as an extra term in the graph scoring function you already call before reranking (`self._graph.score`).

This is completely free as long as your KG store is self‑hosted (which it sounds like it is); it’s just an offline job.

***

## 7. Budget‑aware context sizing (leveraging existing knobs)

You already have `_BUDGET_BY_QUALITY`, token estimation, and partial group packing inside `_fit_within_budget`.  To make it more adaptive without new models:

- Expose a `max_context_tokens` field on the query or quality profile.
- Use that instead of fixed `_BUDGET_BY_QUALITY` when present.

```python
# assembler.py build()
budget = query_context_budget or _BUDGET_BY_QUALITY[quality]
```

You can compute `query_context_budget` at the orchestrator level based on the chosen LLM model (cheap vs strong), which is free and trivially configurable.

***

## 8. Putting it together in your constructor

Your `RAGOrchestrator` already receives `rewriter, router, transformer, retriever, graph_scorer, reranker, assembler, llm, critic, sessions`.  The minimal free upgrade path that fits in cleanly:

1. **Instantiate free components once at startup**:
    - `QueryMetadataExtractor` with GLiNER model.
    - `EvidenceCompressor` using your existing embedder.
    - `RetrievalPlanner` wrapping your in‑house GraphRAG client.
2. **Wire them into existing modules**:
    - Add `metadata_extractor` to the orchestrator and pass metadata into `HybridRetriever.retrieve`.
    - Give `ContextAssembler` a `compressor` instance (you already support `compressor=None`).
    - Wrap `scope_filter` via `RetrievalPlanner.plan` before calling `HybridRetriever.retrieve`.
3. **Local code changes only**:
    - `_passage_text` enrichment in `CascadeReranker`.
    - Extra boosts in `HybridRetriever._dedup_and_fuse`.
    - Optional use of metadata/recency in `_render_xml` if you want to surface timestamps more prominently (you already pass them as XML attributes).

All of this keeps you on open‑source/freely‑hostable components, reuses your existing BGE/FlashRank and Supabase stack, and plugs into clear extension points you’ve already built (final_score fusion, context budgets, KG scores, etc.).

If you want, I can next draft concrete diff‑style snippets for a couple of key files (`hybrid.py`, `cascade.py`, `assembler.py`, `orchestrator.py`) that you can more or less paste in and adapt.

