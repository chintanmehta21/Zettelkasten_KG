# Phase B — KG Quality: Design (grounded)

## Root-cause diagnosis (verified, file:line)

The "connections look random" complaint is **not** a scoring-tuning problem. The v2 KG-population path does not exist:

1. **Add Zettel creates ZERO kg nodes/edges.** `persist.py:566-614` writes only `content.*`. The v1 node/link helpers were deleted in the DB-v2 purge (`persist.py:654-657,702-707`) and never rebuilt. `KGRepository.add_edge`/`upsert_node` (`kg_repository.py:16,46`) are dead — zero prod callers. No RPC/trigger/job inserts `kg.kg_edges`.
2. **Existing edges are frozen migration artifacts.** Only writer ever = one-shot `ops/scripts/refactor_v2/03_backfill_kg.py:44-55`, copying legacy `graph_store.py` shared-tag-overlap links; its INSERT **omits `weight` and `connection_strength`** → NULL.
3. **Read path renders flat 1.0.** `routes.py:498-499` feeds `edge.get("weight")` (always NULL) to `_normalize_connection_strength` (`routes.py:421-432`, `None→1.0`). It reads `weight`, **not** the `connection_strength` column (`42_kg_connection_strength.sql`). No strong/medium/weak tiering applied on read.
4. `kg_features/scoring.py` (D-KG-1: 0.55 emb+0.25 tag+0.15 struct+0.05 temporal) is correct but **dead** (zero callers).

## STRUCTURAL signal — implemented (restored 2026-05-18)

The hook previously passed `structural=None` (kg_population.py ~line 281) so the 0.15-weighted slot was inert and `matched_via.structural` was a hard `0.0`. It is now populated by `kg_population._structural_map` (scorer **unchanged** — D-KG-1 weights/kernel/thresholds untouched; the scorer still squashes via `count/(count+2)` at `scoring.py:101-118`).

**PRIMARY — shared-chunk co-mention overlap.** Source: `kg.chunk_node_mentions(kg_node_id, canonical_chunk_id)` (`supabase/website/_v2/03_kg_schema.sql:48-58`, index `idx_chunk_node_mentions_node`). ONE bounded query: `select kg_node_id, canonical_chunk_id where kg_node_id IN (new ∪ ≤K candidates)` (≤26 ids), `.limit(5000)`. `cooccur(new,cand) = |chunks(new) ∩ chunks(cand)|` (distinct shared canonical chunks). Reuses the exact `.in_("kg_node_id", ids)` pattern of `kg_repository.py:145-196` (`list_node_zettel_mapping`).

**SECONDARY / FALLBACK — Adamic-Adar over `kg.kg_edges`.** `AA(u,v) = Σ_{w ∈ N(u)∩N(v)} 1/log(deg(w))`, guarding `deg(w) ≤ 1` (log domain). Workspace-fenced selects on the `(workspace_key, src_node_id)` / `(workspace_key, dst_node_id)` composite indexes (`03_kg_schema.sql:44-45`): **Q1+Q2** key on src/dst over the seed set (new node ∪ candidates) to materialise `N(new)` and `N(cand)`; **Q3** (a src+dst pair over the *common-neighbour* set only, hard-capped at `_AA_NEIGHBOUR_CAP=500`) resolves each common neighbour's **true degree** — seed-incident edges alone undercount `deg(w)` (only w's edges touching a seed are visible), which would inflate `1/log(deg)` and wrongly trip the `deg≤1` guard. No per-neighbour fan-out, no recursion, no all-pairs. Cold graph → `0`.

**Combination.** `effective = shared_chunk_cooccur + round(_ADAMIC_AA_WEIGHT * adamic_adar)` is fed to the unchanged `count/(count+2)` kernel. `_ADAMIC_AA_WEIGHT = 0.5` (module constant, conservative): a strong AA (~2.0) contributes `round(1.0)=1` — at most one extra co-mention's worth — so shared-chunk overlap stays **dominant whenever non-zero**, while AA still registers when there are edges but no shared chunks yet (cold case) and lightly boosts when both fire.

**`matched_via` (auditable).** `{"structural": <squashed [0,1)>, "structural_shared_chunks": <int cooccur>, "structural_adamic_adar": <float AA>, "embedding": ..., "tag": ..., "temporal": ..., "composite": ...}`.

**Per-add structural cost: a small constant — at most 5 PostgREST queries** (1 shared-chunk + Q1/Q2 seed-incident + Q3's src/dst degree pair; drops to 3 when there are no common neighbours since Q3 short-circuits), all index-backed and `.limit()`-guarded, independent of workspace size. **Cold-start / failure:** empty intersection or cold graph → `0.0` gracefully; ANY exception in the structural computation is logged and degrades to `structural=None` (pre-restore behaviour) — the fire-and-forget hook NEVER raises.

Net: the graph is a frozen, uniformly-weighted tag-coincidence topology; new zettels never connect.

## Chosen approach (mirrors existing codebase patterns)

`persist.py:670-681` already fires post-persist async enrichment via `asyncio.create_task(_run(), name="rag-chunks-...")` (the RAG-chunk hook). The `pipelines` v2 schema already models this: `pipelines.pipeline_runs(kind IN ('kg_extract','metadata_enrich','recompute_signals',...), status...)` + `pipeline_run_items` (`_v2/05_pipelines_schema.sql:5-27`).

**Design:** add a KG-population enrichment hook mirroring the rag-chunks pattern:

- **Sync (Add Zettel, unchanged latency):** persist `content.*` as today (+ P1-7 stable hash).
- **Async hook (new, fire-and-forget `asyncio.create_task`):** for the persisted zettel:
  1. upsert `kg.kg_nodes` (workspace-scoped) + node embedding (reuse `_generate_node_embedding`, `embeddings.py`).
  2. candidate set = top-K most-similar existing **workspace** nodes via `kg.match_kg_nodes` kNN (bounded; not all-pairs — scale-safe on 1-vCPU / 10k+ target).
  3. score each candidate with the **D-KG-1 scorer** (`scoring.py`, wired at last).
  4. upsert `kg.kg_edges` with two-level strength.
  5. track via `pipelines.pipeline_runs(kind='kg_extract')` for idempotency + observability (skip if a succeeded run exists for the zettel).
- **Read path fix:** `routes.py` reads `connection_strength` (not `weight`), applies percentile/tier buckets (strong/med/weak) from workspace distribution, edge color → amber `#D4A024` (currently blue `rgba(100,130,200)`; UI rule).

## Schema change (new `_v2` migration, additive)

`kg.kg_edges` add: `workspace_strength numeric(4,3)`, `global_strength numeric(4,3)`, `matched_via jsonb` (which signals fired: embedding/tag/structural/temporal/entity). Render uses `workspace_strength` only; `global_strength` stored for future cross-user analytics, never surfaced. New idempotent migration `_v2/46_*.sql` (CREATE OR REPLACE / ADD COLUMN IF NOT EXISTS); prod-apply gated.

## Reports alignment

Convergent with both reports: two-phase ingestion (1 §"Fast ingest, lazy analytics" / 2 §5.3.2), two-level global+workspace (1 §"Split global vs workspace" / 2 §5.1.1), percentile buckets (both), subtle edge encoding already present (width/opacity done; only color off-spec). Pseudo-tags (P2-2) feed the D-KG-1 tag signal — included in the async hook's tag extraction.

## Decisions requiring sign-off (schema + KG-semantics + persist-sequence + scale)

See chat AskUserQuestion: (Q1) async-hook vs sync vs worker; (Q2) D-KG-1 scorer as-is; (Q3) two-level schema + read-path/percentile/amber; (Q4) bounded kNN candidate scope.
