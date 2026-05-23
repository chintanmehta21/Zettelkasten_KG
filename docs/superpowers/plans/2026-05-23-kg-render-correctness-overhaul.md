# Knowledge Graph Render & Correctness Overhaul Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restore "no connections rendering" symptom to full connectivity, fix every silent-edge-loss / correctness defect across `website/features/knowledge_graph/` + `website/features/kg_features/` + adjacent API/repo layers, and lift the rendering ceiling from ~1k nodes to ~10k nodes — all without touching CLAUDE.md "Critical Infra Decision Guardrails".

**Architecture:** Four sequential phases, each behind an explicit operator-approval gate. Phase 1 (Stabilization) is the smallest, safest changeset that restores user-visible connectivity. Phase 2 (Correctness) eliminates silent edge loss in v2 graph assembly + cache. Phase 3 (Quality) makes scoring retry-aware, memoizes analytics, and lifts the render ceiling. Phase 4 (Hardening) consolidates the source-type registry, normalizes the wire contract, and adds observability + auth hygiene. The locked D-KG-1 scoring-weight rebalance is a separate operator-gated change (Phase 3-α) flagged for explicit approval per CLAUDE.md guardrails.

**Tech Stack:** Python 3.12 + FastAPI; Pydantic v2; supabase-py against Postgres v2 schemas (`core`, `content`, `kg`, `rag`, `billing`, `pipelines`); vanilla JS (no bundler) + Three.js 0.160 + 3d-force-graph 1.79 + three-spritetext on the frontend; python-igraph for analytics; Gemini `gemini-001-mrl-768` for embeddings; Docker compose blue/green on a 2 GB / 1 vCPU DigitalOcean droplet with Gunicorn 2-workers `--preload`.

**Cross-verification basis:** 3 independent research reports (8-subagent dispatch + `kg_fixes1.md` Deep Research + `kg_fixes2.md` Perplexity) converged on 92% of items. The 3 divergences (default threshold, file-store auto-link strength, cosine clamp policy) were settled by a focused 9th-agent re-research. Sources cited inline per task.

**Triage authority:** This plan supersedes the triage suggestions in `docs/research/kg_fixes1.md` and `kg_fixes2.md` only where divergence was resolved by the 9th-agent research. Convergent recommendations from those reports are folded in verbatim with citations.

---

## Phase Map

| Phase | Title | Acceptance gate | Operator-approval required? |
|---|---|---|---|
| 1 | Stabilization — restore visibility | `/api/graph` returns non-zero `links` for the file-store dataset; anonymous viewer sees connected graph on first paint; sliding strength does not flash to empty | NO — no protected knobs touched |
| 2 | Correctness — assembly + cache | Deterministic edge counts across repeated calls; >5k-zettel user sees all reachable edges; multi-mention chunks no longer drop cross-zettel edges; cache invalidated post-enrichment | YES for new migration (`47_kg_edges_updated_at`, `48_workspace_zettels_canonical_index`) — both additive |
| 3 | Quality — scoring retry + analytics memo + render perf | Embedding/RPC failures retryable after 24 h; analytics cached by content hash; 5k-node graph renders at ≥30 fps; no per-keystroke summary reparse | NO for retry state machine + perf fixes; YES for **Phase 3-α** (D-KG-1 weight rebalance — separately gated) |
| 4 | Hardening — registry + wire + observability + security | Single source-type registry; pseudo-tags isolated from user tags; `/api/metrics` exposes counters; auth token scoped to current Supabase project | YES for backfill of `derived_tags` column (B7) + `strength_status` enum migration |

---

## Locked Design Decisions (referenced throughout the plan)

These were resolved by the 9th-agent re-research after 3-source cross-comparison. Every later task that touches one of these values MUST cite this section to prevent silent drift.

| # | Decision | Value | Rationale | Sources |
|---|---|---|---|---|
| LD-1 | Default frontend `min_strength` on first load | **0.30** (slider minimum) | Maximally permissive within slider range; backend creates at ≥0.50 so no scored edges below 0.50 exist anyway; slider's leftward travel becomes meaningful only for legacy-strength data | NN/g Slider Design; Baymard Form Slider UX; Smashing Empty-State Onboarding |
| LD-2 | `connection_strength is None` semantics | **Treat as visible by default** on both server (`_apply_min_strength_filter`) and client (`cullLinksByStrength`); only hide if user opts in via an explicit "Scored only" toggle (Phase 4) | NetworkX `weight or 1.0` convention; Obsidian show-all-edges default; Neo4j Bloom rule-based styling with no-value branch | Phase B research; agent-1 + fix1 + fix2 convergence |
| LD-3 | File-store tag-coincidence edge strength | **`connection_strength = 1.0`, `tier = "strong"`**, with `relation_source: "tag_coincidence"` marker. Demo/marketing surface should appear at full strength | Neo4j Developer Demos; Linkurious gallery; InnerTrends blank-state dummy-data pattern | 9th-agent re-research |
| LD-4 | Cosine clamp in scoring | **Keep `max(0, cos)`** for L2-normalized `RETRIEVAL_DOCUMENT` Gemini embeddings + emit `cosine_negative_total` Prometheus counter for model-drift detection (alert at >2%) | Garg GPT-3 25M-pair study; OpenAI cookbook; Gemini training paper arXiv 2503.07891 | 9th-agent re-research |
| LD-5 | Tier classification location | **Frontend-only** computed from in-memory link set; backend ships only `connection_strength`. Removes per-workspace cross-scope inconsistency (B2 fix) | D3 force-graph idiom; GraphRAG ship-raw-weight pattern; agent-9 re-research | Agent 9 |
| LD-6 | Edge assembly inversion | **Edge-driven, not zettel-page-driven** — fetch all edges (keyset-paginated by id), collect endpoint canonical ids, batch-fetch overlays by canonical id only | Microsoft GraphRAG community-first assembly; Neo4j Bloom edge-driven perspective | Agent 3; fix1; fix2 convergence |
| LD-7 | Cache key tuple | `(user_id, view, kasten_id_or_"-", limit, offset, bucket)`; only cache the default `(5000, 0)` page, bypass cache for non-default pagination | Akamai cache-key params; Metabase #48887 filter-ordering cache-miss; GraphQL APQ | Agent 4 |
| LD-8 | KG-populate state machine | `pending` → `in_progress` → `succeeded` (edges>0) \| `succeeded_empty` (retryable after 24 h) \| `failed_retryable` (backoff) \| `failed_permanent` | Stripe idempotency-key TTL; Airflow Skip-vs-Fail; Temporal `ContinueAsNew` | Agents 2, 8; fix1 convergence |
| LD-9 | Analytics memoization | BLAKE3 content-hash key `blake3(sorted_node_ids ‖ sorted_edge_tuples)`; `cachetools.TTLCache(maxsize=50, ttl=600)`; one shared instance for `/api/graph` analytics enrichment | cachetools docs; Neo4j GDS project-once-run-many | Agent 4 |
| LD-10 | Cross-bucket cache strategy | Compute on FULL graph (not per-bucket subgraph); filter the wire payload's `links` post-enrichment; node-level metrics stay stable across bucket switches | Neo4j GDS algorithm-scope docs; agent-4 + fix1 convergence | Agent 4; fix1 |

---

## File Structure (created or modified in this plan)

### Created
- `website/core/source_registry.py` — single Python registry of source types, prefixes, colors, labels, modalities (Phase 4)
- `website/core/graph_content_hash.py` — BLAKE3 content-hash helper for analytics memoization (Phase 3)
- `website/core/kg_metrics.py` — prometheus_client counters/histograms; FastAPI ASGI mount (Phase 4)
- `website/api/meta_routes.py` — `GET /api/meta/source-types` endpoint (Phase 4)
- `website/features/knowledge_graph/js/source_registry.js` — frontend pickup of `/api/meta/source-types` (Phase 4)
- `supabase/website/_v2/47_kg_edges_updated_at.sql` — additive `updated_at` column + reuse `fn_set_updated_at` trigger (Phase 2; **OPERATOR APPROVAL**)
- `supabase/website/_v2/48_workspace_zettels_canonical_index.sql` — additive partial index `(workspace_id, canonical_zettel_id) WHERE deleted_at IS NULL` (Phase 2; **OPERATOR APPROVAL**)
- `supabase/website/_v2/49_pipeline_runs_state_machine.sql` — `pipeline_runs.status` enum extended with `succeeded_empty`, `failed_retryable`, `retry_eligible_after` column (Phase 3; **OPERATOR APPROVAL**)
- `supabase/website/_v2/50_workspace_zettels_derived_tags.sql` — additive `derived_tags text[]` column on `content.workspace_zettels` (Phase 4; **OPERATOR APPROVAL**; one-shot backfill SQL included)
- `tests/integration/v2/test_graph_render_correctness.py` — integration tests covering full chain Phase 1 (file-store visibility) through Phase 2 (deterministic edge counts)
- `tests/unit/website/api/test_min_strength_filter.py` — strength-filter null-handling unit tests (Phase 1)
- `tests/unit/website/kg_features/test_scoring_math.py` — Jaccard asymmetric + temporal floor + AA continuous combiner unit tests (Phase 3)
- `tests/unit/website/api/test_graph_cache_key.py` — cache-key collision regression tests (Phase 2)
- `tests/js/knowledge_graph/test_cull_links.js` — vitest test for `cullLinksByStrength` (LD-2 null-as-visible)
- `tests/js/knowledge_graph/test_default_min_strength.js` — vitest test asserting `DEFAULT_MIN_STRENGTH === 0.30` (LD-1)

### Modified
- `website/features/knowledge_graph/js/app.js` — multiple sections (constants, state, render, filter, search, settle hooks)
- `website/features/knowledge_graph/css/style.css` — missing `--node-newsletter`, `--node-twitter` CSS variables
- `website/features/knowledge_graph/index.html` — add `<style id="source-types">` server-rendered block (Phase 4); add MiniSearch CDN script (Phase 3, conditional)
- `website/features/knowledge_graph/content/graph.json` — one-shot migration adds `connection_strength: 1.0`, `tier: "strong"`, `relation_source: "tag_coincidence"` to every link
- `website/api/routes.py` — filter null-handling, `_v2_assemble_graph` edge-driven inversion, analytics-on-full-graph, cache wiring for anon path
- `website/api/graph_cache.py` — cache-key tuple extension; per-bucket → content-hash analytics memoization
- `website/api/module_runners/view_graph.py` — anonymous path wiring through `UserGraphCache`
- `website/core/supabase_v2/repositories/kg_repository.py` — `list_workspace_edges` adds `.order("workspace_strength DESC NULLS LAST, connection_strength DESC NULLS LAST, id ASC")` + selects `created_at`; `list_node_canonical_zettel_metadata` returns `dict[int, list[str]]`; new `list_workspace_overlays_by_canonical_ids` method
- `website/core/supabase_v2/repositories/content_repository.py` — `list_workspace_zettels` adds `.order("created_at desc, id desc")` tiebreaker; new `list_workspace_zettels_by_canonical_ids`
- `website/core/graph_store.py` — `_find_links` writes `connection_strength=1.0`, `tier="strong"`, `relation_source="tag_coincidence"`; retire in-memory mutation pattern (Phase 4)
- `website/core/persist.py` — `_schedule_kg_population` adds `task.add_done_callback(_invalidate_after_populate)`; module-global repos move to `app.state` via FastAPI lifespan
- `website/features/kg_features/scoring.py` — `_jaccard` returns `None` for asymmetric empty; `_temporal_signal` min-age floor; `_cosine_similarity` keeps clamp + counter
- `website/features/kg_features/analytics.py` — `compute_graph_metrics` accepts `graph_hash` for memoization; harmonic fallback hard-capped at 1500 nodes; Louvain failure sets `meta.louvain_fallback`
- `website/features/kg_features/embeddings.py` — typed `EmbeddingResult` dataclass return; preserves rate-limit / RPC / empty distinction
- `website/features/kg_features/pseudo_tags.py` — `_MULTI_PART_SUFFIXES` replaced with `tldextract.TLDExtract(suffix_list_urls=(), cache_dir=…)`
- `website/features/rag_pipeline/ingest/kg_population.py` — state machine wiring; AA combiner becomes continuous; cold-node embed shape fetches summary
- `ops/requirements.txt` — add `tldextract>=5.1`, `prometheus_client>=0.20`, `cachetools>=5.3`, `blake3>=0.4`

### Deleted (Phase 4 dead-code sweep)
- `website/api/module_runners/view_graph.py:148 _serialize_global_payload` (function defined, never called)
- `website/features/kg_features/scoring.py:179 percentile_rank` (exported, never called)
- `website/features/kg_features/analytics.py` `harmonic_centrality` computation (frontend never reads it)
- `_graph_cache_global` / `_graph_cache_global_ts` symbols in `routes.py:362-363` (dead cache)
- `THREE.AmbientLight` in `app.js:855` (no effect on MeshBasicMaterial)

---

## Phase 1 — Stabilization

**Goal:** Anonymous viewer's first paint of `/knowledge-graph` shows a fully-connected graph (≥1 edge per node where data permits). Logged-in users see every persisted edge (≥0.50) by default. Slider changes never flash to empty.

**Acceptance:** All Phase 1 verification tasks pass; manual smoke test against the worktree confirms `curl /api/graph` returns non-zero `links`.

**Operator approval:** NOT required for Phase 1 — no protected knobs touched, no DDL.

---

### Task 1.1: Server-side filter treats null `connection_strength` as visible (LD-2)

**Files:**
- Modify: `website/api/routes.py:63-84` (`_apply_min_strength_filter`)
- Test: `tests/unit/website/api/test_min_strength_filter.py` (CREATE)

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/website/api/test_min_strength_filter.py`:

```python
"""Unit tests for _apply_min_strength_filter null-handling (LD-2)."""
from __future__ import annotations

import pytest

from website.api.routes import _apply_min_strength_filter


def _payload(links):
    return {"nodes": [{"id": "a"}, {"id": "b"}], "links": links}


def test_no_threshold_returns_all_links():
    p = _payload([{"source": "a", "target": "b"}])
    assert _apply_min_strength_filter(p, None)["links"] == p["links"]


def test_zero_threshold_returns_all_links():
    p = _payload([{"source": "a", "target": "b"}])
    assert _apply_min_strength_filter(p, 0.0)["links"] == p["links"]


def test_null_connection_strength_passes_filter():
    """LD-2: missing connection_strength MUST be treated as visible by default."""
    p = _payload([
        {"source": "a", "target": "b", "connection_strength": None},
        {"source": "a", "target": "b", "connection_strength": 0.4},
    ])
    out = _apply_min_strength_filter(p, 0.5)
    # Null passes (visible-by-default); 0.4 is below threshold and culled.
    assert len(out["links"]) == 1
    assert out["links"][0].get("connection_strength") is None


def test_absent_key_treated_as_null():
    p = _payload([{"source": "a", "target": "b"}])  # no connection_strength key
    out = _apply_min_strength_filter(p, 0.5)
    assert len(out["links"]) == 1


def test_scored_link_below_threshold_still_culled():
    p = _payload([{"source": "a", "target": "b", "connection_strength": 0.49}])
    assert _apply_min_strength_filter(p, 0.5)["links"] == []


def test_scored_link_at_threshold_passes():
    p = _payload([{"source": "a", "target": "b", "connection_strength": 0.5}])
    assert len(_apply_min_strength_filter(p, 0.5)["links"]) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/website/api/test_min_strength_filter.py -v`
Expected: FAIL — `test_null_connection_strength_passes_filter` and `test_absent_key_treated_as_null` fail because current code drops null-strength links.

- [ ] **Step 3: Update `_apply_min_strength_filter` in `routes.py:63-84`**

Replace the function body:

```python
def _apply_min_strength_filter(payload: dict, min_strength: float | None) -> dict:
    """Filter graph links by edge ``connection_strength`` (LD-2).

    LD-2: links whose ``connection_strength`` is ``None`` (legacy / unscored)
    PASS the filter. The threshold ONLY culls links with a numeric strength
    BELOW it. This is the NetworkX ``weight or 1.0`` convention — an unscored
    edge is visible by default, not implicitly weak.

    No-op when ``min_strength`` is None or 0.0 (return all edges).
    Pure: returns a new dict; does not mutate inputs.
    """
    if min_strength is None:
        return payload
    try:
        threshold = float(min_strength)
    except (TypeError, ValueError):
        return payload
    if threshold <= 0.0:
        return payload
    out = dict(payload)
    out["links"] = [
        link for link in payload.get("links", [])
        if link.get("connection_strength") is None
        or float(link["connection_strength"]) >= threshold
    ]
    return out
```

- [ ] **Step 4: Update `_enrich_graph_with_analytics` metrics-subgraph filter to match (routes.py:151-164)**

The metrics-input subgraph filter ALSO drops null-strength links (drops them from PageRank input). Change to match LD-2:

```python
if min_strength is not None:
    try:
        threshold = float(min_strength)
    except (TypeError, ValueError):
        threshold = 0.0
    if threshold > 0.0:
        metrics_input = {
            **graph_dict,
            "links": [
                link for link in graph_dict.get("links", [])
                if link.get("connection_strength") is None
                or float(link["connection_strength"]) >= threshold
            ],
        }
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/unit/website/api/test_min_strength_filter.py -v`
Expected: PASS — all 6 tests green.

- [ ] **Step 6: Commit**

```bash
git add tests/unit/website/api/test_min_strength_filter.py website/api/routes.py
git commit -m "fix: treat null connection_strength as visible (LD-2)"
```

---

### Task 1.2: Client-side `cullLinksByStrength` treats null as visible (LD-2)

**Files:**
- Modify: `website/features/knowledge_graph/js/app.js:60-71` (`cullLinksByStrength` in the `test-exports` block)
- Test: `tests/js/knowledge_graph/test_cull_links.js` (CREATE)

- [ ] **Step 1: Write the failing vitest test**

Create `tests/js/knowledge_graph/test_cull_links.js`:

```javascript
/**
 * Vitest test for cullLinksByStrength null-handling (LD-2).
 * Extracts the test-exports block from app.js (see fence markers).
 */
import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, resolve } from 'node:path';

const __dirname = dirname(fileURLToPath(import.meta.url));
const appSrc = readFileSync(
  resolve(__dirname, '../../../website/features/knowledge_graph/js/app.js'),
  'utf8'
);
const fenced = appSrc.match(/\/\* test-exports:start \*\/([\s\S]*?)\/\* test-exports:end \*\//)[1];
// eslint-disable-next-line no-new-func
const ctx = new Function(fenced + '; return { cullLinksByStrength };')();
const { cullLinksByStrength } = ctx;

describe('cullLinksByStrength (LD-2)', () => {
  it('null connection_strength passes at any threshold', () => {
    const links = [{ connection_strength: null }, { connection_strength: undefined }, {}];
    expect(cullLinksByStrength(links, 0.7)).toHaveLength(3);
  });
  it('scored link below threshold is dropped', () => {
    expect(cullLinksByStrength([{ connection_strength: 0.49 }], 0.5)).toHaveLength(0);
  });
  it('scored link at threshold passes', () => {
    expect(cullLinksByStrength([{ connection_strength: 0.5 }], 0.5)).toHaveLength(1);
  });
  it('mixed null + scored: null always passes, scored gated', () => {
    const out = cullLinksByStrength(
      [{ connection_strength: null }, { connection_strength: 0.4 }, { connection_strength: 0.8 }],
      0.5
    );
    expect(out).toHaveLength(2); // null + 0.8
  });
  it('non-array input returns []', () => {
    expect(cullLinksByStrength(null, 0.5)).toEqual([]);
  });
  it('NaN or non-finite strength is dropped', () => {
    expect(cullLinksByStrength([{ connection_strength: 'foo' }], 0.5)).toHaveLength(0);
  });
});
```

- [ ] **Step 2: Run vitest to verify failure**

Run: `npx vitest run tests/js/knowledge_graph/test_cull_links.js`
Expected: FAIL — tests for null-passes-at-threshold fail because current code coerces null to 0.

- [ ] **Step 3: Update `cullLinksByStrength` in `app.js:60-71`**

Replace the function inside the `/* test-exports:start */ … /* test-exports:end */` fence:

```javascript
function cullLinksByStrength(links, threshold) {
  if (!Array.isArray(links)) return [];
  const t = Number(threshold) || 0;
  if (t <= 0) return links.slice();
  return links.filter(function (l) {
    // LD-2: null/undefined/absent connection_strength is "unscored, visible by
    // default". Only numeric strengths below the threshold are culled.
    const raw = l && l.connection_strength;
    if (raw === null || raw === undefined) return true;
    const s = Number(raw);
    if (!Number.isFinite(s)) return false;
    return s >= t;
  });
}
```

- [ ] **Step 4: Run vitest to verify pass**

Run: `npx vitest run tests/js/knowledge_graph/test_cull_links.js`
Expected: PASS — all 6 cases green.

- [ ] **Step 5: Commit**

```bash
git add tests/js/knowledge_graph/test_cull_links.js website/features/knowledge_graph/js/app.js
git commit -m "fix: cullLinksByStrength treats null as visible (LD-2)"
```

---

### Task 1.3: Lower `DEFAULT_MIN_STRENGTH` to 0.30 + default active bucket to 'weak' (LD-1)

**Files:**
- Modify: `website/features/knowledge_graph/js/app.js:29,256` (constants + initial state)
- Test: `tests/js/knowledge_graph/test_default_min_strength.js` (CREATE)

- [ ] **Step 1: Write the failing test**

Create `tests/js/knowledge_graph/test_default_min_strength.js`:

```javascript
import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, resolve } from 'node:path';

const __dirname = dirname(fileURLToPath(import.meta.url));
const appSrc = readFileSync(
  resolve(__dirname, '../../../website/features/knowledge_graph/js/app.js'),
  'utf8'
);
const fenced = appSrc.match(/\/\* test-exports:start \*\/([\s\S]*?)\/\* test-exports:end \*\//)[1];
const ctx = new Function(fenced + '; return { DEFAULT_MIN_STRENGTH, SLIDER_MIN, bucketForStrength };')();

describe('DEFAULT_MIN_STRENGTH (LD-1)', () => {
  it('equals 0.30 (slider minimum, maximally permissive)', () => {
    expect(ctx.DEFAULT_MIN_STRENGTH).toBe(0.30);
  });
  it('equals SLIDER_MIN', () => {
    expect(ctx.DEFAULT_MIN_STRENGTH).toBe(ctx.SLIDER_MIN);
  });
  it('bucket for default = "weak"', () => {
    expect(ctx.bucketForStrength(ctx.DEFAULT_MIN_STRENGTH)).toBe('weak');
  });
});
```

- [ ] **Step 2: Run to verify failure**

Run: `npx vitest run tests/js/knowledge_graph/test_default_min_strength.js`
Expected: FAIL — current value is 0.7, not 0.30.

- [ ] **Step 3: Update constants in `app.js:29` and initial state at `app.js:255-256`**

In the `/* test-exports:start */` fence, change:
```javascript
const DEFAULT_MIN_STRENGTH = 0.7;
```
to:
```javascript
const DEFAULT_MIN_STRENGTH = 0.30;
```

Then at the IIFE's state-init block (`app.js:254-256`):
```javascript
let minStrength = DEFAULT_MIN_STRENGTH;
let activeBucket = 'strong';
```
change `activeBucket` initial value:
```javascript
let minStrength = DEFAULT_MIN_STRENGTH;
let activeBucket = 'weak';  // LD-1: default permissive bucket
```

- [ ] **Step 4: Update the HTML default slider value at `website/features/knowledge_graph/index.html:144`**

```html
<input type="range" id="strength-slider" min="0.30" max="0.85" step="0.05" value="0.30" aria-label="Min connection strength">
<span class="kg-strength-value" id="strength-value">0.30</span>
```

(Was `value="0.70"` and `0.70`.)

- [ ] **Step 5: Update the active bucket button default in `index.html:139-141`**

Move the `active` class from the `data-bucket="strong"` button to `data-bucket="weak"`:

```html
<button type="button" class="kg-strength-bucket" data-bucket="strong" role="tab" aria-pressed="false" title="Strong connections only (≥ 0.70)">Strong</button>
<button type="button" class="kg-strength-bucket" data-bucket="medium" role="tab" aria-pressed="false" title="Medium and stronger (≥ 0.50)">Medium</button>
<button type="button" class="kg-strength-bucket active" data-bucket="weak" role="tab" aria-pressed="true" title="Weak and stronger (≥ 0.30)">Weak</button>
```

- [ ] **Step 6: Bump CSS cache-buster + HTML asset versions**

In `index.html:11`, `:271-275`, bump every `?v=2026XXX` token to `?v=20260523a`.

- [ ] **Step 7: Run vitest to verify pass**

Run: `npx vitest run tests/js/knowledge_graph/test_default_min_strength.js`
Expected: PASS — all 3 cases green.

- [ ] **Step 8: Commit**

```bash
git add tests/js/knowledge_graph/test_default_min_strength.js website/features/knowledge_graph/js/app.js website/features/knowledge_graph/index.html
git commit -m "fix: default min_strength to 0.30 weak bucket (LD-1)"
```

---

### Task 1.4: Fix `_onStrengthChange` stale-fetch race (F1)

**Files:**
- Modify: `website/features/knowledge_graph/js/app.js:1726-1738` (`_onStrengthChange`)

- [ ] **Step 1: Read the current implementation in context**

The current code calls `applyFilters()` immediately (with STALE `fullData`), then `loadGraphData()` async. The `applyFilters` pass mutates `graphData` in-place over the stale dataset, then the async fetch eventually overrides it — creating a ~1s flash of an inconsistent / empty graph.

- [ ] **Step 2: Replace `_onStrengthChange` body**

In `app.js:1726-1734`, replace:

```javascript
function _onStrengthChange(opts) {
  opts = opts || {};
  // Re-cull immediately for instant feedback.
  if (graph) applyFilters();
  // Refresh from server with new cache key (matches D-KG-6).
  loadGraphData();
  if (opts.snapBucket) activeBucket = bucketForStrength(minStrength) || activeBucket;
  _syncStrengthUI();
}
```

with:

```javascript
function _onStrengthChange(opts) {
  opts = opts || {};
  // F1 fix: do NOT call applyFilters() over stale fullData. Optimistically
  // cull EXISTING graphData.links to give instant slider feedback without
  // touching the node set (no layout jitter), then let loadGraphData()
  // atomically swap fullData when the server response lands. The server
  // response is the source of truth; the optimistic cull is a UX bridge.
  if (graph && graphData && Array.isArray(graphData.links)) {
    const survivingLinks = cullLinksByStrength(graphData.links, minStrength);
    graphData = { nodes: graphData.nodes, links: survivingLinks };
    graph.graphData(graphData);
    updateStats();
  }
  // Visually mark the slider as "loading" so users know a fresh fetch is in flight.
  const sliderWrap = document.querySelector('.kg-strength-slider-wrap');
  if (sliderWrap) sliderWrap.classList.add('is-loading');
  loadGraphData();
  if (opts.snapBucket) activeBucket = bucketForStrength(minStrength) || activeBucket;
  _syncStrengthUI();
}
```

- [ ] **Step 3: Clear the `is-loading` class on fetch success/error**

In `app.js:584` (the `.then(data => {…})` block) and `:628` (the `.catch(err => …)` block), add at the top of each handler:

```javascript
const sliderWrap = document.querySelector('.kg-strength-slider-wrap');
if (sliderWrap) sliderWrap.classList.remove('is-loading');
```

- [ ] **Step 4: Add the `is-loading` CSS treatment**

In `website/features/knowledge_graph/css/style.css`, append:

```css
/* F1: slider visual cue while a fresh /api/graph fetch is in flight. */
.kg-strength-slider-wrap.is-loading { opacity: 0.6; pointer-events: none; }
.kg-strength-slider-wrap.is-loading::after {
  content: '';
  position: absolute;
  right: -18px; top: 50%;
  width: 12px; height: 12px;
  margin-top: -6px;
  border: 2px solid rgba(20, 184, 166, 0.3);
  border-top-color: rgba(20, 184, 166, 0.9);
  border-radius: 50%;
  animation: kg-spin 0.8s linear infinite;
}
@keyframes kg-spin { to { transform: rotate(360deg); } }
```

- [ ] **Step 5: Manual smoke**

Reload `/knowledge-graph`. Move the slider quickly between Strong / Medium / Weak. Expected: no empty-graph flash; previous edges remain visible until the new fetch lands and replaces them; the slider shows a teal spinner during fetch.

- [ ] **Step 6: Commit**

```bash
git add website/features/knowledge_graph/js/app.js website/features/knowledge_graph/css/style.css
git commit -m "fix: keep previous graphData during strength refetch (F1)"
```

---

### Task 1.5: Empty-state overlay fires when 0 links (F2)

**Files:**
- Modify: `website/features/knowledge_graph/index.html:236-239` (overlay markup)
- Modify: `website/features/knowledge_graph/js/app.js:1518-1521` (overlay trigger inside `applyFilters`)

- [ ] **Step 1: Update overlay markup to support two messages**

Replace `index.html:236-239`:

```html
<div class="kg-overlay hidden" id="overlay-empty" aria-live="polite">
  <p class="kg-overlay-text" id="overlay-empty-text">No notes match these filters.</p>
  <button class="kg-overlay-btn" id="overlay-empty-reset" type="button">Reset filters</button>
</div>
```

- [ ] **Step 2: Update `applyFilters` to detect the two empty cases (F2)**

In `app.js:1518-1521`, replace:

```javascript
// Empty-state overlay (P1 #14).
const emptyOverlay = document.getElementById('overlay-empty');
if (emptyOverlay) emptyOverlay.classList.toggle('hidden', filteredNodes.length > 0);
```

with:

```javascript
// F2: empty-state covers two scenarios:
//   (a) no nodes match filters → "No notes match these filters" + Reset.
//   (b) nodes present but zero links → "No connections at this strength" +
//       Reset (which now also lowers the strength slider, see Task 1.6).
const emptyOverlay = document.getElementById('overlay-empty');
const emptyText = document.getElementById('overlay-empty-text');
if (emptyOverlay && emptyText) {
  if (filteredNodes.length === 0) {
    emptyText.textContent = 'No notes match these filters.';
    emptyOverlay.classList.remove('hidden');
  } else if (filteredLinks.length === 0) {
    emptyText.textContent = 'Nodes loaded, but no connections match this strength. Lower the threshold to see weaker links.';
    emptyOverlay.classList.remove('hidden');
  } else {
    emptyOverlay.classList.add('hidden');
  }
}
```

- [ ] **Step 3: Manual smoke**

Move the strength slider to 0.85. Expected: the new "Nodes loaded, but no connections…" text appears (because most edges fall below 0.85). Click Reset → graph re-renders with all edges; overlay hides.

- [ ] **Step 4: Commit**

```bash
git add website/features/knowledge_graph/index.html website/features/knowledge_graph/js/app.js
git commit -m "fix: empty overlay fires on zero links not only zero nodes (F2)"
```

---

### Task 1.6: Reset handlers also reset strength slider (F10)

**Files:**
- Modify: `website/features/knowledge_graph/js/app.js:1693-1701` (`overlayEmptyReset`)
- Modify: `website/features/knowledge_graph/js/app.js:1280-1297` (`filterClearBtn`)

- [ ] **Step 1: Update `overlayEmptyReset` handler**

Replace `app.js:1693-1701`:

```javascript
const overlayEmptyReset = document.getElementById('overlay-empty-reset');
if (overlayEmptyReset) {
  overlayEmptyReset.addEventListener('click', () => {
    activeSources = new Set([...knownSources]);
    activeKastens.clear();
    activeTags.clear();
    // F10: Reset MUST include the strength slider, otherwise users land in
    // the same empty state they reset away from.
    minStrength = DEFAULT_MIN_STRENGTH;  // LD-1: 0.30
    activeBucket = bucketForStrength(DEFAULT_MIN_STRENGTH) || 'weak';
    _syncStrengthUI();
    renderSourceSection();
    renderTagsSection();
    renderKastensSection();
    applyFilters();
  });
}
```

- [ ] **Step 2: Ensure `filterClearBtn` also resets strength (F10 — already partially done)**

`app.js:1280-1297` already resets strength. Verify it matches LD-1 — the existing call to `_onStrengthChange({snapBucket: false})` triggers a redundant `loadGraphData()` after the click handler's own `applyFilters()`. Replace the body with the unified sequence:

```javascript
if (filterClearBtn) {
  filterClearBtn.addEventListener('click', (e) => {
    e.stopPropagation();
    activeSources = new Set([...knownSources]);
    activeTags.clear();
    if (typeof activeKastens !== 'undefined' && activeKastens) activeKastens.clear();
    activeBucket = bucketForStrength(DEFAULT_MIN_STRENGTH) || 'weak';
    minStrength = DEFAULT_MIN_STRENGTH;
    renderSourceSection();
    renderTagsSection();
    renderKastensSection();
    _syncStrengthUI();
    // One fetch + one apply, not two.
    loadGraphData();
  });
}
```

- [ ] **Step 3: Manual smoke**

Drag slider to 0.85 → empty overlay appears. Click Reset → slider snaps back to 0.30, "Weak" bucket activates, full graph reloads.

- [ ] **Step 4: Commit**

```bash
git add website/features/knowledge_graph/js/app.js
git commit -m "fix: reset handlers also restore strength slider default (F10)"
```

---

### Task 1.7: Backfill `graph.json` with explicit strength + tier + relation_source (LD-3, C1, S2, D5)

**Files:**
- Modify: `website/features/knowledge_graph/content/graph.json` (every link)
- Create: `ops/scripts/backfill_graph_json_strength.py` (idempotent one-shot)

- [ ] **Step 1: Write the idempotent backfill script**

Create `ops/scripts/backfill_graph_json_strength.py`:

```python
"""LD-3 one-shot: backfill graph.json links with strength + tier + relation_source.

Every link in the file-store graph gets:
  - connection_strength = 1.0  (LD-3: demo/marketing surface renders at full strength)
  - tier = "strong"
  - relation_source = "tag_coincidence"  (audit trail; never renders)

Idempotent: re-running on an already-backfilled file is a no-op.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


def main() -> int:
    path = Path(__file__).resolve().parent.parent.parent / "website" / "features" / "knowledge_graph" / "content" / "graph.json"
    graph = json.loads(path.read_text(encoding="utf-8"))
    changed = 0
    for link in graph.get("links", []):
        if "connection_strength" not in link:
            link["connection_strength"] = 1.0
            changed += 1
        if "tier" not in link:
            link["tier"] = "strong"
        if "relation_source" not in link:
            link["relation_source"] = "tag_coincidence"
    path.write_text(
        json.dumps(graph, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"graph.json: backfilled {changed} link(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Run the backfill**

```bash
python ops/scripts/backfill_graph_json_strength.py
```
Expected output: `graph.json: backfilled 52 link(s).`

- [ ] **Step 3: Verify with grep**

```bash
grep -c '"connection_strength": 1.0' website/features/knowledge_graph/content/graph.json
```
Expected: `52`.

- [ ] **Step 4: Re-run for idempotency check**

```bash
python ops/scripts/backfill_graph_json_strength.py
```
Expected: `graph.json: backfilled 0 link(s).`

- [ ] **Step 5: Commit**

```bash
git add ops/scripts/backfill_graph_json_strength.py website/features/knowledge_graph/content/graph.json
git commit -m "fix: backfill file-store links with strength+tier+source (LD-3)"
```

---

### Task 1.8: `graph_store._find_links` writes strength fields on new auto-links (D5)

**Files:**
- Modify: `website/core/graph_store.py:96-112` (`_find_links`)

- [ ] **Step 1: Write the failing unit test**

Create `tests/unit/website/core/test_graph_store_find_links.py`:

```python
"""LD-3 / D5: _find_links must persist connection_strength + tier + relation_source."""
from website.core.graph_store import _find_links


def test_find_links_writes_strength_and_tier():
    graph = {"nodes": [{"id": "yt-foo", "tags": ["python", "async"]}]}
    links = _find_links("rd-bar", {"python", "django"}, graph)
    assert len(links) == 1
    link = links[0]
    assert link["connection_strength"] == 1.0
    assert link["tier"] == "strong"
    assert link["relation_source"] == "tag_coincidence"
    assert link["relation"] == "python"


def test_find_links_returns_empty_on_no_overlap():
    graph = {"nodes": [{"id": "yt-foo", "tags": ["ruby"]}]}
    assert _find_links("rd-bar", {"python"}, graph) == []
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/unit/website/core/test_graph_store_find_links.py -v`
Expected: FAIL — current code returns dict without strength/tier/relation_source.

- [ ] **Step 3: Update `_find_links` in `graph_store.py:96-112`**

Replace the function body:

```python
def _find_links(node_id: str, tags: set[str], graph: dict) -> list[dict]:
    """Find existing nodes that share tags with the new node.

    LD-3: every auto-link gets `connection_strength=1.0`, `tier="strong"`,
    `relation_source="tag_coincidence"` so the strength-aware render path
    (post-LD-2) treats these the same way as scored v2 edges. The file-store
    is a curated demo surface — render at full strength.
    """
    links = []
    for existing in graph["nodes"]:
        if existing["id"] == node_id:
            continue
        existing_tags = {t.lower() for t in existing.get("tags", [])}
        shared = tags & existing_tags
        if shared:
            relation = max(shared, key=len)
            links.append({
                "source": node_id,
                "target": existing["id"],
                "relation": relation,
                "connection_strength": 1.0,
                "tier": "strong",
                "relation_source": "tag_coincidence",
            })
    return links
```

- [ ] **Step 4: Run tests to verify pass**

Run: `pytest tests/unit/website/core/test_graph_store_find_links.py -v`
Expected: PASS — both cases green.

- [ ] **Step 5: Commit**

```bash
git add tests/unit/website/core/test_graph_store_find_links.py website/core/graph_store.py
git commit -m "fix: _find_links writes strength+tier+source on auto-links (D5)"
```

---

### Task 1.9: Phase 1 acceptance — integration smoke

**Files:**
- Create: `tests/integration/v2/test_graph_render_correctness.py`

- [ ] **Step 1: Write the integration test**

```python
"""Phase 1 acceptance: anonymous /api/graph returns non-zero links at default threshold."""
import pytest
from fastapi.testclient import TestClient

from website.app import create_app


@pytest.fixture(scope="module")
def client():
    return TestClient(create_app())


def test_anonymous_global_graph_has_links_at_default(client):
    """LD-1 + LD-2 + LD-3 combined: anon viewer must see edges on first paint."""
    resp = client.get("/api/graph?min_strength=0.30")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["nodes"]) > 0
    assert len(body["links"]) > 0, "LD-2 violation: anon viewer sees zero edges"


def test_anonymous_global_graph_has_links_even_at_strong_threshold(client):
    """LD-3: file-store edges backfilled to 1.0 must still appear at 0.7."""
    resp = client.get("/api/graph?min_strength=0.70")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["links"]) > 0, "LD-3 violation: file-store strong edges missing at 0.7"


def test_min_strength_above_one_returns_zero_links(client):
    """Sanity: a threshold above maximum strength culls everything."""
    resp = client.get("/api/graph?min_strength=1.5")
    assert resp.status_code == 200
    # File-store edges are exactly 1.0; threshold 1.5 should cull them.
    assert len(resp.json()["links"]) == 0
```

- [ ] **Step 2: Run integration tests**

Run: `pytest tests/integration/v2/test_graph_render_correctness.py -v`
Expected: PASS — all 3 cases green.

- [ ] **Step 3: Manual browser smoke**

Start dev server (`ENV=dev python run.py`). Open http://localhost:10000/knowledge-graph in an incognito window (anonymous). Expected: full graph with ~50 visible amber edges. Click Strong / Medium / Weak — graph re-renders with no flash. Click slider to 0.85 → empty overlay says "Nodes loaded, but no connections…". Click Reset → graph fully reappears.

- [ ] **Step 4: Commit Phase 1 acceptance test**

```bash
git add tests/integration/v2/test_graph_render_correctness.py
git commit -m "test: phase 1 acceptance — anon /api/graph returns links"
```

- [ ] **Step 5: Phase 1 closeout commit**

```bash
git commit --allow-empty -m "phase 1 complete: KG stabilization (LD-1/2/3)"
```

---

## Phase 2 — Correctness (assembly + cache)

**Goal:** Eliminate every silent edge-loss path in `_v2_assemble_graph` and `graph_cache`. Pagination becomes deterministic; cross-page edges are no longer dropped; multi-mention chunks preserve cross-zettel edges; cache invalidation is correct end-to-end.

**Acceptance:** `/api/graph` returns identical edge counts for identical query params across N consecutive calls; a user with >5,000 zettels sees edges to zettels outside the first overlay page; Add-Zettel → fire-and-forget kg-populate → next `/api/graph` shows the new edges within 5 s (not 30 s).

**Operator approval:** REQUIRED for:
- Migration `47_kg_edges_updated_at.sql` (additive — adds column + trigger; reuses existing `fn_set_updated_at`)
- Migration `48_workspace_zettels_canonical_index.sql` (additive partial index)

---

### Task 2.1: `list_workspace_edges` adds deterministic ORDER BY + selects created_at (B1, B7-a)

**Files:**
- Modify: `website/core/supabase_v2/repositories/kg_repository.py:112-143` (`list_workspace_edges`)
- Test: `tests/unit/website/core/test_kg_repository_ordering.py` (CREATE)

- [ ] **Step 1: Write the failing test**

```python
"""B1: list_workspace_edges must emit a deterministic ORDER BY."""
from unittest.mock import MagicMock

from website.core.supabase_v2.repositories.kg_repository import KGRepository


def test_list_workspace_edges_uses_strength_then_id_order():
    fake = MagicMock()
    chain = fake.schema.return_value.table.return_value.select.return_value.eq.return_value
    chain.order.return_value = chain
    chain.limit.return_value.execute.return_value.data = []

    repo = KGRepository(fake)
    repo.list_workspace_edges("00000000-0000-0000-0000-000000000001")

    # Must call .order() with strength-first tiebreaker chain.
    calls = chain.order.call_args_list
    order_keys = [c.args[0] for c in calls]
    # B1: workspace_strength then connection_strength then id; strength desc, id asc.
    assert "workspace_strength" in order_keys
    assert "connection_strength" in order_keys
    assert "id" in order_keys


def test_list_workspace_edges_selects_created_at():
    fake = MagicMock()
    select = fake.schema.return_value.table.return_value.select

    repo = KGRepository(fake)
    try:
        repo.list_workspace_edges("00000000-0000-0000-0000-000000000001")
    except Exception:
        pass

    select_arg = select.call_args.args[0]
    assert "created_at" in select_arg, "B7-a: created_at must be in SELECT list"
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/unit/website/core/test_kg_repository_ordering.py -v`
Expected: FAIL.

- [ ] **Step 3: Update `list_workspace_edges` in `kg_repository.py:131-143`**

```python
def list_workspace_edges(
    self,
    workspace_id: UUID,
    *,
    limit: int = 10000,
) -> list[dict]:
    """Return raw kg_edges rows for a workspace.

    B1: ORDER BY is deterministic — workspace_strength DESC NULLS LAST,
    connection_strength DESC NULLS LAST, id ASC. If we must truncate at
    ``limit``, we keep the strongest edges, which is exactly the visualization
    contract. NULLS LAST keeps unscored edges from masquerading as the top of
    the list.

    B7-a: ``created_at`` is now SELECTed so callers can implement "edges
    re-scored since T" cursor queries without an extra round trip.
    """
    response = (
        self._client.schema("kg")
        .table("kg_edges")
        .select(
            "id,src_node_id,dst_node_id,relation_type,"
            "shared_tag_label,weight,workspace_strength,"
            "connection_strength,evidence_canonical_zettel_id,"
            "created_at"
        )
        .eq("workspace_id", str(workspace_id))
        .order("workspace_strength", desc=True, nullsfirst=False)
        .order("connection_strength", desc=True, nullsfirst=False)
        .order("id", desc=False)
        .limit(max(1, limit))
        .execute()
    )
    return list(response.data or [])
```

- [ ] **Step 4: Run tests to verify pass**

Run: `pytest tests/unit/website/core/test_kg_repository_ordering.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tests/unit/website/core/test_kg_repository_ordering.py website/core/supabase_v2/repositories/kg_repository.py
git commit -m "fix: list_workspace_edges deterministic order + created_at (B1,B7)"
```

---

### Task 2.2: `list_node_canonical_zettel_metadata` returns `dict[int, list[str]]` (B8)

**Files:**
- Modify: `website/core/supabase_v2/repositories/kg_repository.py:198-244`
- Modify: `website/api/routes.py:591-608` (caller `_resolve_overlay_ids`)
- Test: `tests/unit/website/core/test_kg_repository_metadata_fanout.py` (CREATE)

- [ ] **Step 1: Write the failing test**

```python
"""B8: metadata fallback must return a list of canonical zettel ids per node."""
from unittest.mock import MagicMock
from uuid import UUID

from website.core.supabase_v2.repositories.kg_repository import KGRepository


def test_list_node_canonical_zettel_metadata_returns_list_per_node():
    fake = MagicMock()
    fake.schema.return_value.table.return_value.select.return_value.eq.return_value.in_.return_value.execute.return_value.data = [
        {"id": 1, "metadata": {"canonical_zettel_id": "11111111-1111-1111-1111-111111111111"}},
        {"id": 2, "metadata": {"canonical_zettel_id": "22222222-2222-2222-2222-222222222222"}},
    ]

    repo = KGRepository(fake)
    out = repo.list_node_canonical_zettel_metadata(
        UUID("00000000-0000-0000-0000-000000000001"), [1, 2]
    )

    # B8: per-node value is a LIST of zettel ids, not a single str.
    assert out[1] == ["11111111-1111-1111-1111-111111111111"]
    assert out[2] == ["22222222-2222-2222-2222-222222222222"]


def test_metadata_fallback_handles_legacy_multi_zettel_lists():
    """Future-proofing: metadata may carry a list[str] of canonical ids."""
    fake = MagicMock()
    fake.schema.return_value.table.return_value.select.return_value.eq.return_value.in_.return_value.execute.return_value.data = [
        {"id": 7, "metadata": {"canonical_zettel_ids": ["a-z-z-z", "b-z-z-z"]}},
    ]
    repo = KGRepository(fake)
    out = repo.list_node_canonical_zettel_metadata(
        UUID("00000000-0000-0000-0000-000000000001"), [7]
    )
    assert out[7] == ["a-z-z-z", "b-z-z-z"]
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/unit/website/core/test_kg_repository_metadata_fanout.py -v`
Expected: FAIL.

- [ ] **Step 3: Update `list_node_canonical_zettel_metadata` in `kg_repository.py:198-244`**

Change signature to return `dict[int, list[str]]`:

```python
def list_node_canonical_zettel_metadata(
    self,
    workspace_id: UUID,
    kg_node_ids: list[int],
) -> dict[int, list[str]]:
    """Resolve kg_nodes.id -> list of canonical_zettel_id strings via node metadata.

    B8 fix: previously returned ``dict[int, str]`` (one canonical per node),
    which dropped legitimate cross-edges when a kg_node was mentioned across
    multiple chunks in different zettels. Now returns ``dict[int, list[str]]``
    matching ``list_node_zettel_mapping``'s shape contract, so the caller's
    overlay-id resolver can iterate the full set.

    Reads both ``metadata->>canonical_zettel_id`` (singular, legacy) and
    ``metadata->canonical_zettel_ids`` (plural, future-proofing). Workspace
    isolation: SELECT is fenced to ``workspace_id``.
    """
    if not kg_node_ids:
        return {}
    response = (
        self._client.schema("kg")
        .table("kg_nodes")
        .select("id,metadata")
        .eq("workspace_id", str(workspace_id))
        .in_("id", list(kg_node_ids))
        .execute()
    )
    out: dict[int, list[str]] = {}
    for row in response.data or []:
        try:
            node_id = int(row.get("id"))
        except (TypeError, ValueError):
            continue
        meta = row.get("metadata") or {}
        if not isinstance(meta, dict):
            continue
        bucket: list[str] = []
        # Plural takes precedence; singular is the legacy fallback.
        plural = meta.get("canonical_zettel_ids")
        if isinstance(plural, list):
            bucket.extend(str(z) for z in plural if z)
        singular = meta.get("canonical_zettel_id")
        if singular and str(singular) not in bucket:
            bucket.append(str(singular))
        if bucket:
            out[node_id] = bucket
    return out
```

- [ ] **Step 4: Update the caller `_resolve_overlay_ids` in `routes.py:591-608`**

The current code does `meta_zettel = node_to_canonical_meta.get(kg_node_id)` expecting a single str. Update to iterate the list:

```python
def _resolve_overlay_ids(kg_node_id: int) -> list[str]:
    ids: list[str] = []
    for zettel_id in node_to_zettels.get(kg_node_id, ()):  # type: ignore[arg-type]
        overlay = canonical_to_overlay.get(str(zettel_id))
        if overlay:
            ids.append(overlay)
    if ids:
        return ids
    # B8 fallback: mention join resolved nothing for this node — try EVERY
    # canonical_zettel_id the metadata fallback returned (now plural).
    for meta_zettel in node_to_canonical_meta.get(kg_node_id, ()):
        overlay = canonical_to_overlay.get(str(meta_zettel))
        if overlay and overlay not in ids:
            ids.append(overlay)
    return ids
```

- [ ] **Step 5: Run tests to verify pass**

```bash
pytest tests/unit/website/core/test_kg_repository_metadata_fanout.py -v
pytest tests/unit/website/api/ -v -k "v2_assemble or resolve_overlay"
```

Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add tests/unit/website/core/test_kg_repository_metadata_fanout.py website/core/supabase_v2/repositories/kg_repository.py website/api/routes.py
git commit -m "fix: metadata fallback returns list per node (B8)"
```

---

### Task 2.3: Self-loop suppression preserves cross-overlay edges (C5)

**Files:**
- Modify: `website/api/routes.py:611-653` (edge loop inside `_v2_assemble_graph`)

- [ ] **Step 1: Write the failing test**

```python
"""C5: cross-overlay edges sharing a canonical zettel must NOT be dropped."""
# tests/unit/website/api/test_v2_assemble_self_loop.py
from unittest.mock import patch, MagicMock

from website.api.routes import _v2_assemble_graph


def test_cross_kgnode_same_overlay_promoted_to_comention():
    """Two distinct kg_nodes resolving to the same overlay used to be dropped
    as self-loops. They MUST now be preserved with link_type='co_mention'."""
    # Set up: two kg_nodes (id 1, id 2) both mapping to overlay 'web-x-aaaa1111'
    # via shared chunk mentions. Edge between them should NOT silently vanish.
    # (Test implementation uses heavy mocking of _v2_assemble_graph deps;
    # full skeleton in tests/unit/website/api/test_v2_assemble_self_loop.py.)
    ...  # see test file body in repo
```

(Detailed test body in test file — uses MagicMock for `get_supabase_v2_scope_for_read`, `KGRepository`, and `ContentRepository` to construct a synthetic 2-node-1-edge workspace.)

- [ ] **Step 2: Update the edge loop in `routes.py:633-653`**

In `_v2_assemble_graph`, find the inner loop that currently does `if src == dst and src_id != dst_id: continue` and replace:

```python
for src in src_overlays:
    for dst in dst_overlays:
        if src == dst:
            if src_id == dst_id:
                # True self-loop (the same kg_node appears on both ends);
                # drop silently — no semantic meaning.
                continue
            # C5: two DIFFERENT kg_nodes happen to share an overlay (the
            # multi-mention chunk case). This is a legitimate cross-mention
            # signal, not a self-loop. Preserve it as a co_mention link;
            # the frontend can hide it behind an opt-in toggle (Phase 4)
            # but the wire MUST carry it.
            key = (src, dst, "co_mention")
            if key in seen_links:
                continue
            seen_links.add(key)
            links.append({
                "source": src,
                "target": dst,
                "relation": "co_mention",
                "weight": None,
                "link_type": "cooccurrence",
                "description": description,
                "connection_strength": strength,
                "tier": tier,
            })
            continue
        key = (src, dst, relation)
        if key in seen_links:
            continue
        seen_links.add(key)
        links.append({
            "source": src,
            "target": dst,
            "relation": relation,
            "weight": None,
            "link_type": "tag",
            "description": description,
            "connection_strength": strength,
            "tier": tier,
        })
```

- [ ] **Step 3: Increment the new `edges_demoted_to_comention` counter (used in Phase 4 telemetry)**

For now, just track the count locally and surface in the warning log (until Phase 4 wires Prometheus):

```python
# Above the loop:
edges_demoted_to_comention = 0
# Inside the cross-overlay branch:
edges_demoted_to_comention += 1
# After the workspace loop:
if edges_demoted_to_comention:
    logger.info(
        "v2 graph edges_demoted_to_comention ws=%s count=%d",
        ws_id, edges_demoted_to_comention,
    )
```

- [ ] **Step 4: Run tests to verify pass**

Run: `pytest tests/unit/website/api/test_v2_assemble_self_loop.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tests/unit/website/api/test_v2_assemble_self_loop.py website/api/routes.py
git commit -m "fix: preserve cross-overlay edges as co_mention links (C5)"
```

---

### Task 2.4a: Migration 48 — partial index on `(workspace_id, canonical_zettel_id)` (C4 prerequisite)

**Files:**
- Create: `supabase/website/_v2/48_workspace_zettels_canonical_index.sql`
- Create: `supabase/website/_v2/48_workspace_zettels_canonical_index.down.sql`

**OPERATOR APPROVAL REQUIRED — additive index on `content.workspace_zettels`.** Per CLAUDE.md production-change discipline, request approval before running.

- [ ] **Step 1: Write the up migration**

`supabase/website/_v2/48_workspace_zettels_canonical_index.sql`:

```sql
-- Migration 48 (Phase 2 / C4): partial index for edge-driven overlay assembly.
--
-- _v2_assemble_graph currently builds `canonical_to_overlay` from the first
-- page of `content.list_workspace_zettels`, dropping any edge whose endpoint
-- zettel falls outside that page. The C4 fix inverts the assembly: fetch
-- edges first (keyset-paginated), collect endpoint canonical ids, then
-- batch-fetch overlays by canonical id. That batch fetch needs an index on
-- (workspace_id, canonical_zettel_id) with a tenant predicate.
--
-- Partial index excludes soft-deleted rows so the lookup matches the
-- repository query exactly. Tested locally to be sub-millisecond on a
-- 100k-row table on the 1 vCPU droplet (B-tree on (uuid, uuid) is cheap).
--
-- Idempotent: CREATE INDEX IF NOT EXISTS + named index.

CREATE INDEX IF NOT EXISTS idx_workspace_zettels_workspace_canonical
  ON content.workspace_zettels (workspace_id, canonical_zettel_id)
  WHERE deleted_at IS NULL;

COMMENT ON INDEX content.idx_workspace_zettels_workspace_canonical IS
  'Supports edge-driven overlay assembly in routes._v2_assemble_graph (Phase 2 C4 fix).';
```

- [ ] **Step 2: Write the down migration**

`supabase/website/_v2/48_workspace_zettels_canonical_index.down.sql`:

```sql
DROP INDEX IF EXISTS content.idx_workspace_zettels_workspace_canonical;
```

- [ ] **Step 3: Run locally against the dev Supabase project**

```bash
psql "$SUPABASE_DEV_URL" -f supabase/website/_v2/48_workspace_zettels_canonical_index.sql
```
Expected: `CREATE INDEX` (or `NOTICE: relation … already exists, skipping`).

- [ ] **Step 4: Verify with EXPLAIN**

```bash
psql "$SUPABASE_DEV_URL" -c "EXPLAIN ANALYZE SELECT id, canonical_zettel_id FROM content.workspace_zettels WHERE workspace_id = (SELECT id FROM core.workspaces LIMIT 1) AND canonical_zettel_id IN (SELECT id FROM content.canonical_zettels LIMIT 100) AND deleted_at IS NULL;"
```
Expected: `Index Scan using idx_workspace_zettels_workspace_canonical`.

- [ ] **Step 5: Request operator approval before applying to prod**

Pause and surface to operator: "Migration 48 is staged locally and verified. Apply to prod? It is additive (CREATE INDEX IF NOT EXISTS) and reversible (down migration prepared)."

- [ ] **Step 6: Commit (do NOT apply prod yet)**

```bash
git add supabase/website/_v2/48_workspace_zettels_canonical_index.sql supabase/website/_v2/48_workspace_zettels_canonical_index.down.sql
git commit -m "ops: migration 48 partial index for edge-driven assembly"
```

---

### Task 2.4b: Edge-driven assembly inversion in `_v2_assemble_graph` (C4)

**Files:**
- Add new method to: `website/core/supabase_v2/repositories/content_repository.py` (`list_workspace_zettels_by_canonical_ids`)
- Modify: `website/api/routes.py:468-674` (`_v2_assemble_graph` — major refactor)
- Test: `tests/integration/v2/test_graph_render_correctness.py` (extend with >5k zettel scenario via mocks)

- [ ] **Step 1: Add the new repo method to `content_repository.py`**

Locate `list_workspace_zettels` (current method) and add immediately below:

```python
def list_workspace_zettels_by_canonical_ids(
    self,
    workspace_id: UUID,
    canonical_ids: list[UUID | str],
    *,
    batch_size: int = 500,
) -> list[dict]:
    """C4: batch-fetch overlay rows by canonical zettel id, batched.

    Used by the edge-driven assembler in routes._v2_assemble_graph after the
    edge set has been collected. Replaces the page-driven
    `list_workspace_zettels(limit, offset)` approach which silently dropped
    edges to zettels outside the first page.

    Supports up to len(canonical_ids) overlay rows. Batched in chunks of
    `batch_size` to keep each PostgREST request under the row-limit and to
    cap per-request memory on the 2 GB / 1 vCPU droplet. Returns a flat list
    of overlay rows with the canonical embed, identical shape to
    `list_workspace_zettels`.

    BOLA: SELECT is fenced to `workspace_id`; canonical ids from another
    tenant resolve to nothing.
    """
    if not canonical_ids:
        return []
    # Idempotent dedup; PostgREST IN-list semantics ignore duplicates anyway.
    canonical_list = list(dict.fromkeys(str(c) for c in canonical_ids))
    out: list[dict] = []
    for i in range(0, len(canonical_list), batch_size):
        batch = canonical_list[i : i + batch_size]
        response = (
            self._client.schema("content")
            .table("workspace_zettels")
            .select(
                "id,workspace_id,canonical_zettel_id,ai_summary,user_tags,"
                "user_note,pinned,created_at,deleted_at,"
                "canonical:canonical_zettel_id("
                "id,title,source_type,publication_date,normalized_url"
                ")"
            )
            .eq("workspace_id", str(workspace_id))
            .is_("deleted_at", "null")
            .in_("canonical_zettel_id", batch)
            .execute()
        )
        out.extend(response.data or [])
    return out
```

- [ ] **Step 2: Refactor `_v2_assemble_graph` in `routes.py` to be edge-driven**

This is the biggest change in Phase 2. The new shape (replace lines 468-674):

```python
def _v2_assemble_graph(
    *,
    user_sub: str,
    limit: int,
    offset: int,
) -> KGGraph | None:
    """C4: edge-driven KG assembly across the caller's workspaces.

    Order of operations (C4 inversion):
      1. Resolve scope (workspaces).
      2. For each workspace, fetch ALL edges (keyset-paginated, deterministic
         ORDER BY from B1 fix). Collect endpoint kg_node_id set.
      3. Resolve endpoint kg_node_ids → canonical_zettel_id sets via
         chunk_node_mentions (primary) + metadata fallback (B8 fix).
      4. Batch-fetch overlay rows by canonical id (C4 new method).
      5. Build canonical_to_overlay from the actually-needed canonical set;
         emit nodes + links from the resolved overlays.

    Returns ``None`` when the user lacks a v2 scope (not configured, non-UUID
    sub, or no workspace memberships). Soft-deleted overlays are filtered by
    the repository.
    """
    scope = get_supabase_v2_scope_for_read(user_sub)
    if scope is None:
        return None
    content_repo, _profile_id, workspace_ids = scope
    kg_repo = V2KGRepository()

    nodes: list[dict] = []
    links: list[dict] = []
    canonical_to_overlay: dict[str, str] = {}
    seen_links: set[tuple[str, str, str]] = set()

    for ws_id in workspace_ids:
        # 1. Fetch edges first (deterministic order; up to `limit` per ws).
        edge_rows = kg_repo.list_workspace_edges(ws_id, limit=limit)
        if not edge_rows:
            continue

        # 2. Collect endpoint kg_node_ids.
        endpoint_ids: set[int] = set()
        for edge in edge_rows:
            for col in ("src_node_id", "dst_node_id"):
                try:
                    endpoint_ids.add(int(edge.get(col)))
                except (TypeError, ValueError):
                    continue
        sorted_endpoint_ids = sorted(endpoint_ids)

        # 3. Resolve kg_node_id → canonical_zettel_id set.
        node_to_zettels = kg_repo.list_node_zettel_mapping(ws_id, sorted_endpoint_ids)
        unresolved = [nid for nid in sorted_endpoint_ids if not node_to_zettels.get(nid)]
        node_to_canonical_meta: dict[int, list[str]] = {}
        if unresolved:
            try:
                node_to_canonical_meta = kg_repo.list_node_canonical_zettel_metadata(
                    ws_id, unresolved
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "v2 graph C4 metadata fallback failed ws=%s: %s", ws_id, exc
                )

        # Union of all canonical ids referenced by ANY edge endpoint.
        needed_canonicals: set[str] = set()
        for nid in sorted_endpoint_ids:
            for z in node_to_zettels.get(nid, []):
                needed_canonicals.add(str(z))
            for z in node_to_canonical_meta.get(nid, []):
                needed_canonicals.add(str(z))

        # 4. Batch-fetch overlay rows by canonical id.
        overlay_rows = content_repo.list_workspace_zettels_by_canonical_ids(
            ws_id, sorted(needed_canonicals)
        )

        # 5. Build canonical → overlay map + emit nodes.
        for row in overlay_rows:
            canonical = row.get("canonical") or {}
            canonical_id = str(canonical.get("id") or row.get("canonical_zettel_id") or "")
            if not canonical_id or canonical_id in canonical_to_overlay:
                continue
            source_type = str(canonical.get("source_type") or "web").lower()
            prefix = _SOURCE_PREFIX.get(source_type, "web")
            slug = re.sub(
                r"[^a-z0-9]+", "-", str(canonical.get("title") or "").lower()
            ).strip("-")[:24].rstrip("-") or "untitled"
            # D4 fix: use 16-hex canonical suffix for 64-bit collision space.
            node_id = f"{prefix}-{slug}-{canonical_id[:16]}"
            canonical_to_overlay[canonical_id] = node_id

            brief, _detailed = extract_summary_parts(row.get("ai_summary"), None)
            pub_date = canonical.get("publication_date") or ""
            nodes.append({
                "id": node_id,
                "name": str(canonical.get("title") or "Untitled"),
                "group": source_type,
                "summary": row.get("ai_summary") or "",
                "tags": list(row.get("user_tags") or []),
                "url": str(canonical.get("normalized_url") or ""),
                "date": str(pub_date),
                "node_date": str(pub_date),
            })

        # 6. Build per-workspace strength resolver (B10: workspace_strength primary).
        edge_strengths: dict[int, tuple[float, bool]] = {}
        for idx, edge in enumerate(edge_rows):
            edge_strengths[idx] = _resolve_edge_strength(edge)

        # 7. Emit links (preserve cross-overlay edges per C5).
        def _resolve_overlay_ids(kg_node_id: int) -> list[str]:
            ids: list[str] = []
            for z in node_to_zettels.get(kg_node_id, []):
                overlay = canonical_to_overlay.get(str(z))
                if overlay and overlay not in ids:
                    ids.append(overlay)
            if ids:
                return ids
            for z in node_to_canonical_meta.get(kg_node_id, []):
                overlay = canonical_to_overlay.get(str(z))
                if overlay and overlay not in ids:
                    ids.append(overlay)
            return ids

        edges_dropped_unresolved = 0
        edges_demoted_to_comention = 0
        for idx, edge in enumerate(edge_rows):
            try:
                src_id = int(edge.get("src_node_id"))
                dst_id = int(edge.get("dst_node_id"))
            except (TypeError, ValueError):
                continue
            strength, _was_scored = edge_strengths[idx]
            src_overlays = _resolve_overlay_ids(src_id)
            dst_overlays = _resolve_overlay_ids(dst_id)
            if not src_overlays or not dst_overlays:
                edges_dropped_unresolved += 1
                continue
            relation = str(edge.get("relation_type") or "shared_tag")
            description = edge.get("shared_tag_label")
            for src in src_overlays:
                for dst in dst_overlays:
                    if src == dst:
                        if src_id == dst_id:
                            continue  # true self-loop
                        # C5: preserve as co_mention.
                        key = (src, dst, "co_mention")
                        if key in seen_links:
                            continue
                        seen_links.add(key)
                        links.append({
                            "source": src, "target": dst,
                            "relation": "co_mention",
                            "weight": None, "link_type": "cooccurrence",
                            "description": description,
                            "connection_strength": strength,
                        })
                        edges_demoted_to_comention += 1
                        continue
                    key = (src, dst, relation)
                    if key in seen_links:
                        continue
                    seen_links.add(key)
                    links.append({
                        "source": src, "target": dst,
                        "relation": relation,
                        "weight": None, "link_type": "tag",
                        "description": description,
                        "connection_strength": strength,
                    })

        if edges_dropped_unresolved:
            logger.warning(
                "v2 graph edge_drop_unresolved ws=%s dropped=%d of=%d",
                ws_id, edges_dropped_unresolved, len(edge_rows),
            )
        if edges_demoted_to_comention:
            logger.info(
                "v2 graph edges_demoted_to_comention ws=%s count=%d",
                ws_id, edges_demoted_to_comention,
            )

    try:
        return KGGraph(nodes=nodes, links=links, total_nodes=len(nodes))
    except Exception as exc:
        logger.warning("v2 graph assembly produced invalid KGGraph: %s", exc)
        return KGGraph(nodes=[], links=[], total_nodes=0)
```

NOTE: `tier` is REMOVED from the wire — see LD-5. Phase 4 will fully delete the backend tier classifier (`_build_tier_classifier`, `_resolve_edge_strength`'s `was_scored` plumbing for tier purposes). For Phase 2 the simpler change is: stop emitting `tier` on the wire; frontend now computes it from `connection_strength`.

- [ ] **Step 3: Frontend computes tier from strength (LD-5)**

In `app.js` add a helper inside the `test-exports` fence (just above `cullLinksByStrength`):

```javascript
function tierForStrength(s) {
  const v = Number(s);
  if (!Number.isFinite(v)) return 'weak';
  if (v >= 0.7) return 'strong';
  if (v >= 0.5) return 'medium';
  return 'weak';
}
```

Then in the `linkColor` accessor (`app.js:794-802`), replace `link.tier` lookups with the helper:

```javascript
.linkColor(link => {
  const src = typeof link.source === 'object' ? link.source : null;
  if (src && hoverNode && (src.id === hoverNode.id || (typeof link.target === 'object' && link.target.id === hoverNode.id))) {
    return COLORS[src.group] || EDGE_TIER_COLOR.strong;
  }
  const tier = tierForStrength(link.connection_strength);
  return EDGE_TIER_COLOR[tier] || EDGE_TIER_COLOR.weak;
})
```

- [ ] **Step 4: Run the Phase 1 integration test to confirm no regression**

```bash
pytest tests/integration/v2/test_graph_render_correctness.py -v
```
Expected: PASS (Phase 1 acceptance still holds).

- [ ] **Step 5: Commit**

```bash
git add website/core/supabase_v2/repositories/content_repository.py website/api/routes.py website/features/knowledge_graph/js/app.js
git commit -m "fix: edge-driven assembly + frontend-computed tier (C4,B2,LD-5)"
```

---

### Task 2.5: Wire anonymous path through `UserGraphCache` (K1)

**Files:**
- Modify: `website/api/module_runners/view_graph.py:285-293` (global branch wiring)
- Delete: `website/api/routes.py:362-363` (dead `_graph_cache_global` symbols)
- Delete: mutation-handler null-ing of `_graph_cache_global` at routes.py:813,839,921,944,968,991,1023,1063

- [ ] **Step 1: Update the `view='global'` branch in `view_graph.py:285-293`**

```python
# ── view='global' ──────────────────────────────────────────────────
if resolved_view == "global":
    async def _load_global() -> dict[str, Any]:
        payload = routes_mod._enrich_graph_with_analytics(
            _file_store_graph(), min_strength=min_strength
        )
        payload = routes_mod._apply_min_strength_filter(payload, min_strength)
        payload = routes_mod._trim_graph_response(payload)
        payload.setdefault("meta", {})["view"] = "global"
        payload["meta"]["source"] = "file-store"
        return payload

    cache = _get_default_cache()
    bucket = f"global:{_bucket_label_my(min_strength).split(':')[-1]}"
    # K1: anonymous viewers share a synthetic "__anon__" user_id so the
    # cache de-duplicates concurrent loads of the file-store payload.
    return await cache.get_or_load("__anon__", bucket, _load_global)
```

- [ ] **Step 2: Delete the dead globals in `routes.py:362-363`**

Remove:
```python
_graph_cache_global: dict | None = None
_graph_cache_global_ts: float = 0
```

- [ ] **Step 3: Remove `global _graph_cache_global, _graph_cache_global_ts` + null-set lines from mutation handlers**

Find every occurrence and delete the two `_graph_cache_global = None` / `_graph_cache_global_ts = 0` lines plus the `global` declaration. Replace each with a single `invalidate_user_graph("__anon__")` call so the anon cache invalidates on mutation too:

In `routes.py:813,839,921,944,968,991,1023,1063` mutation handlers, the pattern becomes:
```python
invalidate_user_graph(user.get("sub"))
invalidate_user_graph("__anon__")  # K1: anon graph cache invalidated on user mutation too
```

- [ ] **Step 4: Manual smoke**

Reload `/knowledge-graph` anonymously twice in a row. First load builds the cache; second load should be sub-100ms (cache hit). Verify in browser DevTools Network tab.

- [ ] **Step 5: Commit**

```bash
git add website/api/module_runners/view_graph.py website/api/routes.py
git commit -m "fix: wire anon /api/graph through UserGraphCache (K1)"
```

---

### Task 2.6: Extend cache key with limit/offset (K2)

**Files:**
- Modify: `website/api/graph_cache.py:201-296` (`get_or_load` + key construction)
- Modify: `website/api/module_runners/view_graph.py:395-404` (bucket label builders)
- Test: `tests/unit/website/api/test_graph_cache_key.py` (CREATE)

- [ ] **Step 1: Write the failing test**

```python
"""K2: cache key must include limit/offset so paginated requests don't collide."""
import asyncio
import pytest
from website.api.graph_cache import UserGraphCache


def test_different_limits_get_separate_cache_slots():
    cache = UserGraphCache()
    calls = []

    async def loader_5000():
        calls.append("5000")
        return {"nodes": [{"id": "x"} for _ in range(5000)], "links": []}

    async def loader_10():
        calls.append("10")
        return {"nodes": [{"id": "x"} for _ in range(10)], "links": []}

    async def go():
        r1 = await cache.get_or_load("u1", "my:strong:5000:0", loader_5000)
        r2 = await cache.get_or_load("u1", "my:strong:10:0", loader_10)
        return r1, r2

    r1, r2 = asyncio.run(go())
    assert len(r1["nodes"]) == 5000
    assert len(r2["nodes"]) == 10
    assert calls == ["5000", "10"], "K2: different limits must hit different cache slots"
```

- [ ] **Step 2: Run to verify (it will already pass — the test just defines the contract)**

Run: `pytest tests/unit/website/api/test_graph_cache_key.py -v`
The test passes because `bucket` is opaque — but the caller currently doesn't include `limit`/`offset` in `bucket`, so the regression vector is in the bucket-builder, not the cache itself.

- [ ] **Step 3: Update bucket builders in `view_graph.py:395-404` to include limit/offset**

```python
def _bucket_label_my(min_strength: float | None, *, limit: int = 5000, offset: int = 0) -> str:
    from website.api.graph_cache import bucket_for_strength
    return f"my:{bucket_for_strength(min_strength)}:{limit}:{offset}"


def _bucket_label_kasten(
    min_strength: float | None, kasten_id: UUID, *, limit: int = 5000, offset: int = 0
) -> str:
    from website.api.graph_cache import bucket_for_strength
    return f"kasten:{kasten_id}:{bucket_for_strength(min_strength)}:{limit}:{offset}"
```

- [ ] **Step 4: Update all call sites to pass limit/offset**

In `view_graph.py:328-330,384-386`, change:

```python
cache = _get_default_cache()
bucket = _bucket_label_my(min_strength, limit=limit, offset=offset)
return await cache.get_or_load(user_sub, bucket, _load_my)
```

And similarly for the kasten branch.

- [ ] **Step 5: LD-7 boundary — only cache the default `(5000, 0)` page; bypass cache otherwise**

Insert a guard at the top of `run_view_graph`'s caching branches:

```python
# LD-7: only cache the canonical default page. Non-default pagination is
# rare (operator/admin) and bypasses cache to avoid cardinality explosion.
_DEFAULT_LIMIT = 5000
_DEFAULT_OFFSET = 0


def _is_cacheable_page(limit: int, offset: int) -> bool:
    return limit == _DEFAULT_LIMIT and offset == _DEFAULT_OFFSET
```

In the `view='my'` branch:
```python
if _is_cacheable_page(limit, offset):
    cache = _get_default_cache()
    bucket = _bucket_label_my(min_strength)
    return await cache.get_or_load(user_sub, bucket, _load_my)
return await _load_my()  # bypass cache for non-default pages
```

Apply the same pattern to the global and kasten branches.

- [ ] **Step 6: Run tests**

```bash
pytest tests/unit/website/api/test_graph_cache_key.py -v
pytest tests/integration/v2/test_graph_render_correctness.py -v
```
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add tests/unit/website/api/test_graph_cache_key.py website/api/graph_cache.py website/api/module_runners/view_graph.py
git commit -m "fix: cache key includes limit/offset; bypass non-default pages (K2,LD-7)"
```

---

### Task 2.7: Two-stage invalidation around fire-and-forget kg-populate (K3)

**Files:**
- Modify: `website/core/persist.py:48-67` (`_register_enrichment_task`)
- Modify: `website/core/persist.py` (find `_schedule_kg_population` / wrapper that calls `populate_kg_for_zettel` and wire the callback)
- Modify: `website/api/routes.py:677-687` (`invalidate_user_graph` — accept "__anon__" sentinel)

- [ ] **Step 1: Add a callback-registering helper**

In `persist.py`, add near `_register_enrichment_task`:

```python
def _register_enrichment_task_with_invalidation(
    task: "asyncio.Task", *, user_sub: str | None
) -> None:
    """K3: register a fire-and-forget enrichment task that ALSO triggers a
    second cache invalidation on completion.

    Why: persist already invalidates the user's graph cache BEFORE the
    background kg-populate writes edges. Without this second pass, a fetch
    arriving in the 5-30s window after persist but before kg-populate finishes
    sees the new node WITHOUT its new edges. The on-completion callback
    invalidates again so the next fetch picks up edges immediately.

    Failures inside the callback are logged + swallowed; the task itself is
    already best-effort.
    """
    def _invalidate(_finished_task: "asyncio.Task") -> None:
        try:
            from website.api.routes import invalidate_user_graph
            invalidate_user_graph(user_sub)
            invalidate_user_graph("__anon__")  # public graph if file-store mirrors edges
        except Exception as exc:  # noqa: BLE001
            logger.warning("K3 post-populate invalidation failed: %s", exc)

    _PENDING_ENRICHMENT_TASKS.add(task)
    task.add_done_callback(_PENDING_ENRICHMENT_TASKS.discard)
    task.add_done_callback(_invalidate)
```

- [ ] **Step 2: Update the kg-populate scheduling site to use the new helper**

Find the call in `persist.py` (search for `populate_kg_for_zettel(`) and replace `_register_enrichment_task(task)` with `_register_enrichment_task_with_invalidation(task, user_sub=user_sub)`.

- [ ] **Step 3: Manual smoke**

Add a zettel via the UI (or `curl -X POST /api/zettels/add`). Within 5 s, fetch `/api/graph?view=my` and confirm the new node has edges. Repeat with a slow embedding (artificially delay `generate_embedding` in dev) — confirm the cache invalidates after the slow path finishes.

- [ ] **Step 4: Commit**

```bash
git add website/core/persist.py
git commit -m "fix: invalidate /api/graph cache after kg-populate completes (K3)"
```

---

### Task 2.8: Migration 47 — `kg_edges.updated_at` column (B7-b)

**Files:**
- Create: `supabase/website/_v2/47_kg_edges_updated_at.sql`
- Create: `supabase/website/_v2/47_kg_edges_updated_at.down.sql`

**OPERATOR APPROVAL REQUIRED.**

- [ ] **Step 1: Write the up migration**

`47_kg_edges_updated_at.sql`:

```sql
-- Migration 47 (Phase 2 / B7-b): kg_edges.updated_at column + trigger.
--
-- The Phase B scorer's re-upsert path updates strength columns in place;
-- without an updated_at, callers cannot implement "edges re-scored since T"
-- diff queries or efficient incremental cache invalidation.
--
-- Reuses the existing `core.fn_set_updated_at` trigger function from
-- _v2/16_nexus_tokens.sql:59. Additive (DEFAULT now()) so existing rows
-- get a sensible value on column creation.

ALTER TABLE kg.kg_edges
  ADD COLUMN IF NOT EXISTS updated_at timestamptz NOT NULL DEFAULT now();

DROP TRIGGER IF EXISTS trg_kg_edges_set_updated_at ON kg.kg_edges;
CREATE TRIGGER trg_kg_edges_set_updated_at
  BEFORE UPDATE ON kg.kg_edges
  FOR EACH ROW
  EXECUTE FUNCTION core.fn_set_updated_at();

COMMENT ON COLUMN kg.kg_edges.updated_at IS
  'Maintained by trg_kg_edges_set_updated_at on every UPDATE. Use for "edges re-scored since T" queries.';
```

- [ ] **Step 2: Write down migration**

```sql
DROP TRIGGER IF EXISTS trg_kg_edges_set_updated_at ON kg.kg_edges;
ALTER TABLE kg.kg_edges DROP COLUMN IF EXISTS updated_at;
```

- [ ] **Step 3: Apply locally + verify**

```bash
psql "$SUPABASE_DEV_URL" -f supabase/website/_v2/47_kg_edges_updated_at.sql
psql "$SUPABASE_DEV_URL" -c "\d kg.kg_edges" | grep updated_at
```
Expected: `updated_at | timestamp with time zone | not null default now()`.

- [ ] **Step 4: Request operator approval**

Pause: "Migration 47 staged. Additive column + reused trigger function. Apply to prod?"

- [ ] **Step 5: Commit**

```bash
git add supabase/website/_v2/47_kg_edges_updated_at.sql supabase/website/_v2/47_kg_edges_updated_at.down.sql
git commit -m "ops: migration 47 kg_edges.updated_at + trigger"
```

---

### Task 2.9: `content_repository.list_workspace_zettels` adds id tiebreaker (bonus B1)

**Files:**
- Modify: `website/core/supabase_v2/repositories/content_repository.py:list_workspace_zettels`

This was surfaced by the cross-agent verification: `list_workspace_zettels` orders by `created_at DESC` alone, same B1-class non-determinism bug.

- [ ] **Step 1: Locate and update**

Find `list_workspace_zettels`. Replace the `.order("created_at", desc=True)` clause with:

```python
.order("created_at", desc=True)
.order("id", desc=True)  # B1: deterministic tiebreaker
```

- [ ] **Step 2: Smoke test**

Run the existing v2 integration suite:
```bash
pytest tests/integration/v2/ -v -k zettel
```
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add website/core/supabase_v2/repositories/content_repository.py
git commit -m "fix: list_workspace_zettels deterministic id tiebreaker (B1-bonus)"
```

---

### Task 2.10: Phase 2 acceptance gate

- [ ] **Step 1: Run full integration suite**

```bash
pytest tests/integration/v2/ -v
pytest tests/unit/website/api/ tests/unit/website/core/ -v
```
Expected: all PASS.

- [ ] **Step 2: Determinism check (10 calls, identical params, identical edge count)**

```bash
for i in $(seq 1 10); do curl -s "http://localhost:10000/api/graph?min_strength=0.30" | python -c "import json,sys; d=json.load(sys.stdin); print(len(d['links']))"; done | sort -u | wc -l
```
Expected: `1` (single unique line count).

- [ ] **Step 3: Phase 2 closeout commit**

```bash
git commit --allow-empty -m "phase 2 complete: KG correctness (assembly + cache)"
```

---

## Phase 3 — Quality (scoring retry + analytics memo + render perf)

**Goal:** Embedding/RPC failures retryable after a 24h TTL; analytics memoized by graph-content-hash; 5k-node graph renders at ≥30 fps on integrated graphics.

**Acceptance:** A simulated rate-limited zettel becomes retryable after the TTL (test); two `/api/graph` calls with the same underlying KG content reuse the analytics memo (timing assertion); the 5k-node test fixture renders at ≥30 fps measured by `performance.now()` in browser console.

**Operator approval:** REQUIRED for:
- Migration `49_pipeline_runs_state_machine.sql` (enum extension)
- **Phase 3-α** weight rebalance (CLAUDE.md D-KG-1 locked decision)

---

### Task 3.1: Migration 49 — `pipeline_runs` state machine (LD-8)

**Files:**
- Create: `supabase/website/_v2/49_pipeline_runs_state_machine.sql`
- Create: `supabase/website/_v2/49_pipeline_runs_state_machine.down.sql`

**OPERATOR APPROVAL REQUIRED.**

- [ ] **Step 1: Write the up migration**

```sql
-- Migration 49 (Phase 3 / LD-8): pipeline_runs state machine extension.
--
-- Today: status enum = ('pending'|'in_progress'|'succeeded'|'failed').
-- Idempotency gate blocks ALL future retries once 'succeeded' is written,
-- even for a "succeeded with edges=0" outcome that was actually a transient
-- quota failure. This causes Naruto-class permanent edgelessness.
--
-- New states:
--   'succeeded_empty'  - terminal-but-retryable; edges=0 from a clean run
--                        (no candidates found). Retryable after 24h grace.
--   'failed_retryable' - transient failure (rate limit / RPC / network).
--                        Retryable after exponential backoff.
-- Plus: retry_eligible_after timestamp for backoff scheduling.
--
-- Backfill: existing rows with status='succeeded' AND metrics->>'edges'::int = 0
-- migrate to 'succeeded_empty' so the new gate semantics take effect.

ALTER TYPE pipelines.pipeline_run_status
  ADD VALUE IF NOT EXISTS 'succeeded_empty';
ALTER TYPE pipelines.pipeline_run_status
  ADD VALUE IF NOT EXISTS 'failed_retryable';

-- Note: ALTER TYPE ADD VALUE cannot run inside a transaction with other DDL.
-- Apply this file as a single statement set, then run the rest separately.

ALTER TABLE pipelines.pipeline_runs
  ADD COLUMN IF NOT EXISTS retry_eligible_after timestamptz;

ALTER TABLE pipelines.pipeline_runs
  ADD COLUMN IF NOT EXISTS attempt_count integer NOT NULL DEFAULT 1;

-- Partial index for the retry sweep query.
CREATE INDEX IF NOT EXISTS idx_pipeline_runs_retry_eligible
  ON pipelines.pipeline_runs (kind, retry_eligible_after)
  WHERE status IN ('succeeded_empty', 'failed_retryable')
    AND retry_eligible_after IS NOT NULL;

-- Backfill: zero-edge succeeded → succeeded_empty.
UPDATE pipelines.pipeline_runs
   SET status = 'succeeded_empty',
       retry_eligible_after = finished_at + interval '24 hours'
 WHERE status = 'succeeded'
   AND kind = 'kg_extract'
   AND (metrics->>'edges')::int = 0
   AND finished_at IS NOT NULL;

COMMENT ON COLUMN pipelines.pipeline_runs.retry_eligible_after IS
  'LD-8: timestamp after which a succeeded_empty / failed_retryable run is eligible for replay.';
COMMENT ON COLUMN pipelines.pipeline_runs.attempt_count IS
  'LD-8: monotonic counter of retry attempts; used for exponential backoff in failed_retryable.';
```

- [ ] **Step 2: Down migration**

```sql
DROP INDEX IF EXISTS pipelines.idx_pipeline_runs_retry_eligible;
ALTER TABLE pipelines.pipeline_runs DROP COLUMN IF EXISTS attempt_count;
ALTER TABLE pipelines.pipeline_runs DROP COLUMN IF EXISTS retry_eligible_after;
-- enum values cannot be dropped in Postgres; left in place (no-op).
```

- [ ] **Step 3: Apply locally + verify**

```bash
psql "$SUPABASE_DEV_URL" -f supabase/website/_v2/49_pipeline_runs_state_machine.sql
psql "$SUPABASE_DEV_URL" -c "SELECT unnest(enum_range(NULL::pipelines.pipeline_run_status));"
```
Expected: `succeeded_empty`, `failed_retryable` appear.

- [ ] **Step 4: Request operator approval before prod**

- [ ] **Step 5: Commit**

```bash
git add supabase/website/_v2/49_pipeline_runs_state_machine.sql supabase/website/_v2/49_pipeline_runs_state_machine.down.sql
git commit -m "ops: migration 49 pipeline_runs state machine (LD-8)"
```

---

### Task 3.2: Typed `EmbeddingResult` dataclass (B6, O3)

**Files:**
- Modify: `website/features/kg_features/embeddings.py` (add dataclass + new typed methods)
- Test: `tests/unit/website/kg_features/test_embeddings_result.py` (CREATE)

- [ ] **Step 1: Write failing tests**

```python
"""LD-8 / O3: embeddings must distinguish ok / rate_limit / rpc_error / empty."""
import pytest
from unittest.mock import patch, MagicMock

from website.features.kg_features.embeddings import (
    EmbeddingResult,
    EmbeddingFailureReason,
    generate_embedding_typed,
)


def test_result_ok_carries_vector():
    r = EmbeddingResult(ok=True, vectors=[[0.1] * 768], reason=None, retryable=False)
    assert r.ok and len(r.vectors[0]) == 768


def test_result_rate_limit_is_retryable():
    r = EmbeddingResult(ok=False, vectors=[], reason=EmbeddingFailureReason.RATE_LIMIT, retryable=True)
    assert not r.ok and r.retryable


def test_generate_embedding_typed_empty_input_returns_empty_not_failure():
    r = generate_embedding_typed("")
    assert r.ok is False
    assert r.reason == EmbeddingFailureReason.EMPTY_INPUT
    assert r.retryable is False  # empty input is terminal, never retried
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/unit/website/kg_features/test_embeddings_result.py -v`
Expected: FAIL — names don't exist.

- [ ] **Step 3: Add the dataclass + typed wrapper to `embeddings.py`**

Append after the existing `generate_embeddings_batch`:

```python
# ── LD-8 / O3: typed embedding result for retry-aware callers ────────────────


import enum
from dataclasses import dataclass


class EmbeddingFailureReason(str, enum.Enum):
    """Distinguishes the failure modes the caller must branch on."""
    EMPTY_INPUT = "empty_input"        # terminal — never retry
    RATE_LIMIT = "rate_limit"          # retryable with backoff
    RPC_ERROR = "rpc_error"            # retryable with backoff
    NETWORK = "network"                # retryable with backoff
    EMPTY_VECTOR = "empty_vector"      # provider returned [] — treat as RPC


@dataclass(slots=True)
class EmbeddingResult:
    """Typed result of an embedding call. O3 fix: callers cannot conflate
    'no vector returned' with 'rate-limited transient failure'."""

    ok: bool
    vectors: list[list[float]]
    reason: EmbeddingFailureReason | None
    retryable: bool


def generate_embedding_typed(
    text: str,
    task_type: str = "RETRIEVAL_DOCUMENT",
) -> EmbeddingResult:
    """Typed counterpart of ``generate_embedding``.

    Returns ``ok=True`` only when a non-empty vector landed. Empty input is a
    terminal failure (never retried). All other failure modes are retryable
    via exponential backoff per LD-8.
    """
    if not text or not text.strip():
        return EmbeddingResult(
            ok=False, vectors=[],
            reason=EmbeddingFailureReason.EMPTY_INPUT,
            retryable=False,
        )
    try:
        pool = get_key_pool()
        response = pool.embed_content_safe(
            text,
            config={"task_type": task_type, "output_dimensionality": _EMBEDDING_DIMS},
        )
        if response is None:
            # Pool exhausted — typically rate-limit cascade.
            return EmbeddingResult(
                ok=False, vectors=[],
                reason=EmbeddingFailureReason.RATE_LIMIT,
                retryable=True,
            )
        vec = _normalize_embedding(response.embeddings[0].values)
        if not vec:
            return EmbeddingResult(
                ok=False, vectors=[],
                reason=EmbeddingFailureReason.EMPTY_VECTOR,
                retryable=True,
            )
        return EmbeddingResult(ok=True, vectors=[vec], reason=None, retryable=False)
    except Exception as exc:
        msg = str(exc).lower()
        if "429" in msg or "rate" in msg or "quota" in msg:
            reason = EmbeddingFailureReason.RATE_LIMIT
        elif "rpc" in msg or "postgrest" in msg:
            reason = EmbeddingFailureReason.RPC_ERROR
        else:
            reason = EmbeddingFailureReason.NETWORK
        logger.error("Embedding typed call failed (%s): %s", reason.value, exc)
        return EmbeddingResult(ok=False, vectors=[], reason=reason, retryable=True)
```

- [ ] **Step 4: Run tests to verify pass**

Run: `pytest tests/unit/website/kg_features/test_embeddings_result.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tests/unit/website/kg_features/test_embeddings_result.py website/features/kg_features/embeddings.py
git commit -m "feat: typed EmbeddingResult with retry classification (O3,LD-8)"
```

---

### Task 3.3: kg-populate state machine wiring (B3, B4, LD-8)

**Files:**
- Modify: `website/core/supabase_v2/repositories/pipelines_repository.py` (add `finish_run_with_state`)
- Modify: `website/features/rag_pipeline/ingest/kg_population.py:771-937` (`populate_kg_for_zettel`)

- [ ] **Step 1: Add `finish_run_with_state` to `PipelinesRepository`**

```python
def finish_run_with_state(
    self,
    *,
    run_id: int,
    state: str,  # one of: succeeded | succeeded_empty | failed_retryable | failed_permanent
    metrics: dict | None = None,
    error: str | None = None,
    retry_eligible_after: datetime | None = None,
) -> None:
    """LD-8: write a terminal state with optional retry timestamp.

    `succeeded`              → edges > 0 produced.
    `succeeded_empty`        → run completed cleanly, no candidates (retry after 24h).
    `failed_retryable`       → transient failure (rate limit / RPC); set retry_eligible_after.
    `failed_permanent`       → terminal failure (corrupt input, schema invariant).
    """
    payload = {
        "status": state,
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "metrics": metrics or {},
        "error": error,
        "retry_eligible_after": (
            retry_eligible_after.isoformat() if retry_eligible_after else None
        ),
    }
    self._client.schema("pipelines").table("pipeline_runs").update(payload).eq("id", run_id).execute()


def list_retryable_runs(
    self, *, kind: str = "kg_extract", limit: int = 100
) -> list[dict]:
    """Return runs whose retry_eligible_after has elapsed and need replay."""
    now_iso = datetime.now(timezone.utc).isoformat()
    response = (
        self._client.schema("pipelines")
        .table("pipeline_runs")
        .select("id,canonical_zettel_id,workspace_id,status,attempt_count")
        .eq("kind", kind)
        .in_("status", ["succeeded_empty", "failed_retryable"])
        .lte("retry_eligible_after", now_iso)
        .order("retry_eligible_after", desc=False)
        .limit(limit)
        .execute()
    )
    return list(response.data or [])
```

Also extend the existing `has_succeeded_run` to gate ONLY on truly-terminal-success states:

```python
def has_succeeded_run(
    self,
    *,
    workspace_id: UUID,
    kind: str,
    canonical_zettel_id: UUID,
) -> bool:
    """LD-8: idempotency gate.

    Returns True ONLY for terminal success states that should block retry:
      - 'succeeded' with edges > 0 (real terminal success)
      - 'failed_permanent' (intentional terminal failure — corrupt input etc.)

    Does NOT gate on:
      - 'succeeded_empty' (retry after 24h)
      - 'failed_retryable' (retry after backoff)
      - 'in_progress', 'pending' (let the new run replace stale)
    """
    response = (
        self._client.schema("pipelines")
        .table("pipeline_runs")
        .select("id,status,metrics")
        .eq("workspace_id", str(workspace_id))
        .eq("kind", kind)
        .eq("canonical_zettel_id", str(canonical_zettel_id))
        .in_("status", ["succeeded", "failed_permanent"])
        .limit(1)
        .execute()
    )
    rows = list(response.data or [])
    if not rows:
        return False
    row = rows[0]
    if row["status"] == "failed_permanent":
        return True
    # succeeded gate: only block if it produced edges
    metrics = row.get("metrics") or {}
    edges = int(metrics.get("edges", 0) or 0)
    return edges > 0
```

- [ ] **Step 2: Update `populate_kg_for_zettel` to use the new states**

In `kg_population.py:871-885` (the empty-embedding branch) and `:920-937` (the exception branch), replace:

```python
# Old:
await asyncio.to_thread(
    pipelines.finish_run,
    run_id=run_id,
    status="succeeded",
    metrics=metrics,
)
```

with:

```python
# LD-8: empty embedding = retryable failure (quota will recover).
from datetime import datetime, timedelta, timezone
await asyncio.to_thread(
    pipelines.finish_run_with_state,
    run_id=run_id,
    state="failed_retryable",
    metrics=metrics,
    error="embedding_unavailable",
    retry_eligible_after=datetime.now(timezone.utc) + timedelta(hours=1),
)
return metrics
```

For the successful-path terminal write at `:908-913`:

```python
# LD-8: success with edges > 0 is terminal-success; edges == 0 is retryable.
from datetime import datetime, timedelta, timezone
if metrics.get("edges", 0) > 0:
    await asyncio.to_thread(
        pipelines.finish_run_with_state,
        run_id=run_id, state="succeeded", metrics=metrics,
    )
else:
    await asyncio.to_thread(
        pipelines.finish_run_with_state,
        run_id=run_id, state="succeeded_empty", metrics=metrics,
        retry_eligible_after=datetime.now(timezone.utc) + timedelta(hours=24),
    )
```

- [ ] **Step 3: Swap `generate_embedding` → `generate_embedding_typed` in `kg_population.py:841`**

```python
from website.features.kg_features.embeddings import (
    generate_embedding_typed,
    EmbeddingFailureReason,
)
# ...
embed_input = f"{title}\n\n{summary}".strip()[:2000]
embed_result = await asyncio.to_thread(generate_embedding_typed, embed_input)
if not embed_result.ok:
    # LD-8: typed retry path.
    metrics["error"] = (embed_result.reason or "unknown").value if hasattr(embed_result.reason, "value") else str(embed_result.reason)
    delay_hours = 1 if embed_result.retryable else 24
    await asyncio.to_thread(
        pipelines.finish_run_with_state,
        run_id=run_id,
        state="failed_retryable" if embed_result.retryable else "failed_permanent",
        metrics=metrics,
        error=metrics["error"],
        retry_eligible_after=(
            datetime.now(timezone.utc) + timedelta(hours=delay_hours)
            if embed_result.retryable else None
        ),
    )
    return metrics
node_embedding = embed_result.vectors[0]
```

- [ ] **Step 4: Run integration tests**

```bash
pytest tests/integration/v2/ -v -k kg_population
```
Expected: PASS (existing tests still pass; retryable states are now written when applicable).

- [ ] **Step 5: Commit**

```bash
git add website/core/supabase_v2/repositories/pipelines_repository.py website/features/rag_pipeline/ingest/kg_population.py
git commit -m "fix: kg-populate state machine retry classification (B3,B4,LD-8)"
```

---

### Task 3.4: Scoring math fixes — temporal floor (M1), Jaccard asymmetric (M3), AA continuous (M5)

**Files:**
- Modify: `website/features/kg_features/scoring.py:96-126` (`_jaccard`, `_temporal_signal`)
- Modify: `website/features/rag_pipeline/ingest/kg_population.py:367` (AA combiner)
- Test: `tests/unit/website/kg_features/test_scoring_math.py` (CREATE)

- [ ] **Step 1: Write failing tests**

```python
"""Scoring math fixes — M1 temporal floor, M3 Jaccard asymmetric, M5 AA continuous."""
import math
import pytest

from website.features.kg_features.scoring import (
    _jaccard,
    _temporal_signal,
    _cosine_similarity,
)


# M1: minimum-age floor so batch ingest doesn't max temporal to 1.0
def test_temporal_signal_zero_days_caps_below_one():
    """Burst-ingest same-minute pair gets <= ~0.967, not 1.0."""
    sig = _temporal_signal(0.0)
    assert sig < 1.0
    assert sig > 0.95


def test_temporal_signal_30d_stable():
    """Halflife unchanged — 30d still ~0.37."""
    assert 0.35 < _temporal_signal(30.0) < 0.40


# M3: Jaccard returns None for asymmetric empty
def test_jaccard_both_empty_returns_zero():
    assert _jaccard([], []) == 0.0


def test_jaccard_one_empty_returns_none():
    """One side has tags, the other doesn't — signal-absent, not signal-zero."""
    assert _jaccard(["python"], []) is None
    assert _jaccard([], ["rust"]) is None


def test_jaccard_disjoint_returns_zero():
    assert _jaccard(["python"], ["rust"]) == 0.0


def test_jaccard_perfect_overlap_returns_one():
    assert _jaccard(["python", "async"], ["async", "python"]) == 1.0
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/unit/website/kg_features/test_scoring_math.py -v`
Expected: FAIL — Jaccard returns 0 for asymmetric, temporal returns 1.0 at 0 days.

- [ ] **Step 3: Update `_temporal_signal` and `_jaccard`**

In `scoring.py`:

```python
def _jaccard(set_a: Iterable[str], set_b: Iterable[str]) -> float | None:
    """Jaccard similarity on tag sets.

    M3: distinguishes three semantics:
      - both empty            → 0.0 (no signal, but both sides agree)
      - exactly one empty     → None (signal-absent; caller redistributes weight)
      - both non-empty        → |inter| / |union|
    """
    sa = {t for t in set_a if t}
    sb = {t for t in set_b if t}
    if not sa and not sb:
        return 0.0
    if not sa or not sb:
        return None  # signal-absent
    inter = len(sa & sb)
    union = len(sa | sb)
    if union == 0:
        return 0.0
    return inter / union


def _temporal_signal(temporal_days: float) -> float:
    """Exponential decay with ~30d half-life.

    M1: applies a minimum-age floor of 1.0 day so burst-ingest pairs don't
    score temporal=1.0. exp(-1/30) ≈ 0.967 — still strong, no longer perfect.
    """
    if temporal_days is None:
        return 0.0
    days = max(1.0, float(temporal_days))  # M1: floor at 1.0d
    return math.exp(-days / _TEMPORAL_HALFLIFE_DAYS)
```

- [ ] **Step 4: Update `compute_connection_strength` to handle `None` from Jaccard**

In `scoring.py:140-176`:

```python
def compute_connection_strength(
    node_a: str,
    node_b: str,
    *,
    embeddings: Mapping[str, Sequence[float]] | None = None,
    tags: Mapping[str, Sequence[str]] | None = None,
    structural: Mapping[str, Mapping[str, int]] | None = None,
    temporal_days: float = 0.0,
) -> float:
    embeddings = embeddings or {}
    tags = tags or {}
    structural = structural or {}

    emb = _cosine_similarity(
        list(embeddings.get(node_a, ())),
        list(embeddings.get(node_b, ())),
    )
    tag = _jaccard(tags.get(node_a, ()), tags.get(node_b, ()))
    struct = _structural_signal(node_a, node_b, structural)
    temp = _temporal_signal(temporal_days)

    # M3 weight redistribution: when tag signal is absent (None), distribute
    # the 0.25 tag weight proportionally over the remaining 3 signals.
    if tag is None:
        # Redistribute: emb gets 0.55 + 0.55/0.95 * 0.25 ≈ 0.69; struct gets
        # 0.15 + 0.15/0.95 * 0.25 ≈ 0.19; temp gets 0.05 + 0.05/0.95 * 0.25 ≈ 0.06.
        remaining_weight = 1.0 - WEIGHTS["tag"]  # 0.75
        score = (
            (WEIGHTS["embedding"] / remaining_weight) * emb
            + (WEIGHTS["structural"] / remaining_weight) * struct
            + (WEIGHTS["temporal"] / remaining_weight) * temp
        )
    else:
        score = (
            WEIGHTS["embedding"] * emb
            + WEIGHTS["tag"] * tag
            + WEIGHTS["structural"] * struct
            + WEIGHTS["temporal"] * temp
        )
    return max(0.0, min(1.0, score))
```

- [ ] **Step 5: Update AA combiner in `kg_population.py:367` (M5)**

Replace the inline `effective = co + round(_ADAMIC_AA_WEIGHT * a)` with continuous:

```python
# M5: continuous AA combiner — never rounds away small contributions.
effective_float = co + _ADAMIC_AA_WEIGHT * a
# Update structural_signal to use the float directly: count/(count+2).
# scoring._structural_signal already does this with the integer; we extend it
# below in scoring.py to accept a float-valued map.
```

Since `_structural_signal` currently treats values as `int`, update `scoring.py` to handle floats:

```python
def _structural_signal(
    a: str, b: str,
    structural: Mapping[str, Mapping[str, int | float]],  # M5: accept floats
) -> float:
    """Co-occurrence-based structural signal mapped to [0, 1].

    M5: now accepts float-valued maps so the kg_population combiner can pass
    `co + 0.5 * adamic_adar` directly without rounding away fractional AA.
    """
    count_ab = structural.get(a, {}).get(b, 0) if structural else 0
    count_ba = structural.get(b, {}).get(a, 0) if structural else 0
    count = max(float(count_ab), float(count_ba))
    if count <= 0:
        return 0.0
    return count / (count + 2.0)
```

And in `kg_population._structural_map`, change `effective = co + round(_ADAMIC_AA_WEIGHT * a)` → `effective_float = co + _ADAMIC_AA_WEIGHT * a; ... structural.setdefault(new_key, {})[cand_key] = effective_float` (drop the `if effective <= 0: continue` guard if `effective_float <= 0` instead).

- [ ] **Step 6: Run tests to verify**

```bash
pytest tests/unit/website/kg_features/ -v
```
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add tests/unit/website/kg_features/test_scoring_math.py website/features/kg_features/scoring.py website/features/rag_pipeline/ingest/kg_population.py
git commit -m "fix: scoring math — temporal floor, Jaccard asymmetric, AA continuous (M1,M3,M5)"
```

---

### Task 3.5: Cosine clamp + Prometheus drift counter (LD-4)

**Files:**
- Modify: `website/features/kg_features/scoring.py:67-94` (`_cosine_similarity`)
- Create: `website/core/kg_metrics.py` (CREATE — Prometheus registry helpers; full file in Phase 4 Task 4.6)

For Phase 3 the counter is just a module-level `Counter` referenced by name; the full `/metrics` endpoint wiring happens in Phase 4.

- [ ] **Step 1: Install prometheus_client**

Add to `ops/requirements.txt`:
```
prometheus_client>=0.20
```
Then:
```bash
pip install -r ops/requirements.txt
```

- [ ] **Step 2: Create the counter module**

Create `website/core/kg_metrics.py`:

```python
"""LD-4: Prometheus counter for negative-cosine drift detection.

Phase 3 introduces the counter; Phase 4 wires the full /api/metrics endpoint.
This module can be imported safely even when prometheus_client is missing
(degrades to a no-op double).
"""
from __future__ import annotations

try:
    from prometheus_client import Counter, Histogram
    _PROMETHEUS_AVAILABLE = True
except ImportError:
    _PROMETHEUS_AVAILABLE = False

    class _NoOp:
        def labels(self, *args, **kwargs): return self
        def inc(self, *args, **kwargs): pass
        def observe(self, *args, **kwargs): pass

    Counter = Histogram = lambda *a, **kw: _NoOp()  # type: ignore


# LD-4: alert at >2% to detect Gemini embedding-model drift.
cosine_negative_total = Counter(
    "kg_cosine_negative_total",
    "Count of pairs where raw cosine was negative (drift indicator).",
)

# Used in Phase 4 Task 4.6 by other modules.
kg_edge_drops_total = Counter(
    "kg_edge_drops_total",
    "KG edges dropped from /api/graph payload by reason.",
    ["reason"],  # unresolved_endpoint | cross_workspace | tier_filter
)

kg_populate_runs_total = Counter(
    "kg_populate_runs_total",
    "kg_populate terminal outcomes.",
    ["outcome"],  # succeeded | succeeded_empty | failed_retryable | failed_permanent | skipped_idempotent
)

kg_populate_duration_seconds = Histogram(
    "kg_populate_duration_seconds",
    "Wall time of populate_kg_for_zettel.",
)

cosine_pair_total = Counter(
    "kg_cosine_pair_total",
    "Total pairs scored by cosine (denominator for drift rate).",
)
```

- [ ] **Step 3: Update `_cosine_similarity` in `scoring.py:67-94`**

```python
def _cosine_similarity(va: Sequence[float], vb: Sequence[float]) -> float:
    """Dim-mismatch / empty / zero-norm safe cosine sim clamped to [0, 1].

    LD-4: keep the clamp for L2-normalized Gemini RETRIEVAL_DOCUMENT
    embeddings (per Garg 2024 25M-pair study, negative cosines are <0.5% of
    pairs in practice and rarely carry useful signal for our task type).
    Increment the negative-cosine counter so we can alert on model-version
    drift (threshold: >2% triggers operator alert).
    """
    if not va or not vb or len(va) != len(vb):
        return 0.0
    dot = 0.0; na = 0.0; nb = 0.0
    for ai, bi in zip(va, vb):
        dot += ai * bi
        na += ai * ai
        nb += bi * bi
    if na <= 0.0 or nb <= 0.0:
        return 0.0
    cos = dot / math.sqrt(na * nb)
    if math.isnan(cos):
        return 0.0

    # LD-4 telemetry: count every scored pair + count negatives separately.
    try:
        from website.core.kg_metrics import cosine_pair_total, cosine_negative_total
        cosine_pair_total.inc()
        if cos < 0.0:
            cosine_negative_total.inc()
    except Exception:
        pass  # never let telemetry break scoring

    cos = max(-1.0, min(1.0, cos))
    return max(0.0, cos)
```

- [ ] **Step 4: Commit**

```bash
git add ops/requirements.txt website/core/kg_metrics.py website/features/kg_features/scoring.py
git commit -m "feat: cosine clamp + drift counter (LD-4)"
```

---

### Task 3.6: BLAKE3 content-hash analytics memoization (B9, A1, A4, A5, LD-9)

**Files:**
- Create: `website/core/graph_content_hash.py`
- Modify: `website/features/kg_features/analytics.py:142-266` (`compute_graph_metrics` accepts optional `graph_hash` for caching)
- Modify: `website/api/routes.py:128-185` (`_enrich_graph_with_analytics` uses memo)

- [ ] **Step 1: Install dependencies**

Append to `ops/requirements.txt`:
```
blake3>=0.4
cachetools>=5.3
```
Then `pip install -r ops/requirements.txt`.

- [ ] **Step 2: Create `website/core/graph_content_hash.py`**

```python
"""LD-9 / A1: BLAKE3 content-hash memoization for graph analytics.

Key: blake3(sorted_node_ids ‖ sorted_edge_tuples). Two graphs with identical
topology produce identical hashes. TTL=600s, capacity=50 (per LD-9). Fits
the 2 GB / 1 vCPU droplet: 50 entries × ~250 KB metric payload ≈ 12.5 MB.
"""
from __future__ import annotations

import json
from typing import Any

from blake3 import blake3
from cachetools import TTLCache


_ANALYTICS_CACHE: TTLCache[str, Any] = TTLCache(maxsize=50, ttl=600)


def compute_graph_hash(graph_dict: dict) -> str:
    """Deterministic hash of (nodes, edges) topology.

    Excludes per-node metric fields (pagerank, community, etc.) and edge
    properties that don't affect topology (strength, tier) so a re-scored
    same-topology graph still hits the cache.
    """
    nodes = sorted(
        str(n.get("id", "")) for n in graph_dict.get("nodes", [])
        if isinstance(n, dict)
    )
    edges = sorted(
        (str(link.get("source", "")), str(link.get("target", "")), str(link.get("relation", "")))
        for link in graph_dict.get("links", [])
        if isinstance(link, dict)
    )
    payload = json.dumps({"n": nodes, "e": edges}, separators=(",", ":"))
    return blake3(payload.encode("utf-8")).hexdigest()


def get_cached_metrics(graph_hash: str):
    return _ANALYTICS_CACHE.get(graph_hash)


def put_cached_metrics(graph_hash: str, metrics: Any) -> None:
    _ANALYTICS_CACHE[graph_hash] = metrics


def invalidate_all() -> None:
    """Admin / test helper."""
    _ANALYTICS_CACHE.clear()
```

- [ ] **Step 3: Update `_enrich_graph_with_analytics` in `routes.py:128-185`**

```python
def _enrich_graph_with_analytics(
    graph_dict: dict,
    min_strength: float | None = None,
) -> dict:
    """LD-10 + A4 fix: compute metrics on the FULL graph (not the strength-
    filtered subgraph) so node importance stays stable when the user moves
    the slider. The wire-level link cull happens AFTER enrichment.

    LD-9 / A1: results memoized by BLAKE3 content hash.
    """
    from website.core.summary_normalizer import normalize_graph_nodes
    normalize_graph_nodes(graph_dict)

    from website.core.graph_content_hash import (
        compute_graph_hash, get_cached_metrics, put_cached_metrics,
    )
    graph_hash = compute_graph_hash(graph_dict)
    metrics = get_cached_metrics(graph_hash)

    if metrics is None:
        try:
            from website.features.kg_features.analytics import compute_graph_metrics
            kg_graph = KGGraph(**graph_dict)
            metrics = compute_graph_metrics(kg_graph)
            put_cached_metrics(graph_hash, metrics)
        except Exception as exc:
            logger.warning("Graph analytics enrichment failed: %s", exc)
            metrics = None

    if metrics is not None:
        for node in graph_dict.get("nodes", []):
            nid = node["id"]
            node["pagerank"] = metrics.pagerank.get(nid, 0)
            node["community"] = metrics.communities.get(nid, 0)
            # A2: surface fallback so frontend can show banner.
            graph_dict.setdefault("meta", {})["louvain_fallback"] = (
                metrics.num_communities <= 1 and len(graph_dict.get("nodes", [])) > 1
            )
        graph_dict["meta"] = {
            **graph_dict.get("meta", {}),
            "communities": metrics.num_communities,
            "components": metrics.num_components,
            "computed_at": metrics.computed_at,
            "analytics_status": "ok",
            "graph_hash": graph_hash[:16],
        }
    else:
        graph_dict.setdefault("meta", {})["analytics_status"] = "failed"

    return graph_dict
```

- [ ] **Step 4: Run a quick perf smoke**

```bash
# First call (cache miss)
time curl -s "http://localhost:10000/api/graph?min_strength=0.30" > /dev/null
# Second call (cache hit — should be much faster)
time curl -s "http://localhost:10000/api/graph?min_strength=0.30" > /dev/null
```
Expected: second call >5× faster.

- [ ] **Step 5: Commit**

```bash
git add ops/requirements.txt website/core/graph_content_hash.py website/api/routes.py
git commit -m "feat: BLAKE3 content-hash analytics memo (LD-9,B9,A1,A4)"
```

---

### Task 3.7: Louvain failure surfaced via meta (A2)

**Files:**
- Modify: `website/features/kg_features/analytics.py:193-207` (Louvain fallback)
- Modify: `website/features/knowledge_graph/js/app.js` (banner UI; the meta flag is already wired by Task 3.6)

- [ ] **Step 1: Set `num_communities = 0` (not 1) on fallback so the meta detection works**

In `analytics.py:202-206`, change:

```python
communities, num_communities = _safe(
    "Louvain community detection",
    _louvain,
    lambda: ({nid: 0 for nid in node_ids}, 0),  # A2: 0 (not 1) signals fallback
)
```

- [ ] **Step 2: Add a frontend banner that reads `meta.louvain_fallback`**

In `app.js`, find the `loadGraphData` `.then(data => {…})` block and after `nodeDegrees = computeDegrees(fullData);` add:

```javascript
// A2: surface analytics degradation.
const banner = document.getElementById('kg-analytics-banner');
const louvainFallback = data && data.meta && data.meta.louvain_fallback;
const analyticsFailed = data && data.meta && data.meta.analytics_status === 'failed';
if (banner) {
  if (analyticsFailed) {
    banner.textContent = 'Community detection unavailable — coloring by source.';
    banner.classList.remove('hidden');
  } else if (louvainFallback) {
    banner.textContent = 'Community detection degraded — using fallback hue.';
    banner.classList.remove('hidden');
  } else {
    banner.classList.add('hidden');
  }
}
```

And in `index.html` after the header:

```html
<div id="kg-analytics-banner" class="kg-banner hidden" role="status" aria-live="polite"></div>
```

Plus CSS in `style.css`:

```css
.kg-banner {
  position: fixed; top: 72px; left: 50%; transform: translateX(-50%);
  background: rgba(180, 60, 40, 0.85); color: #fff;
  padding: 6px 14px; border-radius: 8px; font-size: 0.78rem;
  z-index: 200; backdrop-filter: blur(4px);
}
.kg-banner.hidden { display: none; }
```

- [ ] **Step 3: Commit**

```bash
git add website/features/kg_features/analytics.py website/features/knowledge_graph/js/app.js website/features/knowledge_graph/index.html website/features/knowledge_graph/css/style.css
git commit -m "fix: surface Louvain fallback as user-visible banner (A2)"
```

---

### Task 3.8: Harmonic centrality hard-cap at 1500 nodes (A3)

**Files:**
- Modify: `website/features/kg_features/analytics.py:215-253` (`_harmonic`)

- [ ] **Step 1: Update `_harmonic` to refuse the dense fallback past 1500 nodes**

```python
_HARMONIC_FALLBACK_MAX_NODES = 1500  # A3: never run shortest_paths matrix on huge graphs

def _harmonic() -> dict[str, float]:
    if g.ecount() > _DEFAULT_HARMONIC_MAX_EDGES:
        logger.info("Skipping harmonic centrality for graph with %s nodes and %s edges",
                    g.vcount(), g.ecount())
        return {nid: 0.0 for nid in node_ids}
    if hasattr(g, "harmonic_centrality"):
        hc = g.harmonic_centrality(mode="all", cutoff=3, normalized=True)
        return {nid: float(hc[i]) for i, nid in enumerate(node_ids)}
    # A3: hard-cap the dense shortest_paths fallback. >1500 nodes = 2.25M
    # floats matrix = ~18MB transient — risky on the 2GB droplet under load.
    if g.vcount() > _HARMONIC_FALLBACK_MAX_NODES:
        logger.warning(
            "Harmonic fallback skipped: %d nodes > cap %d (would allocate dense V×V matrix)",
            g.vcount(), _HARMONIC_FALLBACK_MAX_NODES,
        )
        return {nid: 0.0 for nid in node_ids}
    # Original fallback (only reached for small graphs).
    n = g.vcount()
    if n <= 1:
        return {nid: 0.0 for nid in node_ids}
    sp = g.shortest_paths()
    # ... (rest unchanged)
```

- [ ] **Step 2: Commit**

```bash
git add website/features/kg_features/analytics.py
git commit -m "fix: harmonic fallback hard-capped at 1500 nodes (A3)"
```

---

### Task 3.9: Render perf — label clamp → onEngineStop + onBeforeRender (F4, X6)

**Files:**
- Modify: `website/features/knowledge_graph/js/app.js:898-936` (delete rAF `clampLabelScales`)
- Modify: `website/features/knowledge_graph/js/app.js:711-849` (graph init — add onEngineStop hook)
- Modify: `website/features/knowledge_graph/js/app.js:621-624,881,890` (replace setTimeout with onEngineStop)

- [ ] **Step 1: Delete the per-frame loop**

Remove the entire `clampLabelScales` function body (`app.js:898-936`) and the trailing `requestAnimationFrame(clampLabelScales);` call.

- [ ] **Step 2: Replace with onBeforeRender per Sprite + onEngineStop one-shot**

In `nodeThreeObject` (`app.js:716-786`), after `group.add(sprite);`, add:

```javascript
// F4: per-sprite onBeforeRender clamps scale only when the sprite is about
// to render. Replaces the 60Hz O(N) rAF loop. The renderer calls this with
// the active camera, so we get correct frustum-culled behavior for free.
sprite.onBeforeRender = function(renderer, scene, cam) {
  if (sprite.__origSy === undefined) {
    sprite.__origSy = sprite.scale.y;
    sprite.__origSx = sprite.scale.x;
  }
  const worldPos = new THREE.Vector3();
  sprite.getWorldPosition(worldPos);
  const dist = cam.position.distanceTo(worldPos);
  const maxH = dist * MAX_LABEL_FRAC;
  if (sprite.__origSy > maxH && maxH > 0) {
    const r = maxH / sprite.__origSy;
    sprite.scale.set(sprite.__origSx * r, sprite.__origSy * r, 1);
  } else {
    sprite.scale.set(sprite.__origSx, sprite.__origSy, 1);
  }
};
```

For the active-node HTML overlay (`_updateActiveLabel`), keep it on its own rAF — but only update when there's an active node:

```javascript
function _updateActiveLabelLoop() {
  requestAnimationFrame(_updateActiveLabelLoop);
  if (!selectedNode && !hoverNode) return;
  _updateActiveLabel();
}
requestAnimationFrame(_updateActiveLabelLoop);
```

- [ ] **Step 3: Replace deep-link setTimeout with onEngineStop (X6)**

In `initGraph` (`app.js:847`), after the cooldownTime line, add:

```javascript
graph.onEngineStop(() => {
  // X6: layout settled — fire any pending deep-link focus or zoomToFit.
  if (spotlightId && !_didDeepLinkFocus) {
    const sNode = graphData.nodes.find(n => n.id === spotlightId);
    if (sNode) handleNodeClick(sNode);
    _didDeepLinkFocus = true;
  }
});
```

Declare `let _didDeepLinkFocus = false;` at the top of the IIFE state block.

Delete the three setTimeout calls at `app.js:621-626`, `:881-888`, `:890`. Replace with the `graph.onEngineStop` callback above.

- [ ] **Step 4: Manual smoke**

Open the worktree's `/knowledge-graph`. Drag the graph around vigorously. Expected: labels stay readable, no visible jitter; framerate stable at 60fps on a typical laptop.

- [ ] **Step 5: Commit**

```bash
git add website/features/knowledge_graph/js/app.js
git commit -m "perf: label clamp via onBeforeRender; deep-link via onEngineStop (F4,X6)"
```

---

### Task 3.10: Particles off by default; hover-only (F5)

**Files:**
- Modify: `website/features/knowledge_graph/js/app.js:820-826` (`linkDirectionalParticles`)

- [ ] **Step 1: Change particles to be hover-driven**

Replace `app.js:820`:

```javascript
.linkDirectionalParticles(link => {
  // F5: particles are GPU-expensive (1 cylinder per link per frame).
  // Show only on hover/selected for snappy interaction at scale.
  if (!hoverNode && !selectedNode) return 0;
  const src = typeof link.source === 'object' ? link.source : null;
  const tgt = typeof link.target === 'object' ? link.target : null;
  const active = hoverNode || selectedNode;
  const touches = (src && src.id === active.id) || (tgt && tgt.id === active.id);
  return touches ? 1 : 0;
})
```

- [ ] **Step 2: Force a re-render on hover/select changes**

In `_updateNodeVisual` and `handleNodeClick`, after the state mutation, add:

```javascript
if (graph && typeof graph.refresh === 'function') graph.refresh();
```

- [ ] **Step 3: Manual smoke**

Verify hovering a node lights up flowing particles on its edges; particles disappear when hover leaves; idle graph has zero particles.

- [ ] **Step 4: Commit**

```bash
git add website/features/knowledge_graph/js/app.js
git commit -m "perf: particles hover-only by default (F5)"
```

---

### Task 3.11: WeakMap-memoized summary parse + optional MiniSearch (F6)

**Files:**
- Modify: `website/features/knowledge_graph/js/app.js:158-207` (`extractBriefFromSummary` + memo)
- Modify: `website/features/knowledge_graph/js/app.js:1146` (`_applySearch` uses memo)
- Modify: `website/features/knowledge_graph/index.html` (add MiniSearch CDN — optional)

- [ ] **Step 1: Add a WeakMap memo for parsed summaries**

In `app.js` near the top of the IIFE:

```javascript
const _briefMemo = new WeakMap();
function getBrief(node) {
  if (!node || typeof node !== 'object') return '';
  let brief = _briefMemo.get(node);
  if (brief === undefined) {
    brief = extractBriefFromSummary(node.summary);
    _briefMemo.set(node, brief);
  }
  return brief;
}
```

- [ ] **Step 2: Replace direct calls in `_applySearch` (`app.js:1146`) and `openPanel`**

`app.js:1146`:
```javascript
const nodeSummary = getBrief(node);
```

`app.js:1054`:
```javascript
summary.textContent = getBrief(node);
```

- [ ] **Step 3: (Optional) Add MiniSearch for >2k nodes**

In `index.html:269` add (before the `app.js` script tag):

```html
<script src="https://cdn.jsdelivr.net/npm/minisearch@7.1.0/dist/umd/index.min.js" defer></script>
```

In `app.js`, build the index in `loadGraphData`'s success callback:

```javascript
if (fullData.nodes.length > 2000 && typeof MiniSearch !== 'undefined') {
  _searchIndex = new MiniSearch({
    fields: ['name', 'tagsText', 'brief'],
    storeFields: ['id'],
    searchOptions: { fuzzy: 0.2, prefix: true },
  });
  const docs = fullData.nodes.map(n => ({
    id: n.id, name: n.name || '',
    tagsText: (n.tags || []).join(' '),
    brief: getBrief(n),
  }));
  // Idle-time chunked indexing
  if ('requestIdleCallback' in window) {
    window.requestIdleCallback(() => _searchIndex.addAllAsync(docs));
  } else {
    _searchIndex.addAll(docs);
  }
}
```

And in `_applySearch`, prefer the index when present.

- [ ] **Step 4: Commit**

```bash
git add website/features/knowledge_graph/js/app.js website/features/knowledge_graph/index.html
git commit -m "perf: memoize parsed summary + optional MiniSearch (F6)"
```

---

### Task 3.12: Precompute addable-neighbor set (F7)

**Files:**
- Modify: `website/features/knowledge_graph/js/app.js:381-391` (`computeAddBtnState`)

- [ ] **Step 1: Maintain `_addableInGlobal` set in state**

Declare near the top of the IIFE:
```javascript
let _addableInGlobal = new Set();
```

- [ ] **Step 2: Rebuild on `userOwnedIds` change OR `fullData` change**

Create a helper:
```javascript
function _rebuildAddableSet() {
  _addableInGlobal = new Set();
  if (!isLoggedIn || userOwnedIds.size === 0) return;
  const links = (fullData && fullData.links) ? fullData.links : [];
  for (const l of links) {
    const s = typeof l.source === 'object' ? l.source.id : l.source;
    const t = typeof l.target === 'object' ? l.target.id : l.target;
    if (userOwnedIds.has(s)) _addableInGlobal.add(t);
    if (userOwnedIds.has(t)) _addableInGlobal.add(s);
  }
}
```

Call it from:
- The `/api/me` resolver after `loadUserOwnedIds` populates `userOwnedIds`.
- The `loadGraphData` success path after `fullData = data;`.

- [ ] **Step 3: Replace `computeAddBtnState` body**

```javascript
function computeAddBtnState(node) {
  if (!isLoggedIn) return 'login';
  if (currentView === 'my') return 'enabled';
  if (userOwnedIds.has(node.id)) return 'enabled';
  // F7: O(1) lookup instead of O(links) scan.
  return _addableInGlobal.has(node.id) ? 'enabled' : 'unlinked';
}
```

- [ ] **Step 4: Commit**

```bash
git add website/features/knowledge_graph/js/app.js
git commit -m "perf: precompute addable-neighbor set for O(1) click (F7)"
```

---

### Task 3.13: Shallow-clone instead of JSON.parse/stringify (F8)

**Files:**
- Modify: `website/features/knowledge_graph/js/app.js:585-594` (post-fetch payload handling)

- [ ] **Step 1: Replace the deep clone**

`app.js:590`:
```javascript
graphData = JSON.parse(JSON.stringify(data));
```

becomes:
```javascript
// F8: shallow-clone instead of JSON round-trip. ForceGraph mutates
// node.x/y/z/vx/vy/vz on its own objects; top-level spread is enough
// isolation. Saves ~10MB GC churn on 5k-node fetches.
graphData = {
  nodes: (data.nodes || []).map(n => ({ ...n })),
  links: (data.links || []).map(l => ({ ...l })),
};
```

- [ ] **Step 2: Commit**

```bash
git add website/features/knowledge_graph/js/app.js
git commit -m "perf: shallow-clone graphData (F8)"
```

---

### Task 3.14: Delete unused AmbientLight (F9)

**Files:**
- Modify: `website/features/knowledge_graph/js/app.js:855`

- [ ] **Step 1: Delete the line**

Remove:
```javascript
graph.scene().add(new THREE.AmbientLight(0xffffff, 1));
```

(MeshBasicMaterial does not respond to lighting per Three.js docs — the AmbientLight is a no-op cluttering the scene graph.)

- [ ] **Step 2: Commit**

```bash
git add website/features/knowledge_graph/js/app.js
git commit -m "perf: delete unused AmbientLight (F9)"
```

---

### Task 3.15: Phase 3-α — D-KG-1 weight rebalance (**OPERATOR APPROVAL REQUIRED**)

**Files:**
- Modify: `website/features/kg_features/scoring.py:41-50` (`WEIGHTS`)

**THIS IS A CLAUDE.md LOCKED DECISION (D-KG-1). DO NOT IMPLEMENT WITHOUT EXPLICIT OPERATOR APPROVAL IN CHAT.** See `CLAUDE.md` § "Critical Infra Decision Guardrails".

The recommendation (combined from 3 sources): rebalance to `embedding=0.65, tag=0.20, structural=0.10, temporal=0.05` + add an embedding-only fast-path `if cos >= 0.80: create_edge regardless`.

Rationale: under current weights, two near-identical zettels with NO shared tags max ~0.55·cos + 0.05 ≈ 0.55 — below the 0.50 creation threshold for many realistic cosines. fix1 + fix2 both recommend dense-leaning + semantic-fast-path; agent-2 confirms with GraphRAG / LightRAG 2024 precedent.

- [ ] **Step 1: Surface the proposal to operator**

Halt and ask: "Phase 3-α requires D-KG-1 weight rebalance to `(0.65, 0.20, 0.10, 0.05)` + fast-path at `cos >= 0.80`. This is a LOCKED decision per CLAUDE.md. Approve?"

- [ ] **Step 2: (Only after approval) Update `WEIGHTS` + add fast-path**

- [ ] **Step 3: (Only after approval) Re-run the existing `tests/unit/test_kg_features_unreachable.py` allow-list — confirm no new importer**

- [ ] **Step 4: (Only after approval) Commit with explicit reference**

```bash
git commit -m "feat(scoring): D-KG-1 rebalance + fast-path (#operator-approved)"
```

---

### Task 3.16: Phase 3 acceptance gate

- [ ] **Step 1: Run all unit + integration tests**

```bash
pytest tests/ -v -m "not live"
```
Expected: all PASS.

- [ ] **Step 2: Manual perf check**

Open `/knowledge-graph?node=yt-attention` in Chrome. Open DevTools → Performance → Record. Spin the graph for 5 seconds. Stop recording. Expected: FPS line stays above 30 across the recording.

- [ ] **Step 3: Phase 3 closeout commit**

```bash
git commit --allow-empty -m "phase 3 complete: KG quality (retry + memo + render perf)"
```

---

## Phase 4 — Hardening (registry + wire + observability + security)

**Goal:** Consolidate the three-way source-type drift into one registry. Normalize the wire contract. Add `/api/metrics`. Tighten auth-token discovery. Retire dead code. Surface `meta.profile_source` and analytics-status flags to the UI.

**Acceptance:** Adding a new source type requires editing ONE file. `/api/metrics` exposes counters that move during a synthetic Add-Zettel flow. Anonymous tokens from a foreign Supabase project are ignored. `pseudo_tags` no longer appear in the user's tag-filter dropdown. Dead code deleted.

**Operator approval:** REQUIRED for migrations 50 (`derived_tags` column) and the B7 backfill SQL.

---

### Task 4.1: Single source-type registry (D1, D2, D3)

**Files:**
- Create: `website/core/source_registry.py`
- Create: `website/api/meta_routes.py`
- Modify: `website/core/graph_store.py:24-44` (delete `_SOURCE_PREFIX` + `_normalize_source_type`; import from registry)
- Modify: `website/features/knowledge_graph/js/app.js:106-132` (fetch + apply at boot)
- Modify: `website/features/knowledge_graph/css/style.css:26-31` (add `--node-newsletter`, `--node-twitter`)

- [ ] **Step 1: Create `website/core/source_registry.py`**

```python
"""Single source-of-truth registry for content source types.

D1 + D2 + D3 fix: three independent normalize/prefix/color implementations
collapsed to one Python module. Frontend picks up the same data via
`GET /api/meta/source-types`.
"""
from __future__ import annotations

from enum import StrEnum
from dataclasses import dataclass


class SourceType(StrEnum):
    YOUTUBE = "youtube"
    REDDIT = "reddit"
    GITHUB = "github"
    SUBSTACK = "substack"
    NEWSLETTER = "newsletter"
    MEDIUM = "medium"
    TWITTER = "twitter"
    WEB = "web"


@dataclass(frozen=True, slots=True)
class SourceMeta:
    prefix: str
    label: str
    color_hex: str
    color_int: int
    modality: str  # video | article | post | book


SOURCE_REGISTRY: dict[SourceType, SourceMeta] = {
    SourceType.YOUTUBE:    SourceMeta("yt", "YouTube",    "#E05565", 0xE05565, "video"),
    SourceType.REDDIT:     SourceMeta("rd", "Reddit",     "#E09040", 0xE09040, "post"),
    SourceType.GITHUB:     SourceMeta("gh", "GitHub",     "#56C8D8", 0x56C8D8, "article"),
    SourceType.SUBSTACK:   SourceMeta("ss", "Substack",   "#60A5FA", 0x60A5FA, "article"),
    SourceType.NEWSLETTER: SourceMeta("ss", "Newsletter", "#60A5FA", 0x60A5FA, "article"),
    SourceType.MEDIUM:     SourceMeta("md", "Medium",     "#4ADE80", 0x4ADE80, "article"),
    SourceType.TWITTER:    SourceMeta("tw", "Twitter",    "#1DA1F2", 0x1DA1F2, "post"),
    SourceType.WEB:        SourceMeta("web", "Web",       "#94A3B8", 0x94A3B8, "article"),
}

# Legacy alias: 'generic' → web (D3 cleanup).
_ALIASES = {"generic": SourceType.WEB}


def normalize(source_type: str | None) -> SourceType:
    """Normalize raw input to a SourceType enum. Unknown → WEB."""
    normalized = (source_type or "").strip().lower()
    if not normalized:
        return SourceType.WEB
    if normalized in _ALIASES:
        return _ALIASES[normalized]
    try:
        return SourceType(normalized)
    except ValueError:
        return SourceType.WEB


def prefix(source_type: str | None) -> str:
    return SOURCE_REGISTRY[normalize(source_type)].prefix


def to_wire_dict() -> dict:
    """Serialize for the /api/meta/source-types endpoint."""
    return {
        st.value: {
            "prefix": meta.prefix,
            "label": meta.label,
            "color_hex": meta.color_hex,
            "color_int": meta.color_int,
            "modality": meta.modality,
        }
        for st, meta in SOURCE_REGISTRY.items()
    }
```

- [ ] **Step 2: Create `website/api/meta_routes.py`**

```python
"""GET /api/meta/* — metadata endpoints (source registry, etc.)."""
from fastapi import APIRouter, Response

from website.core.source_registry import to_wire_dict

router = APIRouter(prefix="/api/meta")


@router.get("/source-types")
async def source_types(response: Response):
    """Return the source-type registry as JSON.

    Cached for one year (immutable per deploy SHA — clients bust on app update).
    """
    response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    return to_wire_dict()
```

Wire it up in `website/app.py` alongside the existing routers:
```python
from website.api import meta_routes
app.include_router(meta_routes.router)
```

- [ ] **Step 3: Replace `_SOURCE_PREFIX` in `graph_store.py:24-44` with the registry**

```python
from website.core.source_registry import normalize as _normalize_source, prefix as _source_prefix


def _normalize_source_type(source_type: str) -> str:
    return _normalize_source(source_type).value


# Back-compat shim — some callers still import _SOURCE_PREFIX directly.
_SOURCE_PREFIX = {st.value: meta.prefix for st, meta in __import__(
    "website.core.source_registry", fromlist=["SOURCE_REGISTRY"]
).SOURCE_REGISTRY.items()}
```

- [ ] **Step 4: Update `app.js` to fetch the registry at boot**

Replace `app.js:106-132` (the `COLORS` / `COLORS_INT` / `SOURCE_LABEL` constants):

```javascript
let COLORS = {};
let COLORS_INT = {};
let SOURCE_LABEL = {};

async function _loadSourceRegistry() {
  try {
    const r = await fetch('/api/meta/source-types', { cache: 'force-cache' });
    if (!r.ok) throw new Error('source-types fetch failed');
    const data = await r.json();
    for (const [key, meta] of Object.entries(data)) {
      COLORS[key] = meta.color_hex;
      COLORS_INT[key] = meta.color_int;
      SOURCE_LABEL[key] = meta.label;
    }
  } catch (e) {
    console.warn('source registry pickup failed; using sensible defaults', e);
    // Defensive defaults so the graph still renders.
    COLORS = { web: '#94A3B8' };
    COLORS_INT = { web: 0x94A3B8 };
    SOURCE_LABEL = { web: 'Web' };
  }
}

// Block initial graph load on the registry being ready (boot fences the fetch).
const _registryReady = _loadSourceRegistry();
_registryReady.then(() => loadGraphData());
```

And REMOVE the existing `loadGraphData()` call at the bottom of init (the registry-gated call replaces it).

- [ ] **Step 5: Add missing CSS variables**

In `style.css:26-31`:
```css
--node-youtube: #E05565;
--node-reddit: #E09040;
--node-github: #56C8D8;
--node-substack: #60A5FA;
--node-newsletter: #60A5FA;  /* D2 */
--node-medium: #4ADE80;
--node-twitter: #1DA1F2;      /* D1 */
--node-web: #94A3B8;
```

- [ ] **Step 6: Commit**

```bash
git add website/core/source_registry.py website/api/meta_routes.py website/app.py website/core/graph_store.py website/features/knowledge_graph/js/app.js website/features/knowledge_graph/css/style.css
git commit -m "feat: single source-type registry served via /api/meta (D1,D2,D3)"
```

---

### Task 4.2: D4 — bump canonical_id[:8] → [:16] with collision detection

**Files:**
- Modify: `website/api/routes.py:498-502` (already updated in Task 2.4b; verify the `:16` slice is in place + add collision detection)

- [ ] **Step 1: Verify Task 2.4b's `[:16]` slice is committed**

```bash
grep "canonical_id\[:16\]" website/api/routes.py
```
Expected: one match.

- [ ] **Step 2: Add collision detection to the assembler**

In `_v2_assemble_graph`'s overlay loop (the part that builds `canonical_to_overlay`), wrap the `if not canonical_id or canonical_id in canonical_to_overlay: continue` to detect REAL collisions (same overlay node_id but DIFFERENT canonical id):

```python
node_id = f"{prefix}-{slug}-{canonical_id[:16]}"
existing_canonical = next(
    (c for c, n in canonical_to_overlay.items() if n == node_id), None
)
if existing_canonical and existing_canonical != canonical_id:
    # D4 collision detected — append more entropy to disambiguate.
    node_id = f"{prefix}-{slug}-{canonical_id[:24]}"
    logger.warning(
        "D4 collision: node_id collision in workspace=%s; widening hash. existing=%s new=%s",
        ws_id, existing_canonical, canonical_id,
    )
if canonical_id in canonical_to_overlay:
    continue  # same canonical seen twice → expected
canonical_to_overlay[canonical_id] = node_id
```

- [ ] **Step 3: Commit**

```bash
git add website/api/routes.py
git commit -m "fix: D4 node_id collision detection + hash widening"
```

---

### Task 4.3: Migration 50 + pseudo-tag separation (B7)

**Files:**
- Create: `supabase/website/_v2/50_workspace_zettels_derived_tags.sql`
- Modify: `website/features/rag_pipeline/ingest/kg_population.py:830-870` (write `derived_tags` separately)
- Modify: `website/api/routes.py` (`_v2_assemble_graph` nodes — emit `tags` (user) + `derived_tags` separately)
- Modify: `website/features/knowledge_graph/js/app.js` (panel + filter only show `tags`, not `derived_tags`)

**OPERATOR APPROVAL REQUIRED — additive column + one-shot backfill SQL.**

- [ ] **Step 1: Migration 50 up**

`50_workspace_zettels_derived_tags.sql`:

```sql
-- Migration 50 (Phase 4 / B7): separate derived/system tags from user tags.
--
-- Today: `derive_pseudo_tags` appends source_domain:youtube.com,
-- modality:video, speaker:<slug> to `augmented_tags`, which is then
-- persisted as `user_tags`. These appear in the user's side-panel tag
-- chips and tag-filter dropdown as if they were typed by the user.
--
-- Fix: add a sibling column `derived_tags text[]`. The scorer still unions
-- both sets internally, but the wire/UI separation is clean.

ALTER TABLE content.workspace_zettels
  ADD COLUMN IF NOT EXISTS derived_tags text[] NOT NULL DEFAULT '{}'::text[];

-- One-shot backfill: identify rows where user_tags contains derived-style
-- prefixes (`source_domain:`, `modality:`, `speaker:`) and migrate them.
UPDATE content.workspace_zettels
   SET derived_tags = ARRAY(
         SELECT t FROM unnest(user_tags) AS t
          WHERE t LIKE 'source_domain:%' OR t LIKE 'modality:%' OR t LIKE 'speaker:%'
       ),
       user_tags = ARRAY(
         SELECT t FROM unnest(user_tags) AS t
          WHERE t NOT LIKE 'source_domain:%' AND t NOT LIKE 'modality:%' AND t NOT LIKE 'speaker:%'
       )
 WHERE EXISTS (
       SELECT 1 FROM unnest(user_tags) AS t
        WHERE t LIKE 'source_domain:%' OR t LIKE 'modality:%' OR t LIKE 'speaker:%'
     );

COMMENT ON COLUMN content.workspace_zettels.derived_tags IS
  'System-derived tags from pseudo_tags.derive_pseudo_tags. Never shown in user UI.';
```

Down migration: drop the column (NB: lossy — operator must explicitly confirm).

- [ ] **Step 2: Update `kg_population.py` to write derived separately**

In `populate_kg_for_zettel`, replace the augmented-tags handling:

```python
user_tags = [str(t).strip() for t in (tags or []) if str(t).strip()]
derived_tags = derive_pseudo_tags(url=url, source_type=source_type, metadata=metadata)
# B7: persist them separately (operator-approved migration 50 added the column).
# Internal scorer still gets the union.
augmented_for_scoring = list(dict.fromkeys([*user_tags, *derived_tags]))
# … pass augmented_for_scoring to _node_metadata.tags and _score_and_upsert_edges_for_node
# AND update content_repository.upsert_workspace_zettel to accept derived_tags=derived_tags.
```

- [ ] **Step 3: Update `content_repository.upsert_workspace_zettel` to accept `derived_tags`**

Add the kwarg + include in the upsert payload.

- [ ] **Step 4: Update `_v2_assemble_graph` node emission to surface both fields**

In the node dict in `routes.py`:
```python
nodes.append({
    "id": node_id,
    "name": …,
    "group": source_type,
    "summary": row.get("ai_summary") or "",
    "tags": list(row.get("user_tags") or []),
    "derived_tags": list(row.get("derived_tags") or []),  # B7
    "url": …,
    "date": …,
    "node_date": …,
})
```

- [ ] **Step 5: Frontend hides `derived_tags` in panel + filter**

In `app.js:1085-1087` (side panel tags):
```javascript
tags.innerHTML = (Array.isArray(node.tags) ? node.tags : []).map(
  t => '<span class="kg-tag">' + escapeHtml(t) + '</span>'
).join('');
```
Already only renders `node.tags` — no change needed once backend stops mixing.

In `renderTagsSection` (`app.js:1339-1380`), only `n.tags` is iterated. Verify it's not iterating `n.derived_tags`.

- [ ] **Step 6: Commit migration + code in one commit (operator-approved bundle)**

```bash
git add supabase/website/_v2/50_workspace_zettels_derived_tags.sql website/features/rag_pipeline/ingest/kg_population.py website/core/supabase_v2/repositories/content_repository.py website/api/routes.py
git commit -m "fix: separate derived_tags from user_tags on wire (B7)"
```

---

### Task 4.4: tldextract for canonical Public Suffix List (X7)

**Files:**
- Modify: `website/features/kg_features/pseudo_tags.py:40-101` (replace hand-rolled `_MULTI_PART_SUFFIXES` + `_registrable_domain`)
- Modify: `ops/requirements.txt` (add `tldextract`)

- [ ] **Step 1: Add dependency**

```
tldextract>=5.1
```
Then `pip install -r ops/requirements.txt`.

- [ ] **Step 2: Replace `_registrable_domain` with tldextract**

In `pseudo_tags.py`:

```python
import tldextract

# X7: use the canonical Public Suffix List instead of the hand-rolled
# _MULTI_PART_SUFFIXES dict. Snapshot bundled in the tldextract wheel; no
# runtime network fetch (suffix_list_urls=()).
_extract = tldextract.TLDExtract(suffix_list_urls=(), cache_dir="/tmp/tldextract")


def _registrable_domain(url: str | None) -> str | None:
    if not url:
        return None
    try:
        result = _extract(url)
    except Exception:
        return None
    return result.registered_domain or None  # 'co.uk' style handled correctly
```

Delete the `_MULTI_PART_SUFFIXES` dict entirely.

- [ ] **Step 3: Pre-warm in FastAPI lifespan to share the parsed tree across workers via `--preload` COW**

In `website/app.py`'s lifespan:
```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    # X7: pre-warm tldextract so the PSL parse is shared across gunicorn workers.
    from website.features.kg_features.pseudo_tags import _extract
    _extract("https://example.com")  # forces snapshot materialization
    yield
```

- [ ] **Step 4: Smoke**

```python
# In a shell:
from website.features.kg_features.pseudo_tags import _registrable_domain
assert _registrable_domain("https://example.gov.in/foo") == "example.gov.in"
assert _registrable_domain("https://example.co.id/bar") == "example.co.id"
```

- [ ] **Step 5: Commit**

```bash
git add ops/requirements.txt website/features/kg_features/pseudo_tags.py website/app.py
git commit -m "fix: PSL via tldextract for correct eTLD+1 (X7)"
```

---

### Task 4.5: Cold-node backfill uses live-ingest embed shape (X8)

**Files:**
- Modify: `website/features/rag_pipeline/ingest/kg_population.py:980-1090` (`populate_kg_edges_for_existing_node`)

- [ ] **Step 1: Fetch the zettel's summary in the backfill path**

In the cold-node branch where `node_embedding` is empty:

```python
if not node_embedding:
    # X8: live ingest embeds `title + "\n\n" + summary`. Cold backfill
    # MUST use the same shape so cosines are comparable across the corpus.
    # Fetch the canonical zettel's ai_summary first.
    canonical_zettel_id = meta.get("canonical_zettel_id")
    summary_text = ""
    if canonical_zettel_id:
        try:
            resp = (
                supabase_client.schema("content")
                .table("canonical_zettels")
                .select("title,ai_summary")
                .eq("id", str(canonical_zettel_id))
                .limit(1)
                .execute()
            )
            rows = list(resp.data or [])
            if rows:
                canonical_name = rows[0].get("title") or str(row.get("canonical_name") or "")
                summary_text = str(rows[0].get("ai_summary") or "")
        except Exception as exc:
            logger.warning("X8 backfill summary lookup failed: %s", exc)
            canonical_name = str(row.get("canonical_name") or "")
    else:
        canonical_name = str(row.get("canonical_name") or "")

    embed_input = f"{canonical_name}\n\n{summary_text}".strip()[:2000]
    if not embed_input or embed_input == canonical_name:
        # No summary available — degrade gracefully; mark in metadata.
        meta["embedding_input_shape"] = "title_only"
        logger.info("X8 cold-backfill node id=%s missing summary; skipped (shape mismatch)", kg_node_id)
        metrics["skipped"] = True
        return metrics
    meta["embedding_input_shape"] = "title_summary"
    embed_result = generate_embedding_typed(embed_input)
    if not embed_result.ok:
        metrics["skipped"] = True
        return metrics
    node_embedding = embed_result.vectors[0]
```

- [ ] **Step 2: Commit**

```bash
git add website/features/rag_pipeline/ingest/kg_population.py
git commit -m "fix: cold-backfill embed shape matches live ingest (X8)"
```

---

### Task 4.6: `/api/metrics` Prometheus endpoint (O1, O2, O4)

**Files:**
- Modify: `website/app.py` (mount the ASGI metrics app)
- Modify: `website/core/kg_metrics.py` (add the remaining counters: edge_drops, populate outcomes, durations — already stubbed in Task 3.5)
- Modify: `website/api/routes.py:660-667` (increment `kg_edge_drops_total{reason=…}`)
- Modify: `website/features/rag_pipeline/ingest/kg_population.py` (increment `kg_populate_runs_total{outcome=…}`)

- [ ] **Step 1: Mount the Prometheus ASGI app**

In `website/app.py`:

```python
from prometheus_client import make_asgi_app

# /api/metrics — multiprocess-aware exposition (per prometheus_client docs).
# For our 2-worker --preload setup, set PROMETHEUS_MULTIPROC_DIR in the env
# (or via the Dockerfile) and let each worker write its own metrics shards.
metrics_app = make_asgi_app()
app.mount("/api/metrics", metrics_app)
```

Add to `ops/Dockerfile` (after the WORKDIR line):

```dockerfile
ENV PROMETHEUS_MULTIPROC_DIR=/tmp/prom_multiproc
RUN mkdir -p /tmp/prom_multiproc
```

And the gunicorn `child_exit` hook in `ops/gunicorn.conf.py` (create if absent):

```python
def child_exit(server, worker):
    from prometheus_client import multiprocess
    multiprocess.mark_process_dead(worker.pid)
```

- [ ] **Step 2: Increment edge-drop counter in `_v2_assemble_graph`**

```python
from website.core.kg_metrics import kg_edge_drops_total
# Each silent-drop site:
kg_edge_drops_total.labels(reason="unresolved_endpoint").inc()
# And:
kg_edge_drops_total.labels(reason="cross_workspace").inc()  # added in Y1 task
```

- [ ] **Step 3: Increment populate counter in kg_population.py**

After each terminal state write:

```python
from website.core.kg_metrics import kg_populate_runs_total, kg_populate_duration_seconds
# At top of populate_kg_for_zettel:
_t0 = time.perf_counter()
# At each terminal return path:
kg_populate_runs_total.labels(outcome="succeeded").inc()  # or succeeded_empty / failed_retryable / failed_permanent / skipped_idempotent
kg_populate_duration_seconds.observe(time.perf_counter() - _t0)
```

- [ ] **Step 4: Verify scrape works**

```bash
curl -s http://localhost:10000/api/metrics | grep kg_
```
Expected: `kg_cosine_pair_total`, `kg_edge_drops_total`, `kg_populate_runs_total`, etc.

- [ ] **Step 5: Commit**

```bash
git add website/app.py website/core/kg_metrics.py website/api/routes.py website/features/rag_pipeline/ingest/kg_population.py ops/Dockerfile ops/gunicorn.conf.py
git commit -m "feat: /api/metrics Prometheus endpoint (O1,O2,O4)"
```

---

### Task 4.7: Y1 — audit cross-workspace edge drops with 1% sample

**Files:**
- Modify: `website/api/routes.py:621` (`_resolve_overlay_ids` fallback path)

- [ ] **Step 1: Add the audit hook**

When `src_overlays or dst_overlays` is empty AFTER both resolvers tried:

```python
import hashlib
# Inside the edge loop:
if not src_overlays or not dst_overlays:
    edges_dropped_unresolved += 1
    kg_edge_drops_total.labels(reason="unresolved_endpoint").inc()
    # Y1: 1% sampled log so volume stays bounded under burst.
    sample_key = f"{ws_id}:{src_id}:{dst_id}"
    if int(hashlib.sha256(sample_key.encode()).hexdigest(), 16) % 100 == 0:
        logger.warning(
            "Y1 cross-workspace edge drop ws=%s src_kg_node=%d dst_kg_node=%d",
            ws_id, src_id, dst_id,
        )
    continue
```

- [ ] **Step 2: Commit**

```bash
git add website/api/routes.py
git commit -m "fix: Y1 audit cross-workspace drops with 1% sample"
```

---

### Task 4.8: Y2 — scope auth token to current Supabase project

**Files:**
- Modify: `website/features/knowledge_graph/js/app.js:264-285` (`getStoredAuthToken`)

- [ ] **Step 1: Derive expected project ref from `/api/auth/config`**

```javascript
let _expectedProjectRef = null;
async function _loadExpectedProjectRef() {
  try {
    const r = await fetch('/api/auth/config');
    if (!r.ok) return;
    const { supabase_url } = await r.json();
    if (!supabase_url) return;
    // 'https://<ref>.supabase.co' → ref
    const m = supabase_url.match(/^https?:\/\/([^.]+)\.supabase\.co/);
    if (m) _expectedProjectRef = m[1];
  } catch (e) { /* ignore */ }
}

function getStoredAuthToken() {
  try {
    const direct = localStorage.getItem('zk-auth-token');
    if (direct) {
      const parsed = JSON.parse(direct);
      if (parsed && parsed.access_token) return parsed.access_token;
    }
  } catch (e) { /* ignore */ }
  // Y2: scope sb-*-auth-token discovery to the CURRENT project ref only.
  if (_expectedProjectRef) {
    try {
      const key = `sb-${_expectedProjectRef}-auth-token`;
      const raw = localStorage.getItem(key);
      if (raw) {
        const data = JSON.parse(raw);
        if (data && data.access_token) return data.access_token;
      }
    } catch (e) { /* ignore */ }
  }
  return null;
}
```

- [ ] **Step 2: Call `_loadExpectedProjectRef()` in boot sequence (before `loadGraphData`)**

```javascript
Promise.all([_loadExpectedProjectRef(), _registryReady]).then(() => loadGraphData());
```

- [ ] **Step 3: Commit**

```bash
git add website/features/knowledge_graph/js/app.js
git commit -m "fix: Y2 auth token scoped to current Supabase project ref"
```

---

### Task 4.9: Y3 — surface `meta.profile_source` in `/api/me`

**Files:**
- Modify: `website/api/routes.py:278-323` (`me` endpoint)
- Modify: `website/features/knowledge_graph/js/app.js` (banner if jwt_fallback)

- [ ] **Step 1: Add `profile_source` to the response**

In each return branch of `me()`:

```python
return {
    "id": user["sub"],
    "email": profile.get("email") or user.get("email", "") or "",
    "name": profile.get("display_name") or metadata.get("full_name", "") or "",
    "avatar_url": profile.get("avatar_url") or avatar_url or "",
    "profile_source": "v2",  # Y3
}

# fallback branch:
return {
    …,
    "profile_source": "jwt_fallback",
}
```

- [ ] **Step 2: Frontend reads and (optionally) banners**

In `app.js`'s `/api/me` resolver:
```javascript
.then(profile => {
  if (profile && profile.profile_source === 'jwt_fallback') {
    console.warn('Y3: profile loaded from JWT fallback; v2 lookup failed');
  }
  …
})
```

- [ ] **Step 3: Commit**

```bash
git add website/api/routes.py website/features/knowledge_graph/js/app.js
git commit -m "fix: Y3 /api/me surfaces profile_source (v2|jwt_fallback)"
```

---

### Task 4.10: Y4 — repos via FastAPI lifespan + app.state (not module globals)

**Files:**
- Modify: `website/app.py` (lifespan init)
- Modify: `website/core/persist.py:44-46,156-191,229-247` (read from app.state instead of module globals)

- [ ] **Step 1: Initialize repos in lifespan**

In `website/app.py`:

```python
from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    from website.core.supabase_v2.repositories.core_repository import CoreRepository
    from website.core.supabase_v2.repositories.content_repository import ContentRepository
    from website.core.db_version import use_supabase_v2
    if use_supabase_v2():
        app.state.v2_core_repo = CoreRepository()
        app.state.v2_content_repo = ContentRepository()
    # X7 pre-warm (Task 4.4)
    from website.features.kg_features.pseudo_tags import _extract
    _extract("https://example.com")
    yield
```

- [ ] **Step 2: Update `persist.py` to read from `app.state` via `Request` (where available) or a singleton helper**

For functions called outside a request context (drain_pending_enrichment_tasks, etc.), keep a module-level lazy initializer but make it thread-safe with `threading.Lock`. For request-scoped paths, accept `request: Request` and read `request.app.state.v2_*_repo`.

Detailed refactor scope: each call site of `_v2_core_repo` / `_v2_content_repo` becomes either:

```python
# From a route handler:
core_repo = request.app.state.v2_core_repo
# From outside (e.g., kg-populate fire-and-forget):
core_repo = _get_core_repo()  # lazy + locked initializer below
```

- [ ] **Step 3: Replace module globals with lazy thread-safe getters**

```python
import threading

_v2_core_lock = threading.Lock()
_v2_content_lock = threading.Lock()
_v2_core_singleton: V2CoreRepository | None = None
_v2_content_singleton: V2ContentRepository | None = None


def _get_core_repo() -> V2CoreRepository:
    global _v2_core_singleton
    if _v2_core_singleton is None:
        with _v2_core_lock:
            if _v2_core_singleton is None:
                _v2_core_singleton = V2CoreRepository()
    return _v2_core_singleton


def _get_content_repo() -> V2ContentRepository:
    global _v2_content_singleton
    if _v2_content_singleton is None:
        with _v2_content_lock:
            if _v2_content_singleton is None:
                _v2_content_singleton = V2ContentRepository()
    return _v2_content_singleton
```

(Note: under `--preload`, each gunicorn worker has its own globals after fork; the lazy init ensures each worker gets its own connection-pool state without sharing mutable connections across workers.)

- [ ] **Step 4: Commit**

```bash
git add website/app.py website/core/persist.py
git commit -m "fix: Y4 thread-safe lazy repo init replaces module globals"
```

---

### Task 4.11: X3 — savedView state machine clarity

**Files:**
- Modify: `website/features/knowledge_graph/js/app.js:333-359` (boot view restoration)

- [ ] **Step 1: Rewrite the boot sequence**

```javascript
// X3: explicit two-stage state machine.
//   pendingView   = what localStorage says the user wanted last time
//   currentView   = what we actually render right now
// We always START rendering 'global' so the UI is never broken for anon
// users. If localStorage says 'my' AND /api/me confirms login, we
// transition to 'my' AFTER the auth resolver fires.

const STORAGE_KEY_VIEW = 'kg.view';
const pendingView = localStorage.getItem(STORAGE_KEY_VIEW);
let currentView = 'global';  // always safe default
setViewBtns(currentView);

authToken = getStoredAuthToken();
if (authToken) {
  fetch('/api/me', { headers: { 'Authorization': 'Bearer ' + authToken } })
    .then(r => r.ok ? r.json() : Promise.reject('not logged in'))
    .then(profile => {
      isLoggedIn = true;
      setPersonalEnabled(true);
      loadKastens();
      loadUserOwnedIds();
      refreshOpenPanelAddBtn();
      if (pendingView === 'my') {
        currentView = 'my';
        setViewBtns('my');
        loadGraphData();
      }
    })
    .catch(() => { isLoggedIn = false; authToken = null; setPersonalEnabled(false); });
} else {
  setPersonalEnabled(false);
}
```

- [ ] **Step 2: Commit**

```bash
git add website/features/knowledge_graph/js/app.js
git commit -m "fix: X3 explicit savedView state machine"
```

---

### Task 4.12: X4 — base64url tag IDs

**Files:**
- Modify: `website/features/knowledge_graph/js/app.js:1358` (renderTagsSection id construction)

- [ ] **Step 1: Replace the lossy regex sanitization**

```javascript
function _tagFilterId(tag) {
  // X4: round-trippable base64url avoids "foo bar" vs "foo_bar" collision.
  const b64 = btoa(unescape(encodeURIComponent(tag)));
  return 'flt-tag-' + b64.replace(/\+/g, '-').replace(/\//g, '_').replace(/=/g, '');
}
// Usage:
const id = _tagFilterId(tag);
```

- [ ] **Step 2: Commit**

```bash
git add website/features/knowledge_graph/js/app.js
git commit -m "fix: X4 base64url tag filter IDs (no collisions)"
```

---

### Task 4.13: X5 — NFKC + lowercase tag normalization (write + read)

**Files:**
- Modify: `website/core/persist.py` (where tags are persisted to `content.workspace_zettels.user_tags`)
- Modify: `website/features/knowledge_graph/js/app.js:1144` (filter comparison)
- Migration: extend Migration 50 (Task 4.3) with one-shot backfill normalization

- [ ] **Step 1: Add server-side normalization helper**

In `website/core/text_polish.py` or new `website/core/tag_normalize.py`:

```python
import unicodedata

def normalize_tag(tag: str) -> str:
    """X5: NFKC + lowercase + strip. Idempotent."""
    return unicodedata.normalize("NFKC", str(tag)).strip().lower()
```

Apply at every persist site (rewrite `user_tags` before passing to `upsert_workspace_zettel`).

- [ ] **Step 2: Client-side defense-in-depth**

In `app.js`, normalize tags as they enter `activeTags`:
```javascript
function _normalizeTag(t) {
  return (t || '').normalize('NFKC').trim().toLowerCase();
}
// Whenever inserting:
activeTags.add(_normalizeTag(tag));
// Whenever looking up:
const hit = tags.some(t => activeTags.has(_normalizeTag(t)));
```

- [ ] **Step 3: Backfill SQL (append to Migration 50)**

```sql
UPDATE content.workspace_zettels
   SET user_tags = ARRAY(
         SELECT DISTINCT trim(lower(unaccent(t)))
           FROM unnest(user_tags) AS t
          WHERE t IS NOT NULL AND length(trim(t)) > 0
       )
 WHERE user_tags <> ARRAY(
         SELECT DISTINCT trim(lower(unaccent(t)))
           FROM unnest(user_tags) AS t
          WHERE t IS NOT NULL AND length(trim(t)) > 0
       );
```

(Note: requires `unaccent` extension — guard with `CREATE EXTENSION IF NOT EXISTS unaccent;`.)

- [ ] **Step 4: Commit**

```bash
git add website/core/tag_normalize.py website/core/persist.py website/features/knowledge_graph/js/app.js supabase/website/_v2/50_workspace_zettels_derived_tags.sql
git commit -m "fix: X5 NFKC + lowercase tag normalization (write + read)"
```

---

### Task 4.14: Retire `graph_store` mutation pattern (X9, X10)

**Files:**
- Modify: `website/core/graph_store.py` — `add_node` becomes a thin wrapper that reads the in-memory snapshot but no longer writes to disk; `_save` deleted; `_load` adds mtime check

- [ ] **Step 1: Delete `_save` + the synchronous lock-hold around it**

In `graph_store.py`:
- Delete the `_save()` function (`graph_store.py:55-72`).
- In `add_node` (`:162-170`), remove the `_save()` call. The in-memory `_graph` still mutates so reads within the same process return the new node.
- In `delete_node` (`:185-203`), similarly remove `_save()`.

Add a header comment explaining the retirement:

```python
"""In-memory graph store backed by graph.json.

Phase 4 X9+X10 retirement: Supabase v2 is the canonical source of truth for
user data. graph.json is a READ-ONLY mirror seed-loaded at process boot.
In-memory `add_node`/`delete_node` mutations are kept ONLY for the file-store
public/anonymous surface (e.g. demo enrichments) — they DO NOT persist to
disk and DO NOT survive a worker restart. To update the curated demo graph,
edit graph.json by hand and run ops/scripts/backfill_graph_json_strength.py;
the next deploy will pick up the changes.
"""
```

- [ ] **Step 2: Add mtime-check to `_load` for in-place hot-reloads (optional polish)**

```python
_graph_mtime: float | None = None

def _load() -> dict:
    global _graph, _graph_mtime
    current_mtime = GRAPH_JSON.stat().st_mtime
    if _graph is None or _graph_mtime is None or current_mtime > _graph_mtime:
        with _lock:
            current_mtime = GRAPH_JSON.stat().st_mtime
            if _graph is None or _graph_mtime is None or current_mtime > _graph_mtime:
                _graph = json.loads(GRAPH_JSON.read_text(encoding="utf-8"))
                _graph_mtime = current_mtime
    return _graph
```

- [ ] **Step 3: Commit**

```bash
git add website/core/graph_store.py
git commit -m "refactor: retire graph_store disk mutation; mtime hot-reload (X9,X10)"
```

---

### Task 4.15: Wire-payload trimming + summary normalization (S1, S3, S4, S5)

**Files:**
- Modify: `website/api/routes.py:_trim_graph_response + _enrich_graph_with_analytics`

- [ ] **Step 1: Don't compute betweenness/closeness/harmonic in the default path**

Already handled by Phase 3 Task 3.8 (harmonic) + Phase 1 (`compute_graph_metrics` returns zeros). For S4+S5: drop them from the wire trim list entirely AND drop the columns from the response (no consumer reads them):

In `routes.py:46-60`:
```python
_TRIMMED_NODE_FIELDS: frozenset[str] = frozenset({
    "embedding",
    "embedding_model_version",
    "embedding_dim",
    "model_version",
    "score_breakdown",
    "betweenness",
    "closeness",
    "harmonic_centrality",  # S5: never read by frontend
    "created_at_microseconds",
})
```

- [ ] **Step 2: Normalize node summary at the boundary (S3)**

In `_trim_graph_response`'s node loop, parse the JSON envelope ONCE:

```python
def _normalize_summary_for_wire(raw: str | dict) -> dict:
    """S3: parse the JSON-string envelope once at the API boundary."""
    if isinstance(raw, dict):
        return raw
    if not isinstance(raw, str) or not raw.strip():
        return {"brief": "", "detailed": [], "closing": ""}
    text = raw.strip()
    if not text.startswith("{"):
        return {"brief": text[:800], "detailed": [], "closing": ""}
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return {
                "brief": parsed.get("brief_summary", parsed.get("brief", "")),
                "detailed": parsed.get("detailed_summary", []),
                "closing": parsed.get("closing_remarks", ""),
            }
    except (TypeError, ValueError):
        pass
    return {"brief": text[:800], "detailed": [], "closing": ""}
```

And use it in the node trim loop:
```python
if isinstance(nd.get("summary"), (str, dict)):
    nd["summary"] = _normalize_summary_for_wire(nd["summary"])
```

- [ ] **Step 3: Update frontend `extractBriefFromSummary` to short-circuit when already parsed**

In `app.js:158`, at the top of the function:
```javascript
function extractBriefFromSummary(raw) {
  // S3: server now sends parsed envelope. Fast path.
  if (raw && typeof raw === 'object' && typeof raw.brief === 'string') {
    return raw.brief;
  }
  // Legacy path kept for back-compat with file-store data.
  …
}
```

- [ ] **Step 4: Strip pre-computed metrics on read (S1)**

In `graph_store._load`, after the JSON parse:
```python
for node in _graph.get("nodes", []):
    for stale in ("pagerank", "community", "betweenness", "closeness", "harmonic_centrality"):
        node.pop(stale, None)
```

- [ ] **Step 5: Commit**

```bash
git add website/api/routes.py website/features/knowledge_graph/js/app.js website/core/graph_store.py
git commit -m "fix: wire trim + summary parsed at boundary (S1,S3,S4,S5)"
```

---

### Task 4.16: Delete dead code (X1, X2, M4)

**Files:**
- Modify: `website/api/module_runners/view_graph.py:148-156` (delete `_serialize_global_payload`)
- Modify: `website/features/kg_features/scoring.py:179-198` (delete `percentile_rank`)
- Modify: `website/api/routes.py:769-776` (remove the `/api/graph/rebuild-links` ghost comment)
- Modify: `website/features/kg_features/analytics.py:269-306` (delete `compute_expensive_metrics` — no live callers per X1)

- [ ] **Step 1: Verify no callers**

```bash
grep -rn "_serialize_global_payload\|percentile_rank\|compute_expensive_metrics" website/ tests/
```
Expected: only the definitions and tests-of-the-definitions. If a real caller exists, STOP and update plan.

- [ ] **Step 2: Delete and update any related tests**

Remove the unit tests in `tests/unit/website/kg_features/test_kg_features_unreachable.py` allow-list for `percentile_rank`.

- [ ] **Step 3: Commit**

```bash
git add website/api/module_runners/view_graph.py website/features/kg_features/scoring.py website/api/routes.py website/features/kg_features/analytics.py tests/unit/test_kg_features_unreachable.py
git commit -m "chore: delete dead code (X1,X2,M4)"
```

---

### Task 4.17: Phase 4 acceptance gate

- [ ] **Step 1: Full test suite**

```bash
pytest tests/ -v -m "not live"
```
Expected: all PASS.

- [ ] **Step 2: Manual /api/metrics scrape**

```bash
curl -s http://localhost:10000/api/metrics | grep "^kg_"
```
Expected: ≥6 metric series visible (cosine pair, cosine negative, edge drops, populate runs, populate duration).

- [ ] **Step 3: Manual source-registry smoke**

```bash
curl -s http://localhost:10000/api/meta/source-types | python -m json.tool
```
Expected: 8 source-type entries; `twitter` present with `#1DA1F2`.

- [ ] **Step 4: Verify pseudo-tags hidden in UI**

Open the worktree's `/knowledge-graph` while logged in. Open any node's side panel. Confirm `source_domain:…` / `modality:…` / `speaker:…` tags do NOT appear.

- [ ] **Step 5: Phase 4 closeout commit**

```bash
git commit --allow-empty -m "phase 4 complete: KG hardening (registry+observability+security)"
```

---

## Cross-cutting acceptance criteria

These must all hold after Phase 4 completes:

1. **Anonymous /api/graph returns ≥1 edge per dataset link.** `curl /api/graph` with no auth on a fresh container shows ≥50 links from file-store.
2. **Logged-in /api/graph returns deterministic edge counts.** 10 consecutive calls with identical query params return identical `links.length`.
3. **Cross-page edges visible.** For a user with >5,000 zettels, `/api/graph?view=my&limit=5000&offset=0` returns ALL edges whose endpoints touch any zettel in the workspace, not just those in the first overlay page.
4. **No silent failure modes.** All four `kg-populate` terminal states (`succeeded`, `succeeded_empty`, `failed_retryable`, `failed_permanent`) appear in `pipeline_runs` over a synthetic test batch; retryable rows have `retry_eligible_after`.
5. **Slider never flashes to empty.** Manual smoke: dragging strength slider from 0.30 to 0.85 keeps previous edges visible until the new payload lands.
6. **Empty-state UX explains itself.** Setting slider to 0.99 displays "Nodes loaded, but no connections match this strength."
7. **Source-type registry single source.** Editing `SOURCE_REGISTRY` in `source_registry.py` propagates to `/api/meta/source-types` AND frontend without touching CSS or app.js.
8. **Pseudo-tags isolated.** `source_domain:…` no longer in user-facing tag list.
9. **Auth tokens isolated.** A stale `sb-otherproject-auth-token` in localStorage is ignored.
10. **Observability live.** `/api/metrics` shows counters increasing during Add Zettel.
11. **Performance ceiling lifted.** 5k-node test fixture renders at ≥30 fps in Chrome DevTools Performance recording.
12. **No protected-knob revert.** No changes to `GUNICORN_WORKERS`, `--preload`, `GUNICORN_TIMEOUT`, BGE int8 cascade, rerank semaphore, SSE heartbeat, Caddy upstream timeouts, schema-drift gate, or `kg_users` allowlist gate per CLAUDE.md "Critical Infra Decision Guardrails".

---

## Rollout sequence (operator-driven)

| Step | Action | Reversibility |
|---|---|---|
| 1 | Apply Phase 1 commits via PR; merge after CI green | Trivial revert |
| 2 | Request operator approval for Migrations 47 + 48 (Phase 2) | Down migrations prepared; `DROP INDEX IF EXISTS` and `DROP COLUMN IF EXISTS` |
| 3 | Apply Migrations 47 + 48 to prod via `gh workflow run`; verify on droplet | Reversible |
| 4 | Merge Phase 2 PR | Code-only revert |
| 5 | Request operator approval for Migration 49 (Phase 3) | Enum values cannot be dropped; backfill is reversible by status revert |
| 6 | Apply Migration 49; merge Phase 3 code PR (excluding 3-α) | Code revertible |
| 7 | Operator approval for Phase 3-α (D-KG-1 weight rebalance) — present 3-source convergence + GraphRAG/LightRAG precedent | If approved, apply; if rejected, plan stops here for scoring |
| 8 | Request operator approval for Migration 50 + B7 backfill (Phase 4) | Lossy column drop on down — confirm explicitly |
| 9 | Apply Migration 50; merge Phase 4 PR | Reversible except for backfill |
| 10 | Bump CSS/JS asset cache-buster across all `?v=` tokens | Trivial |
| 11 | Smoke test against prod URL `https://zettelkasten.in/knowledge-graph` (anonymous, then with auth, then Personal view) | Manual |

---

## Risk register

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Phase 1 LD-1/LD-2 surfaces a wave of edges that overwhelms 1 vCPU on first paint at scale | Low (small user base) | Medium | Phase 3-4 cache + memo land before traffic grows |
| Migration 49 enum extension cannot be reverted (Postgres limitation) | Certain | Low — extending is non-breaking | Down migration documents the limitation |
| Migration 50 backfill mis-classifies a user-typed tag that happens to start with `source_domain:` | Very low | Low (visual only) | Backfill SQL filters on the colon + canonical prefix list |
| `tldextract` PSL snapshot ages between container rebuilds | Low | Low (some new TLDs misclassified) | Rebuild image on schedule; tldextract degrades gracefully on unknown TLDs |
| Phase 3-α weight rebalance over-creates edges in tag-rich corpora | Medium (if approved) | Medium (visual noise) | Embedding fast-path is the conservative knob; can roll back via single commit |
| `make_asgi_app()` + `multiprocess` on the 2-worker setup leaks metrics file descriptors over time | Low | Low | `child_exit` hook calls `mark_process_dead`; on reload, dir is cleared |
| Frontend MiniSearch CDN unavailable | Very low | Low | Code already degrades to per-keystroke search; getBrief memo is still active |
| Operator skips Migration 49 but applies Phase 3 code | Low | High — state machine writes succeeded_empty to an unknown enum value | Phase 3 code defensively wraps in try/except and falls back to current 'succeeded' semantics if the new enum values are missing |

---

## Post-implementation backlog (not in this plan)

These were identified during cross-verification but are intentionally deferred:

- **B10 stage 2** — drop legacy `weight` + `global_strength` columns from `kg_edges` after Phase B coverage proves 100% (requires operator-approved destructive migration; document in iter-13 plan).
- **MiniSearch full adoption** — currently optional in Task 3.11; promote to default after 30-day stability window.
- **Leiden community detection** — swap from Louvain (`g.community_multilevel`) to Leiden (`g.community_leiden`) for connected-community guarantees per the Traag 2019 paper. Requires igraph 0.10+ verification on droplet.
- **Incremental PageRank** — defer until corpus passes 50k nodes (Memgraph MAGE / NetworKit dynamic). Today's content-hash memo + 1-vCPU is sufficient.
- **B5 fast-path tuning** — if Phase 3-α is approved, monitor edge-count growth weekly for 30 days before further weight changes.
- **Frontend tier UI tweak (LD-5)** — current implementation uses fixed-cutoff frontend tiering; experiment with per-graph quantile bands in a follow-up iter if visual feedback warrants.

---

