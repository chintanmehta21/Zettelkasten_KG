"""YAML config schemas for the rag_eval framework."""
from __future__ import annotations

from pydantic import BaseModel, Field, model_validator

from website.features.rag_pipeline.evaluation.types import GoldQuery


class CompositeWeights(BaseModel):
    chunking: float = Field(ge=0.0, le=1.0)
    retrieval: float = Field(ge=0.0, le=1.0)
    reranking: float = Field(ge=0.0, le=1.0)
    synthesis: float = Field(ge=0.0, le=1.0)

    def total(self) -> float:
        return self.chunking + self.retrieval + self.reranking + self.synthesis

    @model_validator(mode="after")
    def _sum_to_one(self) -> "CompositeWeights":
        if abs(self.total() - 1.0) > 1e-6:
            raise ValueError(f"Weights must sum to 1.0; got {self.total()}")
        return self


class SeedQueryFile(BaseModel):
    queries: list[GoldQuery] = Field(min_length=5, max_length=5)


class HeldoutQueryFile(BaseModel):
    queries: list[GoldQuery] = Field(min_length=3, max_length=3)
