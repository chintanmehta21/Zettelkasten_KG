# RAG Improvements — iter-01 & iter-02 Design

**Date:** 2026-04-26
**Branch:** `worktree-rag-improvements-iter-01-02`
**Source research:** `docs/research/rag_improvements_phase1.md`, `docs/research/rag_improvements_phase2.md`
**Baseline:** iter-06 (browser-driven, AI/ML Foundations Kasten, Naruto user) — retrieval 100, reranking ~95, synthesis ~92.

## 1. Goal & success criteria

Two wide-net iterations that each apply ALL four research phases (metadata layer, cross-encoder header, context distillation, KG-RAG coupling) end-to-end. iter-02 refines based on iter-01 measurements. Each iter is gated by deploy + browser-verified prod scores.

**Success per iter:**
- Backend: composite score on the new-Kasten gold set ≥ iter-06 (~85). Per-stage component scores log all 4 components ≥ 70 (chunking, retrieval, reranking, synthesis).
- UX: every iter-06 leftover prod bug fixed by end of iter-01. Zero new UX regressions in iter-02 (Chrome flow proves the user path end-to-end without API workarounds).
- Data: full iter-folder artifact set written to `docs/rag_eval/<kasten-slug>/iter-01/` and `iter-02/`.
- Regression gate: composite drop > 5% from previous baseline blocks merge — auto-revert.

**Out of scope:** new summarization features, generative changes to the bot pipeline, Telegram-side changes, mobile-site work.

## 2. Iteration shape

```
iter-01:
  ┌─ Topic discovery (main Claude, via Claude-in-Chrome)
  └─ Phase 0 prereqs (subagent, parallel)
  ↓ both join
  Phase 1 → Phase 2 → Phase 3 → Phase 4   (sequential, each tested)
  ↓
  unit + integration tests → commit → push master → gh deploy → wait for prod
  ↓
  Claude-in-Chrome verification (login as Naruto, run gold-set, capture)
  ↓
  Compute eval artifacts → write iter-01/ folder → commit
  ↓ (gate: composite ≥ baseline-5%, else auto-revert)
iter-02: same shape, baseline = iter-01, no Phase 0 prereqs, refinements informed by iter-01 next_actions.md
```

## 3. Phase 0 (iter-01 only) + Topic discovery (parallel)

**Topic discovery — main Claude via Claude-in-Chrome:**
1. Open https://www.zettelkasten.in, log in as Naruto.
2. GET `/api/graph` (auth'd via JWT in browser context). List Naruto's Zettels.
3. Cluster by `tags` ∪ `source_type` ∪ title-keywords. Rank topics by `(zettel_count ≥ 7) AND (distinct_source_types ≥ 3)` excluding the AI/ML Foundations cluster.
4. Pick highest-ranking eligible topic. Fallback if no topic eligible: **"Knowledge Management & Personal Productivity"** (zettelkasten/obsidian/second-brain/local-first/clean-architecture seed already in `graph.json`).
5. If 5-6 eligible Zettels exist, **add 2-3 fresh Zettels via Chrome** (only sanctioned summarization calls) chosen to balance to ≥ 3 source_types. Each new Zettel goes through full prod pipeline.
6. Output: `<kasten-slug>` (kebab-case), member node_ids, source_type breakdown → handed to iter-01 Phase 4 (Kasten creation).

**Phase 0 fixes — subagent in parallel:**

| Bug | Fix | Test |
|---|---|---|
| #2 `rag_bulk_add_to_sandbox` silent no-op | Read SQL definition; reproduce in psql with Naruto user; identify root cause (likely RLS + `text[]` vs `uuid[]` coercion); patch SQL via Supabase migration; assert in Python route that `added_count == len(requested_ids)` else raise 500 | SQL-level regression test in `tests/integration_tests/test_rag_sandbox_rpc.py` |
| #4 form-submit handler dead | Rebind click on `/home` Add and `/home/kastens` Create — likely stale element refs after async auth lands (same class as commit `72a1fcf`). Use event delegation on parent container | Browser smoke via existing playwright fixture if present; else manual via Chrome flow |
| Dependencies | Add `dateparser>=1.2`, `tldextract>=5.1` to `ops/requirements.txt`. Pin versions. Build + run unit suite locally. | Existing CI |

Phase 0 ships as separate commits before Phase 1 work begins. Topic discovery output unblocks the iter-01 Kasten step but does not block code work.

## 4. Phase 1 — Metadata layer

### 4.1 `QueryMetadataExtractor` (new module `website/features/rag_pipeline/query/metadata.py`)

```python
@dataclass
class QueryMetadata:
    start_date: datetime | None = None
    end_date: datetime | None = None
    authors: list[str] = field(default_factory=list)
    channels: list[str] = field(default_factory=list)
    domains: list[str] = field(default_factory=list)
    preferred_sources: list[SourceType] = field(default_factory=list)
    entities: list[str] = field(default_factory=list)
    confidence: float = 0.0  # 0.0 if pure-C, higher if A confirmed

class QueryMetadataExtractor:
    def __init__(self, *, key_pool, cache):
        self._key_pool = key_pool
        self._cache = cache  # cachetools.TTLCache(maxsize=1024, ttl=3600)
    async def extract(self, text: str, *, query_class: QueryClass) -> QueryMetadata: ...
```

**C-pass (sync, ~5 ms):**
- `dateparser` → `start_date`, `end_date` (relative + absolute)
- `tldextract` → `domains` from URL-like tokens
- Static keyword map → `preferred_sources` (e.g., "youtube talk" → `SourceType.YOUTUBE`)
- Hardcoded known-author list (top-50 from existing graph) → `authors` cheap match

**A-pass (async, cached):**
- Reuse `kg_features/entity_extractor.py` `extract` with a query-mode prompt
- **Skip if** C filled `authors` AND `domains` AND `start_date`
- Otherwise: 1 Gemini Flash-Lite call, structured output, populate `entities`/`authors`/`channels`
- Cache key = `normalize(text)`. TTL 3600s. In-process per-worker.

### 4.2 Ingest-side metadata enrichment

New module `website/features/rag_pipeline/ingest/metadata_enricher.py`:
- Runs after `chunker` writes a chunk
- Extracts `entities` (Gemini batched 5 chunks/call), `domain` (tldextract), `time_span` (dateparser on chunk text)
- Writes to `kg_node_chunks.metadata` JSONB column (already exists in schema)
- New column `metadata_enriched_at timestamptz` so re-deploys don't re-burn
- **Auto-backfill on deploy:** `ops/scripts/backfill_metadata.py` triggered by deploy hook on first iter-01 prod cutover. Idempotent (skips chunks with non-null `metadata_enriched_at`). ~120 chunks × ~1s each ≈ 2 min.

### 4.3 Retrieval-side boosts in `HybridRetriever._dedup_and_fuse`

Pass `query_class` and `QueryMetadata` into `_dedup_and_fuse`. Add three boost helpers:

| Helper | Formula | Score weight |
|---|---|---|
| `_recency_boost(metadata, query_class)` | `scale * max(0, 1 - age_days/730)` where scale = 0.10 (LOOKUP/VAGUE), 0.05 (THEMATIC/STEP_BACK) | additive to `rrf_score` |
| `_source_type_boost(candidate, query_class)` | YouTube +0.03 (THEMATIC/STEP_BACK); Reddit +0.02 (LOOKUP) | additive to `rrf_score` |
| `_author_match_boost(candidate, query_meta)` | +0.05 if any extracted query author matches `metadata.author` (case-insensitive substring) | additive to `rrf_score` |

All boosts are additive and bounded (worst-case +0.18) so they don't dominate the RRF base. RPC call unchanged — pass the metadata via existing `metadata` parameter pattern; no schema migration in iter-01.

## 5. Phase 2 — Cross-encoder structured header

Modify `CascadeReranker._passage_text(candidate)` in `website/features/rag_pipeline/rerank/cascade.py`:

```
[source=youtube; author=Andrej Karpathy; date=2023-10-12; tags=transformers,vision]
{title}
{content[:4000]}
```

- Header always prepended, even if some fields are empty (deterministic)
- Tags capped at top-5
- Body truncation unchanged
- BGE ONNX graph unchanged — improvement is purely textual

Add unit test in `tests/unit/rag/test_passage_text.py` asserting header presence and field ordering for representative candidates.

## 6. Phase 3 — Context distillation

### 6.1 Sentence-level evidence selector (new `website/features/rag_pipeline/context/distiller.py`)

Two-stage cascade mirroring FlashRank → BGE-CE pattern:

| Stage | Trigger | Mechanism |
|---|---|---|
| **Bi-encoder (default)** | Always run | Split candidate content into sentences (regex `[.!?]\s+`); embed via existing BGE embedder, batched per candidate (1 forward pass); cosine sim vs query embedding; keep top-5 sentences + 1 scaffold neighbour for local coherence |
| **Cross-encoder fallback** | (a) top-3 sentence cosines all < 0.55, OR (b) top-3 sentence cosines within 0.05 of each other (tight cluster → ambiguous tie-breaker) | Re-score that candidate's sentences with already-loaded BGE-CE; replace bi-encoder ranking |

Selector runs between rerank and assembler. Outputs `RetrievalCandidate` with content replaced by selected sentences (preserves `node_id`, `chunk_id`, `metadata` for citation integrity). Hook into `ContextAssembler._fit_within_budget` early via optional `compressor` arg (already supports `None`).

### 6.2 Budget-aware dynamic sizing

Replace `_BUDGET_BY_QUALITY` lookup with per-LLM-tier:
```python
_BUDGET_BY_LLM_TIER = {
    "gemini-2.5-flash":      6000,
    "gemini-2.5-flash-lite": 4000,
    "gemini-2.5-pro":        8000,
}
```
Orchestrator passes the model selected by key-pool to `ContextAssembler.build()`. Falls through to existing `_BUDGET_BY_QUALITY` if model unrecognized.

## 7. Phase 4 — KG-RAG coupling

### 7.1 `RetrievalPlanner` adapter

New `website/features/rag_pipeline/retrieval/planner.py` — thin (~50 LOC) adapter wrapping `kg_features/retrieval.py`:

```python
class RetrievalPlanner:
    def __init__(self, kg_retrieval_module):
        self._kg = kg_retrieval_module
    async def plan(self, *, query_meta: QueryMetadata, query_class, scope_filter) -> ScopeFilter:
        if query_class in (QueryClass.LOOKUP, QueryClass.MULTI_HOP) and query_meta.entities:
            expanded = await self._kg.expand_subgraph(query_meta.entities, depth=1)
            if expanded:
                node_ids = (set(scope_filter.node_ids) & set(expanded)) if scope_filter.node_ids else expanded
                return scope_filter.model_copy(update={"node_ids": list(node_ids)})
        return scope_filter
```

The planner consumes `QueryMetadata.entities` already populated by Phase 1's `QueryMetadataExtractor` — no separate Gemini call, no separate cache. If `kg_features/retrieval.py` does not already expose `expand_subgraph(node_ids, depth) -> list[node_id]`, add it as a thin Supabase recursive-CTE query on `kg_links`.

Wired in orchestrator `_prepare_query` BEFORE `HybridRetriever.retrieve`. Behind env flag `RAG_KG_FIRST_ENABLED=true` (default true; flipping false reverts to current behavior).

### 7.2 Usage-edge offline learning

**Schema (Supabase migration):**
```sql
CREATE TABLE kg_usage_edges (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES auth.users(id),
  source_node_id text NOT NULL,
  target_node_id text NOT NULL,
  query_class text NOT NULL,
  verdict text NOT NULL CHECK (verdict IN ('supported','retried_supported')),
  delta float NOT NULL DEFAULT 1.0,
  created_at timestamptz DEFAULT now()
);
CREATE MATERIALIZED VIEW kg_usage_edges_agg AS
  SELECT user_id, source_node_id, target_node_id, query_class,
         SUM(delta * exp(-EXTRACT(epoch FROM (now()-created_at))/2592000.0)) AS weight
  FROM kg_usage_edges GROUP BY 1,2,3,4;
ALTER TABLE kg_usage_edges ENABLE ROW LEVEL SECURITY;
CREATE POLICY "user_owns_usage_edge" ON kg_usage_edges
  USING (user_id = auth.uid()) WITH CHECK (user_id = auth.uid());
```

**Refresh runner:** `.github/workflows/recompute_usage_edges.yml`
- Schedule: `cron: '0 2 * * *'` (2am UTC nightly)
- Job: checkout repo → install deps → run `python ops/scripts/recompute_usage_edges.py`
- Script reads `chat_messages` + `rag_turns` from last 24h via Supabase service-role key (GH secret `SUPABASE_SERVICE_ROLE_KEY`); computes per-edge deltas (`supported`=1.0, `retried_supported`=0.5); upserts `kg_usage_edges`; calls `REFRESH MATERIALIZED VIEW kg_usage_edges_agg`
- Idempotent — safe to re-run. Writes `recompute_runs` audit row per execution.
- Workflow also runnable via `workflow_dispatch` for manual recovery.

### 7.3 Score integration

`graph_score.py` reads `kg_usage_edges_agg.weight` for the candidate node's incoming usage edges from query-class buckets, normalizes (sigmoid `1/(1+exp(-w/5))`), adds 0-0.10 bonus to existing `graph_score` before fusion. Behind env flag `RAG_USAGE_EDGES_ENABLED` (default `true`).

## 8. Verification flow per iter

```
[1] unit suite        → pytest tests/unit/rag/ tests/unit/rag_pipeline/
[2] integration suite → pytest tests/integration_tests/ -m 'not live'
[3] commit + push master
[4] gh run watch <deploy-droplet workflow>  (block until success)
[5] poll GET https://www.zettelkasten.in/api/health every 5s for 90s, assert
    response payload contains the new commit SHA (via /api/health version field)
[6] Claude-in-Chrome verification (full flow, see §10)
[7] Compute eval artifacts via existing rag_pipeline/evaluation/eval_runner.py
[8] Write iter folder, commit `feat: rag_eval <kasten-slug> iter-NN`
[9] Regression gate: if composite < baseline * 0.95, auto-revert via git revert
    HEAD~K..HEAD (K = number of iter commits) and re-deploy
```

## 9. rag_eval folder layout & captured artifacts

```
docs/rag_eval/<kasten-slug>/
  iter-01/
    README.md                 # browser flow narrative + per-query results (iter-06 style)
    queries.json              # 7-10 questions w/ gold node_ids, query_class, expected source_type
    qa_pairs.md               # human-readable Q&A
    answers.json              # actual prod answers + citations + rerank scores + latency
    eval.json                 # composite/RAGAS/DeepEval pass via eval_runner
    scores.md                 # composite + per-stage scoreboard + comparison vs baseline
    ablation_eval.json        # graph_weight_override=0 vs default; KG_FIRST_ENABLED=false vs true
    atomic_facts.json         # for synthesis grading
    ingest.json               # any new Zettels ingested (with summarize cost log)
    kasten.json               # member node_id list snapshot
    kg_snapshot.json          # node/edge counts + usage_edges_agg row count (iter-02+)
    kg_changes.md             # Zettels added; usage-edge writes; metadata enrichment counts
    kg_recommendations.json   # advisory only — no auto-apply this run
    diff.md                   # code paths touched; commit SHAs in this iter
    improvement_delta.json    # iter-01 vs iter-06 baseline (and iter-02 vs iter-01)
    manual_review.md          # browser-flow notes, prod issues, bug repros
    next_actions.md           # carry-forward for next iter
    screenshots/              # Claude-in-Chrome screenshots of key UX states
  iter-02/                    # same shape, baseline = iter-01, no Phase 0
```

## 10. Claude-in-Chrome verification flow (per iter)

| Step | Action | Captured |
|---|---|---|
| 1 | Confirm logged-in user is Naruto (`naruto@zettelkasten.local`) | screenshot of `/home` header |
| 2 | (iter-01 only) Create new Kasten via `/home/kastens` Create button — verify the click handler now fires (Phase 0 fix), Kasten persists, member adds succeed (Phase 0 bug #2 fix) | screenshot of Kasten page; bug-fix proof |
| 3 | Open chat for the new Kasten (`/home/rag` flow) | screenshot |
| 4 | Run each gold-set query sequentially; capture answer text, citations, rerank scores via DevTools network tab → SSE response | per-query JSON appended to `answers.json` |
| 5 | Force ablation pass: in browser context, override `graph_weight=0` and re-run subset | `ablation_eval.json` |
| 6 | Note any new prod bugs surfaced; file in `manual_review.md` | bug list |

## 11. Risk & rollback strategy

| Risk | Mitigation |
|---|---|
| BGE-CE fallback latency spike (Phase 3) | Cap CE escalations to ≤2 candidates per query; budget exceeded → revert to bi-encoder top-K only |
| Gemini quota exhaustion during backfill | Backfill script respects key-pool billing escalation (commit `069eb4e`); circuit-breaks at 80% billing-key burn |
| KG-first wrong subgraph filters out gold | Env flag `RAG_KG_FIRST_ENABLED`; auto-revert if regression gate trips |
| Usage-edge weight overpowers structural signal | Sigmoid normalization caps bonus at 0.10; ablation pass measures graph_lift with weights off |
| Auto-revert leaves DB schema migrated but code reverted | All migrations are forward-additive (new columns/tables only). Old code ignores new columns — no breakage. |
| Browser flow blocked by 3rd new prod bug | Phase 0 fixes guarantee buttons work; if a 4th bug surfaces, escalate as iter-01 prereq fix; do not work around silently |

## 12. Iter-02 delta strategy

iter-02 is NOT a copy of iter-01. It refines based on iter-01 measurements:

- **Always-on:** re-run all 4 phases against iter-01 baseline; verify no regressions on AI/ML Foundations Kasten (run gold-set there too as a guard).
- **If iter-01 chunking < 70:** widen ingest enrichment (extract more entity types, more time-span granularity).
- **If iter-01 reranking < 75:** experiment with header field selection (drop low-signal fields, add chunk-position).
- **If iter-01 synthesis < 75:** tune sentence-distillation top-K and scaffold-neighbour count; consider summary-vs-chunk mix per query class.
- **If KG-first ablation shows lift > 5%:** add THEMATIC to KG-first triggers; tune expand-depth to 2.
- **If `kg_usage_edges_agg` has > 100 rows:** start using usage-weight in `graph_score` with non-zero coefficient; ablation-pass measures lift.
- **Always:** add Supabase `query_metadata_cache` write-through (the iter-01 escalation path).

iter-02 ships its own `improvement_delta.json` comparing to iter-01.

## 13. File touch list (rough)

| Phase | Files |
|---|---|
| 0 | `supabase/website/.../rag_bulk_add_to_sandbox.sql`, `website/api/routes.py`, `website/features/user_home/js/*.js`, `website/features/user_kastens/js/*.js`, `ops/requirements.txt` |
| 1 | NEW `rag_pipeline/query/metadata.py`, NEW `rag_pipeline/ingest/metadata_enricher.py`, NEW `ops/scripts/backfill_metadata.py`, EDIT `rag_pipeline/retrieval/hybrid.py`, EDIT `rag_pipeline/orchestrator.py` |
| 2 | EDIT `rag_pipeline/rerank/cascade.py`, NEW `tests/unit/rag/test_passage_text.py` |
| 3 | NEW `rag_pipeline/context/distiller.py`, EDIT `rag_pipeline/context/assembler.py`, EDIT `rag_pipeline/orchestrator.py` |
| 4 | NEW `rag_pipeline/retrieval/planner.py`, NEW migration `supabase/website/kg_public/usage_edges.sql`, NEW `ops/scripts/recompute_usage_edges.py`, NEW `.github/workflows/recompute_usage_edges.yml`, EDIT `rag_pipeline/retrieval/graph_score.py` |
| eval | NEW `docs/rag_eval/<kasten-slug>/iter-01/*`, NEW `docs/rag_eval/<kasten-slug>/iter-02/*` |

## 14. Open assumptions verified during execution

- Supabase service-role key is set as GH secret `SUPABASE_SERVICE_ROLE_KEY` (verify in iter-01 Phase 4)
- Naruto's prod data has ≥ 5 Zettels in some non-AI/ML topical cluster (verify in iter-01 step 1)
- BGE bi-encoder model is callable from Python without re-loading (verify by reading current `rag_pipeline/ingest/embedder.py`)
- `kg_features/retrieval.py` exposes (or can be extended with) `expand_subgraph(node_ids, depth) -> list[node_id]` returning all nodes within `depth` hops via `kg_links`. If absent, add via recursive CTE in iter-01 Phase 4 — keeps the single-source-of-truth boundary clean.

End of design.
