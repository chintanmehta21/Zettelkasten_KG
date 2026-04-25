# iter-05 manual review — youtube — 2026-04-25

eval_json_hash_at_review: "NOT_CONSULTED"
estimated_composite: 86
estimated_retrieval: 95
estimated_synthesis: 80

## Per-query observations
- h1 (tiers and buyers): Correct gold Zettel `yt-zero-day-market-covert-exploits` retrieved at rank 1 with rerank_score 0.994 and cited consistently. Answer correctly identifies the three tiers (white/gray/black) and names bug bounties, government acquisition, and criminal use. The example framing ("US hacker selling to NSA = gray; selling to Russia's Operation Zero = black") is faithful to the source's own geopolitical-relativity framing and matches reference atomic facts. Minor weakness: reference expects explicit mention of Zerodium and LockBit as exemplars per tier; the answer mentions Operation Zero and NSA but omits Zerodium in h1 and omits LockBit. Slight under-coverage vs reference, but no hallucination. Off-topic neighbors (cannabis, DMT) appear in retrieval but rerank scores are ~3e-5, well below threshold and not cited substantively.
- h2 (Zerodium / pricing): Gold Zettel cited at rank 1 (rerank 0.980). Answer is concrete and grounded: $100K passcode bypass, $2–2.5M zero-click full takeover, $20M Operation Zero attack chain. Aligns with the source's own price list. Reference atomic facts about "remote zero-click full-chain commands highest" and "local PE / older platforms pay less" are partially covered (full takeover is mentioned as highest; the lower-tier comparison is implicit via the $100K passcode-bypass example). Comprehensive and faithful.
- h3 (nation-state + law enforcement): Gold Zettel cited at rank 1 (rerank 0.987). Answer covers Stuxnet, NotPetya, Khashoggi/Saudi tracking, Operation Triangulation, and the LockBit takedown — all source-grounded. Both halves of the reference (cyber-warfare supply chain + law-enforcement use of brokered zero-days) are addressed. The "wealthy/well-contracted countries gain disproportionate capability" thread from the reference is not made explicit; the answer leans on examples rather than the structural argument. No hallucinations detected.

## Per-stage observations
- Chunking: Chunks surfaced are tightly topical — h2 in particular pulled the exact price-list chunk verbatim, indicating chunk boundaries preserve the bullet structure of the source summary. No fragmentation issues observed.
- Retrieval: Gold node is rank-1 across all three held-out queries with strong semantic margin (top rerank ~0.98–0.99 vs runners-up at 1e-5–3e-5). Generalization to unseen queries on a held-out Zettel looks robust.
- Reranking: Reranker maintains rank-1 ordering in every case and produces a very wide score gap to distractors, suggesting the cross-encoder generalizes without overfitting to tuning queries.
- Synthesis: Faithful and well-cited; every claim carries an `[id=...]` citation to the gold node. Slight under-coverage on the structural/abstract dimensions of the reference (tier-by-buyer mapping in h1; explicit highest-vs-lowest price contrast in h2; geopolitical-asymmetry argument in h3) — answers favor concrete examples over the reference's more analytical framing. No fabricated facts.
- KG signal (graph_lift): unknown without evaluator scores - leave blank
