---
name: KG Intelligence — Remaining Checks
description: Features that need re-verification once Gemini quota resets or on paid tier; discovered during 2026-04-06 deployment session
type: project
---

## Remaining checks after Gemini free-tier quota resets

**Why:** All 25 P1-P7 fixes are deployed and code-verified. Three features couldn't be fully end-to-end tested on Render because Gemini's free-tier quota (20 req/day for gemini-2.5-flash) was exhausted during the testing session.

**How to apply:** Re-run these checks after quota resets (~24hrs) or after upgrading to a paid Gemini plan. If any fail, the diagnostic logging added in commit `050f1a7` will show exactly what's happening in Render logs.

### 1. NL Graph Query (M4) — re-verify on Render
- Worked ONCE on Render ("List all my notes" returned naruto's real nodes with correct SQL)
- Subsequent calls hit Gemini 429 rate limit
- **Test:** `POST /api/graph/query` with `Cookie: render_user_id=naruto` and questions like "What YouTube videos are about AI?", "How many nodes do I have?"
- **Check:** SQL is generated, EXPLAIN validates it, execute returns results, answer is formatted
- Code is correct (verified locally) — just needs quota headroom

### 2. Entity Extraction (M1) — re-verify on Render
- Fire-and-forget `asyncio.create_task` in `/api/summarize` (routes.py L524-546)
- Never completed on Render during testing — entities field stays `null` on all naruto nodes
- Likely causes: (a) Gemini rate limit during extraction, (b) Render free-tier worker recycling kills the background task before it completes
- **Test:** Add a new URL via `/api/summarize`, wait 30s, then check `SELECT metadata->'entities' FROM kg_nodes WHERE id = '<new_node_id>'`
- **Check:** Should return a JSON array of extracted entities with `id`, `type`, `description` fields
- If still failing on paid Gemini, check Render logs for `Entity extraction failed:` warnings
- Multi-turn gleaning (commit `84476e5`) and few-shot example also untested in production

### 3. Semantic auto-linking edge cases
- Basic flow WORKS (verified: GPT-2 node → 2 semantic links on Render, cosine 0.905 and 0.796)
- **Untested:** What happens when a node's embedding generation fails mid-request (cooldown active)? The `if emb:` guard should skip auto-linking gracefully. Verify no partial state.
- **Untested:** Duplicate link prevention — if the same URL is submitted twice (dedup prevents re-insert, but what if dedup fails?). The `add_semantic_link` method catches unique-constraint violations via try/except.

### 4. Backfill embeddings for pre-existing nodes
- 34 nodes belonging to user `8842e563-...` (the main authenticated user) have NO embeddings
- 2 naruto nodes (`web-martin-fowler`, `web-the-state-of-vc-within-s`) have no embeddings
- No backfill script exists (`scripts/backfill_embeddings.py` from the plan was never created)
- These nodes won't appear in semantic search or get semantic links until embeddings are generated
- **Action needed:** Write and run a backfill script that reads each node's summary, generates embedding, and UPDATEs the row

### 5. SQL migration not formally tracked
- The migration was deployed via `npx supabase db query --linked` in chunks, not via `supabase db push`
- The `fts` column uses a TRIGGER (not GENERATED ALWAYS AS) because Supabase rejects non-IMMUTABLE expressions in generated columns
- The local SQL file (`001_intelligence.sql`) still has the GENERATED ALWAYS syntax — mismatch with deployed schema
- **Action needed:** Update `001_intelligence.sql` to match deployed trigger-based fts, or document the divergence

### Commits from this session
- `231ce2c` — docs: add KG intelligence verification report
- `84476e5` — fix(kg): wire up intelligence layer end-to-end (P1-P7 fixes)
- `e8eac15` — fix(sql): pgvector operator resolution + find_neighbors forward-ref
- `daeb941` — fix(nl-query): parse explain_kg_query JSON response correctly
- `050f1a7` — fix(embeddings): use title+summary for richer embeddings, add auto-link logging
- `f55a518` — fix(models): parse pgvector string response in KGNode embedding field
