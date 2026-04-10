"""Prompt constants and source context blocks."""
from __future__ import annotations

from website.features.summarization_engine.core.models import SourceType

SYSTEM_PROMPT = (
    "You produce accurate Zettelkasten notes. Preserve facts, surface uncertainty, "
    "and avoid promotional language."
)

SOURCE_CONTEXT: dict[SourceType, str] = {
    SourceType.GITHUB: "Focus on repository purpose, architecture, APIs, maturity, and notable issues.",
    SourceType.HACKERNEWS: "Focus on the linked item, core debate, and strongest comment arguments.",
    SourceType.ARXIV: "Focus on research question, method, findings, limitations, and citations.",
    SourceType.NEWSLETTER: "Focus on the argument, evidence, framing, and implications.",
    SourceType.REDDIT: "Focus on the post, consensus, dissent, and practical takeaways.",
    SourceType.YOUTUBE: "Focus on transcript claims, examples, and timeline-level takeaways.",
    SourceType.LINKEDIN: "Focus on the announcement, author framing, and business context.",
    SourceType.PODCAST: "Focus on show-note topics, guest/host claims, and notable references.",
    SourceType.TWITTER: "Focus on the tweet's claim, context, and quoted/linked evidence.",
    SourceType.WEB: "Focus on the article's argument, evidence, and reusable ideas.",
}


def source_context(source_type: SourceType) -> str:
    return SOURCE_CONTEXT.get(source_type, SOURCE_CONTEXT[SourceType.WEB])
