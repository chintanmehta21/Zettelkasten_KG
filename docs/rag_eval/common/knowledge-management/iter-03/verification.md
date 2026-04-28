# Iter-03 Browser Verification Runbook

End-to-end verification via Claude in Chrome MCP against the deployed production site.
Runs against the existing Naruto-owned **Knowledge Management & Personal Productivity** Kasten (sandbox `227e0fb2-ff81-4d08-8702-76d9235564f4`). Does NOT create a new Kasten.

## Prerequisites

- iter-03 deployed to production (`zettelkasten.in`); `git rev-parse HEAD` recorded in `verification_results.json:deployed_sha`.
- Authenticated browser session as Naruto.
- Claude in Chrome MCP active (`mcp__Claude_in_Chrome__*` tools available).
- Run `python ops/scripts/verify_iter_03_in_browser.py --emit-template` to materialize the empty results template.

## 10-step walkthrough

| # | Check | Tool calls | Pass criteria | Evidence |
|---|---|---|---|---|
| 1 | Kasten chooser renders | `navigate https://zettelkasten.in/rag` → `screenshot 01_chooser.png` | Chooser lists `Knowledge Management & Personal Productivity` with member count badge | `screenshots/01_chooser.png` |
| 2 | Composer placeholder uses Kasten name | Click `Knowledge Management` row → `screenshot 02_chat_composer.png` → `read_page` text near `#composer-input` | Placeholder reads `Ask Knowledge Management & Personal Productivity something…` (or shorter form using kasten name); palette is teal, no purple/violet/lavender, no amber/gold | `screenshots/02_chat_composer.png` |
| 3 | All 13 iter-03 queries answered without over-refusal | For each `qid` in `queries.json`: `fill #composer-input` + click send + `wait_for assistant complete` + `screenshot 03_q_<qid>.png`; record answer text and primary citation in `verification_results.json` | 13/13 produce a substantive answer or correctly refuse on the adversarial-negative `q9`/`q10`. ZERO false-negative refusals on q3/q8/av-1/av-2/av-3 (action-verb regression). End-to-end gold@1 ≥ 0.65 against `baseline.json` | `screenshots/03_q_*.png`, `verification_results.json`, `answers.json` |
| 4 | Strong mode triggers critic loop | Toggle `#qualitySelect` to `high`, re-issue `q4` (multi-hop), inspect `verification_results.json:queries[q4].critic_verdict` | `critic_verdict` is one of `accepted` / `revised` / `accepted_after_revision` (i.e. critic ran). `model_chain_used` includes `gemini-2.5-pro`. p95 latency < 60s due to heartbeat keep-alive | `verification_results.json` |
| 5 | Add-zettels modal Select-all | From a Kasten detail page, open Add Zettels modal → click Select-all header → `screenshot 05_select_all.png` | All checkboxes flip checked simultaneously; counter shows `N of N selected`; teal accent on header row | `screenshots/05_select_all.png` |
| 6 | Heartbeat retry fires after idle | In a query that triggers a slow Strong path, observe DevTools Network tab; wait until `:heartbeat` SSE comments stream every ~10s; if connection drops, client auto-retries silently. `screenshot 06_heartbeat_retry.png` after the retry banner appears | Network panel shows `: heartbeat` lines every ~10s; if synthetic disconnect, "Reconnecting…" teal pill appears, answer resumes | `screenshots/06_heartbeat_retry.png` |
| 7 | Queue UX surfaces 503 Retry-After | Open DevTools console; paste 12-fetch loop submitting concurrent `/sessions/{id}/messages?stream=1` POSTs. `screenshot 07_queue_503.png` when "Server is busy. Please retry in a few seconds." pill appears | Pill renders in teal, includes a `Retry now` link, vanishes on successful retry. No raw 5xx surfaces. `Retry-After` header parsed correctly | `screenshots/07_queue_503.png` |
| 8 | `?debug=1` hidden in prod | `navigate https://zettelkasten.in/rag?debug=1` → `read_page` for `.rag-debug-panel` selector → `screenshot 08_debug_hidden.png` | No debug panel rendered. No model name / token count / score / query_class visible anywhere on the page | `screenshots/08_debug_hidden.png` |
| 9 | Schema-drift gate blocks intentional drift | On staging Supabase, manually `ALTER TABLE kg_users ADD COLUMN drift_canary text;` then run `python ops/scripts/apply_migrations.py --verify-schema`. Capture `deploy.log` excerpt | apply_migrations exits non-zero with a clear "schema-drift detected" message naming `kg_users.drift_canary`; rollback `DROP COLUMN drift_canary` after | `deploy.log` excerpt |
| 10 | SSE survives blue→green cutover | Start a long Strong-mode query; while answer streams, trigger a re-deploy of the same image (`/opt/zettelkasten/deploy/deploy.sh $(git rev-parse HEAD)`); answer must complete via the still-active color even though Caddy upstream flips mid-stream. `screenshot 10_sse_cutover.png` after answer completes | Answer finishes without "Lost connection mid-answer" pill. Drain budget (45s) was sufficient. New requests post-flip route to new color | `screenshots/10_sse_cutover.png` |

## Pass / fail recording

After each step, edit `verification_results.json`:
```json
{ "id": <step>, "status": "pass" | "fail" | "blocked", "notes": "..." }
```

Final acceptance:
- All 10 steps `pass`; 13-query end-to-end gold@1 ≥ 0.65 (vs iter-02 baseline 0.30 full / 0.60 orchestrator-only).
- Synthesizer grounding ≥ 0.85.
- Zero infra failures (Cloudflare 502s) across the 13-query burst replay.
- All UI checks: zero purple/violet/lavender; teal on Kasten surfaces; amber reserved for `/knowledge-graph` only.

## Artifacts to commit on completion

- `docs/rag_eval/common/knowledge-management/iter-03/verification_results.json` (filled in)
- `docs/rag_eval/common/knowledge-management/iter-03/answers.json` (from a parallel `python ops/scripts/rag_eval_loop.py --source knowledge-management --iter 3 --auto` run)
- `docs/rag_eval/common/knowledge-management/iter-03/screenshots/*.png`
- `docs/rag_eval/common/knowledge-management/iter-03/scores.md` (final 3-way comparison vs iter-01 / iter-02)
