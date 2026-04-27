# iter-03 backlog — derived from iter-02 capture

Ordered by priority. Each item names the artifact / module that needs touching.

## P0 — infra reliability

1. **Burst-tolerant upstream.** 5 sequential `POST /api/rag/adhoc` in <60 s caused Cloudflare 502 (q4–q7, q10). Two paths:
   - Easy: bump uvicorn workers to 2 (`website/main.py` add `workers=2`) and retest.
   - Better: front the streaming endpoints with a per-user FIFO so the second request waits for the first, surfacing a tiny "Queued (#2 ahead)" hint in the composer instead of a generic 502.

2. **Streaming SSE survival across blue/green cutover.** When `deploy.sh` swaps the Caddy upstream, in-flight SSE connections drop and the user sees the new "Lost connection mid-answer." friendly message. Add a 5 s grace where the retiring container holds open existing connections (`docker stop --time 30` instead of immediate kill).

## P1 — synthesizer correctness

3. **False-negative refusal on questions that diverge from zettel wording (q3, q8).** Retriever did its job (returned the right zettel + chunk); the synthesizer's grounding-check refused. Two follow-ups:
   - Lower the grounding-check threshold OR move the check to post-generation (let the model draft, then verify).
   - For "lookup_recency"-class queries (q8 was practical-pick), bias toward the zettel that is itself an actionable artifact (gh-zk-org-zk) rather than the discursive companion (Pragmatic Engineer).

4. **Pro-tier reliability for multi-hop / thematic.** Even with the 180 s timeout, gemini-2.5-pro on q4 (multi-hop) and q5 (thematic) consistently fails. Route those classes to Flash by default and let a `?quality=high` URL flag override.

5. **Hide citation chips on canned-refusal answers.** q9's correct refusal still surfaced a Pragmatic Engineer chip — implies a source the answer didn't actually use. In `user_rag.js` `consumeSSE` `done` handler, suppress `replaceCitations(...)` when `turn.content` matches the canned "I can't find that in your Zettels." string.

## P1 — eval coverage

6. **Capture per-stage debug data per query.** answers.json should include retriever's top-K candidate scores, reranker's score margins, and the EvidenceCompressor's compression ratio so iter-03 can diagnose at the module level (currently we only have answer + final citations). Add a `?debug=1` URL flag that surfaces this on a hidden devtools panel without leaking it to normal users.

## P2 — UX polish

7. **Composer placeholder shows the Kasten name.** Currently always "Ask a question..." Replace with "Ask <Kasten name> something..." once a Kasten is selected (the `chat-title` already does this).

8. **Suppress "fetched" pings during long pipelines.** When the orchestrator runs >5 s with no token yet, surface a quiet "Working through your zettels…" status rather than a static spinner.

9. **Legacy `naruto` user_sub residual data.** q1's secondary citation is the Pragmatic Engineer zettel — likely a fragment from the legacy user-id transfer. Audit `kg_node` rows still owned by the legacy `naruto` user and migrate or delete.

## P2 — ops

10. **Container log access via gh workflow.** Currently no easy way to read recent application logs without SSH-ing the droplet. Add a `read_recent_logs.yml` workflow (paralleling `diagnose_sandbox.yml`) that tails the last N lines of the running blue/green container and uploads them as a workflow artifact.

11. **MEMORY.md hygiene.** Add a memory pruner pass — the per-project MEMORY.md is stretching past 200 lines; truncation will start losing context.
