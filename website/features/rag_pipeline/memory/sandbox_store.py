"""Persistent sandbox storage over Supabase."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from website.core.supabase_kg.client import get_supabase_client


class SandboxStore:
    def __init__(self, supabase: Any | None = None):
        self._supabase = supabase or get_supabase_client()

    async def list_sandboxes(self, user_id: UUID, limit: int = 50):
        response = (
            self._supabase.table("rag_sandbox_stats")
            .select("*")
            .eq("user_id", str(user_id))
            .order("last_used_at", desc=True, nullsfirst=False)
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )
        return response.data or []

    async def get_sandbox(self, sandbox_id: UUID, user_id: UUID):
        response = (
            self._supabase.table("rag_sandbox_stats")
            .select("*")
            .eq("id", str(sandbox_id))
            .eq("user_id", str(user_id))
            .limit(1)
            .execute()
        )
        return response.data[0] if response.data else None

    async def create_sandbox(
        self,
        *,
        user_id: UUID,
        name: str,
        description: str | None = None,
        icon: str | None = None,
        color: str | None = None,
        default_quality: str = "fast",
    ):
        payload = {
            "user_id": str(user_id),
            "name": name,
            "description": description,
            "icon": icon,
            "color": color,
            "default_quality": default_quality,
        }
        response = self._supabase.table("rag_sandboxes").insert(payload).execute()
        created = response.data[0]
        return await self.get_sandbox(UUID(created["id"]), user_id)

    async def update_sandbox(
        self,
        sandbox_id: UUID,
        user_id: UUID,
        *,
        name: str | None = None,
        description: str | None = None,
        icon: str | None = None,
        color: str | None = None,
        default_quality: str | None = None,
    ):
        payload = {}
        if name is not None:
            payload["name"] = name
        if description is not None:
            payload["description"] = description
        if icon is not None:
            payload["icon"] = icon
        if color is not None:
            payload["color"] = color
        if default_quality is not None:
            payload["default_quality"] = default_quality
        if not payload:
            return await self.get_sandbox(sandbox_id, user_id)

        response = (
            self._supabase.table("rag_sandboxes")
            .update(payload)
            .eq("id", str(sandbox_id))
            .eq("user_id", str(user_id))
            .execute()
        )
        if not response.data:
            return None
        return await self.get_sandbox(sandbox_id, user_id)

    async def delete_sandbox(self, sandbox_id: UUID, user_id: UUID) -> bool:
        response = (
            self._supabase.table("rag_sandboxes")
            .delete()
            .eq("id", str(sandbox_id))
            .eq("user_id", str(user_id))
            .execute()
        )
        return bool(response.data)

    async def list_members(self, sandbox_id: UUID, user_id: UUID, limit: int = 500):
        response = (
            self._supabase.table("rag_sandbox_members")
            .select("node_id, added_via, added_filter, added_at, kg_nodes(id, name, source_type, url, summary, tags, node_date)")
            .eq("sandbox_id", str(sandbox_id))
            .eq("user_id", str(user_id))
            .order("added_at", desc=True)
            .limit(limit)
            .execute()
        )
        return response.data or []

    async def add_members(
        self,
        *,
        sandbox_id: UUID,
        user_id: UUID,
        node_ids: list[str] | None = None,
        tags: list[str] | None = None,
        tag_mode: str = "all",
        source_types: list[str] | None = None,
        added_via: str = "manual",
    ) -> int:
        response = self._supabase.rpc(
            "rag_bulk_add_to_sandbox",
            {
                "p_user_id": str(user_id),
                "p_sandbox_id": str(sandbox_id),
                "p_tags": tags,
                "p_tag_mode": tag_mode,
                "p_source_types": source_types,
                "p_node_ids": node_ids,
                "p_added_via": added_via,
            },
        ).execute()
        # Post-2026-04-26 migration: RPC returns jsonb
        # {added_count, candidate_count, dropped_node_ids} instead of a bare int.
        # Tolerate the legacy int return shape during the deploy transition window.
        data = response.data
        if isinstance(data, dict):
            return int(data.get("added_count", 0) or 0)
        return int(data or 0)

    async def remove_member(self, sandbox_id: UUID, user_id: UUID, node_id: str) -> bool:
        response = (
            self._supabase.table("rag_sandbox_members")
            .delete()
            .eq("sandbox_id", str(sandbox_id))
            .eq("user_id", str(user_id))
            .eq("node_id", node_id)
            .execute()
        )
        return bool(response.data)

    async def remove_members(self, sandbox_id: UUID, user_id: UUID, node_ids: list[str]) -> int:
        if not node_ids:
            return 0
        response = (
            self._supabase.table("rag_sandbox_members")
            .delete()
            .eq("sandbox_id", str(sandbox_id))
            .eq("user_id", str(user_id))
            .in_("node_id", node_ids)
            .execute()
        )
        return len(response.data or [])

    async def touch_sandbox(self, sandbox_id: UUID, user_id: UUID):
        response = (
            self._supabase.table("rag_sandboxes")
            .update({"last_used_at": datetime.now(timezone.utc).isoformat()})
            .eq("id", str(sandbox_id))
            .eq("user_id", str(user_id))
            .execute()
        )
        return response.data[0] if response.data else None
