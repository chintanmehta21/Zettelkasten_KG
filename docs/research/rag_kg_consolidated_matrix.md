# KG/RAG Consolidated Improvement Matrix

Synthesis of `rag_kg_improvements_1.md` + `rag_kg_improvements_2.md`, **grounded against verified current code** (5 read-only scouts, 2026-05-17). Convergent = both reports recommend it (higher priority). Reality-delta = report assumption contradicted by code.

## 0. Reality deltas (reports vs. verified code) — MUST resolve before acting

| # | Report claim / assumption | Verified reality | Implication |
|---|---|---|---|
| D1 | "Add subtle edge thickness/opacity for strong/med/weak" (both, §5.2.1) | **Already implemented** — `knowledge_graph/js/app.js:69-76` maps `connection_strength`→width(0.5–3.0)+opacity(0.2–1.0) | Re-scope to **edge color = amber** (`app.js:778-784` is blue `rgba(100,130,200)`, off-spec) + verify-only. Not a re-build. |
| D2 | Two-level scoring layers on `kg_features/scoring.py` | `scoring.py` (D-KG-1 scorer 0.55 emb+0.25 tag+0.15 struct+0.05 temporal) is **DEAD CODE — zero prod callers**; docstring lies; `backfill_links.py` doesn't exist | KG edge weights actually come from `kg.kg_edges`; route defaults null→**1.0** (`api/routes.py:421-432`) → false "Strong". **This is the root cause of "connections look random."** Must verify true edge-create path before designing two-level. |
| D3 | rag_eval reuses iter-12 scoring/scripts | Only runner is `eval_iter_03_playwright.py` driving **LIVE prod** `zettelkasten.in` as Naruto via bearer JWT. **No offline harness.** `score_rag_eval.py`/`rag_eval_loop.py` BROKEN (import retired `supabase_kg`) | rag_eval_v2 needs a **new offline/in-process harness** OR per-iter prod deploys. Major architecture decision (Q2). |
| D4 | Ingest from `docs/kasten_skeletons/kasten1.md`/`kasten2.md` ("Psychedelic drugs"/"Economics") | **Files & Kastens do not exist anywhere in repo.** Existing corpus = 1 Kasten "Knowledge Management" | Missing input — BLOCKER (Q1). |
| D5 | Re-enable entity-anchor as KG feature (report2 §5.1.3) | `kg_features/entity_extractor` **deleted** 2026-05-11; but `rag_pipeline/retrieval/entity_anchor.py` still calls `kg.resolve_entity_anchors_v2` (works) | Entity anchors exist in RAG retrieval, not in kg_features. Scope = wire existing v2 RPCs, not rebuild NER. |

## 1. P1 — correctness / data integrity / broken flows / v2 write-fetch / endpoints

| ID | Recommendation | Src | Affected (verified) | Risk | Test | Approval? |
|----|---|---|---|---|---|---|
| P1-1 | Fix broken legacy PageRank RPC: `rag_subgraph_for_pagerank` unqualified, v1 `p_user_id` sig, no v2 migration → graph_score silently 0.0 in prod | derived (both depend on graph signals) | `rag_pipeline/retrieval/graph_score.py:85`; needs new `supabase/website/_v2/*.sql` | **schema migration** | v2 integration + unit regression | **YES (new SQL migration)** |
| P1-2 | `use_supabase_v2()` defaults **v1**; FastAPI route never sets `DB_SCHEMA_VERSION`; v2 persist failure swallowed → HTTP 200 `supabase=false`. **The core v2 write/fetch issue.** | user-stated | `core/db_version.py:11`, `core/persist.py:454`, `api/zettels_routes.py` | infra-default flip (may be deliberate) | endpoint + persist + failure-surfacing | **YES (infra default)** |
| P1-3 | Port 6 `ops/scripts/*` + `lib/rag_eval_kasten.py` off retired `website.core.supabase_kg` → `get_v2_client()`. Unblocks `score_rag_eval.py`, `rag_eval_loop.py` (needed for eval) | derived | `ops/scripts/{score_rag_eval,rag_eval_loop,apply_kg_recommendations,audit_gold_expectations,check_corpus_drift}.py`, `lib/rag_eval_kasten.py` | low | import smoke + dry-run | no |
| P1-4 | Wire a real connection-strength scorer into the live edge-create path (root cause of "random connections"); decide scoring.py-revive vs. in-place | both §5.1.1 / KG | `kg_features/scoring.py` (dead), real path in `core/persist.py:601`→`kg.kg_edges` | visible KG change | scoring unit + edge-create integration | **YES (KG semantics)** |
| P1-5 | Retire/gate `graph.json` dual-write on every persist (`persist.py:461→554`); unbounded growth + global leakage via anon fallback | both §5.1 / report1 | `core/persist.py:461,554`, `core/graph_store.py:55-104`, `api/routes.py:580` | anon fallback UX | persist + fallback | **YES (retires a surface)** |
| P1-6 | Create canonical `website/api/module_runners/create_kasten`; consolidate `/api/rag/sandboxes` route to route through it; add idempotency (no double-submit dedup today) | user-required | new runner; `api/sandbox_routes.py:357`, `supabase_v2/repositories/rag_repository.py:21` | route behavior | accept/reject/idempotency/scope/flow | **YES (new canonical API)** |
| P1-7 | Deterministic dedup: `content_hash`=sha256(LLM summary) → dup canonical rows; `_first()` raises on empty → swallowed invisible data loss | derived | `core/persist.py:488`, `supabase_v2/repositories/content_repository.py:274` | dedup semantics | dedup + empty-result-surfacing | **YES (dedup key change)** |

## 2. P2 — robustness / eval quality / edge cases / observability

| ID | Recommendation | Src | Affected | Risk | Test | Approval? |
|----|---|---|---|---|---|---|
| P2-1 | Two-level **global + workspace** connection strength (`global_strength`, `workspace_strength`, `workspace_id`, `matched_via`); personal-only drives visible edges | **both (convergent)** | `kg_features/scoring.py`, `kg` schema add, `api/routes.py` assembly | schema add | per-workspace histograms + isolation | **YES (schema + KG semantics)** |
| P2-2 | Conservative pseudo-tags `speaker:` `source_domain:` `modality:` (high-confidence only); stored once, reused by KG+RAG | **both (convergent)** | ingest/enrichment, `kg_features/scoring.py` tag set | tag cardinality | cardinality monitor + speaker-query | yes (tag taxonomy) |
| P2-3 | Percentile/confidence-gap strength buckets vs fixed 0.55/0.7 | **both (convergent)** | `kg_features/scoring.py:41`, route filter | label drift | bucket distribution | no (P1-4 follow-on) |
| P2-4 | Query-adaptive dense/sparse/graph mix: entropy/confidence modifier **over existing class-static RRF** (report1=RRF✓ already, report2=entropy → complementary) | **both (complementary)** | `rag_pipeline/retrieval/hybrid.py:158-179,1137` | retrieval regression | per-class no-degradation vs static baseline | yes (retrieval core) |
| P2-5 | KG-aware expansion/rerank feature for THEMATIC/MULTI_HOP (graph proximity) — depends on P1-1 | **both** | `hybrid.py`, `rerank/`, `retrieval/entity_anchor.py` | candidate-set blowup | per-class gold@k before/after | yes (retrieval core) |
| P2-6 | Two-phase ingestion: sync core (meta+chunk+embed+canonical rows) / async enrichment (semantic chunk, entities, KG features) | **both (convergent)** | ingest pipeline, new job table | latency SLA + idempotent jobs | concurrent-ingest + SLA | **YES (ingestion architecture)** |
| P2-7 | Edge-resolution telemetry (silently dropped edges `routes.py:471-476`); null strength ≠ 1.0 (false Strong) | derived/KG | `api/routes.py:421-476` | minor | edge-mapping join test | no |
| P2-8 | Test hardening: `service.py` runtime+non-UUID, SSE path, Supabase-write assertions, concurrency/race, edge-mapping join, BOLA/user-isolation (Naruto-scope) | both §5.5 / user | `tests/**` | none | the tests themselves | no |
| P2-9 | rag_eval_v2 multi-Kasten harness: 2 Kastens, hold-out, perturbation, cross-Kasten aggregation, no overfitting | **both + user** | `docs/rag_eval_v2/`, `scripts/` | eval validity | self-checking scripts | **YES (eval architecture, Q2)** |

## 3. P3 — cleanup / polish (no behavior change)

| ID | Recommendation | Src | Affected |
|----|---|---|---|
| P3-1 | Edge color → amber on `/knowledge-graph` (blue `rgba(100,130,200)` off-spec); width/opacity already done | both §5.2.1 (re-scoped) | `js/app.js:778-784` |
| P3-2 | Targeted readability: `hybrid.py` (~1900L, dead constants), `orchestrator._finalize_answer` (~260L) — no behavior change | report2 §2 | `hybrid.py`, `orchestrator.py:954` |
| P3-3 | Remove `scoring.py` docstring lie, stale `__init__.py:5`, extend CI guard to cover `scoring.py` | derived | `kg_features/*`, `tests/unit/test_kg_features_unreachable.py` |
| P3-4 | Drop deprecated dangling attrs (`kasten_freq_store` no-op, `RetrievalPlanner` shim) | report2 §2 | `hybrid.py:521`, `service.py:84` |

## 4. Proposed decomposition (each = own spec→plan→exec, gated)

- **A. P1 correctness pack** — P1-1,2,3,7 (+P3-3). Bug fixes/unblockers. Lowest product risk; highest leverage. Several touch schema/infra → per-item approval.
- **B. KG quality** — P1-4,5 + P2-1,2,3 + P3-1. Root-causes "random connections". KG-semantics + schema → approval.
- **C. create_kasten API** — P1-6 + route consolidation + P2-8 (API/isolation tests).
- **D. RAG retrieval** — P2-4,5,6. Retrieval-core changes; gated against baseline regression.
- **E. rag_eval_v2 + Naruto ingestion + iteration loop** — P2-9; depends on A–D + Q1/Q2/Q3.

## 5. Open blockers (need user decision — see chat)

- **Q1** Kasten source links missing (D4).
- **Q2** Eval architecture: new offline harness vs live-prod deploy-per-iter (D3).
- **Q3** Production-Supabase write authorization as canonical Naruto + credential availability.
- **Q4** Confirm phased decomposition A→E with approval gates vs. single pass.

Residual research gap (not blocking matrix): exact `kg.kg_edges` write path / weight origin — to verify before B design (Research Discipline).
