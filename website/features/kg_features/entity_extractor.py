"""M1 — Entity Extraction via Gemini structured output.

Extracts named entities and their relationships from summarised KG node
content.  Uses a streamlined pipeline:

1. Single structured JSON extraction (analysis + extraction in one call).
2. Optional gleaning loop to catch missed entities.
3. Post-processing: dedup, normalisation, type validation.
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass
from typing import Callable

import numpy as np
from google.genai import types
from pydantic import BaseModel, Field, field_validator

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

    @field_validator("strength", mode="before")
    @classmethod
    def coerce_strength(cls, v):
        if isinstance(v, int):
            return max(1, min(v, 10))
        if isinstance(v, str):
            try:
                return max(1, min(int(v), 10))
            except ValueError:
                return 5
        return 5


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

# Single-call prompt: combines analysis + structured extraction into one step.
_EXTRACT_PROMPT = """\
You are an expert knowledge-graph builder.  Extract ALL explicitly mentioned
entities and relationships from the content below.

GROUNDING RULE: Do NOT add any entity or relationship that is not explicitly
mentioned in the text.  Every entity must have a direct textual basis.

Allowed entity types: {entity_types}
Allowed relationship types: {relationship_types}

EXAMPLE:
Input: "React Compiler, developed by Andrew Clark and the Meta team, is an
optimizing compiler that automatically memoizes React components. It uses
MLIR under the hood and is inspired by the Forget framework."

Expected output:
{{
  "entities": [
    {{"id": "react_compiler", "type": "TECHNOLOGY", "description": "Optimizing compiler for React"}},
    {{"id": "andrew_clark", "type": "PERSON", "description": "Developer at Meta"}},
    {{"id": "meta", "type": "ORGANIZATION", "description": "Tech company"}},
    {{"id": "mlir", "type": "FRAMEWORK", "description": "Compiler infrastructure"}},
    {{"id": "forget", "type": "FRAMEWORK", "description": "Inspiration for React Compiler"}}
  ],
  "relationships": [
    {{"source": "react_compiler", "target": "meta", "type": "CREATED_BY", "strength": 8}},
    {{"source": "react_compiler", "target": "mlir", "type": "USES", "strength": 7}},
    {{"source": "react_compiler", "target": "forget", "type": "INSPIRED_BY", "strength": 6}}
  ]
}}

---
Title: {title}

{summary}
---

Return a JSON object with "entities" and "relationships" arrays.
{type_hint}"""

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
    """Remove near-duplicate entities using cosine similarity."""
    if not embed_fn or len(entities) <= 1:
        return entities

    texts = [e.id for e in entities]
    embeddings = embed_fn(texts)

    if not embeddings or len(embeddings) != len(entities):
        return entities

    if any(len(v) == 0 for v in embeddings):
        return entities

    keep: list[ExtractedEntity] = []
    keep_vecs: list[np.ndarray] = []

    for entity, vec_list in zip(entities, embeddings):
        vec = np.array(vec_list, dtype=np.float64)
        is_dup = False
        for kept_ent, kept_vec in zip(keep, keep_vecs):
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
        """Run the extraction pipeline.

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

        type_hint = ""
        if existing_types:
            type_hint = (
                f"\nTYPES ALREADY USED IN THIS KG: {', '.join(sorted(existing_types))}\n"
                "Prefer these over creating new ones when the meaning is the same.\n"
            )

        try:
            # ── Single-call extraction (merged analysis + structured) ──
            extract_prompt = _EXTRACT_PROMPT.format(
                entity_types=entity_types,
                relationship_types=relationship_types,
                title=title,
                summary=summary,
                type_hint=type_hint,
            )
            extract_response, _, _ = await asyncio.wait_for(
                pool.generate_content(
                    extract_prompt,
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                    ),
                    starting_model=model,
                    label="Entity extraction",
                ),
                timeout=15.0,
            )
            result = ExtractionResult.model_validate_json(extract_response.text)

            # ── Optional gleaning (skip if already found enough) ──────���
            if max_gleanings > 0 and len(result.entities) < 3:
                conversation_contents = [
                    types.Content(role="user", parts=[types.Part(text=extract_prompt)]),
                    types.Content(role="model", parts=[types.Part(text=extract_response.text)]),
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
                        timeout=15.0,
                    )
                    glean_text = glean_response.text
                    glean_result = ExtractionResult.model_validate_json(glean_text)

                    existing_ids = {e.id for e in result.entities}
                    new_entities = [
                        e for e in glean_result.entities if e.id not in existing_ids
                    ]
                    if not new_entities:
                        break

                    result.entities.extend(new_entities)
                    result.relationships.extend(glean_result.relationships)

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
            logger.error("Entity extraction failed for '%s': %s", title, exc, exc_info=True)
            return ExtractionResult()

    def _postprocess(self, result: ExtractionResult) -> ExtractionResult:
        """Normalise IDs, relationship types, validate, and deduplicate."""
        allowed_entity_set = {t.upper() for t in self.config.allowed_entity_types}
        allowed_rel_set = {t.upper() for t in self.config.allowed_relationship_types}

        normalised_entities: list[ExtractedEntity] = []
        for e in result.entities:
            cleaned_entity = ExtractedEntity(
                id=_normalize_id(e.id),
                type=e.type.upper(),
                description=e.description,
            )
            if cleaned_entity.type in allowed_entity_set and cleaned_entity.id:
                normalised_entities.append(cleaned_entity)

        if self.config.enable_entity_dedup:
            normalised_entities = _deduplicate_entities(
                normalised_entities,
                self.embed_fn,
                self.config.dedup_similarity_threshold,
            )

        valid_ids = {e.id for e in normalised_entities}

        normalised_rels: list[ExtractedRelationship] = []
        for r in result.relationships:
            cleaned_relationship = ExtractedRelationship(
                source=_normalize_id(r.source),
                target=_normalize_id(r.target),
                type=_normalize_relationship_type(r.type),
                strength=r.strength,
                description=r.description,
            )
            if (
                cleaned_relationship.type in allowed_rel_set
                and cleaned_relationship.source in valid_ids
                and cleaned_relationship.target in valid_ids
                and cleaned_relationship.source != cleaned_relationship.target
            ):
                normalised_rels.append(cleaned_relationship)

        return ExtractionResult(
            entities=normalised_entities,
            relationships=normalised_rels,
        )
