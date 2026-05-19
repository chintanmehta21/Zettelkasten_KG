# Comprehensive KG & RAG Improvement Plan

## Knowledge Graph (KG) Module Enhancements

- **Split global vs. workspace edges.** Keep the existing global `compute_connection_strength` logic but store a separate *workspace-specific* strength per edge. This lets each user’s personal graph emphasize signals they can see (e.g. their own zettels and tags) without polluting it with unrelated data.  In practice, maintain a canonical edge UUID for deduplication and analytics, and a parallel workspace-specific weight for rendering.  (This mirrors modern personalization KGs that combine global and personal signals.)  
- **Add conservative pseudo-tags.** Extend the tag vocabulary to include fields like `speaker:Name`, `source_domain:youtube.com`, etc., extracted only when high confidence (e.g. explicit metadata or URL). This boosts Jaccard-style matches for media-heavy zettels without altering the core scorer formula. For example, treating a video’s channel as a tag naturally raises its similarity to other videos from the same speaker or channel.  
- **Percentile-based strength buckets.** Rather than fixed 0.55/0.7 thresholds, compute each zettel’s connection strengths percentile within its neighborhood and label edges weak/med/strong accordingly. This automatically normalizes for dense vs. sparse regions of the graph and prevents all edges from clustering just below a hard cutoff.  
- **Efficient schema design.** Move any heavy per-zettel attributes (like `source_type`, full text, or kasten stats) into separate node-attribute tables keyed by `node_id` (and optionally `workspace_id`) rather than duplicating in every edge. This keeps edge storage lean and ensures graph operations (like PageRank) only touch necessary edge/weight data.  
- **Maintain minimal per-edge data.** Store only what’s needed on edges: e.g. final strength, optional timestamp. Keep richer evidence (entity overlap, semantic score, tag match) off-edge (or in the workspace-specific table) to avoid data explosion as users grow.

### KG Visualization & UX

- **Subtle edge styling.** Use thickness and opacity to encode strength: e.g., thin/faint for weak, thick/opaque for strong edges. Avoid icons or labels that clutter the view. This aligns with best practices for interactive graphs.  
- **Toggle personal/global view.** Add a UI control to switch between the user’s personal KG and the full global graph. By default show only edges the user can see. This prevents confusion where a “strong” edge relies on nodes the user doesn’t have.  
- **Contextual tooltips.** On hover, display the connection-strength breakdown (embedding, tag, structural, temporal) for that edge. This is optional for power users to debug fuzzy links, and keeps the main view clean.  
- **Pitfalls:** Avoid heavy client-side layouts or overly complex visuals (stick to minor style tweaks). Ensure any added styling doesn’t degrade pan/zoom performance.  

## RAG Pipeline: Chunking & Ingestion

- **Fast ingest, lazy analytics.** Break the pipeline into a quick path and a background path. On zettel upload, immediately clean text, chunk, embed, and insert the node into KG/RAG with basic edges (tags, entities). Then *asynchronously* run costly steps (deep centrality, cross-zettel edges, summarization) in background jobs. This keeps UI latency low and avoids exceeding 1 GB RAM on the droplet. The existing non-blocking hook architecture can support this split.  
- **Unified canonical chunks.** Use the same chunking for both KG links and RAG retrieval. That is, store one set of canonical chunks per zettel (in e.g. `canonical_chunks` table) and reference them from KG edges *and* the RAG index. This avoids double chunking and ensures that “chunks” match between visualization and search results.  
- **Contextual and variable chunking.** Apply advanced chunking only where needed: e.g. semantic or LLM-based chunking for long transcripts or articles, simple sentence splits for short notes. Consider **late-chunking** for very long docs, where an LLM embeds the full text and then segments (as suggested by Late-Chunking research). After retrieval, perform **chunk expansion**: always fetch neighboring chunks for each hit so the model sees more context. Pinecone’s best practices note this guards against too-small chunks.  
- **Pitfalls:** Do not recompute embeddings twice for RAG vs KG. Do not run full graph analytics during synchronous ingest (background it instead). Ensure your chunking logic is deterministic so test expectations hold.  

## RAG Pipeline: Retrieval & Fusion

- **Query-type–adaptive retrieval.** Instead of fixed dense/sparse weights, use query-class and simple features (length, presence of quotes/IDs) to adjust fusion strategy. For example: short exact-match queries favor BM25; entity-rich queries use the KG to seed scope; vague questions use dense embeddings with broad expansion. This matches patterns from Adaptive-RAG and GraphRAG.  
- **Hybrid fusion with RRF.** Fuse dense and sparse results using Reciprocal Rank Fusion (or weighted sums) rather than manual weighting. RRF has been shown to consistently improve relevance over any single method. Start with α-blending (as in Weaviate’s hybrid search) but allow the mixing weight to change per query.  
- **Lightweight entity anchoring.** Re-enable entity-anchor query narrowing, but conservatively: only for high-confidence entities (author names, explicit tags). Use the KG’s adjacency to limit scope *if needed*, then fall back if no results. This often helps multi-hop questions without always invoking the full KG path.  
- **Pitfalls:** Don’t over-tune fusion; keep BM25 around as a fallback (BEIR shows BM25 is robust). Avoid a heavy LTR model given compute limits; simple RRF with tuned weights is safer. Ensure KG-first narrowing never blocks retrieval (always widen if empty).  

## Reranking & Diversity

- **Graph-aware reranking features.** Include KG signals in your second-stage ranker. For example, add features like “belongs to the same KG community as the top hits” or “node centrality rank” to the reranker input. This softly boosts supporting evidence from graph context.  
- **Query-class reranker calibration.** Train or tune reranking specifically per query type: e.g. strongly favor exact evidence for LOOKUP queries, but allow more distant inference for THEMATIC queries. Cohere’s docs show reranking works on any candidate list, so you can tailor the input representation (e.g. “doc snippet + metadata”) per case.  
- **Top-k diversity.** When assembling the final context set, enforce diversity: penalize adding multiple chunks from the same zettel (or same KG community) if other high-scoring zettels exist. This guards against “one zettel dominates” answers. A simple approach is to require new candidates come from at least one new neighbor or to re-score with a diminishing boost for repeated zettels.  
- **Pitfalls:** Don’t rely on huge cross-encoders: limit your rerank k to ~20–30 to stay within hardware. Avoid filtering *only* by Pagerank or centrality – use them as features. Maintain some lexical bias so short queries still get precise matches.  

## Synthesis & Style-Aware Generation

- **Kasten-level style stats.** Compute and store per-kasten summaries (e.g. dominant source types, average length, top topics) as a compact `kasten_stats`. Use these stats to guide answer style: e.g. encourage bullet lists if the kasten is news/tweets-heavy, or a narrative if it’s essays/videos-heavy. Contextual AI and other RAG products suggest conditioning answers on user preferences.  
- **Prompt conditioning by profile.** In your system prompts, mention the user’s preference gleaned from `kasten_stats` (e.g. “User prefers concise answers” or “Use detailed reasoning style”). Keep this hint light so it doesn’t override factual content.  
- **Ensure citation coverage.** Extend citation heuristics so that if few top chunks are cited, prompt the model (or retry) to reference additional sources. CRAG’s strategy of retrieval evaluation suggests re-querying if support is thin. For example, if the final answer cites ≤1 zettel, you might automatically pull more from the next-best candidates.  
- **Pitfalls:** Don’t overburden your model with personality – keep extra instructions minimal. Avoid storing large per-user profiles; `kasten_stats` should be small JSON of a few fields.  

## Overfitting & Evaluation Strategy

- **Multi-Kasten benchmarks.** Always evaluate on ≥2 distinct kastens (e.g. one transcript-heavy, one metadata-heavy). Only accept changes that improve the composite score (or at least no worse) on *both* sets. BEIR-style holdouts ensure you’re not just tuning to one scenario.  
- **Hold-out queries.** Reserve a few questions in each kasten as an unseen test set. Tune on the rest and check final gains on the hold-out. This prevents “tuning on the test questions.”  
- **Perturbation tests.** Generate paraphrased or slightly altered versions of key queries to test robustness. If performance drops sharply on synonyms/wording changes, your system is overfitted.  
- **A/B testing for big changes.** For any major new feature (e.g. enabling entity anchors), compare the old vs. new pipeline on the same queries and zettels to quantify impact on the composite score.  

## Key Takeaways

- **Adaptive retrieval & fusion:** All evidence points to making the system adapt to query type. Hybrid search with tuned RRF and occasional KG-based rerouting consistently beats any fixed regime.  
- **Align KG to user:** Store personal edge weights and pseudo-tags for user-specific graph signals, while keeping the global graph separate. Subtle visual cues (thickness/opacity) communicate strength without clutter.  
- **Lightweight vs. heavy paths:** Keep the 1 GB droplet happy by backgrounding heavy steps (graph analytics, large-context LLM queries) and limiting active rerankers to ~20–30 candidates. Monitor latencies and memory closely.  
- **Rigor in evaluation:** Use the limited zettels to create a diverse testbed (cross-kasten, hold-outs, perturbations). Optimize for gains across scenarios, not just peak on one. BEIR teaches us BM25 plus rerank is hard to beat zero-shot, so always preserve strong lexical baselines.  

By integrating these improvements—grounded in industry standards (Google/Anthropic style RAG, Azure Search best practices, etc.) and recent research (GraphRAG/LazyGraphRAG, HippoRAG, RAPTOR, CRAG, Late-Chunking)—your KG and RAG modules will become more nuanced and robust without adding prohibitive cost. Each suggestion above is pragmatically chosen to fit the Zettelkasten context and the droplet’s limits, with careful attention to potential side effects and necessary monitoring. Implementing them should push your composite score well above 80 (and toward the 90 soft target) across **multiple** types of kastens, not just the ones in the current data.  

**References:** The recommendations above draw on recent RAG and KG literature and best practices. For example, Anthropic’s *Contextual Retrieval* shows how augmenting chunks with context and BM25 drastically cuts retrieval failures; Microsoft’s GraphRAG and LazyGraphRAG highlight query-driven graph traversal and deferred LLM use; Pinecone and Weaviate docs explain modern chunking and hybrid search strategies; and survey/benchmark papers (BEIR, CRAG, HippoRAG) emphasize hybrid/RRF fusion, cross-encoder reranking, and KG signals for grounding. These inform the prioritized improvements above.