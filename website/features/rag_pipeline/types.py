"""Shared models and enums for the user-level RAG stack."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


class SourceType(str, Enum):
    YOUTUBE = "youtube"
    REDDIT = "reddit"
    GITHUB = "github"
    TWITTER = "twitter"
    SUBSTACK = "substack"
    MEDIUM = "medium"
    WEB = "web"
    GENERIC = "generic"


class ChunkKind(str, Enum):
    SUMMARY = "summary"
    CHUNK = "chunk"


class ChunkType(str, Enum):
    ATOMIC = "atomic"
    SEMANTIC = "semantic"
    LATE = "late"
    RECURSIVE = "recursive"


class QueryClass(str, Enum):
    LOOKUP = "lookup"
    VAGUE = "vague"
    MULTI_HOP = "multi_hop"
    THEMATIC = "thematic"
    STEP_BACK = "step_back"


class ScopeFilter(BaseModel):
    node_ids: list[str] | None = None
    tags: list[str] | None = None
    tag_mode: Literal["all", "any"] = "all"
    source_types: list[SourceType] | None = None

    @field_validator("node_ids", "tags", "source_types", mode="before")
    @classmethod
    def _empty_list_to_none(cls, v):
        # An empty list from the client means "no filter", not "match nothing".
        # The SQL resolver uses `IS NULL` to short-circuit unfiltered branches;
        # ANY('{}') would otherwise match zero rows and produce empty_scope.
        if isinstance(v, list) and len(v) == 0:
            return None
        return v


class ChunkRecord(BaseModel):
    user_id: UUID
    node_id: str
    chunk_idx: int
    content: str
    chunk_type: ChunkType
    start_offset: int | None = None
    end_offset: int | None = None
    token_count: int | None = None
    metadata: dict = Field(default_factory=dict)


class RetrievalCandidate(BaseModel):
    kind: ChunkKind
    node_id: str
    chunk_id: UUID | None = None
    chunk_idx: int
    name: str
    source_type: SourceType
    url: str
    content: str
    tags: list[str] = Field(default_factory=list)
    metadata: dict = Field(default_factory=dict)
    rrf_score: float = 0.0
    rerank_score: float | None = None
    graph_score: float | None = None
    final_score: float | None = None


class Citation(BaseModel):
    id: str
    node_id: str
    title: str
    source_type: SourceType
    url: str
    snippet: str = Field(max_length=400)
    timestamp: str | None = None
    rerank_score: float = 0.0


class AnswerTurn(BaseModel):
    content: str
    citations: list[Citation] = Field(default_factory=list)
    query_class: QueryClass
    critic_verdict: Literal[
        "supported",
        "partial",
        "unsupported",
        "retried_supported",
        "retried_still_bad",  # legacy alias for retried_low_confidence (kept for back-compat)
        "retried_low_confidence",  # spec 2A.2 — 2nd-pass unsupported, draft + low-confidence tag returned
        # iter-04 critic-retry hardening (orchestrator.py):
        "unsupported_no_retry",   # first-pass refusal / low-score / vague-low-entity → retry skipped
        "retry_budget_exceeded",  # retry exceeded RAG_RETRY_BUDGET_S (default 12s)
        "retry_skipped_dejavu",   # retry mutation matrix produced identical params hash
        # iter-08 / iter-09 gold-tier skip gates (orchestrator.py + RES-1):
        "partial_with_gold_skip",         # iter-08: partial first-pass with rerank>=0.5, retry skipped
        "unsupported_with_gold_skip",     # iter-09 RES-1: LOOKUP unsupported with rerank>=0.7, retry skipped
    ]
    critic_notes: str | None = None
    trace_id: str = ""
    latency_ms: int = 0
    token_counts: dict = Field(default_factory=dict)
    llm_model: str = ""
    retrieved_node_ids: list[str] = Field(default_factory=list)
    retrieved_chunk_ids: list[UUID] = Field(default_factory=list)


class ChatTurn(BaseModel):
    role: Literal["user", "assistant", "system"]
    content: str
    created_at: datetime | None = None


class ChatQuery(BaseModel):
    session_id: UUID | None = None
    sandbox_id: UUID | None = None
    content: str
    scope_filter: ScopeFilter = Field(default_factory=ScopeFilter)
    quality: Literal["fast", "high"] = "fast"
    stream: bool = True


class AnswerChunk(BaseModel):
    content: str
    citations: list[Citation] = Field(default_factory=list)
    done: bool = False
