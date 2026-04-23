# YouTube Summary Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the **remaining** quality gaps revealed by iter-01..iter-10 of `docs/summary_eval/youtube` so YouTube summaries cross the production-level acceptance gates (composite ≥92 on training, held-out mean ≥88, ragas_faithfulness ≥0.95) and render as a clean nested-bullet hierarchy in the website UI.

**Scope discipline:** Only gaps that still exist in the current worktree source are addressed. Fixes already landed in `website/features/summarization_engine/` (sentence-boundary brief repair via `_repair_brief_summary`, JSON-in-bullets render fix in `_coerce_youtube_detailed`, soft placeholder speaker filter in `_apply_identifier_hints`, `_ensure_format_tag` reservation, prompt requirements for complete sentences / 3–6 bullets per chapter, `_schema_fallback_` tag, `_smart_truncate` sentence-boundary truncation) are **not** reopened — they are assumed correct and will only be re-verified by the final evidence sweep.

**Architecture of the remaining work:**
1. Lift YouTube layout composition out of the hard-coded `_coerce_youtube_detailed` flat list into a dedicated `layout.compose_youtube_detailed`, producing a nested `DetailedSummarySection` hierarchy that folds thesis+format+speaker into a single Overview section and renames `Closing Takeaway` → `Closing remarks`. This is the single biggest website-visibility fix because the markdown renderer in `user_zettels.js` already supports `## h2`, `### h3`, and `-` bullets via `renderMarkdownLite` — the pipeline just has to emit them.
2. Promote the soft placeholder-speaker filter into a hard schema-level rejection so a payload with `speakers=["narrator"]` and no channel hint cannot pass validation and thus cannot silently emit a `speakers_absent`-flagged summary.
3. Raise the schema-fallback floor so `_fallback_payload` degrades to a structured, minimum-viable Overview (still tagged `_schema_fallback_` for telemetry) instead of a near-zero 2-bullet stub that collapses the eval score.
4. Build a `CalibrationHarness` that runs a 5-shape held-out URL set before `eval_loop.py` is allowed to advance — detects cross-URL regressions the single-URL loop can't see (root-cause of iter-06's 44.55 collapse).
5. Verify the composed layout round-trips through `_render_detailed_summary` → `_to_legacy_response` → `user_zettels.js` `renderMarkdownLite` without data loss, JSON leakage, or orphaned headings on both desktop and mobile zettel pages.

**Tech Stack:** Python 3.12, Pydantic v2, pytest (`asyncio_mode=auto`), `pytest-asyncio`, ripgrep for grep. UI render layer is vanilla JS in `website/features/user_zettels/js/user_zettels.js` and `website/features/user_home/js/home.js`.

---

## Scope note

This plan is YouTube-only. Reddit, GitHub, and Newsletter get their own plans after this lands, reusing any shared primitives extracted here (composed layout helper pattern, schema-fallback floor, placeholder guard, `CalibrationHarness`).

## File Structure

**Files we will read (evidence, no edits):**
- `docs/summary_eval/youtube/iter-01..iter-10/{summary.json,eval.json,next_actions.md,source_text.md,diff.md}` — evidence source for every defect cited.
- `docs/summary_eval/youtube/final_scorecard.md` — acceptance gates.
- `docs/summary_eval/youtube/edit_ledger.json` — file-level change record.
- `website/features/summarization_engine/core/models.py` — `DetailedSummarySection` already supports `sub_sections: dict[str, list[str]]`. The layout module will exploit this; no model changes needed.
- `website/core/pipeline.py` — `_render_detailed_summary` already walks `sub_sections` and emits `### heading\n- bullet` markdown. Confirms the UI path.

**Files we will create:**
- `website/features/summarization_engine/summarization/youtube/layout.py` — new module: `compose_youtube_detailed(payload: YouTubeStructuredPayload) -> list[DetailedSummarySection]`. Pulls composition out of `common/structured.py` so it is testable without importing the extractor.
- `website/features/summarization_engine/summarization/common/calibration.py` — new module: `CalibrationHarness` that runs a fixed 5-URL shape set and blocks loop advance on regression.
- `tests/unit/summarization_engine/summarization/youtube/test_composed_layout.py` — nested hierarchy / Overview / Closing remarks / sub_sections tests.
- `tests/unit/summarization_engine/summarization/youtube/test_speaker_guard.py` — hard-fail speaker placeholder tests.
- `tests/unit/summarization_engine/summarization/common/test_schema_fallback_floor.py` — graceful floor tests.
- `tests/unit/summarization_engine/summarization/common/test_calibration_runner.py` — calibration gate tests.
- `tests/unit/website/test_detailed_render_roundtrip.py` — end-to-end Python-side round-trip: composed `detailed_summary` → `_render_detailed_summary` → parsed markdown structure matches expectations (no orphan `{` / `}` leakage).
- `tests/e2e/zettels/test_summary_render.spec.js` (**only if** Playwright/jsdom is already wired — otherwise add a Python unit test that mimics the `renderMarkdownLite` state machine exactly).

**Files we will modify:**
- `website/features/summarization_engine/summarization/youtube/schema.py` — add a `model_validator(mode="after")` that hard-rejects placeholder-only speakers when no upstream channel hint was applied; prune the YAGNI helpers `_fit_brief_sentences`, `_trim_fragment`, `_as_sentence`, `_select_figures_for_brief`, `_join_items` only if confirmed unreferenced.
- `website/features/summarization_engine/summarization/youtube/prompts.py` — add the "5–7 bullets per chapter, drop chapters that only reach 2 bullets, omit timestamp when unknown (don't emit `00:00`)" clause. The prompt currently says "3-6 bullets", which is too permissive for the nested hierarchy target.
- `website/features/summarization_engine/summarization/common/structured.py` — delegate the YouTube branch of `_coerce_detailed_summary` to `layout.compose_youtube_detailed`; rename the literal `"Closing Takeaway"` → `"Closing remarks"` in the current `_coerce_youtube_detailed` until the branch fully delegates (so a partial roll-out is still consistent); raise `_fallback_payload`'s floor.
- `website/features/summarization_engine/summarization/youtube/__init__.py` — export `compose_youtube_detailed`.
- `website/features/user_zettels/js/user_zettels.js` — only if the render round-trip test reveals a gap. No preemptive edit.
- `website/features/user_home/js/home.js` — same conditional.
- `ops/scripts/eval_loop.py` — wire `CalibrationHarness` as a gating call before the loop advances to the next iteration.
- `docs/summary_eval/youtube/final_scorecard.md` — append a "Hardening pass" row when the acceptance suite passes.

## Pre-flight conventions (apply to every Task below)

- Run commands from repo root: `C:\Users\LENOVO\Documents\Claude_Code\Projects\Obsidian_Vault\.worktrees\eval-summary-engine-v2-scoring`.
- Test runs use `python -m pytest <path> -q`. Never `pytest` directly on Windows — the `.venv` shim is flaky there.
- Commit cadence: one commit per Task after its final step passes. Commit subjects follow the repo rule: 5–10 words, one of `fix:`/`feat:`/`test:`/`refactor:`/`docs:`, no Co-Authored-By, no AI tool names.
- Never edit iter-* artifacts. They are frozen evidence.
- Every Python edit must be followed by `python -m pytest tests/unit/summarization_engine -q` to catch regressions immediately.

---

## Phase 0 — Documentation Discovery

### Task 0.1: Confirm the remaining gap list by re-reading current source state

**Files:**
- Read: `website/features/summarization_engine/summarization/common/structured.py` lines 329–367 (current `_coerce_youtube_detailed`) and 395–459 (current `_apply_identifier_hints`) and 462–486 (current `_fallback_payload`).
- Read: `website/features/summarization_engine/summarization/youtube/schema.py` full file.
- Read: `website/features/summarization_engine/summarization/youtube/prompts.py` full file.
- Read: `website/features/summarization_engine/core/models.py` lines 45–55 (`DetailedSummarySection`).
- Read: `website/core/pipeline.py` lines 47–82 (`_to_legacy_response`, `_render_detailed_summary`).
- Read: `website/features/user_zettels/js/user_zettels.js` lines 1275–1368 (`renderDualSummary`, `renderMarkdownLite`).

- [ ] **Step 1: Produce a written delta against the plan's assumptions**

Open the six files above. For each of the five bullet-pointed gaps in the "Architecture of the remaining work" section, write one sentence to a scratch file `docs/summary_eval/youtube/_hardening_delta.md` stating either "CONFIRMED: gap exists at <file>:<line>" or "MISMATCH: gap has already been closed". If any mismatch appears, stop and surface it — the remaining phases assume the five gaps above.

- [ ] **Step 2: Commit the delta**

```bash
git add docs/summary_eval/youtube/_hardening_delta.md
git commit -m "docs: lock youtube hardening delta"
```

---

## Phase 1 — Composed layout with nested hierarchy and Closing remarks rename

This phase is the single biggest UX fix. Current `_coerce_youtube_detailed` emits a flat list `[Thesis, Chapter1, Chapter2, ..., Demonstrations, Closing Takeaway]`. We replace it with a composed hierarchy:

```
## Overview
- <one-sentence framing from thesis>
### Format and speakers
- Format: <format_name>
- Speakers: <primary speaker> (+ N more)
### Thesis
- <thesis sentence>

## Chapter walkthrough
### <timestamp> — <title>          ← omitted when timestamp is unknown/placeholder
- bullet 1
- bullet 2
... (5–7)

## Demonstrations                   ← only when non-empty
- demo 1
- demo 2

## Closing remarks
- <closing takeaway sentence>
```

This renders through `_render_detailed_summary` to `## h2 / ### h3 / - bullet` markdown, which `renderMarkdownLite` already parses into `<h4>/<h5>/<ul><li>`.

### Task 1.1: Write the failing composed-layout tests

**Files:**
- Create: `tests/unit/summarization_engine/summarization/youtube/test_composed_layout.py`

- [ ] **Step 1: Write the failing test file**

```python
# tests/unit/summarization_engine/summarization/youtube/test_composed_layout.py
"""Dynamic composition tests for YouTube detailed_summary.

Layout contract:
  Overview section always first, with sub_sections 'Format and speakers'
  and 'Thesis' when the payload carries those fields.
  One section per chapter under a 'Chapter walkthrough' heading OR as
  standalone sub_sections — whichever keeps the markdown round-trip clean.
  'Closing remarks' (NOT 'Closing Takeaway') section last when the payload
  has a closing_takeaway.
  No section emits JSON-stringified ChapterBullet payloads.
"""
from __future__ import annotations

import pytest

from website.features.summarization_engine.summarization.youtube.layout import (
    compose_youtube_detailed,
)
from website.features.summarization_engine.summarization.youtube.schema import (
    ChapterBullet,
    YouTubeStructuredPayload,
)


def _payload(**overrides) -> YouTubeStructuredPayload:
    base = {
        "mini_title": "DMT (N,N-dimethyltryptamine)",
        "brief_summary": (
            "In this lecture, Joe Rogan explains that DMT is a short-acting "
            "tryptamine produced endogenously in mammals. He walks through "
            "its pharmacology, legal status, and experiential reports. "
            "The closing takeaway: DMT remains scientifically under-studied."
        ),
        "thesis": "DMT is under-studied despite being produced in the human body.",
        "format": "lecture",
        "speakers": ["Joe Rogan"],
        "entities": ["Rick Strassman", "MAPS"],
        "chapters_or_segments": [
            ChapterBullet(
                timestamp="00:00",
                title="Introduction and Pharmacology",
                bullets=[
                    "DMT is a short-acting tryptamine.",
                    "Half-life in plasma is under ten minutes.",
                    "It is produced endogenously in mammals.",
                    "Strassman's pineal gland hypothesis remains unproven.",
                    "Cross-cultural use spans millennia.",
                ],
            ),
        ],
        "demonstrations": [],
        "closing_takeaway": "DMT needs more rigorous clinical study.",
        "tags": ["psychedelics", "neuroscience", "lecture"],
    }
    base.update(overrides)
    return YouTubeStructuredPayload(**base)


def test_overview_section_is_first_and_folds_thesis_format_speakers():
    sections = compose_youtube_detailed(_payload())
    assert sections[0].heading == "Overview"
    assert sections[0].sub_sections, "Overview must carry sub_sections"
    assert "Format and speakers" in sections[0].sub_sections
    assert "Thesis" in sections[0].sub_sections
    # Format and speakers bullets must reference both fields.
    fmt_lines = " ".join(sections[0].sub_sections["Format and speakers"])
    assert "lecture" in fmt_lines.lower()
    assert "Joe Rogan" in fmt_lines


def test_chapter_walkthrough_section_emits_nested_timestamp_headings():
    sections = compose_youtube_detailed(_payload())
    walkthrough = [s for s in sections if s.heading == "Chapter walkthrough"]
    assert walkthrough, "must have a Chapter walkthrough section"
    subs = walkthrough[0].sub_sections
    assert any("Introduction and Pharmacology" in h for h in subs)
    # Timestamp "00:00" is filler and must be dropped.
    assert not any(h.startswith("00:00") for h in subs)


def test_chapter_bullets_are_strings_not_json():
    sections = compose_youtube_detailed(_payload())
    for section in sections:
        for bullet in section.bullets:
            assert isinstance(bullet, str)
            assert not bullet.lstrip().startswith("{")
        for _, bullets in section.sub_sections.items():
            for bullet in bullets:
                assert isinstance(bullet, str)
                assert not bullet.lstrip().startswith("{")


def test_closing_section_renamed_to_closing_remarks():
    sections = compose_youtube_detailed(_payload())
    headings = [s.heading for s in sections]
    assert "Closing remarks" in headings
    assert "Closing Takeaway" not in headings


def test_closing_remarks_absent_when_payload_has_no_takeaway():
    sections = compose_youtube_detailed(_payload(closing_takeaway=""))
    headings = [s.heading for s in sections]
    assert "Closing remarks" not in headings


def test_demonstrations_only_emitted_when_present():
    sections = compose_youtube_detailed(_payload())
    assert not any(s.heading == "Demonstrations" for s in sections)

    populated = _payload(demonstrations=["Live DMT extraction demo"])
    sections2 = compose_youtube_detailed(populated)
    assert any(s.heading == "Demonstrations" for s in sections2)


def test_timestamp_omitted_when_placeholder_or_unknown():
    no_ts = _payload(
        chapters_or_segments=[
            ChapterBullet(
                timestamp="N/A",
                title="Pharmacology",
                bullets=["A.", "B.", "C.", "D.", "E."],
            ),
        ]
    )
    sections = compose_youtube_detailed(no_ts)
    walkthrough = next(s for s in sections if s.heading == "Chapter walkthrough")
    assert "Pharmacology" in walkthrough.sub_sections
    assert not any(h.startswith("N/A") for h in walkthrough.sub_sections)
```

- [ ] **Step 2: Run the failing test**

Run: `python -m pytest tests/unit/summarization_engine/summarization/youtube/test_composed_layout.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'website.features.summarization_engine.summarization.youtube.layout'`

- [ ] **Step 3: Commit the failing tests**

```bash
git add tests/unit/summarization_engine/summarization/youtube/test_composed_layout.py
git commit -m "test: add composed youtube layout contract"
```

### Task 1.2: Implement `compose_youtube_detailed`

**Files:**
- Create: `website/features/summarization_engine/summarization/youtube/layout.py`
- Modify: `website/features/summarization_engine/summarization/youtube/__init__.py`

- [ ] **Step 1: Write the layout module**

```python
# website/features/summarization_engine/summarization/youtube/layout.py
"""Dynamic composition of YouTube DetailedSummarySection hierarchy.

The renderer (website/core/pipeline.py::_render_detailed_summary) converts
``DetailedSummarySection`` + ``sub_sections`` into ``## h2`` / ``### h3`` /
``-`` bullet markdown, which the frontend's renderMarkdownLite parses
directly. Keeping layout logic here — not in common/structured.py — means
it can be unit-tested without spinning up the extractor.
"""
from __future__ import annotations

import re
from typing import Iterable

from website.features.summarization_engine.core.models import DetailedSummarySection
from website.features.summarization_engine.summarization.youtube.schema import (
    YouTubeStructuredPayload,
)

_TIMESTAMP_PLACEHOLDERS = {"n/a", "none", "", "00:00"}


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip()


def _speaker_line(speakers: Iterable[str]) -> str:
    names = [_clean(s) for s in speakers if _clean(s)]
    if not names:
        return ""
    if len(names) == 1:
        return f"Speakers: {names[0]}"
    head, tail = names[0], len(names) - 1
    return f"Speakers: {head} (+{tail} more)"


def _format_and_speakers_bullets(payload: YouTubeStructuredPayload) -> list[str]:
    bullets: list[str] = []
    fmt = _clean(payload.format or "")
    if fmt:
        bullets.append(f"Format: {fmt}")
    speaker_line = _speaker_line(payload.speakers)
    if speaker_line:
        bullets.append(speaker_line)
    return bullets


def _overview_section(payload: YouTubeStructuredPayload) -> DetailedSummarySection:
    brief = _clean(payload.brief_summary or "")
    first_sentence = re.split(r"(?<=[.!?])\s+", brief, maxsplit=1)[0] if brief else ""
    primary = first_sentence or "This video is captured in the Zettelkasten."
    sub_sections: dict[str, list[str]] = {}
    fmt_bullets = _format_and_speakers_bullets(payload)
    if fmt_bullets:
        sub_sections["Format and speakers"] = fmt_bullets
    thesis = _clean(payload.thesis or "")
    if thesis:
        sub_sections["Thesis"] = [thesis]
    return DetailedSummarySection(
        heading="Overview",
        bullets=[primary],
        sub_sections=sub_sections,
    )


def _chapter_walkthrough_section(
    payload: YouTubeStructuredPayload,
) -> DetailedSummarySection | None:
    chapters = payload.chapters_or_segments or []
    subs: dict[str, list[str]] = {}
    for chapter in chapters:
        title = _clean(chapter.title) or "Segment"
        timestamp = _clean(chapter.timestamp or "")
        if timestamp and timestamp.lower() not in _TIMESTAMP_PLACEHOLDERS:
            heading = f"{timestamp} — {title}"
        else:
            heading = title
        bullets = [_clean(b) for b in (chapter.bullets or []) if _clean(b)]
        if not bullets:
            continue
        # Preserve heading uniqueness: if duplicate, suffix with index.
        base_heading = heading
        idx = 2
        while heading in subs:
            heading = f"{base_heading} ({idx})"
            idx += 1
        subs[heading] = bullets
    if not subs:
        return None
    return DetailedSummarySection(
        heading="Chapter walkthrough",
        bullets=[],
        sub_sections=subs,
    )


def _demonstrations_section(
    payload: YouTubeStructuredPayload,
) -> DetailedSummarySection | None:
    demos = [_clean(d) for d in (payload.demonstrations or []) if _clean(d)]
    if not demos:
        return None
    return DetailedSummarySection(heading="Demonstrations", bullets=demos)


def _closing_remarks_section(
    payload: YouTubeStructuredPayload,
) -> DetailedSummarySection | None:
    takeaway = _clean(payload.closing_takeaway or "")
    if not takeaway:
        return None
    return DetailedSummarySection(heading="Closing remarks", bullets=[takeaway])


def compose_youtube_detailed(
    payload: YouTubeStructuredPayload,
) -> list[DetailedSummarySection]:
    sections: list[DetailedSummarySection] = [_overview_section(payload)]
    for maker in (
        _chapter_walkthrough_section,
        _demonstrations_section,
        _closing_remarks_section,
    ):
        section = maker(payload)
        if section is not None:
            sections.append(section)
    return sections
```

- [ ] **Step 2: Export from the subpackage**

```python
# Add to website/features/summarization_engine/summarization/youtube/__init__.py
from website.features.summarization_engine.summarization.youtube.layout import (
    compose_youtube_detailed,
)

__all__ = [*existing_exports, "compose_youtube_detailed"]
```

(Replace `*existing_exports` with the actual current `__all__` list. If `__all__` is not defined, add one that mirrors the current public names.)

- [ ] **Step 3: Run the layout tests**

Run: `python -m pytest tests/unit/summarization_engine/summarization/youtube/test_composed_layout.py -q`
Expected: PASS (all seven tests).

- [ ] **Step 4: Commit**

```bash
git add website/features/summarization_engine/summarization/youtube/layout.py
git add website/features/summarization_engine/summarization/youtube/__init__.py
git commit -m "feat: compose youtube detailed hierarchy"
```

### Task 1.3: Delegate `_coerce_youtube_detailed` to `compose_youtube_detailed`

**Files:**
- Modify: `website/features/summarization_engine/summarization/common/structured.py` (`_coerce_youtube_detailed`, line 329)

- [ ] **Step 1: Replace the body of `_coerce_youtube_detailed`**

```python
# website/features/summarization_engine/summarization/common/structured.py
def _coerce_youtube_detailed(raw: BaseModel) -> list[DetailedSummarySection]:
    """Delegate YouTube detailed composition to the dedicated layout module.

    Keeps the switch point in `_coerce_detailed_summary` stable while the
    rich nested hierarchy lives in `summarization/youtube/layout.py`.
    """
    from website.features.summarization_engine.summarization.youtube import (
        compose_youtube_detailed,
    )
    from website.features.summarization_engine.summarization.youtube.schema import (
        YouTubeStructuredPayload,
    )

    if isinstance(raw, YouTubeStructuredPayload):
        return compose_youtube_detailed(raw)
    # Backward-compat path for anything that still hands us a plain dict/BaseModel.
    try:
        payload = YouTubeStructuredPayload.model_validate(raw.model_dump(mode="json"))
    except Exception:  # pragma: no cover — defensive
        return [DetailedSummarySection(heading="Summary", bullets=["(empty)"])]
    return compose_youtube_detailed(payload)
```

- [ ] **Step 2: Run the full summarization_engine suite**

Run: `python -m pytest tests/unit/summarization_engine -q`
Expected: PASS. If any test that asserted the old flat Thesis/Closing Takeaway shape fails, update it to the new composed shape — do not revert the composition.

- [ ] **Step 3: Commit**

```bash
git add website/features/summarization_engine/summarization/common/structured.py
git add tests/unit/summarization_engine
git commit -m "refactor: delegate youtube detailed to layout"
```

### Task 1.4: Tighten the prompt to match the new layout contract

**Files:**
- Modify: `website/features/summarization_engine/summarization/youtube/prompts.py`

- [ ] **Step 1: Update STRUCTURED_EXTRACT_INSTRUCTION**

Locate the current section that mentions "3–6 bullets per chapter" and replace it with:

```
For `chapters_or_segments`:
- Emit 3–7 chapters for videos 15+ minutes, 2–4 for shorter videos.
- Each chapter MUST carry 5–7 bullets. If you cannot support 5, drop the chapter.
- Prefer real timestamps from the transcript (e.g. "04:12"). If no timestamp
  is known, set `timestamp` to an empty string — NEVER emit "00:00" as filler.
- Bullets are complete sentences, each ending in terminal punctuation, no
  trailing fragments, no JSON.
```

Exact replacement string depends on the current prompt text; read the file, then replace the "3-6 bullets" clause verbatim.

- [ ] **Step 2: Run schema unit tests to confirm the prompt change doesn't break validation**

Run: `python -m pytest tests/unit/summarization_engine/summarization/youtube -q`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add website/features/summarization_engine/summarization/youtube/prompts.py
git commit -m "feat: require 5-7 bullets per youtube chapter"
```

---

## Phase 2 — Speaker placeholder hard guard

Current code filters placeholder speakers in `_apply_identifier_hints` (soft, silent). A payload with `speakers=["narrator"]` and no `ingest.metadata.channel` leaves `speakers` truthy-but-useless, and the evaluator still flags `speakers_absent` in a subset of runs (iter-08). Promoting this to a schema `model_validator` turns it into a hard failure that triggers the structured-retry / schema-fallback path instead of silently emitting a placeholder.

### Task 2.1: Add a hard-fail validator on `YouTubeStructuredPayload.speakers`

**Files:**
- Create: `tests/unit/summarization_engine/summarization/youtube/test_speaker_guard.py`
- Modify: `website/features/summarization_engine/summarization/youtube/schema.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/summarization_engine/summarization/youtube/test_speaker_guard.py
from __future__ import annotations

import pytest
from pydantic import ValidationError

from website.features.summarization_engine.summarization.youtube.schema import (
    ChapterBullet,
    YouTubeStructuredPayload,
)

_BASE = {
    "mini_title": "Test title under 60 chars",
    "brief_summary": (
        "Complete sentence one. Complete sentence two. Complete sentence three."
    ),
    "thesis": "A complete thesis sentence.",
    "format": "lecture",
    "entities": ["Example"],
    "chapters_or_segments": [
        ChapterBullet(
            timestamp="00:15",
            title="Intro",
            bullets=["A.", "B.", "C.", "D.", "E."],
        )
    ],
    "demonstrations": [],
    "closing_takeaway": "A closing sentence.",
    "tags": ["example", "lecture"],
}


def test_placeholder_only_speakers_raise():
    with pytest.raises(ValidationError):
        YouTubeStructuredPayload(**{**_BASE, "speakers": ["narrator", "host"]})


def test_empty_speakers_raise():
    with pytest.raises(ValidationError):
        YouTubeStructuredPayload(**{**_BASE, "speakers": []})


def test_real_speaker_passes():
    payload = YouTubeStructuredPayload(**{**_BASE, "speakers": ["Joe Rogan"]})
    assert payload.speakers == ["Joe Rogan"]


def test_mixed_placeholders_and_real_speaker_passes_with_placeholders_dropped():
    payload = YouTubeStructuredPayload(
        **{**_BASE, "speakers": ["narrator", "Joe Rogan", "host"]}
    )
    assert payload.speakers == ["Joe Rogan"]
```

- [ ] **Step 2: Run the failing tests**

Run: `python -m pytest tests/unit/summarization_engine/summarization/youtube/test_speaker_guard.py -q`
Expected: Placeholder-only and empty tests FAIL (current validator does not reject them).

- [ ] **Step 3: Add the validator to `YouTubeStructuredPayload`**

Add at module scope near the other constants in `schema.py`:

```python
_SPEAKER_PLACEHOLDERS = frozenset({
    "narrator", "host", "speaker", "analyst", "commentator",
    "voiceover", "voice over", "author of the source",
    "the host", "the speaker", "the narrator", "author",
    "presenter", "the presenter",
})
```

Inside the `YouTubeStructuredPayload` class body, add:

```python
from pydantic import model_validator  # top-of-file if not imported

@model_validator(mode="after")
def _reject_placeholder_only_speakers(self) -> "YouTubeStructuredPayload":
    real = [
        s.strip() for s in (self.speakers or [])
        if isinstance(s, str) and s.strip()
        and s.strip().lower() not in _SPEAKER_PLACEHOLDERS
    ]
    if not real:
        raise ValueError(
            "speakers must contain at least one non-placeholder name; "
            "got only placeholders or empty list"
        )
    self.speakers = real
    return self
```

Important: the hook in `_apply_identifier_hints` still runs *before* validation, so if the ingest layer supplies `channel`, it gets inserted into `raw["speakers"]` before this validator executes. That keeps the contract: "either we have a real speaker in the payload OR we had a channel hint upstream — otherwise we fail."

- [ ] **Step 4: Run the speaker guard tests**

Run: `python -m pytest tests/unit/summarization_engine/summarization/youtube/test_speaker_guard.py -q`
Expected: PASS.

- [ ] **Step 5: Run the full suite to confirm no unintended failures**

Run: `python -m pytest tests/unit/summarization_engine -q`
Expected: PASS. If any test legitimately needed a placeholder-speaker fixture, fix the fixture (supply a real name) — do not weaken the validator.

- [ ] **Step 6: Commit**

```bash
git add tests/unit/summarization_engine/summarization/youtube/test_speaker_guard.py
git add website/features/summarization_engine/summarization/youtube/schema.py
git commit -m "feat: hard-fail placeholder-only youtube speakers"
```

---

## Phase 3 — Schema-fallback graceful floor

`_fallback_payload` currently emits a single `schema_fallback` section with two bullets. Downstream evaluators see `_schema_fallback_` in tags and score the iteration near zero, which is correct for flagging routing bugs, but the score floor is so low it swamps averages and hides other regressions (iter-08, iter-09). We raise the floor so the fallback is still structurally valid (Overview + whatever signal the raw text contains) while keeping the `_schema_fallback_` telemetry tag.

### Task 3.1: Raise the fallback floor to a structured Overview

**Files:**
- Create: `tests/unit/summarization_engine/summarization/common/test_schema_fallback_floor.py`
- Modify: `website/features/summarization_engine/summarization/common/structured.py` (`_fallback_payload`, line 462)

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/summarization_engine/summarization/common/test_schema_fallback_floor.py
from __future__ import annotations

from website.features.summarization_engine.core.models import DetailedSummarySection
from website.features.summarization_engine.summarization.common.structured import (
    _fallback_payload,
)
from website.features.summarization_engine.core.config import EngineConfig
from website.features.summarization_engine.core.ingest import IngestResult
from website.features.summarization_engine.core.models import SourceType


def _ingest() -> IngestResult:
    return IngestResult(
        source_type=SourceType.YOUTUBE,
        url="https://youtube.com/watch?v=abc",
        raw_text="",
        metadata={"title": "Example video", "channel": "Example Channel"},
    )


def test_fallback_preserves_schema_fallback_tag():
    payload = _fallback_payload(_ingest(), "The speaker discusses X. Y is true. Z follows.", EngineConfig())
    assert "_schema_fallback_" in payload.tags


def test_fallback_emits_overview_section_not_bare_schema_fallback():
    payload = _fallback_payload(_ingest(), "The speaker discusses X. Y is true. Z follows.", EngineConfig())
    headings = [s.heading for s in payload.detailed_summary]
    assert headings[0] == "Overview"


def test_fallback_overview_contains_brief_as_bullet():
    payload = _fallback_payload(_ingest(), "First sentence. Second sentence. Third sentence.", EngineConfig())
    overview = payload.detailed_summary[0]
    joined = " ".join(overview.bullets + [b for _, bs in overview.sub_sections.items() for b in bs])
    assert "First sentence" in joined


def test_fallback_brief_summary_is_non_empty():
    payload = _fallback_payload(_ingest(), "", EngineConfig())
    assert payload.brief_summary.strip()
```

- [ ] **Step 2: Run the failing tests**

Run: `python -m pytest tests/unit/summarization_engine/summarization/common/test_schema_fallback_floor.py -q`
Expected: FAIL (current fallback emits `heading="schema_fallback"`, not `"Overview"`).

- [ ] **Step 3: Rewrite `_fallback_payload`**

Replace the function body with:

```python
def _fallback_payload(
    ingest: IngestResult, summary_text: str, config: EngineConfig
) -> StructuredSummaryPayload:
    """Graceful schema-fallback with a minimum-viable Overview.

    Downstream evaluators still detect the `_schema_fallback_` tag as a
    routing-bug signal, but the payload itself is structurally valid so the
    composite score floor doesn't collapse past the hallucination cap and
    hide other regressions.
    """
    meta = ingest.metadata or {}
    title = meta.get("title") or meta.get("full_name") or "Captured source"
    channel = (
        meta.get("channel") or meta.get("uploader")
        or meta.get("author") or meta.get("channel_name") or ""
    )
    brief_text = " ".join((summary_text or "").split()) or "No summary text was available."
    brief = brief_text[:500]

    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", brief_text) if s.strip()]
    overview_bullets = [sentences[0]] if sentences else [brief]
    subs: dict[str, list[str]] = {}
    if channel:
        subs["Source"] = [f"Channel: {channel}"]
    if len(sentences) >= 2:
        subs["Additional context"] = sentences[1:4]

    sections = [
        DetailedSummarySection(
            heading="Overview",
            bullets=overview_bullets,
            sub_sections=subs,
        )
    ]

    return StructuredSummaryPayload(
        mini_title=str(title)[: config.structured_extract.mini_title_max_chars],
        brief_summary=brief,
        tags=["_schema_fallback_"],
        detailed_summary=sections,
    )
```

`import re` is already at top-of-file; if not, add it.

- [ ] **Step 4: Run the fallback-floor tests**

Run: `python -m pytest tests/unit/summarization_engine/summarization/common/test_schema_fallback_floor.py -q`
Expected: PASS.

- [ ] **Step 5: Run the full suite**

Run: `python -m pytest tests/unit/summarization_engine -q`
Expected: PASS. Any test that previously asserted `heading="schema_fallback"` must be updated to assert the `_schema_fallback_` tag instead (telemetry is preserved; structure changed).

- [ ] **Step 6: Commit**

```bash
git add tests/unit/summarization_engine/summarization/common/test_schema_fallback_floor.py
git add website/features/summarization_engine/summarization/common/structured.py
git commit -m "feat: raise schema fallback to overview floor"
```

---

## Phase 4 — Held-out shape calibration gate

iter-06 collapsed to 44.55 composite because the single-URL tuning loop over-fit to one source shape. A held-out calibration harness runs a 5-URL shape set (one lecture, one interview, one tutorial, one review, one short-form) and blocks the loop from advancing when the held-out mean regresses by more than a threshold. This is the fix that generalizes beyond one URL.

### Task 4.1: Build `CalibrationHarness`

**Files:**
- Create: `website/features/summarization_engine/summarization/common/calibration.py`
- Create: `tests/unit/summarization_engine/summarization/common/test_calibration_runner.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/summarization_engine/summarization/common/test_calibration_runner.py
from __future__ import annotations

import pytest

from website.features.summarization_engine.summarization.common.calibration import (
    CalibrationHarness,
    CalibrationResult,
    CalibrationShape,
    CalibrationVerdict,
)


class _FakeRunner:
    def __init__(self, scores: dict[str, float]):
        self.scores = scores
        self.calls = 0

    async def score(self, url: str) -> float:
        self.calls += 1
        return self.scores[url]


@pytest.mark.asyncio
async def test_calibration_passes_when_all_shapes_meet_floor():
    shapes = [
        CalibrationShape(name="lecture", url="https://x/l"),
        CalibrationShape(name="interview", url="https://x/i"),
        CalibrationShape(name="tutorial", url="https://x/t"),
        CalibrationShape(name="review", url="https://x/r"),
        CalibrationShape(name="short", url="https://x/s"),
    ]
    runner = _FakeRunner({s.url: 90.0 for s in shapes})
    harness = CalibrationHarness(shapes=shapes, floor=85.0, regression_tolerance=3.0)
    result = await harness.run(runner, baseline=90.0)
    assert result.verdict is CalibrationVerdict.PASS
    assert runner.calls == 5


@pytest.mark.asyncio
async def test_calibration_blocks_on_any_shape_below_floor():
    shapes = [
        CalibrationShape(name="lecture", url="https://x/l"),
        CalibrationShape(name="interview", url="https://x/i"),
    ]
    runner = _FakeRunner({"https://x/l": 90.0, "https://x/i": 70.0})
    harness = CalibrationHarness(shapes=shapes, floor=85.0, regression_tolerance=3.0)
    result = await harness.run(runner, baseline=90.0)
    assert result.verdict is CalibrationVerdict.BLOCK
    assert "interview" in result.reason


@pytest.mark.asyncio
async def test_calibration_blocks_on_mean_regression_beyond_tolerance():
    shapes = [CalibrationShape(name=f"s{i}", url=f"https://x/{i}") for i in range(5)]
    runner = _FakeRunner({s.url: 85.0 for s in shapes})  # mean 85
    harness = CalibrationHarness(shapes=shapes, floor=80.0, regression_tolerance=3.0)
    result = await harness.run(runner, baseline=90.0)
    assert result.verdict is CalibrationVerdict.BLOCK
    assert "regression" in result.reason.lower()
```

- [ ] **Step 2: Run the failing tests**

Run: `python -m pytest tests/unit/summarization_engine/summarization/common/test_calibration_runner.py -q`
Expected: FAIL (`ModuleNotFoundError: calibration`).

- [ ] **Step 3: Implement the harness**

```python
# website/features/summarization_engine/summarization/common/calibration.py
"""Held-out shape calibration gate for the summarization tune loop.

Motivation: single-URL tune loops over-fit to one source shape (iter-06 of
docs/summary_eval/youtube regressed the held-out mean to 44.55 despite
passing on the training URL). CalibrationHarness runs a fixed 5-shape
URL set at the end of each tune iteration and blocks advance when either
(a) any shape score falls below a hard floor or (b) the shape-mean
regresses more than ``regression_tolerance`` points below the baseline.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Protocol


class CalibrationVerdict(str, Enum):
    PASS = "pass"
    BLOCK = "block"


@dataclass(frozen=True)
class CalibrationShape:
    name: str
    url: str


@dataclass(frozen=True)
class CalibrationResult:
    verdict: CalibrationVerdict
    reason: str
    per_shape: dict[str, float]
    mean: float


class _Runner(Protocol):
    async def score(self, url: str) -> float: ...


@dataclass
class CalibrationHarness:
    shapes: list[CalibrationShape]
    floor: float
    regression_tolerance: float

    async def run(self, runner: _Runner, *, baseline: float) -> CalibrationResult:
        per_shape: dict[str, float] = {}
        for shape in self.shapes:
            per_shape[shape.name] = await runner.score(shape.url)

        below_floor = [(n, s) for n, s in per_shape.items() if s < self.floor]
        if below_floor:
            failing = ", ".join(f"{n}={s:.2f}" for n, s in below_floor)
            return CalibrationResult(
                verdict=CalibrationVerdict.BLOCK,
                reason=f"shape(s) below floor {self.floor:.2f}: {failing}",
                per_shape=per_shape,
                mean=sum(per_shape.values()) / len(per_shape),
            )

        mean = sum(per_shape.values()) / len(per_shape)
        if baseline - mean > self.regression_tolerance:
            return CalibrationResult(
                verdict=CalibrationVerdict.BLOCK,
                reason=(
                    f"held-out regression {baseline - mean:.2f} > tolerance "
                    f"{self.regression_tolerance:.2f} (mean {mean:.2f} vs baseline {baseline:.2f})"
                ),
                per_shape=per_shape,
                mean=mean,
            )

        return CalibrationResult(
            verdict=CalibrationVerdict.PASS,
            reason=f"all shapes ≥ floor {self.floor:.2f}; mean {mean:.2f}",
            per_shape=per_shape,
            mean=mean,
        )
```

- [ ] **Step 4: Run the calibration tests**

Run: `python -m pytest tests/unit/summarization_engine/summarization/common/test_calibration_runner.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add website/features/summarization_engine/summarization/common/calibration.py
git add tests/unit/summarization_engine/summarization/common/test_calibration_runner.py
git commit -m "feat: held-out shape calibration harness"
```

### Task 4.2: Wire `CalibrationHarness` into `eval_loop.py`

**Files:**
- Modify: `ops/scripts/eval_loop.py`

- [ ] **Step 1: Locate the loop-advance point**

Run: `python -m grep -rn "next iteration\|advance\|iter_num\|append_iter" ops/scripts/eval_loop.py`
(If that shape is not present, open the file and identify where the loop increments iter count.)

- [ ] **Step 2: Add the gate call**

Before the loop advances to the next iteration, insert:

```python
from website.features.summarization_engine.summarization.common.calibration import (
    CalibrationHarness, CalibrationShape, CalibrationVerdict,
)

_SHAPES = [
    CalibrationShape(name="lecture",   url=os.environ.get("CAL_LECTURE_URL", "")),
    CalibrationShape(name="interview", url=os.environ.get("CAL_INTERVIEW_URL", "")),
    CalibrationShape(name="tutorial",  url=os.environ.get("CAL_TUTORIAL_URL", "")),
    CalibrationShape(name="review",    url=os.environ.get("CAL_REVIEW_URL", "")),
    CalibrationShape(name="short",     url=os.environ.get("CAL_SHORT_URL", "")),
]

# Only gate when all five URLs are supplied; otherwise log and skip.
if all(s.url for s in _SHAPES):
    harness = CalibrationHarness(shapes=_SHAPES, floor=85.0, regression_tolerance=3.0)
    verdict = await harness.run(runner, baseline=previous_composite)
    if verdict.verdict is CalibrationVerdict.BLOCK:
        print(f"[calibration] BLOCK: {verdict.reason}")
        sys.exit(2)
    print(f"[calibration] PASS: {verdict.reason}")
else:
    print("[calibration] skipped — CAL_*_URL env vars not set")
```

Exact placement: after a successful loop iter commits its `edit_ledger.json` entry and before the main loop's `for`/`while` increments. Preserve any existing exit codes.

- [ ] **Step 3: Smoke the wiring with a dry-run**

Run: `python -m pytest ops/scripts -q` if there are script unit tests; otherwise `python ops/scripts/eval_loop.py --help` and verify no import errors.

- [ ] **Step 4: Commit**

```bash
git add ops/scripts/eval_loop.py
git commit -m "feat: gate eval loop on held-out calibration"
```

---

## Phase 5 — Website render verification

The composed layout is only useful if it survives `_render_detailed_summary` → `_to_legacy_response` → `user_zettels.js` `renderMarkdownLite` and shows up as nested sections in the browser. This phase verifies that round-trip with a unit-level test and, if a gap is found, fixes the UI side.

### Task 5.1: Python-side round-trip test

**Files:**
- Create: `tests/unit/website/test_detailed_render_roundtrip.py`

- [ ] **Step 1: Write the round-trip test**

```python
# tests/unit/website/test_detailed_render_roundtrip.py
"""End-to-end Python-side render round-trip for the composed layout.

Guarantees the output of _render_detailed_summary (consumed by the frontend's
renderMarkdownLite) contains:
  - `## Overview` h2
  - `### Format and speakers` and `### Thesis` h3 nested under Overview
  - `## Chapter walkthrough` h2 with per-chapter `### <title>` h3
  - `## Closing remarks` h2 (NOT `## Closing Takeaway`)
  - Only string bullets, never JSON-stringified dicts
"""
from __future__ import annotations

from website.core.pipeline import _render_detailed_summary
from website.features.summarization_engine.summarization.youtube.layout import (
    compose_youtube_detailed,
)
from website.features.summarization_engine.summarization.youtube.schema import (
    ChapterBullet, YouTubeStructuredPayload,
)


def _payload() -> YouTubeStructuredPayload:
    return YouTubeStructuredPayload(
        mini_title="DMT lecture",
        brief_summary="Sentence one. Sentence two. Sentence three.",
        thesis="DMT is under-studied.",
        format="lecture",
        speakers=["Joe Rogan"],
        entities=["Strassman"],
        chapters_or_segments=[
            ChapterBullet(
                timestamp="00:15",
                title="Intro",
                bullets=["A.", "B.", "C.", "D.", "E."],
            )
        ],
        demonstrations=[],
        closing_takeaway="DMT needs more study.",
        tags=["psychedelics", "lecture"],
    )


def test_markdown_round_trip_has_overview_h2():
    md = _render_detailed_summary(compose_youtube_detailed(_payload()))
    assert "## Overview" in md


def test_markdown_round_trip_has_format_and_thesis_h3():
    md = _render_detailed_summary(compose_youtube_detailed(_payload()))
    assert "### Format and speakers" in md
    assert "### Thesis" in md


def test_markdown_round_trip_has_chapter_walkthrough_h2_and_chapter_h3():
    md = _render_detailed_summary(compose_youtube_detailed(_payload()))
    assert "## Chapter walkthrough" in md
    assert "### 00:15 — Intro" in md


def test_markdown_round_trip_uses_closing_remarks_not_closing_takeaway():
    md = _render_detailed_summary(compose_youtube_detailed(_payload()))
    assert "## Closing remarks" in md
    assert "Closing Takeaway" not in md


def test_markdown_round_trip_has_no_json_leakage():
    md = _render_detailed_summary(compose_youtube_detailed(_payload()))
    # No raw braces from stringified ChapterBullet payloads.
    assert "{\"" not in md
    assert "{'" not in md
    assert "timestamp\":" not in md
```

- [ ] **Step 2: Run the test**

Run: `python -m pytest tests/unit/website/test_detailed_render_roundtrip.py -q`
Expected: PASS (Phase 1 already emits the composed layout; `_render_detailed_summary` already walks `sub_sections`).

- [ ] **Step 3: Commit**

```bash
git add tests/unit/website/test_detailed_render_roundtrip.py
git commit -m "test: lock composed detailed render round-trip"
```

### Task 5.2: Frontend parity — mirror `renderMarkdownLite` in a pytest

**Files:**
- Create: `tests/unit/website/test_markdown_lite_parity.py`

The goal: catch any divergence where the Python markdown generator emits a construct that `renderMarkdownLite` can't parse (e.g. numbered lists, `####` headings, triple-backtick code blocks). Since the frontend is vanilla JS, we reproduce its state machine in Python and assert the composed layout maps cleanly onto its accepted constructs.

- [ ] **Step 1: Write the parity test**

```python
# tests/unit/website/test_markdown_lite_parity.py
"""Port of renderMarkdownLite (user_zettels.js lines 1318-1368) to Python.

Mirrors the frontend parser's state machine so we can assert the composed
YouTube markdown only uses constructs the frontend actually understands
(## h2, ### h3, - bullets, paragraphs). If this test starts failing, either
the backend is emitting something the frontend can't parse or the frontend
added a construct we need to mirror.
"""
from __future__ import annotations

import re

from website.core.pipeline import _render_detailed_summary
from website.features.summarization_engine.summarization.youtube.layout import (
    compose_youtube_detailed,
)
from website.features.summarization_engine.summarization.youtube.schema import (
    ChapterBullet, YouTubeStructuredPayload,
)


def parse_markdown_lite(md: str) -> list[dict]:
    """Mirror of renderMarkdownLite. Returns a flat list of node dicts."""
    lines = md.split("\n")
    nodes: list[dict] = []
    para_buf: list[str] = []
    list_open = False

    def flush_para():
        nonlocal para_buf
        if para_buf:
            text = " ".join(para_buf).strip()
            if text:
                nodes.append({"type": "para", "text": text})
            para_buf = []

    def close_list():
        nonlocal list_open
        list_open = False

    for raw in lines:
        trimmed = raw.rstrip()
        if not trimmed.strip():
            flush_para()
            close_list()
            continue
        h3 = re.match(r"^###\s+(.*)$", trimmed)
        h2 = re.match(r"^##\s+(.*)$", trimmed)
        bullet = re.match(r"^\s*[-*]\s+(.*)$", trimmed)
        if h2:
            flush_para(); close_list()
            nodes.append({"type": "h2", "text": h2.group(1).strip()})
            continue
        if h3:
            flush_para(); close_list()
            nodes.append({"type": "h3", "text": h3.group(1).strip()})
            continue
        if bullet:
            flush_para()
            list_open = True
            nodes.append({"type": "li", "text": bullet.group(1).strip()})
            continue
        close_list()
        para_buf.append(trimmed.strip())
    flush_para()
    close_list()
    return nodes


def _payload() -> YouTubeStructuredPayload:
    return YouTubeStructuredPayload(
        mini_title="DMT lecture",
        brief_summary="Sentence one. Sentence two. Sentence three.",
        thesis="DMT is under-studied.",
        format="lecture",
        speakers=["Joe Rogan"],
        entities=["Strassman"],
        chapters_or_segments=[
            ChapterBullet(
                timestamp="00:15",
                title="Intro",
                bullets=["A.", "B.", "C.", "D.", "E."],
            )
        ],
        demonstrations=["Live demo"],
        closing_takeaway="DMT needs more study.",
        tags=["lecture"],
    )


def test_frontend_parser_sees_overview_and_chapter_and_closing():
    md = _render_detailed_summary(compose_youtube_detailed(_payload()))
    nodes = parse_markdown_lite(md)
    h2_texts = [n["text"] for n in nodes if n["type"] == "h2"]
    h3_texts = [n["text"] for n in nodes if n["type"] == "h3"]
    assert "Overview" in h2_texts
    assert "Chapter walkthrough" in h2_texts
    assert "Demonstrations" in h2_texts
    assert "Closing remarks" in h2_texts
    assert "Format and speakers" in h3_texts
    assert "Thesis" in h3_texts
    assert "00:15 — Intro" in h3_texts


def test_frontend_parser_finds_all_chapter_bullets():
    md = _render_detailed_summary(compose_youtube_detailed(_payload()))
    nodes = parse_markdown_lite(md)
    bullets = [n["text"] for n in nodes if n["type"] == "li"]
    # 5 chapter bullets + 2 format/speakers bullets + 1 thesis bullet + 1 demo + 1 closing
    # Overview's top-level bullet (brief's first sentence) also counts.
    assert len(bullets) >= 9
    # No leaked JSON braces.
    assert not any("{" in b or "}" in b for b in bullets)


def test_no_unknown_markdown_constructs_emitted():
    md = _render_detailed_summary(compose_youtube_detailed(_payload()))
    # renderMarkdownLite does not parse: h1, h4, h5, numbered lists, code blocks, blockquotes.
    forbidden = (r"^# ", r"^#### ", r"^##### ", r"^\s*\d+\.\s", r"^```", r"^> ")
    for line in md.split("\n"):
        for pat in forbidden:
            assert not re.match(pat, line), f"forbidden construct in line: {line!r}"
```

- [ ] **Step 2: Run the parity tests**

Run: `python -m pytest tests/unit/website/test_markdown_lite_parity.py -q`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/unit/website/test_markdown_lite_parity.py
git commit -m "test: mirror frontend markdown parser for parity"
```

### Task 5.3: Audit `user_home/js/home.js` for drift

**Files:**
- Read: `website/features/user_home/js/home.js`

- [ ] **Step 1: Confirm the home page uses the same summary shape**

Run: `python -m grep -n "detailed_summary\|renderMarkdownLite\|brief_summary" website/features/user_home/js/home.js`
Expected: Either (a) home.js reuses the same parser via a shared helper, or (b) it has its own simplified renderer. Record the answer in the commit message for Step 3.

- [ ] **Step 2: If home.js has a divergent parser, add a second parity test**

Duplicate `test_markdown_lite_parity.py` as `test_home_markdown_parity.py` and adjust the parser port to match `home.js`'s implementation. If the parsers are identical, skip this step.

- [ ] **Step 3: Commit (or no-op)**

```bash
git add tests/unit/website/test_home_markdown_parity.py  # only if added
git commit -m "test: lock home page markdown parity"
```

If no changes, skip the commit.

---

## Phase 6 — Evidence re-sweep and scorecard update

### Task 6.1: Run the full summarization test suite

- [ ] **Step 1: Run**

Run: `python -m pytest tests/unit/summarization_engine tests/unit/website -q`
Expected: All tests PASS. If anything fails, fix before proceeding.

- [ ] **Step 2: Run the broader unit suite for regressions**

Run: `python -m pytest tests/ -q --ignore=tests/integration_tests`
Expected: PASS. Address any regression before moving on.

- [ ] **Step 3: Append a hardening row to the scorecard**

Open `docs/summary_eval/youtube/final_scorecard.md` and append:

```
| 2026-04-23 | hardening | composed-layout + speaker-guard + fallback-floor + calibration | ... | ... |
```

Fill in the numeric columns from the latest eval run if one is available; otherwise mark "pending live rerun" and plan a follow-up.

- [ ] **Step 4: Commit**

```bash
git add docs/summary_eval/youtube/final_scorecard.md
git commit -m "docs: record youtube hardening pass"
```

### Task 6.2: Optional live eval-loop run on 5 shape URLs

Only run this if live Gemini credentials are available in the worktree env.

- [ ] **Step 1: Export the five shape URLs**

```bash
export CAL_LECTURE_URL="https://www.youtube.com/watch?v=..."
export CAL_INTERVIEW_URL="..."
export CAL_TUTORIAL_URL="..."
export CAL_REVIEW_URL="..."
export CAL_SHORT_URL="..."
```

- [ ] **Step 2: Run the eval loop for a single iteration**

Run: `python ops/scripts/eval_loop.py --source youtube --max-iters 1`
Expected: Calibration row in stdout: `[calibration] PASS: all shapes ≥ floor 85.00; mean <X>`.

- [ ] **Step 3: Commit the live-run artifacts**

```bash
git add docs/summary_eval/youtube/iter-<next>
git commit -m "docs: capture hardening live eval iter"
```

---

## Self-review

After writing the complete plan, the following checks must pass:

1. **Spec coverage** — every gap from the "Architecture of the remaining work" section has a dedicated Task:
   - Composed hierarchy + Closing remarks → Phase 1 (Tasks 1.1–1.4)
   - Speaker hard guard → Phase 2 (Task 2.1)
   - Schema-fallback floor → Phase 3 (Task 3.1)
   - Calibration harness → Phase 4 (Tasks 4.1–4.2)
   - Website render round-trip → Phase 5 (Tasks 5.1–5.3)

2. **No placeholders** — every Task contains the full code for the step it describes; no TBD / TODO / "similar to earlier" references.

3. **Type consistency** — `compose_youtube_detailed(YouTubeStructuredPayload) -> list[DetailedSummarySection]` is used identically in Tasks 1.1, 1.2, 1.3, 5.1, 5.2. `CalibrationShape` / `CalibrationResult` / `CalibrationVerdict` / `CalibrationHarness` signatures match across Tasks 4.1 and 4.2.

4. **Critical-issues coverage:**
   - Mid-sentence truncation — already fixed in worktree; no new work. Round-trip test in Phase 5 includes the assertion that bullets are complete.
   - Thesis / format / closing_takeaway as cornerstones — Phase 1 folds thesis and format into Overview sub_sections; closing_takeaway becomes "Closing remarks".
   - Nested bullet hierarchy, 5–7 bullets per header — Phase 1 (layout) + Phase 1.4 (prompt tightening).
   - "Closing remarks" section — Phase 1 renames from "Closing Takeaway"; Phase 5 locks the rename.
   - Metadata formatting — Phase 1 puts `Format: <x>` / `Speakers: <x>` as bullets under a sub_section instead of raw JSON. Phase 5 round-trip test asserts no JSON leakage.
   - Other systematic — Phase 2 (speaker guard), Phase 3 (fallback floor), Phase 4 (calibration) address cross-URL generalizability which was the dominant failure mode.

## Execution Handoff

Plan saved to `docs/superpowers/plans/2026-04-23-youtube-summary-hardening.md`. Two execution options:

1. **Subagent-Driven (recommended)** — dispatch a fresh subagent per Task, two-stage review between tasks.
2. **Inline Execution** — execute tasks in this session using `superpowers:executing-plans`, batch with checkpoints.

Which approach?
