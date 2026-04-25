You are an INDEPENDENT cross-LLM reviewer for a RAG evaluation iteration.
You MUST be blind to the evaluator's output. Do NOT read any evaluator score
artifacts (the auto-scored JSON files in this iter directory).

You may read ONLY these files in iter-05/:
- manual_review_prompt.md (this file's full prompt)
- queries.json
- answers.json
- kasten.json
- kg_snapshot.json

Stamp `eval_json_hash_at_review: "NOT_CONSULTED"` at the top of manual_review.md you write.

For each of the queries, read the question, the system's answer, the citations, and the gold/reference.
Estimate the composite score from your honest reading. Be specific:
- Did the right Zettel get cited?
- Was the answer faithful to the source?
- Were any hallucinations present?
- Was the answer comprehensive against the reference?

Schema for manual_review.md:

```
# iter-05 manual review — youtube — <date>

eval_json_hash_at_review: "NOT_CONSULTED"
estimated_composite: <0-100>
estimated_retrieval: <0-100>
estimated_synthesis: <0-100>

## Per-query observations
- Q1: ...
- Q2: ...
- Q3: ...
- Q4: ...
- Q5: ...

## Per-stage observations
- Chunking: ...
- Retrieval: ...
- Reranking: ...
- Synthesis: ...
- KG signal (graph_lift): unknown without evaluator scores - leave blank
```

Write the file to: docs\rag_eval\youtube\iter-05/manual_review.md
Do NOT compute exact scores; estimate as a human reviewer would.
Be honest about uncertainty.
