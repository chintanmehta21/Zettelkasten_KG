# iter-01 Live Eval — Manual Review (BLOCKED on prod-DB-migration gap)

**Date:** 2026-04-27
**SHA live in prod:** 6f93b80 (deploy 24963971073 succeeded 2026-04-26 18:42 UTC)
**Kasten under test:** `Knowledge Management & Personal Productivity` (sandbox 227e0fb2-ff81-4d08-8702-76d9235564f4) — 7 zettels, Strong quality

## Summary

Strict-Chrome-MCP eval on /home/rag attempted. **Blocked at the first query** with `"This sandbox has no Zettels in the selected scope."` despite the Kasten card showing "7 zettels".

Confirmed via re-create (made a fresh `KM-iter-01-eval` Kasten via the now-deployed UI flow): same 7-zettel selection → same empty-scope chat error. **Proves the `rag_bulk_add_to_sandbox` silent-no-op bug (the very bug T2 was committed to fix, SHA 317eca1) is STILL ACTIVE in production.**

Root cause: the deploy pipeline updates the application image but **does not auto-apply Supabase migrations**. The `supabase/website/kg_public/migrations/2026-04-26_fix_rag_bulk_add_to_sandbox.sql` is in the repo but never ran against prod Supabase. Same likely true for the other four iter-01 migrations: `2026-04-26_kg_usage_edges.sql`, `2026-04-26_expand_subgraph.sql`, `2026-04-26_metadata_enriched_at.sql`, `2026-04-26_delete_test_node.sql`.

## Why the eval can't proceed in pure-Chrome mode

1. **KAS-11 blocker** — Kasten-scoped chat returns no zettels (T2 SQL migration not applied).
2. **Workaround attempt** ("All zettels" scope) returned `network error` in chat after ~10 s — likely a separate prod-side issue surfacing because Strong-quality on 31-node global retrieval hits a model/latency edge that the Kasten path masks.
3. The chat session API rejects programmatic `Authorization: Bearer <token>` (returns "Invalid token") AND the cookie session is being interpreted as anonymous for the `/api/rag/sandboxes/*/members` endpoint (returns "Not authenticated"). So we cannot direct-INSERT or even DELETE the duplicate Kasten via JS console.

## What CAN be reported

- All 8 UX-1..UX-8 fixes ARE live in prod. T3 `data-action="create-kasten"` attribute confirmed present in deployed HTML. Add-Zettel + Create-Kasten flows worked without JS workarounds. UX-2 progress feedback ("Summarizing…" with spinner) was visible during zettel ingest yesterday.
- 25 NEW prod UX bugs catalogued on `/home/rag` itself (KAS-1..KAS-25 below). Per user directive: page is dramatically over-built; left "Context" sidebar should be killed entirely; only need an "Add zettels to current Kasten" button.

## KAS-1..KAS-25 — `/home/rag` UX backlog (full table)

| # | Element | Issue | Fix |
|---|---|---|---|
| KAS-1 | Left "Context" sidebar (Kasten/Quality/Tag/Source filters) | Dead weight once Kasten URL implies scope; elongates page; forces scroll | DELETE the entire panel |
| KAS-2 | Sandbox dropdown ignores `?sandbox=` URL param (defaults to "All zettels") | URL→state desync | Auto-init from URLSearchParams (or kill per KAS-1) |
| KAS-3 | Quality default = "Fast" | Cheaper tier hides better answers from new users | Default to Kasten's `default_quality` |
| KAS-4 | Tag-scope text input + Source-scope chip array | Power-user UI exposed to all; vertical noise | Remove or hide behind ⋯ Advanced |
| KAS-5 | 9+ generic suggestion-prompt cards in left column | Cards are static (RLHF prompt for a PKM Kasten is jarring) | Dynamic per-Kasten chips above composer, or remove |
| KAS-6 | Composer is the LAST element (after sidebar+cards) | Inverts chat-app convention | Sticky-bottom composer |
| KAS-7 | "Streaming answers appear live..." copy persistent | Wastes screen on every visit | Show only first session |
| KAS-8 | "Ask the graph something precise." headline | Vague guidance | Inject Kasten name OR remove |
| KAS-9 | "Ask the graph" submit button label | Verbose, redundant with placeholder | "Send" or icon-only ↑ |
| KAS-10 | "network error" rendered in same style as placeholder hint | Easy to miss as an error | Red color + icon + reason + retry CTA |
| KAS-11 | **BLOCKER**: Kasten chat returns "no Zettels in selected scope" | T2 SQL migration not applied to prod | Apply migration; auto-apply migrations in deploy.sh |
| KAS-12 | No way to delete a Kasten from chat page | Discovery friction | 3-dot menu in header |
| KAS-13 | No "Add zettels to this Kasten" button | The ONE thing the page actually needs per user | Single button → opens existing chooser modal scoped to add-to-existing |
| KAS-14 | Two duplicate "Knowledge Management" Kastens exist now | Eval re-attempt; duplicate `KM-iter-01-eval` sandbox e20777d4 | Cannot delete via API auth; user must click delete in UI (which doesn't exist per KAS-12 — chicken-and-egg) |
| KAS-15 | "Skip to main content" link visually visible (not just on focus) | A11y mis-implementation | `clip:rect(0 0 0 0)` until `:focus` |
| KAS-16 | "Manage kastens" looks like plain text not button | Affordance ambiguity | Style as secondary button or add icon |
| KAS-17 | Page title "User RAG - Zettelkasten" | "User RAG" is internal jargon | "Chat — \<Kasten name\> — Zettelkasten" |
| KAS-18 | Sandbox dropdown allows mid-conversation switch with no confirm | Loses session-id silently | Confirm dialog (or remove dropdown per KAS-1) |
| KAS-19 | URL has duplicate params `?sandbox=X&sandbox_id=X&session_id=Y` | Two code paths writing same state | Canonicalize to `?sandbox=X&session=Y` |
| KAS-20 | "QUESTION" label above textarea | Redundant with placeholder | Remove |
| KAS-21 | Composer `rows=4` | Wasted vertical (~5cm tall empty input) | `rows=1` with auto-grow |
| KAS-22 | No keyboard shortcut hint | Power users don't know Enter vs Cmd+Enter | "Press Cmd+Enter to send" hint |
| KAS-23 | No critic-verdict badge on answers | `chat_messages.critic_verdict` is captured but never surfaced | ✅ Grounded / ⚠ Partial / ❌ Unsupported badge |
| KAS-24 | No model/tier/token/latency disclosure | Trust + cost transparency missing | "Answered by gemini-2.5-flash · 1,432 tokens · 4.2s" |
| KAS-25 | No copy / regenerate / 👍👎 affordances | Standard chat UX absent | Three icon buttons under each answer |

## Action items for iter-02 plan rewrite

1. **D-1 (deploy gap, P0)** — Add migration auto-apply step to `ops/deploy/deploy.sh` (between image pull and container start): walk `supabase/website/kg_public/migrations/*.sql` newer than the last applied marker and run via `psql $SUPABASE_DB_URL -f`. Track applied migrations in a `_migrations_applied` table.
2. **KAS-1..KAS-25** — Q-A page redesign (frontend). Probably 1 medium PR: kill sidebar + cards, sticky composer, model/critic/copy affordances, sandbox-from-URL.
3. **Cleanup** — Delete duplicate KM-iter-01-eval sandbox once a UI delete button exists (currently blocked by KAS-12 chicken-and-egg — needs admin path or KAS-12 fix first).
4. **Re-run iter-01 eval** — After D-1 lands and the SQL migrations execute, the 10-query eval can run end-to-end and the comparison table below can be filled with real numbers (currently the iter-01 column is "blocked" rows).
