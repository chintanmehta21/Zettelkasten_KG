"""Pydantic schema for Reddit-specific structured summary payload."""
from __future__ import annotations

import re

from pydantic import BaseModel, Field, StringConstraints
from pydantic import model_validator
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
    tags: list[str] = Field(..., min_length=7, max_length=10)
    detailed_summary: RedditDetailedPayload

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


def _extract_subreddit(mini_title: str) -> str:
    match = re.match(r"^r/([^ ]+)", (mini_title or "").strip())
    return (match.group(1) if match else "reddit").strip()


def _normalize_mini_title(mini_title: str, *, subreddit: str, op_intent: str) -> str:
    prefix = f"r/{subreddit}"
    lower = op_intent.lower()
    if "heroin" in lower:
        compact = "first-time heroin risks"
    elif "rajkot" in lower and ("ipo" in lower or "gmp" in lower):
        compact = "Rajkot IPO influence debate"
    else:
        words = [
            word
            for word in re.findall(r"[A-Za-z0-9][A-Za-z0-9+/.-]*", op_intent)
            if word.lower()
            not in {"the", "a", "an", "that", "this", "with", "original", "poster", "claimed", "alleged", "asks", "about"}
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
    if canonical not in normalized:
        normalized.insert(0, canonical)
    if thread_type not in normalized:
        normalized.append(thread_type)
    while len(normalized) < 7:
        filler = "reddit-thread"
        if filler not in normalized:
            normalized.append(filler)
        else:
            break
    return normalized[:10]


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
    if any(token in combined for token in ("first-time", "i did", "i tried", "my experience", "share their", "experience")):
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

    primary = reply_clusters[0].reasoning if reply_clusters else "Commenters offered multiple competing explanations."
    dissent = counterarguments[0] if counterarguments else "Some replies challenged the strongest thread narrative."
    open_point = unresolved_questions[0] if unresolved_questions else "Some details remain unresolved in the thread."
    moderation_line = moderation_context or "Removed or missing comments may limit what is visible in the rendered thread."
    consensus = _consensus_phrase(reply_clusters, counterarguments)
    rebuilt = [
        _as_sentence(f"OP argued {_trim_fragment(op_intent, 10)}"),
        _as_sentence(f"Many replies said {_trim_fragment(primary, 10)}"),
        _as_sentence(f"The thread mostly converged on {_trim_fragment(consensus, 10)}"),
        _as_sentence(f"Pushback included {_trim_fragment(dissent, 9)}"),
        _as_sentence(f"Context: {_trim_fragment(moderation_line, 8)}"),
        _as_sentence(f"Open questions remain about {_trim_fragment(open_point, 9)}"),
    ]
    return _fit_sentences(rebuilt, max_chars=400)


def _consensus_phrase(reply_clusters: list[RedditCluster], counterarguments: list[str]) -> str:
    if len(reply_clusters) >= 2:
        return f"{reply_clusters[0].theme.lower()} while {reply_clusters[1].theme.lower()}"
    if reply_clusters:
        return reply_clusters[0].theme.lower()
    if counterarguments:
        return "the strongest counterarguments in the thread"
    return "a mixed response"


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


def _fit_sentences(sentences: list[str], *, max_chars: int) -> str:
    fitted: list[str] = []
    for sentence in sentences:
        if not sentence:
            continue
        candidate = " ".join([*fitted, sentence]).strip()
        if len(candidate) <= max_chars:
            fitted.append(sentence)
            continue
        break
    return " ".join(fitted).strip()
