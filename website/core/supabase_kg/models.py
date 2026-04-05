"""Pydantic models for Supabase knowledge graph data."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


# ── User ─────────────────────────────────────────────────────────────────────

class KGUser(BaseModel):
    """A knowledge-graph user (maps to Render auth)."""
    id: UUID
    render_user_id: str
    display_name: str | None = None
    email: str | None = None
    avatar_url: str | None = None
    is_active: bool = True
    created_at: datetime | None = None
    updated_at: datetime | None = None


class KGUserCreate(BaseModel):
    """Fields for creating a new KG user."""
    render_user_id: str
    display_name: str | None = None
    email: str | None = None
    avatar_url: str | None = None


# ── Node ─────────────────────────────────────────────────────────────────────

class KGNode(BaseModel):
    """A knowledge-graph node (persisted in Supabase)."""
    id: str
    user_id: UUID
    name: str
    source_type: str
    summary: str | None = None
    tags: list[str] = Field(default_factory=list)
    url: str
    node_date: date | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    embedding: list[float] | None = Field(default=None, description="Semantic embedding vector (768-dim)")
    created_at: datetime | None = None
    updated_at: datetime | None = None


class KGNodeCreate(BaseModel):
    """Fields for creating a new KG node."""
    id: str
    name: str
    source_type: str
    summary: str | None = None
    tags: list[str] = Field(default_factory=list)
    url: str
    node_date: date | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    embedding: list[float] | None = Field(default=None, description="Semantic embedding vector (768-dim)")


# ── Link ─────────────────────────────────────────────────────────────────────

class KGLink(BaseModel):
    """An edge between two KG nodes."""
    id: UUID
    user_id: UUID
    source_node_id: str
    target_node_id: str
    relation: str
    weight: int | None = Field(default=None, ge=1, le=10, description="Link strength 1-10; null for auto-derived links")
    link_type: str = Field(default="tag", description="Link origin: 'tag' | 'semantic' | 'entity'")
    description: str | None = Field(default=None, description="Human-readable link description")
    created_at: datetime | None = None


class KGLinkCreate(BaseModel):
    """Fields for creating a new KG link."""
    source_node_id: str
    target_node_id: str
    relation: str
    weight: int | None = Field(default=None, ge=1, le=10, description="Link strength 1-10; null for auto-derived links")
    link_type: str = Field(default="tag", description="Link origin: 'tag' | 'semantic' | 'entity'")
    description: str | None = Field(default=None, description="Human-readable link description")


# ── Graph (aggregate) ────────────────────────────────────────────────────────

class KGGraphNode(BaseModel):
    """Node in the frontend-compatible graph format."""
    id: str
    name: str
    group: str          # source_type mapped to group name
    summary: str = ""
    tags: list[str] = Field(default_factory=list)
    url: str
    date: str = ""      # ISO date string


class KGGraphLink(BaseModel):
    """Link in the frontend-compatible graph format."""
    source: str
    target: str
    relation: str
    weight: int | None = Field(default=None, ge=1, le=10, description="Link strength 1-10; null for auto-derived links")
    link_type: str = Field(default="tag", description="Link origin: 'tag' | 'semantic' | 'entity'")
    description: str | None = Field(default=None, description="Human-readable link description")


class KGGraph(BaseModel):
    """Full graph payload matching the frontend's expected structure."""
    nodes: list[KGGraphNode] = Field(default_factory=list)
    links: list[KGGraphLink] = Field(default_factory=list)
