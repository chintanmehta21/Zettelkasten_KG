# iter-01 Scorecard — `knowledge-management` Kasten

## Final comparison: iter-06 (youtube/AI-ML) vs iter-01 (common/knowledge-management)

| stage | iter-06 (youtube AI/ML) | **iter-01 (common KM)** |
|---|---|---|
| chunking | n/a (live ingest, not measured) | n/a (live ingest, not measured) |
| retrieval | **100** (gold@1 on 4/4 successful queries; new Zettel found) | **BLOCKED** — Kasten chat returns "no Zettels in selected scope" because **T2 SQL migration `2026-04-26_fix_rag_bulk_add_to_sandbox.sql` was not auto-applied to prod Supabase during deploy 6f93b80**. Same root-cause bug iter-06 documented (line 31 of iter-06/README.md) — exactly what T2 was committed to fix. |
| reranking | **~95** (top score ≥0.987 on every successful query; distractor gap >100×) | **BLOCKED** — same reason; reranker never runs because retrieval pool is empty |
| synthesis | **~92** (substantive 600-1700 char answers, full citations, faithful) | **BLOCKED** — synthesis tier returns the templated "no zettels" string for every query |
| graph_lift | n/a (no ablation pass) | n/a (cannot ablate what doesn't run) |

## Per-query gold@1 + score margins

| query | iter-06 result | **iter-01 result** |
|---|---|---|
| q1 | gold@1, 0.998, 1.34× margin | empty-scope error |
| q2 | gold@1, 0.987, 2.31× margin | empty-scope error |
| q3 | gold@1, 0.999, 500× margin | empty-scope error |
| q4 | quota fail | not run |
| q5 | quota fail | not run |
| q6 (NEW Zettel) | gold@1, 0.996, 1.29× margin | not run |
| q7..q10 | (iter-06 had only 6 queries) | not run |

## Composite

| iter | mode | composite | gold@1 rate | new-Zettel handling |
|---|---|---|---|---|
| 06 | browser (AI/ML) | **~95**† | 4/4 (q4/q5 quota) | NEW Zettel gold@1 within 5 min of ingest ✓ |
| **01 (common)** | **browser (KM)** | **— (deploy gap)** | **0/0 — Kasten reports empty** | **N/A — bug pre-empted retrieval** |

† iter-06 estimated from rerank scores + answer quality; not RAGAS composites.

## Verdict

iter-01 ships ALL the planned code (24 plan tasks + 8 UX bugs + per-Q-A audit), but the deploy pipeline does not auto-apply Supabase migrations. The `rag_bulk_add_to_sandbox` SQL fix sits unapplied in prod, so the brand-new Kastens look populated in `/home/kastens` (counter reads from creation-time selection) but are empty in the `rag_sandbox_members` table (where chat reads from). **The exact bug iter-01 was meant to close is still open in prod.**

Path to a real iter-01 vs iter-06 comparison:

1. Apply the 5 iter-01 SQL migrations to prod Supabase manually (one-time `psql -f` x5).
2. Re-add the 7 zettels to the existing KM Kasten via the now-fixed RPC (single API call, populates `rag_sandbox_members`).
3. Re-run the strict-Chrome eval over q1-q10. Expected: composite ~comparable to iter-06 since the underlying retriever/reranker/synthesizer are unchanged for already-enriched chunks; net new behaviour comes from boosts (T8/T9/T20) which are dormant on chunks where `metadata_enriched_at IS NULL`.

These three steps belong in **iter-02 task D-1** (deploy migration auto-apply) which is the new highest-priority task in the iter-02 backlog. The remaining 25 KAS-* page UX issues become the second iter-02 batch.
