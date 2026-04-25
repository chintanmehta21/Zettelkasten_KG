# iter-03 manual review — youtube — 2026-04-25

eval_json_hash_at_review: "NOT_CONSULTED"
estimated_composite: 87
estimated_retrieval: 90
estimated_synthesis: 85

## Per-query observations
- Q1: Gold node `yt-andrej-karpathy-s-llm-in` retrieved at rank 1 and cited. Answer covers both stages (pre-training as base/document-completer, fine-tuning via SFT + RLHF) and matches all four atomic facts. Mentions "Constitutional AI" which is a minor extrapolation beyond the reference but plausible from source. Faithful, comprehensive, well-cited. Strong.
- Q2: Gold node `yt-transformer-architecture` retrieved at rank 1, sole citation. Captures parallelizable self-attention vs sequential recurrence, RNN hidden-state bottleneck, and scaling enablement — all three atomic facts present. Tight, no off-topic citations (improvement over iter-02 which dragged in karpathy-llm and software-1-0). Excellent.
- Q3: Gold node `yt-software-1-0-vs-software` is the only retrieved/cited doc — clean. Covers explicit-programming vs learned-weights distinction and the data-curator/teacher dev-cycle shift. Missing: AlphaGo as flagship example (atomic fact #4) — a small comprehensiveness gap vs reference. Otherwise faithful and on-target.
- Q4: Gold node `yt-lecun-s-vision-human-lev` at rank 1, cited. Covers next-token-prediction critique, JEPA, world-model + Cost/Actor/Optimizer modules. Missing the "AI as amplifier of human intelligence, not replacement" atomic fact. Two extra citations (`yt-software-1-0-vs-software`, `yt-dan-shapiro-overcoming-t`) appear in the cited set but the prose is anchored to the LeCun node — the extras look like over-citation rather than hallucination, slight precision drag.
- Q5: Gold node `yt-programming-workflow-is` at rank 1. Answer is concise, hits all three atomic facts (perception inaccurate, iterative debug-fix loop, search-driven problem-solving over typing speed). Trailing `yt-software-1-0-vs-software` citation is unnecessary but not contradicted by the prose. Solid.

## Per-stage observations
- Chunking: Each gold zettel appears coherently anchored to a single node id (no fragmentation across multiple ids per source); answers stay within one document's voice. No evidence of chunk-boundary artifacts in the prose.
- Retrieval: Markedly tighter than iter-02 — candidate sets shrunk from 3-5 docs (with off-topic noise like `yt-effective-public-speakin`, `yt-zero-day-market-covert-exploits`) down to 1-3 high-precision hits. Gold@1 appears to hold for all 5 queries. Recall preserved.
- Reranking: Reranked order matches retrieved order in every query — reranker is either pass-through or reinforcing first-stage. Given retrieval already places gold@1, this is acceptable; can't tell from text alone whether reranker is adding value or idle.
- Synthesis: Faithful, well-structured, citation-dense. Two minor comprehensiveness gaps (AlphaGo in Q3, "amplifier" framing in Q4). One small extrapolation in Q1 ("Constitutional AI"). No outright hallucinations spotted. Q4 over-cites with two unused gold-adjacent docs.
- KG signal (graph_lift): unknown without evaluator scores - leave blank
