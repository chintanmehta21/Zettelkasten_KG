"""Supabase-backed reads/writes of user_metadata.avatar_url."""
from __future__ import annotations

import logging
from typing import Any

from website.core.supabase_v2.client import get_v2_client

logger = logging.getLogger("website.user_profile.repository")


def update_avatar(user_id: str, avatar_url: str) -> dict[str, Any]:
    """Patch raw_user_meta_data.avatar_url for the given user.

    Uses the service-role client (server-only). Returns the new profile dict
    with at least {id, email, avatar_url}. Sync — callers in async routes
    must dispatch via asyncio.to_thread.
    """
    sb = get_v2_client()
    res = sb.auth.admin.update_user_by_id(
        user_id,
        {"user_metadata": {"avatar_url": avatar_url}},
    )
    user = res.user
    meta = (user.user_metadata or {}) if user else {}
    return {
        "id": user.id if user else user_id,
        "email": user.email if user else None,
        "avatar_url": meta.get("avatar_url", avatar_url),
        "display_name": meta.get("full_name") or meta.get("name"),
    }
