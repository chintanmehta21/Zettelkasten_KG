"""Repository for DB v2 ``pipelines.*`` run-tracking tables.

Used by the Phase B KG-population hook for idempotency + observability:
each per-zettel KG-extract pass is tracked as a
``pipelines.pipeline_runs`` row of ``kind='kg_extract'``. The canonical
zettel id is stored in the ``config`` jsonb (the schema has no dedicated
column — see ``supabase/website/_v2/05_pipelines_schema.sql``).

LD-8 (Migration 70): four terminal states distinguish retry policy —
``succeeded`` (edges > 0; truly terminal), ``succeeded_empty`` (clean run,
edges = 0; retryable after 24 h), ``failed_retryable`` (transient quota /
RPC / network; backoff retry), ``failed_permanent`` (corrupt input or
schema invariant; never retry).
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from supabase import Client

from website.core.supabase_v2.client import get_v2_client


_TERMINAL_BLOCKING_STATES = ("succeeded", "failed_permanent")
_TERMINAL_RETRYABLE_STATES = ("succeeded_empty", "failed_retryable")
_ALL_VALID_STATES = (
    "succeeded",
    "succeeded_empty",
    "failed_retryable",
    "failed_permanent",
    "failed",     # legacy (pre-Migration 70); still accepted for backwards compat
    "cancelled",  # operator-cancelled
)


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
        """True iff a truly-terminal run of *kind* already exists for the zettel.

        LD-8 idempotency gate (post-Migration 70). Returns True ONLY for terminal
        states that should block retry:
          - 'succeeded' with edges > 0 (real terminal success)
          - 'failed_permanent' (intentional terminal failure — corrupt input)

        Does NOT gate on:
          - 'succeeded_empty' (retryable after 24h — quota likely recovered)
          - 'failed_retryable' (retryable after backoff)
          - 'in_progress' / 'pending' (let a new run replace a stale one)

        Workspace-scoped: the ``workspace_id`` equality filter is the tenant
        fence (service-role bypasses RLS). The canonical zettel id is matched
        inside the ``config`` jsonb via PostgREST's ``->>`` arrow filter.
        """
        response = (
            self._client.schema("pipelines")
            .table("pipeline_runs")
            .select("id,status,metrics")
            .eq("workspace_id", str(workspace_id))
            .eq("kind", kind)
            .in_("status", list(_TERMINAL_BLOCKING_STATES))
            .eq("config->>canonical_zettel_id", str(canonical_zettel_id))
            .limit(5)
            .execute()
        )
        rows = list(response.data or [])
        for row in rows:
            status = str(row.get("status") or "")
            if status == "failed_permanent":
                return True
            if status == "succeeded":
                metrics = row.get("metrics") or {}
                try:
                    edges = int(metrics.get("edges", 0) or 0)
                except (TypeError, ValueError):
                    edges = 0
                if edges > 0:
                    return True
                # edges == 0 on a 'succeeded' row → legacy pre-Migration-70 path
                # that hasn't been backfilled yet. Treat as retryable.
        return False

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
        """Mark a run 'succeeded' / 'failed' with optional metrics/error.

        Legacy entrypoint (pre-Migration 70). Prefer ``finish_run_with_state``
        for new code so retry timestamps are written atomically.
        """
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

    def finish_run_with_state(
        self,
        *,
        run_id: UUID,
        state: str,
        metrics: dict | None = None,
        error: str | None = None,
        retry_eligible_after: datetime | None = None,
    ) -> None:
        """LD-8: write a terminal state with optional retry timestamp.

        ``state`` is one of:
          - ``succeeded``         — edges > 0 produced (terminal, never retried)
          - ``succeeded_empty``   — clean run, edges == 0 (retry after 24h)
          - ``failed_retryable``  — transient quota/RPC/network (retry w/ backoff)
          - ``failed_permanent``  — corrupt input / schema invariant (never retried)

        Workspace-scoped invariants are upheld by the caller; this method only
        writes the terminal row patch. ``retry_eligible_after`` is only
        meaningful for the two retryable states.
        """
        if state not in _ALL_VALID_STATES:
            raise ValueError(f"invalid terminal run state: {state!r}")
        patch: dict = {"status": state}
        if metrics is not None:
            patch["metrics"] = metrics
        if error is not None:
            patch["error"] = str(error)[:2000]
        if retry_eligible_after is not None:
            patch["retry_eligible_after"] = retry_eligible_after.astimezone(timezone.utc).isoformat()
        (
            self._client.schema("pipelines")
            .table("pipeline_runs")
            .update(patch)
            .eq("id", str(run_id))
            .execute()
        )

    def list_retryable_runs(
        self,
        *,
        kind: str = "kg_extract",
        limit: int = 100,
    ) -> list[dict]:
        """LD-8: return runs whose ``retry_eligible_after`` has elapsed.

        Used by the retry-sweep scheduler to pick up succeeded_empty /
        failed_retryable runs whose grace window has passed. Ordered by
        ``retry_eligible_after`` ASC so the oldest backlog is processed first.
        """
        now_iso = datetime.now(timezone.utc).isoformat()
        response = (
            self._client.schema("pipelines")
            .table("pipeline_runs")
            .select("id,config,status,attempt_count,retry_eligible_after")
            .eq("kind", kind)
            .in_("status", list(_TERMINAL_RETRYABLE_STATES))
            .lte("retry_eligible_after", now_iso)
            .order("retry_eligible_after", desc=False)
            .limit(max(1, limit))
            .execute()
        )
        return list(response.data or [])
