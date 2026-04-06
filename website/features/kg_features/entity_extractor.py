"""M1 — Entity Extraction via Gemini structured output.

Extracts named entities and their relationships from summarised KG node
content.  Uses a multi-step pipeline:

1. Free-form analysis (grounded — no hallucinated entities).
2. Structured JSON extraction via ``response_mime_type``.
3. Optional gleaning loop to catch missed entities.
4. Post-processing: dedup, normalisation, type validation.
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass
from typing import Callable

import numpy as np
from google.genai import types
from pydantic import BaseModel, Field

from website.features.api_key_switching import get_key_pool

logger = logging.getLogger(__name__)


# ── Pydantic models ─────────────────────────────────────────────────────────

class ExtractedEntity(BaseModel):
    """A single entity extracted from text."""
    id: str
    type: str
    description: str = ""


class ExtractedRelationship(BaseModel):
    """A directed relationship between two entities."""
    source: str
    target: str
    type: str
    strength: int = Field(default=5, ge=1, le=10)
    description: str = ""


class ExtractionResult(BaseModel):
    """Complete extraction output — entities + relationships."""
    entities: list[ExtractedEntity] = Field(default_factory=list)
    relationships: list[ExtractedRelationship] = Field(default_factory=list)


# ── Config ──────────────────────────────────────────────────────────────────

@dataclass
class ExtractionConfig:
    """Tuning knobs for entity extraction."""

    allowed_entity_types: tuple[str, ...] = (
        "PERSON", "ORGANIZATION", "TECHNOLOGY", "CONCEPT",
        "TOOL", "LANGUAGE", "FRAMEWORK", "PLATFORM",
        "PATTERN", "ALGORITHM",
    )
    allowed_relationship_types: tuple[str, ...] = (
        "USES", "IMPLEMENTS", "EXTENDS", "PART_OF", "CREATED_BY",
        "RELATED_TO", "ALTERNATIVE_TO", "DEPENDS_ON", "INSPIRED_BY",
    )
    max_gleanings: int = 1          # capped at 3 in extract()
    enable_entity_dedup: bool = True
    dedup_similarity_threshold: float = 0.90
    model: str = "gemini-2.5-flash"


# ── Prompts ─────────────────────────────────────────────────────────────────

_ANALYSIS_PROMPT = """\
You are an expert knowledge-graph builder.  Analyse the following content
and identify ALL explicitly mentioned entities and relationships.

GROUNDING RULE: Do NOT add any entity or relationship that is not
explicitly mentioned in the text.  Every entity must have a direct textual
basis.  If you are unsure, leave it out.

Allowed entity types: {entity_types}
Allowed relationship types: {relationship_types}

EXAMPLE:
Input: "React Compiler, developed by Andrew Clark and the Meta team, is an
optimizing compiler that automatically memoizes React components. It uses
MLIR under the hood and is inspired by the Forget framework."

Expected entities:
- React Compiler (TECHNOLOGY)
- Andrew Clark (PERSON)
- Meta (ORGANIZATION)
- MLIR (FRAMEWORK)
- Forget (FRAMEWORK)

Expected relationships:
- React Compiler CREATED_BY Meta
- React Compiler USES MLIR
- React Compiler INSPIRED_BY Forget

---
Title: {title}

{summary}
---

List the entities and relationships you found in free-form text.
"""

_STRUCTURED_PROMPT = """\
Given this analysis, produce a JSON object matching the schema below.
Only include entities and relationships that were identified in the
analysis.  Do NOT invent new ones.

Schema:
{schema}

Analysis:
{analysis}
"""

_GLEANING_PROMPT_MULTI_TURN = """Review the original text one more time. Are there any entities \
or relationships you missed in your previous extraction? If yes, return ONLY the NEW ones as \
JSON (same schema). If nothing was missed, return {"entities": [], "relationships": []}."""


# ── Post-processing helpers ─────────────────────────────────────────────────

_ID_CLEAN_RE = re.compile(r"[^a-z0-9_\-]")


def _normalize_id(raw: str) -> str:
    """Lowercase, strip special chars, collapse whitespace to underscores."""
    return _ID_CLEAN_RE.sub("", raw.lower().replace(" ", "_"))


def _normalize_relationship_type(raw: str) -> str:
    """Convert to UPPER_SNAKE_CASE."""
    return re.sub(r"[^A-Z0-9]", "_", raw.upper().strip()).strip("_")


def _deduplicate_entities(
    entities: list[ExtractedEntity],
    embed_fn: Callable[[list[str]], list[list[float]]] | None,
    threshold: float = 0.90,
) -> list[ExtractedEntity]:
    """Remove near-duplicate entities using cosine similarity.

    Two entities are considered duplicates only if they share the same
    ``type`` AND their name embeddings exceed *threshold*.
    """
    if not embed_fn or len(entities) <= 1:
        return entities

    texts = [e.id for e in entities]
    embeddings = embed_fn(texts)

    # If embedding failed, return as-is.
    if not embeddings or any(len(v) == 0 for v in embeddings):
        return entities

    keep: list[ExtractedEntity] = []
    keep_vecs: list[np.ndarray] = []

    for entity, vec_list in zip(entities, embeddings):
        vec = np.array(vec_list, dtype=np.float64)
        is_dup = False
        for kept_ent, kept_vec in zip(keep, keep_vecs):
            # Type-matching guard: only dedup within the same type.
            if entity.type != kept_ent.type:
                continue
            sim = float(np.dot(vec, kept_vec))
            if sim >= threshold:
                is_dup = True
                break
        if not is_dup:
            keep.append(entity)
            keep_vecs.append(vec)

    return keep


# ── Main extractor ──────────────────────────────────────────────────────────

class EntityExtractor:
    """Extract entities and relationships from KG node content."""

    def __init__(
        self,
        config: ExtractionConfig | None = None,
        embed_fn: Callable[[list[str]], list[list[float]]] | None = None,
    ) -> None:
        self.config = config or ExtractionConfig()
        self.embed_fn = embed_fn

    async def extract(
        self,
        summary: str,
        title: str = "",
        existing_types: list[str] | None = None,
    ) -> ExtractionResult:
        """Run the full extraction pipeline.

        Returns an empty :class:`ExtractionResult` on any failure so the
        caller never has to handle exceptions.
        """
        if not summary or not summary.strip():
            return ExtractionResult()

        pool = get_key_pool()
        model = self.config.model
        max_gleanings = min(self.config.max_gleanings, 3)

        entity_types = ", ".join(self.config.allowed_entity_types)
        relationship_types = ", ".join(self.config.allowed_relationship_types)

        schema = ExtractionResult.model_json_schema()

        try:
            # ── Step 1: Free-form analysis ──────────────────────────────
            analysis_prompt = _ANALYSIS_PROMPT.format(
                entity_types=entity_types,
                relationship_types=relationship_types,
                title=title,
                summary=summary,
            )
            analysis_response, _, _ = await asyncio.wait_for(
                pool.generate_content(
                    analysis_prompt,
                    starting_model=model,
                    label="Entity analysis",
                ),
                timeout=10.0,
            )
            analysis_text = analysis_response.text

            # ── Step 2: Structured JSON extraction ──────────────────────
            type_hint = ""
            if existing_types:
                type_hint = (
                    f"\nTYPES ALREADY USED IN THIS KG: {', '.join(sorted(existing_types))}\n"
                    "Prefer these over creating new ones when the meaning is the same.\n"
                )
            structured_prompt = _STRUCTURED_PROMPT.format(
                schema=schema,
                analysis=analysis_text,
            ) + type_hint

            structured_response, _, _ = await asyncio.wait_for(
                pool.generate_content(
                    structured_prompt,
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                        response_schema=ExtractionResult,
                    ),
                    starting_model=model,
                    label="Entity structured",
                ),
                timeout=10.0,
            )
            structured_text = structured_response.text

            result = ExtractionResult.model_validate_json(structured_text)

            # ── Step 3: Multi-turn gleaning loop ────────────────────────
            # Build conversation history so the model sees its own prior
            # turns (matches GraphRAG's multi-turn gleaning approach).
            conversation_contents = [
                types.Content(role="user", parts=[types.Part(text=analysis_prompt)]),
                types.Content(role="model", parts=[types.Part(text=analysis_text)]),
                types.Content(role="user", parts=[types.Part(text=structured_prompt)]),
                types.Content(role="model", parts=[types.Part(text=structured_text)]),
            ]

            for _glean_round in range(max_gleanings):
                conversation_contents.append(
                    types.Content(
                        role="user",
                        parts=[types.Part(text=_GLEANING_PROMPT_MULTI_TURN)],
                    )
                )
                glean_response, _, _ = await asyncio.wait_for(
                    pool.generate_content(
                        conversation_contents,
                        config=types.GenerateContentConfig(
                            response_mime_type="application/json",
                            response_schema=ExtractionResult,
                        ),
                        starting_model=model,
                        label="Entity gleaning",
                    ),
                    timeout=10.0,
                )
                glean_text = glean_response.text

                glean_result = ExtractionResult.model_validate_json(glean_text)

                # Zero-new-entities termination (check against existing IDs).
                existing_ids = {e.id for e in result.entities}
                new_entities = [
                    e for e in glean_result.entities if e.id not in existing_ids
                ]
                if not new_entities:
                    break

                result.entities.extend(new_entities)
                result.relationships.extend(glean_result.relationships)

                # Append model response for next iteration's context.
                conversation_contents.append(
                    types.Content(role="model", parts=[types.Part(text=glean_text)])
                )

            # ── Post-processing ─────────────────────────────────────────
            result = self._postprocess(result)

            return result

        except asyncio.TimeoutError:
            logger.warning("Entity extraction timed out for '%s'", title)
            return ExtractionResult()
        except Exception as exc:
            logger.error("Entity extraction failed for '%s': %s", title, exc)
            return ExtractionResult()

    def _postprocess(self, result: ExtractionResult) -> ExtractionResult:
        """Normalise IDs, relationship types, validate, and deduplicate."""
        allowed_entity_set = {t.upper() for t in self.config.allowed_entity_types}
        allowed_rel_set = {t.upper() for t in self.config.allowed_relationship_types}

        # Normalise entity IDs and filter invalid types.
        normalised_entities: list[ExtractedEntity] = []
        for e in result.entities:
            e.id = _normalize_id(e.id)
            e.type = e.type.upper()
            if e.type in allowed_entity_set and e.id:
                normalised_entities.append(e)

        # Deduplicate entities.
        if self.config.enable_entity_dedup:
            normalised_entities = _deduplicate_entities(
                normalised_entities,
                self.embed_fn,
                self.config.dedup_similarity_threshold,
            )

        # Build a set of valid entity IDs for relationship validation.
        valid_ids = {e.id for e in normalised_entities}

        # Normalise relationships and filter.
        normalised_rels: list[ExtractedRelationship] = []
        for r in result.relationships:
            r.source = _normalize_id(r.source)
            r.target = _normalize_id(r.target)
            r.type = _normalize_relationship_type(r.type)
            if (
                r.type in allowed_rel_set
                and r.source in valid_ids
                and r.target in valid_ids
                and r.source != r.target
            ):
                normalised_rels.append(r)

        return ExtractionResult(
            entities=normalised_entities,
            relationships=normalised_rels,
        )
