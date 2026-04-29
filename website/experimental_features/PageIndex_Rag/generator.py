from __future__ import annotations

import json
from typing import Any, Literal, cast

from .types import AnswerCandidate, EvidenceItem


STYLES: tuple[Literal["direct", "comparative", "exploratory"], ...] = ("direct", "comparative", "exploratory")


def build_answer_prompt(*, query: str, evidence: list[EvidenceItem], style: str) -> str:
    evidence_payload = [
        {
            "node_id": item.node_id,
            "title": item.title,
            "section": item.section,
            "source_url": item.source_url,
            "text": item.text[:4000],
        }
        for item in evidence
    ]
    return (
        "Answer only from the supplied evidence. "
        "Return JSON with keys text, cited_node_ids, citations. "
        f"Style: {style}\n"
        f"Question: {query}\n"
        f"Evidence: {json.dumps(evidence_payload, ensure_ascii=False)}"
    )


def _answer_from_response(
    *,
    answer_id: str,
    style: Literal["direct", "comparative", "exploratory"],
    response_text: str,
    evidence: list[EvidenceItem],
    key_index: int,
) -> AnswerCandidate:
    cited = tuple(item.node_id for item in evidence)
    citations = tuple({"node_id": item.node_id, "title": item.title, "source_url": item.source_url} for item in evidence)
    text = response_text
    try:
        parsed = json.loads(response_text)
    except json.JSONDecodeError:
        parsed = None
    if isinstance(parsed, dict):
        text = str(parsed.get("text") or response_text)
        raw_cited = parsed.get("cited_node_ids")
        if isinstance(raw_cited, list):
            cited = tuple(str(node_id) for node_id in raw_cited)
        raw_citations = parsed.get("citations")
        if isinstance(raw_citations, list):
            citations = tuple(item for item in raw_citations if isinstance(item, dict))
    return AnswerCandidate(
        answer_id=answer_id,
        style=style,
        text=text,
        cited_node_ids=cited,
        citations=cast(tuple[dict[str, Any], ...], citations),
        metrics={"gemini_key_index": float(key_index)},
    )


async def generate_three_answers(
    *,
    key_pool: Any,
    query: str,
    evidence: list[EvidenceItem],
) -> tuple[AnswerCandidate, AnswerCandidate, AnswerCandidate]:
    answers: list[AnswerCandidate] = []
    for idx, style in enumerate(STYLES, start=1):
        prompt = build_answer_prompt(query=query, evidence=evidence, style=style)
        response, model_used, key_index = await key_pool.generate_content(
            prompt,
            label=f"pageindex_rag.answer.{style}",
            telemetry_sink=[],
        )
        text = getattr(response, "text", str(response))
        answer = _answer_from_response(
            answer_id=f"a{idx}",
            style=style,
            response_text=text,
            evidence=evidence,
            key_index=key_index,
        )
        if model_used:
            answer.metrics["gemini_model_reported"] = 1.0
        answers.append(answer)
    return (answers[0], answers[1], answers[2])
