from __future__ import annotations

from unittest.mock import patch

from website.experimental_features.nexus.source_ingest.common.models import NexusProvider
from website.experimental_features.nexus.source_ingest.github import oauth as github_oauth
from website.experimental_features.nexus.source_ingest.reddit import oauth as reddit_oauth
from website.experimental_features.nexus.source_ingest.twitter import oauth as twitter_oauth


def test_github_authorization_url_uses_shared_oauth_state() -> None:
    env = {
        github_oauth.CLIENT_ID_ENV: "github-client",
        github_oauth.CLIENT_SECRET_ENV: "github-secret",
        github_oauth.REDIRECT_URI_ENV: "https://zettelkasten.app/api/nexus/callback/github",
    }
    fake_record = type("Record", (), {"expires_at": "2099-01-01T00:00:00+00:00"})()
    with (
        patch.dict("os.environ", env, clear=False),
        patch.object(github_oauth, "issue_oauth_state", return_value=("state-token", fake_record)),
    ):
        result = github_oauth.build_authorization_url(auth_user_sub="user-1")

    assert result.provider == NexusProvider.GITHUB
    assert "state=state-token" in result.authorization_url
    assert "scope=repo+read%3Auser" in result.authorization_url


def test_reddit_authorization_url_uses_expected_scope_and_duration() -> None:
    env = {
        reddit_oauth.CLIENT_ID_ENV: "reddit-client",
        reddit_oauth.REDIRECT_URI_ENV: "https://zettelkasten.app/api/nexus/callback/reddit",
    }
    fake_record = type("Record", (), {"expires_at": "2099-01-01T00:00:00+00:00"})()
    with (
        patch.dict("os.environ", env, clear=False),
        patch.object(reddit_oauth, "issue_oauth_state", return_value=("reddit-state", fake_record)),
    ):
        result = reddit_oauth.build_authorization_url(auth_user_sub="user-1")

    assert result.provider == NexusProvider.REDDIT
    assert "duration=permanent" in result.authorization_url
    assert "scope=identity+history+read" in result.authorization_url


def test_twitter_authorization_url_includes_pkce_challenge() -> None:
    env = {
        twitter_oauth.CLIENT_ID_ENV: "twitter-client",
        twitter_oauth.REDIRECT_URI_ENV: "https://zettelkasten.app/api/nexus/callback/twitter",
    }
    fake_record = type("Record", (), {"expires_at": "2099-01-01T00:00:00+00:00"})()
    with (
        patch.dict("os.environ", env, clear=False),
        patch.object(twitter_oauth, "generate_code_verifier", return_value="verifier-123"),
        patch.object(twitter_oauth, "build_code_challenge", return_value="challenge-456"),
        patch.object(twitter_oauth, "issue_oauth_state", return_value=("twitter-state", fake_record)),
    ):
        result = twitter_oauth.build_authorization_url(auth_user_sub="user-1")

    assert result.provider == NexusProvider.TWITTER
    assert "state=twitter-state" in result.authorization_url
    assert "code_challenge=challenge-456" in result.authorization_url
