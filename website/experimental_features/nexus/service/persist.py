"""Shared persistence helpers for web and Nexus summarization flows."""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from dataclasses import dataclass
from datetime import date
from typing import Any
from uuid import UUID

from website.core.graph_store import _SOURCE_PREFIX, add_node, get_graph
from website.core.settings import get_settings
from website.core.supabase_kg import KGNodeCreate, KGRepository, is_supabase_configured

logger = logging.getLogger("website.experimental_features.nexus.persist")

_supabase_repo: KGRepository | None = None
_supabase_user_id: str | None = None

_EXISTING_TYPES_CACHE: dict[str, tuple[float, list[str]]] = {}
_EXISTING_TYPES_TTL = 60.0


@dataclass(slots=True)
class PersistenceOutcome:
    """Result of writing a summarized artifact into the knowledge graph."""

    result: dict[str, Any]
    file_node_id: str | None = None
    supabase_node_id: str | None = None
    supabase_saved: bool = False
    supabase_duplicate: bool = False
    kg_user_id: str | None = None


def get_supabase_scope(user_id_override: str | None = None) -> tuple[KGRepository, str] | None:
    """Return ``(repo, kg_user_id)`` when Supabase is configured."""

    global _supabase_repo, _supabase_user_id

    if not is_supabase_configured():
        return None

    if _supabase_repo is None:
        try:
            _supabase_repo = KGRepository()
        except Exception as exc:
            logger.warning("Supabase init failed, falling back to file store: %s", exc)
            return None

    if user_id_override:
        try:
            existing = _supabase_repo.get_user_by_render_id(user_id_override)
            if existing:
                stats = _supabase_repo.get_stats(existing.id)
                if stats["node_count"] == 0:
                    legacy = _supabase_repo.get_user_by_render_id("naruto")
                    if legacy and legacy.id != existing.id:
                        legacy_stats = _supabase_repo.get_stats(legacy.id)
                        if legacy_stats["node_count"] > 0:
                            _supabase_repo.transfer_data(legacy.id, existing.id)
                            _supabase_user_id = None
                            logger.info(
                                "Transferred %d nodes from naruto to %s",
                                legacy_stats["node_count"],
                                user_id_override,
                            )
                return _supabase_repo, str(existing.id)

            legacy = _supabase_repo.get_user_by_render_id("naruto")
            if legacy:
                claimed = _supabase_repo.claim_user("naruto", user_id_override)
                if claimed:
                    _supabase_user_id = None
                    return _supabase_repo, str(claimed.id)

            user = _supabase_repo.get_or_create_user(user_id_override, display_name="Web User")
            return _supabase_repo, str(user.id)
        except Exception as exc:
            logger.warning("Supabase user lookup failed: %s", exc)
            return None

    if _supabase_user_id is None:
        try:
            user = _supabase_repo.get_or_create_user("naruto", display_name="Naruto")
            _supabase_user_id = str(user.id)
        except Exception as exc:
            logger.warning("Supabase default user init failed: %s", exc)
            return None

    return _supabase_repo, _supabase_user_id


def _normalize_summary_text(value: str | None) -> str:
    return (
        str(value or "")
        .replace("\r\n", "\n")
        .replace("\\n", "\n")
        .replace("\\r", "\r")
        .replace("\\t", "\t")
        .replace('\\"', '"')
        .strip()
    )


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


def _get_cached_existing_types(repo: KGRepository, user_id: str) -> list[str]:
    now = time.monotonic()
    cached = _EXISTING_TYPES_CACHE.get(user_id)
    if cached and cached[0] > now:
        return cached[1]

    try:
        types_list = repo.get_distinct_entity_types(UUID(user_id))
    except Exception:
        types_list = []

    _EXISTING_TYPES_CACHE[user_id] = (now + _EXISTING_TYPES_TTL, types_list)
    return types_list


def _schedule_entity_extraction(
    *,
    repo: KGRepository,
    user_id: str,
    node_id: str,
    title: str,
    detailed_summary: str,
    brief_summary: str,
) -> None:
    try:
        from website.features.kg_features.entity_extractor import EntityExtractor
    except Exception as exc:
        logger.warning("Entity extraction import failed for %s: %s", node_id, exc)
        return

    async def _extract_entities() -> None:
        try:
            logger.info("Entity extraction started for %s", node_id)
            existing_types = _get_cached_existing_types(repo, user_id)
            extractor = EntityExtractor()
            extraction = await asyncio.wait_for(
                extractor.extract(
                    summary=(brief_summary or detailed_summary)[:500],
                    title=title,
                    existing_types=existing_types,
                ),
                timeout=40.0,
            )
            if not extraction.entities:
                logger.info("Entity extraction found 0 entities for %s", node_id)
                return

            current_meta = repo.get_node_metadata(user_id, node_id)
            merged = {
                **current_meta,
                "entities": [entity.model_dump() for entity in extraction.entities],
            }
            repo.update_node_metadata(user_id, node_id, merged)
            logger.info("Extracted %d entities for %s", len(extraction.entities), node_id)
        except asyncio.TimeoutError:
            logger.warning("Entity extraction timed out for %s", node_id)
        except Exception as exc:
            logger.warning("Entity extraction failed for %s: %s", node_id, exc)

    try:
        task = asyncio.create_task(_extract_entities(), name=f"entity-extract-{node_id}")
    except RuntimeError:
        logger.debug("No running event loop for entity extraction on %s", node_id)
        return

    task.add_done_callback(lambda task_ref: task_ref.exception() if not task_ref.cancelled() else None)


async def persist_summarized_result(
    result: dict[str, Any],
    *,
    user_sub: str | None = None,
    captured_on: date | None = None,
) -> PersistenceOutcome:
    """Persist a summarize result using the same KG behavior as ``/api/summarize``."""

    payload = dict(result)
    captured_on = captured_on or date.today()

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

    sb = get_supabase_scope(user_sub)
    file_duplicate = _file_graph_contains_url(source_url)

    if sb:
        repo, kg_user_id = sb
        try:
            supabase_node_id, supabase_saved, supabase_duplicate = await _persist_supabase_node(
                payload=payload,
                repo=repo,
                kg_user_id=kg_user_id,
                captured_on=captured_on,
                brief_summary=brief_summary,
                detailed_summary=detailed_summary,
            )
        except Exception as exc:
            logger.warning("Failed to add node to Supabase: %s", exc)

    file_node_id = _persist_file_node(payload, skip_duplicate=file_duplicate or supabase_duplicate)
    if file_node_id:
        payload["node_id"] = file_node_id
    payload.pop("raw_text", None)
    payload.pop("raw_metadata", None)

    return PersistenceOutcome(
        result=payload,
        file_node_id=file_node_id,
        supabase_node_id=supabase_node_id,
        supabase_saved=supabase_saved,
        supabase_duplicate=supabase_duplicate,
        kg_user_id=kg_user_id,
    )


def _persist_file_node(payload: dict[str, Any], *, skip_duplicate: bool) -> str | None:
    if skip_duplicate:
        return None
    try:
        return add_node(
            title=str(payload["title"]),
            source_type=str(payload["source_type"]),
            source_url=str(payload["source_url"]),
            summary=payload.get("brief_summary") or payload["summary"][:200],
            tags=list(payload.get("tags", [])),
        )
    except Exception as exc:
        logger.warning("Failed to add node to file KG: %s", exc)
        return None


async def _persist_supabase_node(
    *,
    payload: dict[str, Any],
    repo: KGRepository,
    kg_user_id: str,
    captured_on: date,
    brief_summary: str,
    detailed_summary: str,
) -> tuple[str, bool, bool]:
    user_uuid = UUID(kg_user_id)
    node_id = _build_supabase_node_id(
        str(payload.get("source_type", "")),
        str(payload.get("title", "")),
    )
    if repo.node_exists(user_uuid, str(payload["source_url"])):
        return node_id, False, True

    embedding = _generate_node_embedding(payload)
    node_create = _build_supabase_node_payload(
        payload=payload,
        node_id=node_id,
        captured_on=captured_on,
        embedding=embedding,
    )
    node_id = node_create.id
    repo.add_node(user_uuid, node_create)

    if embedding:
        _create_semantic_links(
            repo=repo,
            kg_user_id=kg_user_id,
            user_uuid=user_uuid,
            node_id=node_create.id,
            embedding=embedding,
        )

    if get_settings().rag_chunks_enabled:
        from website.features.rag_pipeline.ingest.hook import ingest_node_chunks

        await ingest_node_chunks(
            payload=payload,
            user_uuid=user_uuid,
            node_id=node_create.id,
        )

    _schedule_entity_extraction(
        repo=repo,
        user_id=kg_user_id,
        node_id=node_create.id,
        title=str(payload["title"]),
        detailed_summary=detailed_summary,
        brief_summary=brief_summary,
    )
    return node_id, True, False


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


def _build_supabase_node_payload(
    *,
    payload: dict[str, Any],
    node_id: str,
    captured_on: date,
    embedding: list[float] | None,
) -> KGNodeCreate:
    node_metadata: dict[str, Any] = {}
    if embedding:
        node_metadata["embedding_model"] = "gemini-embedding-001"
    return KGNodeCreate(
        id=node_id,
        name=str(payload["title"]),
        source_type=str(payload["source_type"]),
        tags=list(payload.get("tags", [])),
        url=str(payload["source_url"]),
        summary=payload.get("brief_summary") or payload["summary"][:200],
        node_date=captured_on,
        embedding=embedding,
        metadata=node_metadata,
    )


def _create_semantic_links(
    *,
    repo: KGRepository,
    kg_user_id: str,
    user_uuid: UUID,
    node_id: str,
    embedding: list[float],
) -> None:
    try:
        similar = repo.match_similar_nodes(
            kg_user_id,
            embedding,
            threshold=0.75,
            limit=5,
        )
        for hit in similar:
            hit_id = hit.get("node_id") or hit.get("id")
            hit_similarity = float(hit.get("similarity") or 0.0)
            if hit_id and hit_id != node_id and hit_similarity >= 0.75:
                repo.add_semantic_link(
                    user_id=user_uuid,
                    source_id=node_id,
                    target_id=hit_id,
                    similarity=hit_similarity,
                )
    except Exception as exc:
        logger.warning("Semantic auto-linking failed: %s", exc, exc_info=True)

