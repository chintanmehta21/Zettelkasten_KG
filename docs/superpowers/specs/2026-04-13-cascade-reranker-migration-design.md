# Cascade Reranker Migration Design

**Date:** 2026-04-13
**Status:** Approved
**Goal:** Replace BGE-reranker-v2-m3 TEI sidecar with an in-process FlashRank → BGE-base ONNX INT8 cascade to reduce deploy latency, runtime latency, and memory footprint without losing reranking quality.

---

## 1. Context & Problem

The current RAG pipeline uses `BAAI/bge-reranker-v2-m3` (568M params, ~2.2GB) running in a HuggingFace TEI Docker sidecar (`ghcr.io/huggingface/text-embeddings-inference:cpu-1.9`). This causes:

- **~10min deploy latency** (TEI image pull + model download + warmup)
- **~300ms rerank latency** per query (30-50 candidates over HTTP)
- **2.8GB total RAM** (2048MB reranker + 768MB app)
- **Operational complexity**: two containers, inter-container networking, health check dependency chain

The reranker contributes 60% of the final ranking signal via score fusion (`0.60 * rerank + 0.25 * graph + 0.15 * rrf`). Content is unpredictable — YouTube transcripts, Reddit posts, GitHub READMEs, newsletters, multilingual X posts — so quality must be robust across all source types.

### Current Architecture

```
┌──────────────┐    HTTP POST     ┌─────────────────────────┐
│  App (768MB)  │ ──────────────> │  TEI Sidecar (2048MB)   │
│  TEIReranker  │ <────────────── │  bge-reranker-v2-m3     │
│               │   JSON scores   │  568M params, ~2.2GB    │
└──────────────┘                  └─────────────────────────┘
     Total: 2.8GB RAM, 2 containers, ~10min deploy
```

### Target Architecture

```
┌──────────────────────────────────────────────┐
│  App (~1024MB)                               │
│                                              │
│  CascadeReranker                             │
│  ┌────────────────────┐                      │
│  │ Stage 1: FlashRank │ MiniLM-L-12 (34MB)  │
│  │ N candidates → 15  │ ~15ms               │
│  └────────┬───────────┘                      │
│           ▼                                  │
│  ┌────────────────────┐                      │
│  │ Stage 2: BGE-base  │ ONNX INT8 (~280MB)  │
│  │ 15 candidates → k  │ ~25-40ms            │
│  └────────────────────┘                      │
│                                              │
│  Models: /opt/zettelkasten/data/models/      │
│  (host-mounted, freshness-checked on deploy) │
└──────────────────────────────────────────────┘
     Total: ~1GB RAM, 1 container, ~2min deploy
```

---

## 2. Design Decisions

### Always-Cascade (no conditional gating)

Every query runs both stages sequentially. No score-spread threshold, no query-class routing. At ~40-60ms total, the always-cascade approach is still 5-7x faster than current and guarantees consistent quality across all content types regardless of input distribution.

### Host-Mounted Volume with Freshness Checks

Models stored at `/opt/zettelkasten/data/models/` (host volume, persists across deploys). On app startup, `ModelManager` compares cached model etag/sha256 against HuggingFace Hub — re-downloads only if a newer version exists. This ensures model improvements propagate automatically without manual intervention. Freshness check is async and non-blocking — app starts immediately with cached models, background task handles updates.

### In-Process via ONNX Runtime (no PyTorch)

Both models run on `onnxruntime` (CPU). No PyTorch, no `transformers` library at inference time. Total new dependency footprint: ~100MB (`flashrank` + `onnxruntime`) vs 2.5GB TEI sidecar removed.

---

## 3. Component Design

### 3.1 CascadeReranker (`website/features/rag_pipeline/rerank/cascade.py`)

Replaces `TEIReranker` with the same interface:

```python
class CascadeReranker:
    async def rerank(
        self,
        query: str,
        candidates: list[RetrievalCandidate],
        top_k: int = 8,
    ) -> list[RetrievalCandidate]:
```

**Pipeline:**
1. Stage 1: FlashRank `ms-marco-MiniLM-L-12-v2` scores all candidates, keeps top `stage1_k` (default 15)
2. Stage 2: BGE-reranker-base ONNX INT8 reranks `stage1_k` candidates, populates `rerank_score`
3. Score fusion: `final_score = 0.60 * rerank_score + 0.25 * graph_score + 0.15 * rrf_score`
4. Return top `top_k` sorted by `final_score`

**Graceful degradation chain:**
- Stage 2 fails → use Stage 1 scores for fusion, log degradation event
- Stage 1 also fails → fall back to RRF-only (identical to current HTTP error fallback)
- All degradation events logged to `degradation_events.jsonl` (see Section 3.3)

**Threading:** FlashRank and ONNX inference are CPU-bound sync calls. Wrapped in `asyncio.to_thread()` to avoid blocking the event loop.

### 3.2 ModelManager (`website/features/rag_pipeline/rerank/model_manager.py`)

Handles download, caching, and freshness for both models.

**Startup behavior:**
1. Check if models exist at `RAG_MODEL_DIR` (env var, default `/opt/zettelkasten/data/models/`)
2. If cached models exist → load immediately, app starts
3. In background: compare cached etag against HuggingFace Hub
4. If newer version detected → download to temp dir, atomic swap
5. If HF Hub unreachable + cache exists → use cached, log warning
6. If HF Hub unreachable + no cache → raise `RerankerUnavailable`

**Models managed:**
- `flashrank/ms-marco-MiniLM-L-12-v2` (~34MB)
- `BAAI/bge-reranker-base` ONNX INT8 variant (~280MB)

### 3.3 Degradation Telemetry (`website/features/rag_pipeline/rerank/degradation_log.py`)

When the cascade falls back (either stage fails), appends a structured JSON record to `RAG_MODEL_DIR/degradation_events.jsonl`:

```json
{
  "timestamp": "2026-04-13T14:30:00Z",
  "query_hash": "sha256:abc123...",
  "candidate_count": 42,
  "failed_stage": "stage2",
  "exception_type": "OnnxRuntimeError",
  "exception_message": "...",
  "content_length_stats": {"min": 12, "max": 3800, "mean": 450},
  "source_types": ["youtube", "reddit", "web"]
}
```

- Query content is hashed (SHA-256), never stored raw — privacy safe
- Append-only JSONL — reviewable audit trail for architecture evolution
- Periodic inspection reveals patterns (e.g., "Stage 2 fails on multilingual batches")

### 3.4 Configuration

**New env vars:**
- `RAG_MODEL_DIR` — model storage path (default: `/opt/zettelkasten/data/models/`)
- `RAG_RERANKER_BACKEND` — `cascade` (default), future: `flashrank-only`, `bge-only`
- `RAG_CASCADE_STAGE1_K` — Stage 1 output size (default: `15`)

**Removed env vars:**
- `RAG_RERANKER_URL` — no longer needed (no sidecar)

---

## 4. Docker & Deployment Changes

- Remove `reranker` service block entirely from `docker-compose.blue.yml` and `docker-compose.green.yml`
- Remove `depends_on: reranker: condition: service_healthy` from app service
- Bump app `mem_limit` from `768m` to `1024m` (and `memswap_limit` to match)
- Add host volume mount: `/opt/zettelkasten/data/models:/app/models:rw` (writable for model downloads)
- Add `RAG_MODEL_DIR: "/app/models"` to environment block, remove `RAG_RERANKER_URL`
- Add `flashrank` and `onnxruntime` to `ops/requirements.txt`
- Deploy script gets a one-time model bootstrap: if `/opt/zettelkasten/data/models/` is empty, pre-download both models before starting containers

---

## 5. Test Suite

### 5.1 Unit Tests (`tests/unit/rag/rerank/`)

**`test_cascade.py`** — core cascade behavior:
- Empty candidates returns `[]`
- Stage 1 filters candidates down to `stage1_k`
- Stage 2 reranks Stage 1 output and populates `rerank_score`
- Final score fusion uses `0.60/0.25/0.15` weights
- Graceful degradation: Stage 2 failure → uses Stage 1 scores
- Graceful degradation: both stages fail → falls back to RRF-only
- `top_k` and `stage1_k` configuration respected

**`test_model_manager.py`** — freshness and download logic:
- Loads models from existing cache dir (no network call)
- Detects stale model via etag mismatch → triggers re-download
- HF Hub unreachable + cache exists → uses cached model, logs warning
- HF Hub unreachable + no cache → raises `RerankerUnavailable`
- Background refresh doesn't block app startup

### 5.2 Edge-Case Tests (`tests/unit/rag/rerank/test_cascade_edge_cases.py`)

- **Content length extremes:** single-word zettel, 4000-char truncation boundary, empty `content` field
- **Source type diversity:** YouTube transcript chunk (long, conversational), Reddit post (short, informal, slang/emoji), GitHub README (code-heavy, backticks/markdown), Newsletter (formal, long-form), Generic web (mixed HTML artifacts)
- **Multilingual input:** non-English zettel content (Chinese, Hindi, mixed-language) — verifies cascade doesn't crash, scores are valid floats, ordering is deterministic
- **Score distribution edge cases:** all candidates have identical RRF scores, all candidates have zero graph scores, single candidate (no ranking needed), exactly `stage1_k` candidates (Stage 1 is a no-op pass-through)
- **Candidate count boundaries:** fewer candidates than `stage1_k` (Stage 1 passes all through), fewer candidates than `top_k` (returns all), exactly 1 candidate, 100+ candidates (stress test)

### 5.3 End-to-End Test (`tests/unit/rag/rerank/test_cascade_e2e.py`)

Replaces `test_tei_client.py` entirely (old file deleted):
- Wires `CascadeReranker` into a mock orchestrator pipeline: retriever → graph scorer → cascade reranker → assembler
- Verifies the full flow produces ranked candidates with valid `rerank_score`, `graph_score`, `final_score`
- Verifies `service.py` factory correctly instantiates `CascadeReranker` instead of `TEIReranker`
- Verifies score ordering is consistent across repeated runs (determinism check)

### 5.4 Degradation Telemetry Tests (`tests/unit/rag/rerank/test_degradation_log.py`)

- Verifies records are written on Stage 2 failure and both-stage failure
- Verifies JSONL is append-only and parseable
- Verifies query content is hashed, not stored raw

### 5.5 Integration Test (`tests/integration_tests/test_cascade_live.py`)

- Marked `@pytest.mark.live`, loads real models
- Reranks real candidates across all source types
- Verifies score ordering is sane

### 5.6 Existing Test Updates

- Delete `test_tei_client.py` (replaced by `test_cascade_e2e.py`)
- Update `test_orchestrator.py` — mock `CascadeReranker` instead of `TEIReranker`
- Update `test_rag_api_routes.py` — mock `CascadeReranker` instead of `TEIReranker`

---

## 6. Expected Impact

| Metric | Before | After |
|---|---|---|
| Deploy time | ~10 min | ~2 min |
| Rerank latency (p50) | ~300 ms | ~40-60 ms (5-7x faster) |
| Docker containers | 2 (app + reranker) | 1 (app only) |
| Total RAM | 2.8 GB (768MB + 2048MB) | ~1 GB |
| Model disk footprint | ~2.2 GB (v2-m3) | ~314 MB (34MB + 280MB) |
| New dependencies | TEI Docker image (~2.5GB) | flashrank + onnxruntime (~100MB pip) |
| Reranking quality | Baseline (v2-m3, 51.8 NDCG) | ~95-99% via cascade |
| Operational complexity | 2 containers, health checks, networking | 1 container, in-process |

---

## 7. Files Changed

**New files:**
- `website/features/rag_pipeline/rerank/cascade.py`
- `website/features/rag_pipeline/rerank/model_manager.py`
- `website/features/rag_pipeline/rerank/degradation_log.py`
- `tests/unit/rag/rerank/test_cascade.py`
- `tests/unit/rag/rerank/test_cascade_edge_cases.py`
- `tests/unit/rag/rerank/test_cascade_e2e.py`
- `tests/unit/rag/rerank/test_degradation_log.py`
- `tests/unit/rag/rerank/test_model_manager.py`
- `tests/integration_tests/test_cascade_live.py`

**Modified files:**
- `website/features/rag_pipeline/rerank/__init__.py` — export `CascadeReranker`
- `website/features/rag_pipeline/service.py` — swap `TEIReranker` → `CascadeReranker`
- `ops/requirements.txt` — add `flashrank`, `onnxruntime`
- `ops/docker-compose.blue.yml` — remove reranker service, bump app memory, add model volume
- `ops/docker-compose.green.yml` — same changes as blue
- `tests/unit/rag/test_orchestrator.py` — update reranker mocks
- `tests/test_rag_api_routes.py` — update reranker mocks

**Deleted files:**
- `website/features/rag_pipeline/rerank/tei_client.py`
- `tests/unit/rag/rerank/test_tei_client.py`
