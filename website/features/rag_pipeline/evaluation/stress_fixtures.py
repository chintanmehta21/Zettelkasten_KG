"""Stress-test fixtures for the rag_eval harness.

Three dimensions of robustness beyond the iter-01..iter-06 happy-path golds:

1. Vague — single-token query that should trigger a clarification or refusal.
2. Out-of-corpus — a topic absent from Naruto's KG; the orchestrator must
   refuse with the canonical phrase rather than hallucinate.
3. Multi-hop — a synthesis question requiring two specific zettels at once.

Fixtures are pure data builders so eval_runner / rag_eval_loop can compose
them into any source's gold-set without re-binding to fixture files.
"""
from __future__ import annotations

from website.features.rag_pipeline.evaluation.types import GoldQuery


REFUSAL_PHRASE = "I can't find that in your Zettels."


def build_vague_query_fixture() -> GoldQuery:
    """Single-token query — the orchestrator should ask for clarification."""
    return GoldQuery(
        id="stress-vague-01",
        question="attention",
        gold_node_ids=["__none__"],
        gold_ranking=["__none__"],
        reference_answer=REFUSAL_PHRASE,
        atomic_facts=["clarification or refusal expected"],
        expected_behavior="ask_clarification_or_refuse",
    )


def build_out_of_corpus_fixture() -> GoldQuery:
    """A topic absent from Naruto's AI/ML KG; must refuse, not hallucinate."""
    return GoldQuery(
        id="stress-oop-01",
        question=(
            "What did the 1789 French Estates-General delegate from Brittany "
            "say about the abolition of feudal privileges?"
        ),
        gold_node_ids=["__none__"],
        gold_ranking=["__none__"],
        reference_answer=REFUSAL_PHRASE,
        atomic_facts=["out-of-corpus refusal expected"],
        expected_behavior="refuse",
    )


def build_multi_hop_fixture() -> GoldQuery:
    """Cross-zettel synthesis: Karpathy LLM intro + LeCun JEPA vision."""
    return GoldQuery(
        id="stress-multihop-01",
        question=(
            "How does Karpathy's two-stage LLM training framing relate to "
            "LeCun's JEPA argument that next-token prediction is "
            "insufficient for human-level understanding?"
        ),
        gold_node_ids=[
            "yt-andrej-karpathy-s-llm-in",
            "yt-lecun-s-vision-human-lev",
        ],
        gold_ranking=[
            "yt-andrej-karpathy-s-llm-in",
            "yt-lecun-s-vision-human-lev",
        ],
        reference_answer=(
            "Karpathy frames LLM training as pretraining (kernel) plus "
            "supervised fine-tuning (assistant), while LeCun argues that "
            "next-token prediction alone is too narrow a signal to acquire "
            "the world-model required for human-level intelligence — JEPA "
            "is proposed as a richer prediction objective in latent space."
        ),
        atomic_facts=[
            "Karpathy describes pretraining producing a base model (the kernel)",
            "Karpathy describes fine-tuning producing the assistant",
            "LeCun argues next-token prediction is insufficient for AGI",
            "LeCun proposes JEPA as a richer latent-space prediction objective",
        ],
        expected_behavior="answer",
    )
