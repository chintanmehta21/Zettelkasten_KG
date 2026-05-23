"""Bypass-dedup re-summarize for the popup Refresh button.

The normal Add Zettel flow goes through ``get_url_dedup_gate()`` — when the
URL was already ingested by anyone, the gate short-circuits and the existing
canonical row is reused (no Gemini call). That's the dedup mechanism the user
wants to bypass here: refresh is *meant* to spend a fresh Gemini call on a
URL the system has already seen.

We re-use the same summarization plumbing that ``/api/zettels/add`` uses
(``summarize_url_bundle`` + ``summary_dto``) so output shape is identical.
Quota still fires through ``require_entitlement`` (one Meter.ZETTEL credit
per refresh).

Persistence: we UPDATE content.canonical_zettels in place by normalized_url
rather than going through ``content.upsert_canonical_zettel`` (the upsert
RPC is intentionally a no-op on conflict). Because every workspace_zettel
that ever linked this URL points at the SAME canonical row, all of those
users see the refreshed summary the next time they open it.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from website.api.module_runners.summarization import (
    SummaryDTO,
    _SUMMARIZE_SEMAPHORE,
    default_gemini_client,
    require_entitlement,
    summarize_url_bundle,
    summary_dto,
)
from website.core.url_utils import normalize_url, resolve_redirects
from website.features.user_pricing.models import Meter


async def refresh_zettel_summary(
    *,
    url: str,
    user: dict | None,
    effective_user_id: UUID,
    client_action_id: str,
) -> dict[str, Any]:
    """Re-summarize ``url`` and overwrite the canonical row in place.

    Returns a dict shaped like the standard SummaryDTO model_dump plus a
    ``refreshed_at`` ISO timestamp the frontend can show in its banner.
    """
    # Quota first — fail closed before we burn a Gemini call.
    await require_entitlement(Meter.ZETTEL, user, action_id=client_action_id)

    # Match the canonicalization the add path used so the WHERE clause below
    # actually targets the row the original add wrote.
    resolved = await resolve_redirects(url)
    normalized = normalize_url(resolved)

    async with _SUMMARIZE_SEMAPHORE:
        bundle = await summarize_url_bundle(
            normalized,
            user_id=effective_user_id,
            gemini_client=default_gemini_client(),
        )

    summary: SummaryDTO = summary_dto(bundle)
    now_iso = datetime.now(timezone.utc).isoformat()

    # Direct table UPDATE — sidesteps content.upsert_canonical_zettel which
    # is a no-op on conflict (ON CONFLICT (normalized_url) DO UPDATE SET
    # normalized_url = EXCLUDED.normalized_url). All linked workspace_zettels
    # see the refreshed title/body on their next read.
    write_status = "updated"
    try:
        from website.core.supabase_v2.client import get_v2_client

        client = get_v2_client()
    except RuntimeError:
        # Supabase not configured (local dev / tests). The refresh still
        # returns the regenerated summary to the caller; just no persistence.
        write_status = "skipped_no_supabase"
    else:
        # Stash refresh info inside source_metadata so other clients can read
        # it without a schema migration. Frontend looks for refresh_info.at.
        existing_meta = summary.metadata if isinstance(summary.metadata, dict) else {}
        update_payload: dict[str, Any] = {
            "title": summary.title,
            "body_md": summary.detailed_summary or summary.summary,
            "source_metadata": {
                **existing_meta,
                "refresh_info": {
                    "at": now_iso,
                    "by_user_id": str(effective_user_id),
                },
            },
        }
        (
            client.schema("content")
            .table("canonical_zettels")
            .update(update_payload)
            .eq("normalized_url", normalized)
            .execute()
        )

    response = summary.model_dump(mode="json")
    response.update(
        {
            "refreshed_at": now_iso,
            "refreshed_by_user_id": str(effective_user_id),
            "normalized_url": normalized,
            "write_status": write_status,
        }
    )
    return response
