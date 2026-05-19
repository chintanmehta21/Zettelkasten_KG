# Consolidated RAG/KG Remediation Plan (operator approval)

Sources: comprehensive E2E audits A (extract→summarize→persist→chunk), B (kg_features+knowledge_graph), C (rag online+eval) + research R1 (chunk-source) + R2 (data-hygiene). Chunking root-fix (multi-chunk persist via `build_canonical_chunks`, dead `_schedule_rag_chunks` purged, `backfill_rechunk_v2.py`) is **already implemented** (397 tests pass) — pending the R1 source-policy tweak below + the gated backfill run.

## KEY RESEARCH DECISION — R1: chunk the SUMMARY, not raw text (corrects my earlier "chunk raw" framing)
Live-verified: our `body_md` summaries are unusually dense/self-contained — numbers, named entities, verbatim attributed quotes all survive (R1 quoted real Naruto examples: India-1991 "67 tons of gold… deficit 8%→10.4%"; r/IAmA verbatim pull-quote). Citations resolve to the zettel and the snippet shown to the user IS the summary; chunking raw text would break citation/faithfulness coherence. Summary-indexing is standard for curated corpora (LangChain MultiVector summary-mode 2024; RAPTOR ICLR 2024 +20% multi-hop). Therefore **D1 fix = make summary the PRIMARY chunk source** (precedence flip in `_choose_chunk_source_text`; raw only a fallback) — NOT "plumb raw_text into chunks". This is cheapest, **zero re-ingestion**, no schema change, improves faithfulness. Defer Contextual-Retrieval/both (option c) until summary-retrieval demonstrably plateaus. (Anthropic Contextual Retrieval 2024; RAPTOR arXiv:2401.18059; Snowflake chunking 2024-25.)

## Defect ledger + fixes

| ID | Sev | Defect | Fix | Risk note |
|----|-----|--------|-----|-----------|
| Chunking | P1 | (DONE) persist built 1 monolithic chunk | multi-chunk via `build_canonical_chunks` (shipped) + **R1 precedence flip: summary primary** in `_choose_chunk_source_text` (1-line + docstring) | low; behavior-correct |
| D2 | P1 | 52% zettels 0 chunks / single-chunk legacy | run `ops/scripts/backfill_rechunk_v2.py` Naruto-scoped (gated prod) — re-segments from stored summary, no re-ingest | gated prod write (eval-class authorized) |
| D3 | P1 | chunker SHORT_FORM (reddit/github) → 1 chunk for 16k body | size-gate: atomic only if <~800 tok, else recursive (`chunker.py` SHORT_FORM logic) | low; chunker-internal |
| D10 | P1 | zero-chunk persist returns HTTP 200 "success" | surface degraded flag in PersistenceOutcome when chunks==0 on non-empty source | low |
| B1 | P1 | `/api/graph` resolves edges only via empty `chunk_node_mentions` → all 58 edges dropped → KG renders edgeless | `_v2_assemble_graph` fallback: kg_node→`kg_nodes.metadata.canonical_zettel_id` when mentions empty | low; read-path additive |
| B2 | P1 | no prod path writes `chunk_node_mentions` (B1 root cause + structural signal dead) | `populate_kg_for_zettel`: after upsert_node, insert chunk_node_mentions for the zettel's canonical_chunks | low; additive write |
| C#1 | P1 | harness silently reclassifies gold-resolution-miss as "refuse" → mis-scores correct answers | distinguish declared-refusal (empty expected) vs resolution-failure; latter = unscorable/hard-fail, never silent refuse | eval-only; unblocks trustworthy scores |
| D4 | P2 | `RagSourceType` missing 5 members → silent WEB coercion | add 5 members + long/short bucket map + log-warning on coercion + drift test; pairs w/ staged mig47 | additive |
| D5 | P2 | re-upsert leaves stale higher-idx chunks | prune `DELETE WHERE chunk_idx>=N` after upsert_chunks (NOT in golden RPC) | 1 extra low-QPS DELETE |
| D6 | P2 | duplicate canonical rows same url, divergent hash | one-off gated `_v2/48` dedup migration (keep source-hash/newest, repoint FK children) + recurrence unique-index | **gated prod migration; low-traffic; run BEFORE D5** |
| D7/D8 | P2 | thin/low-confidence extraction still persisted (hallucination-prone) | 2-signal gate: reject only if conf=low AND <source-type floor; else quarantine `quality_flag=thin`; ship **quarantine-first**, reject-tier gated on corpus length-distribution review | false-positive blast radius → quarantine-first |
| B3 | P2 | scoring `(cos+1)/2` compresses cosines → strength 0.55-0.70, tiers degenerate | raw cosine clamped [0,1] + re-tune `EDGE_CREATION_THRESHOLD` | **touches locked D-KG-1 kernel** — genuine degeneracy bug, not a weight retune; flagged |
| C#4 | P2 | critic fail-open → outage passes all as supported | error path returns distinct verdict / surfaces critic_error conservatively | low |
| C#5 | P2 | LOOKUP double-floor over-prunes single-chunk → 1 cand | lower LOOKUP rerank-input floor or raise LOOKUP context min-keep ~3 | composes w/ Phase-D guards |
| C#6 | P2 | retrieval sub-score measures post-cascade, not 9-cand set | expose pre-rerank ids OR document semantics (no silent recall understatement) | eval-only |
| D9 | P3 | dead `hook.py`/`upsert.py` | delete those 2 + exports + their tests; retire LEGACY `backfill_chunks.py`; keep embedder/kg_population/metadata_enricher/content_selection/chunker | hygiene; pre-removal ref-audit (CI yaml/scripts) |
| B4/C#3 | P3 | stale scoring docstring; `_resolve_nodes` None-guard | docstring truth; `if scope_filter is None: ScopeFilter()` | trivial |

## Sequencing (data-safety ordered, per R2)
1. **D6 dedup migration** (gated prod) — must precede D5 (FK repoint must settle before chunk-prune).
2. **Chunking R1 flip + D3 + D10 + D4 + D5** (one persist-path change set) + apply staged **mig47**.
3. **B1 + B2** (KG render + mention writes) — unblocks visible KG.
4. **C#1** (eval-scoring correctness) — required before any iter score is trusted.
5. **D7/D8 quarantine-first**; reject-tier deferred to a corpus-distribution review.
6. **B3** scoring-kernel (re-tune threshold, re-verify tiers).
7. **C#4, C#5, C#6, D9, B4, C#3** (robustness/hygiene).
8. Run `backfill_rechunk_v2.py` Naruto (gated) → KG/chunk_node_mentions regenerate → **end-to-end live verification** → resume eval loop.

All fixes minimal, additive, droplet-safe (steady-state +0 RAM/CPU; only delta = 1 extra low-QPS DELETE per re-ingest). Gated prod ops: D6 migration, mig47, the Naruto rechunk backfill (eval-class authorized earlier). Prod-wide rollout (all users) stays deferred to the merge runbook per the earlier decision.
