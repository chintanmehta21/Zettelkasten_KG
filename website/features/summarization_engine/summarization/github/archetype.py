"""GitHub repository archetype classification.

GitHub extraction is repo-shape-fragile. A single prompt/schema cannot treat
framework READMEs (fastapi), CLI tools (typer), thin-README libraries (requests),
and docs-heavy projects identically without one of them collapsing structured
output. This module classifies the repo before prompting so downstream stages
(prompts, signal extraction, fallback brief) can adapt.

Classification uses deterministic heuristics over ingest metadata + raw_text.
It never calls an LLM.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum


class RepoArchetype(str, Enum):
    FRAMEWORK_API = "framework_api"      # fastapi, starlette, django-rest-framework
    CLI_TOOL = "cli_tool"                # typer, click-apps, ruff, httpie
    LIBRARY_THIN = "library_thin"        # requests, pytz, python-dateutil — short README, core API
    DOCS_HEAVY = "docs_heavy"            # pydantic, sqlalchemy — rich docs/ tree
    APP_EXAMPLE = "app_example"          # example repos, demos, full applications
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class ArchetypeVerdict:
    archetype: RepoArchetype
    confidence: float  # 0..1
    reasons: tuple[str, ...]


_CLI_TOKENS = (
    "cli", "command-line", "command line", "argparse", "click.command",
    "@app.command", "typer.run", "typer(", "console_scripts",
    "entry_points", "bin/",
)
_FRAMEWORK_TOKENS = (
    "asgi", "wsgi", "middleware", "router", "@app.get", "@app.post",
    "openapi", "swagger", "redoc", "starlette", "uvicorn", "fastapi",
    "routes", "endpoints",
)
_LIBRARY_CORE_TOKENS = (
    "import ", "pip install", "from ",
)
_DOCS_HEAVY_MARKERS = (
    "docs/", "mkdocs", "sphinx-build", "readthedocs", "docs.readthedocs",
    "documentation site",
)
_APP_EXAMPLE_MARKERS = (
    "example project", "demo app", "sample application", "reference app",
    "starter template", "tutorial repo",
)


def classify_archetype(
    *,
    raw_text: str,
    metadata: dict | None = None,
) -> ArchetypeVerdict:
    """Classify a GitHub repo by its README + metadata signals.

    Returns the best-fitting archetype with a short reason list. Never raises —
    on empty input returns UNKNOWN with confidence 0.
    """
    text = (raw_text or "")
    lowered = text.lower()
    meta = metadata or {}

    if not lowered.strip():
        return ArchetypeVerdict(RepoArchetype.UNKNOWN, 0.0, ("empty_raw_text",))

    topics = [str(t).lower() for t in (meta.get("topics") or [])]
    lang = str(meta.get("language") or "").lower()
    root_flags = {
        k: bool(v) for k, v in meta.items() if k.startswith("has_") and isinstance(v, bool)
    }

    scores: dict[RepoArchetype, float] = {a: 0.0 for a in RepoArchetype}
    reasons: dict[RepoArchetype, list[str]] = {a: [] for a in RepoArchetype}

    # Framework / API signals
    framework_hits = sum(1 for tok in _FRAMEWORK_TOKENS if tok in lowered)
    if framework_hits >= 2:
        scores[RepoArchetype.FRAMEWORK_API] += min(framework_hits, 6) * 1.0
        reasons[RepoArchetype.FRAMEWORK_API].append(
            f"framework_tokens={framework_hits}"
        )
    if any(t in topics for t in ("web-framework", "api", "asgi", "wsgi", "framework")):
        scores[RepoArchetype.FRAMEWORK_API] += 3.0
        reasons[RepoArchetype.FRAMEWORK_API].append("topics_framework")

    # CLI signals
    cli_hits = sum(1 for tok in _CLI_TOKENS if tok in lowered)
    if cli_hits >= 1:
        scores[RepoArchetype.CLI_TOOL] += min(cli_hits, 5) * 1.5
        reasons[RepoArchetype.CLI_TOOL].append(f"cli_tokens={cli_hits}")
    # Hard markers for CLI
    if re.search(r"(?m)^\s*\$\s+\w+(?:\s+--?\w[\w-]*)+", text):
        scores[RepoArchetype.CLI_TOOL] += 2.5
        reasons[RepoArchetype.CLI_TOOL].append("shell_invocation_with_flags")
    if re.search(r"\bconsole_scripts\b|\[project\.scripts\]|\[tool\.poetry\.scripts\]", text):
        scores[RepoArchetype.CLI_TOOL] += 3.0
        reasons[RepoArchetype.CLI_TOOL].append("entry_points")
    if any(t in topics for t in ("cli", "command-line", "command-line-tool", "console")):
        scores[RepoArchetype.CLI_TOOL] += 3.0
        reasons[RepoArchetype.CLI_TOOL].append("topics_cli")

    # Docs-heavy signals
    if root_flags.get("has_docs"):
        scores[RepoArchetype.DOCS_HEAVY] += 2.0
        reasons[RepoArchetype.DOCS_HEAVY].append("has_docs_dir")
    docs_hits = sum(1 for tok in _DOCS_HEAVY_MARKERS if tok in lowered)
    if docs_hits:
        scores[RepoArchetype.DOCS_HEAVY] += docs_hits * 1.0
        reasons[RepoArchetype.DOCS_HEAVY].append(f"docs_markers={docs_hits}")

    # App / example signals
    if any(m in lowered for m in _APP_EXAMPLE_MARKERS):
        scores[RepoArchetype.APP_EXAMPLE] += 3.0
        reasons[RepoArchetype.APP_EXAMPLE].append("example_marker")
    if any(t in topics for t in ("example", "demo", "template", "starter")):
        scores[RepoArchetype.APP_EXAMPLE] += 2.5
        reasons[RepoArchetype.APP_EXAMPLE].append("topics_example")

    # Library-thin signals (based on README length + presence of imports + low framework/cli scores)
    readme_body = _extract_readme_body(text)
    readme_len = len(readme_body)
    has_import_example = bool(
        re.search(r"(?m)^\s*(from\s+\w|import\s+\w)", readme_body)
    )
    if readme_len and readme_len < 4000 and has_import_example:
        if scores[RepoArchetype.FRAMEWORK_API] < 4 and scores[RepoArchetype.CLI_TOOL] < 4:
            scores[RepoArchetype.LIBRARY_THIN] += 3.0
            reasons[RepoArchetype.LIBRARY_THIN].append(
                f"thin_readme_with_imports len={readme_len}"
            )
    if lang in {"python", "rust", "go", "javascript", "typescript"} and readme_len < 2500:
        scores[RepoArchetype.LIBRARY_THIN] += 1.0
        reasons[RepoArchetype.LIBRARY_THIN].append("short_readme_known_lang")

    # Choose winner
    winner, winning_score = max(scores.items(), key=lambda kv: kv[1])
    total = sum(scores.values())
    if winning_score <= 0 or total <= 0:
        return ArchetypeVerdict(
            RepoArchetype.UNKNOWN,
            0.0,
            ("no_signals",),
        )

    confidence = max(0.0, min(1.0, winning_score / max(total, 1.0)))
    return ArchetypeVerdict(
        archetype=winner,
        confidence=round(confidence, 3),
        reasons=tuple(reasons[winner]) or ("weak_signal",),
    )


def _extract_readme_body(text: str) -> str:
    """Return the README section of the concatenated ingest text.

    The ingestor formats raw_text as ``Repository\n<...>\n\nREADME\n<body>\n\nDocs\n...``.
    We isolate the README block when possible so length-based heuristics do not
    get polluted by Repository / Issues / Commits sections.
    """
    if not text:
        return ""
    match = re.search(r"(?ms)^README\s*\n(.*?)(?:^\s*(Docs|Languages|Issues|Commits|Repository signals|Architecture overview)\s*\n|\Z)", text)
    if not match:
        return text
    return match.group(1).strip()
