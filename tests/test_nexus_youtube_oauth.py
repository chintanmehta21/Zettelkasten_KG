from __future__ import annotations

from unittest.mock import patch

import pytest

from website.experimental_features.nexus.source_ingest.youtube import oauth


def test_get_oauth_config_rejects_non_google_client_id() -> None:
    env = {
        oauth.CLIENT_ID_ENV: "chintan.98.mehta@gmail.com",
        oauth.CLIENT_SECRET_ENV: "secret",
        oauth.REDIRECT_URI_ENV: "https://zettelkasten.in/api/nexus/callback/youtube",
    }
    with patch.dict("os.environ", env, clear=False):
        with pytest.raises(RuntimeError, match="Expected a Google OAuth Client ID"):
            oauth.get_oauth_config()


def test_get_oauth_config_accepts_google_client_id() -> None:
    env = {
        oauth.CLIENT_ID_ENV: "1234567890-abcdef.apps.googleusercontent.com",
        oauth.CLIENT_SECRET_ENV: "secret",
        oauth.REDIRECT_URI_ENV: "https://zettelkasten.in/api/nexus/callback/youtube",
    }
    with patch.dict("os.environ", env, clear=False):
        config = oauth.get_oauth_config()
    assert config.client_id.endswith(".apps.googleusercontent.com")
