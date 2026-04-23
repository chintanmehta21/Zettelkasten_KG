import pytest
from pydantic import ValidationError

from website.features.summarization_engine.summarization.github.schema import (
    GitHubDetailedSection,
    GitHubStructuredPayload,
)


def _base_payload_kwargs():
    return dict(
        mini_title="openai/gym",
        architecture_overview="Layered architecture with env/agent/wrapper modules interacting via gym.Env API.",
        brief_summary="...",
        tags=[
            "python",
            "reinforcement-learning",
            "env",
            "openai",
            "research",
            "benchmark",
            "ml",
        ],
        benchmarks_tests_examples=["Atari benchmarks in examples/"],
        detailed_summary=[
            GitHubDetailedSection(
                heading="Envs",
                bullets=["Classic control", "Atari", "Mujoco"],
                module_or_feature="gym.envs",
                main_stack=["python", "numpy"],
                public_interfaces=["gym.make()", "env.step()", "env.reset()"],
                usability_signals=["v0.26 release", "CI green", "30+ contributors"],
            )
        ],
    )


def test_github_schema_enforces_owner_repo_label():
    with pytest.raises(ValidationError):
        GitHubStructuredPayload(
            mini_title="just-a-title",
            architecture_overview="Modules A and B interact via message queue " * 3,
            brief_summary="...",
            tags=[
                "python",
                "library",
                "cli",
                "rest-api",
                "fastapi",
                "testing",
                "open-source",
            ],
            detailed_summary=[
                GitHubDetailedSection(
                    heading="Core",
                    bullets=["b"],
                    module_or_feature="core",
                    main_stack=["python"],
                    public_interfaces=["/api/foo"],
                    usability_signals=["tests"],
                )
            ],
        )


def test_github_schema_accepts_valid_label():
    payload = GitHubStructuredPayload(**_base_payload_kwargs())
    assert payload.mini_title == "openai/gym"


def test_github_schema_rejects_short_architecture_overview():
    with pytest.raises(ValidationError):
        GitHubStructuredPayload(
            **{**_base_payload_kwargs(), "architecture_overview": "too short"}
        )


def test_github_schema_rejects_empty_detailed_summary():
    with pytest.raises(ValidationError):
        GitHubStructuredPayload(**{**_base_payload_kwargs(), "detailed_summary": []})


def test_github_schema_normalizes_hash_tags_and_preserves_reserved_github_tags():
    payload = GitHubStructuredPayload(
        **{
            **_base_payload_kwargs(),
            "tags": [
                "#python",
                "#api",
                "#framework",
                "#async",
                "#pydantic",
                "#starlette",
                "#openapi",
            ],
        }
    )

    assert all(not tag.startswith("#") for tag in payload.tags)
    assert "python" in payload.tags
    assert "openapi" in payload.tags


def test_github_schema_repairs_brief_into_multi_sentence_contract():
    payload = GitHubStructuredPayload(
        **{
            **_base_payload_kwargs(),
            "brief_summary": "Tiny two sentence summary. Missing the rubric contract.",
        }
    )

    sentences = [s for s in payload.brief_summary.split(". ") if s.strip()]
    assert len(sentences) >= 5
    assert "Documented public surfaces include" in payload.brief_summary
    assert len(payload.brief_summary) <= 400
    assert "Its." not in payload.brief_summary


def test_github_schema_derives_public_interfaces_and_usage_from_section_content():
    payload = GitHubStructuredPayload(
        mini_title="fastapi/fastapi",
        architecture_overview=(
            "FastAPI is an ASGI framework built on Starlette and Pydantic for API "
            "validation, routing, and documentation."
        ),
        brief_summary="Short broken brief",
        tags=["python", "api", "framework", "async", "pydantic", "starlette", "openapi"],
        benchmarks_tests_examples=["TechEmpower benchmarks rank the framework highly."],
        detailed_summary=[
            GitHubDetailedSection(
                heading="APIs & Features",
                bullets=[
                    "Serves Swagger UI (`/docs`) and ReDoc (`/redoc`) by default.",
                    "The `fastapi dev` CLI command starts a development server with reload.",
                ],
                sub_sections={
                    "Installation": [
                        'Standard installation uses `pip install "fastapi[standard]"`.'
                    ]
                },
                module_or_feature="api",
                main_stack=["Python", "Starlette", "Pydantic"],
                public_interfaces=[],
                usability_signals=[],
            )
        ],
    )

    assert "/docs" in payload.brief_summary or "/redoc" in payload.brief_summary
    assert "pip install" in payload.brief_summary or "fastapi dev" in payload.brief_summary


def test_github_schema_backfills_missing_module_or_feature():
    payload = GitHubStructuredPayload(
        mini_title="psf/requests",
        architecture_overview=(
            "Requests is a Python HTTP client library with a small core API and layered "
            "request/response handling."
        ),
        brief_summary="Broken summary",
        tags=["python", "http", "library", "client", "requests", "api", "web"],
        benchmarks_tests_examples=None,
        detailed_summary=[
            GitHubDetailedSection(
                heading="Core API",
                bullets=["High-level HTTP client for Python."],
                public_interfaces=["requests.get"],
                main_stack=["Python"],
                usability_signals=[],
            )
        ],
    )

    assert payload.detailed_summary[0].module_or_feature == "Core API"
