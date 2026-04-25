"""Shared pydantic models for the evaluation harness."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

Category = Literal[
    "single_zettel_factual",
    "multi_zettel_synthesis",
    "cross_source",
    "temporal",
    "out_of_corpus",
    "adversarial",
    "numeric",
    "negation",
]


class Kasten(BaseModel):
    """A topic cluster of 5-7 zettels."""

    id: str
    title: str
    zettel_ids: list[str]
    dominant_tags: list[str]


class Question(BaseModel):
    id: str
    category: Category
    kasten_id: str
    question: str
    expected_zettel_ids: list[str] = Field(default_factory=list)
    expected_behavior: Literal["answer", "refuse", "partial"] = "answer"


class AxisScore(BaseModel):
    faithfulness: int = Field(..., ge=0, le=5)
    relevance: int = Field(..., ge=0, le=5)
    completeness: int = Field(..., ge=0, le=5)
    citation_accuracy: int = Field(..., ge=0, le=5)

    @property
    def total(self) -> int:
        return (
            self.faithfulness
            + self.relevance
            + self.completeness
            + self.citation_accuracy
        )


class JudgeResult(BaseModel):
    scores: AxisScore
    rationale: dict[str, str]


class QuestionResult(BaseModel):
    question_id: str
    category: Category
    kasten_id: str
    question: str
    answer: str
    retrieved_chunk_ids: list[str]
    latency_ms: int
    judge: JudgeResult | None = None
    error: str | None = None


class RunReport(BaseModel):
    iteration: int
    module_under_test: str
    started_at: datetime
    finished_at: datetime
    git_sha: str
    rubric: Literal["b", "c"]
    results: list[QuestionResult]

    def mean_total(self) -> float:
        scored = [r for r in self.results if r.judge is not None]
        if not scored:
            return 0.0
        return sum(r.judge.scores.total for r in scored) / len(scored)


# ── rag_eval framework types ────────────────────────────────────────────────


class GoldQuery(BaseModel):
    id: str
    question: str
    gold_node_ids: list[str] = Field(min_length=1)
    gold_ranking: list[str] = Field(min_length=1)
    reference_answer: str
    atomic_facts: list[str] = Field(min_length=1)


class ComponentScores(BaseModel):
    chunking: float = Field(ge=0.0, le=100.0)
    retrieval: float = Field(ge=0.0, le=100.0)
    reranking: float = Field(ge=0.0, le=100.0)
    synthesis: float = Field(ge=0.0, le=100.0)


class PerQueryScore(BaseModel):
    query_id: str
    retrieved_node_ids: list[str]
    reranked_node_ids: list[str]
    cited_node_ids: list[str]
    ragas: dict[str, float]
    deepeval: dict[str, float]
    component_breakdown: dict[str, float]


class GraphLift(BaseModel):
    composite: float
    retrieval: float
    reranking: float


class EvalResult(BaseModel):
    iter_id: str
    component_scores: ComponentScores
    composite: float
    weights: dict[str, float]
    weights_hash: str
    graph_lift: GraphLift | dict[str, float]
    per_query: list[PerQueryScore]
    eval_divergence: bool = False


class KGSnapshot(BaseModel):
    kasten_node_ids: list[str]
    neighborhood_node_ids: list[str]
    node_count: int
    edge_count: int
    mean_degree: float
    orphan_count: int
    tag_count: int
    tag_histogram: dict[str, int] = Field(default_factory=dict)


KGRecommendationType = Literal[
    "add_link", "add_tag", "merge_nodes", "reingest_node", "orphan_warning"
]
KGRecommendationStatus = Literal["auto_apply", "applied", "quarantined", "rejected"]


class KGRecommendation(BaseModel):
    type: KGRecommendationType
    payload: dict
    evidence_query_ids: list[str]
    confidence: float = Field(ge=0.0, le=1.0)
    status: KGRecommendationStatus
