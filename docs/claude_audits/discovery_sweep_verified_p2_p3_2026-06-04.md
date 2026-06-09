# Discovery-Sweep — Verified P2 / P3 Issues + Actual Examples (2026-06-04)

Companion to `discovery_sweep_verified_p1_2026-06-04.md`. Same method: adversarial verification subagents (one per source-cluster / cross-cutting), each told to *disprove* its claim and confirm only against real data/code/live sources, with verbatim examples. Problems only — no fixes. (Our scale tops out at P3 + P0-deferred; **there is no P4**.)

**What the sweep changed vs the consolidated inventory:**
- **CS-5 demoted P2 → P3.** Humans rate conciseness **healthy** (mean 3.73/5; only 1/81 ≤2). The "verbosity" signal came from a **degenerate iter-005 FineSure conciseness** metric (empty spans, 0.0 scores with zero flagged items) — *another eval-unreliability instance*. The only real residual is a narrow GitHub Overview==Core-argument duplication (2/12).
- **CS-3b count sub-claim disproved as cross-source** — tag counts are locked at exactly 10 for github/newsletter/reddit/youtube; only **web** varies (6–12). The casing/specificity drift is real and cross-source; the count drift is web-only.
- **F2-7 (web shape failures) mostly disproved** — large multi-section pages (gwern, ICIJ, themarkup) are covered *well*; only 1/19 minor brief-editorialization.
- **CS-6 measurement blind spot** — the within-source subtype classifier is **stored for only 47/81** items (github+youtube+newsletter); **absent for all reddit + all web** → true cross-corpus rate unknowable.
- **F2-8 (reddit subtypes) → P3** — real but subtype-conditional and inconsistent (disconfirmed on several threads).

Evidence: ✅EVAL · 🔧CODE✓ · 📚RES · 💡INF. Data keyed by `workspace_zettel_id`.

---

## P2 — confirmed medium

| ID | Source | Issue | Verified verdict | Actual example |
|---|---|---|---|---|
| **F2-5** | youtube | Templated **"argues that" lead-in applied regardless of register** (lectures/tutorials/how-tos forced into thesis framing) | CONFIRMED — 31/32 briefs; 9/9 teaching/demo videos | `707a6e53` (Go WASM **tutorial**): *"In this tutorial, The speaker **argues that** the video **demonstrates** how to… compile a go 'hello world'…"* (argues-vs-demonstrates contradiction); judge flagged `added_framing` |
| **GH-2** | github | **Unfocused / duplicated bullets** (one-bullet-per-unit violated) + low conciseness | CONFIRMED — `one_bullet_per_unit` & `bullets_focused` missed **12/12**; conciseness 0.51; "Overview"=="Core argument" verbatim 12/12 | `2a36ba0a` onionshare: *"Available for Windows, macOS (direct download or Homebrew), and Linux (Flatpak or Snap package)"* (platform+install crammed) · `591880fb` OpenBB: Overview bullet repeated verbatim as Core-argument |
| **WB-1** | web | **Reference/archive page undercoverage** (multi-item page → only first item) | CONFIRMED — **1/19** (re-confirmed; no 2nd instance) | `ec1c363c` brainpost `?month=06-2025`: page lists **3** articles; summary covers **1** (2 silently dropped); `extraction_confidence: high` so it passed |
| **CS-3b** | cross-source | **Stored-tag casing/specificity drift** → graph-link hazard (`Python`≠`python` won't auto-link) | CONFIRMED (casing/specificity); count-drift disproved-as-cross-source | `51750374` web: `['Python','PEP 701','f-strings','Python 3.12',…]` mixed Title/ALLCAPS/lowercase in one array + 7 tags, vs non-web all-lowercase 10-slug; 12 concept tokens collide (`AI/ai`, `Python/python`) |
| **CS-6** | github + youtube | **Within-source subtype misclassification** → wrong summary emphasis | CONFIRMED where classifier exists — github **8/12 wrong** (~67%; no "library" class), youtube stored-format disagrees with emitted format **18/33** | `6a3be69d` big-mac-**data** stored `cli_tool`@conf **1.0** (true: dataset) → picked up spurious "pip install"/operational scaffold · `951bad75` guitar lesson stored `commentary` (true: tutorial) |

## P3 — confirmed low / narrow / residual

| ID | Source | Issue | Verified verdict | Actual example |
|---|---|---|---|---|
| **F2-8** | reddit | Subtype-shape failures (**AMA Q&A-collapse**; advice→declarative; link-claim conflation) | PARTIAL → P3: AMA-collapse 2/2; advice-flattening ~25-40% (disconfirmed on 2 threads); link-conflation 1/3 | `a9de82e8` Ray Dalio AMA: his own answers filed under **"Reply Clusters"** (the commenter-reply field), Q→A linkage lost. *Disconfirmed:* `99790339` preserves per-user attribution |
| **CS-5** | github | Over/under-compression — **narrow** Overview==Core-argument duplication (DEMOTED from P2) | P3 — humans say conciseness healthy (3.73/5); defect is 2/12 github only | `881865c9` requests: `## Overview - psf/requests is a Python HTTP/1.1 library…` then `### Core argument -` **same sentence verbatim** |
| **CS-4** | github | **Residual schema/serialization artifacts** (empty placeholders) — passes the shipped validation gate | P3 — 2/81 residual (both passed gate `patch_applied:false`) | `b52a80d6` theiagen: *"categorized by pathogen type **(e.g.,, )** … **`` & ``** for viruses"* · `c54e4852` athens: empty *"- - @gmail.com"* bullets |
| **NL-1** | newsletter | Spurious **"Call to action:"** label on non-CTA text + text-mangling (n=2) | ≈P3 cosmetic (carry from P1 sweep); promo-contamination *absent* | `f8de85f8`: *"Call to action: The newsletter also discusses… and **the, urgent** implications…"* |
| **F2-7r** | web | Minor brief **editorialization** (qualifier injection) | ≈P3 — 1/19 (large-page undercoverage NOT substantiated) | `7883c431` popular.info Iran: brief appends *"…raising questions about the influence of financial interests on foreign policy"* (unsupported) |

## PARTIAL / CANNOT-VERIFY (flagged, not tiered)

| ID | Source | Why not tiered |
|---|---|---|
| **F2-4** | youtube | **Visual-content loss** — *risk* confirmed (~20/33 had no video-frame tier; transcript/metadata-only) but realized loss is **eval-BLIND** (no video). Side-finding: `e00c622f` (Python overloading) **fabricated on-screen code** (`def add(a,b,c=0)`, `@singledispatch`) from a **metadata-only** extraction that timed out — a faithfulness defect tied to CS-1 |
| **F2-10** | newsletter/web | **Indirect prompt injection** — latent security surface; **no malicious input in the corpus to observe** → can't verify as an occurred defect |
| **P0 set** | arxiv/podcast/twitter/linkedin/HN/document | **Zero eval data** → unverifiable; remain research-only in `consolidated_content_conditional_submodules` File 2 |

---

## Net verified P2/P3
**P2 (5):** F2-5 youtube register-mismatched lead-in · GH-2 github unfocused bullets · WB-1 web reference-page undercoverage · CS-3b stored-tag casing/specificity drift · CS-6 subtype misclassification (github/youtube).
**P3 (5):** F2-8 reddit subtype shapes · CS-5 github Overview/Core-arg duplication (demoted) · CS-4 residual schema artifacts · NL-1 newsletter CTA-mislabel · F2-7r web brief editorialization.
**Unverifiable/latent:** F2-4 (eval-blind), F2-10 (latent security), P0 set (no data).

## Caveats
- Small per-source N (youtube 33, web 19, reddit 15, github 12, newsletter 2).
- **Recurring meta-theme:** the most reliable signal is the **operator-validated human annotations**, not the auto-judge — CS-5's demotion and the GitHub-fabrication-passing-faithfulness (P1 sweep) both trace to auto-judge unreliability (CS-1/CS-2). Treat any P2/P3 that rests *only* on a raw judge score with suspicion.
- `💡INF`/`📚RES` where noted; CONFIRMED rests on judge rubric **+ raw-data reading + human annotations** (not judge alone).
