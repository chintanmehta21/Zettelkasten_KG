from website.experimental_features.PageIndex_Rag.evidence import (
    plan_retrieval_nodes,
    retrieve_evidence,
)
from website.experimental_features.PageIndex_Rag.metrics import mrr, ndcg_at_k, recall_at_k
from website.experimental_features.PageIndex_Rag.types import CandidateDocument, ZettelRecord


class FakeAdapter:
    def get_document_structure(self, doc_id):
        return [
            {"title": "Title", "line_num": 1, "node_id": "0001", "level": 1},
            {"title": "Metadata", "line_num": 3, "node_id": "0002", "level": 2},
            {"title": "Summary", "line_num": 8, "node_id": "0003", "level": 2},
            {"title": "Captured Content", "line_num": 12, "node_id": "0004", "level": 2},
        ]

    def get_page_content(self, doc_id, pages):
        return [{"page": pages, "content": f"Evidence text from {pages}"}]


class FakeKastenAdapter:
    def get_document_structure(self, doc_id):
        return [
            {"title": "Kasten scope", "line_num": 1, "node_id": "0001", "level": 1},
            {"title": "The Pragmatic Engineer", "line_num": 3, "node_id": "0002", "level": 2},
            {"title": "Summary", "line_num": 8, "node_id": "0003", "level": 3},
            {"title": "Captured Content", "line_num": 12, "node_id": "0004", "level": 3},
            {"title": "zk-org/zk", "line_num": 24, "node_id": "0005", "level": 2},
            {"title": "Summary", "line_num": 29, "node_id": "0006", "level": 3},
            {"title": "Captured Content", "line_num": 33, "node_id": "0007", "level": 3},
        ]

    def get_page_content(self, doc_id, pages):
        return [{"page": pages, "content": f"Evidence text from {pages}"}]


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
    assert evidence[0].line_range == "8,12"


def test_retrieve_evidence_fetches_summary_and_captured_content():
    zettel = ZettelRecord(
        "u",
        "gh-zk-org-zk",
        "zk-org/zk",
        "zk is written in Go.",
        "zk stores notes as Markdown with wikilinks and hashtags.",
        "github",
        "https://github.com/zk-org/zk",
        (),
        {},
    )
    evidence = retrieve_evidence(
        adapter=FakeAdapter(),
        candidates=[CandidateDocument("gh-zk-org-zk", "doc", "zk-org/zk", 2.0)],
        zettels_by_id={"gh-zk-org-zk": zettel},
        query="Which programming language and note file format does zk use?",
    )
    assert "Go" in evidence[0].text
    assert "Markdown" in evidence[0].text
    assert "Evidence text from 8,12" in evidence[0].text


def test_retrieve_evidence_scopes_kasten_tree_to_candidate_section():
    zettel = ZettelRecord(
        "u",
        "gh-zk-org-zk",
        "zk-org/zk",
        "zk is written in Go.",
        "zk stores notes as Markdown with wikilinks and hashtags.",
        "github",
        "https://github.com/zk-org/zk",
        (),
        {},
    )
    evidence = retrieve_evidence(
        adapter=FakeKastenAdapter(),
        candidates=[CandidateDocument("gh-zk-org-zk", "kasten-doc", "zk-org/zk", 2.0)],
        zettels_by_id={"gh-zk-org-zk": zettel},
        query="Which programming language and note file format does zk use?",
    )
    assert evidence[0].line_range == "29,33"
    assert "Evidence text from 29,33" in evidence[0].text
    assert "Evidence text from 8,12" not in evidence[0].text


def test_plan_retrieval_nodes_prefers_query_matching_sections():
    tree = [
        {"title": "Title", "line_num": 1, "node_id": "0001", "level": 1},
        {"title": "Metadata", "line_num": 3, "node_id": "0002", "level": 2},
        {"title": "Summary", "line_num": 8, "node_id": "0003", "level": 2, "summary": "plain overview"},
        {
            "title": "Captured Content",
            "line_num": 12,
            "node_id": "0004",
            "level": 2,
            "summary": "Go Markdown wikilinks",
        },
    ]
    selected = plan_retrieval_nodes(tree, "What format uses Markdown wikilinks?")
    assert [node["title"] for node in selected] == ["Captured Content", "Summary"]


def test_retrieval_metrics():
    retrieved = ["a", "b", "c"]
    expected = ["b", "d"]
    assert recall_at_k(retrieved, expected, 3) == 0.5
    assert mrr(retrieved, expected) == 0.5
    assert 0.0 < ndcg_at_k(retrieved, expected, 3) <= 1.0
