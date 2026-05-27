"""End-to-end test for POST /api/feedback/submit with a mocked Slack client."""
from __future__ import annotations


import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, MagicMock

from website.features.feedback.api.routes import build_router
from website.features.feedback.api.deps import get_feedback_rate_limiter
from website.features.feedback.slack.client import SlackPostError


@pytest.fixture(autouse=True)
def _reset_limiter():
    get_feedback_rate_limiter.cache_clear()
    yield
    get_feedback_rate_limiter.cache_clear()


def _make_app(fake_slack_creds: dict, slack_client: MagicMock) -> FastAPI:
    app = FastAPI()
    app.include_router(
        build_router(slack_client_factory=lambda: slack_client),
        prefix="/api/feedback",
    )
    return app


@pytest.fixture
def mock_slack() -> MagicMock:
    m = MagicMock()
    m.upload_image = AsyncMock(return_value="F123")
    m.post_message = AsyncMock(return_value="1716800000.001")
    return m


def test_submit_minimal_authenticated_payload_returns_202(
    fake_slack_creds: dict, mock_slack: MagicMock,
) -> None:
    app = _make_app(fake_slack_creds, mock_slack)
    client = TestClient(app)
    r = client.post(
        "/api/feedback/submit",
        data={
            "intent": "issue",
            "subject": "Smoke",
            "description": "This is a description of a smoke test scenario.",
            "follow_up_email": "false",
        },
        headers={"cf-ipcountry": "IN"},
    )
    assert r.status_code == 202, r.text
    body = r.json()
    assert body["status"] == "accepted"
    assert body["feedback_id"].startswith("FB-")
    mock_slack.post_message.assert_awaited_once()


def test_submit_with_images_uploads_each(
    fake_slack_creds: dict, mock_slack: MagicMock, jpeg_bytes_no_exif: bytes,
) -> None:
    app = _make_app(fake_slack_creds, mock_slack)
    client = TestClient(app)
    r = client.post(
        "/api/feedback/submit",
        data={"intent": "suggestion", "subject": "Idea",
              "description": "Long enough description here, more than ten chars."},
        files=[
            ("images", ("a.jpg", jpeg_bytes_no_exif, "image/jpeg")),
            ("images", ("b.jpg", jpeg_bytes_no_exif, "image/jpeg")),
        ],
        headers={"cf-ipcountry": "JP"},
    )
    assert r.status_code == 202, r.text
    assert mock_slack.upload_image.await_count == 2


def test_oversized_image_returns_413(
    fake_slack_creds: dict, mock_slack: MagicMock,
) -> None:
    app = _make_app(fake_slack_creds, mock_slack)
    client = TestClient(app)
    oversized = b"x" * (5 * 1024 * 1024 + 1)
    r = client.post(
        "/api/feedback/submit",
        data={"intent": "issue", "subject": "Image",
              "description": "Long enough description here."},
        files=[("images", ("big.jpg", oversized, "image/jpeg"))],
    )
    assert r.status_code == 413


def test_svg_upload_returns_400(
    fake_slack_creds: dict, mock_slack: MagicMock,
) -> None:
    app = _make_app(fake_slack_creds, mock_slack)
    client = TestClient(app)
    svg = b'<?xml version="1.0"?><svg xmlns="http://www.w3.org/2000/svg"></svg>'
    r = client.post(
        "/api/feedback/submit",
        data={"intent": "issue", "subject": "SVG",
              "description": "Long enough description here."},
        files=[("images", ("shot.svg", svg, "image/svg+xml"))],
    )
    assert r.status_code == 400


def test_heic_upload_returns_400(
    fake_slack_creds: dict, mock_slack: MagicMock, jpeg_bytes_no_exif: bytes,
) -> None:
    app = _make_app(fake_slack_creds, mock_slack)
    client = TestClient(app)
    r = client.post(
        "/api/feedback/submit",
        data={"intent": "issue", "subject": "HEIC",
              "description": "Long enough description here."},
        files=[("images", ("shot.heic", jpeg_bytes_no_exif, "image/heic"))],
    )
    assert r.status_code == 400


def test_submit_with_anon_follow_up_email_posts_email_in_context(
    fake_slack_creds: dict, mock_slack: MagicMock,
) -> None:
    app = _make_app(fake_slack_creds, mock_slack)
    client = TestClient(app)
    r = client.post(
        "/api/feedback/submit",
        data={
            "intent": "issue",
            "subject": "Follow up",
            "description": "Long enough description here, more than ten chars.",
            "anon_name": "Sakura",
            "follow_up_email": "true",
            "anon_email": "sakura@example.com",
        },
        headers={"cf-ipcountry": "IN"},
    )
    assert r.status_code == 202, r.text
    blocks = mock_slack.post_message.call_args.kwargs["blocks"]
    context = next(b for b in blocks if b["type"] == "context")
    assert "Sakura" in context["elements"][0]["text"]
    assert "sakura@example.com" in context["elements"][0]["text"]


def test_slack_delivery_failure_returns_502_not_false_success(
    fake_slack_creds: dict, mock_slack: MagicMock,
) -> None:
    mock_slack.post_message = AsyncMock(side_effect=SlackPostError("channel_not_found"))
    app = _make_app(fake_slack_creds, mock_slack)
    client = TestClient(app)
    r = client.post(
        "/api/feedback/submit",
        data={
            "intent": "issue",
            "subject": "Slack failure",
            "description": "Long enough description here, more than ten chars.",
        },
        headers={"cf-ipcountry": "IN"},
    )
    assert r.status_code == 502
    assert "feedback_id" not in r.text


def test_subject_validation_returns_422(
    fake_slack_creds: dict, mock_slack: MagicMock,
) -> None:
    app = _make_app(fake_slack_creds, mock_slack)
    client = TestClient(app)
    r = client.post(
        "/api/feedback/submit",
        data={"intent": "issue", "subject": "",
              "description": "Long enough description here."},
    )
    assert r.status_code == 422


def test_invalid_intent_returns_422(
    fake_slack_creds: dict, mock_slack: MagicMock,
) -> None:
    app = _make_app(fake_slack_creds, mock_slack)
    client = TestClient(app)
    r = client.post(
        "/api/feedback/submit",
        data={"intent": "praise", "subject": "x",
              "description": "Long enough description here."},
    )
    assert r.status_code == 422


def test_invalid_follow_up_email_returns_422(
    fake_slack_creds: dict, mock_slack: MagicMock,
) -> None:
    app = _make_app(fake_slack_creds, mock_slack)
    client = TestClient(app)
    r = client.post(
        "/api/feedback/submit",
        data={
            "intent": "issue",
            "subject": "x",
            "description": "Long enough description here.",
            "follow_up_email": "true",
            "anon_email": "not-an-email",
        },
    )
    assert r.status_code == 422


def test_rate_limit_429_after_cap(
    fake_slack_creds: dict, mock_slack: MagicMock,
) -> None:
    """Hammer the endpoint 11x; the 11th must 429."""
    from website.features.feedback.api.deps import DEFAULT_DAILY_CAP
    app = _make_app(fake_slack_creds, mock_slack)
    client = TestClient(app)
    payload = {"intent": "issue", "subject": "x",
               "description": "Long enough description here."}
    headers = {"cf-ipcountry": "IN"}
    for i in range(DEFAULT_DAILY_CAP):
        r = client.post("/api/feedback/submit", data=payload, headers=headers)
        assert r.status_code == 202, f"hit {i} should be 202: {r.text}"
    r = client.post("/api/feedback/submit", data=payload, headers=headers)
    assert r.status_code == 429
    assert "Retry-After" in r.headers


def test_health_endpoint_returns_200(
    fake_slack_creds: dict, mock_slack: MagicMock,
) -> None:
    app = _make_app(fake_slack_creds, mock_slack)
    client = TestClient(app)
    r = client.get("/api/feedback/health")
    assert r.status_code == 200
    assert r.json() == {"ok": True}
