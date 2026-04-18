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

# Citation tokens the system prompt asks the LLM to emit. Single- and
# double-quoted forms are both tolerated because some models normalize quotes.
_CITATION_RE = re.compile(r'\[id=(?P<quote>["\'])(?P<zid>[^"\']+)(?P=quote)\]')

# After stripping hallucinated citations we can be left with double-spaces or
# a stray space before a period/comma. Normalize those so punctuation stays
# tight against the preceding word.
_SPACE_BEFORE_PUNCT_RE = re.compile(r"\s+([.,;:!?])")
_COLLAPSED_SPACES_RE = re.compile(r" {2,}")


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


def strip_invalid_citations(
    text: str, valid_ids: set[str]
) -> tuple[str, list[str]]:
    """Remove ``[id="..."]`` citation tokens whose id isn't in ``valid_ids``.

    The rag system prompt instructs the LLM to cite only zettel ids that
    appear in the context block. When the model strays and cites an id we
    never surfaced, that citation is a hallucination — stripping it prevents
    the user from seeing a fabricated source and keeps the critic's grounding
    check honest.

    Returns the cleaned text plus a list of dropped ids (order preserved,
    duplicates preserved) so callers can log how often hallucination fires
    without re-parsing the original string.
    """
    if not text:
        return "", []
    dropped: list[str] = []

    def _replace(match: re.Match[str]) -> str:
        zid = match.group("zid")
        if zid in valid_ids:
            return match.group(0)
        dropped.append(zid)
        return ""

    cleaned = _CITATION_RE.sub(_replace, text)
    if dropped:
        cleaned = _SPACE_BEFORE_PUNCT_RE.sub(r"\1", cleaned)
        cleaned = _COLLAPSED_SPACES_RE.sub(" ", cleaned)
        cleaned = cleaned.strip()
    return cleaned, dropped


def has_valid_citation(text: str, valid_ids: set[str]) -> bool:
    """Return True iff ``text`` contains at least one ``[id="..."]`` whose id
    is in ``valid_ids``.

    Used by the orchestrator to detect the "every citation the model emitted
    was hallucinated" failure mode. After :func:`strip_invalid_citations` has
    scrubbed a text, if nothing valid remains the answer is a string of naked
    claims with no source trail — indistinguishable from training-data
    recollection and therefore unsafe to serve.
    """
    if not text or not valid_ids:
        return False
    for match in _CITATION_RE.finditer(text):
        if match.group("zid") in valid_ids:
            return True
    return False
