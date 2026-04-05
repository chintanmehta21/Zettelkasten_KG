-- ============================================================================
-- Supabase Knowledge Graph Schema
-- Run this in the Supabase SQL Editor to create all tables, indexes, RLS
-- policies, and views for multi-user knowledge graph storage.
-- ============================================================================

-- ── Enable required extensions ───────────────────────────────────────────────

-- pgcrypto for gen_random_uuid() (usually enabled by default in Supabase)
CREATE EXTENSION IF NOT EXISTS pgcrypto;


-- ── Table: kg_users ─────────────────────────────────────────────────────────
-- Maps external Render auth users to KG-local records.
-- No passwords or sessions — auth is handled entirely by Render.

CREATE TABLE IF NOT EXISTS kg_users (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    render_user_id  TEXT        UNIQUE NOT NULL,
    display_name    TEXT,
    email           TEXT,
    avatar_url      TEXT,
    is_active       BOOLEAN     NOT NULL DEFAULT true,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE  kg_users IS 'KG user records — maps Render auth IDs to local UUIDs';
COMMENT ON COLUMN kg_users.render_user_id IS 'External user ID from Render authentication';


-- ── Table: kg_nodes ─────────────────────────────────────────────────────────
-- Knowledge graph nodes. Composite PK (user_id, id) allows the same node
-- slug across different users.

CREATE TABLE IF NOT EXISTS kg_nodes (
    id              TEXT        NOT NULL,
    user_id         UUID        NOT NULL REFERENCES kg_users(id) ON DELETE CASCADE,
    name            TEXT        NOT NULL,
    source_type     TEXT        NOT NULL CHECK (source_type IN (
                        'youtube', 'reddit', 'github', 'substack', 'medium', 'web', 'generic'
                    )),
    summary         TEXT,
    tags            TEXT[]      NOT NULL DEFAULT '{}',
    url             TEXT        NOT NULL,
    node_date       DATE,
    metadata        JSONB       NOT NULL DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),

    PRIMARY KEY (user_id, id)
);

COMMENT ON TABLE  kg_nodes IS 'Knowledge graph nodes — one per captured URL per user';
COMMENT ON COLUMN kg_nodes.id IS 'Node slug, e.g. yt-attention, gh-transformers';
COMMENT ON COLUMN kg_nodes.source_type IS 'Content source: youtube, reddit, github, substack, medium, web (legacy: generic)';
COMMENT ON COLUMN kg_nodes.tags IS 'Normalized tags for linking and filtering';
COMMENT ON COLUMN kg_nodes.metadata IS 'Extensible JSON for source-specific extras';


-- ── Table: kg_links ─────────────────────────────────────────────────────────
-- Edges between nodes, scoped to a single user's graph.

CREATE TABLE IF NOT EXISTS kg_links (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID        NOT NULL REFERENCES kg_users(id) ON DELETE CASCADE,
    source_node_id  TEXT        NOT NULL,
    target_node_id  TEXT        NOT NULL,
    relation        TEXT        NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- Composite FKs ensure source/target belong to the same user
    FOREIGN KEY (user_id, source_node_id) REFERENCES kg_nodes(user_id, id) ON DELETE CASCADE,
    FOREIGN KEY (user_id, target_node_id) REFERENCES kg_nodes(user_id, id) ON DELETE CASCADE,

    -- Prevent duplicate edges
    UNIQUE (user_id, source_node_id, target_node_id, relation)
);

COMMENT ON TABLE  kg_links IS 'Knowledge graph edges — shared-tag relationships between nodes';
COMMENT ON COLUMN kg_links.relation IS 'The shared tag that forms this connection';


-- ── Indexes ─────────────────────────────────────────────────────────────────

-- Tag-based queries: "find nodes with tag X", "nodes matching any of [X, Y]"
CREATE INDEX IF NOT EXISTS idx_kg_nodes_tags
    ON kg_nodes USING GIN (tags);

-- Filter by source type per user
CREATE INDEX IF NOT EXISTS idx_kg_nodes_user_source
    ON kg_nodes (user_id, source_type);

-- Date-ordered listing per user
CREATE INDEX IF NOT EXISTS idx_kg_nodes_user_date
    ON kg_nodes (user_id, node_date DESC);

-- URL lookup for dedup checks
CREATE INDEX IF NOT EXISTS idx_kg_nodes_user_url
    ON kg_nodes (user_id, url);

-- Edge lookups by source and target
CREATE INDEX IF NOT EXISTS idx_kg_links_user_source
    ON kg_links (user_id, source_node_id);

CREATE INDEX IF NOT EXISTS idx_kg_links_user_target
    ON kg_links (user_id, target_node_id);


-- ── Updated-at trigger ──────────────────────────────────────────────────────
-- Automatically set updated_at on row modification.

CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_kg_users_updated_at
    BEFORE UPDATE ON kg_users
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER trg_kg_nodes_updated_at
    BEFORE UPDATE ON kg_nodes
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();


-- ── Row-Level Security (RLS) ────────────────────────────────────────────────
-- Users can only access their own KG data.
-- Service role key bypasses RLS for server-side admin operations.

ALTER TABLE kg_users ENABLE ROW LEVEL SECURITY;
ALTER TABLE kg_nodes ENABLE ROW LEVEL SECURITY;
ALTER TABLE kg_links ENABLE ROW LEVEL SECURITY;

-- kg_users: users can read/update their own record
CREATE POLICY kg_users_select ON kg_users
    FOR SELECT USING (id = auth.uid());

CREATE POLICY kg_users_update ON kg_users
    FOR UPDATE USING (id = auth.uid());

-- kg_nodes: full CRUD on own nodes
CREATE POLICY kg_nodes_select ON kg_nodes
    FOR SELECT USING (user_id = auth.uid());

CREATE POLICY kg_nodes_insert ON kg_nodes
    FOR INSERT WITH CHECK (user_id = auth.uid());

CREATE POLICY kg_nodes_update ON kg_nodes
    FOR UPDATE USING (user_id = auth.uid());

CREATE POLICY kg_nodes_delete ON kg_nodes
    FOR DELETE USING (user_id = auth.uid());

-- kg_links: full CRUD on own links
CREATE POLICY kg_links_select ON kg_links
    FOR SELECT USING (user_id = auth.uid());

CREATE POLICY kg_links_insert ON kg_links
    FOR INSERT WITH CHECK (user_id = auth.uid());

CREATE POLICY kg_links_update ON kg_links
    FOR UPDATE USING (user_id = auth.uid());

CREATE POLICY kg_links_delete ON kg_links
    FOR DELETE USING (user_id = auth.uid());


-- ── Service-role policies ───────────────────────────────────────────────────
-- The service role key (used by the Python backend) bypasses RLS by default.
-- These explicit policies allow the server to manage all data when using
-- the anon key with a custom JWT claim.

CREATE POLICY kg_users_service_all ON kg_users
    FOR ALL USING (
        current_setting('request.jwt.claims', true)::jsonb ->> 'role' = 'service_role'
    );

CREATE POLICY kg_nodes_service_all ON kg_nodes
    FOR ALL USING (
        current_setting('request.jwt.claims', true)::jsonb ->> 'role' = 'service_role'
    );

CREATE POLICY kg_links_service_all ON kg_links
    FOR ALL USING (
        current_setting('request.jwt.claims', true)::jsonb ->> 'role' = 'service_role'
    );


-- ── Views ───────────────────────────────────────────────────────────────────

-- Per-user graph stats (uses subqueries to avoid count-multiplication from JOINs)
CREATE OR REPLACE VIEW kg_user_stats AS
SELECT
    u.id                    AS user_id,
    u.render_user_id,
    u.display_name,
    (SELECT COUNT(*) FROM kg_nodes n WHERE n.user_id = u.id) AS node_count,
    (SELECT COUNT(*) FROM kg_links l WHERE l.user_id = u.id) AS link_count,
    COALESCE(
        (SELECT array_agg(DISTINCT unnested)
         FROM kg_nodes n2, unnest(n2.tags) AS unnested
         WHERE n2.user_id = u.id),
        '{}'
    )                       AS all_tags
FROM kg_users u;

COMMENT ON VIEW kg_user_stats IS 'Aggregated KG stats per user — node count, link count, all tags';


-- Per-user graph data in a frontend-compatible {nodes, links} format
CREATE OR REPLACE VIEW kg_graph_view AS
SELECT
    u.id AS user_id,
    jsonb_build_object(
        'nodes',
        COALESCE(
            (SELECT jsonb_agg(
                jsonb_build_object(
                    'id',      n.id,
                    'name',    n.name,
                    'group',   n.source_type,
                    'summary', n.summary,
                    'tags',    n.tags,
                    'url',     n.url,
                    'date',    COALESCE(n.node_date::text, '')
                )
            )
            FROM kg_nodes n
            WHERE n.user_id = u.id),
            '[]'::jsonb
        ),
        'links',
        COALESCE(
            (SELECT jsonb_agg(
                jsonb_build_object(
                    'source',   l.source_node_id,
                    'target',   l.target_node_id,
                    'relation', l.relation
                )
            )
            FROM kg_links l
            WHERE l.user_id = u.id),
            '[]'::jsonb
        )
    ) AS graph_data
FROM kg_users u;

COMMENT ON VIEW kg_graph_view IS 'Per-user graph data as JSONB {nodes, links} for frontend consumption';


-- ── Done ────────────────────────────────────────────────────────────────────
-- Run this SQL in the Supabase SQL Editor (Dashboard → SQL Editor → New query).
-- After running, verify tables exist in Table Editor.
