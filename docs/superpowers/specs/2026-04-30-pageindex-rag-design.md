# PageIndex RAG Design

Date: 2026-04-30
Status: Approved for implementation planning

## Goal

Build `PageIndex_Rag` as a replacement-grade experimental RAG system that can run alongside the current `website/features/rag_pipeline` implementation. The system should trust PageIndex where it already fits, especially Markdown tree indexing, while keeping this app's production architecture, multi-user boundaries, Gemini key routing, metrics, and evaluation discipline intact.

The initial target is CLI-first testing behind feature flags. Web UI exposure is explicitly out of scope until PageIndex RAG proves quality, latency, memory, citation behavior, and production readiness against the current RAG baseline.

## Research Summary

PageIndex is a tree-indexed, reasoning-oriented retrieval system. It converts documents into a hierarchical structure, then uses LLM-guided tree navigation and tight page or section reads instead of relying only on vector chunk retrieval.

Relevant PageIndex references:

- Getting started: https://docs.pageindex.ai/getting-started
- Python SDK overview: https://docs.pageindex.ai/sdk
- Document processing SDK: https://docs.pageindex.ai/sdk/tree
- Chat API: https://docs.pageindex.ai/sdk/chat
- MCP integration: https://docs.pageindex.ai/mcp
- Endpoints: https://docs.pageindex.ai/endpoints
- Pricing: https://docs.pageindex.ai/pricing
- Open-source repo: https://github.com/VectifyAI/PageIndex

The cloud SDK shape and open-source repo shape differ. The cloud docs expose API methods such as `submit_document`, `get_document`, `get_tree`, and `chat_completions`. The open-source repo exposes local `PageIndexClient.index()`, `get_document_structure()`, and `get_page_content()`, with Markdown support through `md_to_tree`. Because this project needs self-hosted behavior, the first implementation should use the open-source PageIndex path behind a local adapter.

Dependency contract: pin PageIndex to an exact PyPI version or git SHA during implementation planning. Before feature work, verify the local self-hosted API shape in a smoke test: `PageIndexClient(workspace=...)`, `index(markdown_path, mode="md")`, `get_document()`, `get_document_structure()`, and `get_page_content()`. Do not track an unpinned main branch.

## Non-Goals

- Do not replace the production RAG route by default.
- Do not expose PageIndex RAG in the web UI until evaluation passes.
- Do not introduce PageIndex Cloud as the default path.
- Do not make OpenAI-compatible credentials the primary provider strategy.
- Do not fork or vendor PageIndex immediately unless direct import fails a concrete production requirement.

## Core Decisions

1. Self-hosted PageIndex first.
   Use the open-source PageIndex package locally and keep document data off PageIndex Cloud.

2. Import-first, not rewrite-first.
   Trust PageIndex's Markdown indexing and retrieval where it fits. Vendor or reimplement only if import blocks Gemini key-pool routing, async safety, workspace isolation, memory limits, citation mapping, or replacement-grade evaluation.

3. One zettel per PageIndex document.
   Each `kg_nodes` row becomes one deterministic Markdown document. PageIndex indexes that document as its own tree.

4. Full-KG and scoped RAG both matter.
   Match the current RAG shape: one system can ask across the full Zettel system, and another can be created from multiple selected zettels, analogous to current sandbox/scoped RAG.

5. Gemini key pool remains the default model strategy.
   All PageIndex indexing, tree-summary, retrieval-planning, and answer-generation model calls must route through the existing Gemini key pool by default. OpenAI-compatible or `litellm` paths are allowed only as non-production compatibility shims or explicit test overrides, not as the production provider model.

6. Three answer candidates.
   The answer stage synthesizes three independent cross-zettel answers with citations. CLI output should expose all three and their metrics. Evaluation should score each answer and optionally best-of-three, critic-selected, or merged variants.

## Proposed Folder

Create:

```text
website/experimental_features/PageIndex_Rag/
```

The folder should start as an experimental feature boundary. Initial implementation modules should be added only after implementation planning.

Expected eventual structure:

```text
PageIndex_Rag/
  __init__.py
  config.py
  types.py
  markdown/
    renderer.py
  index/
    workspace.py
    pageindex_adapter.py
    sync.py
  retrieval/
    candidate_selector.py
    tree_search.py
    evidence.py
  generation/
    answer_set.py
    prompts.py
  api/
    routes.py
  cli/
    query.py
    backfill.py
  evaluation/
    runner.py
    metrics.py
  observability/
    metrics.py
    tracer.py
```

## Architecture

### 1. Markdown Rendering

Render every zettel from `kg_nodes` into deterministic Markdown:

- Title as H1.
- Source URL, source type, author/date when available.
- Tags.
- Summary.
- Full captured/extracted content when available.
- Existing metadata needed for citations.
- Stable source markers so citations can map back to `node_id`, source URL, and section.

Because self-hosted PageIndex Markdown mode builds structure from Markdown headings, the renderer must emit exactly one H1, deterministic metadata headings, and normalized section headings. Raw extracted content must be nested under a stable heading, and any embedded headings must be demoted, escaped, or fenced so they cannot corrupt the zettel tree.

Renderer output must be content-addressed. The index key should include:

- `user_id`
- `node_id`
- `content_hash`
- renderer version

If content and renderer version are unchanged, indexing should be skipped.

### 2. Local PageIndex Workspace

Use a controlled app workspace rather than PageIndex's default demo workspace. The workspace must isolate users and avoid filename collisions:

```text
<configured_pageindex_workspace>/<user_id>/<node_id>/<content_hash>/
```

Persist:

- Rendered Markdown file.
- PageIndex document JSON.
- Tree snapshot.
- Metadata mapping from `node_id` to PageIndex `doc_id`.
- Index status and last indexed timestamp.

Workspace writes need file locks or equivalent atomic write discipline so concurrent backfills and queries cannot corrupt JSON.

### 3. PageIndex Adapter

Wrap direct PageIndex imports behind an internal adapter:

```python
class PageIndexAdapter:
    index_markdown(...)
    get_document(...)
    get_document_structure(...)
    get_page_content(...)
```

The rest of `PageIndex_Rag` should not call PageIndex directly. This keeps the replacement path flexible if PageIndex internals need patching later.

### 4. Candidate Selection

Because one zettel is one PageIndex document, cross-zettel QA needs a candidate selection layer before tree retrieval.

Initial candidate selector should support:

- Full-KG query over all indexed zettels for a user.
- Scoped query over explicit node IDs or sandbox-like sets.
- Metadata-aware filtering by tags, source types, and node IDs.
- A cheap first-pass score using zettel title, tags, summary, source type, and PageIndex tree summaries when available.

Scoped RAG must support an explicit `PageIndexRagScope` with `scope_id`, `user_id`, `node_ids`, `membership_hash`, optional name, TTL/expiry for temporary scopes, and persisted-scope mode for reusable multi-zettel systems. Scope membership must be user-isolated and must not duplicate PageIndex documents unnecessarily.

Candidate selection can initially reuse current Supabase metadata. Current RAG signals may be used only for comparison, ablation, or shadow diagnostics. Replacement-readiness scoring must include a PageIndex-only candidate-selection mode that does not call `rag_pipeline` retrieval, rerank, or context assembly.

### 5. Tree-Guided Evidence Retrieval

For each selected candidate zettel:

1. Load PageIndex tree.
2. Ask the retrieval model which tree nodes are relevant to the query.
3. Fetch tight content ranges from the selected zettel.
4. Normalize evidence into a common `EvidenceItem` model.

Self-hosted retrieval must follow the local PageIndex tool protocol: `get_document` -> `get_document_structure` without text -> choose node IDs or line ranges -> `get_page_content` using Markdown line-number ranges. Do not depend on PageIndex Cloud `chat_completions`, MCP, or `enable_citations` for local retrieval.

Evidence items must carry:

- `node_id`
- PageIndex document ID
- zettel title
- source URL
- tags
- section title or line range
- quoted or summarized evidence text
- retrieval score and reasoning metadata

### 6. Three-Answer Generation

Generate three citation-grounded answers from the gathered evidence.

The three answers should be deliberately useful alternatives, not three random samples. Candidate variants can be:

- Direct answer: concise synthesis.
- Comparative answer: emphasizes tradeoffs, disagreement, and cross-source relationships.
- Exploratory answer: surfaces less obvious connections and follow-up questions.

Each answer must cite the zettels/evidence it used. The CLI should show all three answers and their per-answer metrics. Later production UI can choose whether to show all three, select one through a critic, or merge them.

### 7. Feature-Flagged CLI and API

Add feature flags before any runnable path:

- `PAGEINDEX_RAG_ENABLED`
- `PAGEINDEX_RAG_WORKSPACE`
- `PAGEINDEX_RAG_MODE=local`

Testing path:

1. CLI command for indexing/backfill.
2. CLI command for querying PageIndex RAG.
3. Hidden API route only for local/CLI testing.
4. No web UI entrypoint until evaluation passes.

The hidden API route must be disabled by default, require `PAGEINDEX_RAG_ENABLED=true` and `PAGEINDEX_RAG_MODE=local`, be guarded for CLI/admin/local-only access, and never be linked from or mounted into public web UI flows before evaluation approval.

### 8. Metrics and Observability

Treat this as a candidate replacement. It must report metrics comparable to current RAG:

- End-to-end latency.
- Per-stage latency: render, index, candidate selection, tree retrieval, evidence assembly, generation.
- RSS memory before/after heavy stages.
- Number of candidate zettels inspected.
- Number of PageIndex trees loaded.
- Evidence token/character counts.
- Gemini key-pool usage and fallback behavior.
- Cache hit/miss rates.
- Index freshness.
- Error/degradation reason.

### 9. Evaluation

Evaluate against the current RAG baseline using existing fixtures where possible:

- Golden QA.
- Cross-source retrieval.
- Scoped/sandbox-style retrieval.
- Conflict resolution.
- Empty-scope and no-evidence refusals.
- Citation correctness.
- Faithfulness/groundedness.
- Answer quality.
- Latency.
- RSS memory and peak stage memory.
- Backfill/index throughput.

Because the system generates three answers, evaluation should record:

- Per-answer scores.
- Best-of-three score.
- Critic-selected score, if a critic is added.
- Merged-answer score, if merging is added later.

Reuse or mirror the current `website/features/rag_pipeline/evaluation` output schema where possible: component scores, per-query scores, retrieved node IDs, reranked node IDs, cited node IDs, RAGAS/DeepEval sidecars, latency p50/p95, and explicit retrieval/rerank formulas such as Recall@k, MRR, Hit@k, NDCG@k, Precision@k, and false-positive rate.

## Error Handling

The PageIndex path must degrade cleanly:

- Missing index: index on demand only if allowed, otherwise return an explicit not-indexed error.
- Corrupt workspace JSON: quarantine and reindex that zettel.
- PageIndex import failure: feature reports unavailable; current RAG remains unaffected.
- Gemini key-pool exhaustion: return structured degraded response.
- Scope resolves to zero zettels: return an explicit empty-scope response.
- No evidence found: return a grounded refusal, not a fabricated answer.

## Testing Plan

Initial tests:

- Markdown renderer determinism and metadata coverage.
- One zettel indexes into PageIndex and returns a tree.
- Content hash skip behavior.
- Workspace isolation across users and node IDs.
- Concurrent index attempts for the same zettel.
- Full-KG candidate selection over multiple zettels.
- Scoped candidate selection over selected zettels.
- Three-answer generation shape and citations.
- Empty evidence refusal.
- PageIndex import unavailable behavior.

Replacement-readiness tests:

- Compare current RAG vs PageIndex RAG on golden QA fixtures.
- Compare current RAG vs PageIndex RAG on cross-source queries.
- Measure RSS memory during indexing and query.
- Stress query concurrency.
- Backfill many zettels without workspace corruption.

## Open Implementation Risks

- PageIndex's local API may require OpenAI-compatible `litellm` behavior. If Gemini key pool cannot be integrated cleanly through configuration, the adapter may need targeted patching or a small vendored model-call layer.
- PageIndex tree retrieval is document-native; our replacement path needs robust cross-document candidate selection.
- One zettel may be short enough that PageIndex tree retrieval adds overhead without much quality benefit. Evaluation must prove whether structure beats current chunk retrieval for summaries.
- Workspace JSON persistence must be hardened for concurrent production-like use.
- Three-answer generation increases model cost and latency; CLI testing should measure this explicitly.

## Approval Status

Approved architecture:

- Self-hosted PageIndex.
- Import PageIndex directly where it fits.
- One zettel per PageIndex document.
- Full-KG and scoped multi-zettel RAG.
- Existing Gemini key pool as default provider strategy.
- Feature-flagged CLI/API testing before web UI exposure.
- Replacement-grade memory and RAG metrics.
- Three cross-zettel answers with citations.
