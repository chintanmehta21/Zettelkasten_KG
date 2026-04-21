from website.features.summarization_engine.core.config import load_config, reset_config_cache
from website.features.summarization_engine.core.model_factory import build_summary_result_model


def test_build_summary_result_model_applies_config_caps():
    reset_config_cache()
    cfg = load_config()
    Model = build_summary_result_model(cfg)

    import pytest
    from pydantic import ValidationError

    from website.features.summarization_engine.core.models import (
        DetailedSummarySection,
        SourceType,
        SummaryMetadata,
    )

    meta_args = dict(
        source_type=SourceType.YOUTUBE,
        url="https://example.com",
        extraction_confidence="high",
        confidence_reason="ok",
        total_tokens_used=0,
        total_latency_ms=0,
    )
    with pytest.raises(ValidationError):
        Model(
            mini_title="ok",
            brief_summary="ok",
            tags=["a", "b"],
            detailed_summary=[DetailedSummarySection(heading="H", bullets=["b"])],
            metadata=SummaryMetadata(**meta_args),
        )
