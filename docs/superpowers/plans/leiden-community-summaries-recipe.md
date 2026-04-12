# Leiden Community Summaries Migration Recipe

Trigger this parked upgrade when thematic-query `ContextRecall` stays below `0.55` for two consecutive weeks, even after query-transformation and reranker tuning.

## Migration shape

Create `supabase/website/rag_chatbot/006_communities.sql` with:

- `kg_communities(id, user_id, label, summary, embedding, created_at, updated_at)`
- `kg_community_members(community_id, node_id, user_id, created_at)`

## Build workflow

1. Pull the scoped user graph from `kg_nodes` + `kg_links`.
2. Run Leiden community detection over the weighted graph.
3. Generate one LLM summary per community from the member zettels.
4. Embed each community summary.
5. Store the summary embeddings and the membership edges.

## Retrieval integration

Extend `rag_hybrid_search` with a sixth stream over `kg_communities.embedding`, then expand matching communities back into their member nodes before reranking.

## Why it stays parked

The current v1 design uses LazyGraphRAG over retrieved subgraphs because it avoids stale offline summaries and keeps writes simple while the personal graph remains relatively small.
