# Solutions Research & Refinement — Zettel Summarization Fixes (2026-06-09)

Critical research pass over the operator-provided solutions report (`docs/research/zettel-eval-v1_solutions.md`), one dedicated subagent per solution area. Each ran: industry-standard (<5yr) · pragmatic-for-us refinements · side-effect + **2GB-droplet** safety · **content-type-conditional scoping** · **code-seam verification in the actual repo** · real citations. Subagents were instructed to *disprove/refine*, not rubber-stamp.

---

## Cross-cutting findings (read first)

1. **Most fixes are SMALLER than the report stated — the infra already exists; the work is "wire + consolidate + gate," not greenfield.**
   - The immutable source-evidence packet **already exists** as the production ingest cache (`docs/summary_eval/_cache/ingests/`, keyed by `(url, ingestor_version, source_type)` — the same keys the eval manifest stores). The eval just reads the wrong artifact.
   - The YouTube speaker contract is **~60% built** — *three* uncoordinated resolvers + an `attribution_confidence` field already exist; they're just not wired to gate the brief composer.
   - Reddit coverage stats (`comment_divergence_pct`, counts) are **already computed** at ingest.

2. **The real root cause for the two worst content bugs is DETERMINISTIC POST-PROCESSING, not the LLM/prompt.** Prompt-level fixes would miss them entirely.
   - YouTube doubling = the Python composer `youtube/schema.py:531-536` (`f"In this {fmt}, {speaker} argues that {thesis.lower()}"`, no idempotence guard).
   - Reddit "Consensus stayed around… / Dissent centered on…" = **three hardcoded templates** (`reddit/schema.py:218-226`, `:282`, `reddit/layout.py:201`) — forbidding the word in the *prompt* does nothing to these.

3. **Two of the report's root-cause stories are partly inverted — corrected here:**
   - Schema artifact: it is NOT "tags dropped from `structured_payload`." Production's `ai_summary` column is a **thin envelope** (`{brief_summary, detailed_summary}` only — `persist.py:910-928`); tags/`mini_title` live in `user_tags` + `structured_payload`. The harness froze `ai_summary` faithfully → 2 keys. Fix = freeze from `structured_payload` (already in `meta.json`).
   - GitHub: the fabrication source is the README **regex output injected as "must-preserve"** (`prompts.py::_signals_slot` fed by `readme_signals.py`), not merely "no top rung." Adding a manifest top rung alone would NOT fix thin-API repos.

4. **Fixing the eval will (correctly) LOWER scores and break comparability with iter-001…005.** Once faithfulness is scored against the true source (not the summary-derived reference) and the judge is fed the real schema, fabrications that "sailed through" will fail. This is an **eval-methodology version bump** requiring a re-freeze + re-judge — an explicit operator decision, not a silent change.

5. **Everything is droplet-safe.** No new always-on model calls. Manifest parsing uses stdlib `tomllib` (Python 3.12 — already our base image). The **one** new runtime cost is GitHub's optional manifest fetch (+2–3 Contents-API GETs/repo ingest, inside the existing rate-limit + SSRF-safe `api.github.com` envelope). No protected knob (`GUNICORN_WORKERS`, `--preload`, timeouts, rerank semaphore, SSE, Caddy) is touched.

6. **Content-conditional scoping (the operator's hint) — yes, and it varies per fix** (table below).

| Fix | Fires on | Notes |
|---|---|---|
| Eval evidence-bundle | ALL sources | one schema, source-varying `sections` dict |
| Schema/contract test | ALL (shared base + per-source extension) | additive versioning |
| GitHub interface-ladder | GitHub (manifest fetch); demotion rule cross-source | gate label on artifact-presence, not archetype |
| Reddit coverage-gate | Reddit now; HN/Twitter = P0 later | threaded multi-author opinion only |
| YouTube speaker+verb | YouTube (+podcast later) | format-conditional verb; 0% doubling on other sources → don't widen |

---

## Solution 1 — Eval `SourceEvidenceBundle` (the #1 priority)
**Verdict: SOUND, but smaller than stated.** The canonical immutable packet already exists in the production ingest cache (`orchestrator.py:184-211` → `FsContentCache` `docs/summary_eval/_cache/ingests/`); `IngestResult{raw_text, sections, metadata, extraction_confidence, …}` is the packet. The bug is one place: `01_freeze_manifest.py:107,134` writes `source_text.md` from Supabase `body_md`, which is summary-derived (`len==body_md_len` on all 81; `persist.py:797` falls through to `detailed_summary`).
**Refinements:** (a) **rewire the freeze to read the ingest cache** (join on the manifest's existing `normalized_url`+`source_type`), don't build a parallel artifact; (b) write a NEW `source_evidence.json` + a `content_digest` (sha256 of `raw_text`) for idempotent re-freeze — don't overwrite `source_text.md` in place; (c) **flagged fallback** when the cache misses (older `ingestor_version`): re-ingest or record `evidence_source ∈ {ingest_cache, refetched, body_md_fallback}` in `meta.json` so circular items are *excludable*, not silently scored; (d) cap stored `raw_text` (~600KB; one 513KB transcript exists) to bound git size; (e) `02_run_judge.py:353` / `03_run_nli.py:542` change **data source only** — NLI already chunks+max-pools long premises (no logic change). *Cit: FineSurE ACL'24; FaithBench NAACL'25; RAGAS arXiv:2309.15217; FFCI JAIR'22; golden-dataset immutability (Statsig/Arize'25).*
**Decision needed:** post-fix scores drop + are incomparable to iter-001…005 → version bump + re-freeze/re-judge.

## Solution 2 — Canonical versioned summary schema + contract tests
**Verdict: adopt the mechanism; the report's root cause is INVERTED.** True cause: `ai_summary` is a 2-field envelope (`persist.py:910-928`); the harness froze it faithfully (`01_freeze_manifest.py:136` → `summary.json` = `{brief, detailed}`); the rubric then scores 30/100 pts of `tags`+`label` it was never given + applies `generic_cap=90` (`rubric_universal.yaml:58-99`, `models.py:235-242`).
**Refinements:** (a) freeze `summary.json` from `structured_payload` (already in `meta.json`), fallback to envelope only when `is_schema_fallback`; (b) **consumer-driven contract test** — assert every rubric-referenced field (`tags.*`, `label.*`, `mini_title`, brief, detailed) exists in the fed summary, fail-closed (gated on `_summary_source` so legitimately-thin historical rows don't break it); (c) **move deterministic schema/required-field checks OUT of the LLM judge** (`prompts.py:118-134`) into the contract test; (d) **NOT one flat schema** — per-source payloads diverge (`GitHubStructuredPayload` etc.); use shared base + per-source extension, **additive** SemVer versioning (open-consumer/closed-producer), so old cached runs stay valid. *Cit: Pact CDCT; Confluent schema-evolution; DeepEval LLM-judge (deterministic-checks-separate); collinwilkins structured-output'26.*
**Decision needed:** re-freeze+re-judge (same as Sol 1).

## Solution 3 — GitHub interface evidence-ladder
**Verdict: ENDORSE with 3 modifications; the ladder alone won't fix thin-API repos.**
**Refinements:** (M1) **refusal-first** — default "no verified interface artifact found / library overview" and flip to "verified surface" only on a HIGH-rung artifact hit (CloudAPIBench: *intelligently-triggered* grounding beats always-augment); (M2) **the actual root fix** — demote `readme_signals.py` regex output (`_ENDPOINT_PATH`/`_CLI_FLAG`) OUT of the "must-preserve" prompt slot (`prompts.py::_signals_slot`); that instruction is *why* the LLM echoes `/sub`/`--Please`; regex becomes corroboration-only, the `_is_bogus_surface` blocklist a backstop (not primary defense); (M3) **top rung = parse manifests** the ingestor newly fetches: npm `package.json` `bin`, Python `pyproject [project.scripts]`/`console_scripts`, Cargo `[[bin]]`, committed OpenAPI — **this is new fetch work** (the ingestor fetches dir *listings* + README bodies, not manifest bodies today); (M4) cap +2-3 Contents-API GETs, `tomllib`, silent degrade, stay on `api.github.com` (SSRF-safe). **Gate the conservative label on artifact-ABSENCE, not `archetype.confidence`** (archetype misclassifies — CS-6). *Cit: CloudAPIBench arXiv:2407.09726; OOPS arXiv:2601.12735 (97-98% endpoint F1 from artifacts); learning-to-refuse arXiv:2409.11242; generation-time>post-hoc grounding arXiv:2509.21557; npm `bin` docs.*
**Decision needed:** new GitHub ingestor fetch (+API calls) is a production-ingestor change; re-baseline GitHub eval after (`public_interfaces` content shifts).

## Solution 4 — Reddit coverage-aware viewpoint summarization
**Verdict: adopt principle; 3 corrections (root cause is hardcoded templates).**
**Refinements:** (M1) **fix the 3 deterministic templates FIRST** (`reddit/schema.py:218-226` `_repair_brief_summary`, `:282` min-safe fallback, `layout.py:201` "rough consensus") — make them coverage-aware/drop the consensus sentence under low coverage; prompt word-banning is necessary-but-insufficient (these bypass it); (M2) **fix a measurement bug** — `rendered_count` counts top-level `t1` only (`ingest.py:58-60`) while nested replies are fetched + counted separately (`nested_reply_count`), so `divergence_pct` conflates removed-vs-nested → add corrected `fetched_comment_count = rendered + nested`; gate on `fetched/num_comments`, keep `divergence_pct` for the existing note (don't rename — harness reads it); (M3) **quantify, don't just hedge** (counts already available; `cluster_rebalance.py:150-198` synthesizes dissent); (M5) inject via the existing `_apply_ingest_enrichments` seam (`summarizer.py:319-344`) — no new model call. **Threshold (our call, not paper-derived): permit consensus-class language only when `coverage ≥ 0.60 AND fetched ≥ 10`**, config-driven, **calibrate on the 15-thread Reddit eval set**. *Cit: ARQUSUMM arXiv:2511.16985; ThreadSumm arXiv:2604.17648; FacSum EMNLP-F'25; QQSUM arXiv:2506.04020; uncertainty-under-partial-data arXiv:2510.12040.*
**Scope:** Reddit now; HN/Twitter P0.

## Solution 5 — YouTube speaker-resolution + idempotent formatter
**Verdict: APPROVE with major mods; ~60% already exists — wire/consolidate/gate, don't rebuild.**
**Refinements:** (M1) **gate the brief composer on the existing `attribution_confidence`** (`schema.py:72`) — when `missing`, use speaker-free framing, never a fabricated subject (abstention pattern); (M2) **idempotent anchored guard at the COMPOSITION seam** (`schema.py:531-536`, not render-time — else the doubled string still lands in `meta.json`/RAG): detect an existing `^<name|role> (argues|posits|…) that` in the thesis and lift it verbatim instead of prepending; add an idempotency property test; (M3) ship the missing doubling/idempotence/legit-repetition tests (none exist); (M5) **consolidate the 3 resolvers** (`schema.py::_sanitize_speakers`, `common/speaker_detector.py::detect_youtube_speakers` [positive-evidence, no-LLM], `common/structured.py::_post_process_youtube_speakers`) and **fix the `attribution_confidence` desync** — the detector overrides `speakers` but not confidence → can mis-gate (latent bug). **Format-conditional verb (fixes F2-5):** map the format label → verb (lecture→explains, tutorial/walkthrough→demonstrates, commentary→argues). **GOTCHA:** `format_classifier.FORMAT_LABELS` ≠ `YouTubeDetailedPayload.format` Literal — resolve the label-set mismatch or the verb map silently misses. *Cit: FineSurE ACL'24; BARREL abstention arXiv:2505.13529; ASR-confidence selective-correction arXiv:2407.21414; reporting-verb stance taxonomy (Adelaide).*
**Scope:** YouTube (+podcast later); 0% doubling elsewhere → don't widen.

---

## Recommended rollout (refined from the report's 3 waves)
- **Wave 0 (eval first — makes the signal trustworthy):** Sol 1 (rewire freeze to ingest-cache + flagged fallback + digest) + Sol 2 (freeze from `structured_payload` + contract test). Then re-freeze + re-judge → a clean v2 baseline. *Gate everything else on this.*
- **Wave 1 (deterministic root-cause fixes — cheap, highest faithfulness leverage):** Reddit M1 (3 templates) + M2 (corrected coverage) ; YouTube M1+M2 (gate composer + idempotent guard) + M5 (resolver/confidence desync) + format-verb. These are pure string/threshold logic, no model calls.
- **Wave 2 (GitHub):** demote regex (M2) + refusal-first label (M1) [cheap], then manifest top-rung (M3) [new fetch].
- **Every wave** ships behind the frozen-81 CI gate (no axis regresses, paired bootstrap, idempotency asserted), FLAG/shadow before prod, per the rollout doc.

## Open decisions for operator approval (surfaced, not assumed)
1. **Eval version bump + re-freeze/re-judge** (scores drop, incomparable to iter-001…005).
2. **GitHub ingestor new fetch** (+2-3 API calls/repo) — a production change.
3. **Reddit thresholds** 0.60 / 10 — to be calibrated on the 15-thread set.
4. Production-summarizer edits at all (Waves 1-2 touch live `website/features/summarization_engine/`) — blast-radius; confirm before implementation.

*(Full per-area subagent detail incl. line-exact seams + complete citation lists is in the workflow record; this report is the synthesis. Problems→solutions research only — no code changed.)*
