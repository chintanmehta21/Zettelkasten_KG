"""Repository for DB v2 ``pipelines.*`` run-tracking tables.

Used by the Phase B KG-population hook for idempotency + observability:
each per-zettel KG-extract pass is tracked as a
``pipelines.pipeline_runs`` row of ``kind='kg_extract'``. The canonical
zettel id is stored in the ``config`` jsonb (the schema has no dedicated
column — see ``supabase/website/_v2/05_pipelines_schema.sql``).
"""

from __future__ import annotations

from uuid import UUID

from supabase import Client

from website.core.supabase_v2.client import get_v2_client


class PipelinesRepository:
    def __init__(self, client: Client | None = None) -> None:
        self._client = client or get_v2_client()

    def has_succeeded_run(
        self,
        *,
        workspace_id: UUID,
        kind: str,
        canonical_zettel_id: UUID,
    ) -> bool:
        """True iff a 'succeeded' run of *kind* already exists for the zettel.

        Workspace-scoped: the ``workspace_id`` equality filter is the tenant
        fence (service-role bypasses RLS). The canonical zettel id is matched
        inside the ``config`` jsonb via PostgREST's ``->>`` arrow filter.
        """
        response = (
            self._client.schema("pipelines")
            .table("pipeline_runs")
            .select("id")
            .eq("workspace_id", str(workspace_id))
            .eq("kind", kind)
            .eq("status", "succeeded")
            .eq("config->>canonical_zettel_id", str(canonical_zettel_id))
            .limit(1)
            .execute()
        )
        return bool(response.data)

    def start_run(
        self,
        *,
        workspace_id: UUID,
        kind: str,
        canonical_zettel_id: UUID,
    ) -> UUID:
        """Insert a 'running' run row and return its id."""
        response = (
            self._client.schema("pipelines")
            .table("pipeline_runs")
            .insert(
                {
                    "workspace_id": str(workspace_id),
                    "kind": kind,
                    "status": "running",
                    "config": {"canonical_zettel_id": str(canonical_zettel_id)},
                }
            )
            .execute()
        )
        if not response.data:
            raise RuntimeError("pipeline_runs insert returned no row")
        return UUID(str(response.data[0]["id"]))

    def finish_run(
        self,
        *,
        run_id: UUID,
        status: str,
        metrics: dict | None = None,
        error: str | None = None,
    ) -> None:
        """Mark a run 'succeeded' / 'failed' with optional metrics/error."""
        if status not in ("succeeded", "failed", "cancelled"):
            raise ValueError(f"invalid terminal run status: {status!r}")
        patch: dict = {"status": status}
        if metrics is not None:
            patch["metrics"] = metrics
        if error is not None:
            # Defensive: keep the stored error operator-safe and bounded.
            patch["error"] = str(error)[:2000]
        (
            self._client.schema("pipelines")
            .table("pipeline_runs")
            .update(patch)
            .eq("id", str(run_id))
            .execute()
        )
