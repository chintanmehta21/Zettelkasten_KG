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
