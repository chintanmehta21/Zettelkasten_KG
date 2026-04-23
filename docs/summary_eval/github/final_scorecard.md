# GitHub - Final Scorecard

## Per-loop Progression

| Loop | URLs | Composite (mean) | Faithfulness (min) | Status | Notes |
|---|---|---:|---:|---|---|
| 1 (baseline) | #1 | 100.00 | 1.000 | baseline | Auto-eval over-scored; manual estimate was 73.7. |
| 2 (tune) | #1 | 83.00 | 0.900 | degraded vs baseline | Canonical label recovery and tag normalization stabilized. |
| 3 (tune) | #1 | 89.10 | 0.830 | improved | Brief formatting improved but stayed below target. |
| 4 (probe) | #1,#2 | 87.21 | 0.844 | probe below gate | Cross-URL behavior was acceptable but not production-grade. |
| 5 (joint) | #1,#2,#3 | 62.97 | 0.000 | failed | `psf/requests` schema collapse drove the mean down. |
| 6 (held-out) | #1-#5 sweep | 74.37 | 0.880 | failed | Held-out mean missed the >=88 gate. |
| 7 (prod-parity) | skipped | n/a | n/a | skipped | Held-out failed, so extension path took priority. |
| 8 (extension) | #1,#2,#3 | 62.33 | 0.000 | failed | Section-schema softening did not remove repo-shape fragility. |
| 9 (extension final) | #1-#5 sweep | 68.26 | 0.270 | failed | `tiangolo/typer` collapsed; final held-out remained unsafe. |

## Acceptance

- [ ] Training URL #1 composite >= 92 in >= 3 of last 5 tuning iters.
- [ ] Training URL #1 ragas_faithfulness >= 0.95.
- [ ] URLs #1, #2, #3 each >= 88 at loop 5.
- [ ] Held-out mean >= 88 and held-out min faithfulness >= 0.95.
- [ ] Prod-parity delta <= 5.
- [ ] No hallucination or faithfulness collapse in final held-out path.
- [x] `owner/repo` label recovery improved materially.
- [x] GitHub repo redirects now resolve in both ingest and API-signal clients.

**Overall: DEGRADED.**

## Root Cause

GitHub structured extraction remains repo-shape fragile. Framework-style repositories like `fastapi/fastapi` score well, but valid repositories with different documentation and public-surface shapes still collapse or degrade sharply. The final held-out sweep had a 68.26 mean and a 0.270 min faithfulness, so the source is not safe to mark production-grade.

## Signal Utilization

- `owner/repo` labels are recovered from GitHub URLs when metadata is incomplete.
- Redirected repositories such as `tiangolo/typer` are followed instead of failing at HTTP 301.
- Tags now normalize reserved GitHub concepts and strip unsupported hash formatting.
- Brief repair improved generic format issues but did not solve heterogeneous repo structures.
- Architecture and public-surface signals are still brittle when README shape differs from framework/API repos.

## Cross-model Disagreement

- Agreement loops: 6 of 8 completed loops.
- Major disagreement loops: iter-01 and iter-05.
- Required consecutive-major disagreement analysis: not triggered because the major disagreements were non-consecutive.

## Billing Spend

- Recorded billing calls across iter-01 through iter-09: 0 in loop artifacts.
- Current eval CLI now forces billing-only, one-retry, fail-fast behavior for the four scoring-loop sources to avoid wasting time on exhausted free keys.
- Live/default key-pool behavior remains normal unless those eval-only environment overrides are set.

## Known Risks

- Prod-parity/Zoro verification was skipped because held-out validation failed and extension mode was required first.
- The edit ledger still reflects noisy dirty-worktree context from concurrent plan work; the scorecard and per-iter artifacts are the authoritative Plan 8 outcome.
- The next robust fix should be repo-shape-aware GitHub extraction, not another wording-only prompt tune.

## Lessons For Plan 10

- GitHub needs archetype-specific extraction paths for framework/API repos, CLI repos, libraries with thin READMEs, and documentation-heavy repos.
- Schema fallback must degrade into a faithful minimal summary, not a near-zero structured payload.
- Held-out sweeps need at least five repositories because one or two URLs cannot expose repo-shape collapse.
- Eval-loop key policy should remain fail-fast during scoring runs so quota issues do not consume loop time.
