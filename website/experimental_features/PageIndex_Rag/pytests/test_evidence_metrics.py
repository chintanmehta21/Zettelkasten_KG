from website.experimental_features.PageIndex_Rag.evidence import retrieve_evidence
from website.experimental_features.PageIndex_Rag.metrics import mrr, ndcg_at_k, recall_at_k
from website.experimental_features.PageIndex_Rag.types import CandidateDocument, ZettelRecord


class FakeAdapter:
    def get_document_structure(self, doc_id):
        return [{"title": "Summary", "line_num": 3, "node_id": "0001"}]

    def get_page_content(self, doc_id, pages):
        return [{"page": 3, "content": "Evidence text"}]


def test_retrieve_evidence_maps_candidate_to_citation():
    zettel = ZettelRecord("u", "n", "Title", "summary", "body", "web", "https://x", (), {})
    evidence = retrieve_evidence(
        adapter=FakeAdapter(),
        candidates=[CandidateDocument("n", "doc", "Title", 2.0)],
        zettels_by_id={"n": zettel},
        query="question",
    )
    assert evidence[0].node_id == "n"
    assert evidence[0].source_url == "https://x"
    assert evidence[0].line_range == "3"


def test_retrieval_metrics():
    retrieved = ["a", "b", "c"]
    expected = ["b", "d"]
    assert recall_at_k(retrieved, expected, 3) == 0.5
    assert mrr(retrieved, expected) == 0.5
    assert 0.0 < ndcg_at_k(retrieved, expected, 3) <= 1.0
