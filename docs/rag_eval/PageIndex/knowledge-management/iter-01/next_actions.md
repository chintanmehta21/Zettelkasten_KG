# PageIndex Knowledge Management iter-01 Next Actions

## Gates

- Recall@5: 0.882
- MRR: 0.885
- NDCG@5: 0.928
- p95 latency: 17103.0 ms
- citation correctness: see `manual_review.md` for expected citation versus cited-node comparison per query.

## Actions

1. Use `q9` as the first iter-02 target because it has the largest retrieval/citation gap in `eval.json`.
2. Replace the local Markdown fallback with the packaged PageIndex client once the upstream repo publishes install metadata or a vendored package boundary is approved.
3. Re-run with a warmed Gemini key pool or lower answer fanout if p95 latency remains above the product target.
