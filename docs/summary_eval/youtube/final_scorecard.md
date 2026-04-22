# YouTube - Final Scorecard

## Per-loop progression
| Loop | URLs | Composite (mean) | Faithfulness (min) | Status |
|---|---|---:|---:|---|
| 1 (baseline) | #1 | 60.00 | 0.80 | baseline established |
| 2 (tune) | #1 | 86.35 | 1.00 | strong recovery after hallucination cleanup |
| 3 (tune) | #1 | 91.10 | 0.95 | training score near target |
| 4 (probe) | #1, #2 | 83.38 | n/a | cross-URL regression surfaced |
| 5 (joint) | #1, #2, #3 | 80.48 | n/a | convergence gate missed |
| 6 (held-out) | #4, #5 | 44.55 | 0.90 | held-out collapse triggered extensions |
| 7 (prod-parity) | #4, #5 | 88.05 | n/a | local/prod-parity path looked healthier but did not resolve brief defect |
| 8 (ext) | #1, #2, #3 | 60.12 | n/a | broad cross-URL regression after brief repair attempt |
| 9 (ext final) | #4, #5 | 59.23 | 0.70 | held-out still degraded |

## Acceptance (spec §10.1)
- [ ] Training URL composite >= 92 in >= 3 of last 5 tuning iters
- [ ] Training URL ragas_faithfulness >= 0.95
- [ ] URLs #1, #2, #3 each >= 88 at loop 5
- [ ] Held-out mean >= 88 AND min ragas_faithfulness >= 0.95 (loop 6)
- [ ] Prod-parity delta <= 5 (loop 7)
- [ ] No iteration triggered hallucination cap (60) in loops 5-7
- [ ] Rubric label regex match in 100% of loop-6 held-out runs

**Overall: DEGRADED**

## Lessons
- The largest gain came from removing invented-chapter style failures and schema-key leakage; those fixes improved the training URL fast but did not generalize.
- The persistent bottleneck was the brief layer, not the detailed layer. Detailed summaries stayed mostly useful while briefs repeatedly failed thesis completeness, speaker salience, segment coverage, and finished takeaways.
- Held-out reliability is the real blocker. Iter-06 collapsed to 44.55 mean and iter-09 still ended at 59.23 with min faithfulness 0.70, so training-loop gains cannot be trusted as production quality.
- The iteration infrastructure also needed repair. Held-out Phase B state detection and edit-ledger attribution were both broken until fixed in this run, which made earlier loop analysis less reproducible than it should have been.
- Placeholder speaker entities such as `Source`, `The Source`, or entity names standing in for people are a robust regression signal and should be treated as a hard failure in the brief builder.

## Known risks / follow-ups
- The current brief-repair path still truncates thesis and takeaway sentences under unfamiliar transcript shapes.
- Cross-URL behavior regressed badly in iter-08, which indicates the repair logic is over-template-driven rather than content-grounded.
- Held-out faithfulness dropped to 0.70 in iter-09, so YouTube cannot be called production-grade.
- Prod-parity KG/RAG verification was not captured in `iter-07`; that path still needs an explicit verification artifact if YouTube work resumes.

## Zoro prod-parity verification (loop 7)
- Supabase KG writes: not verified in this run
- RAG retrieval: not verified in this run
- Reference: no `docs/summary_eval/youtube/iter-07/zoro_kg_verification.md` artifact was produced
