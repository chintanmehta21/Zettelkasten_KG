"""GitHub per-source summarizer (3-call DenseVerify pipeline).

Call budget (<=3 per zettel):
  1. DenseVerifier (pro) — dense + verify + archetype signal (from DV's
     ``archetype`` hint field, informational; ``classify_archetype`` is
     authoritative because it folds README signals the LLM cannot see).
  2. StructuredExtractor (flash) — schema-shaped GitHub payload, guided by
     DV's ``missing_facts`` via ``missing_facts_hint``.
  3. Optional flash patch — only when the structured brief still omits a
     DV-flagged fact (pragmatic substring probe).

README signals (install commands, public surfaces, stack) are extracted
deterministically before the LLM ever runs; they feed both the prompt
(must-preserve slots) and the graceful-fallback builder so held-out URLs
(`psf/requests`, `tiangolo/typer`) retain faithfulness even when the flash
call emits a schema-invalid payload.
"""
from __future__ import annotations

import json
import logging
import re
import time

from pydantic import BaseModel

from website.features.summarization_engine.core.config import EngineConfig
from website.features.summarization_engine.core.gemini_client import TieredGeminiClient
from website.features.summarization_engine.core.models import (
    IngestResult,
    SourceType,
    SummaryResult,
)
from website.features.summarization_engine.summarization import register_summarizer
from website.features.summarization_engine.summarization.base import BaseSummarizer
from website.features.summarization_engine.summarization.common.dense_verify_runner import (
    maybe_patch_structured_brief,
    run_dense_verify,
)
from website.features.summarization_engine.summarization.common.structured import (
    StructuredExtractor,
)
from website.features.summarization_engine.summarization.github.archetype import (
    RepoArchetype,
    classify_archetype,
)
from website.features.summarization_engine.summarization.github.prompts import (
    source_context_for,
)
from website.features.summarization_engine.summarization.github.readme_signals import (
    ReadmeSignals,
    extract_signals,
)
from website.features.summarization_engine.summarization.github.schema import (
    GitHubDetailedSection,
    GitHubStructuredPayload,
)

_log = logging.getLogger(__name__)


class GitHubSummarizer(BaseSummarizer):
    source_type = SourceType.GITHUB

    def __init__(self, gemini_client: TieredGeminiClient, config):
        super().__init__(gemini_client, config)
        from website.features.summarization_engine.core.config import load_config

        self._engine_config = load_config()

    async def summarize(self, ingest: IngestResult) -> SummaryResult:
        start = time.perf_counter()

        verdict = classify_archetype(
            raw_text=ingest.raw_text or "",
            metadata=ingest.metadata or {},
        )
        signals = extract_signals(
            raw_text=ingest.raw_text or "",
            metadata=ingest.metadata or {},
        )
        _log.info(
            "github.summarizer archetype=%s confidence=%.3f reasons=%s",
            verdict.archetype.value,
            verdict.confidence,
            ",".join(verdict.reasons),
        )

        # Call 1 — DenseVerify (pro). DV returns a dense verified summary plus
        # ``missing_facts``/``archetype`` hints. We use the dense text as the
        # input to StructuredExtractor so it extracts from a higher-fidelity
        # surface than the raw README.
        dv = await run_dense_verify(client=self._client, ingest=ingest)

        def _prompt_builder(
            ingest_inner: IngestResult, summary_text: str, schema_json: str
        ) -> str:
            return (
                f"{source_context_for(verdict.archetype, signals)}\n\n"
                f"Return a JSON object that EXACTLY matches the following JSON schema "
                f"for class GitHubStructuredPayload. Populate every required field "
                f"from the SUMMARY below - do not invent facts. Use temperature 0 judgment.\n\n"
                f"SCHEMA:\n{schema_json}\n\n"
                "Do NOT wrap in markdown code blocks. Return raw JSON only.\n\n"
                f"SUMMARY:\n{summary_text}"
            )

        def _fallback_builder(
            ingest_inner: IngestResult, summary_text: str, _config: EngineConfig
        ) -> BaseModel:
            return _build_graceful_fallback(
                ingest=ingest_inner,
                summary_text=summary_text,
                archetype=verdict.archetype,
                signals=signals,
            )

        extractor = StructuredExtractor(
            self._client,
            self._engine_config,
            payload_class=GitHubStructuredPayload,
            fallback_builder=_fallback_builder,
            prompt_builder=_prompt_builder,
            missing_facts_hint=list(dv.missing_facts),
        )
        latency_ms = int((time.perf_counter() - start) * 1000)

        # Call 2 — structured extraction (flash).
        result = await extractor.extract(
            ingest,
            dv.dense_text or ingest.raw_text or "",
            pro_tokens=0,
            flash_tokens=0,
            latency_ms=latency_ms,
            cod_iterations_used=0,
            self_check_missing_count=len(dv.missing_facts),
            patch_applied=False,
        )

        # Call 3 (optional) — flash patch when DV-flagged facts remain omitted
        # from the structured payload. No-op when DV had no missing_facts.
        payload_json = ""
        if result.metadata is not None and result.metadata.structured_payload:
            try:
                payload_json = json.dumps(result.metadata.structured_payload)
            except Exception:  # noqa: BLE001
                payload_json = str(result.metadata.structured_payload)
        new_brief, patch_applied, patch_tokens = await maybe_patch_structured_brief(
            client=self._client,
            current_brief=result.brief_summary,
            dv=dv,
            extracted_payload_json=payload_json,
        )
        if patch_applied:
            result.brief_summary = new_brief
            if result.metadata is not None:
                result.metadata.patch_applied = True
                result.metadata.gemini_flash_tokens = (
                    int(result.metadata.gemini_flash_tokens or 0) + patch_tokens
                )
                result.metadata.total_tokens_used = (
                    int(result.metadata.total_tokens_used or 0) + patch_tokens
                )

        # Stash archetype verdict + DV signals in metadata so eval/debug can see
        # routing decisions even when the fallback path engaged.
        if result.metadata is not None:
            extras = dict(result.metadata.structured_payload or {}) if result.metadata.structured_payload else {}
            extras.setdefault("_github_archetype", {
                "archetype": verdict.archetype.value,
                "confidence": verdict.confidence,
                "reasons": list(verdict.reasons),
            })
            if dv.archetype:
                extras.setdefault("_dense_verify", {
                    "archetype": dv.archetype,
                    "missing_fact_count": len(dv.missing_facts),
                })
            result.metadata.structured_payload = extras
        return result


def _build_graceful_fallback(
    *,
    ingest: IngestResult,
    summary_text: str,
    archetype: RepoArchetype,
    signals: ReadmeSignals,
) -> GitHubStructuredPayload:
    """Build a minimal but faithful GitHub payload from deterministic signals.

    Used when structured extraction validation fails. Prior behavior emitted
    zeros/boilerplate for brief/detailed/tags, which zeroed the composite
    score on held-out URLs (`psf/requests`, `tiangolo/typer`). This path
    ensures the fallback still carries the canonical owner/repo label,
    signal-derived tags, README-grounded brief, and an archetype-aware
    detailed section — enough to preserve faithfulness while clearly
    flagged as schema_fallback in metadata.
    """
    owner_repo = _canonical_owner_repo(ingest)
    repo_name = owner_repo.split("/", 1)[1].strip().lower() if "/" in owner_repo else ""
    purpose = signals.purpose_sentence.strip() or _first_paragraph(summary_text) or (
        f"{owner_repo} is a documented software project."
    )
    # Filter out obvious junk fragments from signal-derived pieces so the
    # fallback brief doesn't surface unicode garbage or broken prose.
    clean_surfaces = [s for s in signals.any_public_surface() if _looks_clean_surface(s)]
    clean_stack = [
        s for s in signals.stack
        if _looks_clean(s) and s.strip().lower() != repo_name
    ]
    stack_phrase = ", ".join(clean_stack[:4]) if clean_stack else "the documented stack"
    surface_phrase = ", ".join(clean_surfaces[:4]) if clean_surfaces else "the documented public API"
    install_phrase = signals.install_cmds[0] if signals.install_cmds and _looks_clean(signals.install_cmds[0]) else "the documented installation method"

    archetype_hint = {
        RepoArchetype.FRAMEWORK_API: "a framework / API toolkit",
        RepoArchetype.CLI_TOOL: "a command-line tool",
        RepoArchetype.LIBRARY_THIN: "a library with a focused public API",
        RepoArchetype.DOCS_HEAVY: "a documentation-heavy project",
        RepoArchetype.APP_EXAMPLE: "an example / starter application",
        RepoArchetype.UNKNOWN: "a software repository",
    }[archetype]

    # When signals are thin, lean on the densified summary rather than emit
    # the formulaic five-sentence stub.
    dense_paragraph = _first_paragraph(summary_text)
    use_dense = (
        len(clean_surfaces) < 2
        and (not dense_paragraph or len(dense_paragraph) >= 120)
        and dense_paragraph
    )
    if use_dense:
        brief = dense_paragraph[:500]
        if len(brief) < 120:
            brief = brief + " " + _as_sentence(purpose)
    else:
        brief_sentences = [
            _as_sentence(purpose),
            _as_sentence(f"It is {archetype_hint} built with {stack_phrase}"),
            _as_sentence(f"Documented public surfaces include {surface_phrase}"),
            _as_sentence(f"Users adopt it via {install_phrase}"),
        ]
        brief = _fit_sentences(brief_sentences, max_chars=450, min_sentences=3)

    architecture_overview = _fit_architecture_overview(
        purpose=purpose,
        stack=tuple(clean_stack),
        surfaces=tuple(clean_surfaces),
        archetype_hint=archetype_hint,
    )

    # Build one detailed section per meaningful signal bucket
    clean_install = [c for c in signals.install_cmds if _looks_clean(c)]
    bullets: list[str] = []
    if purpose:
        bullets.append(purpose)
    if clean_surfaces:
        bullets.append("Public surfaces: " + ", ".join(f"`{s}`" for s in clean_surfaces[:6]))
    if clean_install:
        bullets.append("Install: " + " ; ".join(f"`{c}`" for c in clean_install[:3]))
    if signals.first_code_block:
        snippet = signals.first_code_block.splitlines()[0][:120]
        if snippet:
            bullets.append(f"Usage snippet: `{snippet}`")
    if not bullets:
        bullets = [f"{owner_repo} summary reconstructed from README signals."]

    detailed = [
        GitHubDetailedSection(
            heading="Overview",
            bullets=bullets,
            module_or_feature="Overview",
            main_stack=list(clean_stack[:4]),
            public_interfaces=list(clean_surfaces[:6]),
            usability_signals=list(clean_install[:3]),
        )
    ]

    tags = _fallback_tags(archetype=archetype, signals=signals)

    return GitHubStructuredPayload(
        mini_title=owner_repo,
        architecture_overview=architecture_overview,
        brief_summary=brief,
        tags=tags,
        benchmarks_tests_examples=None,
        detailed_summary=detailed,
    )


def _canonical_owner_repo(ingest: IngestResult) -> str:
    match = re.search(
        r"github\.com/([^/\s]+)/([^/\s?#]+)",
        str(ingest.url or ""),
        flags=re.IGNORECASE,
    )
    if match:
        return f"{match.group(1)}/{match.group(2)}"[:60]
    meta = ingest.metadata or {}
    full_name = meta.get("full_name") or meta.get("repo_full_name")
    if isinstance(full_name, str) and "/" in full_name:
        return full_name[:60]
    return "unknown/repo"


def _looks_clean(text: str) -> bool:
    """Reject obviously-malformed signal fragments (unicode replacement chars,
    truncated ellipsis markers, or pure prose sentences masquerading as
    identifiers)."""
    t = (text or "").strip()
    if not t or len(t) > 120:
        return False
    if "\ufffd" in t or "..." in t:
        return False
    # Prose sentences tend to have multiple spaces and lowercase first word.
    words = t.split()
    if len(words) > 8:
        return False
    return True


# HTML element names that README code snippets leak as fake endpoints
# (`/div`, `/span`, `/p`, etc.). Never treat these as public surfaces.
_HTML_ELEMENT_PATHS = {
    "/div", "/span", "/p", "/a", "/li", "/ul", "/ol", "/td", "/tr", "/th",
    "/tbody", "/thead", "/table", "/form", "/input", "/button", "/label",
    "/select", "/option", "/img", "/br", "/hr", "/head", "/body", "/html",
    "/pre", "/code", "/em", "/strong", "/b", "/i", "/h1", "/h2", "/h3",
    "/h4", "/h5", "/h6", "/nav", "/section", "/article", "/aside",
    "/footer", "/header", "/main", "/figure", "/figcaption",
}


def _looks_clean_surface(text: str) -> bool:
    """Like _looks_clean but also rejects fragments that don't look like
    exported identifiers — HTML closing tags, multi-word phrases starting
    with keywords like 'except', 'raise', 'return', etc."""
    if not _looks_clean(text):
        return False
    t = (text or "").strip()
    if t.lower() in _HTML_ELEMENT_PATHS:
        return False
    lowered = t.lower()
    if any(
        lowered.startswith(prefix + " ")
        for prefix in ("except", "raise", "return", "import", "from", "def ", "class ", "with ", "if ", "elif ", "else")
    ):
        return False
    return True


def _first_paragraph(text: str) -> str:
    if not text:
        return ""
    for chunk in re.split(r"\n\s*\n", text):
        cleaned = re.sub(r"\s+", " ", chunk).strip()
        if 40 <= len(cleaned) <= 320:
            return cleaned
    first = re.sub(r"\s+", " ", text).strip()
    return first[:300]


def _fallback_tags(*, archetype: RepoArchetype, signals: ReadmeSignals) -> list[str]:
    ordered: list[str] = []
    # Language tag
    stack_lower = [s.lower() for s in signals.stack]
    for lang in ("python", "rust", "go", "javascript", "typescript", "java", "ruby"):
        if lang in stack_lower:
            ordered.append(lang)
            break
    # Archetype tag
    archetype_tag = {
        RepoArchetype.FRAMEWORK_API: "api-framework",
        RepoArchetype.CLI_TOOL: "cli-tool",
        RepoArchetype.LIBRARY_THIN: "library",
        RepoArchetype.DOCS_HEAVY: "documentation",
        RepoArchetype.APP_EXAMPLE: "example-project",
        RepoArchetype.UNKNOWN: "github-project",
    }[archetype]
    if archetype_tag not in ordered:
        ordered.append(archetype_tag)
    # Stack tags
    for item in signals.stack:
        clean = re.sub(r"[^a-z0-9+-]+", "-", item.lower()).strip("-")
        if clean and clean not in ordered:
            ordered.append(clean)
    # Domain heuristics from surfaces
    surface_blob = " ".join(signals.any_public_surface()).lower()
    if "async" not in ordered and any(tok in surface_blob for tok in ("async", "await")):
        ordered.append("async")
    if "http" in surface_blob and "http-client" not in ordered:
        ordered.append("http-client")
    # Ensure schema minimum of 7
    filler = ["open-source", "documented", "public-api", "github", "source-code", "repository"]
    for f in filler:
        if len(ordered) >= 7:
            break
        if f not in ordered:
            ordered.append(f)
    return ordered[:10]


def _fit_architecture_overview(
    *,
    purpose: str,
    stack: tuple[str, ...] | list[str],
    surfaces: tuple[str, ...],
    archetype_hint: str,
) -> str:
    stack_part = ", ".join(list(stack)[:4]) if stack else "documented stack"
    surface_part = ", ".join(list(surfaces)[:3]) if surfaces else "documented public API"
    sentence = (
        f"{purpose} "
        f"It is {archetype_hint} built with {stack_part}, exposing "
        f"{surface_part} as documented public surfaces."
    )
    sentence = re.sub(r"\s+", " ", sentence).strip()
    if len(sentence) < 50:
        sentence = (sentence + " " + (
            "This summary was reconstructed from deterministic README signals "
            "after the primary structured extraction step did not validate."
        )).strip()
    return sentence[:500]


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


register_summarizer(GitHubSummarizer)
