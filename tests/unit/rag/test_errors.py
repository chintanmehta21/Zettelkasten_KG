from website.features.rag_pipeline.errors import (
    CriticFailure,
    EmptyScopeError,
    LLMUnavailable,
    RAGError,
    RerankerUnavailable,
    SessionGoneError,
)


def test_error_hierarchy() -> None:
    assert issubclass(EmptyScopeError, RAGError)
    assert issubclass(LLMUnavailable, RAGError)
    assert issubclass(RerankerUnavailable, RAGError)
    assert issubclass(CriticFailure, RAGError)
    assert issubclass(SessionGoneError, RAGError)

