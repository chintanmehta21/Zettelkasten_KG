"""Canonical persistence helpers for summarize → write-everywhere fanout.

This module is the **single source of truth** for persisting a summarize
result into the knowledge graph. Every ingest path should call
:func:`persist_summarized_result`.

Historically this code lived at
``website.experimental_features.nexus.service.persist``; a compat shim at
that path re-exports the public symbols so existing imports keep working.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
from dataclasses import dataclass
from datetime import date
from typing import Any
from uuid import UUID

from website.core.graph_store import _SOURCE_PREFIX, add_node, get_graph
from website.core.request_context import get_operation_id
from website.core.db_version import use_supabase_v2
from website.core.supabase_v2.client import is_v2_configured
from website.core.settings import get_settings  # noqa: F401 - legacy test patch hook
from website.core.supabase_v2.models import CanonicalChunkCreate, CanonicalZettelCreate, WorkspaceZettelCreate
from website.core.supabase_v2.repositories.content_repository import ContentRepository as V2ContentRepository
from website.core.supabase_v2.repositories.core_repository import CoreRepository as V2CoreRepository
from website.core.supabase_v2.client import get_v2_client as _get_v2_client
from website.core.text_polish import polish, rewrite_tags, strip_caveats

# Keep a forward reference to supabase Client only for typing; importing at
# module top would force the supabase package even when v2 is disabled.
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover
    from supabase import Client  # noqa: F401

logger = logging.getLogger("website.core.persist")

_v2_core_repo: V2CoreRepository | None = None
_v2_content_repo: V2ContentRepository | None = None

# Registry of in-flight best-effort enrichment tasks (Phase-B KG population +
# RAG chunk ingest). These are scheduled fire-and-forget so the *website*
# Add-Zettel route returns without waiting (latency unchanged). But the
# create_kasten CLI / Phase-E runner is a SHORT-LIVED process: it awaits the
# Add-Zettel pipeline (which only SCHEDULES these tasks) then returns, and the
# event loop is torn down by ``asyncio.run`` — silently cancelling the pending
# kg-populate tasks before they create any edges (observed: 10 kg_nodes,
# 0 kg_edges after a real CLI ingest). The runner therefore drains this
# registry via ``drain_pending_enrichment_tasks`` before returning, guaranteeing
# KG population actually completes. The live FastAPI route never calls the
# drain, so its fire-and-forget latency is unaffected.
_PENDING_ENRICHMENT_TASKS: "set[asyncio.Task]" = set()


def _register_enrichment_task(task: "asyncio.Task") -> None:
    """Track a fire-and-forget enrichment task so a short-lived caller can
    deterministically drain it before process exit (see module docstring on
    ``_PENDING_ENRICHMENT_TASKS``). The done-callback removes the task so the
    set never grows unbounded on a long-lived server."""
    _PENDING_ENRICHMENT_TASKS.add(task)
    task.add_done_callback(_PENDING_ENRICHMENT_TASKS.discard)


async def drain_pending_enrichment_tasks(*, timeout: float = 120.0) -> int:
    """Await every currently-registered fire-and-forget enrichment task.

    Used by the create_kasten runner (CLI / Phase-E / route-background path)
    so KG population + RAG chunk ingest are guaranteed to complete before the
    runner returns and the interpreter (CLI) tears the loop down. Idempotent
    and safe to call repeatedly. Never raises: individual task failures are
    already logged + swallowed at their own call sites (best-effort contract);
    a per-task timeout is enforced so one stuck task cannot wedge the runner.

    Returns the number of tasks drained (for observability / tests). New tasks
    scheduled *while* draining (e.g. a task that itself schedules another) are
    picked up by the drain loop until the registry is empty or the deadline
    passes.
    """
    import time as _time

    drained = 0
    deadline = _time.monotonic() + timeout
    while _PENDING_ENRICHMENT_TASKS:
        remaining = deadline - _time.monotonic()
        if remaining <= 0:
            logger.warning(
                "drain_pending_enrichment_tasks: %d task(s) still pending at "
                "timeout; leaving them to the loop",
                len(_PENDING_ENRICHMENT_TASKS),
            )
            break
        # Snapshot: a task may schedule another while we await this batch.
        batch = list(_PENDING_ENRICHMENT_TASKS)
        done, _pending = await asyncio.wait(batch, timeout=remaining)
        drained += len(done)
    return drained


class SupabaseV2PersistError(RuntimeError):
    """Raised when a v2-configured Add Zettel persist attempt fails.

    P1-2 fix: when v2 is configured the persist path MUST attempt v2 and, on
    failure, surface a structured error the route turns into a non-200
    problem+json response. Previously every exception out of
    ``_persist_supabase_v2_zettel`` was swallowed with a ``logger.warning`` and
    Add Zettel returned HTTP 200 with ``supabase=false`` — silent data loss on
    a broken RPC / schema-cache miss / RLS denial / empty PostgREST result.

    ``detail`` is a short operator-safe string (no secrets, no raw row data);
    the original exception is chained for log forensics only.
    """

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


@dataclass(slots=True)
class PersistenceOutcome:
    """Result of writing a summarized artifact into the knowledge graph."""

    result: dict[str, Any]
    file_node_id: str | None = None
    supabase_node_id: str | None = None
    file_saved: bool = False  # True if file-backed graph.json was written
    supabase_saved: bool = False
    supabase_duplicate: bool = False
    kg_user_id: str | None = None
    # D10: the zettel persisted but is NOT cleanly retrievable. Set True when
    # a NON-EMPTY source yielded ZERO embeddable chunks (batch-embed failure
    # or chunker produced nothing) — the row is saved (no 500, recoverable
    # via backfill_rechunk_v2.py) but the caller MUST NOT report a clean
    # success. ``quality_flag`` names the degradation ("no_chunks"). Mirrors
    # the P1-2 structured-signal style: visible, not swallowed.
    degraded: bool = False
    quality_flag: str | None = None


def get_supabase_v2_scope_for_read(
    user_sub: str | None = None,
) -> tuple[V2ContentRepository, UUID, list[UUID]] | None:
    """Return ``(content_repo, profile_id, workspace_ids)`` for read paths.

    Mirrors :func:`get_supabase_v2_scope` but enumerates *every* workspace the
    profile is a member of (default-workspace-only is too narrow for the graph
    read path, which fans across personal + shared workspaces). Returns
    ``None`` when v2 is not in use, the JWT subject is not a UUID, or the
    profile has no workspace memberships.
    """
    global _v2_core_repo, _v2_content_repo

    if not _persist_should_attempt_v2() or not user_sub:
        return None
    try:
        profile_id = UUID(str(user_sub))
    except (TypeError, ValueError):
        logger.info(
            "DB v2 read scope requires UUID auth subject; falling back for user_sub=%r",
            user_sub,
        )
        return None

    try:
        _v2_core_repo = _v2_core_repo or V2CoreRepository()
        _v2_content_repo = _v2_content_repo or V2ContentRepository()
        # Enumerate all workspaces the profile is a member of via the same
        # core.workspace_members table CoreRepository.get_default_workspace_id
        # already uses; service-role client bypasses RLS for read fan-out.
        response = (
            _v2_core_repo._client.schema("core")
            .table("workspace_members")
            .select("workspace_id")
            .eq("profile_id", str(profile_id))
            .order("added_at")
            .execute()
        )
        workspace_ids = [
            UUID(str(row["workspace_id"])) for row in (response.data or []) if row.get("workspace_id")
        ]
        if not workspace_ids:
            return None
        return _v2_content_repo, profile_id, workspace_ids
    except Exception as exc:
        logger.warning("Supabase v2 read scope lookup failed, falling back: %s", exc)
        return None


def _persist_should_attempt_v2() -> bool:
    """Per-call decision: should the Add Zettel persist path ATTEMPT v2?

    P1-2 fix. The Add Zettel CLI (``module_runners/summarization.py``) forces
    ``DB_SCHEMA_VERSION=v2`` before persisting, so ``use_supabase_v2()`` is
    true there. The FastAPI route process does NOT export that env var, so the
    same code previously skipped v2 entirely and silently wrote only the file
    graph. This helper makes the persist path behave like the CLI **whenever
    v2 credentials are present**, WITHOUT mutating the global
    ``DB_SCHEMA_VERSION`` default and WITHOUT changing ``use_supabase_v2()``'s
    definition (both are deliberate prior infra decisions — see
    ``db_version.py``).

    Returns ``True`` when either the global routing flag is on
    (``use_supabase_v2()``) OR v2 is configured. When v2 is NOT configured,
    returns ``False`` and the caller keeps the unchanged file-graph path.
    """
    return use_supabase_v2() or is_v2_configured()


def get_supabase_v2_scope(user_sub: str | None = None) -> tuple[V2ContentRepository, UUID, UUID] | None:
    """Return ``(content_repo, profile_id, workspace_id)`` for DB v2.

    DB v2 is workspace-first and requires a Supabase Auth UUID. Anonymous or
    legacy render-style IDs intentionally fall back to the existing file/v1
    path until the auth migration is complete.

    P1-2: gating is ``_persist_should_attempt_v2()`` (configured-or-flagged),
    not bare ``use_supabase_v2()``, so the route path attempts v2 exactly when
    the CLI does. Scope-resolution failures (no UUID subject, no workspace)
    still fall back to the file path and return ``None`` — those are not
    persist failures, they are "v2 not applicable for this caller". An actual
    persist failure is surfaced later via :class:`SupabaseV2PersistError`.
    """
    global _v2_core_repo, _v2_content_repo

    if not _persist_should_attempt_v2() or not user_sub:
        return None
    try:
        profile_id = UUID(str(user_sub))
    except (TypeError, ValueError):
        logger.info("DB v2 requires UUID auth subject; falling back for user_sub=%r", user_sub)
        return None

    try:
        _v2_core_repo = _v2_core_repo or V2CoreRepository()
        _v2_content_repo = _v2_content_repo or V2ContentRepository()
        workspace_id = _v2_core_repo.get_default_workspace_id(profile_id)
        if workspace_id is None:
            return None
        return _v2_content_repo, profile_id, workspace_id
    except Exception as exc:
        logger.warning("Supabase v2 scope lookup failed, falling back: %s", exc)
        return None


def get_billing_scope(user_sub: str | UUID) -> tuple["Client", UUID]:
    """Return ``(v2 client, profile_id)`` for billing.* operations.

    Hard-fails on non-UUID ``user_sub``: per operator decision (2026-05-10,
    Phase 8.0 v2 purge), legacy non-UUID render_user_ids are not supported in
    the v2 billing path. Both production users are UUID-authed; v1 fallback
    branches in ``user_pricing/repository.py`` are dead code and have been
    removed (closes H2 + H3). See
    ``docs/db-v2/phase-9-pricing-enforcement-plan.md`` for the broader
    pricing-enforcement plan that replaces v1's request-counter model.
    """
    try:
        profile_id = user_sub if isinstance(user_sub, UUID) else UUID(str(user_sub))
    except (TypeError, ValueError) as exc:
        raise RuntimeError(
            f"v2 billing requires a Supabase auth UUID; got {user_sub!r}"
        ) from exc
    return _get_v2_client(), profile_id


# Internal sentinel tokens that must never leak to persisted surfaces.
# Mirrors summarization.common.structured._SENTINEL_TAG_RE but also covers
# bracketed/angle forms the LLM sometimes emits mid-text (e.g. ``[RESERVED]``,
# ``<SENTINEL:foo>``) that pollute persisted KG node summaries.
_SENTINEL_TEXT_RE = re.compile(
    r"(\[(?:RESERVED|SENTINEL)[^\]]*\])|(<SENTINEL[^>]*>)|(\b_[a-z][a-z0-9_]*_\b)",
    re.IGNORECASE,
)
# Mid-sentence truncation: a sentence ending abruptly mid-word before terminal
# punctuation. When the last non-empty line has visible text but no terminal
# punctuation, the LLM output is truncated and the downstream surface will show
# a half-written sentence. We drop the dangling fragment rather than render it.
_TERMINAL_PUNCT = (".", "!", "?", ":", ";", '"', "'", ")", "]")


def _strip_sentinel_text(text: str) -> str:
    """Remove sentinel tokens from a rendered summary body.

    Returns the original text with sentinel markers deleted and any resulting
    double-spaces collapsed. Leaves newlines intact so markdown structure is
    preserved.
    """
    if not text:
        return text
    cleaned = _SENTINEL_TEXT_RE.sub("", text)
    # Collapse 2+ spaces (but not newlines) introduced by the excision.
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    return cleaned


def _drop_unterminated_tail(text: str) -> str:
    """Strip a trailing unterminated sentence fragment from a multi-line body.

    Walks lines from the end; while the last non-empty line doesn't end in
    terminal punctuation AND isn't a markdown heading or list marker, drop it.
    Stops as soon as a terminated sentence is found. Empty inputs pass through
    untouched. Single-line inputs are returned as-is (callers decide whether
    to reject them).
    """
    if not text or "\n" not in text:
        return text
    lines = text.split("\n")
    while lines:
        last = lines[-1].rstrip()
        if not last:
            lines.pop()
            continue
        # Preserve markdown headings and list markers even without terminal punct.
        if last.lstrip().startswith(("#", "- ", "* ", "1.", "2.", "3.")):
            break
        if last.endswith(_TERMINAL_PUNCT):
            break
        lines.pop()
    return "\n".join(lines).rstrip() + ("\n" if text.endswith("\n") else "")


def _coerce_detailed_to_markdown(value: Any) -> str:
    """Convert a structured detailed_summary (list-of-dicts or pydantic
    section models) into markdown that ``renderMarkdownLite`` on the
    frontend can parse.

    Returns an empty string for non-list/dict inputs. String inputs pass
    through untouched. This is the single point where a Python ``list`` /
    ``dict`` (shape emitted by the summarization engine and some eval
    register scripts) is rendered to a stable textual surface. Without
    this, callers that forward the raw Python object fall back to
    ``str(list_of_dicts)`` which produces a Python repr with single quotes
    — the exact bug we are fixing.
    """
    if value is None or isinstance(value, str):
        return value or ""
    sections: list[Any]
    if isinstance(value, list):
        sections = value
    elif isinstance(value, dict):
        sections = [value]
    else:
        return ""

    lines: list[str] = []
    for section in sections:
        if hasattr(section, "model_dump"):
            try:
                section = section.model_dump()
            except Exception:
                section = None
        if not isinstance(section, dict):
            continue
        heading = str(section.get("heading") or "").strip()
        if lines:
            lines.append("")
        if heading:
            lines.append(f"## {heading}")
        bullets = section.get("bullets") or []
        if isinstance(bullets, list):
            for bullet in bullets:
                text = str(bullet).strip()
                if text:
                    lines.append(f"- {text}")
        sub_sections = section.get("sub_sections") or section.get("subSections") or {}
        if isinstance(sub_sections, dict):
            for sub_heading, sub_bullets in sub_sections.items():
                if not isinstance(sub_bullets, list) or not sub_bullets:
                    continue
                lines.append("")
                lines.append(f"### {str(sub_heading).strip()}")
                for bullet in sub_bullets:
                    text = str(bullet).strip()
                    if text:
                        lines.append(f"- {text}")
    return "\n".join(lines).strip()


def _normalize_summary_text(value: Any) -> str:
    """Normalize + sanitize a summary body for persistence.

    Beyond whitespace/escape normalization, this strips internal sentinel
    tokens (``[RESERVED]``, ``<SENTINEL...>``, ``_schema_fallback_``) that
    must never reach user-facing surfaces, and collapses trailing mid-
    sentence truncation so persisted summaries always end on a complete
    sentence or a structural marker.

    Non-string inputs (list-of-dict section payloads from the engine's
    structured summaries, or a single-dict section) are coerced to
    markdown via :func:`_coerce_detailed_to_markdown` rather than running
    through ``str()`` — which would emit a Python repr with single quotes
    (the iter-23 github regression).
    """
    if value is None:
        raw_text = ""
    elif isinstance(value, (list, dict)):
        raw_text = _coerce_detailed_to_markdown(value)
    else:
        raw_text = str(value)
    raw = (
        raw_text
        .replace("\r\n", "\n")
        .replace("\\n", "\n")
        .replace("\\r", "\r")
        .replace("\\t", "\t")
        .replace('\\"', '"')
        .strip()
    )
    cleaned = _strip_sentinel_text(raw)
    cleaned = _drop_unterminated_tail(cleaned)
    return cleaned.strip()


def _extract_summary_field_by_regex(text: str, field_name: str) -> str:
    pattern = re.compile(
        rf'"{re.escape(field_name)}"\s*:\s*"((?:\\.|[^"\\])*)"',
        re.IGNORECASE | re.DOTALL,
    )
    match = pattern.search(text)
    if not match:
        return ""
    return _normalize_summary_text(match.group(1))


def _try_parse_summary_object(raw_text: str | None) -> dict[str, Any] | None:
    cleaned = str(raw_text or "").strip()
    if not cleaned:
        return None

    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*```$", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"^json\s*", "", cleaned, flags=re.IGNORECASE).strip()

    candidates = [cleaned]
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start != -1 and end > start:
        candidates.append(cleaned[start : end + 1])

    for candidate in candidates:
        candidate = candidate.strip()
        if not candidate:
            continue
        try:
            parsed = json.loads(candidate)
            if isinstance(parsed, dict):
                return parsed
            if isinstance(parsed, str):
                nested = json.loads(parsed)
                if isinstance(nested, dict):
                    return nested
        except Exception:
            continue

    regex_brief = _extract_summary_field_by_regex(cleaned, "brief_summary")
    regex_detailed = _extract_summary_field_by_regex(cleaned, "detailed_summary")
    if regex_brief or regex_detailed:
        return {
            "brief_summary": regex_brief,
            "detailed_summary": regex_detailed,
        }

    return None


def extract_summary_parts(raw_summary: str | None, fallback_brief: str | None = None) -> tuple[str, str]:
    """Normalize a summarizer payload into brief + detailed summary strings."""

    fallback_brief_text = _normalize_summary_text(fallback_brief)
    parsed = _try_parse_summary_object(raw_summary)
    if parsed:
        brief = _normalize_summary_text(
            parsed.get("brief_summary")
            or parsed.get("briefSummary")
            or parsed.get("one_line_summary")
            or parsed.get("summary")
        )
        detailed = _normalize_summary_text(
            parsed.get("detailed_summary")
            or parsed.get("detailedSummary")
            or parsed.get("summary")
        )
        if brief or detailed:
            resolved_brief = brief or detailed or fallback_brief_text
            resolved_detailed = detailed or brief or fallback_brief_text
            return (
                resolved_brief or "No summary available for this zettel.",
                resolved_detailed or resolved_brief or "No summary available for this zettel.",
            )

    fallback = fallback_brief_text or _normalize_summary_text(raw_summary) or "No summary available for this zettel."
    return fallback, fallback


def _build_supabase_node_id(source_type: str, title: str) -> str:
    prefix = _SOURCE_PREFIX.get((source_type or "").strip().lower(), "web")
    slug = re.sub(r"[^a-z0-9]+", "-", str(title or "").lower()).strip("-")[:24].rstrip("-")
    slug = slug or "untitled"
    return f"{prefix}-{slug}"


def _file_graph_contains_url(source_url: str) -> bool:
    graph = get_graph()
    normalized_url = str(source_url or "").strip()
    if not normalized_url:
        return False
    return any(str(node.get("url") or "").strip() == normalized_url for node in graph.get("nodes", []))


# Phase 8.0.3 B+: removed v1-only helpers _get_cached_existing_types and
# _schedule_entity_extraction. They wrote to ``public.kg_nodes`` (dropped in
# Phase 6) via KGRepository; v2 entity extraction will be re-introduced as a
# pipeline against ``content.workspace_zettels`` in a later iter.


async def persist_summarized_result(
    result: dict[str, Any],
    *,
    user_sub: str | None = None,
    captured_on: date | None = None,
) -> PersistenceOutcome:
    """Persist a summarized result using the canonical Add Zettel KG behavior."""

    payload = dict(result)
    captured_on = captured_on or date.today()

    # Operation-scoped persist-boundary trace: the last checkpoint before the
    # row is written, so a contaminated zettel can be tied to its operation.
    _raw_meta = payload.get("raw_metadata") or (payload.get("metadata") or {}).get("raw_metadata") or {}
    logger.info(
        "persist_boundary op=%s source_url=%s video_id=%s",
        get_operation_id(),
        payload.get("source_url"),
        _raw_meta.get("video_id") if isinstance(_raw_meta, dict) else None,
    )

    explicit_brief = _normalize_summary_text(payload.get("brief_summary"))
    explicit_detailed = _normalize_summary_text(payload.get("detailed_summary"))
    if explicit_brief and explicit_detailed:
        brief_summary = explicit_brief
        detailed_summary = explicit_detailed
    else:
        brief_summary, detailed_summary = extract_summary_parts(
            payload.get("summary"),
            payload.get("brief_summary"),
        )
    payload["brief_summary"] = brief_summary
    payload["detailed_summary"] = detailed_summary
    payload["summary"] = detailed_summary
    payload["captured_at"] = captured_on.isoformat()

    supabase_node_id: str | None = None
    supabase_saved = False
    supabase_duplicate = False
    kg_user_id: str | None = None
    source_url = str(payload["source_url"])
    file_duplicate = False

    v2_scope = get_supabase_v2_scope(user_sub)
    file_duplicate = _file_graph_contains_url(source_url)

    if v2_scope:
        repo_v2, profile_id, workspace_id = v2_scope
        kg_user_id = str(profile_id)
        try:
            supabase_node_id, supabase_saved, supabase_duplicate = await _persist_supabase_v2_zettel(
                payload=payload,
                repo=repo_v2,
                workspace_id=workspace_id,
                captured_on=captured_on,
                detailed_summary=detailed_summary,
                profile_id=profile_id,
            )
        except SupabaseV2PersistError:
            # Already structured + logged at the failure site; re-raise so the
            # route turns it into a non-200 problem+json. No silent fallback.
            raise
        except Exception as exc:
            # P1-2: do NOT swallow. A v2-configured path that fails must be
            # visible to the caller, not reported as 200 + supabase=false.
            logger.exception("Failed to add zettel to Supabase v2")
            raise SupabaseV2PersistError(
                "Knowledge-graph write failed; the zettel was not saved."
            ) from exc

    # Phase 8.0.3 B+: v1 fallback branch (KGRepository.add_node + semantic
    # auto-link) was removed — v1 ``kg_nodes`` / ``kg_users`` tables were
    # dropped in Phase 6, so the call would 500 against the live DB.

    file_node_id = _persist_file_node(payload, skip_duplicate=file_duplicate or supabase_duplicate)
    if file_node_id:
        payload["node_id"] = file_node_id
    payload.pop("raw_text", None)
    payload.pop("raw_metadata", None)
    payload.pop("source_fingerprint_text", None)

    # D10: a non-empty source that yielded ZERO chunks persisted the zettel
    # but it is NOT retrievable. Surface a degraded signal (set by
    # _persist_supabase_v2_zettel on the shared payload). Translate the
    # internal marker into a stable public ``quality_flag`` on both the
    # outcome and the result dict so the caller/response can show
    # "persisted but not retrievable (0 chunks)" instead of clean success.
    degraded = bool(payload.pop("_degraded_no_chunks", False))
    quality_flag = "no_chunks" if degraded else None
    if quality_flag:
        payload["quality_flag"] = quality_flag

    return PersistenceOutcome(
        result=payload,
        file_node_id=file_node_id,
        supabase_node_id=supabase_node_id,
        file_saved=file_node_id is not None,
        supabase_saved=supabase_saved,
        supabase_duplicate=supabase_duplicate,
        kg_user_id=kg_user_id,
        degraded=degraded,
        quality_flag=quality_flag,
    )


def _normalize_source_fingerprint(text: str) -> str:
    """Minimal whitespace normalization of source text for the dedup hash.

    Collapses every run of ASCII/Unicode whitespace (spaces, tabs, newlines)
    to a single space and strips ends. This is the ONLY transform applied
    before hashing: trivially-noisy re-extraction of identical content
    (re-wrapped lines, added trailing newline, tab↔space drift) yields the
    same hash, but any material change to the source words still changes it.
    """
    return re.sub(r"\s+", " ", text).strip()


def _stable_content_hash(payload: dict[str, Any], normalized_url: str) -> bytes:
    """Deterministic dedup hash for ``(normalized_url, content_hash)``.

    P1-7(a)+(b) fix. Previously ``content_hash = sha256(body_md)`` where
    ``body_md`` fell through to the LLM ``detailed_summary``/``summary``. LLM
    output is non-deterministic, so re-ingesting the same URL produced a
    different hash, the ``(normalized_url, content_hash)`` ON CONFLICT key in
    ``content.upsert_canonical_zettel`` missed, and a duplicate canonical row
    was inserted on every re-ingest.

    The hash derives ONLY from stable inputs available at persist time: the
    normalized source URL plus the **extracted source text** (the pre-summary
    article/transcript/body fetched by the source ingestor). It never hashes
    the LLM summary. The source text is read, in priority order, from:

    1. ``payload['source_fingerprint_text']`` — the dedicated key the Add
       Zettel route now threads from ``IngestResult.raw_text`` (P1-7(b)).
       Single-purpose: nothing else consumes it, so populating it cannot
       affect ``body_md`` or RAG chunk-source selection.
    2. ``payload['raw_text']`` — legacy/back-compat fallback for callers
       (and existing tests) that still pass the source under ``raw_text``.
    3. neither present → ``""`` (URL-only hash).

    The chosen text is whitespace-normalized via
    :func:`_normalize_source_fingerprint` so trivially-noisy re-extraction of
    identical content does NOT churn the hash, while a material content change
    still does. Properties:

    * Same URL re-ingested, different LLM wording → identical hash → dedup.
    * Genuine source-content change → different hash → a new canonical row,
      exactly as the dedup contract intends.
    * Whitespace-only / re-wrap difference in source text → identical hash.
    * When no source text is available the hash is ``sha256(url || "")`` —
      still fully stable across re-ingests of the same URL, so dedup holds;
      it simply cannot detect source drift (strictly better than the old
      always-miss behavior, and never crashes).

    The SQL RPC dedup columns are unchanged; only the Python-side input to
    ``content_hash`` changed.
    """
    raw_source = payload.get("source_fingerprint_text")
    if raw_source is None:
        raw_source = payload.get("raw_text")
    raw_source_text = "" if raw_source is None else _normalize_source_fingerprint(str(raw_source))
    fingerprint = f"{normalized_url}\x00{raw_source_text}"
    return hashlib.sha256(fingerprint.encode("utf-8")).digest()


async def _persist_supabase_v2_zettel(
    *,
    payload: dict[str, Any],
    repo: V2ContentRepository,
    workspace_id: UUID,
    captured_on: date,
    detailed_summary: str,
    profile_id: UUID | None = None,
) -> tuple[str, bool, bool]:
    normalized_url = str(payload["source_url"])
    body_md = str(payload.get("raw_text") or detailed_summary or payload.get("summary") or "")
    content_hash = _stable_content_hash(payload, normalized_url)

    zettel = CanonicalZettelCreate(
        normalized_url=normalized_url,
        content_hash=content_hash,
        source_type=str(payload.get("source_type") or "web"),
        title=polish(str(payload["title"])),
        body_md=body_md,
        publication_date=captured_on.isoformat(),
        source_metadata={
            "source_url": normalized_url,
            "metadata": payload.get("metadata") or {},
        },
    )
    workspace = WorkspaceZettelCreate(
        workspace_id=workspace_id,
        ai_summary=_encode_summary_payload(payload),
        ai_summary_engine_version=str(payload.get("engine_version") or ""),
        user_tags=list(rewrite_tags(payload.get("tags", []) or [])),
        added_via="website",
    )
    # PR #39 / Wave-3 B1 (2026-05-20): chunk+embed moved off the critical
    # Add Zettel path. We write the canonical zettel + workspace zettel
    # SYNCHRONOUSLY (so My Zettels surfaces the summary the moment _run
    # finalizes) and enqueue a durable lazy-enrichment job for the
    # chunker + Gemini batch embed (typically the heaviest step). The
    # job is drained by an in-process poller in each gunicorn worker.
    # The legacy inline `_degraded_no_chunks` signal is dropped here:
    # with the split, "no chunks" is a transient state until the
    # enrichment job completes (logged by the handler).
    result = await asyncio.to_thread(
        repo.upsert_canonical_zettel,
        zettel,
        workspace=workspace,
        chunks=[],
    )
    persisted_id = result.workspace_zettel_id or result.canonical_zettel_id

    # Enqueue chunk+embed enrichment. Defensive: failure to enqueue must
    # NEVER fail Add Zettel — the zettel is already persisted and the
    # backfill_rechunk_v2.py script can pick it up out of band.
    if profile_id is not None:
        from website.features.summarization_engine.lazy_enrichment import (
            repo as enrichment_repo,
        )

        enrichment_payload = {
            "canonical_zettel_id": str(result.canonical_zettel_id),
            "workspace_zettel_id": (
                str(result.workspace_zettel_id) if result.workspace_zettel_id else None
            ),
            "workspace_id": str(workspace_id),
            "detailed_summary": detailed_summary,
            "summarized_payload": _enrichment_safe_payload(payload),
        }
        try:
            await asyncio.to_thread(
                enrichment_repo.enqueue_chunk_embed,
                user_id=profile_id,
                canonical_zettel_id=result.canonical_zettel_id,
                workspace_zettel_id=result.workspace_zettel_id,
                payload=enrichment_payload,
            )
        except Exception:
            logger.exception(
                "enqueue_chunk_embed failed for %s; chunk_embed_backfill "
                "will recover via ops/scripts/backfill_rechunk_v2.py",
                result.canonical_zettel_id,
            )

    # Phase B: fire-and-forget KG-population enrichment via
    # _schedule_kg_population's asyncio.create_task. Best-effort: never
    # blocks or fails Add Zettel. The KG handler is summary-driven and
    # does NOT depend on the lazy-chunk rows landing first.
    _schedule_kg_population(
        payload=payload,
        workspace_id=workspace_id,
        profile_id=profile_id,
        canonical_zettel_id=result.canonical_zettel_id,
        title=zettel.title,
        summary=detailed_summary or body_md,
    )
    return str(persisted_id), result.workspace_zettel_id is not None, not result.was_new


def _enrichment_safe_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Return a JSON-safe slice of the persist payload for the enrichment
    job. Excludes mutable cursors and large internal-only fields. Reusable
    by both _persist_supabase_v2_zettel and any future enqueue site."""
    safe_keys = (
        "source_url", "title", "source_type", "summary", "brief_summary",
        "detailed_summary", "tags", "metadata", "raw_metadata", "raw_text",
        "captured_at", "engine_version",
    )
    out: dict[str, Any] = {}
    for k in safe_keys:
        if k in payload:
            out[k] = payload[k]
    return out


def _encode_summary_payload(payload: dict[str, Any]) -> str:
    """Serialize brief + detailed summaries as JSON so both survive persistence.

    Applies the deterministic polish + caveat-strip stack at the WRITE
    boundary so every persisted row is born clean. Idempotent — re-encoding
    an already-polished payload is a no-op. Complements the read-time polish
    in ``summary_normalizer.normalize_summary_for_wire``.
    """
    brief = _normalize_summary_text(payload.get("brief_summary"))
    detailed = _normalize_summary_text(payload.get("detailed_summary") or payload.get("summary"))
    if not brief and not detailed:
        return ""
    cleaned_brief = polish(strip_caveats(brief))
    detailed_value = detailed or brief
    cleaned_detailed = polish(strip_caveats(detailed_value)) if detailed_value else cleaned_brief
    return json.dumps(
        {"brief_summary": cleaned_brief, "detailed_summary": cleaned_detailed},
        ensure_ascii=False,
    )


def _persist_file_node(payload: dict[str, Any], *, skip_duplicate: bool) -> str | None:
    if skip_duplicate:
        return None
    try:
        return add_node(
            title=polish(str(payload["title"])),
            source_type=str(payload["source_type"]),
            source_url=str(payload["source_url"]),
            summary=_encode_summary_payload(payload),
            tags=list(rewrite_tags(payload.get("tags", []) or [])),
        )
    except Exception as exc:
        logger.warning("Failed to add node to file KG: %s", exc)
        return None


# Phase 8.0.3 B+: removed v1-only helpers _persist_supabase_node and
# _schedule_embedding_and_links. They both took a v1 ``KGRepository`` and
# wrote to ``public.kg_nodes`` / ``public.kg_node_links`` (dropped in Phase 6).
# v2 zettel persist runs through ``_persist_supabase_v2_zettel`` above.


# Per-zettel chunk-count safety cap. Mirrors no explicit cap in the chunker
# itself, so this is a generous defensive ceiling: a pathological ~92k-char
# body cannot explode the chunk list (and the downstream batch embed / RPC
# payload) unbounded. Long-form chunks are ~512 tokens (~2k chars), so 200
# chunks ≈ a ~400k-char body — well past any real article/transcript.
_MAX_CHUNKS_PER_ZETTEL = 200


def _choose_chunk_source_text(payload: dict[str, Any], detailed_summary: str) -> str:
    """Pick the text the RAG chunker is designed to chunk — SUMMARY-PRIMARY.

    R1 policy (corrects the earlier raw-first intent):

    1. ``content_selection.choose_chunk_source_text(raw_text=payload['raw_text'],
       summary_text=<summary>)`` — the SUMMARY is the primary chunk source;
       ``raw_text`` is only a fallback when the summary is empty or a known
       stub. Rationale: our persisted ``body_md`` summaries are dense and
       self-contained (numbers, entities, attributed quotes survive),
       citations resolve to the zettel = the summary, and the route never
       plumbs raw source text into chunks — so chunking the summary keeps
       citation/faithfulness coherent (R1 research; RAPTOR ICLR 2024).
    2. if that yields nothing, ``content_selection.synthesize_fallback_text``
       builds a minimal searchable body from title/channel/tags/description/
       url so a transcript-less node still gets a chunk instead of zero
       chunks.

    The summary fed to step 1 is ``detailed_summary or payload['summary']``
    (= the persisted ``body_md``).
    """
    from website.features.rag_pipeline.ingest.content_selection import (
        choose_chunk_source_text,
        synthesize_fallback_text,
    )

    summary_text = detailed_summary or str(payload.get("summary") or "")
    text = choose_chunk_source_text(
        raw_text=payload.get("raw_text"),
        summary_text=summary_text,
    )
    if not text:
        text = synthesize_fallback_text(payload)
    return text or ""


async def build_canonical_chunks(
    *,
    payload: dict[str, Any],
    detailed_summary: str,
) -> list[CanonicalChunkCreate]:
    """Shared chunk+embed core for the inline persist path AND the v2
    re-chunk backfill (single source of truth — they cannot diverge on
    source-text selection, chunker, dimensionality, model-version stamp, or
    the embed-or-skip contract).

    Pipeline:
      1. select source text via the chunker's own convention
         (:func:`_choose_chunk_source_text`);
      2. segment it with :class:`ZettelChunker` (the real multi-chunk chunker
         — chonkie, ~512-token long-form chunks, same one the dead hook used);
      3. enforce :data:`_MAX_CHUNKS_PER_ZETTEL`;
      4. batch-embed every chunk text in ONE call via
         :func:`embed_chunk_texts`;
      5. return ``list[CanonicalChunkCreate]``.

    Returns ``[]`` when there is no source text OR the batch embed fails.
    Per the embed-or-skip contract, an embed failure must NEVER yield a
    NULL-embedding row (the column is NOT NULL DEFAULT model_version, so such
    a row would always lie about success). The caller persists the zettel
    without chunk rows and the backfill recovers them.
    """
    source_text = _choose_chunk_source_text(payload, detailed_summary)
    if not source_text.strip():
        return []

    from website.features.rag_pipeline.ingest.chunker import ZettelChunker
    from website.features.rag_pipeline.types import SourceType as RagSourceType

    source_type_value = str(payload.get("source_type") or "web").strip().lower()
    try:
        source_type = RagSourceType(source_type_value)
    except ValueError:
        # D4: never silently coerce. An unrecognised source-type means the
        # RAG enum drifted from the summarization enum (the drift-guard test
        # should have caught it) OR a genuinely new upstream type — either
        # way it must be observable, not invisible. We still degrade to WEB
        # so the zettel is chunked instead of lost.
        logger.warning(
            "Unknown source_type %r for %s; coercing to RagSourceType.WEB "
            "(provenance + chunking-bucket fidelity degraded — check the "
            "RagSourceType drift guard).",
            source_type_value,
            payload.get("source_url"),
        )
        source_type = RagSourceType.WEB

    chunker = ZettelChunker()
    chunks = chunker.chunk(
        source_type=source_type,
        title=str(payload.get("title") or ""),
        raw_text=source_text,
        tags=list(rewrite_tags(payload.get("tags", []) or [])),
        extra_metadata=dict(payload.get("raw_metadata") or payload.get("metadata") or {}),
    )
    if not chunks:
        return []

    if len(chunks) > _MAX_CHUNKS_PER_ZETTEL:
        logger.warning(
            "Chunk count %d exceeds cap %d; truncating to the cap.",
            len(chunks),
            _MAX_CHUNKS_PER_ZETTEL,
        )
        chunks = chunks[:_MAX_CHUNKS_PER_ZETTEL]

    texts = [c.content for c in chunks]
    embeddings = await embed_chunk_texts(texts)
    if embeddings is None:
        return []

    return [
        CanonicalChunkCreate(
            chunk_idx=i,
            content=ch.content,
            content_hash=hashlib.sha256(ch.content.encode("utf-8")).digest(),
            chunk_type=ch.chunk_type.value,
            start_offset=ch.start_offset,
            end_offset=ch.end_offset,
            token_count=ch.token_count or max(1, len(ch.content.split())),
            embedding=embeddings[i],
            embedding_model_version=_CHUNK_EMBED_MODEL_VERSION,
            metadata=dict(ch.metadata or {}),
        )
        for i, ch in enumerate(chunks)
    ]


def _schedule_kg_population(
    *,
    payload: dict[str, Any],
    workspace_id: UUID,
    profile_id: UUID | None,
    canonical_zettel_id: UUID,
    title: str,
    summary: str,
) -> None:
    """Phase B: populate kg nodes/edges off the Add Zettel critical path.

    Fire-and-forget via ``asyncio.create_task(... name="kg-populate-...")``.
    Any failure inside the hook is logged and swallowed — KG population is
    best-effort enrichment and must NEVER 502 Add Zettel (P1-2 surfaces
    persist failures; this enrichment is explicitly out of that contract).
    Requires a resolved owner ``profile_id`` (the ``kg.match_kg_nodes``
    candidate fence keys off it); anonymous/no-scope writes are skipped.
    """
    if profile_id is None:
        logger.debug("KG population skipped: no resolved profile for %s", canonical_zettel_id)
        return

    async def _run() -> None:
        try:
            from website.core.supabase_v2.client import get_v2_client
            from website.features.rag_pipeline.ingest.kg_population import (
                populate_kg_for_zettel,
            )

            await populate_kg_for_zettel(
                workspace_id=workspace_id,
                profile_id=profile_id,
                canonical_zettel_id=canonical_zettel_id,
                title=title,
                summary=summary,
                tags=list(rewrite_tags(payload.get("tags", []) or [])),
                url=str(payload.get("source_url") or "") or None,
                source_type=str(payload.get("source_type") or "web"),
                supabase_client=get_v2_client(),
                metadata=dict(payload.get("raw_metadata") or payload.get("metadata") or {}),
            )
        except Exception as exc:
            logger.warning(
                "Background KG population failed for %s: %s",
                canonical_zettel_id,
                exc,
            )

    try:
        task = asyncio.create_task(_run(), name=f"kg-populate-{canonical_zettel_id}")
    except RuntimeError:
        logger.debug("No running event loop for KG population on %s", canonical_zettel_id)
        return
    task.add_done_callback(lambda t: t.exception() if not t.cancelled() else None)
    _register_enrichment_task(task)


# Chunk embedding model-version stamp. Must match the row default in
# content.embedding_model_versions(is_default=true) and the schema column
# default in _v2/02_content_schema.sql (halfvec(768)). Single constant so the
# inline ingest path and the backfill script can never diverge on the stamp.
_CHUNK_EMBED_MODEL_VERSION = "gemini-001-mrl-768"


async def embed_chunk_texts(texts: list[str]) -> list[list[float]] | None:
    """Embed chunk texts via the shared Gemini key pool (768-d RETRIEVAL_DOCUMENT).

    Single source of truth for canonical-chunk embedding, reused by BOTH the
    inline Add-Zettel persist path (``_persist_supabase_v2_zettel``) and the
    backfill script (``ops/scripts/backfill_chunk_embeddings.py``) so the two
    can never diverge on model / dimensionality / task type.

    Returns the list of 768-d vectors, or ``None`` if embedding failed or the
    returned dimensionality is wrong (caller must then NOT persist a chunk row
    with a model_version implying success — see the call site).
    """
    if not texts:
        return []
    try:
        from website.features.rag_pipeline.adapters.pool_factory import (
            get_embedding_pool,
        )
        from website.features.rag_pipeline.ingest.embedder import (
            DIM as _EMBED_DIM,
        )
        from website.features.rag_pipeline.ingest.embedder import ChunkEmbedder

        embedder = ChunkEmbedder(pool=get_embedding_pool())
        vectors = await embedder.embed(texts)
        if len(vectors) != len(texts) or any(
            len(v) != _EMBED_DIM for v in vectors
        ):
            logger.warning(
                "Chunk embed returned %d vectors (want %d) / wrong dim; "
                "treating as failure (no NULL-embedding chunk written).",
                len(vectors),
                len(texts),
            )
            return None
        return vectors
    except Exception as exc:
        logger.warning("Chunk embedding generation failed: %s", exc)
        return None


def _generate_node_embedding(payload: dict[str, Any]) -> list[float] | None:
    from website.features.kg_features.embeddings import generate_embedding

    try:
        embed_input = (
            f"{payload.get('title', '')}\n\n"
            f"{payload.get('summary') or payload.get('brief_summary') or ''}"
        )
        return generate_embedding(embed_input.strip()[:2000]) or None
    except Exception as exc:
        logger.warning("Embedding generation failed: %s", exc)
        return None


# Phase 8.0.3 B+: removed v1-only helpers _build_supabase_node_payload (built
# a ``KGNodeCreate`` for ``public.kg_nodes``) and _create_semantic_links
# (called ``KGRepository.match_similar_nodes`` + ``add_semantic_link`` against
# ``public.kg_node_links``). Both v1 tables were dropped in Phase 6; v2
# canonical chunks + semantic edges are produced by the rag_pipeline ingest
# hook against ``content.canonical_chunks`` / ``rag.zettel_links_v2``.
