"""Tests for engine config loading."""
from website.features.summarization_engine.core.config import (
    EngineConfig,
    load_config,
    reset_config_cache,
)


def test_load_default_config():
    cfg = load_config()
    assert isinstance(cfg, EngineConfig)
    assert cfg.engine.version == "2.0.0"
    assert cfg.gemini.model_chains["pro"][0] == "gemini-2.5-pro"
    assert cfg.gemini.phase_tiers["cod_densify"] == "pro"
    assert cfg.gemini.phase_tiers["structured_extract"] == "flash"
    assert cfg.chain_of_density.iterations == 2
    assert cfg.self_check.patch_threshold == 3
    assert cfg.structured_extract.tags_min == 7
    assert cfg.structured_extract.tags_max == 10
    assert cfg.batch.max_concurrency == 3


def test_config_sources_block():
    cfg = load_config()
    assert "github" in cfg.sources
    assert "twitter" in cfg.sources
    assert cfg.sources["podcast"]["audio_transcription"] is False


def test_structured_extract_loads_new_char_caps():
    reset_config_cache()
    cfg = load_config()
    assert cfg.structured_extract.mini_title_max_chars == 60
    assert cfg.structured_extract.brief_summary_max_chars == 500
    assert cfg.structured_extract.brief_summary_max_sentences == 6
    assert cfg.structured_extract.brief_summary_min_sentences == 3
    assert cfg.structured_extract.detailed_summary_max_bullets_per_section == 8
    assert cfg.structured_extract.detailed_summary_min_bullets_per_section == 1
    assert cfg.structured_extract.tags_min == 7
    assert cfg.structured_extract.tags_max == 10
