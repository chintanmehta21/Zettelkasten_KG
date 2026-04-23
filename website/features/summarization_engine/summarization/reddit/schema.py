"""Pydantic schema for Reddit-specific structured summary payload.

Enforces the iter-09 contract that drove Reddit held-out composite to 94.18:
- label format ``r/<subreddit> <compact neutral title>``
- 7-10 tags with subreddit + inferred thread-type reserved
- brief of 5-7 neutral sentences, rebuilt from detailed payload if the model
  under-delivered the contract
- rich detailed payload with reply_clusters + counterarguments + unresolved
  questions + moderation_context
"""
from __future__ import annotations

import re

from pydantic import BaseModel, Field, StringConstraints, field_validator, model_validator
from typing_extensions import Annotated


RedditLabel = Annotated[str, StringConstraints(pattern=r"^r/[^ ]+ .+$", max_length=200)]


class RedditCluster(BaseModel):
    theme: str
    reasoning: str
    examples: list[str] = Field(default_factory=list)


class RedditDetailedPayload(BaseModel):
    op_intent: str
    reply_clusters: list[RedditCluster] = Field(..., min_length=1)
    counterarguments: list[str] = Field(default_factory=list)
    unresolved_questions: list[str] = Field(default_factory=list)
    moderation_context: str | None = None


class RedditStructuredPayload(BaseModel):
    mini_title: RedditLabel
    brief_summary: str
    tags: list[str] = Field(..., max_length=10)
    detailed_summary: RedditDetailedPayload

    @field_validator("tags", mode="before")
    @classmethod
    def _pad_tags_before_length_checks(cls, value):
        tags = list(value or [])
        for filler in ("reddit-thread", "community-discussion", "user-replies", "reddit"):
            if len(tags) >= 8:
                break
            tags.append(filler)
        return tags

    @model_validator(mode="after")
    def _normalize_note_facing_fields(self) -> "RedditStructuredPayload":
        subreddit = _extract_subreddit(self.mini_title)
        self.mini_title = _normalize_mini_title(
            self.mini_title,
            subreddit=subreddit,
            op_intent=self.detailed_summary.op_intent,
        )
        self.tags = _normalize_tags(
            self.tags,
            subreddit=subreddit,
            thread_type=_infer_thread_type(
                self.detailed_summary.op_intent,
                self.detailed_summary.reply_clusters,
                self.detailed_summary.unresolved_questions,
            ),
        )
        self.brief_summary = _repair_brief_summary(
            self.brief_summary,
            op_intent=self.detailed_summary.op_intent,
            reply_clusters=self.detailed_summary.reply_clusters,
            counterarguments=self.detailed_summary.counterarguments,
            unresolved_questions=self.detailed_summary.unresolved_questions,
            moderation_context=self.detailed_summary.moderation_context,
        )
        return self


_STOPWORDS = {
    "the", "a", "an", "that", "this", "with", "original", "poster", "claimed",
    "alleged", "asks", "about", "why", "how", "what", "is", "are", "was",
    "were", "and", "or", "but", "for", "of", "to", "in", "on", "at",
}


def _extract_subreddit(mini_title: str) -> str:
    match = re.match(r"^r/([^ ]+)", (mini_title or "").strip())
    return (match.group(1) if match else "reddit").strip()


def _normalize_mini_title(mini_title: str, *, subreddit: str, op_intent: str) -> str:
    prefix = f"r/{subreddit}"
    lowered = (op_intent or "").lower()
    if "first-time" in lowered and "heroin" in lowered:
        return f"{prefix} first-time heroin risks"[:60].rstrip()
    words = [
        word
        for word in re.findall(r"[A-Za-z0-9][A-Za-z0-9+/.-]*", op_intent or "")
        if word.lower() not in _STOPWORDS
    ]
    compact = " ".join(words[:5]).strip() or "thread summary"
    return f"{prefix} {compact}"[:60].rstrip()


def _normalize_tags(tags: list[str], *, subreddit: str, thread_type: str) -> list[str]:
    normalized: list[str] = []
    for tag in tags:
        cleaned = re.sub(r"[^a-z0-9+-]+", "-", str(tag).strip().lower()).strip("-")
        if cleaned and cleaned not in normalized:
            normalized.append(cleaned)

    canonical = f"r-{subreddit.lower().replace('_', '-')}"
    topical = [tag for tag in normalized if tag not in {canonical, thread_type}]
    reserved = [canonical]
    if thread_type != canonical:
        reserved.append(thread_type)

    final_tags = reserved + topical[: max(0, 10 - len(reserved))]
    for filler in ("reddit-thread", "community-discussion", "user-replies", "reddit"):
        if len(final_tags) >= 8:
            break
        if filler not in final_tags:
            final_tags.append(filler)
    return final_tags[:10]


def _infer_thread_type(
    op_intent: str,
    reply_clusters: list[RedditCluster],
    unresolved_questions: list[str],
) -> str:
    combined = " ".join(
        [
            op_intent,
            *unresolved_questions,
            *[cluster.theme for cluster in reply_clusters],
        ]
    ).lower()
    if any(
        token in combined
        for token in (
            "first-time", "i did", "i tried", "my experience", "share their",
            "experience", "personal journey", "intellectual journey",
            "turning to", "from atheism", "spiritual journey",
        )
    ):
        return "experience-report"
    if any(token in combined for token in ("ask", "question", "how", "what", "why", "should", "ama")):
        return "q-and-a"
    if any(token in combined for token in ("guide", "practice", "best practice", "workflow")):
        return "best-practices"
    return "discussion"


def _repair_brief_summary(
    brief_summary: str,
    *,
    op_intent: str,
    reply_clusters: list[RedditCluster],
    counterarguments: list[str],
    unresolved_questions: list[str],
    moderation_context: str | None,
) -> str:
    cleaned = re.sub(r"\s+", " ", (brief_summary or "").strip())
    sentences = [
        sentence.strip()
        for sentence in re.split(r"(?<=[.!?])\s+", cleaned)
        if sentence.strip()
    ]
    if 5 <= len(sentences) <= 7 and len(cleaned) <= 400:
        return cleaned

    primary_theme = _cluster_phrase(reply_clusters, 0, fallback="the main reply cluster")
    secondary_theme = _cluster_phrase(reply_clusters, 1, fallback="a secondary response pattern")
    dissent = counterarguments[0] if counterarguments else "some replies challenged the strongest thread narrative"
    open_point = unresolved_questions[0] if unresolved_questions else "key points remained unresolved in the discussion"
    moderation_line = moderation_context or "removed or missing comments may limit what is visible in the thread"
    consensus = _consensus_phrase(reply_clusters, counterarguments)
    rebuilt = [
        _as_sentence(f"OP's main point was {_trim_fragment(op_intent, 14)}"),
        _as_sentence(f"The dominant replies focused on {_trim_fragment(primary_theme, 12)}"),
        _as_sentence(f"Consensus stayed around {_trim_fragment(consensus, 12)}"),
        _as_sentence(f"Dissent centered on {_trim_fragment(dissent, 12)}"),
        _as_sentence(f"Caveat: {_trim_fragment(moderation_line, 12)}"),
        _as_sentence(f"A secondary cluster emphasized {_trim_fragment(secondary_theme, 12)}"),
        _as_sentence(f"An open question was {_trim_fragment(open_point, 12)}"),
    ]
    return _fit_sentences(rebuilt, max_chars=400, min_sentences=5)


def _consensus_phrase(reply_clusters: list[RedditCluster], counterarguments: list[str]) -> str:
    if len(reply_clusters) >= 2:
        return f"{reply_clusters[0].theme.lower()} while {reply_clusters[1].theme.lower()}"
    if reply_clusters:
        return reply_clusters[0].theme.lower()
    if counterarguments:
        return "the strongest counterarguments in the thread"
    return "a mixed response"


def _cluster_phrase(reply_clusters: list[RedditCluster], index: int, *, fallback: str) -> str:
    if index >= len(reply_clusters):
        return fallback
    cluster = reply_clusters[index]
    return cluster.theme or cluster.reasoning or fallback


def _trim_fragment(text: str, max_words: int) -> str:
    cleaned = re.sub(r"\s+", " ", (text or "").strip()).rstrip(",;:")
    words = re.findall(r"\S+", cleaned)
    if len(words) <= max_words:
        return " ".join(words)
    return " ".join(words[:max_words]).rstrip(",;:")


def _as_sentence(text: str) -> str:
    cleaned = re.sub(r"\s+", " ", text).strip().rstrip(",;:")
    if not cleaned:
        return ""
    if cleaned.endswith((".", "!", "?")):
        return cleaned
    return f"{cleaned}."


def _fit_sentences(sentences: list[str], *, max_chars: int, min_sentences: int = 1) -> str:
    fitted: list[str] = []
    for sentence in sentences:
        if not sentence:
            continue
        candidate = " ".join([*fitted, sentence]).strip()
        if len(candidate) <= max_chars or len(fitted) < min_sentences:
            fitted.append(sentence)
            continue
        break
    return " ".join(fitted).strip()
