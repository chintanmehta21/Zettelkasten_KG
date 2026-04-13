# Reranker options for Zettelkasten_KG without losing quality

## Overview

This report analyzes lighter-weight reranking options that can replace the current BGE cross‑encoder in the Zettelkasten_KG RAG + KG pipeline without materially degrading ranking quality, and proposes concrete migration paths and cascades.
The focus is on models that can be deployed as a TEI-compatible `/rerank` sidecar (or similar HTTP service) and work well for both unstructured RAG documents and KG node/edge textual representations.

## Current setup in Zettelkasten_KG

The `TEIReranker` client in `website/features/rag_pipeline/rerank/tei_client.py` calls a sidecar at `http://reranker:8080/rerank` with a JSON payload containing the query and candidate texts, and receives a list of scored items indexed back into the candidate list.
For each candidate, the pipeline sets `rerank_score` from the cross‑encoder and computes a `final_score = 0.60 * rerank_score + 0.25 * graph_score + 0.15 * rrf_score`, then returns the top‑k (default 8); on HTTP errors, it falls back to ranking purely by `rrf_score`.
This means the reranker contributes 60% of the final ranking signal but graph and retrieval scores still provide substantial signal, slightly relaxing the requirement on reranker perfection.

## Baseline: BGE‑reranker‑large

BGE‑reranker‑large is a 0.6B‑parameter cross‑encoder (XLM‑RoBERTa‑large backbone) trained on multilingual pair data for reranking, with strong performance on MS MARCO, BEIR, and C‑MTEB reranking tasks.[^1][^2]
Official documentation reports average reranking scores (C‑MTEB reranking tasks) of 66.09 vs 65.42 for BGE‑reranker‑base, indicating only a ~1% absolute advantage on these benchmarks.[^3][^1]
The large model’s parameter count and FP16 weights typically translate into ~1 GB or more of model files plus runtime framework overhead in a container, which matches the observed Docker size and cold‑start latency issues.

## Option 1 – BGE‑reranker‑base (drop‑in smaller BGE)

- **Thesis**: Replace `BAAI/bge-reranker-large` with `BAAI/bge-reranker-base` in the reranker sidecar to roughly halve parameter count while maintaining ~99% of BGE‑large’s reranking quality on published benchmarks.

- **Quality vs BGE‑large**:
  - On C‑MTEB reranking tasks, BGE‑reranker‑base achieves an average reranking score of 65.42 vs 66.09 for BGE‑reranker‑large, i.e. about 99% of the large model’s quality.[^3][^1]
  - Base/large embedding models also show small gaps (e.g., 63.13 vs 64.53 average on C‑MTEB), suggesting the base architecture preserves most semantic capacity.[^3]

- **Benefits**:
  - Parameter count drops from ~560M to ~278M (first‑generation BGE rerankers), or effectively 0.6B → 0.3B according to Hugging Face model cards, which directly reduces disk footprint and memory usage.[^1]
  - Inference cost is roughly linear in parameter count for cross‑encoders, so CPU/GPU latency should improve by ~1.8–2× at the same batch size for your `/rerank` sidecar.
  - Fully backward‑compatible with your current `TEIReranker` client: same paired input format (query, passage) and scalar similarity output.

- **Trade‑offs / risks**:
  - Small but non‑zero quality drop: on some tasks (e.g., CMedQAv1/2, MMarcoReranking), the large model is 1–2 points ahead in MAP/MRR, which could matter for highly specialized domains.[^2][^3]
  - Still not “tiny”: 0.3B parameters will keep the reranker container in the several‑hundred‑MB range, though materially smaller than 0.6B.

- **Fit for KG + RAG**:
  - Because your final score blends rerank, graph, and RRF signals, the ~1% loss in pure reranker quality is likely to translate into even smaller differences in the final ranking, especially for KG‑heavy queries where `graph_score` carries information.[^3]
  - Base and large BGE models share training data and multilingual coverage, so behavior on KG‑encoded text (node/edge labels, textual descriptions) should be similar.

## Option 2 – Quantized BGE (base or v2‑M3)

- **Thesis**: Keep a BGE reranker but deploy an ONNX/quantized variant (e.g., BGE‑reranker‑base in INT8) to shrink the model footprint and accelerate inference while preserving most accuracy.

- **Quality vs BGE‑large**:
  - Quantization to INT8 typically incurs a small degradation (often <1–2 nDCG points) when applied with standard ONNX Runtime tooling; BGE’s docs explicitly show ONNX deployment with identical logits compared to the FP32/FP16 model for base variants.[^1]
  - BGE‑reranker‑base already trails BGE‑large by only 0.67 points on the C‑MTEB reranking average (65.42 vs 66.09); if quantization costs another ~1 point, the combined gap is still modest in many applications.[^3]

- **Benefits**:
  - ONNX/INT8 compresses weight files significantly compared to FP16, often by ~2×, further reducing the disk and memory footprint beyond switching to base.
  - CPU inference benefit: ONNX Runtime with INT8 can exploit vector instructions to keep per‑request latency acceptable even without GPU, which is useful if you want the reranker to run on cheaper CPU‑only nodes.

- **Trade‑offs / risks**:
  - Quantization is more sensitive to out‑of‑distribution inputs; for heavily domain‑shifted KG text (e.g., dense notation, code, or very long triples) you should validate on your own evaluation set.
  - Tooling complexity: you must either use a pre‑quantized model checkpoint from Hugging Face (several exist for BGE rerankers) or maintain a small quantization pipeline integrated into your image build.[^3]

- **Fit for KG + RAG**:
  - When combined with your existing graph + RRF blending, a 1–3% drop in reranker quality will likely be diluted, especially on KG‑centric questions where graph structure dominates the relevance signal.
  - ONNX quantization does not change the model’s interface, so it remains a drop‑in TEI server; no changes are required in `TEIReranker`.

## Option 3 – FlashRank with MiniLM/TinyBERT cross‑encoders

- **Thesis**: Replace BGE in the sidecar with FlashRank running a compact cross‑encoder (e.g., `ms-marco-MiniLM-L-6-v2` or `L-12-v2`), gaining much smaller models and very fast CPU inference while staying within ~90–98% of BGE‑large’s quality depending on domain.

- **Quality vs BGE‑large (benchmarks)**:
  - In the "How Good are LLM-based Rerankers" study, FlashRank‑MiniLM variants reach nDCG@10 of 70.8 on TREC DL19 vs 72.16 for BGE‑reranker‑large (≈98% of its performance), and 66.27 vs 66.16 on DL20 (essentially equal).[^4]
  - On BEIR datasets, FlashRank‑MiniLM is usually within a few nDCG points of BGE‑large (e.g., NFCorpus 33.0 vs 34.8, Touche 34.8 vs 35.6, Robust04 47.2 vs 49.9), implying roughly 94–98% of BGE‑large’s quality on most general‑domain tasks.[^4]
  - The biggest gap is on SciFact (scientific domain), where FlashRank‑MiniLM scores around 66.3 vs 74.1 for BGE‑large (~89% of its performance), indicating some risk if your KG/RAG heavily targets scientific or biomedical text.[^4]

- **Latency and footprint**:
  - FlashRank is designed for ultra‑fast, CPU‑friendly reranking using ONNX cross‑encoders; public benchmarks report reranking 100 documents in ~72 ms on parallel CPU INT8, significantly faster than cloud APIs like Jina Reranker v3 (~188 ms) and Cohere Rerank 3.5 (~595 ms).[^5]
  - FlashRank can run with very small models (TinyBERT ~4–20 MB) and mid‑size MiniLM cross‑encoders (~100M parameters), dramatically shrinking the model footprint compared to 0.3–0.6B‑parameter BGE models.[^6][^5]

- **Benefits**:
  - Huge container size reduction: a MiniLM‑based cross‑encoder is an order of magnitude smaller than BGE‑large and still substantially smaller than BGE‑base in parameters and serialized weight size.[^6][^1]
  - Excellent speed/quality trade‑off: the reranking paper explicitly highlights FlashRank‑MiniLM as a strong choice for general‑purpose reranking with low latency, sitting near the Pareto frontier of MRR vs runtime.[^4]
  - FlashRank’s implementation is lightweight (no heavy PyTorch/Transformers dependencies in the serving path) and is well‑suited to serverless or tightly‑constrained Docker deployments.[^7][^5]

- **Trade‑offs / risks**:
  - Some quality regressions on specialized domains (e.g., SciFact, certain scientific QA benchmarks) relative to BGE‑large; if your KG leans heavily on research papers, you may see more noticeable differences.[^4]
  - FlashRank itself is primarily an inference engine; you must choose and manage the underlying ONNX cross‑encoder model (MiniLM/TinyBERT/etc.), and quality will depend on that choice.[^8][^6]

- **Fit for KG + RAG**:
  - For general software documentation, product notes, and knowledge‑worker text, FlashRank‑MiniLM’s near‑BGE performance plus your additional graph and RRF signals is likely enough to keep end‑to‑end answer quality indistinguishable from BGE‑large in most cases.[^4]
  - For KG triples, if you ensure that `candidate.content` includes a short natural‑language description (e.g., node label + relation + neighbor snippets), MiniLM‑style models tend to handle this style of text well.
  - You can run FlashRank as a small HTTP service with the same `/rerank` contract and JSON shape used by `TEIReranker`, making it a low‑touch swap at the infra level.

## Option 4 – Hosted rerank APIs (Cohere, Voyage, Jina, Workers AI)

- **Thesis**: Offload reranking to managed APIs such as Cohere Rerank 3.5, Voyage Rerank 2.x, Jina Reranker, or Cloudflare Workers AI BGE‑reranker‑base to eliminate model weights from your Docker images at the cost of network latency and per‑request fees.

- **Quality vs BGE‑style models**:
  - LlamaIndex’s benchmarking shows that BGE‑reranker‑large and CohereRerank both consistently boost hit rate and MRR across embeddings; for OpenAI embeddings, CohereRerank achieves hit rate ~0.927 and MRR ~0.866, while BGE‑reranker‑large reaches 0.910/0.856, i.e. within a few percentage points of each other.[^9]
  - Agentset’s comparison of BGE reranker v2‑M3 vs Cohere Rerank 3.5 reports very close nDCG@10 values (0.084 vs 0.080), but higher ELO and win‑rate for Cohere (124 higher ELO, 12.3% higher win rate) and significantly lower latency than that specific BGE v2 variant, indicating competitive or slightly better perceived quality at lower end‑to‑end latency in their setup.[^10]
  - Cloudflare Workers AI and Azure Foundry expose BGE‑reranker‑base/large as hosted models behind an HTTP API; quality is identical to self‑hosted BGE but you pay in network hops and tokens.[^11][^12]

- **Benefits**:
  - Reranker container becomes a thin HTTP proxy (or disappears entirely if you call APIs directly from the orchestrator), removing the 1 GB+ model weight overhead from your deployments.
  - Access to continuously‑updated, production‑grade models without maintaining your own GPU fleet or quantization pipeline.

- **Trade‑offs / risks**:
  - Added network latency dominates for small top‑k; FlashRank benchmarks show local reranking 100 docs in ~72 ms on CPU, while Cohere/Jina APIs are 2.6–8.3× slower (hundreds of ms) just for reranking, before your own application overhead.[^5]
  - On‑going cost per token/document; this is especially relevant if your KG and RAG pipeline run at high QPS or on long contexts.
  - Data residency and privacy considerations for KG content, depending on where the APIs are hosted.

- **Fit for KG + RAG**:
  - Best suited as a second‑stage "premium" reranker for a small subset of queries (e.g., user‑flagged important questions, or only for the top 3–5 documents after a cheaper local reranker), not as the primary reranker for all traffic.
  - Good escape hatch if you want maximum quality for critical queries without carrying heavy models in your images.

## Option 5 – LLM‑based listwise reranking

- **Thesis**: Use your main LLM (or a specialized listwise reranker like RankGPT/Zephyr) to rerank the top few documents by prompting it with the query plus candidate summaries, leveraging its deeper reasoning at the cost of higher latency and context usage.

- **Quality vs BGE‑large**:
  - The reranking study reports RankGPT‑GPT‑4 achieving nDCG@10 of 75.59 on DL19 vs 72.16 for BGE‑reranker‑large, i.e. ~105% of BGE‑large’s quality on that benchmark.[^4]
  - Listwise rerankers like Zephyr‑7B reach nDCG@10 around 74.22 on DL19 and 80.7 on BEIR Covid, outperforming many pointwise cross‑encoders, and show the smallest performance drop (~8%) when evaluated on novel future queries, suggesting strong robustness.[^4]

- **Benefits**:
  - No additional model weights beyond your main LLM if you already deploy it; reranking is "just another prompt".
  - Particularly attractive for KG‑heavy reasoning where document‑level relevance depends on subtle logical relationships, which powerful LLMs are better at expressing than smaller cross‑encoders.

- **Trade‑offs / risks**:
  - Latency and cost are substantially higher—LLM calls for listwise reranking often run in seconds, not tens of milliseconds, and consume significant tokens when you include multiple long passages.[^4]
  - More complex orchestration (sliding windows, prompt engineering) to handle long lists and avoid positional biases.

- **Fit for KG + RAG**:
  - Best as a final "refinement" stage for only the top 3–5 documents after a fast cross‑encoder reranker, particularly for critical queries or when the top candidates have very close scores.
  - Overkill for most everyday queries, given your explicit requirement to reduce overhead.

## Quantitative comparison vs BGE‑reranker‑large

The table below summarizes key properties of the main options relative to BGE‑reranker‑large.

| Option | Params (approx) | Quality vs BGE‑large | Latency profile | Deployment impact |
|-------|------------------|----------------------|-----------------|-------------------|
|BGE‑reranker‑large|~0.6B|100% (baseline)|High; GPU or slow CPU; cross‑encoder over all candidates|Current; ~1 GB+ image overhead[^1][^2]|
|BGE‑reranker‑base|~0.3B|≈99% on C‑MTEB reranking (65.42 vs 66.09)|~1.8–2× faster than large at same hardware|Halves model footprint; minimal code changes[^3][^1]|
|Quantized BGE‑base (INT8 ONNX)|~0.3B (INT8)|≈96–99% (typical small quantization hit)|Faster CPU inference via ONNX Runtime|Smaller weights; need ONNX tooling[^1]|
|FlashRank‑MiniLM|~100M|≈94–98% on TREC/BEIR; ~89% on SciFact|Very fast on CPU; ~72 ms for 100 docs (INT8)|Tiny container; replace sidecar with FlashRank service[^5][^6][^4]|
|Hosted Cohere/Voyage/Jina|External|Within a few % of BGE and often competitive or better by ELO|Hundreds of ms per call due to network and service latency|Zero model weights locally; pay‑per‑use cost[^9][^5][^10]|
|LLM listwise (RankGPT/Zephyr)|Billions|Often >100% of BGE quality on some benchmarks|Slow (seconds), high token cost|No extra model if LLM already deployed; orchestration complexity[^4]|

## Cascade designs

### Cascade A – BGE‑base only (simple swap)

- Replace the TEI sidecar model with `BAAI/bge-reranker-base` (or an ONNX‑quantized variant) while keeping the rest of the pipeline identical.
- This immediately halves parameter count and should significantly reduce both container size and per‑request latency while preserving ~99% of BGE‑large’s reranking quality.[^1][^3]

**Use when**: you want the simplest change with minimal risk and are satisfied with a moderate but not extreme reduction in overhead.

### Cascade B – FlashRank primary, BGE‑base fallback

- Use a FlashRank service with a MiniLM cross‑encoder as the primary reranker for all queries, ranking the top N candidates from embedding + KG retrieval.
- Optionally, for ambiguous cases (e.g., where the score margin between top candidates is small or where KG coverage is sparse), send only the top 5–10 candidates to a secondary BGE‑reranker‑base service for final scoring.

This approach:

- Offloads most traffic to a tiny, very fast FlashRank container while reserving a smaller BGE‑base container for a fraction of queries.
- Should match or exceed BGE‑large quality on most general‑domain queries because the heavy model only arbitrates close calls, while FlashRank handles clear wins cheaply.[^5][^4]

**Use when**: you want aggressive reduction in average latency and Docker weight but are willing to maintain two reranking services and slightly more complex orchestration.

### Cascade C – Fast cross‑encoder then LLM rerank (for critical queries)

- First, apply a fast cross‑encoder reranker (FlashRank‑MiniLM or BGE‑base) to go from, say, 50 candidates down to 10.
- Second, only for important queries (e.g., ones tagged by users or by business rules), call your main LLM with those 10 documents in a listwise reranking prompt to produce the final top 3–5.

This design:

- Keeps infrastructure overhead low (one small reranker model plus the LLM you already run) and uses the LLM sparingly.
- Takes advantage of evidence that listwise LLM rerankers like RankGPT/Zephyr can outperform BGE‑large by several nDCG points while generalizing better to novel queries.[^4]

**Use when**: you care about squeezing maximum quality out of a handful of high‑value queries but do not want LLM costs or latency on every request.

## Recommendation and migration plan

### Strategic recommendation

- **Primary recommendation**: Switch the reranker sidecar from BGE‑reranker‑large to BGE‑reranker‑base (preferably an ONNX/INT8 variant) as a near‑zero‑risk baseline that cuts model size roughly in half while keeping ≈99% of the large model’s reranking quality.
- **Secondary optimization**: Evaluate FlashRank‑MiniLM as a full replacement for BGE on your own datasets; if its end‑to‑end KG + RAG performance stays within ~2–3% of the BGE‑base baseline, consider migrating fully to FlashRank to minimize container overhead and runtime latency.
- **Optional high‑accuracy tier**: For a "premium" path, keep either a small BGE‑base service or a hosted Cohere/Voyage rerank API as a fallback for ambiguous or high‑stake queries, invoked only after a fast local reranker.

### Concrete plan for Zettelkasten_KG

1. **Establish a local reranking benchmark**
   - Log query–document pairs, KG node candidates, and user feedback (clicks, explicit ratings) to build an offline evaluation set.
   - Compute offline metrics (nDCG@k, MRR) for your current BGE‑large setup to serve as the baseline.

2. **Implement BGE‑base sidecar**
   - Reconfigure your TEI (or equivalent) reranker container to use `BAAI/bge-reranker-base` instead of `BAAI/bge-reranker-large` and verify `/rerank` compatibility with `TEIReranker`.
   - If feasible, use a pre‑quantized ONNX variant of BGE‑base; validate that numerical outputs closely match the FP16 model on a small test set.[^3]
   - Measure: container image size, model load time, per‑query latency at your typical batch sizes, and offline reranking metrics vs baseline.

3. **Prototype a FlashRank sidecar**
   - Stand up a separate FlashRank service exposing a `/rerank` endpoint that accepts `query` and `texts` and returns index/score pairs compatible with your current client.
   - Start with `cross-encoder/ms-marco-MiniLM-L-6-v2` or `L-12-v2` models, which offer strong MS MARCO reranking performance with relatively small parameter counts.[^6]
   - Run the same offline benchmark suite to compare against BGE‑base; pay special attention to queries grounded in KG edges and any scientific/technical domains where BGE‑large had clear advantages.[^4]

4. **Decide between pure BGE‑base vs FlashRank vs Cascade B**
   - If FlashRank is within ~2–3% of BGE‑base on your metrics and user‑visible answers look comparable, adopt FlashRank as the sole reranker and retire BGE entirely.
   - If FlashRank lags more than you are comfortable with but brings significant infra savings, adopt Cascade B: FlashRank primary plus BGE‑base fallback for the top 5–10 candidates when the score distribution is "flat" or when KG coverage is low.
   - If FlashRank underperforms on key business domains, stick with BGE‑base (quantized) as the main reranker and treat FlashRank as optional.

5. **Consider a limited LLM rerank tier**
   - For high‑value use cases (e.g., complex multi‑hop KG queries or user‑flagged "important" questions), add an optional step where the top 5–10 candidates from the cross‑encoder are re‑scored by the main LLM in a listwise rerank prompt.
   - Cap this to a small fraction of traffic to bound cost and latency, while improving perceived answer quality where it matters most.[^4]

6. **Monitor and iterate**
   - Instrument the pipeline to log candidate scores (`rerank_score`, `graph_score`, `rrf_score`) and final selections, then periodically re‑evaluate models as new rerankers (e.g., BGE v2‑M3, newer FlashRank variants, Voyage/Cohere releases) appear.[^13][^10]
   - Use A/B tests on real traffic where possible to validate that changes to the reranker translate into better end‑to‑end user satisfaction rather than only offline metric gains.

This plan should let you reduce your reranker container footprint from ~1 GB to a few hundred megabytes (BGE‑base) or even below that (FlashRank), while keeping ranking quality within a few percent of the current BGE‑large setup for both KG and RAG contexts.
By layering in an optional cascade with a heavier model or LLM, you can further hedge against edge cases where small cross‑encoders struggle, without imposing their cost on every query.[^5][^4]

---

## References

1. [BGE Reranker — BGE documentation - BGE Models](https://bge-model.com/tutorial/5_Reranking/5.2.html)

2. [bge-reranker-large - Accenture AI Refinery SDK](https://sdk.airefinery.accenture.com/distiller/model_catalog/Reranker/BAAI/bge-reranker-large/) - Let's put our knowledge at a place where it is easily searchable and readable.

3. [BAAI/bge-reranker-base - Hugging Face](https://huggingface.co/BAAI/bge-reranker-base) - We’re on a journey to advance and democratize artificial intelligence through open source and open s...

4. [[PDF] How Good are LLM-based Rerankers? An Empirical Analysis ... - arXiv](https://arxiv.org/pdf/2508.16757.pdf) - bge-reranker-large. 72.16 66.16 ... For general- purpose reranking with low latency, FlashRank-. Min...

5. [Flash-Rerank — Rust text processing library // Lib.rs](https://lib.rs/crates/flash_rerank) - Core reranking engine — cross-encoder and ColBERT inference via ONNX Runtime

6. [navteca/ms-marco-MiniLM-L-12-v2 - Hugging Face](https://huggingface.co/navteca/ms-marco-MiniLM-L-12-v2) - Performance ; cross-encoder/ms-marco-TinyBERT-L-2-v2, 69.84, 32.56, 9000 ; cross-encoder/ms-marco-Mi...

7. [Next-Level ReRanking with FlashRank: A Speedy Solution for Advanced RAG](https://www.youtube.com/watch?v=fUIeMuRtQr8) - Welcome to my comprehensive tutorial on enhancing your search and retrieval systems using Flash Rank...

8. [FlashRank - Rankify](https://rankify.readthedocs.io/en/latest/api/rerankings/flashrank/) - FlashRank. rankify.models.flashrank. HF_PRE_DEFIND_MODELS = {'upr': {'t5 ... bge-reranker-large', 'b...

9. [Boosting RAG: Picking the Best Embedding & Reranker models](https://www.llamaindex.ai/blog/boosting-rag-picking-the-best-embedding-reranker-models-42d079022e83) - Pick the best embedding and reranker models to boost RAG performance. Compare OpenAI, Cohere, and Ji...

10. [BAAI/BGE Reranker v2 M3 vs Cohere Rerank 3.5 - Agentset](https://agentset.ai/rerankers/compare/baaibge-reranker-v2-m3-vs-cohere-rerank-35) - Compare BAAI/BGE Reranker v2 M3 vs Cohere Rerank 3.5 reranking models for RAG. Side-by-side analysis...

11. [bge-reranker-base - Workers AI](https://developers.cloudflare.com/workers-ai/models/bge-reranker-base/) - Different from embedding model, reranker uses question and document as input and directly output sim...

12. [baai-bge-reranker-large - Microsoft Foundry](https://ai.azure.com/catalog/models/baai-bge-reranker-large) - Explore the comprehensive catalog of AI models from Microsoft Foundry

13. [rerank-2 and rerank-2-lite: the next generation of ... - Voyage AI](https://blog.voyageai.com/2024/09/30/rerank-2/) - TL;DR — We’re excited to announce the Voyage 2 series of rerankers, rerank-2 and rerank-2-lite. When...

