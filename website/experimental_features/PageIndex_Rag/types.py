from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal


@dataclass(frozen=True, slots=True)
class ZettelRecord:
    user_id: str
    node_id: str
    title: str
    summary: str
    content: str
    source_type: str
    url: str | None
    tags: tuple[str, ...]
    metadata: dict[str, Any]


@dataclass(frozen=True, slots=True)
class PageIndexDocument:
    user_id: str
    node_id: str
    content_hash: str
    doc_id: str
    markdown_path: Path
    tree_path: Path


@dataclass(frozen=True, slots=True)
class PageIndexRagScope:
    scope_id: str
    user_id: str
    node_ids: tuple[str, ...]
    membership_hash: str
    name: str = "Knowledge Management"
    mode: Literal["temporary", "persisted"] = "temporary"


@dataclass(frozen=True, slots=True)
class CandidateDocument:
    node_id: str
    doc_id: str
    title: str
    score: float
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class EvidenceItem:
    node_id: str
    doc_id: str
    title: str
    source_url: str | None
    section: str
    line_range: str
    text: str
    score: float


@dataclass(frozen=True, slots=True)
class AnswerCandidate:
    answer_id: str
    style: Literal["direct", "comparative", "exploratory"]
    text: str
    cited_node_ids: tuple[str, ...]
    citations: tuple[dict[str, Any], ...]
    metrics: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class PageIndexQueryResult:
    query_id: str
    query: str
    retrieved_node_ids: tuple[str, ...]
    reranked_node_ids: tuple[str, ...]
    evidence: tuple[EvidenceItem, ...]
    answers: tuple[AnswerCandidate, AnswerCandidate, AnswerCandidate]
    timings_ms: dict[str, float]
    memory_rss_mb: dict[str, float]
