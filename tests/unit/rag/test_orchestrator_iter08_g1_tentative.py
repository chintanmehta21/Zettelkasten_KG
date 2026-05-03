"""iter-08 G1: early citations SSE event must carry tentative=True flag."""
import inspect


def test_early_citations_event_has_tentative_flag():
    """The first citations yield (pre-generation) must include tentative=True."""
    from website.features.rag_pipeline import orchestrator
    src = inspect.getsource(orchestrator)
    assert '"tentative": True' in src or "'tentative': True" in src, \
        "tentative=True missing from early citations event"
