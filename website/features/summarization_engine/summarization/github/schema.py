"""Pydantic schema for GitHub-specific structured summary payload."""
from __future__ import annotations

import re

from pydantic import BaseModel, Field, StringConstraints
from pydantic import model_validator
from typing_extensions import Annotated

from website.features.summarization_engine.core.models import DetailedSummarySection


GitHubLabel = Annotated[str, StringConstraints(pattern=r"^[^/]+/[^/]+$", max_length=60)]


class GitHubDetailedSection(DetailedSummarySection):
    module_or_feature: str = ""
    main_stack: list[str] = Field(default_factory=list)
    public_interfaces: list[str] = Field(default_factory=list)
    usability_signals: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _fill_optional_descriptor_fields(self) -> "GitHubDetailedSection":
        if not self.module_or_feature:
            self.module_or_feature = self.heading
        return self


class GitHubStructuredPayload(BaseModel):
    mini_title: GitHubLabel
    architecture_overview: str = Field(..., min_length=50, max_length=500)
    brief_summary: str
    tags: list[str] = Field(..., min_length=7, max_length=10)
    benchmarks_tests_examples: list[str] | None = None
    detailed_summary: list[GitHubDetailedSection] = Field(..., min_length=1)

    @model_validator(mode="after")
    def _normalize_note_facing_fields(self) -> "GitHubStructuredPayload":
        self.tags = _normalize_tags(self.tags, self.detailed_summary)
        self.brief_summary = _repair_brief_summary(
            self.brief_summary,
            architecture_overview=self.architecture_overview,
            detailed_summary=self.detailed_summary,
            tags=self.tags,
            benchmarks_tests_examples=self.benchmarks_tests_examples or [],
        )
        return self


def _normalize_tags(
    tags: list[str],
    detailed_summary: list[GitHubDetailedSection],
) -> list[str]:
    normalized: list[str] = []
    for tag in tags:
        cleaned = re.sub(r"[^a-z0-9+-]+", "-", str(tag).strip().lower()).strip("-")
        if cleaned and cleaned not in normalized:
            normalized.append(cleaned)

    inferred = _infer_tags(detailed_summary)
    reserved = []
    for tag in inferred:
        if tag not in reserved:
            reserved.append(tag)

    topical = [tag for tag in normalized if tag not in reserved]
    final_tags = reserved + topical[: max(0, 10 - len(reserved))]
    while len(final_tags) < 7:
        filler = "open-source"
        if filler not in final_tags:
            final_tags.append(filler)
        else:
            break
    return final_tags[:10]


def _infer_tags(detailed_summary: list[GitHubDetailedSection]) -> list[str]:
    parts: list[str] = []
    for section in detailed_summary:
        parts.extend(
            [
                section.heading,
                section.module_or_feature,
                *section.bullets,
                *section.main_stack,
                *section.public_interfaces,
                *section.usability_signals,
            ]
        )
    lowered = " ".join(parts).lower()

    reserved: list[str] = []
    if "python" in lowered:
        reserved.append("python")
    if any(token in lowered for token in ("api", "openapi", "swagger", "redoc", "@app.get", "@app.post")):
        reserved.append("api-framework")
    if any(token in lowered for token in ("async", "asgi", "websocket")):
        reserved.append("async")
    if "pydantic" in lowered:
        reserved.append("pydantic")
    if "starlette" in lowered:
        reserved.append("starlette")
    if any(token in lowered for token in ("openapi", "swagger ui", "redoc", "json schema")):
        reserved.append("openapi")
    if any(token in lowered for token in ("fastapi dev", "cli", "command-line")):
        reserved.append("cli-tool")
    if not reserved:
        reserved.append("github-project")
    return reserved


def _repair_brief_summary(
    brief_summary: str,
    *,
    architecture_overview: str,
    detailed_summary: list[GitHubDetailedSection],
    tags: list[str],
    benchmarks_tests_examples: list[str],
) -> str:
    """Accept the LLM brief if it's a natural paragraph. Rebuild only when
    the model returns empty or malformed output. The rebuild uses whole
    source sentences so it never dies mid-clause.
    """
    cleaned = re.sub(r"\s+", " ", (brief_summary or "").strip())
    sentences = [
        sentence.strip()
        for sentence in re.split(r"(?<=[.!?])\s+", cleaned)
        if sentence.strip()
    ]
    looks_complete = (
        cleaned
        and cleaned[-1] in ".!?"
        and len(sentences) >= 2
        and len(cleaned) <= 500
    )
    if looks_complete:
        return cleaned

    purpose_sentence = _first_full_sentence(
        _purpose_phrase(
            detailed_summary,
            fallback="This repository provides a documented software project with a defined public surface.",
        )
    )
    architecture_sentence = _first_full_sentence(architecture_overview)
    stack = _stack_phrase(detailed_summary, tags)
    public_surface = _public_surface_phrase(detailed_summary)

    parts: list[str] = []
    if purpose_sentence:
        parts.append(purpose_sentence)
    if architecture_sentence:
        parts.append(f"At a high level, {architecture_sentence.rstrip('.')}.")
    if stack and stack != "documented framework components":
        parts.append(f"The main stack includes {stack}.")
    if public_surface and public_surface != "documented APIs and developer tooling":
        parts.append(f"Documented public surfaces include {public_surface}.")
    rebuilt = " ".join(parts).strip()
    if len(rebuilt) > 500:
        rebuilt = " ".join(parts[: max(2, len(parts) - 1)]).strip()
    return rebuilt[:500].rstrip() or cleaned[:500]


def _first_full_sentence(text: str) -> str:
    cleaned = re.sub(r"\s+", " ", (text or "")).strip()
    if not cleaned:
        return ""
    match = re.match(r"^.+?[.!?](?=\s|$)", cleaned)
    if match:
        return match.group(0).strip()
    return cleaned


def _purpose_phrase(
    detailed_summary: list[GitHubDetailedSection],
    *,
    fallback: str,
) -> str:
    for section in detailed_summary:
        if section.bullets:
            for bullet in section.bullets:
                lowered = bullet.lower()
                if any(token in lowered for token in ("framework", "library", "tool", "build", "api")):
                    return bullet
    for section in detailed_summary:
        if section.bullets:
            return section.bullets[0]
    return fallback


def _stack_phrase(detailed_summary: list[GitHubDetailedSection], tags: list[str]) -> str:
    stack: list[str] = []
    for section in detailed_summary:
        for item in section.main_stack:
            cleaned = item.strip()
            if cleaned and cleaned.lower() not in {s.lower() for s in stack}:
                stack.append(cleaned)
    if not stack:
        stack = [tag for tag in tags if tag in {"python", "pydantic", "starlette", "fastapi", "openapi"}]
    return ", ".join(stack[:4]) if stack else "documented framework components"


def _public_surface_phrase(detailed_summary: list[GitHubDetailedSection]) -> str:
    interfaces: list[str] = []
    for section in detailed_summary:
        for item in section.public_interfaces:
            cleaned = item.strip()
            if cleaned and cleaned not in interfaces:
                interfaces.append(cleaned)
        for bullet in section.bullets:
            for match in re.findall(r"`([^`]+)`", bullet):
                cleaned = match.strip()
                if cleaned and cleaned not in interfaces and (
                    cleaned.startswith("/")
                    or " " in cleaned
                    or cleaned.endswith(")")
                    or cleaned in {"OpenAPI", "OpenAPI 3", "JSON Schema", "Swagger UI", "ReDoc", "ASGI"}
                ):
                    interfaces.append(cleaned)
    if not interfaces:
        return "documented APIs and developer tooling"
    return ", ".join(interfaces[:4])


def _usage_phrase(detailed_summary: list[GitHubDetailedSection]) -> str:
    for section in detailed_summary:
        for bullet in section.bullets:
            lowered = bullet.lower()
            if any(token in lowered for token in ("pip install", "install", "dev command", "fastapi dev", "run", "reload")):
                return _trim_fragment(bullet, 12)
        for values in section.sub_sections.values():
            for bullet in values:
                lowered = bullet.lower()
                if any(token in lowered for token in ("pip install", "install", "dev command", "fastapi dev", "run", "reload")):
                    return _trim_fragment(bullet, 12)
    for section in detailed_summary:
        for item in section.usability_signals:
            cleaned = item.strip()
            if cleaned:
                return _trim_fragment(cleaned, 10)
    return "installation, configuration, and developer usage guidance"


def _examples_phrase(benchmarks_tests_examples: list[str]) -> str:
    if benchmarks_tests_examples:
        return _trim_fragment(benchmarks_tests_examples[0], 14)
    return "tests, examples, or supporting repository evidence"


def _trim_fragment(text: str, max_words: int) -> str:
    cleaned = re.sub(r"\s+", " ", (text or "").strip()).rstrip(",;:")
    words = re.findall(r"\S+", cleaned)
    if len(words) <= max_words:
        return " ".join(words)
    return " ".join(words[:max_words]).rstrip(",;:")


def _as_sentence(text: str) -> str:
    cleaned = re.sub(r"\s+", " ", (text or "").strip()).rstrip(",;:")
    if not cleaned:
        return ""
    if cleaned.endswith((".", "!", "?")):
        return cleaned
    return f"{cleaned}."


def _fit_sentences(sentences: list[str], *, max_chars: int, min_sentences: int = 1) -> str:
    fitted: list[str] = []
    for sentence in sentences:
        if not sentence:
            continue
        candidate = " ".join([*fitted, sentence]).strip()
        if len(candidate) <= max_chars or len(fitted) < min_sentences:
            fitted.append(sentence)
            continue
        break
    return " ".join(fitted).strip()
