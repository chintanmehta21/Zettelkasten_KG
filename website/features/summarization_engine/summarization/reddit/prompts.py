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
    "Return a JSON object with these exact keys:\n"
    '- "mini_title": format "r/<subreddit> <compact neutral title>" (max 60 chars)\n'
    '- "brief_summary": 5-7 sentence paragraph covering OP question, dominant response pattern, consensus/dissent, caveats\n'
    '- "tags": array of 7-10 lowercase hyphenated tags; include subreddit as a tag (e.g. "r-askhistorians")\n'
    '- "detailed_summary": object with keys "op_intent", "reply_clusters" (array of {theme, reasoning, examples}), '
    '"counterarguments" (array of strings), "unresolved_questions" (array of strings), "moderation_context" (string OR null)\n\n'
    "For high-divergence or experiential threads, emit at least 2 materially different reply_clusters when the discussion contains major warnings, minority dissent, or contrasting lived experience.\n"
    "Keep labels and briefs neutral. Do not simply compress the OP framing if the comments clearly debate or reject it.\n\n"
    "Do NOT wrap in markdown code blocks. Return raw JSON only.\n\n"
    "SUMMARY:\n{summary_text}"
)
