"""Persistent chat session storage over Supabase."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from website.features.rag_pipeline.types import AnswerTurn, ChatTurn
from website.core.supabase_kg.client import get_supabase_client

_REWRITER_WINDOW = 5


class ChatSessionStore:
    def __init__(self, supabase: Any | None = None):
        self._supabase = supabase or get_supabase_client()

    async def create_session(
        self,
        *,
        user_id,
        sandbox_id,
        title="New conversation",
        initial_scope_filter=None,
        quality_mode="fast",
    ):
        payload = {
            "user_id": str(user_id),
            "sandbox_id": str(sandbox_id) if sandbox_id else None,
            "title": title,
            "last_scope_filter": initial_scope_filter or {},
            "quality_mode": quality_mode,
        }
        response = self._supabase.table("chat_sessions").insert(payload).execute()
        return response.data[0]["id"]

    async def get_session(self, session_id, user_id):
        response = (
            self._supabase.table("chat_sessions")
            .select("*")
            .eq("id", str(session_id))
            .eq("user_id", str(user_id))
            .limit(1)
            .execute()
        )
        return response.data[0] if response.data else None

    async def list_sessions(self, user_id, sandbox_id=None, limit=50):
        query = (
            self._supabase.table("chat_sessions")
            .select("*")
            .eq("user_id", str(user_id))
            .order("last_message_at", desc=True)
            .limit(limit)
        )
        if sandbox_id is not None:
            query = query.eq("sandbox_id", str(sandbox_id))
        response = query.execute()
        return response.data or []

    async def list_messages(self, session_id, user_id, limit=100):
        response = (
            self._supabase.table("chat_messages")
            .select("*")
            .eq("session_id", str(session_id))
            .eq("user_id", str(user_id))
            .order("created_at")
            .limit(limit)
            .execute()
        )
        return response.data or []

    async def delete_session(self, session_id, user_id):
        response = (
            self._supabase.table("chat_sessions")
            .delete()
            .eq("id", str(session_id))
            .eq("user_id", str(user_id))
            .execute()
        )
        return bool(response.data)

    async def update_session(
        self,
        session_id,
        user_id,
        *,
        sandbox_id=None,
        title=None,
        last_scope_filter=None,
        quality_mode=None,
    ):
        payload = {}
        if sandbox_id is not None:
            payload["sandbox_id"] = str(sandbox_id)
        if title is not None:
            payload["title"] = title
        if last_scope_filter is not None:
            payload["last_scope_filter"] = last_scope_filter
        if quality_mode is not None:
            payload["quality_mode"] = quality_mode
        if not payload:
            return None

        response = (
            self._supabase.table("chat_sessions")
            .update(payload)
            .eq("id", str(session_id))
            .eq("user_id", str(user_id))
            .execute()
        )
        return response.data[0] if response.data else None

    async def load_recent_turns(self, session_id, user_id, limit=_REWRITER_WINDOW):
        response = (
            self._supabase.table("chat_messages")
            .select("role, content, created_at")
            .eq("session_id", str(session_id))
            .eq("user_id", str(user_id))
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )
        rows = list(reversed(response.data or []))
        return [ChatTurn(**row) for row in rows]

    async def append_user_message(self, *, session_id, user_id, content):
        payload = {
            "session_id": str(session_id),
            "user_id": str(user_id),
            "role": "user",
            "content": content,
        }
        response = self._supabase.table("chat_messages").insert(payload).execute()
        return response.data[0]

    async def append_assistant_message(self, *, session_id, user_id, turn: AnswerTurn):
        payload = {
            "session_id": str(session_id),
            "user_id": str(user_id),
            "role": "assistant",
            "content": turn.content,
            "citations": [citation.model_dump() for citation in turn.citations],
            "retrieved_node_ids": list(turn.retrieved_node_ids),
            "retrieved_chunk_ids": [str(chunk_id) for chunk_id in turn.retrieved_chunk_ids],
            "llm_model": turn.llm_model,
            "token_counts": turn.token_counts,
            "latency_ms": turn.latency_ms,
            "trace_id": turn.trace_id,
            "critic_verdict": turn.critic_verdict,
            "critic_notes": turn.critic_notes,
            "query_class": turn.query_class.value,
        }
        response = self._supabase.table("chat_messages").insert(payload).execute()
        return response.data[0]

    async def auto_title_session(self, session_id, user_id, first_query: str):
        title = first_query.strip().split("\n")[0][:60]
        if len(title) == 60:
            title = title.rstrip() + "..."
        self._supabase.table("chat_sessions").update({"title": title}).eq(
            "id", str(session_id)
        ).eq("user_id", str(user_id)).execute()
        return title

