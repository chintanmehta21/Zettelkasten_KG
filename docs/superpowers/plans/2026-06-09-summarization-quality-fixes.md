# Summarization Quality Fixes — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the verified P1 summarization defects, starting by making the offline eval trustworthy (so every later fix can be measured), then hardening the per-source summarizers.

**Architecture:** Two subsystems, sequenced by blast radius. **Wave 0 = offline eval harness** (`docs/zettel_eval_v1/`, no production risk) — repair the circular faithfulness reference and the schema-feed artifact so scores become real. **Waves 1–2 = production summarizer** (`website/features/summarization_engine/`, live blast radius) — Reddit/YouTube deterministic-template root-cause fixes, then GitHub interface grounding. Each later wave is gated on Wave 0's re-baselined eval + explicit operator approval.

**Tech Stack:** Python 3.12, Pydantic, pytest (`asyncio_mode=auto`), the existing `zettel_eval_v1` scripts + `summarization_engine` subtree. `tomllib` (stdlib) for manifest parsing. No new services; 2GB droplet untouched.

**Source research:** `docs/claude_audits/zettel_eval_solutions_research_2026-06-09.md` (+ the verified P1/P2/P3 sweeps). Read it before executing.

---

## ⚠️ Open decisions (operator must approve BEFORE the gated tasks)
- **D1 — Eval version bump + RE-JUDGE. ✅ RESOLVED 2026-06-09 → NO re-judge** (operator declined the ~$8 spend). Phase A still ships the schema-feed fix (code + contract test) so **future** freezes carry `tags`/`mini_title`; the existing 81 are **not** re-scored this iteration — the current baseline stays the reference. (Re-freezing without re-judging would desync `summary.json` from the cached judge scores, so leave the frozen corpus as-is — see Step A7.)
- **D2 — Sol 1 raw-source provenance. ✅ RESOLVED 2026-06-09 → (b) cache-where-present + fallback.** Use the 38/81 cached ingests in `docs/summary_eval/_cache/ingests/` (github 11/12, web 14/19, reddit 9/15, newsletter 1/2, youtube 3/33); **operator re-ingests the raw-text for the misses out-of-band**. Phase B stamps `evidence_source` ∈ {`production_ingest_cache`, `reingest`, `body_md_fallback`} per zettel so provenance is explicit.
- **D3 — Touching production at all (Waves 1–2). ✅ RESOLVED 2026-06-09 → approved.** Waves 1–2 may edit live `website/features/summarization_engine/`; each still expands into its own code-complete plan + TDD before code lands.
- **D4 — GitHub manifest-fetch. ✅ RESOLVED 2026-06-09 → Option B (REST piggyback) + token** (research: `docs/claude_audits/github_single_call_research_2026-06-09.md`). Reuse the root `/contents` listing the ingestor already fetches to detect manifests, fetch only the present ones (**+1–2 calls, not 2–3**); token-gated on a 0-permission fine-grained `GITHUB_TOKEN` (operator provisions on the droplet — this also fixes the pre-existing 60/hr-anonymous production risk). **Reddit thresholds** (`coverage ≥ 0.60 AND fetched ≥ 10`) — still confirm during Wave 1A.

---

# WAVE 0 — Eval trustworthiness (safe, offline, NO production code)

## Phase A — Schema-feed fix + contract test (Sol 2)  ✅ fully specified, no open decision

**Root cause (verified):** production's `ai_summary` column is a 2-field envelope (`{brief_summary, detailed_summary}`); tags + `mini_title` live in `canonical_zettels.source_metadata.metadata.structured_payload`. `01_freeze_manifest.py:136` writes `summary.json` = `json.loads(ai_summary)` (2 keys), so the judge never sees tags/label → rubric scores 30/100 pts it wasn't given + applies `generic_cap=90` on all 81 (CS-3a). The `structured_payload` is **already fetched** by `fetch_rows` (line 88) and already stored in `meta.json` (line 124) — the fix only changes what `summary.json` contains.

**Files:**
- Modify: `docs/zettel_eval_v1/scripts/01_freeze_manifest.py:103-143` (`write_zettel_bundle`)
- Test: `docs/zettel_eval_v1/tests/test_01_freeze_contract.py` (new)

- [ ] **Step A1: Write the failing contract test**

```python
# docs/zettel_eval_v1/tests/test_01_freeze_contract.py
"""Contract: the summary.json fed to the judge must carry every field the
rubric scores (tags, mini_title) — not just the ai_summary envelope (CS-3a)."""
from __future__ import annotations
import json, importlib.util
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
SCRIPT = REPO / "docs" / "zettel_eval_v1" / "scripts" / "01_freeze_manifest.py"

def _load():
    spec = importlib.util.spec_from_file_location("freeze01", SCRIPT)
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    return m

def test_summary_json_includes_rubric_fields(tmp_path, monkeypatch):
    m = _load()
    monkeypatch.setattr(m, "DATA_ROOT", tmp_path)
    row = {
        "id": "wz-1", "workspace_id": "ws-1",
        "ai_summary": json.dumps({"brief_summary": "B", "detailed_summary": "D"}),
        "created_at": "2026-01-01T00:00:00Z",
        "canonical": {
            "id": "cz-1", "normalized_url": "https://x", "title": "T",
            "source_type": "github", "content_hash": "\\xab", "body_md": "BODY",
            "source_metadata": {"metadata": {"structured_payload": {
                "tags": ["a", "b", "c"], "mini_title": "psf/requests"}}},
        },
    }
    m.write_zettel_bundle(row, dry_run=False)
    summ = json.loads((tmp_path / "wz-1" / "summary.json").read_text(encoding="utf-8"))
    assert summ["brief_summary"] == "B" and summ["detailed_summary"] == "D"
    assert summ["tags"] == ["a", "b", "c"]          # was MISSING before fix (CS-3a)
    assert summ["mini_title"] == "psf/requests"     # label the rubric scores
    assert summ["_summary_source"] == "structured_payload"

def test_summary_json_flags_envelope_fallback(tmp_path, monkeypatch):
    m = _load()
    monkeypatch.setattr(m, "DATA_ROOT", tmp_path)
    row = {"id": "wz-2", "workspace_id": "ws-1",
           "ai_summary": json.dumps({"brief_summary": "B", "detailed_summary": "D"}),
           "created_at": "", "canonical": {"id": "cz-2", "source_type": "web",
           "body_md": "x", "content_hash": "", "source_metadata": {}}}
    m.write_zettel_bundle(row, dry_run=False)
    summ = json.loads((tmp_path / "wz-2" / "summary.json").read_text(encoding="utf-8"))
    assert summ["_summary_source"] == "ai_summary_envelope"  # no structured_payload -> documented fallback
```

- [ ] **Step A2: Run it — verify it FAILS**

Run: `cd <repo> && python -m pytest docs/zettel_eval_v1/tests/test_01_freeze_contract.py -v`
Expected: FAIL — `KeyError: 'tags'` / `_summary_source` missing (current code writes only the 2 envelope keys).

- [ ] **Step A3: Implement — enrich `summary.json` from `structured_payload`**

In `01_freeze_manifest.py::write_zettel_bundle`, replace the `summary.json` build block (lines 135-142) with:

```python
    try:
        summary_payload = json.loads(ai_summary)
    except Exception:
        summary_payload = {"_raw": ai_summary}
    sp = (((canon.get("source_metadata") or {}).get("metadata") or {})
          .get("structured_payload") or {})
    if isinstance(summary_payload, dict):
        # CS-3a: feed the judge the fields the rubric scores but ai_summary omits.
        if sp:
            summary_payload.setdefault("tags", sp.get("tags") or [])
            summary_payload.setdefault("mini_title", sp.get("mini_title") or "")
        summary_payload["_summary_source"] = "structured_payload" if sp else "ai_summary_envelope"
    (out / "summary.json").write_text(
        json.dumps(summary_payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
```

- [ ] **Step A4: Run the test — verify it PASSES**

Run: `cd <repo> && python -m pytest docs/zettel_eval_v1/tests/test_01_freeze_contract.py -v`
Expected: PASS (2 passed).

- [ ] **Step A5: Update the judge's deterministic schema-failure check (move out of LLM judge)**

Add an assertion the harness runs at load time (not the LLM): in `02_run_judge.py`, after loading `summary.json`, assert the rubric-referenced keys exist OR `_summary_source == "ai_summary_envelope"` (documented thin row); fail-closed otherwise. (Add a 4-line guard + a one-line test in `test_01_freeze_contract.py` style.) This makes the contract enforced at the boundary, per DeepEval "keep deterministic checks out of the judge."

- [ ] **Step A6: Commit**

```bash
git add docs/zettel_eval_v1/scripts/01_freeze_manifest.py docs/zettel_eval_v1/tests/test_01_freeze_contract.py docs/zettel_eval_v1/scripts/02_run_judge.py
git commit -m "fix: feed judge the rubric fields tags+label from structured_payload"
```

- [ ] **Step A7: 🚦 GATE D1 — SKIPPED per operator (no re-judge).** Operator declined the re-judge spend (D1). The schema-feed fix applies to **future** freezes only; do **not** re-freeze + re-judge the existing 81 this iteration (a free re-freeze without the paid re-judge would desync `summary.json` from the cached judge scores). Revisit if/when a fresh eval iteration is commissioned.

## Phase B — True-source evidence reference (Sol 1)  🚦 BLOCKED on decision D2

**Intent:** stop scoring faithfulness against `source_text.md` (= summary-derived `body_md`; `len==body_md_len` on all 81) and score against the true raw source. The faithfulness consumers to repoint: `02_run_judge.py:353` and `03_run_nli.py:542` (data source only; NLI already chunks long premises).
**Open decision D2 (raw-source provenance for the 81):** resolve which of {re-ingest at freeze / production-ingest-cache-where-present + `body_md_fallback` flag / defer} before writing code-complete tasks. Once D2 is chosen, expand Phase B into TDD tasks: (1) `evidence_source` field + `content_digest` in `meta.json`; (2) `source_evidence.json` writer; (3) repoint the 2 consumers; (4) harness-health metric "% corpus with true source"; (5) re-judge under D1.

---

# WAVES 1–2 — Production summarizer (🚦 BLOCKED on D3; expand to own plans after Wave 0 baseline)

> Per the writing-plans multi-subsystem rule, each of these becomes its **own** code-complete plan once Wave 0 yields a trustworthy baseline and the operator approves D3. Below = the verified seams + the research-backed fix spec + the test each plan must include, so the roadmap is explicit. **No production code is written until D3.**

## Wave 1A — Reddit deterministic consensus templates (Sol 4)  [highest faithfulness leverage, cheap]
- **Root cause (verified):** the "Consensus stayed around…/Dissent centered on…" text is **hardcoded Python**, not the LLM — `reddit/schema.py:218-226` (`_repair_brief_summary`), `:282` (min-safe fallback), `reddit/layout.py:201`. Prompt word-banning will NOT fix these.
- **Fix spec:** make all three templates coverage-aware; under low coverage drop the consensus sentence and use "Among the visible sampled comments…"; add corrected `fetched_comment_count = rendered + nested` (fix the `ingest.py:58-60` top-level-only count bug) and gate on `coverage = fetched/num_comments ≥ 0.60 AND fetched ≥ 10` (config-driven; **D4**); inject via existing `_apply_ingest_enrichments` (`summarizer.py:319-344`) — no model call.
- **Tests:** the min-safe fallback must NOT assert consensus on a thread it knows nothing about; brief stays within 5–7 sentences after dropping the consensus line; coverage-unknown (HTML/`num_comments==0` path) → hedge, never "high".
- **Scope:** Reddit now; HN/Twitter = P0/later.

## Wave 1B — YouTube speaker-gate + idempotent formatter + format-verb (Sol 5)
- **Root cause (verified):** doubling = the composer `youtube/schema.py:531-536` prepending `f"In this {fmt}, {speaker} argues that {thesis.lower()}"` with no idempotence guard; `"The speaker"` fallback at `:159`; **three** uncoordinated speaker resolvers (`schema.py::_sanitize_speakers`, `common/speaker_detector.py::detect_youtube_speakers`, `common/structured.py::_post_process_youtube_speakers`) + an `attribution_confidence` field (`:72`) that never gates the composer.
- **Fix spec:** (M1) gate composer on `attribution_confidence` (missing → speaker-free framing); (M2) anchored idempotent guard at the **composition** seam (not render-time, else doubled text still lands in `meta.json`/RAG) — detect `^<name|role> (argues|posits|…) that` and lift verbatim; (M5) consolidate the 3 resolvers + fix the detector→`attribution_confidence` desync (latent mis-gate bug); format-conditional verb map (lecture→explains, tutorial→demonstrates, commentary→argues). **GOTCHA:** `format_classifier.FORMAT_LABELS` ≠ `YouTubeDetailedPayload.format` Literal — resolve label-set mismatch or the verb map silently misses.
- **Tests:** the 3 verified doubling spans collapse; legitimate repetition unchanged; idempotency property test (`f(f(x))==f(x)`); composer-gated-on-confidence test.
- **Scope:** YouTube (+podcast later); 0% doubling elsewhere → don't widen.

## Wave 2 — GitHub interface evidence-ladder (Sol 3)
- **Root cause (verified):** README regex output (`readme_signals.py` `_ENDPOINT_PATH`/`_CLI_FLAG`) is injected as "must-preserve" in `prompts.py::_signals_slot` → the LLM echoes `/sub` (from `</sub>`), `--Please` (from "Please cite"), `/center`.
- **Fix spec:** (M1) refusal-first — default "library/repository overview, no verified interface artifact" and flip to "verified surface" only on a HIGH-rung hit; (M2) **demote the regex out of must-preserve** (corroboration-only; `_is_bogus_surface` blocklist = backstop); (M3) top rung = parse `package.json` `bin` / `pyproject [project.scripts]` + `console_scripts` / `setup.cfg` console_scripts / `Cargo [[bin]]` / committed OpenAPI. **Option B (REST piggyback, per D4):** reuse the root `/contents` listing already fetched at `ingest.py:471` to detect which manifests exist at root, then read only the present ones via the existing `_fetch_file_contents` (`ingest.py:527`) — **+1–2 Contents GETs, no new request mechanism**; `tomllib` (stdlib) for TOML; stay on `api.github.com`. **Token-gated:** with `GITHUB_TOKEN` present (`ingest.py:68-70` already wires `Authorization: Bearer`) the reads run authenticated (5,000/hr); **with no token, gracefully skip manifest verification and fall back to M1's refusal-first label — never fabricate.** Gate the "verified surface" label on artifact-PRESENCE, not `archetype.confidence`. (`openapi.*` is often nested → root-only coverage is best-effort; an optional single recursive Trees call can resolve nested paths later if needed.)
- **Tests:** the verified fabricated tokens are NOT emitted for thin-API repos; a repo with a real `package.json` `bin` DOES surface its real commands; `requests` (real API, no manifest bin) → "library overview, no machine-verified CLI/HTTP artifact" (true + defensible); **no-token / anonymous path → manifest verification is skipped and M1's refusal-first label is used (no fabrication, no crash)**; a manifest absent from the root listing → **zero** wasted fetch calls.
- **Scope:** manifest-fetch top rung = GitHub-only; the regex-demotion rule is cross-source.

---

## Self-review
- **Spec coverage:** Sol 2 → Phase A (complete). Sol 1 → Phase B (gated D2). Sol 4 → Wave 1A. Sol 5 → Wave 1B. Sol 3 → Wave 2. All five solution areas mapped. The eval-version-bump/re-judge cost → D1 gate. Production-edit approval → D3 gate.
- **Placeholders:** Phase A is code-complete (real test + real edit). Waves 1–2 + Phase B are intentionally **not** code-stubbed — they are decision-gated and will be expanded into their own code-complete plans once D2/D3 are resolved (per the multi-subsystem rule), not left as in-task TODOs.
- **Type/seam consistency:** all file:line seams verified this session against the actual code (`01_freeze_manifest.py`, `youtube/schema.py:531-536/159`, `reddit/schema.py:218-226/282`, `reddit/summarizer.py:330`, `github/prompts.py`/`readme_signals.py`).
- **Recurring caution baked in:** every wave ships behind the frozen-81 CI gate (no axis regresses, paired bootstrap, idempotency asserted) + FLAG/shadow before prod; trust human annotations over raw judge scores.
