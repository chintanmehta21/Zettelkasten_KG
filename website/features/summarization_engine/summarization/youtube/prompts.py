"""YouTube-specific prompt templates."""
from __future__ import annotations

SOURCE_CONTEXT = (
    "You are summarizing a YouTube video. Write in natural, complete sentences "
    "— never templated phrasing. Always identify the speaker or host BY NAME "
    "(e.g. 'Steve Jobs at Stanford', not 'the speaker'). Preserve chronological "
    "structure and chapter order. Identify the central thesis, the speaker and "
    "any guests, named products/libraries/tools/datasets referenced, and the "
    "closing takeaway. When examples or analogies are used, summarize their "
    "PURPOSE, not their verbatim content. Do not retain clickbait phrasing."
)

STRUCTURED_EXTRACT_INSTRUCTION = (
    f"{SOURCE_CONTEXT}\n\n"
    "Return a JSON object with these exact keys:\n"
    '- "mini_title": 3-5 word content-first title (max 50 chars); NO clickbait\n'
    '- "brief_summary": 3-5 COMPLETE sentences (<=450 chars). Natural prose. '
    'MUST name the primary speaker/host. State what the video is, who delivers '
    'it, the central thesis, and the closing takeaway. Every sentence must end '
    'properly — never trail off mid-clause.\n'
    '- "tags": 7-10 lowercase hyphenated tags (topic/domain, creator or channel, '
    'format, named tools/concepts, audience)\n'
    '- "speakers": array of strings (host/speaker names, NOT roles like '
    '"narrator" or "presenter"; at least one)\n'
    '- "guests": array of strings OR null\n'
    '- "entities_discussed": array of named products/libraries/datasets/tools\n'
    '- "detailed_summary": object with keys "thesis" (1-2 sentences), "format" '
    '(enum tutorial|interview|commentary|lecture|review|debate|walkthrough|'
    'reaction|vlog|other), "chapters_or_segments" (array of {timestamp, title, '
    'bullets}) — EACH chapter needs 3-6 bullets of concrete, grounded claims '
    'from that segment (no verbatim quotes, no speculation). Chapter titles '
    'must be short noun phrases. "demonstrations" (array of strings describing '
    'any hands-on demos/examples), "closing_takeaway" (1-2 sentences).\n\n'
    "Do NOT wrap in markdown code blocks. Return raw JSON only.\n\n"
    "SUMMARY:\n{summary_text}"
)
