# iter-01 manual review — youtube — 2026-04-25

eval_json_hash_at_review: "NOT_CONSULTED"
estimated_composite: 87
estimated_retrieval: 95
estimated_synthesis: 82

## Per-query observations

- Q1 (Karpathy two-stage LLM): Gold node `yt-andrej-karpathy-s-llm-in` was retrieved AND ranked #1 (rerank 0.997). Answer correctly identifies pre-training + fine-tuning, names SFT/RLHF/Constitutional AI, and covers all 4 atomic facts (next-token, transformer base, instruction tuning, base->assistant ordering). Slight embellishment with "blurry JPEG" / Llama 2 2T tokens — plausible content from the source but I can't verify without the chunk text. No hallucination signal. Synthesis is comprehensive, citations are clean. Strong retrieval, strong synthesis.

- Q2 (Transformer scaling): Gold node `yt-transformer-architecture` retrieved and ranked #1 (rerank 0.986); secondary gold `yt-andrej-karpathy-s-llm-in` ranked #2. Perfect ranking match to gold_ranking. Answer is faithful and hits all 3 atomic facts (replace recurrence, parallelizable self-attention, enabled scaling). However the answer is unusually short — three sentences, somewhat repetitive ("parallelizable" three times). Lacks the depth of the reference (no explicit RNN/LSTM contrast, no mention of forward/backward pass). Retrieval is excellent; synthesis is correct but thin.

- Q3 (Software 1.0 vs 2.0): Gold node `yt-software-1-0-vs-software` ranked #1 (0.999). Answer correctly explains the paradigm shift and the data-curator development cycle. Hits 3 of 4 atomic facts (1.0 = explicit code, 2.0 = learned weights, dev cycle = data curation). **Misses AlphaGo example** which is in the reference and atomic_facts. Distractor `yt-zero-day-market-covert-exploits` appears in retrieval at position 4 — clearly off-topic, but rerank score is near-zero and it was not used in synthesis, so no harm. Solid but incomplete coverage.

- Q4 (LeCun critique + JEPA): Gold node `yt-lecun-s-vision-human-lev` ranked #1 (0.999). Answer is thorough — covers next-token limitation, JEPA, world model, objective-driven AI, System 1/2 framing, perception/world/cost/actor modules. Hits all 4 atomic facts. **Missing**: LeCun's "AI as amplifier of human intelligence, not replacement" closing point from the reference, though the snippet hints at it. Otherwise highly faithful and detailed. Best-synthesized answer of the five.

- Q5 (Programming workflow): Gold node `yt-programming-workflow-is` ranked #1 (0.988); it's the only gold for this question. Answer is concise and faithful, hits all 3 atomic facts (perception inaccurate, debug-fix cycle with Google/SO, debugging > typing speed). Distractors (`yt-effective-public-speakin`, `yt-lecun`) appear far down with negligible rerank scores and were not cited. Answer is correct but quite short — could have been more concrete about the iterative loop steps. Clean retrieval.

## Per-stage observations

- Chunking: Cannot inspect chunks directly. Snippet previews look like the JSON-encoded summary blobs (brief_summary, detailed_summary) rather than narrative prose — suggests chunks are derived from the structured note JSON. Answers cite specific facts (Llama 2 2T tokens, Constitutional AI, 4 JEPA modules) suggesting chunks carry sufficient density. No evidence of mid-sentence cuts harming synthesis.

- Retrieval: Excellent. The gold node was retrieved and ranked #1 in all 5 queries. Gold_ranking secondary nodes also surfaced (Q1, Q2, Q3, Q4). Distractor leakage on Q3 (zero-day) and Q5 (public speaking) is real but harmless given rerank scoring suppresses them. Estimated retrieval recall@k = 5/5 for primary gold, ~4/5 for secondary gold.

- Reranking: Working as intended. Rerank scores show clean separation — gold consistently >0.98 while distractors fall below 0.001. The reranker is doing real work and the ordering matches gold_ranking order on every query I can check.

- Synthesis: Generally faithful, with citations consistently placed. Q1 and Q4 are comprehensive; Q3 misses AlphaGo (atomic fact dropped); Q2 and Q5 are correct but noticeably terse compared to reference depth. No hallucinations detected. Main weakness is variable answer length / under-coverage on simpler queries — the model is conservative and doesn't always pull all relevant atomic facts even when the right Zettel is in context.

- KG signal (graph_lift): unknown without evaluator scores - leave blank
