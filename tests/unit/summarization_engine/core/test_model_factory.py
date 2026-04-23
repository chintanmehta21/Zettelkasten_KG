import pytest
from pydantic import ValidationError

from website.features.summarization_engine.core.config import (
    load_config,
    reset_config_cache,
)
from website.features.summarization_engine.core.model_factory import (
    build_summary_result_model,
)


def _summary_metadata():
    from website.features.summarization_engine.core.models import (
        SourceType,
        SummaryMetadata,
    )

    return SummaryMetadata(
        source_type=SourceType.YOUTUBE,
        url="https://example.com",
        extraction_confidence="high",
        confidence_reason="ok",
        total_tokens_used=0,
        total_latency_ms=0,
    )


def _valid_model_kwargs(cfg):
    from website.features.summarization_engine.core.models import DetailedSummarySection

    return dict(
        mini_title="t" * cfg.structured_extract.mini_title_max_chars,
        brief_summary="b" * cfg.structured_extract.brief_summary_max_chars,
        tags=[f"tag-{index}" for index in range(cfg.structured_extract.tags_max)],
        detailed_summary=[DetailedSummarySection(heading="H", bullets=["b"])],
        metadata=_summary_metadata(),
    )


def test_build_summary_result_model_applies_config_caps():
    reset_config_cache()
    cfg = load_config()
    Model = build_summary_result_model(cfg)

    from website.features.summarization_engine.core.models import DetailedSummarySection

    with pytest.raises(ValidationError):
        Model(
            mini_title="ok",
            brief_summary="ok",
            tags=["a", "b"],
            detailed_summary=[DetailedSummarySection(heading="H", bullets=["b"])],
            metadata=_summary_metadata(),
        )


def test_build_summary_result_model_accepts_boundary_values():
    reset_config_cache()
    cfg = load_config()
    Model = build_summary_result_model(cfg)

    result = Model(**_valid_model_kwargs(cfg))

    assert len(result.mini_title) == cfg.structured_extract.mini_title_max_chars
    assert len(result.brief_summary) == cfg.structured_extract.brief_summary_max_chars
    assert len(result.tags) == cfg.structured_extract.tags_max


@pytest.mark.parametrize(
    ("field_name", "invalid_value"),
    [
        (
            "mini_title",
            lambda cfg: "t" * (cfg.structured_extract.mini_title_max_chars + 1),
        ),
        (
            "brief_summary",
            lambda cfg: "b" * (cfg.structured_extract.brief_summary_max_chars + 1),
        ),
        (
            "tags",
            lambda cfg: [
                f"tag-{index}" for index in range(cfg.structured_extract.tags_max + 1)
            ],
        ),
    ],
)
def test_build_summary_result_model_rejects_values_past_config_caps(
    field_name, invalid_value
):
    reset_config_cache()
    cfg = load_config()
    Model = build_summary_result_model(cfg)

    with pytest.raises(ValidationError):
        Model(**{**_valid_model_kwargs(cfg), field_name: invalid_value(cfg)})
