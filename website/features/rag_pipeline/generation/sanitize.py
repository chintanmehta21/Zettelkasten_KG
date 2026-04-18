"""Post-processing for LLM-generated answers before they reach the critic or user.

Even with a tight system prompt, LLMs occasionally leak chain-of-thought
scratchpads, echo back fragments of the context XML, or prefix their output
with conversational scaffolding like ``Answer:``. Running every generated
answer through :func:`sanitize_answer` gives the critic a clean string to
verify against the context and prevents the user from ever seeing the junk.
"""

from __future__ import annotations

import re

_SCRATCHPAD_RE = re.compile(r"<scratchpad\b[^>]*>.*?</scratchpad>", re.IGNORECASE | re.DOTALL)
_UNCLOSED_SCRATCHPAD_RE = re.compile(r"<scratchpad\b[^>]*>.*", re.IGNORECASE | re.DOTALL)

# The assembler emits <context>, <zettel>, and <passage> tags. If the LLM
# echoes any of those (rule 7 says it shouldn't), strip them — but keep the
# inner text so a paraphrased citation survives intact.
_CONTEXT_TAG_RE = re.compile(
    r"</?(?:context|zettel|passage)\b[^>]*>",
    re.IGNORECASE,
)

# Some models prefix every response with "Answer:" (a hangover from the user
# template). Strip the leading marker so the answer reads cleanly.
_ANSWER_PREFIX_RE = re.compile(r"^\s*answer\s*:\s*", re.IGNORECASE)

# Collapse runs of 3+ blank lines down to a single blank line. Preserve
# paragraph breaks (double newlines) — only squash gratuitous gaps.
_EXTRA_BLANK_LINES_RE = re.compile(r"\n{3,}")


def sanitize_answer(text: str) -> str:
    """Strip leaked prompt/context artifacts from an LLM answer.

    The steps run in order:

    1. Remove balanced ``<scratchpad>...</scratchpad>`` blocks (chain-of-thought
       reasoning that should stay hidden).
    2. Remove any trailing unclosed ``<scratchpad>`` span — if the model
       started a scratchpad but ran out of tokens, truncate there so the
       user never sees the partial reasoning.
    3. Strip echoed context-XML tags (``<context>``, ``<zettel>``, ``<passage>``)
       while keeping their inner text.
    4. Drop a leading ``Answer:`` prefix.
    5. Collapse 3+ consecutive newlines into a single blank line.
    6. Strip leading/trailing whitespace.

    An empty or whitespace-only input returns an empty string.
    """
    if not text:
        return ""
    cleaned = _SCRATCHPAD_RE.sub("", text)
    cleaned = _UNCLOSED_SCRATCHPAD_RE.sub("", cleaned)
    cleaned = _CONTEXT_TAG_RE.sub("", cleaned)
    cleaned = _ANSWER_PREFIX_RE.sub("", cleaned)
    cleaned = _EXTRA_BLANK_LINES_RE.sub("\n\n", cleaned)
    return cleaned.strip()
