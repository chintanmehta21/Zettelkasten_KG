# iter-02 — Manual Review (qualitative notes per query)

Each entry: what the user actually saw, what it should have shown, what the data tells us about which RAG-pipeline stage to fix.

## q1 — lookup, two-fact extraction (PASS)
- **Asked:** Which language is zk-org/zk written in, and what file format does it use?
- **Got:** "The zk-org/zk command-line tool is written in Go [id=gh-zk-org-zk]. It processes and supports Markdown for its notes [id=gh-zk-org-zk]." + 2 citation chips (zk-org/zk + Pragmatic Engineer).
- **Verdict:** Both atomic facts present. The Pragmatic-Engineer citation chip is irrelevant — it's the residual from the legacy `naruto` user transfer (P2 in next_actions).

## q2 — lookup, author boost (PASS)
- **Asked:** What metaphor did Steve Jobs use about death?
- **Got:** Both expected metaphors ("single best invention of Life", "Life's change agent"), the "you are already naked" line, citation to the right zettel.
- **Verdict:** This is the iter-02 model run. The author-boost (T9) clearly works: a generic "Steve Jobs Stanford" hint pulled the right zettel and the synthesizer used the zettel's actual quotes.

## q3 — single-zettel deep extraction (FAIL — synthesizer over-refusal)
- **Asked:** What is "verbal punctuation" in Patrick Winston's MIT lecture?
- **Got:** "I can't find that in your Zettels." with citations to BOTH the Public Speaking zettel AND Pragmatic Engineer.
- **What this proves:** Retriever did its job (right zettel surfaced as citation). Synthesizer's grounding check fired wrongly because the zettel summary uses "punctuation cues / landmarks" rather than the literal phrase "verbal punctuation". The synthesizer should rephrase the user's term against the zettel's wording before deciding the content is missing.

## q4 — multi-hop synthesis (INFRA — Cloudflare 502)
- **Asked:** Which Walker sleep deficit most impairs the debugging zettel's perception-vs-reality reasoning?
- **Got:** 502 in 5.7 s — Cloudflare returned an HTML error page before the orchestrator finished.
- **What this proves:** When 5 sequential POSTs land within ~60 s, the 1 GB droplet's single-uvicorn-worker saturates and the proxy starts returning 502. The pipeline itself was never reached. Roll into iter-03 P0.

## q5 — thematic, ≥4 sources (INFRA — Cloudflare 502, 126 ms)
- Same as q4 — 502 fired in 126 ms, faster than any orchestrator path can fail. Pure proxy-level rejection.

## q6 — step-back reasoning (INFRA — Cloudflare 502)
## q7 — vague rewriter (INFRA — Cloudflare 502)
- Same pattern. Both queries lost to the burst-load 502.

## q8 — practical-pick lookup (FAIL — wrong primary + over-refusal)
- **Asked:** Which item should I open first to start a personal wiki tonight?
- **Got:** "I can't find that in your Zettels." with the Pragmatic Engineer chip.
- **Expected:** The zk-org/zk zettel (it IS a buildable Go CLI for plain-text wikis — most actionable answer).
- **What this proves:** Two failures cascaded. (1) Retriever ranked Pragmatic Engineer above zk-org/zk (probably author-boost on "engineer" + "engineer" appearing in Pragmatic-Engineer title). (2) Synthesizer over-refused even with that wrong context. The lookup-recency class needs a bias toward zettels that ARE artifacts (CLI / web / repo) over zettels that DESCRIBE artifacts.

## q9 — adversarial-negative (PASS — correct refusal)
- **Asked:** Summarize what this Kasten says about Notion's database features.
- **Got:** "I can't find that in your Zettels." + a stray Pragmatic Engineer chip.
- **Verdict:** The refusal is the correct behaviour — Notion is genuinely absent from the corpus. The stray citation chip is wrong (no source was used) and should be hidden when the synthesizer emits a canned-refusal — see iter-03 P1.

## q10 — adversarial-partial (INFRA — Cloudflare 502)
- Lost to the burst-load 502 along with q4/q5/q6/q7. No data on whether the synthesizer would have correctly grounded the Jobs half and refused the Naval half.

---

## Cross-cutting observations

- **The chat surface is production-grade.** Shared header, friendly errors, personalized "Naruto"/"Zettelkasten" labels, no model name leakage, tighter bubbles, no scrollbar artifact, no Advanced Filters clutter — every UI fix the user reported during iter-02 is live and verified via Chrome MCP.
- **The blocker is now upstream-load + synthesizer over-refusal**, not retrieval. This is qualitatively different from iter-01 where retrieval was completely blocked at the SQL layer.
- **Eval rigour caveat:** quality=fast (Flash) was used for the capture because the Pro path was fighting the 60 s SDK timeout that we bumped to 180 s mid-session — by the time the bump deployed, the proxy 502 storm was already underway. iter-03 should redo the capture once the burst-load fix lands, ideally with Pro on the multi-hop / thematic / step-back classes that benefit most from the bigger model.
