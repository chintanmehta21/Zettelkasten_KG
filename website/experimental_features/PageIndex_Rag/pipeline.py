from __future__ import annotations

import time

from website.features.api_key_switching import get_key_pool

from .candidate_selector import select_candidates
from .evidence import retrieve_evidence
from .generator import generate_three_answers
from .pageindex_adapter import PageIndexAdapter
from .types import PageIndexQueryResult, ZettelRecord
from .workspace import PageIndexWorkspace


async def answer_query(
    *,
    query_id: str,
    query: str,
    zettels: list[ZettelRecord],
    workspace: PageIndexWorkspace,
    adapter: PageIndexAdapter,
    candidate_limit: int,
) -> PageIndexQueryResult:
    timings: dict[str, float] = {}
    t0 = time.perf_counter()
    if workspace.kasten_document is not None:
        docs = {zettel.node_id: workspace.kasten_document for zettel in zettels}
    else:
        docs = {zettel.node_id: workspace.ensure_indexed(zettel) for zettel in zettels}
    timings["index_ms"] = (time.perf_counter() - t0) * 1000
    t1 = time.perf_counter()
    candidates = select_candidates(query=query, zettels=zettels, documents=docs, limit=candidate_limit)
    timings["candidate_ms"] = (time.perf_counter() - t1) * 1000
    t2 = time.perf_counter()
    evidence = retrieve_evidence(adapter=adapter, candidates=candidates, zettels_by_id={z.node_id: z for z in zettels}, query=query)
    timings["evidence_ms"] = (time.perf_counter() - t2) * 1000
    t3 = time.perf_counter()
    answers = await generate_three_answers(key_pool=get_key_pool(), query=query, evidence=evidence)
    timings["generation_ms"] = (time.perf_counter() - t3) * 1000
    timings["total_ms"] = (time.perf_counter() - t0) * 1000
    node_ids = tuple(candidate.node_id for candidate in candidates)
    return PageIndexQueryResult(
        query_id=query_id,
        query=query,
        retrieved_node_ids=node_ids,
        reranked_node_ids=node_ids,
        evidence=tuple(evidence),
        answers=answers,
        timings_ms=timings,
        memory_rss_mb={},
    )
