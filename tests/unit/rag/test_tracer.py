from website.features.rag_pipeline.observability import tracer


def test_record_generation_cost_retries_without_unsupported_kwargs(monkeypatch) -> None:
    class GenerationClient:
        def __init__(self) -> None:
            self.calls = []

        def update_current_generation(self, **kwargs) -> None:
            self.calls.append(kwargs)
            if "token_counts" in kwargs:
                raise TypeError("unexpected keyword argument 'token_counts'")

    client = GenerationClient()
    monkeypatch.setattr(tracer, "get_client", lambda: client)

    tracer.record_generation_cost(
        model="gemini-2.5-flash",
        token_counts={"total": 12},
    )

    assert client.calls == [
        {"model": "gemini-2.5-flash", "token_counts": "***REDACTED***"},
        {"model": "gemini-2.5-flash"},
    ]


def test_record_generation_cost_falls_back_to_span_metadata(monkeypatch) -> None:
    class SpanClient:
        def __init__(self) -> None:
            self.metadata = None

        def update_current_span(self, *, metadata) -> None:
            self.metadata = metadata

    client = SpanClient()
    monkeypatch.setattr(tracer, "get_client", lambda: client)

    tracer.record_generation_cost(
        model="gemini-2.5-flash",
        token_counts={"total": 12},
    )

    assert client.metadata == {
        "model": "gemini-2.5-flash",
        "token_counts": "***REDACTED***",
    }
