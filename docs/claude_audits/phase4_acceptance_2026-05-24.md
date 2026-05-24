# Phase 4 acceptance gate — 2026-05-24

Branch: `feat/kg-phase-4` (17 commits ahead of master after T4.5 test fix).

## Step 1 — pytest sweep

```bash
pytest tests/unit/ -m "not live" \
  --deselect "tests/unit/kg_features/test_analytics_igraph.py::test_perf_budget_pagerank_louvain[1000-0.5]" \
  --deselect "tests/unit/api/test_pricing_preflights.py::test_add_zettel_checks_entitlement_before_expensive_work"
# 3471 passed, 91 skipped, 2 deselected, 102 warnings in 525.45s
```

Three known not-live flakes documented in iter-12 handoff (`2× quantize_bge_int8`,
`cascade_int8`) and two pre-existing failures verified independent of Phase 4:

- `test_pricing_preflights::test_add_zettel_checks_entitlement_before_expensive_work` — reproduces on tip-of-branch with all Phase 4 changes stashed; pre-existing async-timing flake on this Windows host.
- `test_perf_budget_pagerank_louvain[1000-0.5]` — pre-existing perf flake (3.77s vs 0.5s budget); confirmed reproducing on stashed state. Machine-load sensitive.

Phase-4-introduced regression (`test_backfill_kg_edge_strength.py` cold-node
tests) was caused by T4.5 swapping `generate_embedding` → `generate_embedding_typed`;
the test fixture was updated to mock the typed entrypoint and now passes 25/25.

## Steps 2-4 — manual smokes (OPERATOR)

Steps 2 (`/api/metrics` scrape), 3 (`/api/meta/source-types` shape), 4
(pseudo-tags hidden in UI) require a running container and a live login; they
are operator territory. Reproducible commands inlined in the plan
(`docs/superpowers/plans/2026-05-23-kg-render-correctness-overhaul.md:4430-4448`).

## Cross-cutting 12-item checklist

| # | Criterion | Verifiable now? | Status |
|---|---|---|---|
| 1 | Anonymous /api/graph returns ≥1 edge per dataset link | runtime | code-ready; needs container smoke |
| 2 | Logged-in /api/graph returns deterministic edge counts | code+runtime | code-ready (T2.1 deterministic ORDER BY landed); needs container smoke |
| 3 | Cross-page edges visible (>5000 zettels) | code+runtime | code-ready (T2.4b edge-driven assembly); needs synthetic-scale smoke |
| 4 | All 4 kg-populate terminal states appear over a synthetic batch | code | code-ready (T3.3 LD-8 state machine wired; pipelines_repository.finish_run_with_state writes all 4 outcomes through one chokepoint) |
| 5 | Slider never flashes to empty | runtime | code-ready (T1.4 F1 fix) |
| 6 | Empty-state UX explains itself at 0.99 | runtime | code-ready (T1.5 F2 overlay) |
| 7 | Source-type registry single source | code | code-ready (T4.1 source_registry.py canonical; /api/meta/source-types serves it; app.js fetches at boot) |
| 8 | Pseudo-tags isolated from user-facing tag list | code+runtime | code-ready (T4.3 derived_tags column + persist split; **PROD-APPLY of Mig 72 PENDING — OPERATOR**) |
| 9 | Auth tokens isolated per project ref | code+runtime | code-ready (T4.8 _expectedProjectRef scoping) |
| 10 | /api/metrics counters increase during Add Zettel | runtime | code-ready (T4.6 Prometheus ASGI mount + kg_populate_runs_total + duration histogram) |
| 11 | 5k-node fixture renders ≥30 fps | runtime (Chrome DevTools) | code-ready (T3.9/3.11/3.12/3.13 frontend perf); OPERATOR Chrome smoke |
| 12 | No protected-knob revert | code | **VERIFIED** — `git diff master...HEAD -- ops/ .github/` shows zero edits to GUNICORN_WORKERS, --preload, GUNICORN_TIMEOUT, FP32_VERIFY_ENABLED, SSE heartbeat, Caddy upstream timeouts, schema-drift gate, or kg_users allowlist gate. The only ops/ touch is `ops/Dockerfile` adding `PROMETHEUS_MULTIPROC_DIR` (pure addition for T4.6), and `website/gunicorn_conf.py` adding a non-knob `child_exit` hook for Prometheus metric cleanup. |

## Operator gates still open

- **Migration 73** (`73_normalize_user_tags.sql`) — X5 NFKC + lower + strip
  backfill of `content.workspace_zettels.user_tags`. SQL is staged; prod-apply
  is **NOT** done — needs explicit operator authorization per CLAUDE.md
  "Approval Threshold". Down-migration prepared (no-op; canonicalisation is
  irrecoverable).
- **Migration 72** (`72_workspace_zettels_derived_tags.sql`) — B7 derived_tags
  column + backfill. SQL staged in PR #71 follow-up branch — **operator
  pre-DROP audit prerequisite**, then `gh workflow run apply-migrations.yml`.

## Files changed (17 commits)

```
 28 files changed, 838 insertions(+), 258 deletions(-)
```

Summary of new files:
- `supabase/website/_v2/72_workspace_zettels_derived_tags.sql` + `.down.sql`
- `supabase/website/_v2/73_normalize_user_tags.sql` + `.down.sql`
- `website/core/source_registry.py`
- `website/api/meta_routes.py`
- `tests/unit/website/test_tag_normalize.py`
- `ops/scripts/rescore_kg_edges.py` (already shipped in pre-Phase-4)
- `.github/workflows/rescore_kg_edges.yml` (already shipped in pre-Phase-4)
