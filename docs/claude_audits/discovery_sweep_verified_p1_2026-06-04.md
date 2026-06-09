# Discovery-Sweep — Verified P1 Issues + Actual Examples (2026-06-04)

**Method:** 7 adversarial verification subagents (one per source-cluster + cross-cutting), each instructed to *disprove* its claim and confirm only against our real data/code/live sources, returning verbatim examples. Problems only — no fixes.

**What the sweep changed vs the consolidated inventory:**
- **Web → NO P1** (confirmed cleanest: faithfulness 1.0 on 18/19, zero hallucination caps; WB-1 narrows to a P2 reference-page undercoverage, 1/19).
- **Newsletter → NO P1** (n=2; NL-1 demoted to ≈P3 cosmetic — and the one iter-002 faithfulness flag was itself a *false positive*).
- **F2-1 broadened:** wrong-entity speaker attribution hits **single-speaker** videos too, not just multi-speaker.
- **RD-1 narrowed:** the *detailed* body **does** disclose the coverage gap (14/15 carry a moderation note); only the **brief headline** asserts consensus unhedged (13/15). The stronger reddit P1 is F2-3.
- **CS-1/CS-2 came back stronger:** the faithfulness reference (`source_text.md`) is itself **summary-derived** (`len == body_md_len` for all 81) — so the eval is circular for ~77% of items, and the judge literally rated a fabricated GitHub API as "neutral — source mentions this."

---

## Verified P1 — per source

### YouTube — 2 P1
| Issue | Verified verdict | Actual example (verbatim) |
|---|---|---|
| **YT-1** templated lead-in + attribution **doubling** + generic "The speaker" (deterministic POST bug, `youtube/schema.py:534`) | CONFIRMED — doubling 8/32, templated lead-in 31/32, generic-speaker 12/32 | `b18ffaaf` — *"In this walkthrough, James Fadiman argues that **james fadiman argues that** psychedelics… can serve as a powerful tool"* (lowercased echo) |
| **F2-1** wrong/generic **speaker attribution** (not just multi-speaker — wrong *entity* on single-speaker too) | CONFIRMED (broadened) — ~10/32 wrong-entity speaker | `cd73b78e` — *"Speakers: **U.S. Treasury bonds**"* · `f6139a40` — *"Speakers: **Adam Smith**"* (true: Kaushik Basu +4) · `681a07c3` — "Stack Overflow" |

### Reddit — 2 P1
| Issue | Verified verdict | Actual example |
|---|---|---|
| **F2-3** formulaic **consensus/dissent asserted on heavily-truncated threads** | CONFIRMED — mean 72.5% divergence; 15/15 briefs assert consensus+dissent regardless of coverage | `5a0e0654` — *"Consensus stayed around… Dissent centered on…"* built from **2 of 98** comments (98% divergence) · `af39dd2c` — full cluster synthesis from **6 of 206** |
| **RD-1** brief **headline presents a partial thread as settled** (detailed body discloses; brief doesn't) | PARTIAL (narrowed) — mean coverage 27.5%; 13/15 briefs un-hedged | `af39dd2c` — brief leads with consensus; only **6/206** comments rendered; detailed footer admits *"6/206 visible; divergence 97.09%"* but the brief does not |

### GitHub — 2 P1
| Issue | Verified verdict | Actual example (absence fetch-confirmed) |
|---|---|---|
| **GH-1** fabricated **public API/CLI surface** (HTML tags + prose misread as endpoints/flags) | CONFIRMED (strong) — fabricated tokens in **8/12** repos | `b52a80d6` theiagen — `--Please` (from "Please cite"), `/center`, `--pathogen` (no CLI in README) · `d5650ab7` dendron — `/sub` (from `</sub>` avatar-grid tags) |
| **F2-2** fabrication **concentrates on thin-API repos** (caveat: tag/email noise leaks into rich repos too) | CONFIRMED (caveat) — nonsense fabrications exclusively in thin-API repos (6/7) | `39cc4810` athens — *"README explicitly documents the following public interfaces: @gmail.com, /summary"* — README is a 12-line deprecation notice with neither |

### Web — **NO P1**
| Issue | Verified verdict | Actual example |
|---|---|---|
| (WB-1, **P2** — not P1) reference/index-page **undercoverage** | PARTIAL — 1/19; ambiguous-label & list-devolution did NOT reproduce | `ec1c363c` brainpost monthly archive — summarized **only the top** of 3 distinct articles; the other two silently dropped (faithful to what was captured) |
| Web faithfulness | NO P1 — faith 1.0 on 18/19, zero hallucination caps; Bellingcat 7/7 load-bearing claims verified true | — |

### Newsletter — **NO P1** (n=2, cannot generalize)
| Issue | Verified verdict | Actual example |
|---|---|---|
| (NL-1, ≈**P3** cosmetic) spurious **"Call to action:"** label on non-CTA content | NOT confirmed at P2 — promo-tail contamination *absent* (engine correctly drops Substack CTAs) | `f8de85f8` — *"Call to action: The newsletter also discusses…"* (descriptive, not a CTA) + stray *"the , urgent"* |
| Newsletter faithfulness | NO P1 — ~25 claims verified faithful across both; iter-002's one faithfulness flag was a false positive | — |

---

## Verified P1 — cross-source (harness / pipeline-wide)
| Issue | Verified verdict | Actual example |
|---|---|---|
| **CS-1** extraction-surface mismatch — faithfulness is checked against a **summary-derived** reference, not the true source | CONFIRMED (code-verified) — `source_text.md len == body_md_len` for all 81; `02_run_judge.py:353` / `03_run_nli.py:7` load it as "source of truth" | `628789b4` youtube — true transcript 34,612 chars → reference 6,392 chars (= summary reformatted) · `a9de82e8` reddit — 106/800 comments |
| **CS-2** eval circularity — `source_text.md` ≈ `detailed_summary` | CONFIRMED — **62/81 (77%)** near-identical (web 19/19, github 11/12, youtube 22/33) | `51750374` PEP 701 — byte-identical (difflib 1.000) |
| **CS-3a** tags/label **harness-feed artifact** — judge never fed the tags production emits → false "missing" + `generic_cap=90` on all 81 | CONFIRMED — 10/10 sampled (structural) | `881865c9` requests — `meta` has 10 tags + `mini_title`; the `summary.json` fed to the judge has neither; judge fires `generic_cap=90`, `missing_meta=[mini_title,label,tags]` |

> **Bonus validity finding** (corroborates CS-1/CS-2): the iter-002 judge rated theiagen's fabricated `/center`/`--Please` as **"neutral — Source mentions this as a public API interface"** (faithfulness 0.95) — it treated the fabrication as ground truth, because its "source" is the summary-derived reference. The fabrications **sailed through** the eval.

---

## Net verified P1 list
1. **YT-1** YouTube templated/doubling/generic-speaker brief.
2. **F2-1** YouTube wrong-entity speaker attribution.
3. **F2-3** Reddit formulaic consensus on truncated threads.
4. **RD-1** Reddit brief headline asserts settled consensus on a partial thread (narrowed).
5. **GH-1** GitHub fabricated public API/CLI surface.
6. **F2-2** GitHub fabrication concentrated on thin-API repos.
7. **CS-1** faithfulness checked against a summary-derived reference (not true source).
8. **CS-2** source_text ≈ summary → circular eval (77%).
9. **CS-3a** tags/label harness-feed artifact (`generic_cap` on all 81).

**No P1 for Web or Newsletter** (Web verified clean; Newsletter n=2). Scope: problems only, no fixes. P0/no-data sources not swept (unverifiable). Data keyed by `workspace_zettel_id`.
