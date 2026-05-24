# Phase 1-4 adversarial audit — 2026-05-24

Goal: find every residual issue so we do not have to touch these modules again.

Process:
1. Ruff lint on every Phase 1-4 touched Python module.
2. Focused pytest sweep on the full KG + KG-API surface.
3. E2E stress test on `/api/graph` (50 serial, 50 concurrent, 100 burst).
4. Background dispatch of `superpowers:code-reviewer` against the full branch diff with adversarial brief.
5. Triage every finding into FIX / SKIP-WITH-RATIONALE / FALSE POSITIVE.

## 1. Ruff — 4 findings, all fixed

| File | Issue | Fix |
|---|---|---|
| `routes.py:19` | `bucket_for_strength` imported but unused | dropped (used elsewhere in `view_graph` runner, not here) |
| `routes.py:21` | `get_graph` imported but unused | dropped (anon path now goes through `view_graph`) |
| `pseudo_tags.py:29` | `urlsplit` imported but unused | dropped (T4.4 switched to tldextract) |
| `view_graph.py:218` | `cz_str` assigned never used | dropped + cleaned the surrounding 8 lines |

Re-run after fixes: **All checks passed.**

## 2. Pytest — 191/191 PASS (KG + KG-API)

Suites covered:
- `tests/unit/website/{test_kg_population,test_persist_v2_correctness,test_tag_normalize,test_pseudo_tags,test_graph_store_find_links}.py`
- `tests/unit/kg_features/` (scoring, analytics, embeddings, etc.)
- `tests/unit/api/{test_v2_assemble_self_loop,test_view_graph_runner}.py`
- `tests/unit/ops/test_backfill_kg_edge_strength.py`
- `tests/unit/supabase_v2/test_schema_files.py`
- `tests/unit/test_kg_features_unreachable.py`

Deselected: the two known-pre-existing perf-budget machine flakes (`test_perf_budget_pagerank_louvain[1000-0.5]` and `[5000-3.0]`) — confirmed in §3 of the verification report that they reproduce on `master` with this branch stashed.

## 3. Stress — `/api/graph` via in-process TestClient

| Scenario | min | p50 | p95 | p99 | max | errors |
|---|---|---|---|---|---|---|
| cold (1 call) | — | 569 ms | — | — | — | 0 |
| 50 SERIAL warm | 236 | 295 | 344 | 354 | 354 | 0 |
| 50 CONCURRENT (10 workers) | 879 | 2131 | 2868 | 2932 | 2932 | 0 |
| 100 BURST (20 workers) | 350 | 4639 | 7234 | 7575 | 7575 | 0 |

**0 errors across 200 total requests.** Concurrent numbers are inflated by TestClient running the entire ASGI app in one Python process under the GIL — production gunicorn has 2 worker processes (real parallel) and UserGraphCache single-flight collapses N concurrent loads for the same key to 1 upstream round-trip (see `graph_cache.py:207-296`). The architectural signal that matters: zero failures under burst, cache + brotli middleware survive.

Stress harness committed at [docs/claude_audits/stress_graph_api.py](docs/claude_audits/stress_graph_api.py) for re-run.

## 4. Adversarial code review — findings triaged

The code-reviewer agent (background dispatch, full branch diff) returned **0 CRITICAL / 8 MAJOR / 11 MINOR** with several self-withdrawals on re-reading. After triage:

### FIXED in this audit (commit `e88c5bdc`)

| ID | Severity | Issue | Fix |
|---|---|---|---|
| M1 | MAJOR | `kg_populate_runs_total{outcome="skipped_idempotent"}` was never emitted — the idempotency-gate early-return bypassed `finish_run_with_state`'s chokepoint, so dashboards under-counted re-ingests. | Increment the same counter inline at the idempotency-skip return in `kg_population.py`. Mirrors the LD-8 4-state chokepoint pattern. |
| M6 | MAJOR | Title-to-slug derivation in `_v2_assemble_graph`, `_build_supabase_node_id`, `graph_store._slugify`, and `kg_population._slugify` lowercased BEFORE NFKC normalization. NFD-form titles (combining accents, full-width digits, ligatures) produced different slugs across re-renders, silently desynchronising frontend ownership maps for non-ASCII titles. | NFKC-normalize the title first in all 4 sites; matches `text_polish.normalize_tag` (X5). |
| m3 | MINOR | File-store path wrote `tier="strong"` on every auto-link (`graph_store._find_links`); v2 path did NOT emit `tier` (LD-5 client-computes). Anon vs logged-in graphs had divergent wire shapes. | Added `"tier"` to `_TRIMMED_EDGE_FIELDS`. Single consistent wire shape. |
| m8 | MINOR | Y1 sampled-log comment claimed "at most once per process" — actually deterministic across all workers for the same `(ws, src, dst)` triplet. | Comment corrected; behaviour was already the stronger guarantee. |

Re-run after fixes: ruff clean, 105 targeted tests pass.

### SKIPPED with explicit rationale

| ID | Severity | Issue | Why skipped |
|---|---|---|---|
| C1 (renumbered) | MAJOR | Mig 72 UPDATE backfill not batched; `statement_timeout=60s` bounds it. | Today's max workspace ~50 zettels; UPDATE bounds at <100ms. At scale (10k+) we'd batch in a follow-up ops script. **Documented in the migration header.** |
| M5 | MAJOR | `_metadata_embedding_candidates` Python-side cosine loop on up to 2000 rows × 768-d vectors; not numpy-vectorized. | Fallback path — only fires when `match_kg_nodes` RPC returns empty AND the primary chunk-mention candidate set is empty. T2.B2 writes chunk_node_mentions on every live ingest, so steady-state fallback frequency is ~0. Worth numpy-vectorising if Prometheus shows the fallback firing >1×/hour. **Flagged in follow-up backlog.** |
| m1 | MINOR | Dead `i - 1` expression in `text_polish.py:202`. | Pre-existing on master; not introduced by Phase 1-4; out of scope. |
| m7 | MINOR | Verify `PROMETHEUS_MULTIPROC_DIR` is exported in droplet env-file. | Already in `ops/Dockerfile:104` (verified earlier in PR #82). |

### FALSE POSITIVES (withdrawn on closer reading)

| ID | Claim | Why withdrawn |
|---|---|---|
| C1 (original) | K3 invalidation double done-callback race | Both callbacks use `set.discard` which is idempotent. Safe by construction. |
| M2 | DB write fails after metric increment → overcount | Re-read `finish_run_with_state`: counter fires AFTER `.execute()` returns successfully; DB failure aborts before metric. |
| M4 | Mig 73 uses `normalize(t, NFKC)` may not be available | Verified: PG 13+ has `normalize()` in core SQL, Supabase runs PG 15+. Documented inline. |
| M7 | Cache bucket under-render on slider-down within bucket | **Verified in `view_graph.py:273-296,314-340,357-406`**: cache stores the un-filtered payload (`_v2_assemble_graph(min_strength=None)`), then `_apply_min_strength_filter(cached, min_strength)` applies the user's exact threshold AFTER cache hit. Cache is correct. |

### MINOR follow-ups (not blocking; deferrable)

- `_v2_assemble_graph` re-defines `_resolve_overlay_ids` per workspace iteration — cosmetic closure overhead.
- Authorization token regex `/^https?:\/\/([^.]+)\.supabase\.co/` assumes `.supabase.co` — pre-prod or custom-domain deployments need a config-driven host list.
- Speaker pseudo-tag slug clash at the 48-char boundary — acceptable, low-cardinality is the point.

## 5. Verdict

**Zero critical findings.** Four corrective fixes landed (M1 observability hole, M6 Unicode slug drift, m3 wire parity, m8 docstring accuracy). Three skipped items have explicit rationale and follow-up triggers (M5: monitor fallback frequency; C1-renumbered: revisit migration batching at 10k+ scale; m1: pre-existing dead code).

**These modules do not need to be touched again** for Phase 1-4 scope. The remaining gates are operator territory (Migrations 72 + 73 prod-apply + 3 manual smokes), already documented in [docs/claude_audits/phase4_acceptance_2026-05-24.md](docs/claude_audits/phase4_acceptance_2026-05-24.md) and [PR #82](https://github.com/chintanmehta21/Zettelkasten_KG/pull/82).
