"""Reddit-specific prompt templates."""
from __future__ import annotations

SOURCE_CONTEXT = (
    "You are summarizing a Reddit thread. Separate the original post (OP) from "
    "the comment discussion. Represent major clusters of opinions/themes as "
    "discrete units, not individual comments. Use hedging language ('commenters "
    "argue...', 'one user claims...') for unverified claims; never assert comment "
    "content as fact. Preserve counterarguments, moderator context, and "
    "unresolved questions. If num_comments > rendered_count, mention "
    "missing/removed comments."
)

STRUCTURED_EXTRACT_INSTRUCTION = (
    f"{SOURCE_CONTEXT}\n\n"
    "Return a JSON object with EXACTLY these top-level keys:\n"
    '  "mini_title": string in the format "r/<subreddit> <compact neutral title>" (max 60 chars)\n'
    '  "brief_summary": string, 5-7 sentence paragraph covering OP question, dominant response pattern, consensus/dissent, caveats\n'
    '  "tags": array of 8-10 lowercase hyphenated strings; include the subreddit (e.g. "r-askhistorians")\n'
    '  "detailed_summary": object with these keys:\n'
    '      "op_intent": string\n'
    '      "reply_clusters": array of objects, where each object has string keys "theme", "reasoning", and "examples" (array of strings)\n'
    '      "counterarguments": array of strings\n'
    '      "unresolved_questions": array of strings\n'
    '      "moderation_context": string OR null\n\n'
    "Each reply_clusters entry MUST be a JSON object literally shaped like "
    '{{"theme": "...", "reasoning": "...", "examples": ["...", "..."]}}. '
    "Never collapse those three keys into a single key, never wrap them in another object, "
    "never output the literal placeholder text.\n\n"
    "For high-divergence or experiential threads, emit at least 2 materially different reply_clusters when the discussion contains major warnings, minority dissent, or contrasting lived experience.\n"
    "Keep labels and briefs neutral. Do not simply compress the OP framing if the comments clearly debate or reject it.\n\n"
    "Do NOT wrap in markdown code blocks. Return raw JSON only.\n\n"
    "SUMMARY:\n{summary_text}"
)
