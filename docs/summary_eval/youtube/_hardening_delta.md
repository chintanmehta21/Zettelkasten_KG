# YouTube Hardening Delta — 2026-04-23

Status of the five gaps called out in the hardening plan. Each line is either CONFIRMED (gap still exists) or MISMATCH (gap already closed, plan needs revision).

## Gap 1 — Flat-list YouTube layout, no Overview, "Closing Takeaway" literal

CONFIRMED at website/features/summarization_engine/summarization/common/structured.py:364 — `_coerce_youtube_detailed` appends `DetailedSummarySection(heading="Closing Takeaway", bullets=[takeaway])` with no `sub_sections`; flat list structure with no composed Overview wrapper.

## Gap 2 — Soft placeholder-speaker filter, no schema hard-fail

CONFIRMED at website/features/summarization_engine/summarization/youtube/schema.py:49 — `YouTubeStructuredPayload` has `@model_validator(mode="after")` that normalizes fields but does NOT hard-reject placeholder-only speakers; `_apply_identifier_hints` in structured.py:433-458 filters placeholders softly with fallback to channel name, does NOT raise ValidationError.

## Gap 3 — Near-zero schema-fallback payload

CONFIRMED at website/features/summarization_engine/summarization/common/structured.py:477-485 — `_fallback_payload` emits a single `DetailedSummarySection(heading="schema_fallback", bullets=[...])` with two generic bullets; not a structured Overview section.

## Gap 4 — No held-out calibration gate

CONFIRMED — no file at website/features/summarization_engine/summarization/common/calibration.py; grep search found zero occurrences of "calibration" or "Calibration" in ops/scripts/eval_loop.py or anywhere in the codebase; eval_loop.py runs run_phase_a and run_phase_b with no calibration check between them.

## Gap 5 — Frontend render layer supports nested hierarchy

CONFIRMED — `DetailedSummarySection.sub_sections: dict[str, list[str]]` exists at website/features/summarization_engine/core/models.py:50; `_render_detailed_summary` walks `sub_sections` at website/core/pipeline.py:79-81 emitting `### {heading}` markdown; `renderMarkdownLite` parses `## h2 / ### h3 / -` bullets at website/features/user_zettels/js/user_zettels.js:1339-1348.

## Summary

All five gaps confirmed; plan is valid to execute.
