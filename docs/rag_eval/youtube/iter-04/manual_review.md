# iter-04 manual review — youtube — 2026-04-25

eval_json_hash_at_review: "NOT_CONSULTED"
estimated_composite: 87
estimated_retrieval: 92
estimated_synthesis: 84

## Per-query observations
- Q1 (Karpathy two-stage LLM): Gold `yt-andrej-karpathy-s-llm-in` retrieved at rank 1 and cited. Answer faithfully covers pre-training (next-token prediction, base "document completer") and fine-tuning (SFT + RLHF/Constitutional AI -> assistant). Adds the "blurry JPEG of the web" framing which is plausible but not in the reference; minor embellishment, not a hallucination of fact. The probe Zettel `yt-effective-public-speakin` was NOT cited. Score: high.
- Q2 (Transformer scaling): Single gold `yt-transformer-architecture` retrieved, reranked, and cited cleanly. Answer correctly attributes scaling to replacing sequential recurrence with parallelizable self-attention and notes the RNN hidden-state bottleneck. Faithful, comprehensive, no probe contamination. Score: very high.
- Q3 (Software 1.0 vs 2.0): Gold `yt-software-1-0-vs-software` cited correctly. Covers both axes (paradigm + dev cycle), data-curator role, error-fixing-via-data-augmentation. Reference also mentions AlphaGo and gradient descent / loss design — answer mentions AlphaGo but does not explicitly name gradient descent or loss functions. Slight comprehensiveness gap. Score: high.
- Q4 (LeCun critique + JEPA): Gold `yt-lecun-s-vision-human-lev` ranked 1 and cited. Notably an improvement over iter-03 — secondary citations are now `yt-andrej-karpathy-s-llm-in` and `yt-software-1-0-vs-software` (LLM-relevant) rather than the iter-03 distractor `yt-dan-shapiro-overcoming-t`. Answer captures System-1-only critique, hallucinations, data bottleneck, JEPA, world model, perception module. Misses the reference's "AI as amplifier of human intelligence" framing. Probe NOT cited. Score: high.
- Q5 (programming perception): Gold `yt-programming-workflow-is` cited at rank 1. Answer is concise, faithful, and matches the reference's debug-loop framing. The secondary citation of `yt-software-1-0-vs-software` is unnecessary but not harmful. No hallucinations, no probe contamination. Score: high.

## Probe contamination check
The new distractor `yt-effective-public-speakin` (added this iter as a similar-looking YouTube Zettel) does NOT appear in retrieved/reranked/cited lists for any of Q1-Q5. Retrieval correctly rejected it. Trend vs iter-03: q4's irrelevant `yt-dan-shapiro-overcoming-t` citation was replaced by topically-coherent LLM Zettels, suggesting reranker discrimination improved or was at least stable in the face of the added distractor.

## Per-stage observations
- Chunking: Stable; no signs of chunk fragmentation in any answer (citations resolve to the right Zettel for each topic).
- Retrieval: Strong. All five gold nodes ranked first. The added probe distractor was never surfaced in top-k for any query — good semantic separation between LLM/programming content and the public-speaking probe.
- Reranking: Q4 secondary slots cleaned up vs iter-03 (no more Dan Shapiro intrusion). Q5's `yt-software-1-0-vs-software` co-citation is the only remaining dilution and it is benign.
- Synthesis: Faithful overall. Two minor comprehensiveness gaps (Q3 missing gradient-descent/loss vocabulary; Q4 missing the "amplifier of human intelligence" thesis). Q1 has a plausible but unverified "blurry JPEG" phrase — likely from source but flagged as something to confirm. No outright hallucinations detected.
- KG signal (graph_lift): unknown without evaluator scores - leave blank
