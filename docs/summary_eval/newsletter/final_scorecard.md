# Newsletter - Final Scorecard

## Per-loop progression

| Loop | URLs | Composite (mean) | Faithfulness (min) | Status | Edits |
|---|---|---:|---:|---|---|
| 1 (baseline) | #1 | 94.50 | 1.000 | baseline | baseline artifacts |
| 2 (tune) | #1 | 95.40 | 1.000 | +0.90 | brief/type tags |
| 3 (tune) | #1 | 100.00 | 1.000 | +4.60 | caveats/actions |
| 4 (probe) | #1,#2 | 53.15 | 0.000 | gap found | contamination + branded cap |
| 5 (joint) | #1,#2,#3 | 86.27 | 0.700 | not converged | payload contamination guard |
| 6 (held-out) | #1-#5 | 81.54 | 0.800 | extension required | dead heldouts + evaluator parser fixes |
| 7 (prod-parity) | #1-#5 | 95.14 | 0.900 | KG write verified | Supabase compatibility fixes |
| 8 (extension) | #1-#3 | 92.45 | 1.000 | recovered training/cross set | branded labels + numeric guardrails |
| 9 (extension final) | #1-#5 | 88.60 | 0.900 | held-out mean pass, faithfulness gap | no edits after measurement |

## Acceptance

- [x] Training URL #1 composite >= 92 in >= 3 of last 5 tuning iters.
- [x] Training URL #1 faithfulness >= 0.95.
- [ ] URLs #1, #2, #3 each >= 88 at loop 5. Loop 5 mean was 86.27 with URL-level faithfulness as low as 0.700.
- [ ] Held-out mean >= 88 + min faithfulness >= 0.95. Final held-out mean passed at 88.60, but min faithfulness was 0.900.
- [ ] Prod-parity delta <= 5. Prod-parity mean was 95.14 vs final held-out 88.60, delta 6.54.
- [x] No schema fallback or schema-key leakage in final extension loops.
- [x] Anti-pattern `branded_source_missing_publication` resolved for branded labels in final runs.
- [x] Pragmatic Engineer routes through newsletter summarizer, not generic web.

**Overall: DEGRADED with residual min-faithfulness/prod-delta gap.** Newsletter quality is materially improved and KG writes are verified, but strict spec 10.1 is not fully met.

## Plan-4 Signal Utilization

- Site-specific newsletter extractors fired on all 5 final held-out URLs.
- Branded publication identity enforced for Platformer, Organic Synthesis, Pragmatic Engineer, and beehiiv.
- CTA/constraint handling is present for beehiiv MCP, beehiiv Email Boosts, and Pragmatic Engineer.
- Stance classifier outputs in final runs: skeptical/cautionary, neutral, optimistic, mixed.
- C2 hybrid label rule compliant in final held-out run after Pragmatic Engineer routing fix.

## Cross-model Disagreement

- AGREEMENT loops: 9/9.
- MAJOR_DISAGREEMENT loops: 0.
- `disagreement_analysis.md` required: no.

## Billing Spend

- Recorded billing calls in iter-07 and iter-08 input ledgers: 0.
- Eval commands used billing-only key routing plus fail-fast cooldown controls to avoid repeatedly hitting exhausted free keys.

## Zoro Prod-Parity Verification

- KG writes: 5 new newsletter nodes created for Zoro KG user.
- Source-type storage: production schema accepted legacy `substack` source type through compatibility fallback.
- RAG browser check: skipped because `docs/login_details.txt` credentials returned invalid Supabase Auth credentials.
- Reference: `docs/summary_eval/newsletter/iter-07/zoro_kg_verification.md`.

## Lessons

- Eval source lists can contain URLs that route to the wrong summarizer; router coverage needs source-specific regression tests.
- Live Supabase schema can lag code-level models; writers must degrade optional v2 fields without failing user writes.
- Self-check/evaluator support calls must fail open on transient Gemini 504s so user summaries still complete.
- Held-out URLs need >=5 diverse live sources; dead newsletter URLs masked quality until replaced.
- Edit-ledger attribution is essential for making iteration gains reproducible.

## Known Risks / Follow-ups

- Final held-out min faithfulness remains 0.900, below the strict 0.950 target.
- Prod-parity delta is 6.54, above the <=5 gate, though prod-parity scored higher than final local held-out.
- Browser RAG verification still needs valid Zoro/Naruto auth credentials.
- Production Supabase should still receive a proper schema migration for v2 columns and `newsletter` source type; the fallback keeps writes working meanwhile.

## Branded Sources YAML Final State

- Publications added during Plan 9: `beehiiv`, `organic synthesis`, `pragmatic engineer` in commit `1d2510e`.
- Current branded source count: 11.
