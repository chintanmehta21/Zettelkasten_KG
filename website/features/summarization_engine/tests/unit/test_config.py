"""Tests for engine config loading."""
from website.features.summarization_engine.core.config import EngineConfig, load_config


def test_load_default_config():
    cfg = load_config()
    assert isinstance(cfg, EngineConfig)
    assert cfg.engine.version == "2.0.0"
    assert cfg.gemini.model_chains["pro"][0] == "gemini-2.5-pro"
    assert cfg.gemini.phase_tiers["cod_densify"] == "pro"
    assert cfg.gemini.phase_tiers["structured_extract"] == "flash"
    assert cfg.chain_of_density.iterations == 2
    assert cfg.self_check.patch_threshold == 3
    assert cfg.structured_extract.tags_min == 8
    assert cfg.structured_extract.tags_max == 15
    assert cfg.batch.max_concurrency == 3


def test_config_sources_block():
    cfg = load_config()
    assert "github" in cfg.sources
    assert "twitter" in cfg.sources
    assert cfg.sources["podcast"]["audio_transcription"] is False
