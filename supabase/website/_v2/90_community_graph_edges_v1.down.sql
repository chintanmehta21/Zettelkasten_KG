-- Down for 90_community_graph_edges_v1.sql.
--
-- Dropping the edge RPC returns the community graph to its node-only Phase 1
-- state (the wrapper degrades to links=[] — see CommunityGraphRepository
-- .get_community_edges, which swallows a missing-function error). It does NOT
-- touch migration 88's node RPC, the community_reader role (87), or any data.

BEGIN;

DROP FUNCTION IF EXISTS content.community_graph_edges_v1(int, int, int, real, real);

COMMIT;

NOTIFY pgrst, 'reload schema';
