from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
V2_DIR = ROOT / "supabase" / "website" / "_v2"


def _sql(name: str) -> str:
    return (V2_DIR / name).read_text(encoding="utf-8")


def test_all_v2_schema_files_exist_in_apply_order() -> None:
    # Exclude .down.sql rollback files — they're paired with their up migration
    # and never participate in the forward apply order. Convention adopted with
    # Migration 69 (Phase 2 KG render+correctness overhaul, 2026-05-23).
    names = [p.name for p in sorted(V2_DIR.glob("*.sql")) if not p.name.endswith(".down.sql")]
    assert names == [
        "00_extensions.sql",
        "01_core_schema.sql",
        "02_content_schema.sql",
        "03_kg_schema.sql",
        "04_rag_schema.sql",
        "05_pipelines_schema.sql",
        "06_billing_schema.sql",
        "07_partman_setup.sql",
        "08_rls_policies.sql",
        "09_seed_scorer_registry.sql",
        "10_hnsw_indexes.sql",
        "11_post_install.sql",
        "12_revert_unauthorized_pricing.sql",
        "13_v2_kasten_rpcs.sql",
        "15_drop_legacy_tables.sql",
        "16_nexus_tokens.sql",
        "19_enriched_search_rpc.sql",
        "20_hybrid_search_rpc.sql",
        "21_resolve_effective_nodes_rpc.sql",
        "22_kg_aliases_table.sql",
        "23_resolve_entity_anchors_rpc.sql",
        "24_entities_to_anchor_chunks_rpc.sql",
        "25_search_chunks_enriched_kasten.sql",
        "26_hybrid_search_chunks_kasten.sql",
        "27_drop_redundant_retrieval_idx.sql",
        "28_drop_legacy_rpcs.sql",
        "29_kasten_sharing_rls.sql",
        "30_billing_pricing_active_plan.sql",
        "31_drop_legacy_pricing.sql",
        "32_extraction_blocklist.sql",
        "34_retrieval_feedback_events.sql",
        "35_retrieval_signal_views.sql",
        "36_signal_views_pgcron.sql",
        "37_signal_cron_3hourly_and_monitors.sql",
        "38_extensible_attrs.sql",
        "41_migrate_39_to_repeatable.sql",
        "42_kg_connection_strength.sql",
        "43_port_match_kg_nodes.sql",
        "44_functional_gates.sql",
        "45_document_source_type.sql",
        # PR #23 KG-scoring migrations (already prod-applied under these
        # names; NOT renumbered per migration discipline). They are
        # independent of master's source_type/url_dedup migrations and sort
        # deterministically between them via the glob.
        "45_rag_subgraph_for_pagerank.sql",
        "46_kg_two_level_strength.sql",
        "46_url_dedup.sql",
        "47_migrate_17_to_repeatable.sql",
        "48_operations.sql",
        "49_operations_sweep.sql",
        "50_rls_partitions_and_migrations.sql",
        "51_operations_state_machine.sql",
        "52_default_privileges_hardening.sql",
        "53_set_search_path_v2_functions.sql",
        "54_revoke_legacy_public_secdef_grants.sql",
        "55_revoke_public_grant_on_secdef.sql",
        "56_drop_legacy_public_functions.sql",
        "57_stuck_running_reaper.sql",
        "58_revoke_legacy_secdef_idempotent.sql",
        "59_reaper_threshold_7m.sql",
        "60_zettel_enrichment_jobs.sql",
        "61_enrichment_jobs_reaper.sql",
        "62_enrich_claim_next_fix.sql",
        "63_grant_v2_tables_to_service_role.sql",
        "64_grant_all_v2_tables_to_service_role.sql",
        "65_reaper_threshold_10m.sql",
        "66_workspace_zettels_partial_indexes.sql",
        "67_canonical_shred_grace_30d.sql",
        "68_hybrid_search_chunks_workspace.sql",
        "69_kg_edges_updated_at.sql",
        "71_pipeline_runs_state_machine.sql",
        "72_workspace_zettels_derived_tags.sql",
        "73_normalize_user_tags.sql",
        "74_enrichment_jobs_canonical_fk_cascade.sql",
        "75_ops_finalize_extended_ttl.sql",
        "76_custom_access_token_hook.sql",
        "77_ensure_provisioned.sql",
    ]


def test_v2_schema_declares_expected_tables() -> None:
    # Includes 0*.sql (canonical 39 tables) plus 22_kg_aliases_table.sql
    # (kg.kg_node_aliases, Phase 1.D.4a) plus 34_retrieval_feedback_events.sql
    # (rag.retrieval_feedback_events, Phase 8.5.B-1).
    canonical_extras = {"22_kg_aliases_table.sql", "34_retrieval_feedback_events.sql"}
    combined = "\n".join(
        p.read_text(encoding="utf-8")
        for p in sorted(V2_DIR.glob("*.sql"))
        if p.name.startswith("0") or p.name in canonical_extras
    )
    tables = re.findall(r"CREATE TABLE IF NOT EXISTS ([a-z_]+\.[a-z_]+)", combined)
    assert len(set(tables)) == 41


def test_jwt_workspace_ids_uses_safe_jsonb_array_cast() -> None:
    sql = _sql("01_core_schema.sql")
    assert "jsonb_array_elements_text" in sql
    assert "::text::uuid[]" not in sql


def test_enrich_claim_next_has_variable_conflict_directive() -> None:
    """PR #40 hotfix lock: migration 62 must contain the
    ``#variable_conflict use_column`` plpgsql directive inside the
    ``core.enrich_claim_next`` body. Without it the bare ``attempts``
    reference in the UPDATE … SET clause becomes ambiguous between the
    OUT-table column and the table column, raising 42702 on every worker
    poll and freezing the lazy-enrichment queue. Pin the fix here so a
    future refactor can't silently remove the directive."""
    sql = _sql("62_enrich_claim_next_fix.sql")
    # Directive must be the first non-blank line inside the function body.
    assert "CREATE OR REPLACE FUNCTION core.enrich_claim_next()" in sql
    # The directive form is comment-like but is a real plpgsql parser hint;
    # placement must be inside the AS $$ ... $$ block, before DECLARE/BEGIN.
    assert "#variable_conflict use_column" in sql
    # And the buggy bare-column reference is still present (we only added
    # the directive; the SET clause's `attempts = attempts + 1` is now
    # unambiguous courtesy of the directive).
    assert "attempts   = attempts + 1" in sql


def test_hnsw_is_only_in_post_backfill_file() -> None:
    pre_backfill = "\n".join(
        p.read_text(encoding="utf-8")
        for p in sorted(V2_DIR.glob("0*.sql"))
        if p.name != "10_hnsw_indexes.sql"
    )
    assert "USING hnsw" not in pre_backfill
    assert "USING hnsw" in _sql("10_hnsw_indexes.sql")


def test_search_chunks_and_quota_are_typed_rpcs() -> None:
    content_sql = _sql("02_content_schema.sql")
    core_sql = _sql("01_core_schema.sql")
    kg_sql = _sql("03_kg_schema.sql")
    assert "CREATE OR REPLACE FUNCTION content.search_chunks" in content_sql
    assert "p_query_embedding halfvec(768)" in content_sql
    assert "CREATE OR REPLACE FUNCTION core.consume_quota" in core_sql
    assert "CREATE OR REPLACE FUNCTION core.is_service_role()" in core_sql
    assert "CREATE OR REPLACE FUNCTION core.jwt_has_workspace_role" in core_sql
    assert "core.is_service_role() OR p_workspace_id = ANY" in core_sql
    assert "core.is_service_role() OR p_workspace_id = ANY" in content_sql
    assert "core.is_service_role() OR p_workspace_id = ANY" in kg_sql
    assert "exec_sql_returning" not in core_sql


def test_search_chunks_excludes_null_embeddings() -> None:
    sql = _sql("02_content_schema.sql")
    assert "AND cc.embedding IS NOT NULL" in sql


def test_document_source_type_is_added_by_forward_migration() -> None:
    # 02_content_schema.sql is an already-applied (2026-05-09) versioned
    # migration; its body is immutable (schema-drift gate). 'document' is NOT
    # in the frozen base 02 CHECK — it is added by the forward migration
    # 45_document_source_type.sql, which is the authoritative effective CHECK
    # for the live DB and for fresh installs (it runs in apply order).
    assert "'document'" not in _sql("02_content_schema.sql")
    assert "'document'" in _sql("45_document_source_type.sql")


def test_document_source_type_migration_preserves_current_engine_sources() -> None:
    migration = _sql("45_document_source_type.sql")
    for source_type in [
        "youtube",
        "reddit",
        "github",
        "twitter",
        "substack",
        "newsletter",
        "medium",
        "hackernews",
        "linkedin",
        "arxiv",
        "podcast",
        "document",
        "web",
        "generic",
    ]:
        assert f"'{source_type}'" in migration


def test_citation_reaper_ignores_malformed_citation_ids() -> None:
    sql = _sql("02_content_schema.sql")
    assert "c ? 'canonical_chunk_id'" in sql
    assert "(c ->> 'canonical_chunk_id') ~*" in sql
    assert "(c ->> 'canonical_chunk_id')::uuid" in sql


def test_citation_reaper_skips_chat_message_citations() -> None:
    sql = _sql("02_content_schema.sql")
    assert "rag.chat_messages" in sql
    assert "canonical_chunk_id" in sql


def test_rls_keeps_canonical_chunks_service_role_only() -> None:
    sql = _sql("08_rls_policies.sql")
    assert "canonical_chunks_service_all" in sql
    assert "FOR SELECT TO authenticated" not in sql.split("canonical_chunks_service_all")[0]


def test_rls_uses_roles_for_workspace_writes() -> None:
    sql = _sql("08_rls_policies.sql")
    assert "core.jwt_has_workspace_role(workspace_id, ARRAY['owner', 'editor'])" in sql
    assert "core.jwt_has_workspace_role(workspace_id, ARRAY['owner'])" in sql
    assert "kasten_members_workspace_insert" in sql
    assert "chat_messages_workspace_insert" in sql


# Regression guard for the 2026-05-21 production incident where
# core.operations was created in migration 48 with RLS + service_role policy
# but no explicit table-level GRANT. operations_repo.get_operation() then
# failed 42501 "permission denied" on every PostgREST poll, hanging the Add
# Zettel UI for the full 300s poll budget.
#
# Strict contract (post-2026-05-21): every v2 table (in core, content, kg, rag,
# pipelines, billing) MUST have an explicit `GRANT ... TO service_role` per-
# table statement somewhere in _v2/*.sql. Schema-wide grants in 08_rls_policies
# and ALTER DEFAULT PRIVILEGES in 52_default_privileges_hardening are
# defense-in-depth backstops, NOT the contract — a Supabase platform update
# or a stray schema-wide REVOKE can silently shadow them, so per-table grants
# are the only mechanism we trust.
def _live_v2_tables_from_migrations() -> list[tuple[str, str]]:
    """Return [(source_file, qualified_name)] for every v2 CREATE TABLE that
    has NOT been dropped by a later migration."""
    table_re = re.compile(
        r"CREATE\s+TABLE(?:\s+IF\s+NOT\s+EXISTS)?\s+([a-z_]+\.[a-z_]+)",
        re.IGNORECASE,
    )
    drop_re = re.compile(
        r"DROP\s+TABLE(?:\s+IF\s+EXISTS)?\s+([a-z_]+\.[a-z_]+)",
        re.IGNORECASE,
    )
    v2_schemas = {"core", "content", "kg", "rag", "pipelines", "billing"}
    created: list[tuple[str, str]] = []
    dropped: set[str] = set()
    for p in sorted(V2_DIR.glob("*.sql")):
        text = p.read_text(encoding="utf-8")
        for m in table_re.finditer(text):
            q = m.group(1)
            if q.split(".", 1)[0] in v2_schemas:
                created.append((p.name, q))
        for m in drop_re.finditer(text):
            q = m.group(1)
            if q.split(".", 1)[0] in v2_schemas:
                dropped.add(q)
    return [(src, q) for src, q in created if q not in dropped]


def test_every_v2_table_has_explicit_service_role_grant() -> None:
    files = sorted(V2_DIR.glob("*.sql"))
    all_sql = "\n".join(p.read_text(encoding="utf-8") for p in files)

    live_tables = _live_v2_tables_from_migrations()
    assert live_tables, "no v2 CREATE TABLE statements parsed - regex broken?"

    missing: list[str] = []
    for source_file, qualified in live_tables:
        grant_pat = re.compile(
            r"GRANT\s+[A-Z, ]+\s+ON\s+(?:TABLE\s+)?"
            + re.escape(qualified)
            + r"\b[^;]*?\bservice_role\b",
            re.IGNORECASE | re.DOTALL,
        )
        if not grant_pat.search(all_sql):
            missing.append(f"{qualified} (from {source_file})")

    assert not missing, (
        "v2 tables without an explicit per-table GRANT to service_role "
        "anywhere in _v2/*.sql:\n  - "
        + "\n  - ".join(missing)
        + "\nEvery v2 table must have an explicit "
        "`GRANT ALL ON <table> TO service_role;` (or equivalent) per the "
        "post-2026-05-21 contract. Add it in the table's migration or in "
        "64_grant_all_v2_tables_to_service_role.sql. Schema-wide grants and "
        "ALTER DEFAULT PRIVILEGES are backstops, not the contract."
    )


def test_v2_grant_backfill_migration_covers_known_gap_tables() -> None:
    sql = _sql("63_grant_v2_tables_to_service_role.sql")
    for qualified in (
        "core.operations",
        "billing.pricing_usage_counters",
        "billing.pricing_action_ledger",
    ):
        pat = re.compile(
            r"GRANT\s+SELECT,\s*INSERT,\s*UPDATE,\s*DELETE\s+ON\s+"
            + re.escape(qualified)
            + r"\s+TO\s+service_role",
            re.IGNORECASE,
        )
        assert pat.search(sql), (
            f"63_grant_v2_tables_to_service_role.sql must include an explicit "
            f"GRANT SELECT, INSERT, UPDATE, DELETE ON {qualified} TO service_role."
        )
    # Self-verification block guards against silent grant failure.
    assert "has_table_privilege('service_role'" in sql


def test_v2_grant_all_tables_migration_has_self_verification() -> None:
    sql = _sql("64_grant_all_v2_tables_to_service_role.sql")
    # Must self-verify on apply: assert every v2 table has service_role SELECT.
    assert "has_table_privilege('service_role'" in sql
    # Must include the dynamic catch-all loop so any table created outside this
    # file (partman partitions, hand-DDL, missed entries) is still covered.
    assert "ALTER DEFAULT PRIVILEGES" in sql
    assert "FROM pg_tables" in sql
    # Must include the 6 v2 schemas in its scope.
    for schema in ("core", "content", "kg", "rag", "pipelines", "billing"):
        assert schema in sql, f"migration 64 must mention schema {schema}"
