"""Tests for the GEMINI_API_KEYS env var fallback in init_key_pool()."""
from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def reset_pool_singleton():
    """Reset the module-level _pool singleton between tests."""
    import website.features.api_key_switching as pkg

    pkg._pool = None
    yield
    pkg._pool = None


def test_loads_keys_from_env_var_when_no_file(monkeypatch, tmp_path):
    """GEMINI_API_KEYS env var (comma-separated) is used when no api_env file exists."""
    import website.features.api_key_switching as pkg

    monkeypatch.setattr(pkg, "_API_ENV_PATHS", [str(tmp_path / "no_such_file")])
    monkeypatch.setenv("GEMINI_API_KEYS", "key_alpha,key_beta,key_gamma")

    pool = pkg.init_key_pool()

    assert pool is not None
    assert pool._keys == ["key_alpha", "key_beta", "key_gamma"]


def test_env_var_strips_whitespace_and_skips_empty(monkeypatch, tmp_path):
    """Whitespace and empty entries are tolerated in GEMINI_API_KEYS."""
    import website.features.api_key_switching as pkg

    monkeypatch.setattr(pkg, "_API_ENV_PATHS", [str(tmp_path / "no_such_file")])
    monkeypatch.setenv("GEMINI_API_KEYS", " key_one , ,key_two,  ")

    pool = pkg.init_key_pool()

    assert pool._keys == ["key_one", "key_two"]


def test_file_takes_priority_over_env_var(monkeypatch, tmp_path):
    """If an api_env file exists, it wins over GEMINI_API_KEYS."""
    import website.features.api_key_switching as pkg

    api_env_file = tmp_path / "api_env"
    api_env_file.write_text("file_key_1\nfile_key_2\n", encoding="utf-8")

    monkeypatch.setattr(pkg, "_API_ENV_PATHS", [str(api_env_file)])
    monkeypatch.setenv("GEMINI_API_KEYS", "env_key_1,env_key_2,env_key_3")

    pool = pkg.init_key_pool()

    assert pool._keys == ["file_key_1", "file_key_2"]


def test_falls_back_to_single_key_when_env_var_empty(monkeypatch, tmp_path):
    """When GEMINI_API_KEYS is empty/missing, fall back to settings.gemini_api_key."""
    import website.features.api_key_switching as pkg

    monkeypatch.setattr(pkg, "_API_ENV_PATHS", [str(tmp_path / "no_such_file")])
    monkeypatch.delenv("GEMINI_API_KEYS", raising=False)

    class FakeSettings:
        gemini_api_key = "single_legacy_key"

    monkeypatch.setattr(pkg, "get_settings", lambda: FakeSettings())

    pool = pkg.init_key_pool()

    assert pool._keys == ["single_legacy_key"]


def test_raises_when_no_source_yields_keys(monkeypatch, tmp_path):
    """Empty file paths + empty env var + empty single-key -> ValueError."""
    import website.features.api_key_switching as pkg

    monkeypatch.setattr(pkg, "_API_ENV_PATHS", [str(tmp_path / "no_such_file")])
    monkeypatch.delenv("GEMINI_API_KEYS", raising=False)

    class FakeSettings:
        gemini_api_key = ""

    monkeypatch.setattr(pkg, "get_settings", lambda: FakeSettings())

    with pytest.raises(ValueError, match="No Gemini API keys"):
        pkg.init_key_pool()
