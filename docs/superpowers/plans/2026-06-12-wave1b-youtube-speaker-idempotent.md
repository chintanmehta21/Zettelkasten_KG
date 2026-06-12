# Wave 1B — YouTube Speaker-Gate + Idempotent Brief Composer + Format-Verb Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop the YouTube one-line brief composer (`youtube/schema.py::_compose_structured_brief`) from doubling attribution clauses, fabricating a "The speaker" subject, and always using the verb "argues" — by gating the lead sentence on `attribution_confidence`, lifting any pre-existing leading attribution clause idempotently at the composition seam, and selecting a format-conditional reporting verb — while consolidating the three uncoordinated speaker resolvers so the detector override no longer desyncs `attribution_confidence`.

**Architecture:** All composition logic lives in one new pure leaf module `website/features/summarization_engine/summarization/youtube/attribution.py` (no model call, no I/O). It exposes: (a) `compose_lead_sentence(...)` — the confidence-gated, format-verb-aware, idempotent first sentence used by `_compose_structured_brief`; (b) `has_leading_attribution(text)` / `lift_leading_attribution(text)` — the anchored, canonicalised, ReDoS-safe idempotency guard; (c) `reporting_verb_phrase(format_label, confidence)` — the La-Trobe-stance verb map keyed on the canonical format label. The schema's composer (`schema.py:531-536`) delegates its lead sentence to `compose_lead_sentence`; the fabricated `"The speaker"` fallback at `schema.py:528` is removed in favour of confidence-gated, topic-fronted framing. The label-set mismatch (`format_classifier.FORMAT_LABELS` vs the `YouTubeDetailedPayload.format` Literal) is resolved first with a single canonical-label normaliser so the verb map never silently misses. Resolver consolidation routes the `speaker_detector` override (`youtube/summarizer.py:171-189`) through one helper that re-derives `attribution_confidence` whenever it changes `speakers`.

**Tech Stack:** Python 3.12, Pydantic v2.12 (`validate_assignment` is OFF — confirmed below; this is *why* the format leak and the bad subject reach `meta.json`), `re` (CPython backtracking engine — anchored + bounded ranges only, ReDoS-safe), `unicodedata.normalize("NFC", …)` for canonicalisation, pytest (`asyncio_mode=auto`). **Hypothesis is NOT installed** (`ops/requirements-dev.txt` has no `hypothesis`; `import hypothesis` → `ModuleNotFoundError` on this tree) — the idempotency *property* is therefore exercised with a deterministic in-test generator loop over a fixed corpus of theses (with/without leading attribution, varied case/punctuation/Unicode), NOT `@given`. See FLAG-H below. No new model call on any path. Production code under `website/features/summarization_engine/` — operator approved (D3).

---

## VERIFICATION SUMMARY (read before implementing — every seam confirmed against the live tree on 2026-06-12)

All line numbers below were read from disk and several were **reproduced empirically** (see the two repro blocks at the end of this section). Where the task spec diverged from the actual code, it is **FLAGGED**.

| Seam (task spec) | Actual state on disk | Action |
|---|---|---|
| `youtube/schema.py:531-536` doubling composer | **CONFIRMED + REPRODUCED.** Lines 531-536 inside `_compose_structured_brief` (518-556): `parts.append(f"In this {format_name}, {speaker} argues that {thesis_sentence.lower().rstrip('.')}.")`. No idempotence guard. Repro 1 below shows `"In this commentary, The speaker argues that the host argues that …"`. | Task 4 delegates this block to `attribution.compose_lead_sentence`. |
| `schema.py:159` "The speaker" fabricated fallback | **FLAG — TWO sites, not one.** (a) `schema.py:159` `self.speakers = ["The speaker"]` in `_sanitize_speakers` (Step 4) — this sets `speakers` AND `attribution_confidence="missing"` (160). That is acceptable as an internal sentinel. (b) **The real fabrication-into-prose site is `schema.py:528`** `speaker = _primary_speaker(speakers) or "The speaker"`, which then feeds the lead sentence at 534 EVEN WHEN `attribution_confidence == "missing"` (Repro 2 emits `"…The speaker argues that the narrator traces…"`). Task 4 removes the `or "The speaker"` prose fallback; the sentinel in `_sanitize_speakers` is left intact (Task 1 reconciles it). | Task 4 → `schema.py:528,531-536`. |
| `schema.py:72` `attribution_confidence` field | **CONFIRMED.** `attribution_confidence: Literal["high","low","missing"] = "high"` (72). Set by `_sanitize_speakers` (142/155/160) but **never read by the composer**. | Task 4 makes the composer gate on it (passed in via Task 3 signature change). |
| Resolver #1 `schema.py::_sanitize_speakers` | **CONFIRMED.** `model_validator(mode="after")` at 97-161; 4-step fallback; sets `attribution_confidence`. | Task 1 (reconciliation helper reused by Task 5). |
| Resolver #2 `common/speaker_detector.py::detect_youtube_speakers` | **CONFIRMED.** Positive-evidence, no-LLM, returns `["The speaker"]` when nothing proven (231-232). | Task 5 routes its override through the reconciliation helper. |
| Resolver #3 `common/structured.py::_post_process_youtube_speakers` | **FLAG — WRONG NAME.** No function named `_post_process_youtube_speakers` exists. The YouTube speaker post-processing lives in **`common/structured.py::_apply_identifier_hints`** (def at 641), the `elif st == SourceType.YOUTUBE:` branch at **702-742**. It filters placeholders, falls back to channel, and sets `attribution_confidence` (734/736/741). | Task 5 self-review confirms it stays consistent; **no edit** unless the override test shows a desync through it. |
| Detector override desync (`summarizer.py`) | **CONFIRMED.** `youtube/summarizer.py:171-189`: when `detect_youtube_speakers` returns a real list, it does `sp["speakers"] = detected` (186) but **never touches `sp["attribution_confidence"]`** — so a payload the LLM marked `"missing"`/`"low"` keeps that stale confidence even though a real speaker was just proven. Latent mis-gate. | Task 5 fixes: when the override changes speakers, recompute confidence. |
| `format_classifier.FORMAT_LABELS` vs `YouTubeDetailedPayload.format` Literal | **CONFIRMED MISMATCH (empirically).** `FORMAT_LABELS = ("documentary","commentary","lecture","explainer","interview")`. Literal = `("tutorial","interview","commentary","lecture","review","debate","walkthrough","reaction","vlog","other")`. Overlap = `{commentary, lecture, interview}` only. `validate_assignment` is OFF, so `_normalize_format_name` (schema.py:680-708) **silently assigns out-of-Literal labels** (`documentary`/`explainer`) into `detailed_summary.format` (Repro 2: final `format == "documentary"`). A naïve verb map keyed on the Literal would miss every classifier-upgraded label. | Task 2 builds one canonical-label normaliser the verb map keys on; resolves the mismatch **first**. |
| Hypothesis availability | **FLAG-H — NOT INSTALLED.** `import hypothesis` → `ModuleNotFoundError`; absent from `ops/requirements-dev.txt`. Adding a new test dependency is a test-strategy decision (CLAUDE.md memory tagging list) that needs operator approval and a `requirements-dev.txt` bump + CI install. To stay self-contained and droplet-safe, the idempotency property `compose(compose(x)) == compose(x)` is exercised by a **deterministic generator loop** over a fixed thesis corpus inside the test (no `@given`). If the operator later approves Hypothesis, the same corpus converts to `@given(st.sampled_from(...))` trivially. | Property test uses stdlib loop; Hypothesis deferral surfaced as open decision #1. |

**Repro 1 — DOUBLING (run on this tree, 2026-06-12):**
```text
>>> _compose_structured_brief(format_name='commentary',
...     thesis='The host argues that inflation is structural, not transitory',
...     speakers=['the host'], entities=[], chapter_titles=[],
...     demonstrations=[], closing_takeaway='Rates will stay high.')
'In this commentary, The speaker argues that the host argues that inflation is structural, not transitory. The closing point is that rates will stay high.'
```
(`speakers=['the host']` is a placeholder → `_primary_speaker` returns `''` → `or "The speaker"` → fabricated subject; the thesis already opens with `"The host argues that"` → doubled.)

**Repro 2 — FABRICATED SUBJECT + FIXED VERB + FORMAT LEAK (run on this tree, 2026-06-12):**
```text
>>> p = YouTubeStructuredPayload(... format='other',
...     thesis='The narrator traces an untold story using archival footage.',
...     speakers=['The speaker'] ...)
>>> p.detailed_summary.format ; p.attribution_confidence ; p.brief_summary
'documentary'   # classifier label leaked through (out of Literal, validate_assignment OFF)
'missing'
'In this documentary, The speaker argues that the narrator traces an untold story using archival footage. The documentary moves through Seg 1. The closing point is that the investigation continues.'
```
(`attribution_confidence == "missing"` yet the composer still emits `"The speaker argues that …"` — the exact M1 defect. Format is a documentary but the verb is "argues" — the M-verb defect.)

**Pydantic / config facts (verified):** `pydantic 2.12.5`; `YouTubeStructuredPayload.model_config.get('validate_assignment')` is `None` (→ False). `_sanitize_speakers` and `_normalize_note_facing_fields` are BOTH `model_validator(mode="after")`; Pydantic runs after-validators in **definition order**, so `_normalize_note_facing_fields` (defined first, 74) runs **before** `_sanitize_speakers` (97). **Consequence:** when `_repair_brief_summary`/`_compose_structured_brief` runs, `attribution_confidence` is still its raw input value (often the default `"high"`), NOT yet the value `_sanitize_speakers` will set. **Task 1 fixes this ordering hazard by reordering the two validators** so speaker sanitation (which fixes confidence) runs *before* brief composition. This is required for M1 to gate on a correct confidence.

**Citations carried into forensic comments / commits where load-bearing:**
- Idempotency `f(f(x))==f(x)` + NFC canonicalisation before compare: Unicode UAX #15 (normalization is idempotent); property-based testing idempotence law.
- ReDoS / catastrophic backtracking (anchored, literal prefix, bounded `\w{1,40}`/`\s{1,3}`, no nested quantifiers): Snyk ReDoS guidance.
- Abstention / never invent a subject; topic-fronted agentless framing gated by confidence: AIS attribution test (Rashkin et al., Computational Linguistics 2023); abstention survey (Wen et al., TACL 2025, arXiv:2407.18418).
- Reporting-verb stance taxonomy (neutral / strong / tentative; agentless for unknown): La Trobe reporting-verbs; AnthroScore over-attribution (Cheng et al., EACL 2024, arXiv:2402.02056).

---

## Task 1 — Reconciliation helper + validator ordering (fix the confidence desync at the source)

`_sanitize_speakers` already derives `attribution_confidence` from the speaker list, but (a) it runs **after** brief composition (wrong order — composition needs the corrected confidence) and (b) its derivation logic is inline, so the `speaker_detector` override (Task 5) cannot reuse it and ends up desyncing confidence. Extract the derivation into one pure helper `reconcile_attribution_confidence(speakers)` and reorder the two `model_validator`s so sanitation runs first. No behavioural change to a single-pass construction except the corrected ordering; the helper returns exactly what the inline code computed.

**Files:**
- Modify: `website/features/summarization_engine/summarization/youtube/schema.py:74-95` (move `_normalize_note_facing_fields` below `_sanitize_speakers`) and `schema.py:97-161` (extract derivation)
- Test: `tests/unit/summarization_engine/summarization/test_youtube_attribution.py` (Create)

Current code to replace — the inline confidence derivation in `_sanitize_speakers` (schema.py:135-160), quoted verbatim:
```python
        # H2/C2: detect mixed real+placeholder for the "low" tier.
        had_placeholder = any(
            _is_placeholder_speaker(s.strip()) or _is_geographic_entity(s.strip())
            for s in raw_speakers
        )
        if real:
            self.speakers = real
            self.attribution_confidence = "low" if had_placeholder else "high"
            return self

        # Step 3: first named human entity in entities_discussed.
        for entity in (self.entities_discussed or []):
            if (
                isinstance(entity, str)
                and _looks_like_named_human(entity)
                and not _is_geographic_entity(entity)
                and not _is_non_human_speaker_entity(entity)
            ):
                self.speakers = [entity.strip()]
                # Coerced from entities — original speakers were all placeholders.
                self.attribution_confidence = "missing"
                return self

        # Step 4: deterministic neutral label.
        self.speakers = ["The speaker"]
        self.attribution_confidence = "missing"
        return self
```

### Steps

- [ ] **Write failing test** (REAL code) — create the new test module and lock the reconciliation contract (the helper does not exist yet → import error is the failure):
```python
# tests/unit/summarization_engine/summarization/test_youtube_attribution.py
"""Wave 1B: YouTube attribution gating, idempotent composer, format-verb map.

Pure deterministic string/threshold logic — NO model call, NO network.
"""
from __future__ import annotations

from website.features.summarization_engine.summarization.youtube.attribution import (
    reconcile_attribution_confidence,
)


def test_reconcile_all_real_names_is_high():
    assert reconcile_attribution_confidence(["Lex Fridman", "Andrej Karpathy"]) == "high"


def test_reconcile_mixed_real_and_placeholder_is_low():
    # one real + one placeholder/geographic survivor pattern -> "low"
    assert reconcile_attribution_confidence(["Lex Fridman", "the host"]) == "low"


def test_reconcile_all_placeholder_is_missing():
    assert reconcile_attribution_confidence(["the host", "narrator"]) == "missing"


def test_reconcile_sentinel_the_speaker_is_missing():
    assert reconcile_attribution_confidence(["The speaker"]) == "missing"


def test_reconcile_empty_is_missing():
    assert reconcile_attribution_confidence([]) == "missing"
```

- [ ] **Run to FAIL:**
```
cd "C:\Users\LENOVO\Documents\Claude_Code\Projects\Obsidian_Vault\.claude\worktrees\thirsty-dirac-c3a180" && python -m pytest tests/unit/summarization_engine/summarization/test_youtube_attribution.py -q
```
Expected: FAIL — `ModuleNotFoundError: No module named '...youtube.attribution'`.

- [ ] **Minimal impl — part A** (create the helper). Create `website/features/summarization_engine/summarization/youtube/attribution.py` with ONLY the reconciliation helper for now (the rest is added in Tasks 2-4):
```python
"""Confidence-gated, idempotent, format-verb-aware lead-sentence composition
for YouTube briefs (Wave 1B). Pure + deterministic — NO model call.

Three defects this module fixes in youtube/schema.py::_compose_structured_brief:
  1. DOUBLING — prepended "{speaker} argues that {thesis}" with no idempotence
     guard, so a thesis already opening with an attribution clause doubled it.
  2. FABRICATED SUBJECT — "The speaker" was injected as a grammatical subject
     even when attribution_confidence == "missing" (no source supported it).
  3. FIXED VERB — always "argues", over-attributing stance for non-argumentative
     formats (La Trobe stance taxonomy; AnthroScore arXiv:2402.02056).
"""
from __future__ import annotations

from website.features.summarization_engine.summarization.youtube.schema import (
    _is_placeholder_speaker,
    _is_geographic_entity,
)

_SENTINEL_SPEAKER = "the speaker"


def reconcile_attribution_confidence(speakers: list[str]) -> str:
    """Derive attribution_confidence ('high'|'low'|'missing') from a speaker list.

    Single source of truth reused by the schema validator AND the
    speaker_detector override seam (summarizer.py) so the two can never desync.
    Mirrors the prior inline logic in _sanitize_speakers exactly:
      - any real (non-placeholder, non-geographic, non-sentinel) name present:
        'high' if NO placeholder/geographic was also present, else 'low'
      - no real name at all: 'missing'
    """
    cleaned = [s.strip() for s in (speakers or []) if isinstance(s, str) and s.strip()]
    real = [
        s for s in cleaned
        if not _is_placeholder_speaker(s)
        and not _is_geographic_entity(s)
        and s.lower() != _SENTINEL_SPEAKER
    ]
    if not real:
        return "missing"
    had_placeholder = any(
        _is_placeholder_speaker(s) or _is_geographic_entity(s) or s.lower() == _SENTINEL_SPEAKER
        for s in cleaned
    )
    return "low" if had_placeholder else "high"


__all__ = ["reconcile_attribution_confidence"]
```
**FLAG (import direction):** `attribution.py` imports the leaf predicates `_is_placeholder_speaker` / `_is_geographic_entity` from `schema.py`. `schema.py` will import the *composer* helpers from `attribution.py` (Task 4) — a potential cycle. Avoid it by importing those composer helpers **lazily inside `_compose_structured_brief`** (Task 4 does exactly this, matching the existing lazy-import pattern at schema.py:440 and 698). The predicate import here is module-top-level and safe because `attribution.py` is imported *by* schema only inside a function.

- [ ] **Minimal impl — part B** (rewire `_sanitize_speakers` to use the helper). Replace schema.py:135-160 (quoted above) with:
```python
        if real:
            self.speakers = real
        else:
            # Step 3: first named human entity in entities_discussed.
            coerced = None
            for entity in (self.entities_discussed or []):
                if (
                    isinstance(entity, str)
                    and _looks_like_named_human(entity)
                    and not _is_geographic_entity(entity)
                    and not _is_non_human_speaker_entity(entity)
                ):
                    coerced = entity.strip()
                    break
            # Step 4: deterministic neutral sentinel when nothing plausible.
            self.speakers = [coerced] if coerced else ["The speaker"]
        # Single source of truth for confidence (reused by the detector
        # override seam so the two resolvers can never desync — Wave 1B M5).
        from website.features.summarization_engine.summarization.youtube.attribution import (
            reconcile_attribution_confidence,
        )
        self.attribution_confidence = reconcile_attribution_confidence(self.speakers)
        return self
```
**Behaviour-preservation note:** the prior code set `"missing"` for the entities-coerced case AND for the sentinel case; `reconcile_attribution_confidence(["The speaker"])` and `reconcile_attribution_confidence([<single coerced real name>])` — the coerced name is a *real* name, so reconcile returns `"high"`, NOT `"missing"`. **FLAG — DELIBERATE CHANGE:** a name surfaced from `entities_discussed` is a genuinely named human (passed `_looks_like_named_human`), so `"high"` is more correct than the old `"missing"`; but it IS a behaviour change. Surface as open decision #2; if the operator wants the old conservative `"missing"` for entity-coerced speakers, add a 1-line branch (`if coerced: self.attribution_confidence = "missing"`) after the reconcile call.

- [ ] **Minimal impl — part C** (reorder the two validators so sanitation runs first). Move the entire `_sanitize_speakers` method (97-161) **above** `_normalize_note_facing_fields` (74-95) in the class body. No code inside either method changes; only their definition order. After the move, `_sanitize_speakers` is the first `model_validator(mode="after")` and runs before brief composition.
```text
# class YouTubeStructuredPayload body, after the field declarations:
#   1) _sanitize_speakers      (moved up — fixes speakers + confidence FIRST)
#   2) _normalize_note_facing_fields  (now runs second — composes brief with corrected confidence)
```

- [ ] **Run to PASS:**
```
cd "C:\Users\LENOVO\Documents\Claude_Code\Projects\Obsidian_Vault\.claude\worktrees\thirsty-dirac-c3a180" && python -m pytest tests/unit/summarization_engine/summarization/test_youtube_attribution.py -q
```
Expected: 5 passed.

- [ ] **Regression — existing schema/summarizer suite still green:**
```
cd "C:\Users\LENOVO\Documents\Claude_Code\Projects\Obsidian_Vault\.claude\worktrees\thirsty-dirac-c3a180" && python -m pytest tests/unit/summarization_engine/summarization/test_youtube_schema.py tests/unit/summarization_engine/summarization/test_youtube_summarizer.py -q
```
Expected: 3 passed (the two existing schema tests + the summarizer test; the validator reorder + helper extraction are behaviour-preserving for those fixtures, both of which supply real speakers → `"high"` unchanged).

- [ ] **Commit:**
```
git commit -m "refactor: single-source youtube attribution confidence"
```

### Self-review
- [ ] `reconcile_attribution_confidence` returns the identical value the old inline code did for every case EXCEPT the entity-coerced case (now `"high"` not `"missing"`) — flagged as open decision #2.
- [ ] Validator order is now sanitize → normalize; confirm with: `[v.__name__ for v in ...]` is not exposed, so verify by the Task-4 gate test (a `"missing"`-confidence payload must hit the agentless branch — proves confidence was set before composition).
- [ ] No cycle: `attribution.py` top-level imports only leaf predicates from `schema.py`; `schema.py` imports from `attribution.py` lazily inside functions only.
- [ ] `_apply_identifier_hints` (structured.py:702-742, resolver #3) still independently sets confidence on the raw dict before validation — that is fine; the validator re-reconciles from the final speaker list, so the last word is always `reconcile_attribution_confidence`.

---

## Task 2 — Canonical format label + the FORMAT_LABELS↔Literal bridge (resolve the mismatch FIRST)

The verb map (Task 3) keys on the format label. But `detailed_summary.format` can hold either a Literal value the LLM emitted (`tutorial`/`review`/`debate`/`walkthrough`/`reaction`/`vlog`/`other`) **or** a classifier label that leaked through `_normalize_format_name` (`documentary`/`explainer`) — `validate_assignment` is OFF so the leak is silent (Repro 2). Build one `canonical_format(label)` that folds BOTH vocabularies onto a small closed set of canonical keys the verb map is guaranteed to cover. This is the prerequisite that stops the verb map from silently missing.

**Files:**
- Modify: `website/features/summarization_engine/summarization/youtube/attribution.py` (add `canonical_format`)
- Test: `tests/unit/summarization_engine/summarization/test_youtube_attribution.py` (extend)

### Canonical key set + folding table (closed; every input maps to exactly one)
| Canonical key | Folds these labels (Literal ∪ FORMAT_LABELS, case-insensitive) |
|---|---|
| `lecture` | `lecture`, `talk` |
| `explainer` | `explainer`, `tutorial`, `walkthrough`, `how-to`, `howto`, `demo`, `guide` |
| `commentary` | `commentary`, `opinion`, `essay`, `review`, `reaction`, `debate`, `vlog` |
| `documentary` | `documentary`, `docuseries` |
| `news` | `news`, `report`, `recap` |
| `interview` | `interview`, `discussion`, `podcast`, `q&a`, `conversation` |
| `unknown` | `other`, `""`, anything unrecognised |

Rationale per the research verb taxonomy: lecture/talk→neutral *explains*; tutorial/walkthrough/demo→*demonstrates*; commentary/opinion/essay/debate→*argues*; news/report/recap→*reports*; interview/discussion→agentless *covers/discusses*; documentary→agentless *examines/traces* (narrator-fronted, source rarely a single named arguer); unknown→agentless (no guessed verb).

### Steps

- [ ] **Write failing test** (REAL code) — append to `test_youtube_attribution.py`:
```python
import pytest

from website.features.summarization_engine.summarization.youtube.attribution import (
    canonical_format,
)


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("lecture", "lecture"),
        ("talk", "lecture"),
        ("tutorial", "explainer"),
        ("walkthrough", "explainer"),
        ("demo", "explainer"),
        ("explainer", "explainer"),
        ("commentary", "commentary"),
        ("review", "commentary"),
        ("reaction", "commentary"),
        ("debate", "commentary"),
        ("vlog", "commentary"),
        ("documentary", "documentary"),   # classifier-leaked label, NOT in Literal
        ("news", "news"),
        ("recap", "news"),
        ("interview", "interview"),
        ("discussion", "interview"),
        ("other", "unknown"),
        ("", "unknown"),
        ("ASMR-something-weird", "unknown"),
        ("  Commentary  ", "commentary"),  # case + whitespace tolerant
    ],
)
def test_canonical_format_folds_both_vocabularies(raw, expected):
    assert canonical_format(raw) == expected


def test_canonical_format_covers_every_literal_and_classifier_label():
    # No label from either vocabulary may fall through to a verb-map miss.
    from website.features.summarization_engine.summarization.youtube.format_classifier import (
        FORMAT_LABELS,
    )
    literal = ("tutorial", "interview", "commentary", "lecture", "review",
               "debate", "walkthrough", "reaction", "vlog", "other")
    for label in (*FORMAT_LABELS, *literal):
        key = canonical_format(label)
        assert key in {"lecture", "explainer", "commentary", "documentary", "news", "interview", "unknown"}
```

- [ ] **Run to FAIL:**
```
cd "C:\Users\LENOVO\Documents\Claude_Code\Projects\Obsidian_Vault\.claude\worktrees\thirsty-dirac-c3a180" && python -m pytest tests/unit/summarization_engine/summarization/test_youtube_attribution.py -k canonical_format -q
```
Expected: FAIL — `ImportError: cannot import name 'canonical_format'`.

- [ ] **Minimal impl** (REAL code) — add to `attribution.py`:
```python
# Wave 1B: fold BOTH the YouTubeDetailedPayload.format Literal AND
# format_classifier.FORMAT_LABELS onto one closed key set the verb map covers.
# validate_assignment is OFF, so classifier labels (documentary/explainer) leak
# into detailed_summary.format unvalidated — without this fold the verb map
# would silently miss them. Keys: lecture|explainer|commentary|documentary|
# news|interview|unknown.
_FORMAT_FOLD: dict[str, str] = {
    "lecture": "lecture", "talk": "lecture",
    "explainer": "explainer", "tutorial": "explainer", "walkthrough": "explainer",
    "how-to": "explainer", "howto": "explainer", "demo": "explainer", "guide": "explainer",
    "commentary": "commentary", "opinion": "commentary", "essay": "commentary",
    "review": "commentary", "reaction": "commentary", "debate": "commentary", "vlog": "commentary",
    "documentary": "documentary", "docuseries": "documentary",
    "news": "news", "report": "news", "recap": "news",
    "interview": "interview", "discussion": "interview", "podcast": "interview",
    "q&a": "interview", "conversation": "interview",
}
_CANONICAL_KEYS = frozenset(_FORMAT_FOLD.values()) | {"unknown"}


def canonical_format(label: str | None) -> str:
    """Fold any Literal/classifier format label to a canonical verb-map key.

    Unrecognised / empty / "other" -> "unknown" (agentless framing, no guessed
    verb). Closed mapping: the verb map can never miss.
    """
    return _FORMAT_FOLD.get((label or "").strip().lower(), "unknown")
```
And extend `__all__`:
```python
__all__ = ["reconcile_attribution_confidence", "canonical_format"]
```

- [ ] **Run to PASS:**
```
cd "C:\Users\LENOVO\Documents\Claude_Code\Projects\Obsidian_Vault\.claude\worktrees\thirsty-dirac-c3a180" && python -m pytest tests/unit/summarization_engine/summarization/test_youtube_attribution.py -k canonical_format -q
```
Expected: all parametrized cases + the coverage test pass.

- [ ] **Commit:**
```
git commit -m "feat: canonical youtube format label fold"
```

### Self-review
- [ ] `_CANONICAL_KEYS` is the exact set the verb map (Task 3) defines an entry for — the coverage test cross-checks that every Literal ∪ FORMAT_LABELS input lands in it.
- [ ] No change to `format_classifier.FORMAT_LABELS` or the Literal themselves (backward-compatible; `_normalize_format_name` and `_yt_reserved` still emit the same raw labels for tags). The fold is read-only and used ONLY for verb selection.
- [ ] Open decision #3: the deeper fix would be aligning the classifier output to the Literal (so `detailed_summary.format` never holds an out-of-Literal value). That is a larger schema/tag change touching `_yt_reserved` + eval label expectations — out of scope for Wave 1B; the fold is the surgical, backward-compatible bridge. Surface to operator.

---

## Task 3 — Format-conditional reporting-verb phrase (stance taxonomy)

With one canonical key in hand, map it to a reporting-verb *phrase* that also encodes whether attribution is agented (named subject + verb) or agentless (subject-free framing). Confidence modulates strength: `low` confidence downgrades a strong verb to tentative ("suggests"); `missing` forces agentless regardless of format.

**Files:**
- Modify: `website/features/summarization_engine/summarization/youtube/attribution.py` (add `reporting_verb_phrase`)
- Test: `tests/unit/summarization_engine/summarization/test_youtube_attribution.py` (extend)

### Verb selection matrix (canonical key × confidence)
| Canonical key | `high` (agented) | `low` (agented, hedged) | `missing` (agentless) |
|---|---|---|---|
| `lecture` | `explains that` | `suggests that` | agentless |
| `explainer` | `demonstrates how` | `walks through how` | agentless |
| `commentary` | `argues that` | `suggests that` | agentless |
| `documentary` | agentless (`examines`) | agentless | agentless |
| `news` | `reports that` | `reports that` | agentless |
| `interview` | agentless (`covers`) | agentless | agentless |
| `unknown` | agentless | agentless | agentless |

"agentless" means: NO `{speaker} {verb} that` form — the caller (Task 4) uses a topic-fronted frame instead.

### Steps

- [ ] **Write failing test** (REAL code) — append to `test_youtube_attribution.py`:
```python
from website.features.summarization_engine.summarization.youtube.attribution import (
    reporting_verb_phrase,
)


def test_verb_lecture_high_is_explains():
    assert reporting_verb_phrase("lecture", "high") == "explains that"


def test_verb_explainer_high_is_demonstrates():
    assert reporting_verb_phrase("explainer", "high") == "demonstrates how"


def test_verb_commentary_high_is_argues():
    assert reporting_verb_phrase("commentary", "high") == "argues that"


def test_verb_news_reports():
    assert reporting_verb_phrase("news", "high") == "reports that"


def test_verb_low_confidence_downgrades_strong_to_tentative():
    # commentary's strong "argues" softens to "suggests" at low confidence.
    assert reporting_verb_phrase("commentary", "low") == "suggests that"


def test_verb_missing_confidence_is_agentless_for_every_format():
    for key in ("lecture", "explainer", "commentary", "documentary", "news", "interview", "unknown"):
        assert reporting_verb_phrase(key, "missing") is None  # None == agentless


def test_verb_interview_and_documentary_are_agentless_even_at_high():
    assert reporting_verb_phrase("interview", "high") is None
    assert reporting_verb_phrase("documentary", "high") is None


def test_verb_unknown_format_is_agentless():
    assert reporting_verb_phrase("unknown", "high") is None
```

- [ ] **Run to FAIL:**
```
cd "C:\Users\LENOVO\Documents\Claude_Code\Projects\Obsidian_Vault\.claude\worktrees\thirsty-dirac-c3a180" && python -m pytest tests/unit/summarization_engine/summarization/test_youtube_attribution.py -k verb -q
```
Expected: FAIL — `ImportError: cannot import name 'reporting_verb_phrase'`.

- [ ] **Minimal impl** (REAL code) — add to `attribution.py`:
```python
# Wave 1B: reporting-verb stance taxonomy (La Trobe; over-attribution
# AnthroScore arXiv:2402.02056). neutral=explains/demonstrates/reports,
# strong=argues, tentative=suggests. interview/documentary/unknown -> agentless
# (a host/narrator/unknown source is not a single arguer). Returns None for the
# agentless case; the caller then uses topic-fronted framing.
_VERB_AGENTED: dict[str, dict[str, str]] = {
    "lecture":    {"high": "explains that",    "low": "suggests that"},
    "explainer":  {"high": "demonstrates how", "low": "walks through how"},
    "commentary": {"high": "argues that",      "low": "suggests that"},
    "news":       {"high": "reports that",     "low": "reports that"},
    # documentary / interview / unknown deliberately absent -> always agentless.
}


def reporting_verb_phrase(canonical_key: str, confidence: str) -> str | None:
    """Return the agented reporting-verb phrase (e.g. 'argues that'), or None
    when the lead sentence must be agentless (missing confidence, or a format
    whose 'speaker' is not a single arguer: interview/documentary/unknown).
    """
    if confidence == "missing":
        return None
    table = _VERB_AGENTED.get(canonical_key)
    if not table:
        return None
    return table.get(confidence) or table.get("high")
```
Extend `__all__`:
```python
__all__ = ["reconcile_attribution_confidence", "canonical_format", "reporting_verb_phrase"]
```

- [ ] **Run to PASS:**
```
cd "C:\Users\LENOVO\Documents\Claude_Code\Projects\Obsidian_Vault\.claude\worktrees\thirsty-dirac-c3a180" && python -m pytest tests/unit/summarization_engine/summarization/test_youtube_attribution.py -k verb -q
```
Expected: all pass.

- [ ] **Commit:**
```
git commit -m "feat: format-conditional youtube reporting verb"
```

### Self-review
- [ ] Every canonical key resolves (agented phrase or `None`); no `KeyError` possible (`.get` everywhere).
- [ ] `missing` short-circuits to agentless before the table lookup — proves M1 (`missing` never yields a named-subject sentence).
- [ ] Default-verb-everywhere ("argues") is gone: only `commentary@high` uses "argues"; the over-attribution defect is closed.

---

## Task 4 — Idempotent, confidence-gated `compose_lead_sentence` + wire it into the schema composer

The keystone. Implement the anchored ReDoS-safe leading-attribution detector/lifter and the gated lead-sentence builder, then replace `_compose_structured_brief`'s lines 528 + 531-536 so the brief's first sentence is produced by `attribution.compose_lead_sentence`. This kills DOUBLING (lift instead of prepend), FABRICATED SUBJECT (no `"The speaker"` prose; agentless framing on `missing`), and FIXED VERB (format-conditional).

**Files:**
- Modify: `website/features/summarization_engine/summarization/youtube/attribution.py` (add the detector/lifter + `compose_lead_sentence`)
- Modify: `website/features/summarization_engine/summarization/youtube/schema.py:518-536` (delegate the lead sentence; pass `attribution_confidence` in — see signature change)
- Test: `tests/unit/summarization_engine/summarization/test_youtube_attribution.py` (extend) and `tests/unit/summarization_engine/summarization/test_youtube_schema.py` (extend with the end-to-end doubling/gate cases)

Current code to replace — `_compose_structured_brief` head (schema.py:528-536), quoted verbatim:
```python
    speaker = _primary_speaker(speakers) or "The speaker"
    parts: list[str] = []

    thesis_sentence = _first_sentence(thesis)
    if thesis_sentence:
        parts.append(
            f"In this {format_name}, {speaker} argues that "
            f"{thesis_sentence.lower().rstrip('.')}."
        )
    else:
        parts.append(f"This {format_name} is delivered by {speaker}.")
```

**Signature change (in-scope, backward-compatible at the only call site):** `_compose_structured_brief` and its caller `_repair_brief_summary` gain an `attribution_confidence` kwarg. `_repair_brief_summary` is called once, from `_normalize_note_facing_fields` (schema.py:85-94); add `attribution_confidence=self.attribution_confidence` there. After the Task-1 validator reorder, `self.attribution_confidence` is already reconciled at that point. No other caller exists (verified: `_compose_structured_brief` is referenced only at schema.py:507).

### Steps

- [ ] **Write failing test** (REAL code) — append to `test_youtube_attribution.py`. This is the idempotency property loop (stdlib, no Hypothesis), the anchored-detector unit cases, the ReDoS guard, the gate, and the legitimate-repetition guard:
```python
from website.features.summarization_engine.summarization.youtube.attribution import (
    has_leading_attribution,
    lift_leading_attribution,
    compose_lead_sentence,
)

# --- detector: anchored, only fires on a LEADING whole clause -------------
def test_detector_fires_on_leading_attribution_clause():
    assert has_leading_attribution("The host argues that inflation is structural.")
    assert has_leading_attribution("In this commentary, Jane Doe argues that X happens.")


def test_detector_does_not_fire_on_interior_argues():
    # "argues" appears, but NOT as a leading attribution clause -> must not fire.
    assert not has_leading_attribution("Inflation, she argues, is structural and persistent.")
    assert not has_leading_attribution("The paper that argues for rate cuts is flawed.")


def test_detector_does_not_fire_without_reporting_verb():
    assert not has_leading_attribution("The host of the show lives in Boston.")


# --- lifter: returns the thesis with the leading clause preserved verbatim --
def test_lift_returns_clause_plus_remainder_verbatim():
    text = "The host argues that inflation is structural."
    lifted = lift_leading_attribution(text)
    assert lifted == "The host argues that inflation is structural."  # already a full sentence


# --- IDEMPOTENCY PROPERTY (deterministic corpus loop; see FLAG-H) ----------
_THESIS_CORPUS = [
    "Inflation is structural, not transitory.",
    "The host argues that inflation is structural.",
    "the host argues that inflation is structural",          # lowercase, no period
    "In this commentary, Jane Doe argues that markets overreact.",
    "Dr. Rick Strassman explains that DMT binds serotonin receptors.",  # abbrev guard
    "She argues, in passing, that the model is wrong.",       # interior
    "",                                                       # empty
    "The narrator examines an untold story.",
    "THE HOST ARGUES THAT RATES STAY HIGH",                  # all caps
    "Jane Doe suggests that the data is noisy.",   # NBSP / Unicode drift
]


def _compose(thesis, fmt="commentary", conf="high", speakers=("Jane Doe",)):
    return compose_lead_sentence(
        format_name=fmt, canonical_key=fmt, thesis=thesis,
        speakers=list(speakers), attribution_confidence=conf,
    )


def test_compose_lead_sentence_is_idempotent_over_corpus():
    # f(f(x)) == f(x): feeding the composer its own output as the thesis must
    # not re-prepend / double the attribution clause. (Unicode UAX#15: NFC is
    # itself idempotent; we canonicalise before the anchored compare.)
    for thesis in _THESIS_CORPUS:
        once = _compose(thesis)
        # feed the produced sentence back in as the thesis
        twice = _compose(once)
        assert twice == once, f"not idempotent for {thesis!r}: once={once!r} twice={twice!r}"


def test_compose_does_not_double_when_thesis_already_attributed():
    out = _compose("The host argues that inflation is structural.",
                   fmt="commentary", conf="high", speakers=("the host",))
    low = out.lower()
    assert low.count("argues that") == 1, f"doubled attribution: {out!r}"


def test_compose_missing_confidence_is_speaker_free_and_no_the_speaker():
    out = _compose("Inflation is structural.", conf="missing", speakers=("The speaker",))
    low = out.lower()
    assert "the speaker" not in low, f"fabricated subject leaked: {out!r}"
    assert "argues that" not in low  # agentless on missing
    assert out.endswith((".", "!", "?")) and out


def test_compose_legitimate_repetition_not_mangled():
    # A thesis that merely repeats a content word is left intact (no clause to lift).
    out = _compose("Index funds beat index-tracking ETFs over index periods.",
                   conf="high", speakers=("Jane Doe",))
    assert "index" in out.lower()
    assert out.endswith((".", "!", "?"))


# --- ReDoS adversarial input must return fast -------------------------------
def test_detector_redos_adversarial_input_returns_quickly():
    import time
    # Degenerate: long run of spaces + word chars that would blow up an
    # unbounded/backtracking pattern. Anchored + bounded ranges -> linear.
    evil = ("In this commentary, " + ("a" * 5000) + " " * 5000 + "argues that " + "z" * 5000)
    start = time.perf_counter()
    has_leading_attribution(evil)
    lift_leading_attribution(evil)
    elapsed = time.perf_counter() - start
    assert elapsed < 0.5, f"detector too slow on adversarial input: {elapsed:.3f}s"
```

- [ ] **Run to FAIL:**
```
cd "C:\Users\LENOVO\Documents\Claude_Code\Projects\Obsidian_Vault\.claude\worktrees\thirsty-dirac-c3a180" && python -m pytest tests/unit/summarization_engine/summarization/test_youtube_attribution.py -k "detector or lift or compose or redos or idempotent" -q
```
Expected: FAIL — `ImportError: cannot import name 'has_leading_attribution'`.

- [ ] **Minimal impl — part A** (detector/lifter + composer in `attribution.py`):
```python
import re
import unicodedata
from website.features.summarization_engine.summarization.common.text_guards import (
    split_sentences as _split_sentences,
)

# Wave 1B — ReDoS-safe anchored leading-attribution detector.
# Requires the WHOLE leading clause: optional "In this <fmt>, " frame +
# subject (1-4 capitalised-ish tokens OR a role phrase) + reporting verb +
# "that"/"how". Anchored at ^, literal prefixes, BOUNDED ranges (\w{1,40},
# \s{1,3}), NO nested quantifiers -> linear time on CPython's backtracking
# engine (Snyk ReDoS guidance). Only fires on a LEADING clause, so a thesis
# that merely *contains* "argues" elsewhere is untouched.
_REPORTING_VERBS = (
    "argues", "explains", "demonstrates", "reports", "suggests", "contends",
    "describes", "shows", "claims", "examines", "discusses", "covers",
)
_LEADING_ATTRIBUTION_RE = re.compile(
    r"^\s{0,3}"
    r"(?:in\s{1,3}this\s{1,3}\w{1,40}\s{0,3},\s{0,3})?"   # optional "In this <fmt>,"
    r"(?:the\s{1,3})?"                                      # optional leading "the"
    r"\w{1,40}(?:\s{1,3}\w{1,40}){0,3}"                    # subject: 1-4 tokens (bounded)
    r"\s{1,3}(?:" + "|".join(_REPORTING_VERBS) + r")"      # reporting verb
    r"\s{1,3}(?:that|how)\b",                               # complementiser
    re.IGNORECASE,
)


def _canon(text: str) -> str:
    """NFC + collapse whitespace (incl. NBSP) for stable anchored compare.
    UAX#15: NFC is idempotent, so canonicalising twice == once."""
    nfc = unicodedata.normalize("NFC", text or "")
    return re.sub(r"\s+", " ", nfc.replace(" ", " ")).strip()


def has_leading_attribution(thesis: str) -> bool:
    """True iff ``thesis`` opens with a full attribution clause."""
    return bool(_LEADING_ATTRIBUTION_RE.match(_canon(thesis)))


def lift_leading_attribution(thesis: str) -> str:
    """Return ``thesis`` as a finished lead sentence, preserving an existing
    leading attribution clause verbatim (just normalise whitespace + ensure a
    terminal period + leading capital). Used when the thesis is ALREADY
    attributed, so we never prepend a second clause (idempotency)."""
    cleaned = _canon(thesis)
    if not cleaned:
        return ""
    if cleaned[:1].islower():
        cleaned = cleaned[:1].upper() + cleaned[1:]
    if cleaned[-1] not in ".!?":
        cleaned = cleaned + "."
    return cleaned


def compose_lead_sentence(
    *,
    format_name: str,
    canonical_key: str,
    thesis: str,
    speakers: list[str],
    attribution_confidence: str,
) -> str:
    """Build the brief's first sentence — confidence-gated, format-verb-aware,
    idempotent. ``format_name`` is the human label for the frame ("commentary");
    ``canonical_key`` is the folded key for verb selection (Task 2)."""
    from website.features.summarization_engine.summarization.youtube.schema import (
        _primary_speaker,
        _first_sentence,
    )

    thesis_sentence = _first_sentence(thesis)
    if not thesis_sentence:
        # No thesis: agentless frame; never invent a speaker.
        return f"This {format_name} sets out its central topic."

    # IDEMPOTENCY: if the thesis already opens with an attribution clause, lift
    # it verbatim instead of prepending another (kills DOUBLING + makes f(f(x))==f(x)).
    if has_leading_attribution(thesis_sentence):
        return lift_leading_attribution(thesis_sentence)

    body = thesis_sentence.rstrip(".")
    verb_phrase = reporting_verb_phrase(canonical_key, attribution_confidence)
    speaker = _primary_speaker(speakers)  # "" when only placeholders/sentinel

    # M1 GATE: agented only when we have BOTH a real speaker AND an agented verb
    # for this format+confidence. Otherwise topic-fronted / agentless framing —
    # NEVER the literal "The speaker" (abstention: Rashkin 2023; Wen 2025).
    if verb_phrase and speaker:
        return f"In this {format_name}, {speaker} {verb_phrase} {body[:1].lower() + body[1:]}."
    # Agentless framings by intent:
    if attribution_confidence == "missing" or not speaker:
        return f"This {format_name} examines {body[:1].lower() + body[1:]}."
    # Have a speaker but format is agentless (interview/documentary/unknown):
    return f"In this {format_name}, {speaker} centers on {body[:1].lower() + body[1:]}."
```
**FLAG (capitalisation of `body`):** lower-casing only the first character (`body[:1].lower() + body[1:]`) preserves proper nouns inside the thesis (e.g. "DMT", "Jane Doe"), unlike the old `.lower()` which destroyed them. This is a small quality improvement riding along; if byte-identical legacy behaviour is required for the rebuild path, this is the one visible delta — call it out in the commit.

- [ ] **Minimal impl — part B** (wire into the schema composer). Replace schema.py:528-536 (quoted above) with a delegation, and thread the confidence kwarg. First, change the `_compose_structured_brief` signature (schema.py:518-527) to accept `attribution_confidence`:
```python
def _compose_structured_brief(
    *,
    format_name: str,
    thesis: str,
    speakers: list[str],
    entities: list[str],
    chapter_titles: list[str],
    demonstrations: list[str],
    closing_takeaway: str,
    attribution_confidence: str = "high",
) -> str:
    from website.features.summarization_engine.summarization.youtube.attribution import (
        canonical_format,
        compose_lead_sentence,
    )
    parts: list[str] = []
    parts.append(
        compose_lead_sentence(
            format_name=format_name,
            canonical_key=canonical_format(format_name),
            thesis=thesis,
            speakers=speakers,
            attribution_confidence=attribution_confidence,
        )
    )
```
(Delete the old `speaker = _primary_speaker(speakers) or "The speaker"` line and the `if thesis_sentence: … else: …` block; everything BELOW the lead sentence — the chapter/demo/entity/closing parts at schema.py:540-556 — stays unchanged, but note those still reference `speaker`. **Sub-step:** the entity sentence at schema.py:550 uses `speaker`; redefine it from `_primary_speaker` AFTER the lead sentence so the agentless lead doesn't force a bad subject downstream:)
```python
    # Below-lead sentences may still name a real speaker if one exists; they are
    # additive context, not the attribution claim, so a real name is fine here.
    speaker = _primary_speaker(speakers)
    titles = [t for t in (chapter_titles or []) if t and t.strip()][:3]
    if titles:
        parts.append(f"The {format_name} moves through {_join_series(titles)}.")
    demos = [d for d in (demonstrations or []) if d and d.strip()][:2]
    if demos:
        parts.append(f"It walks through {_join_series(demos)}.")
    entity_text = [e for e in (entities or []) if e and e.strip()][:3]
    if entity_text:
        subject = speaker or "the discussion"
        parts.append(f"Along the way {subject} references {_join_series(entity_text)}.")
    closing_sentence = _first_sentence(closing_takeaway)
    if closing_sentence:
        parts.append(f"The closing point is that {closing_sentence.lower().rstrip('.')}.")
    return _fit_parts_to_budget(parts)
```
**FLAG:** the old entity sentence used `speaker` unconditionally (could be `"The speaker"`); the new one falls back to `"the discussion"` to avoid re-introducing the fabricated subject in a secondary sentence. This is consistent with M1.

- [ ] **Minimal impl — part C** (pass confidence from the validator). In `_normalize_note_facing_fields` (schema.py:85-94) add the kwarg to the `_repair_brief_summary(...)` call:
```python
        self.brief_summary = _repair_brief_summary(
            brief=self.brief_summary,
            format_name=self.detailed_summary.format,
            thesis=self.detailed_summary.thesis,
            speakers=self.speakers,
            entities=self.entities_discussed,
            chapter_titles=[item.title for item in self.detailed_summary.chapters_or_segments],
            demonstrations=list(self.detailed_summary.demonstrations or []),
            closing_takeaway=self.detailed_summary.closing_takeaway,
            attribution_confidence=self.attribution_confidence,
        )
```
And `_repair_brief_summary` (schema.py:414-424 signature) gains `attribution_confidence: str = "high"` and forwards it to `_compose_structured_brief(...)` at its Path-5 call (schema.py:507-515):
```python
    return _compose_structured_brief(
        format_name=format_name,
        thesis=thesis,
        speakers=speakers,
        entities=entities,
        chapter_titles=chapter_titles,
        demonstrations=demonstrations,
        closing_takeaway=closing_takeaway,
        attribution_confidence=attribution_confidence,
    )
```

- [ ] **Run to PASS (attribution unit + property):**
```
cd "C:\Users\LENOVO\Documents\Claude_Code\Projects\Obsidian_Vault\.claude\worktrees\thirsty-dirac-c3a180" && python -m pytest tests/unit/summarization_engine/summarization/test_youtube_attribution.py -q
```
Expected: all attribution tests pass (Tasks 1-4).

- [ ] **Write the end-to-end schema regression** (REAL code) — append to `test_youtube_schema.py` to prove the doubling/gate fix lands in the actual `brief_summary` (the surface that reaches meta.json/RAG), reproducing the two repro cases through the real validator:
```python
def test_youtube_brief_no_double_attribution_when_thesis_pre_attributed():
    payload = YouTubeStructuredPayload(
        mini_title="Inflation Structural Debate",
        brief_summary="too short",  # forces the rebuild (Path 5) composer
        tags=["inflation", "macro", "economics", "rates", "fed", "policy", "markets"],
        speakers=["the host"],  # placeholder -> sanitized to sentinel -> missing
        entities_discussed=[],
        detailed_summary={
            "thesis": "The host argues that inflation is structural, not transitory.",
            "format": "commentary",
            "chapters_or_segments": [
                {"timestamp": "", "title": "Setup", "bullets": ["A claim about prices."]},
            ],
            "demonstrations": [],
            "closing_takeaway": "Rates will stay high.",
        },
    )
    low = payload.brief_summary.lower()
    assert low.count("argues that") <= 1, f"doubled attribution reached brief: {payload.brief_summary!r}"
    assert "the speaker argues" not in low  # no fabricated subject


def test_youtube_brief_missing_confidence_uses_agentless_framing():
    payload = YouTubeStructuredPayload(
        mini_title="Untold Story Archival",
        brief_summary="too short",
        tags=["history", "archive", "story", "war", "people", "places", "events"],
        speakers=["The speaker"],  # sentinel -> attribution_confidence == "missing"
        entities_discussed=[],
        detailed_summary={
            "thesis": "An untold story is traced through archival footage.",
            "format": "other",  # classifier may upgrade; either way agentless
            "chapters_or_segments": [
                {"timestamp": "", "title": "Seg 1", "bullets": ["A grounded claim."]},
            ],
            "demonstrations": [],
            "closing_takeaway": "The investigation continues.",
        },
    )
    assert payload.attribution_confidence == "missing"
    low = payload.brief_summary.lower()
    assert "the speaker" not in low, f"fabricated subject in brief: {payload.brief_summary!r}"
    assert "argues that" not in low
    assert payload.brief_summary.endswith((".", "!", "?"))
```

- [ ] **Run to PASS (schema end-to-end):**
```
cd "C:\Users\LENOVO\Documents\Claude_Code\Projects\Obsidian_Vault\.claude\worktrees\thirsty-dirac-c3a180" && python -m pytest tests/unit/summarization_engine/summarization/test_youtube_schema.py -q
```
Expected: all pass (2 existing + 2 new). The two existing tests still pass: `test_youtube_payload_repairs_brief_and_adds_format_tag` supplies real speakers (→ agented `commentary` lead, "argues that" still valid) and `test_youtube_payload_upgrades_other_format_and_preserves_speaker_sentence` asserts only format!="other" + no dangling tail + length, all preserved.

- [ ] **Commit:**
```
git commit -m "fix: idempotent confidence-gated youtube brief composer"
```

### Self-review
- [ ] DOUBLING: anchored detector + lift path proven by `test_compose_does_not_double_*` AND the end-to-end `test_youtube_brief_no_double_attribution_*`.
- [ ] IDEMPOTENCY `f(f(x))==f(x)`: deterministic corpus loop green; NFC canonicalisation makes the compare stable across case/punct/NBSP.
- [ ] FABRICATED SUBJECT: `"The speaker"` removed from `_compose_structured_brief`; agentless framing on `missing`; secondary entity sentence falls back to "the discussion".
- [ ] FIXED VERB: lead verb is `reporting_verb_phrase(canonical_format(format), confidence)`; "argues" only for `commentary@high`.
- [ ] ReDoS: pattern anchored, literal prefixes, bounded ranges, no nested quantifiers; adversarial test < 0.5s.
- [ ] Composition seam, NOT render-time: the fix mutates `brief_summary` inside the Pydantic validator, so the corrected string is what persists to `meta.json` / RAG (the spec's hard requirement). Verified: `brief_summary` is the persisted field; no later render re-derives it from `thesis`.
- [ ] No protected knob touched (pure string ops, no model call, no infra). Confirmed against CLAUDE.md guardrails.

---

## Task 5 — Fix the detector-override desync (resolver consolidation)

`youtube/summarizer.py:171-189` overrides `speakers` with the positive-evidence detector's result but leaves `attribution_confidence` stale. After Task 1 there is one helper to recompute it. Route the override through `reconcile_attribution_confidence` so a freshly-proven real speaker also upgrades confidence (and the Task-4 gate then produces an agented lead, not an agentless one).

**Files:**
- Modify: `website/features/summarization_engine/summarization/youtube/summarizer.py:183-189` (the `if detected and detected != ["The speaker"]:` block)
- Test: `tests/unit/summarization_engine/summarization/test_youtube_summarizer.py` (extend)

Current code to replace — summarizer.py:183-189, quoted verbatim:
```python
            if detected and detected != ["The speaker"]:
                if result.metadata is not None and result.metadata.structured_payload:
                    sp = dict(result.metadata.structured_payload)
                    sp["speakers"] = detected
                    result.metadata.structured_payload = sp
        except Exception as exc:  # noqa: BLE001
            _log.debug("speaker_detector failed (non-fatal): %s", exc)
```

### Steps

- [ ] **Write failing test** (REAL code) — append to `test_youtube_summarizer.py`. Drive the same stubbed pipeline but seed a `structured_payload` whose `attribution_confidence` is stale `"missing"` while the detector proves a real speaker, and assert the override reconciles confidence to `"high"`:
```python
@pytest.mark.asyncio
async def test_speaker_detector_override_reconciles_attribution_confidence(
    mock_gemini_client, monkeypatch
):
    from website.features.summarization_engine.summarization.common import (
        dense_verify, dense_verify_runner, structured,
    )
    from website.features.summarization_engine.summarization.youtube import summarizer as yt_mod

    async def _fake_run_dense_verify(*, client, ingest, precomputed_dense=None, cache=None):  # noqa: ARG001
        return dense_verify.DenseVerifyResult(
            dense_text="dense", missing_facts=[], stance=None, archetype=None,
            format_label=None, core_argument="x", closing_hook="y",
        )
    monkeypatch.setattr(yt_mod, "run_dense_verify", _fake_run_dense_verify)
    dense_verify_runner._DV_CACHE.clear()

    # Detector proves a real two-signal speaker.
    monkeypatch.setattr(
        yt_mod, "detect_youtube_speakers",
        lambda *, title, uploader, transcript: ["Lex Fridman"],
        raising=False,
    )

    async def fake_extract(self, ingest, text, **kwargs):
        from website.features.summarization_engine.core.models import (
            SummaryMetadata, SummaryResult, DetailedSummarySection,
        )
        md = SummaryMetadata(
            source_type=SourceType.YOUTUBE, url=ingest.url,
            extraction_confidence="high", confidence_reason="ok",
            total_tokens_used=0, total_latency_ms=0,
        )
        # Stale confidence: LLM said "missing" with the sentinel speaker.
        md.structured_payload = {
            "speakers": ["The speaker"],
            "attribution_confidence": "missing",
            "detailed_summary": {"format": "commentary"},
        }
        return SummaryResult(
            mini_title="t", brief_summary="b",
            tags=["a", "b", "c", "d", "e", "f", "g"],
            detailed_summary=[DetailedSummarySection(heading="H", bullets=["b"])],
            metadata=md,
        )

    monkeypatch.setattr(structured.StructuredExtractor, "extract", fake_extract)
    # Keep __init__ real-ish: reuse the production constructor.
    ingest = IngestResult(
        source_type=SourceType.YOUTUBE,
        url="https://youtube.com/watch?v=x",
        original_url="https://youtube.com/watch?v=x",
        raw_text="... Lex Fridman ... Lex Fridman ... Lex Fridman ...",
        extraction_confidence="high", confidence_reason="ok",
        fetched_at="2026-04-21T00:00:00+00:00",
        metadata={"title": "Conversation with Lex Fridman", "uploader": "Lex Fridman"},
    )
    summarizer = YouTubeSummarizer(mock_gemini_client, {})
    result = await summarizer.summarize(ingest)
    sp = result.metadata.structured_payload
    assert sp["speakers"] == ["Lex Fridman"]
    assert sp["attribution_confidence"] == "high", (
        "detector override must reconcile confidence, not leave it stale 'missing'"
    )
```

- [ ] **Run to FAIL:**
```
cd "C:\Users\LENOVO\Documents\Claude_Code\Projects\Obsidian_Vault\.claude\worktrees\thirsty-dirac-c3a180" && python -m pytest tests/unit/summarization_engine/summarization/test_youtube_summarizer.py::test_speaker_detector_override_reconciles_attribution_confidence -q
```
Expected: FAIL — `assert 'missing' == 'high'` (override leaves confidence stale).

- [ ] **Minimal impl** (REAL code) — replace summarizer.py:183-189 with:
```python
            if detected and detected != ["The speaker"]:
                if result.metadata is not None and result.metadata.structured_payload:
                    from website.features.summarization_engine.summarization.youtube.attribution import (
                        reconcile_attribution_confidence,
                    )
                    sp = dict(result.metadata.structured_payload)
                    sp["speakers"] = detected
                    # Wave 1B M5: a freshly-proven speaker must also refresh
                    # confidence (single source of truth) — else the composer
                    # mis-gates to agentless on a real attribution.
                    sp["attribution_confidence"] = reconcile_attribution_confidence(detected)
                    result.metadata.structured_payload = sp
        except Exception as exc:  # noqa: BLE001
            _log.debug("speaker_detector failed (non-fatal): %s", exc)
```

- [ ] **Run to PASS:**
```
cd "C:\Users\LENOVO\Documents\Claude_Code\Projects\Obsidian_Vault\.claude\worktrees\thirsty-dirac-c3a180" && python -m pytest tests/unit/summarization_engine/summarization/test_youtube_summarizer.py -q
```
Expected: all pass (existing test + the new override-reconcile test).

- [ ] **Commit:**
```
git commit -m "fix: detector override reconciles youtube confidence"
```

### Self-review
- [ ] Resolver consolidation: all three resolvers now agree on confidence via `reconcile_attribution_confidence` — `_sanitize_speakers` (Task 1), the detector override (here), and `_apply_identifier_hints` (structured.py:702-742) writes a *pre-validation* hint that the validator re-reconciles, so the final value is always the helper's. Verified no fourth writer exists (grep `attribution_confidence` → schema.py:72/142(now via helper)/.., structured.py:734/736/741, summarizer here).
- [ ] The override writes into `result.metadata.structured_payload` (a plain dict on the SummaryResult), NOT re-running the Pydantic validator — so reconciling here is REQUIRED (the validator won't run again on this dict). Confirmed: `structured_payload` is set from `sp = dict(...)` with no re-validation downstream in `summarize`.
- [ ] Detector returning `["The speaker"]` (nothing proven) is excluded by the existing `!= ["The speaker"]` guard, so confidence is never spuriously upgraded.

---

## Task 6 — Final batch lint + full summarization-suite gate

Per repo convention (batch ruff at end of plan), one lint pass over the touched files + the broader summarization unit suite to confirm no import/regression fallout.

**Files:** none (verification only)

### Steps

- [ ] **Ruff (only the files this plan touched):**
```
cd "C:\Users\LENOVO\Documents\Claude_Code\Projects\Obsidian_Vault\.claude\worktrees\thirsty-dirac-c3a180" && python -m ruff check website/features/summarization_engine/summarization/youtube/attribution.py website/features/summarization_engine/summarization/youtube/schema.py website/features/summarization_engine/summarization/youtube/summarizer.py tests/unit/summarization_engine/summarization/test_youtube_attribution.py tests/unit/summarization_engine/summarization/test_youtube_schema.py tests/unit/summarization_engine/summarization/test_youtube_summarizer.py
```
Expected: no errors (fix any import-order / unused-import findings in place; note `attribution.py` does a couple of intentional in-function imports to break the schema cycle — those are local, not module-level, so no F401).

- [ ] **Summarization-engine unit suite (regression gate):**
```
cd "C:\Users\LENOVO\Documents\Claude_Code\Projects\Obsidian_Vault\.claude\worktrees\thirsty-dirac-c3a180" && python -m pytest tests/unit/summarization_engine/ -q -m "not live"
```
Expected: all pass. Pay attention to any other test that constructs a `YouTubeStructuredPayload` with a known brief and asserts exact text — the lead-sentence rewording (proper-noun-preserving first-char lowercasing + format-conditional verb) can shift such strings. If one regresses, it is asserting the OLD doubled/over-attributed behaviour; update the expectation to the corrected lead and note it in the commit (do NOT weaken the assertion).

- [ ] **Commit (only if ruff applied fixes):**
```
git commit -m "chore: lint wave1b youtube attribution"
```

### Self-review
- [ ] No protected knob touched (pure deterministic string ops; no Gemini call on any new/changed path; no infra/timeout/worker change). Confirmed against CLAUDE.md "Critical Infra Decision Guardrails".
- [ ] No new runtime dependency added; `unicodedata` + `re` are stdlib, droplet-safe.
- [ ] Hypothesis NOT added (FLAG-H, open decision #1) — idempotency proven by deterministic corpus loop.
- [ ] All seam edits live under `website/features/summarization_engine/` (D3-approved); the new module is a pure leaf.

---

## Residual risk & operator decisions (surface before merge)

1. **Hypothesis deferral (FLAG-H).** The research recommended a Hypothesis property test for `f(f(x))==f(x)`. Hypothesis is not installed and adding a test dependency is a test-strategy decision needing approval + a `requirements-dev.txt` bump + CI install. This plan ships the property as a deterministic corpus loop (same law, no `@given`). Confirm whether to add Hypothesis in a follow-up.
2. **Entity-coerced speaker confidence (Task 1, part B FLAG).** A speaker surfaced from `entities_discussed` now reconciles to `"high"` (it passed `_looks_like_named_human`), where the old inline code hardcoded `"missing"`. This is more correct (it is a real named human) but is a behaviour change to the gate. Confirm `"high"` is acceptable, or request the conservative `"missing"` (1-line branch provided).
3. **Format-Literal alignment deferred (Task 2, open decision #3).** The clean fix is to make the classifier emit only in-Literal labels so `detailed_summary.format` never holds `documentary`/`explainer`. That touches `_yt_reserved` tagging + eval label expectations, so Wave 1B uses the read-only `canonical_format` fold instead. Confirm the fold is the intended scope for now.
4. **Eval comparability.** Removing doubled/over-attributed lead sentences will (correctly) shift YouTube faithfulness/quality scores. This is part of the Wave-0 eval version bump already flagged; gate behind the frozen-set CI bootstrap so no axis regresses unexpectedly.
5. **Proper-noun preservation delta (Task 4 FLAG).** The new lead lower-cases only the first character of the thesis body (vs the old `.lower()`), preserving "DMT"/"Jane Doe". Benign quality improvement; noted so a byte-diff reviewer expects it.
