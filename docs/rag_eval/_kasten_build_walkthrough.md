# iter-01 Eval-Kasten — Live Chrome MCP Build Walkthrough

**Date:** 2026-04-26
**User:** naruto@zettelkasten.local (uid f2105544-b73d-4946-8329-096d82f070d3)
**Site:** https://www.zettelkasten.in (PROD, pre-T26-deploy — T3/T7/T10/T16 fixes NOT yet deployed)
**Result:** Kasten "Knowledge Management & Personal Productivity" created successfully with 7 zettels (target was 9; 2 dropped, see UX-3 below). `Kastens: 2 → 3`, `Zettels Included: 7 → 14`.

## Step Timings (timestamped, end-to-end)

| # | Step | Duration | Outcome | UX issue ID |
|---|---|---|---|---|
| 1 | Chrome navigate `/home/kastens` (verify Naruto session via JWT) | 923 ms | ✅ logged in, render OK | — |
| 2 | Navigate `/home`, render | ~1 s | ✅ | — |
| 3 | Click "+ Add Zettel" button | — | ❌ no UI response (button highlighted but dropdown stayed `display:none`) | **UX-1 (T3 prod bug live)** |
| 3b | JS workaround: force `add-zettel-dropdown.style.display='block'` | < 1 ms | ✅ URL input now visible (301×35px) | — |
| 4 | Submit zettel #1 (Andy Matuschak — `https://andymatuschak.org/`) via UI flow | ~50 s click→DB-confirmed | ✅ `web-transformative-tools-for` "Transformative Tools for Thought" (web) | UX-2 (no progress indicator after submit; only a P element with empty error class shown) |
| 5 | Re-open dropdown for zettel #2 | — | ❌ Add-button second click still stale; dropdown hidden again on re-render | UX-1 (recurring) |
| 6 | Bypass via direct `POST /api/summarize` for zettel #2 (`https://github.com/zk-org/zk`) | 34.2 s | ✅ `gh-zk-org-zk` "zk-org/zk" (github) | — |
| 7 | Zettel #3 attempt 1 (`youtube.com/watch?v=AN9qbxuIyTA`) | 10.0 s | ❌ HTTP 422 "transcript access restricted" | **UX-4 (YouTube transcript-fail UX is a flat 422; no model-fallback to video-understanding API mentioned in CLAUDE.md "GeminiKeyPool can bypass transcript and send URL directly to video understanding API")** |
| 8 | Zettel #3 attempt 2 (`youtube.com/watch?v=OdrZq4SzdaA` — Tiago Forte BASB) | 10.1 s | ❌ HTTP 422 same error | UX-4 (same) |
| 9 | Zettel #3 attempt 3 (`youtube.com/watch?v=arj7oStGLkU` — Tim Urban) | 44.8 s | ✅ `yt-tim-urban-s-procrastinat` "Tim Urban's Procrastination Model" (youtube) | — |
| 10 | Navigate `/home/kastens` | ~1 s | ✅ | — |
| 11 | Click "+ Create Kasten" button | 12.7 s click→modal-visible | ⚠ slow, but OK | UX-5 (modal open felt laggy; >2 s would be a UX smell, 12.7 s is far over) |
| 12 | Fill name + select scope=Specific + description | < 1 ms (programmatic) | ✅ | — |
| 13 | Pick 9 target zettels (6 warm-start + 3 fresh) | 0 ms | ⚠ 7 of 9 selected; 2 missing | **UX-3 (chooser-stale)** |
| 14 | Submit Kasten create | 15.7 s submit→overlay-closed | ✅ | UX-6 (no inline progress indicator during 15.7 s wait) |
| 15 | Verify result on `/home/kastens` | < 1 s | ✅ "Knowledge Management & Personal Productivity" appears as latest, KASTENS=3, ZETTELS INCLUDED=14 | — |

**Total wall time:** ~5 min 30 s (would have been ~3 min if not for the YouTube transcript-fail retries and the T3 stale-handler workaround steps).

## Production UX Issues Captured (must NOT reach end-user → fold into iter-02)

| ID | Severity | Description | Evidence | Fix path |
|---|---|---|---|---|
| **UX-1** | 🚨 **Blocker** | "+ Add Zettel" button click on `/home` does NOT toggle the URL-input dropdown. Same pattern on Create Kasten — but the latter happens to work on the first cold load only. Confirms iter-06 README #129 is still in prod. | `add-zettel-dropdown` stays `display:none` after click; live HTML has NO `data-action` attributes (T3 commit `3263655` not yet deployed) | **T3 fix is committed, gated on T26 deploy** |
| **UX-2** | High | Add-Zettel UI gives ZERO progress feedback during the 30-50 s summarization. The skeleton-card placeholder appears in `My Zettels` but is easy to miss; a `<p class="home-add-error">` with empty text is rendered. Users will assume the action failed and click again, creating duplicate jobs. | Step 4 — no toast, no spinner inline with the button, no clear "in progress" message | iter-02: add inline button-state ("Summarizing… ⏳") + skeleton-with-label, ALSO gate the Add button to disabled while a job is in flight |
| **UX-3** | High | Create-Kasten "Specific" zettel chooser shows a STALE list — newly added zettels (within the same session, even after a hard nav back to `/home/kastens`) are absent. The chooser only had 24 zettels; user actually has 31. | Step 13 — `tim-urban` zettel added 2 min earlier was missing from chooser; "show 24, but graph has 31" | iter-02: chooser must `fetch /api/graph?view=my` on every modal open, not at page load. Add `Refresh` button as fallback. |
| **UX-4** | High | YouTube ingestion returns flat 422 when transcript access is restricted, **even though** the GeminiKeyPool documentation claims "it can bypass transcript extraction and send the video URL directly to Gemini's video understanding API" (per `CLAUDE.md` § API Key Pool & Model Fallback). The fallback path is not wired for the website's `/api/summarize` route. | Steps 7-8 — two real PKM-topic videos failed with the same generic error; only worked for a third video that happened to have transcripts | iter-02: wire video-understanding fallback into `/api/summarize` (not just the bot path); update error copy to be specific ("Tried transcript + video API; both denied") |
| **UX-5** | Medium | Create-Kasten modal opens **12.7 seconds** after click. Sufficient delay that the user will click the button again. | Step 11 | Investigate root cause (probably blocking JS render on full graph data + chooser-list build). Defer chooser population behind a spinner; show modal shell first |
| **UX-6** | Medium | Create-Kasten submit takes 15.7 s with no progress indicator before the modal closes. | Step 14 | Same as UX-2: inline button-state + disabled state |
| **UX-7** | Low | `web-test-title` "Test Title" still appears as a real zettel in Naruto's `/home` feed, ahead of the AI/ML Foundations content. | Persistent; visible in /api/graph?view=my for several iterations | F-3 cleanup — DELETE FROM kg_nodes WHERE id='web-test-title' (single-user, test artifact) |
| **UX-8** | Low | "My Zettels" badge shows count "22" but `/api/graph?view=my` returns 29-31. Counts diverge. | Header badge static / not refreshed after add | iter-02: invalidate cache & refetch on add success |

## Members of New Kasten (for T28 eval)

| node_id | source | name |
|---|---|---|
| nl-the-pragmatic-engineer-t | newsletter | The Pragmatic Engineer |
| yt-effective-public-speakin | youtube | Effective Public Speaking (P. Winston, MIT) |
| yt-steve-jobs-2005-stanford | youtube | Steve Jobs 2005 Stanford Commencement |
| yt-matt-walker-sleep-depriv | youtube | Matt Walker on Sleep Deprivation |
| yt-programming-workflow-is | youtube | Programming Workflow Is Debugging Cycle |
| web-transformative-tools-for | web | Transformative Tools for Thought (Andy Matuschak) — ★ added in this run |
| gh-zk-org-zk | github | zk-org/zk CLI Zettelkasten — ★ added in this run |

**Source-type breakdown:** youtube=4, newsletter=1, web=1, github=1 → 4 source types ✓ (meets the iter-01 plan "≥3 distinct source types" gate even with the 2-zettel shortfall).

**Dropped from intended set:**
- `nl-the-pragmatic-engineer-the-product-minded-engineer-in-the-a` — does not exist as a separate node in Naruto's graph; the discovery JSON treated a substring of one node as two.
- `yt-tim-urban-s-procrastinat` — added 2 min before Kasten-create but absent from chooser (UX-3).

## Conclusion (end-user perspective)

**Net usability today: poor.** Without the JS-console workaround, an end-user would NOT have been able to add a zettel via `/home` at all (UX-1). For users who happen to start on `/home/kastens` cold, the create flow works once but the chooser staleness (UX-3) means they cannot include zettels they just added. The 15-50 s waits without progress indicators (UX-2, UX-5, UX-6) are the kind of friction that drives users to abandon the action. The YouTube fallback path being silently absent (UX-4) means a non-trivial slice of YouTube URLs fail with a misleading error.

**iter-01 fixes already committed but not yet deployed:** T3 (3263655) addresses UX-1 directly. T26 deploy is the gating step.

**iter-02 must address:** UX-2, UX-3, UX-4, UX-5, UX-6, UX-7, UX-8 — none of these are in the current iter-01 plan; all are net-new prod bugs surfaced by this walkthrough.
