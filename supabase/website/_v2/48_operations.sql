-- 48_operations.sql — async request-reply operation store (Cloudflare-524 fix).
-- Shared, durable replacement for the per-worker in-memory _OPERATIONS dict so
-- POST /api/zettels/add can fast-ack 202 and any Gunicorn worker can answer
-- GET /api/operations/{id}. Composite PK (user_id, operation_id) makes the
-- store idempotent per (effective_user, client_action_id) and BOLA-safe.
-- Versioned migration: co-apply with deploy (schema-drift gate frozen).

BEGIN;

CREATE TABLE IF NOT EXISTS core.operations (
    user_id      uuid        NOT NULL,
    operation_id text        NOT NULL,
    request_hash text        NOT NULL,
    status text NOT NULL CHECK (status IN ('accepted', 'succeeded', 'failed')),
    response jsonb,
    error jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    expires_at timestamptz NOT NULL DEFAULT (now() + interval '24 hours'),
    PRIMARY KEY (user_id, operation_id)
);

CREATE INDEX IF NOT EXISTS operations_expires_at_idx
    ON core.operations (expires_at);

ALTER TABLE core.operations ENABLE ROW LEVEL SECURITY;

-- Service-role only: the app reads/writes via the service-role v2 client and
-- enforces per-user scope in the query (WHERE user_id = effective_user_id),
-- exactly like canonical_chunks_service_all. No authenticated-direct access.
DROP POLICY IF EXISTS operations_service_all ON core.operations;
CREATE POLICY operations_service_all ON core.operations
    FOR ALL
    USING (core.is_service_role())
    WITH CHECK (core.is_service_role());

COMMIT;
