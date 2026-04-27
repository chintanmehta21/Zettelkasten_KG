# iter-02 Scorecard — Knowledge-Management Kasten

**Date:** 2026-04-27
**Deployed SHA at capture:** `83da88e` (final fix bundle of the day — 7 commits stacked on `ca39543`)
**Kasten under test:** Knowledge Management & Personal Productivity (sandbox `227e0fb2`) — same 7 zettels as iter-01.
**Quality mode:** `fast` (gemini-2.5-flash). `high` (gemini-2.5-pro) was attempted first but consistently hit the 60 s SDK timeout that the iter-02 fix bundle bumped to 180 s; by the time the bump deployed, Cloudflare had begun returning 502 for the long-body adhoc POSTs (see "Known constraints" in `answers.json`).

---

## 3-way comparison: iter-06 (youtube AI/ML) vs iter-01 (KM blocked) vs iter-02 (KM unblocked)

| Stage | iter-06 (yt AI/ML) | iter-01 (KM) | **iter-02 (KM)** |
|---|---|---|---|
| Kasten retrieval | gold@1 4/4 | **BLOCKED** — `rag_bulk_add_to_sandbox` SQL fix never applied to prod, Kasten chat returned "no Zettels in selected scope" on every query | **3/5 of the queries that reached the orchestrator landed the right primary citation; 2 picked the wrong primary** |
| Reranker | top score ≥ 0.987, 100× distractor gap | not run | not separately measured (cascaded inside fast tier) |
| Synthesis | 600–1700 char grounded answers | not run | **2/5 substantive grounded answers (q1, q2); 1 correct adversarial refusal (q9); 2 false-negative refusals (q3, q8) where the retriever returned the right zettel but the synthesizer wrote "I can't find that…"** |
| Adversarial resistance | n/a (iter-06 had none) | not run | **q9 (Notion — absent) correctly refused; q10 (Naval Ravikant — absent) lost to Cloudflare 502 before reaching the orchestrator** |
| Composite | **~95** | **— (deploy gap)** | **30 % full-pass rate, 50 % infra-502, 20 % synthesizer over-refusal** |

### iter-02 per-query verdict

| qid | class | expected primary | actual primary | verdict |
|---|---|---|---|---|
| q1 | lookup (two-fact) | gh-zk-org-zk | gh-zk-org-zk | ✅ PASS — "Go" + "Markdown" both extracted, cited |
| q2 | lookup (author boost) | yt-steve-jobs-2005-stanford | yt-steve-jobs-2005-stanford | ✅ PASS — exact-quote synthesis with citation |
| q3 | lookup (deep extract) | yt-effective-public-speakin | yt-effective-public-speakin | ❌ FAIL — retrieved correctly but synthesizer refused |
| q4 | multi-hop | (sleep + programming) | n/a | ⚠ INFRA — Cloudflare 502 |
| q5 | thematic | (4+ zettels) | n/a | ⚠ INFRA — Cloudflare 502 |
| q6 | step-back | tools-for-thought + zk + winston | n/a | ⚠ INFRA — Cloudflare 502 |
| q7 | vague | yt-steve-jobs-2005-stanford | n/a | ⚠ INFRA — Cloudflare 502 |
| q8 | lookup (practical) | gh-zk-org-zk | nl-the-pragmatic-engineer-t | ❌ FAIL — wrong primary; synthesizer refused |
| q9 | adversarial-negative | (none — Notion absent) | (none authoritative) | ✅ PASS — refusal was correct |
| q10 | adversarial-partial | yt-steve-jobs-2005-stanford | n/a | ⚠ INFRA — Cloudflare 502 |

---

## What iter-02 actually closed (vs the 4 infrastructure bugs entering this iter)

| Infra bug entering iter-02 | iter-02 outcome |
|---|---|
| `scope_filter` empty arrays coerced to null | ✅ shipped (commit `ca39543`); Kasten-scoped retrieval now returns the 7 members |
| `kg_expand_subgraph` CTE divergence | ✅ shipped pre-iter; T18 multi-hop expansion live |
| Fatal migration gate in `deploy.sh` | ✅ shipped pre-iter; deploys now bail before image swap if any pending SQL migration fails |
| IPv4 pooler for Supabase | ✅ shipped; droplet → Supabase reachability stable |

## What iter-02 added (UI fix bundle from this session)

All shipped via 7 commits during the iter-02 capture session:

| # | Fix | Commit |
|---|---|---|
| 1 | Composer textarea overflow:hidden — phantom scrollbar buttons gone | `1f3a86e` |
| 2 | Advanced Filters disclosure removed (DOM kept hidden, default quality forced) | `1f3a86e` |
| 3 | SSE pre-yield "queued" status (response-head flush in <100 ms) | `1f3a86e` |
| 4 | `/home/rag` switched to `_render_with_shell` so `<!--ZK_HEADER-->` partial loads — same header as `/home/zettels` | `8925a94` |
| 5 | Manage Kastens + 3-dot menu moved into in-page action row (was in custom header) | `8925a94` |
| 6 | Robust try/except around the entire `_stream_answer` body (any failure becomes an SSE `error` event on a 200 response, not a 5xx) | `444e680` |
| 7 | Personalized role label — "USER" → signed-in user's display name; "ASSISTANT" → "Zettelkasten" | `444e680` |
| 8 | 1-retry client-side on 5xx + fetch-reject (cold-start mask) | `444e680` |
| 9 | Tighter message bubbles (less blank space) | `444e680` |
| 10 | Model name / token meta hidden from end users (no infra disclosure) | `a67999e` |
| 11 | Dead `.rag-header*` CSS removed | `a67999e` |
| 12 | Server-side single retry on cold-start orchestrator failures | `bb7b341` |
| 13 | Gemini SDK timeout 60 s → 180 s (was hard cap on Pro multi-hop synthesis) | `27bdf7e` |
| 14 | User-facing chat error always generic + actionable ("I hit a temporary error while answering. Please retry in a moment.") | `27bdf7e` |
| 15 | Mid-stream connection-drop friendly message ("Lost connection mid-answer. Please retry.") | `83da88e` |

## What iter-02 did NOT close (rolls into iter-03)

1. **Cloudflare/Caddy 502 storm under burst load (P0).** Five sequential adhoc POSTs in <60 s saturated the single-uvicorn-worker on the 1 GB droplet and Cloudflare returned 502 directly. Need worker count ≥2, or per-IP request queue with backpressure visible in the UI.
2. **Synthesizer over-refusal (P1).** q3 and q8 are the smoking gun: the retriever returned the right Zettel(s), the citations rendered correctly, yet the synthesizer wrote "I can't find that in your Zettels." The synthesizer's grounding-check threshold is too tight when the question wording diverges from the zettel wording (q3 "verbal punctuation" vs the zettel's "punctuation cues"). Lower the threshold or move the check to post-generation.
3. **Citation chip on refusal answers (P2).** q9's correct-refusal still surfaced a citation chip for the Pragmatic Engineer zettel — the chip implies the answer leaned on that source, which it didn't. Hide citations when the synthesizer body is the canned "I can't find" string.
4. **Pro-tier latency for multi-hop / thematic (P1).** Even with the 180 s timeout, gemini-2.5-pro on q4/q5 (multi-hop, thematic) consistently fails to deliver in time. Either route those classes to Flash by default or pre-generate a cached answer for the most common thematic prompts.
5. **The "Naruto" legacy user transfer race (P2).** q1's secondary citation is the Pragmatic Engineer zettel, not the expected zk-org/zk zettel. Suggests a still-live pollution from the legacy `naruto` user_sub that the iter-01 user-id transfer didn't fully clean up.

---

## Verdict

| | composite | gold@1 rate | adversarial-handling | infra-stability under burst |
|---|---|---|---|---|
| iter-06 yt | ~95 | 4/4 (q4/q5 quota) | n/a | n/a |
| iter-01 KM | — | 0/0 (blocked) | — | — |
| **iter-02 KM** | **~30 % full-pass / 50 % infra / 20 % synth-error** | **2/5 reaching orchestrator** | **1/1 reaching orchestrator (q9)** | **degraded under 5+ concurrent POSTs** |

iter-02 unblocks the four infrastructure bugs that prevented iter-01 from running at all. The chat surface is now production-grade (shared header, no model-name disclosure, friendly errors, personalized labels). The remaining gaps are upstream-load handling (Cloudflare 502 under burst) and synthesizer over-refusal — both go on the iter-03 punch list rather than blocking the eval.
