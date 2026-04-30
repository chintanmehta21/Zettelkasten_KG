from __future__ import annotations

import json
import re
from dataclasses import replace
from typing import Any, Literal, cast

from .types import AnswerCandidate, EvidenceItem


STYLES: tuple[Literal["direct", "comparative", "exploratory"], ...] = ("direct", "comparative", "exploratory")
STOPWORDS = {
    "about",
    "according",
    "also",
    "and",
    "are",
    "does",
    "for",
    "from",
    "how",
    "into",
    "its",
    "not",
    "that",
    "the",
    "their",
    "this",
    "what",
    "when",
    "where",
    "which",
    "with",
}
REFUSAL_PATTERNS = (
    "does not contain",
    "do not contain",
    "no information",
    "not provided",
    "not explicitly covered",
    "cannot answer",
    "i am sorry",
)
GENERIC_TOPIC_TOKENS = {"city", "citie", "community", "heat", "urban", "resilience"}


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
        "Treat user wording as a paraphrase of the evidence: if the exact phrase is absent but the cited zettel "
        "contains a semantic equivalent, answer using the zettel wording and explain the mapping. "
        "Prefer a complete answer over a terse answer: include the concrete facts, causal links, named practices, "
        "and contrasts that directly answer the question. "
        "For multi-source questions, synthesize across every relevant cited node. "
        "If one requested entity is missing but another is present, answer the present part first and then state "
        "the missing part without using a blanket refusal. "
        "Return JSON with keys text, cited_node_ids, citations. "
        f"Style: {style}\n"
        f"Question: {query}\n"
        f"Evidence: {json.dumps(evidence_payload, ensure_ascii=False)}"
    )


def _tokens(text: str) -> set[str]:
    return {
        token[:-1] if token.endswith("s") and len(token) > 4 else token
        for token in re.findall(r"[a-z0-9]+", text.lower())
        if len(token) > 2 and token not in STOPWORDS
    }


def _is_refusal(text: str) -> bool:
    lowered = text.lower()
    return any(pattern in lowered for pattern in REFUSAL_PATTERNS)


def _parse_json_payload(response_text: str) -> dict[str, Any] | None:
    text = response_text.strip()
    fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", text, flags=re.DOTALL | re.IGNORECASE)
    if fenced:
        text = fenced.group(1).strip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _normalize_answer(answer: AnswerCandidate) -> tuple[str, tuple[str, ...], tuple[dict[str, Any], ...]]:
    parsed = _parse_json_payload(answer.text)
    if not parsed:
        return answer.text.strip(), answer.cited_node_ids, answer.citations
    text = str(parsed.get("text") or answer.text).strip()
    cited = answer.cited_node_ids
    citations = answer.citations
    raw_cited = parsed.get("cited_node_ids")
    if isinstance(raw_cited, list):
        cited = tuple(str(node_id) for node_id in raw_cited)
    raw_citations = parsed.get("citations")
    if isinstance(raw_citations, list):
        citations = tuple(item for item in raw_citations if isinstance(item, dict))
    return text, cited, cast(tuple[dict[str, Any], ...], citations)


def _support_ratio(*, query: str, evidence: list[EvidenceItem]) -> float:
    query_tokens = _tokens(query)
    if not query_tokens:
        return 0.0
    evidence_tokens = _tokens(" ".join(f"{item.title} {item.section} {item.text}" for item in evidence))
    return len(query_tokens & evidence_tokens) / len(query_tokens)


def _answer_score(*, query: str, evidence: list[EvidenceItem], answer: AnswerCandidate) -> float:
    text, cited, _ = _normalize_answer(answer)
    answer_tokens = _tokens(text)
    evidence_tokens = _tokens(" ".join(item.text for item in evidence))
    query_tokens = _tokens(query)
    support = _support_ratio(query=query, evidence=evidence)
    refusal = _is_refusal(text)
    score = 0.0
    score += min(len(answer_tokens) / 120, 1.0)
    score += min(len(cited), 4) * 0.18
    if cited:
        score += 0.25
    if query_tokens:
        score += len(answer_tokens & query_tokens) / len(query_tokens)
    if evidence_tokens:
        score += min(len(answer_tokens & evidence_tokens) / 45, 0.6)
    if answer.style == "comparative":
        score += 0.08
    if answer.style == "exploratory":
        score += 0.12
    if refusal and support >= 0.25:
        score -= 1.2
    elif refusal and support < 0.25:
        score += 0.5
    elif not refusal and support < 0.25:
        score -= 0.6
    return score


def _rank_cited_node_ids(
    *,
    query: str,
    text: str,
    cited: tuple[str, ...],
    evidence: list[EvidenceItem],
) -> tuple[str, ...]:
    if not cited:
        return cited
    query_tokens = _tokens(query)
    answer_tokens = _tokens(text)
    by_id = {item.node_id: item for item in evidence}

    def score(node_id: str) -> tuple[float, int]:
        item = by_id.get(node_id)
        if item is None:
            return (0.0, len(evidence))
        title_tokens = _tokens(item.title)
        node_tokens = _tokens(f"{item.title} {item.section} {item.text}")
        value = 0.0
        value += len(answer_tokens & title_tokens) * 4.0
        value += len(query_tokens & title_tokens) * 3.0
        value += len((query_tokens & title_tokens) - GENERIC_TOPIC_TOKENS) * 6.0
        value += len((answer_tokens & title_tokens) - GENERIC_TOPIC_TOKENS) * 2.0
        value += min(len(answer_tokens & node_tokens) / 6, 5.0)
        value += min(len(query_tokens & node_tokens) / 8, 2.0)
        return (value, next((idx for idx, candidate in enumerate(evidence) if candidate.node_id == node_id), len(evidence)))

    unique = tuple(dict.fromkeys(node_id for node_id in cited if node_id in by_id))
    return tuple(sorted(unique, key=lambda node_id: (-score(node_id)[0], score(node_id)[1])))


def select_final_answer(
    *,
    query: str,
    evidence: list[EvidenceItem],
    answers: list[AnswerCandidate],
) -> tuple[AnswerCandidate, AnswerCandidate, AnswerCandidate]:
    normalized = []
    evidence_by_id = {item.node_id: item for item in evidence}
    for answer in answers:
        text, cited, citations = _normalize_answer(answer)
        cited = _rank_cited_node_ids(query=query, text=text, cited=cited, evidence=evidence)
        if cited:
            citations_by_id = {
                str(item.get("node_id")): item
                for item in citations
                if isinstance(item, dict) and item.get("node_id")
            }
            citations = tuple(
                citations_by_id.get(
                    node_id,
                    {
                        "node_id": node_id,
                        "title": evidence_by_id[node_id].title,
                        "source_url": evidence_by_id[node_id].source_url,
                    },
                )
                for node_id in cited
                if node_id in evidence_by_id
            )
        normalized.append(replace(answer, cited_node_ids=cited, citations=cast(tuple[dict[str, Any], ...], citations)))
    ranked = sorted(normalized, key=lambda answer: _answer_score(query=query, evidence=evidence, answer=answer), reverse=True)
    return (ranked[0], ranked[1], ranked[2])


def _answer_from_response(
    *,
    answer_id: str,
    style: Literal["direct", "comparative", "exploratory"],
    response_text: str,
    evidence: list[EvidenceItem],
    query: str,
    key_index: int,
) -> AnswerCandidate:
    cited = tuple(item.node_id for item in evidence)
    citations = tuple({"node_id": item.node_id, "title": item.title, "source_url": item.source_url} for item in evidence)
    text = response_text
    parsed = _parse_json_payload(response_text)
    if isinstance(parsed, dict):
        text = str(parsed.get("text") or response_text)
        raw_cited = parsed.get("cited_node_ids")
        if isinstance(raw_cited, list):
            cited = tuple(str(node_id) for node_id in raw_cited)
        raw_citations = parsed.get("citations")
        if isinstance(raw_citations, list):
            citations = tuple(item for item in raw_citations if isinstance(item, dict))
    cited = _rank_cited_node_ids(query=query, text=text, cited=cited, evidence=evidence)
    if cited:
        citations_by_id = {
            str(item.get("node_id")): item
            for item in citations
            if isinstance(item, dict) and item.get("node_id")
        }
        evidence_by_id = {item.node_id: item for item in evidence}
        citations = tuple(
            citations_by_id.get(
                node_id,
                {
                    "node_id": node_id,
                    "title": evidence_by_id[node_id].title,
                    "source_url": evidence_by_id[node_id].source_url,
                },
            )
            for node_id in cited
            if node_id in evidence_by_id
        )
    return AnswerCandidate(
        answer_id=answer_id,
        style=style,
        text=text,
        cited_node_ids=cited,
        citations=cast(tuple[dict[str, Any], ...], citations),
        metrics={"gemini_key_index": float(key_index)},
    )


def _fallback_answer(
    *,
    answer_id: str,
    style: Literal["direct", "comparative", "exploratory"],
    query: str,
    evidence: list[EvidenceItem],
    error: Exception,
) -> AnswerCandidate:
    support = _support_ratio(query=query, evidence=evidence)
    cited_items = evidence[:4] if support >= 0.2 else ()
    if not cited_items:
        text = "The supplied evidence does not contain enough support to answer this question."
    else:
        snippets = []
        for item in cited_items:
            snippet = " ".join(item.text.split())
            snippets.append(f"{item.title}: {snippet[:650]}")
        text = "Based on the supplied evidence, " + " ".join(snippets)
    cited = tuple(item.node_id for item in cited_items)
    citations = tuple({"node_id": item.node_id, "title": item.title, "source_url": item.source_url} for item in cited_items)
    return AnswerCandidate(
        answer_id=answer_id,
        style=style,
        text=text,
        cited_node_ids=cited,
        citations=cast(tuple[dict[str, Any], ...], citations),
        metrics={"generator_fallback": 1.0, "error_length": float(len(str(error)))},
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
        try:
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
                query=query,
                key_index=key_index,
            )
            if model_used:
                answer.metrics["gemini_model_reported"] = 1.0
        except Exception as exc:
            answer = _fallback_answer(
                answer_id=f"a{idx}",
                style=style,
                query=query,
                evidence=evidence,
                error=exc,
            )
        answers.append(answer)
    return select_final_answer(query=query, evidence=evidence, answers=answers)
