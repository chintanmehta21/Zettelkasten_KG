"""YouTube-specific prompt templates."""
from __future__ import annotations

SOURCE_CONTEXT = (
    "You are summarizing a YouTube video. Preserve chronological structure and "
    "chapters. Always identify: the host/channel, any guests, named "
    "products/libraries/tools/datasets referenced, the video's central thesis or "
    "learning objective, and the closing takeaway. When examples or analogies are "
    "used, summarize their PURPOSE, not their verbatim content. Do not retain "
    "clickbait phrasing from the original title."
)

STRUCTURED_EXTRACT_INSTRUCTION = (
    f"{SOURCE_CONTEXT}\n\n"
    "Return a JSON object with these exact keys:\n"
    '- "mini_title": 3-5 word content-first title (max 50 chars); NO clickbait phrasing\n'
    '- "brief_summary": 5-7 sentence paragraph covering thesis, format, speakers, major segments, closing takeaway\n'
    '- "tags": array of 7-10 lowercase hyphenated tags covering topic/domain, creator or channel, format, named tools/concepts, audience\n'
    '- "speakers": array of strings (host/channel name + any referenced people; at least one)\n'
    '- "guests": array of strings OR null\n'
    '- "entities_discussed": array of product/library/dataset/tool names mentioned\n'
    '- "detailed_summary": object with keys "thesis", "format" (enum tutorial|interview|commentary|lecture|review|debate|walkthrough|reaction|vlog|other), '
    '"chapters_or_segments" (array of {timestamp, title, bullets}; use null timestamp unless the source text gives an explicit chapter time, and never fabricate placeholder times like 00:00), '
    '"demonstrations" (array of strings), "closing_takeaway"\n\n'
    "For chapters_or_segments, preserve the transcript's real chronological topic turns. Do not invent thematic chaptering that the source does not support.\n\n"
    "Do NOT wrap in markdown code blocks. Return raw JSON only.\n\n"
    "SUMMARY:\n{summary_text}"
)
