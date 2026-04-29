from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from website.core.supabase_kg.client import get_supabase_client

from .types import PageIndexRagScope, ZettelRecord


def load_knowledge_management_fixture(path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload["_meta"], payload["queries"]


def scope_from_fixture(meta: dict[str, Any], *, user_id: str) -> PageIndexRagScope:
    node_ids = tuple(meta["members_node_ids"])
    membership_hash = "|".join(sorted(node_ids))
    return PageIndexRagScope(
        scope_id=f"{meta['kasten_slug']}:iter-01",
        user_id=user_id,
        node_ids=node_ids,
        membership_hash=membership_hash,
        name=meta["kasten_name"],
        mode="temporary",
    )


def resolve_user_id_from_login(login: dict[str, str]) -> str:
    if "kg_user_id" in login:
        return login["kg_user_id"]
    client = get_supabase_client()
    render_user_id = login.get("render_user_id") or login.get("auth_id") or login.get("auth")
    if render_user_id:
        resp = client.table("kg_users").select("id").eq("render_user_id", render_user_id).limit(1).execute()
    elif "email" in login:
        resp = client.table("kg_users").select("id").eq("email", login["email"]).limit(1).execute()
    else:
        raise ValueError(("login_details" + ".txt") + " must include kg_user_id, render_user_id, or email.")
    rows = resp.data or []
    if not rows:
        raise ValueError("Naruto user could not be resolved from " + ("login_details" + ".txt") + ".")
    return str(rows[0]["id"])


def _content_from_row(row: dict[str, Any]) -> str:
    summary = row.get("summary") or ""
    summary_v2 = row.get("summary_v2") or {}
    if isinstance(summary_v2, dict):
        detailed = summary_v2.get("detailed_summary") or summary_v2.get("content")
        if detailed:
            return str(detailed)
    metadata = row.get("metadata") or {}
    if isinstance(metadata, dict):
        for key in ("content", "captured_content", "raw_content", "text"):
            if metadata.get(key):
                return str(metadata[key])
    return str(summary)


def fetch_zettels_for_scope(scope: PageIndexRagScope) -> list[ZettelRecord]:
    client = get_supabase_client()
    select_cols = "id,name,summary,summary_v2,source_type,url,tags,metadata,user_id"
    legacy_select_cols = "id,name,summary,source_type,url,tags,metadata,user_id"
    def _execute_node_query(*, scoped: bool, select_cols: str):
        query = client.table("kg_nodes").select(select_cols)
        if scoped:
            query = query.eq("user_id", scope.user_id)
        return query.in_("id", list(scope.node_ids)).execute()

    try:
        resp = _execute_node_query(scoped=True, select_cols=select_cols)
    except Exception as exc:
        if "summary_v2" not in str(exc):
            raise
        resp = _execute_node_query(scoped=True, select_cols=legacy_select_cols)
    rows = resp.data or []
    by_id = {row["id"]: row for row in rows}
    missing = [node_id for node_id in scope.node_ids if node_id not in by_id]
    if missing:
        try:
            fallback_resp = _execute_node_query(scoped=False, select_cols=select_cols)
        except Exception as exc:
            if "summary_v2" not in str(exc):
                raise
            fallback_resp = _execute_node_query(scoped=False, select_cols=legacy_select_cols)
        fallback_rows = fallback_resp.data or []
        owners: dict[str, dict[str, dict[str, Any]]] = {}
        for row in fallback_rows:
            owners.setdefault(str(row["user_id"]), {})[row["id"]] = row
        complete_owners = {
            user_id: owned
            for user_id, owned in owners.items()
            if all(node_id in owned for node_id in scope.node_ids)
        }
        if len(complete_owners) == 1:
            by_id = next(iter(complete_owners.values()))
            missing = []
    if missing:
        raise ValueError(f"Missing {len(missing)} zettels for scope: {missing}")
    return [
        ZettelRecord(
            user_id=str(row["user_id"]),
            node_id=row["id"],
            title=row.get("name") or row["id"],
            summary=row.get("summary") or "",
            content=_content_from_row(row),
            source_type=row.get("source_type") or "unknown",
            url=row.get("url"),
            tags=tuple(row.get("tags") or ()),
            metadata=row.get("metadata") or {},
        )
        for row in (by_id[node_id] for node_id in scope.node_ids)
    ]
