# Zettelkasten_KG RAG + Knowledge Graph Deep-Dive and Improvement Plan

## 1. Current eval history and iter-12 scope

The latest completed eval documents for the "Knowledge Management & Personal Productivity" Kasten are under `docs/rag_eval/common/knowledge-management/iter-10..iter-12`.  
iter-11 `scores.md` reports composite 60.26 with stage scores chunking 40.43, retrieval 64.26, reranking 52.45, and synthesis 65.92 using the old weights, and gold@1 unconditional 0.6154 and within_budget_rate 0.5.  
iter-12 `RESEARCH.md` explains that iter-12’s goal is composite ≥ 85 under new trust‑first weights and accuracy_user_visible ≥ 0.85, with focus on infra stability, router reliability, dynamic thresholds, and scoring correctness rather than changing the user‑visible KM Kasten corpus.

The iter-12 research doc also diagnoses iter-11’s dominant failure mode as synchronous Supabase RPCs blocking the asyncio loop on a 1‑vCPU droplet, causing burst 502s and one OOM during eval, and introduces Class P (PATH_F) using `asyncio.to_thread`, a sized thread pool, a global semaphore, and httpx pool tuning to fix this.  
It further introduces K3 confidence-gap thresholds, K4 per‑Kasten magnet bootstrap, Q3/Q5/Q7 correctness fixes for refusal and routing, S/W scoring changes, and notes that entity-anchor resolvers and anchor bandit are in play but some NLI‑based monitors (D3) and LLM gazetteer replacement (K6) are explicitly deferred to iter‑13.

For your purposes, the important implication is that the RAG pipeline foundations (PATH_F, router, confidence-gap, magnet metrics, composite) are already modernized and tuned for the KM benchmark, so remaining gaps are mostly: (a) KG quality and representation, (b) KG↔RAG integration and personalization, and (c) generalization beyond the KM Kasten under your user/workspace/Kasten constraints.


## 2. High-level architecture of the three modules

### 2.1 rag_pipeline feature

The `website/features/rag_pipeline` package contains the full online RAG stack: query routing, retrieval (dense/sparse/graph), reranking, critique, and answer synthesis, plus ingest and evaluation helpers.  
Key subpackages include `retrieval` (hybrid search, anchor resolve, graph score), `rerank`, `query` (router and query typing), `context` and `generation`, `critic`, `observability`, and `evaluation`, orchestrated by `orchestrator.py` and exposed via `service.py` to the FastAPI layer.

The iter-12 research doc lists 12 RPC call sites in `retrieval` (hybrid, chunk_share, kasten_freq, graph_score, entity_anchor, anchor_seed) and shows that anchor‑boost and seed‑injection are controlled by flags but are now on by default after PATH_F.  
Router behavior is governed by a hybrid of deterministic regex and an LLM router with few‑shot prompt, with short‑vague patterns ("anything about ...") overridden by a VAGUE discovery regex and then fed into the VAGUE/THEMATIC transformer branches.

### 2.2 knowledge_graph feature

The `website/features/knowledge_graph` directory contains a static HTML+JS front-end that renders a force-directed graph of nodes and edges for the user’s Zettels.  
The `content/graph.json` file is a JSON representation of the KG nodes and links, and iter‑12 EXEC_PLAN notes that this file storage path is now considered legacy since v2’s DB schema is the source of truth; in production the write path is currently blocked by a read‑only mount, with `_persist_file_node` catching OSError and marking `file_saved=False`.

The JS code (e.g. `js/graph.js`) uses D3-style visualization with per‑edge attributes (strength, etc.), which is where connection_strength tiers (strong/medium/weak) can be mapped into visual properties such as stroke width and opacity without changing KG semantics.  
The KG front-end treats all nodes in a workspace as one graph, and personal graphs are understood as workspace‑scoped subsets, which matches your requirement that personal KG edges should not be driven solely by global connections invisible to the current workspace.

### 2.3 kg_features feature

The `website/features/kg_features` package encapsulates feature extraction, scoring, and analytics for KG connections.  
`embeddings.py` is responsible for computing dense representations for zettels and potentially tags, `scoring.py` houses the connection scoring logic (e.g. Jaccard or hybrid scores over tags, titles, and other metadata), and `analytics.py` computes aggregate metrics like degree distributions, centrality, or similarity distributions to support KG introspection and monitoring.

The current connection_strength appears to be computed from a combination of content similarity and metadata overlap with global weights, and the feature layer exposes strong/medium/weak tiers as derived from a scalar score but does not yet differentiate global and per‑workspace calibration or store per‑workspace overrides in a structured way.  
Tags today are simple strings without pseudo-tag expansion such as `speaker:...` or `source_domain:...`, so KG similarity is not yet leveraging full rich URL/intake metadata that your ingestion stack has access to.


## 3. Industry patterns for RAG + KG pipelines (last 5 years)

### 3.1 Chunking best practices

Recent RAG references emphasize that chunk size is a primary lever for retrieval quality, and recommend 250–500 tokens with 50–100 token overlaps as a robust default, with semantic or hierarchical chunking preferred over naive fixed‑size splits for long documents.[^1][^2]
GraphRAG and similar systems add graph-aware late chunking, where entities and citation graphs inform chunk boundaries to keep strongly connected concepts together and to avoid splitting key passages across multiple chunks.[^3][^1]

Redis’s 2026 chunking guide notes that smaller chunks (<200 tokens) tend to improve precision but hurt recall and synthesis coherence, whereas larger chunks (>800 tokens) increase recall but degrade reranker and LLM efficiency; it suggests starting with 400–600 tokens for long-form content and shrinking only when retrieval proves too coarse.[^2]
GraphRAG guidance stresses semantic chunking based on embedding similarity between consecutive sentences, using boundaries where cosine distance spikes, which your system could approximate by offline embedding-based segmentation during ingest rather than online.[^1]

### 3.2 Hybrid dense/sparse retrieval and query-adaptive mixing

Industry practice since 2024 is to combine BM25-like sparse retrieval with dense vector retrieval rather than relying solely on one.[^4][^5]
Hybrid retrieval commonly uses sparse retrieval for initial candidate generation and dense retrieval for semantic reranking, or vice versa, with query-dependent weighting and sometimes multiple rounds of reweighting based on uncertainty.[^6][^5]

Recent research on dynamic hybrid retrieval uses entropy over score distributions to adapt weights between sparse and dense per query: if the sparse distribution has low entropy (few strong lexical matches), sparse weight increases; if dense scores exhibit clearer separation, dense gets more weight.[^7][^6]
This kind of query-adaptive weighting is more robust than fixed global weights and matches your desire to make the dense/sparse/graph mix query-adaptive rather than static.

### 3.3 Reranking and cross-encoder calibration

Production-grade RAG stacks increasingly use cross-encoder rerankers (MiniLM, BGE variants) as a final relevance layer over a candidate pool from hybrid retrieval.[^8][^4]
However, studies such as BEIR and subsequent analyses show that absolute cross-encoder scores are not calibrated across corpora, so percentile-based or gap-based heuristics (top1 vs top2) are preferred over fixed thresholds.[^4][^8]

Your iter-12 K3 and Q5 decisions (confidence-gap and percentile-based title overlap handling) align with these findings by replacing static thresholds with relative metrics that adapt to each query’s score distribution.  
Recent work also integrates NLI-based monitors as second-tier faithfulness checks (e.g., Cleanlab and TLM hallucination benchmarks) but warns about memory overhead, which is relevant given your 1 GB RAM droplet.[^4]

### 3.4 KG-augmented RAG and graph-aware retrieval

Advanced RAG guides now emphasize using KGs to inject structure—entities, relations, and paths—into retrieval rather than just as a visualization layer.[^9][^4]
Neo4j’s path-aware RAG and similar approaches show that KG-derived context (paths connecting entities referenced in a query) improves multi-hop reasoning and thematic grouping, especially when used to expand the candidate set after initial vector retrieval.[^9]

Graph-aware late chunking papers in 2026 explicitly link entity graphs to chunk formation so that chunks align with meaningful graph neighborhoods, allowing chunk-level retrieval to reflect graph structure without needing separate per-sentence retrieval.[^3]
These systems typically store per-node features including degree, pagerank, topic cluster, and source metadata (domain, author, date), and then expose those features both to retrievers (via filters and boosts) and to KGs (for visualization and analysis).[^3]

### 3.5 Personalized and metadata-driven RAG for heterogeneous users

Recent RAG work in education and healthcare builds personalization on top of metadata-driven filters and user profiles rather than per-user fine-tuned models.[^10][^11]
A 2026 university information RAG system uses a domain ontology plus rule-based metadata filtering (e.g. batch, program, year) to prune irrelevant documents, then employs ontology-informed ranking to prioritize sources that match user context, yielding higher precision and fewer hallucinations.[^10]

OpenRAG, an open-source personalized learning RAG architecture, splits the pipeline into generator, indexing, retriever, and orchestration, with user profiles (preferences, goals) feeding into retriever filters and summarization style choices, not into the base embeddings.[^11]
Several medical and wearable-agent RAG systems introduce light-weight memory mechanisms (per-user histories, recent interaction logs) that bias retrieval toward sources previously interacted with or confirmed useful, without requiring large stateful models, which is practical for 1 GB edge or droplet environments.[^12][^13]

NotebookLM-specific analyses highlight three reasons it feels better than typical DIY RAG: carefully curated multi-level chunking, aggressive grounding with explicit per-snippet citations, and query-dependent following of references (e.g. within-note links or headings) to fetch related chunks beyond the immediate match.[^14][^15][^8]
Users report that NotebookLM maintains context across diverse media (PDFs, notes, transcripts) and automatically surfaces related sections, suggesting it uses a mix of entity recognition, section-aware chunking, and retrieval expansion guided by the structure of uploaded materials.[^16][^14]


## 4. Gaps and issues specific to your stack

### 4.1 KG connection quality and over-random matches

You report that KG connections often look random, with arbitrary Zettels being linked despite each zettel containing rich metadata (tags, source, speaker, etc.).  
Given that `kg_features/scoring.py` appears to use a fixed combination of content similarity and simple tag overlap, and that entity-anchor resolvers were disabled in iter-11 due to infra but re-enabled under PATH_F with no NLI monitors yet, current KG edges likely lean heavily on coarse similarity rather than nuanced structured signals.

Global weights for connection strength also contribute to ambiguous edges: if thresholds for strong/medium/weak connections are global across all workspaces, a connection considered "medium" in a dense, topic-specific Kasten might feel spurious in a sparse, multi-topic personal KG.  
Furthermore, without workspace-specific weights or per-workspace statistics stored in the KG schema, edges influenced by zettels outside the current workspace can appear unexplained to the user, fulfilling your concern about invisible drivers.

### 4.2 Fixed global connection_strength vs global+personal layers

Currently, connection_strength is computed with fixed global weights and then surfaced visually, but there is no separation between global scores (e.g. across all users) and personal adjustments (per workspace).  
This means that when a user sees an edge in their personal KG, it may be partially driven by patterns learned from other users’ zettels or different workspaces, which is confusing when those zettels are not visible.

Your requirement is to introduce a two-layer view: a global layer (store global UUID-level characteristics for future use) and a personal layer where connection_strength and other features (tags, domain, speaker) are computed relative to workspace-level data only, and only the personal layer should directly drive visible edges in the personal KG.  
This aligns with industry practices for metadata-driven RAG, where global models generate base scores but profile-specific filters and reweighting determine what is shown to each user.[^11][^10]

### 4.3 Overfitting of RAG knobs to the KM Kasten

The iter-12 research doc explicitly states that iter-08..iter-11 accumulated many static knobs (floors, thresholds, percentage shares) tuned against the KM Kasten, and iter-12 replaced most with confidence-gap and per-Kasten bootstrap primitives precisely because static settings generalize poorly.  
However, the eval corpus is still a single Kasten with 14 queries, so while cross-encoder calibration and magnet-spotter logic are now less brittle, the retrieval/reranking stack may still be optimized for that particular distribution of topics and media.

You also plan to test only 20–30 zettels per new Kasten for now, which means any heavy per-Kasten modeling (e.g., bandits, per-Kasten floor learning) risks overfitting further, matching literature that warns systems tuned on narrow settings often generalize poorly out-of-distribution.[^17][^4]
This constrains improvements to approaches that adapt based on per-query statistics and light-weight per-Kasten summaries rather than complex per-Kasten model states.

### 4.4 Chunking location and latency vs UX

Your current pipeline chunks and summarizes zettels during ingestion or summarization, and KG ingestion also needs access to chunked or summarized content, which may create duplication or latency spikes.  
Since you also expose a "View in KG" button that should feel instant, very aggressive on-the-fly analysis at ingestion could hurt UX on your 1 GB droplet.

Industry references recommend pushing as much heavy computation as possible into deferred, asynchronous jobs or incremental background tasks (e.g., late semantic chunking, entity graph construction) while keeping ingestion-time work limited to extracting essential metadata and computing first-pass embeddings.[^13][^2]
With your constraints, this suggests computing minimal chunks and embeddings synchronously, writing them to shared content tables, and then letting KG enrichment and more advanced chunk rearrangement happen via background workers so that the Zettel appears quickly and KG visualization is filled in over a short time.


## 5. Proposed improvements for each module

### 5.1 KG features and KG scoring (website/features/kg_features)

#### 5.1.1 Two-level global + personal connection strength

**Suggested improvement.**  
Introduce a two-tier scoring scheme where `kg_features.scoring` computes:
- A global base score: similarity between zettels based on content embeddings, global co-occurrence patterns, and globally known tags or entities.
- A personal adjustment: re-weighting and thresholding of edges based only on the subset of zettels present in the current workspace (personal graph) and workspace-level statistics.

Implement this by adding additional columns to your KG edge store, e.g., `global_strength`, `workspace_strength`, `workspace_id`, and `matched_via` flags, with `workspace_strength` computed using only nodes accessible in that workspace and used for personal KG rendering, while `global_strength` is stored for future cross-user analytics but not directly surfaced.[^10]
Workspace-level stats such as edge-score percentiles and average degree can be maintained via a light-weight `kg_kasten_metrics`-like table (similar to your existing rolling top-1 metrics) keyed by workspace, with rolling windows or summary stats (mean, stdev) that support percentile-based thresholds.

**Pitfalls to avoid.**  
Do not use global edges whose endpoints are not both visible in the workspace to drive personal KG layout or connection_strength labels, otherwise users will see edges driven by invisible neighbors.  
Avoid per-Kasten or per-workspace high-dimensional weight vectors; store only simple scalars (e.g. per-workspace score percentiles) to keep schema growth manageable as user count scales.[^17]

**Monitors and tests.**  
Add per-workspace histograms of `workspace_strength` and count distributions to KG analytics and alert on anomalies (e.g. all edges suddenly strong after a change).  
For each workspace, sample a subset of edges and log `global_strength`, `workspace_strength`, and `matched_via` metadata for manual review, checking that personal adjustments never promote edges where global evidence is weak and that hidden nodes are not influencing personal graphs.

#### 5.1.2 Richer feature engineering: tags, pseudo-tags, and URL metadata

**Suggested improvement.**  
Extend `kg_features.embeddings` and `scoring` to incorporate richer metadata from your ingestion stack, including:
- `speaker:Name` pseudo-tags for video/podcast sources where speaker extraction is reliable (e.g. YouTube channel metadata, transcript intros).
- `source_domain:domain.com` or more granular `source_channel:youtube.com/channel/...` tags derived from URLs.
- Source modality tags like `modality:video`, `modality:article`, `modality:book`.

Compute a Jaccard or weighted-Jaccard similarity over the expanded tag set and combine it with embedding cosine similarity and structural features (e.g. shared entities) in your connection score, but store full tag sets in the DB so they can be reused by both KG and RAG.[^9][^4]
Ensure pseudo-tags are only added when extraction is high-confidence (e.g., channel ID present, speaker recognized from a curated mapping) to avoid polluting the tag space with noisy labels.[^9]

**Pitfalls to avoid.**  
Do not blindly tag every URL with deep path fragments as separate tags; constrain to stable identifiers such as domains or channel IDs to prevent tag cardinality explosion.  
Avoid treating pseudo-tags as more important than core user-provided tags; they should provide additional axes for similarity, not override the user’s own organization.[^4]

**Monitors and tests.**  
Track counts of unique tags and pseudo-tags over time per workspace and per installation to detect runaway growth.  
Add evaluation cases where queries ask for connections by speaker or source ("What did Naval say about X?"), and verify that tagged zettels cluster and are retrieved or surfaced in KG as expected.

#### 5.1.3 Entity-anchor resolution and graph-based matching

**Suggested improvement.**  
Re-enable and harden entity-anchor resolvers as a KG feature, using them to create edges based on shared entities (e.g. people, organizations, concepts) extracted from zettel content and titles.[^3]
Store per-zettel entity lists and per-edge `matched_via` metadata that includes `entities:[...]` so KG analytics can distinguish entity-based connections from purely vector-based or tag-based ones.

This matches GraphRAG-style graph-aware retrieval where entity nodes connect documents; for your KG you can either add entity nodes explicitly or simply use shared-entity edges between zettels, with weights reflecting count and salience of shared entities.[^3][^9]
With PATH_F in place, the RPC and NER loads should now be manageable if you cap per-document entities (e.g., top 5 per doc) and run entity extraction during ingestion rather than query-time for KG construction.

**Pitfalls to avoid.**  
Do not run heavy NER models synchronously on every query; keep entity extraction as an offline ingest step and reuse stored entities for both KG edges and RAG retrieval expansion.  
Avoid unbounded entity lists; enforce a per-zettel max and prefer high-salience entities (e.g. from titles, headings) over every mention to limit DB and memory use.[^13]

**Monitors and tests.**  
Monitor NER runtime and memory footprint on the 1 GB droplet, ensuring ingestion latency and memory usage stay within safe bounds.  
Add harness tests that ingest zettels with clearly shared entities (e.g. multiple talks by the same speaker) and check that entity-based edges dominate connection_strength for those nodes and that RAG retrieval improves on entity-focused queries.

### 5.2 KG front-end (website/features/knowledge_graph)

#### 5.2.1 Visual encoding of connection strength tiers

**Suggested improvement.**  
Update the D3 graph rendering to map connection_strength tiers (strong/medium/weak) into subtle edge visual properties:
- Strong: thicker stroke (e.g. 2.0–2.5 px) and higher opacity (0.9–1.0).
- Medium: default stroke (1.2–1.5 px), medium opacity (0.6–0.7).
- Weak: thinner stroke (0.5–0.8 px), low opacity (0.3–0.4).

This leverages standard information visualization practice of encoding importance via line width and opacity, without introducing new icons or labels.[^4]
Because the KG already uses colors for node types, using edge thickness/opacity avoids overloading the color channel and keeps the visual design simple.

**Pitfalls to avoid.**  
Do not introduce drastic differences (e.g. very thick edges) that dominate the layout; keep the ratio between weak and strong modest (e.g. 1:2) so the graph remains readable.[^4]
Avoid encoding strength only through color saturation, as color differences can be hard to perceive and conflict with your existing palette.

**Monitors and tests.**  
Add snapshot visual regression tests (e.g. via Playwright screenshots from your existing eval harness) to ensure edge-styling changes do not break layout or legibility.  
During user testing, gather feedback on whether users can correctly distinguish strong vs weak edges and adjust thresholds if many edges appear indistinguishable.

#### 5.2.2 Workspace-scoped graphs and clarity of scope

**Suggested improvement.**  
Make it explicit in KG JS that the personal graph is workspace-scoped: only zettels in the current workspace should be rendered by default, with any global edges or cross-workspace suggestions shown only in dedicated views or overlays.  
Add optional filters (checkboxes) in the UI to show/hide weak connections or to focus on certain tag clusters, but keep defaults simple so that new users see a clean graph of their core zettels.

This matches NotebookLM-style design where the notebook is the unit of context, and retrieval or KG operations happen within that notebook unless explicitly expanded.[^15][^8]
For Kasten-specific KG views, you can draw subgraphs induced by the Kasten’s zettels, but keep the underlying personal KG store unchanged so you avoid duplicating edges.

**Pitfalls to avoid.**  
Do not create separate physical KG stores per Kasten; use workspace-level graphs with Kasten IDs as metadata to prevent data duplication and schema bloat.  
Avoid exposing global edges in personal graphs unless you have an explicit UX pattern explaining why they appear (e.g. "Similar to public zettel X" badges) to prevent ambiguity.

**Monitors and tests.**  
Add tests that verify that when switching between workspaces, KG nodes/edges update and no cross-workspace leakage occurs.  
Use analytics to measure average node and edge counts per workspace and ensure they remain within reasonable ranges for interactive visualization on low-resource clients.

### 5.3 RAG pipeline: chunking and ingestion (website/features/rag_pipeline/ingest)

#### 5.3.1 Shared chunk store and avoiding duplication

**Suggested improvement.**  
Ensure that chunking output is written once into `content.canonical_chunks` and reused by both RAG retrieval and KG features.  
Avoid separate chunking logic in KG ingestion; instead, let KG consume the same chunks and metadata that RAG uses, adding KG-specific features (e.g. entity summaries) as additional columns or linked tables rather than new chunk entities.

This matches best practices where indexing subsystems feed both search and analytics, and where chunking is centralised to avoid diverging views of the same underlying document.[^11][^1]
Your existing v2 schema already treats `canonical_zettels`, `workspace_zettels`, and `canonical_chunks` as shared resources, so the main work is to audit any KG-specific chunking functionality and either remove or unify it.

**Pitfalls to avoid.**  
Do not introduce multiple chunk sizes per zettel unless you have a clear query-adaptive use case; storing many chunk variants for every zettel can blow up storage quickly under multi-user load.  
Avoid KG-specific summarization forms that diverge significantly from RAG chunks, because that makes it harder to keep both views consistent and increases ingest latency.

**Monitors and tests.**  
Add DB constraints or checks to ensure each zettel’s chunk set is synchronized between RAG and KG (e.g., a count mismatch alert).  
Run periodic audits that compare chunk counts and sizes between the two consumers and ensure no duplicate or orphan chunks exist.

#### 5.3.2 Ingestion latency vs user experience via lazy enrichment

**Suggested improvement.**  
Adopt a two-phase ingestion workflow:
1. **Synchronous phase (on user submission / summarization)**: extract core metadata (title, author, URL, tags), compute a single document embedding, and generate baseline chunks using a simple hierarchical or fixed-size (e.g. 400–600 tokens) strategy. Write `canonical_zettels`, `workspace_zettels`, and `canonical_chunks` rows immediately.[^2][^1]
2. **Asynchronous enrichment phase** (background job): compute semantic chunk boundaries, run NER and entity-anchor extraction, compute KG features (tags, pseudo-tags, entity sets, graph-based scores), and update KG edge stores.[^9][^3]

This ensures the zettel appears in the KG and is available for basic retrieval within one request/response cycle, while heavier analytics are applied in the background, aligning with industry patterns for edge RAG where hierarchical or two-stage retrieval designs reduce resource burden.[^13][^2]
On your 1 GB droplet, you can enqueue enrichment tasks via a simple Postgres job table or lightweight queue; avoid distributed queues that would add infra overhead without need.

**Pitfalls to avoid.**  
Do not block the user-facing API on enrichment tasks; keep ingestion SLA tight (e.g., < 2–3 seconds where network permits) and tolerate slightly stale KG features that converge after a few seconds or minutes.  
Avoid running enrichment continuously for the same zettel; ensure idempotent jobs keyed by zettel ID so that repeated ingestion or edits do not spawn duplicate heavy tasks.

**Monitors and tests.**  
Instrument ingestion paths with per-stage metrics and track `p_user_complete_ms` (already used in iter-12 scoring) to ensure within_budget rate stays ≥ 0.85 as targeted.  
Add tests that simulate concurrent ingestion of 20–30 zettels and verify that background jobs complete without exceeding memory limits or causing RAG query latency spikes.

### 5.4 RAG retrieval and reranking (website/features/rag_pipeline/retrieval, rerank, query)

#### 5.4.1 Query-adaptive dense/sparse/graph mixing

**Suggested improvement.**  
Extend your existing hybrid retrieval in `hybrid.py` to compute a query-level confidence/entropy metric over sparse and dense scores, and adjust weights accordingly, keeping graph-based scores as a third component.

A pragmatic approach consistent with literature:
- For each candidate doc, compute normalized sparse score (e.g. BM25) and dense score (cosine similarity), then compute per-channel score distributions and Shannon entropy.[^6][^7]
- If sparse entropy is low (few items get most of the mass), increase sparse weight; if dense entropy is lower, increase dense weight; if both are high (uncertain), rely more on KG/graph-based expansion (entities and tags) to broaden the candidate pool.[^6]
- Keep graph score as a modifier rather than a primary retrieval channel: boost candidates whose nodes are close in the KG (short path, high common neighbors) relative to query-relevant nodes.

This yields query-adaptive mixing without per-Kasten tuned weights and plays well with your existing K3 confidence-gap logic, which already uses relative scores to decide when to bypass some gates.[^6]
The computation overhead is low: entropies and normalized scores can be computed over the small candidate set you already manage before reranking, and there is no need for repeated retrieval queries.

**Pitfalls to avoid.**  
Do not run separate full sparse and dense retrievals with large K for every query; reuse your current hybrid design and adapt weights only at the late stages to stay within memory and latency budgets.[^13]
Avoid complex iterative reweighting loops beyond 1–2 passes; with a small candidate pool, a single adaptive adjustment is usually sufficient.

**Monitors and tests.**  
Log per-query weights and entropy metrics and build histograms per query class (LOOKUP, THEMATIC, MULTI_HOP, etc.) to ensure they behave as expected.  
Add regression tests for queries where lexical match is crucial (e.g. exact names) and for purely semantic queries, ensuring that the adaptive scheme does not degrade either class relative to your current hybrid baseline.

#### 5.4.2 KG-aware retrieval for multi-hop and thematic queries

**Suggested improvement.**  
Use KG-derived features (tags, entities, graph distance) to expand or rerank results in retrieval, particularly for multi-hop and thematic queries.

Concretely:
- When the router classifies a query as THEMATIC or MULTI_HOP, identify seed entities or tags from the query using your existing router/transformer sequence and entity extraction.[^3]
- Use the KG to find neighboring nodes within 1–2 hops that match these entities/tags and add their associated chunks as low-priority candidates (with lower base scores but higher diversity).  
- During reranking, add a graph proximity feature (e.g. shortest path length to the primary node, common neighbor count) to the candidate score and let your cross-encoder reranker integrate this signal alongside text similarity.[^9][^3]

This pattern mirrors GraphRAG and path-aware Neo4j RAG approaches that gain robustness on multi-document reasoning tasks.[^3][^9]
Given your droplet constraints, the KG queries should be simple (few hops, small result sets) and limited to the current workspace’s KG; avoid complex global graph traversals.

**Pitfalls to avoid.**  
Do not expand candidate sets aggressively for every query; restrict KG expansion to classes where graph structure is clearly valuable or when baseline retrieval returns too few candidates.  
Avoid storing full graph embeddings or path indices that would consume significant memory; simple adjacency lists and lightweight metrics suffice at your scale.[^13]

**Monitors and tests.**  
Add per-class retrieval diagnostics that compare gold@k and rerank scores before and after KG-aware expansion on multi-hop queries in your eval set.  
Monitor additional latency introduced by KG lookups and ensure it stays within a small fraction of total retrieval time.

#### 5.4.3 Robust router and user-style-aware synthesis

**Suggested improvement.**  
You already have Q7 regex and A1 few-shot router improvements; extend this with lightweight user-style parameters that influence retrieval and synthesis but not core correctness.

For instance, store per-workspace preferences in a `kasten_stats`-like structure: preferred media types (e.g. fraction of zettels from YouTube vs articles), average zettel length, and dominant topics extracted from tags.[^10]
Use this to:
- Slightly up-weight zettels matching dominant source types (e.g. more video-heavy retrieval for a user who mainly stores videos) in tie-breaking scenarios.
- Choose synthesis style templates (short bullet summary vs long essay vs conversational script) based on observed usage, while maintaining the same grounded citations.[^8][^11]

NotebookLM and personalized RAG systems in education/healthcare show that aligning answer format and example sources with user habits increases perceived quality without changing the underlying retrieval correctness.[^8][^11][^10]
Keep style preferences as optional hints, not as strong filters, to avoid overfitting to current usage and to support exploration of new content types.

**Pitfalls to avoid.**  
Do not introduce heavy per-user models or large histories; instead, rely on aggregated statistics over recent zettel additions and queries to keep storage minimal.  
Avoid tying style too directly to Kasten-level metrics; use workspace-level observations to prevent repeated recalculation per Kasten.

**Monitors and tests.**  
Log selected synthesis styles and their correlation with query satisfaction proxies (e.g. follow-up questions, dwell time) to see whether style adaptation helps.  
Ensure that faithfulness metrics (RAGAS, over_refusal/under_refusal rates) remain unchanged as style preferences are introduced.

### 5.5 Scoring and evaluation (rag_eval, scoring)

#### 5.5.1 Cross-Kasten evaluation practice under 20–30 zettel constraints

**Suggested improvement.**  
Given your limited ability to generate large eval sets per Kasten, adopt a Kasten-agnostic eval routine combining:
- A small, hand-crafted query set (10–20 queries) per new Kasten, covering lookup, thematic, multi-hop, and vague classes, similar to your iter-11 classes.  
- A shared meta-eval harness that computes the same metrics as your iter-12 scoring (accuracy_user_visible, gold@k, faithfulness, over_refusal/under_refusal, within_budget) for each Kasten but aggregates metrics across Kastens to detect overfitting.

In addition, use synthetic "orientation" tests: apply the same query templates ("What are the main themes in these zettels?", "Summarize Naval’s advice from your notes", etc.) across very different Kastens (history videos, motivational speeches, technical articles) and track whether retrieval patterns or failure modes become coupled to content type.[^17][^4]
This helps diagnose overfitting of thresholds or KG heuristics to a particular Kasten phenotype even when each Kasten has only a small number of zettels.

**Pitfalls to avoid.**  
Do not rely solely on one Kasten’s metrics to decide pipeline changes; always consider cross-Kasten performance as a gate for shipping general changes.  
Avoid designing eval queries that hinge on extremely niche behavior; focus on generic RAG behaviors that should generalize (entity lookup, concept explanation, cross-document synthesis).

**Monitors and tests.**  
Extend your existing `score_rag_eval.py` and `post_iter_audit.py` to support multiple Kasten IDs and to print per-Kasten and cross-Kasten breakdowns.  
Use the per-class breakdown introduced in Class S to ensure each query phenotype performs consistently across Kastens.

#### 5.5.2 KG-specific eval metrics

**Suggested improvement.**  
Define a small set of KG-focused metrics and tests, separate from RAG eval:
- Edge precision: for a sample of edges labeled strong, manually rate correctness and compute precision for strong connections; aim to increase this over time.  
- Clustering quality: measure whether zettels sharing key tags or entities form cohesive clusters (e.g., using modularity or normalized mutual information between graph communities and tag/topic labels).[^9][^3]
- Diversity and degree distribution: track if certain nodes become over-connected magnets (similar to `gh-zk-org-zk` in iter-11) and use magnet-spotter-like logic to detect this in KG.

These can be computed offline using `kg_features.analytics` and can share infrastructure with your existing magnet-spotter metrics (e.g. frequency of top-1 nodes across queries).[^3]
Use them as gates when shipping KG changes: an improvement in RAG may not be acceptable if KG edges become less interpretable or over-dense.

**Pitfalls to avoid.**  
Do not over-index on raw edge count as a measure of KG quality; many weak, low-value edges can make the graph noisy without improving RAG or user understanding.  
Avoid expensive global graph metrics that require full graph traversal in the online path; reserve these for offline analytics.

**Monitors and tests.**  
Add a KG audit script that runs after any schema or scoring changes, producing a markdown report with edge precision samples, degree histograms, and cluster/tag overlap, stored alongside your RAG iter reports.  
Track metrics over iterations to see if KG quality trends align with RAG improvements.


## 6. Storage and infra considerations for 1 GB droplet

### 6.1 Schema design and growth control

Given your 1 GB RAM and NVMe SSD, schema design must avoid per-user explosion.  
The iter-12 design already shows careful consideration of executor sizes, connection pools, and table sizes for `kg_kasten_metrics` with background pruning after 90 days.

For new per-workspace or Kasten-level stats (style preferences, source-type distributions), follow the same pattern: small tables with few columns, indexed by workspace or Kasten ID, and periodic pruning or aggregation.[^11][^13]
Do not introduce per-Kasten weight profiles beyond a handful of scalar values; avoid per-user cross-encoder fine-tuning or large per-user embedding tables.

### 6.2 Process and thread limits

PATH_F sets `ThreadPoolExecutor(max_workers=8)` and a global `_RPC_SEM=8`, with httpx pools sized to 16 connections, tuned for your droplet’s resources.  
Any additional KG-related RPCs (e.g. entity lookups or graph_score queries) must respect the same bounds; reuse existing RPC wrappers to ensure you do not inadvertently exceed connection limits or saturate the executor.

If you add background jobs (e.g. for enrichment), consider running them via a separate low-priority worker or batched jobs triggered outside of high-load windows, using the same Supabase client but with rate limiting.[^13]
Monitor `event_loop_lag_ms` and `p_user_complete_ms` as in iter-12; any KG update that increases these metrics beyond your targets should be reconsidered.


## 7. Summary of concrete changes mapped to your issues

The table below maps your listed issues to the proposed improvements above.

| Your issue | Proposed changes (modules) |
|-----------|----------------------------|
| KG connections look random | Two-level global+personal scoring in `kg_features.scoring`, richer tag/entity features, entity-anchor edges, KG-aware retrieval for THEMATIC/MULTI_HOP.[^3][^9] |
| Show strong/medium/weak subtly | Edge thickness/opacity encoding in `knowledge_graph/js/graph.js`, with tiers derived from workspace_strength.[^4] |
| RAG overfit to current Kasten | Query-adaptive hybrid retrieval, K3/K4-style metrics extended beyond KM, cross-Kasten eval harness using small query sets.[^6][^17] |
| Underperforming chunking/retrieval/reranking/synthesis | Centralized chunking with hierarchical/semantic defaults, KG-aware retrieval for multi-hop, confidence-gap and percentile-based thresholds already in iter-12 plus KG features to improve thematic and multi-hop retrieval and reranking.[^1][^3] |
| Move from fixed global weights to global+personal levels | Introduce per-workspace `workspace_strength` and percentile thresholds, store global UUID-level stats separately in KG tables.[^10] |
| When to chunk/rerank vs ingest latency | Two-phase ingestion with minimal synchronous core and async enrichment; avoid duplicated chunking in KG; reuse `canonical_chunks`.[^2] |
| Extend tags to pseudo-tags | Add `speaker:` and `source_domain:` pseudo-tags under strict extraction rules and include them in KG similarity and RAG filters.[^4][^9] |
| Store more zettel data without explosion | Use compact scalar stats and shared chunk store; avoid per-Kasten high-dimensional state; prune metrics tables with time-based retention as in `kg_kasten_metrics`.[^13] |
| entity-anchor resolvers disabled | Re-enable under PATH_F with per-request semaphores and move to ingest-time for KG construction; store entity-based edges explicitly.[^3] |
| Optional Kasten-level style info | Add `kasten_stats`-like workspace/Kasten summaries for dominant source types, average length, and topics; use for style and light retrieval preferences, not core semantics.[^10] |
| Query-adaptive dense/sparse/graph mix | Implement entropy-based hybrid weighting in `retrieval/hybrid.py`, using KG proximity as a third factor for THEMATIC/MULTI_HOP.[^6][^7] |
| Eval under 20–30 zettels per Kasten | Multi-Kasten eval harness reusing iter-12 scoring metrics, with small hand-designed query sets per Kasten and cross-Kasten aggregation.[^17] |
| Avoid heavy per-Kasten weight profiles | Limit per-Kasten info to a few scalar stats and avoid storing full per-Kasten threshold vectors or models.[^11] |

These changes keep infra overhead compatible with your 1 GB droplet, leverage industry-standard RAG and KG practices from the last five years, and are grounded in your existing iter-12 architecture, while addressing the concrete KG and RAG gaps you have observed.

---

## References

1. [Text Chunking - GraphRAG](https://graphrag.com/guides/chunking/) - This process of splitting up documents into smaller pieces is called Chunking. There are a number of...

2. [Best Chunking Strategies for RAG Pipelines - Redis](https://redis.io/blog/chunking-strategy-rag-pipelines/) - Learn which chunking strategy fits your RAG pipeline—fixed-size, recursive, semantic, or LLM-driven—...

3. [Graph-Aware Late Chunking for Retrieval-Augmented Generation in ...](https://arxiv.org/html/2603.22633v1) - Graph-based RAG (GraphRAG) methods [6, 22, 11] leverage knowledge graphs, citation networks, and ent...

4. [Advanced RAG — Hybrid Search, Reranking & Knowledge Graphs ...](https://myengineeringpath.dev/genai-engineer/advanced-rag/) - Go beyond basic RAG: hybrid search combining dense and sparse retrieval, cross-encoder reranking, kn...

5. [The SolutionLink Copied](https://mbrenndoerfer.com/writing/hybrid-retrieval-combining-sparse-dense-methods-effective-information-retrieval) - A comprehensive guide to hybrid retrieval systems introduced in 2024. Learn how hybrid systems combi...

6. [[PDF] Entropy-Based Dynamic Hybrid Retrieval for Adaptive Query ...](https://openreview.net/attachment?id=bwGaZOVo0c&name=pdf)

7. [3. Dense And Sparse Space...](https://arxiv.org/html/2410.20381v1)

8. [My NotebookLM takeaways from advanced RAG videos - Ethan Lazuk](https://ethanlazuk.com/blog/rag-notebooklm/) - Retrieval Augmented Generation (RAG) is an architecture for building systems that can access and pro...

9. [Knowledge Graph Chunking for RAG: Neo4j Path-Aware and Vector ...](https://www.linkedin.com/pulse/knowledge-graph-chunking-rag-neo4j-path-aware-vector-store-mysore-hiulc) - This article presents a comprehensive performance analysis of 10 different chunking strategies appli...

10. [Metadata-Driven RAG Architecture for Context-Aware University Information Retrieval](https://ieeexplore.ieee.org/document/11499763/) - General-purpose Large Language Models (LLMs) frequently produce generic or hallucinated responses wh...

11. [OpenRAG: Open-source Retrieval-Augmented Generation Architecture for Personalized Learning](https://ieeexplore.ieee.org/document/10900069/) - This paper introduces OpenRAG, an open-source Retrieval-Augmented Generation (RAG) system architectu...

12. [Improving the RAG-based Personalized Discharge Care System by Introducing the Memory Mechanism](https://ieeexplore.ieee.org/document/10963086/) - As the performance of large language models is proven in general domains, we can consider applying t...

13. [A Memory-Efficient Retrieval Architecture for RAG-Enabled Wearable Medical LLMs-Agents](https://ieeexplore.ieee.org/document/11327513/) - With powerful and integrative large language models (LLMs), medical AI agents have demonstrated uniq...

14. [NotebookLM: RAG Architecture Overview | PDF - Scribd](https://www.scribd.com/document/887551310/NotebookLM-Internal-Framework-Explained) - The RAG architecture in NotebookLM provides access to up-to-date, user-specific information by opera...

15. [Clean Messy Notes for Grounding - NotebookLM Guide](https://notebooklm-guide.com/notebooklm-grounded-rag-pipeline) - Build a private AI expert brain: zero hallucination, every answer cited. Plus the Claude preprocessi...

16. [Why is NotebookLM so much better than my custom RAG ... - Reddit](https://www.reddit.com/r/notebooklm/comments/1rvgdmm/why_is_notebooklm_so_much_better_than_my_custom/) - Every custom RAG system I've tried to build (with LangChain) feels like a nothing in comparison with...

17. [arXiv:2503.23013v1 [cs.IR] 29 Mar 2025](https://arxiv.org/pdf/2503.23013v1.pdf)

