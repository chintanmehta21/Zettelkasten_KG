"""WAVE-C kg_features gap-fill — embedding provenance (KF-EMB-A + KF-EMB-B).

Covers two gaps not handled by the 1c-A backend subagent:

* **KF-EMB-A** — every row landed in ``content.canonical_chunks`` MUST carry a
  non-null, non-empty ``embedding_model_version`` value. The column has a
  ``NOT NULL DEFAULT 'gemini-001-mrl-768'`` constraint at the schema level
  (``supabase/website/_v2/02_content_schema.sql``); these tests pin that the
  contract holds via both the explicit insert path the upsert pipeline uses
  *and* the implicit DEFAULT path.

* **KF-EMB-B** — ``find_similar_nodes`` calls the legacy ``match_kg_nodes``
  RPC. Per CLAUDE.md Phase 8 closeout (2026-05-11) the ``public.kg_*`` tables
  were dropped, but the RPC body still references ``public.kg_nodes``. The
  RPC also takes **no** ``model_version`` argument today, so cross-version
  cosine collisions are not filtered at the storage layer. These tests
  document the current behaviour as a *finding*:

    1. The RPC signature still accepts only
       ``(query_embedding, match_threshold, match_count, target_user_id)``.
    2. The RPC body references a dropped table — invoking it raises a
       PostgREST error rather than silently returning cross-version matches.
    3. ``find_similar_nodes`` swallows that error and returns ``[]`` — so the
       caller cannot accidentally mix model versions today, but only because
       the RPC is broken, not because of a positive filter.

  Marked ``xfail(strict=False)`` for the "RPC supports model_version filter"
  test so the suite stays green today but flips RED the moment the v2 RPC
  ships with a ``model_version`` parameter (the desired end state per the
  KF-EMB-B spec).

Both tests are ``@pytest.mark.live`` because they need real Postgres (halfvec
casts, RPC dispatch). Seeding pattern mirrors
``test_ingest_memory_e2e._seed_zettel``.
"""
from __future__ import annotations

import uuid

import asyncpg
import pytest

pytestmark = pytest.mark.live


# ── Helpers ──────────────────────────────────────────────────────────────


def _embedding_literal(seed: float = 0.0) -> str:
    """Deterministic 768-dim halfvec literal, matching ingest_memory_e2e."""
    base = 0.001 + seed
    vals = [round(base + i * 1e-5, 6) for i in range(768)]
    return "[" + ",".join(f"{v:.6f}" for v in vals) + "]"


async def _seed_canonical_zettel(
    pool: asyncpg.Pool,
) -> uuid.UUID:
    """Insert a bare ``canonical_zettel`` and return its id. Workspace-agnostic
    so the row stays compatible with both KF-EMB-A and KF-EMB-B fixtures.
    """
    cz_id = uuid.uuid4()
    chash = uuid.uuid4().bytes + uuid.uuid4().bytes
    norm_url = f"https://kf-emb.test/{uuid.uuid4().hex}"
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO content.canonical_zettels
                (id, normalized_url, content_hash, source_type, title,
                 body_md, publication_date)
            VALUES ($1, $2, $3, 'web', $4, $5, '2026-05-12'::date)
            """,
            cz_id, norm_url, chash, "kf-emb seed", "body",
        )
    return cz_id


async def _insert_chunk_with_version(
    pool: asyncpg.Pool,
    *,
    cz_id: uuid.UUID,
    chunk_idx: int,
    seed: float,
    embedding_model_version: str | None,
) -> uuid.UUID:
    """Insert one chunk; ``embedding_model_version=None`` exercises the
    schema DEFAULT path (column is NOT NULL DEFAULT 'gemini-001-mrl-768').
    """
    cc_id = uuid.uuid4()
    chash = uuid.uuid4().bytes + uuid.uuid4().bytes
    emb = _embedding_literal(seed)
    async with pool.acquire() as conn:
        if embedding_model_version is None:
            await conn.execute(
                f"""
                INSERT INTO content.canonical_chunks
                    (id, canonical_zettel_id, chunk_idx, content,
                     content_hash, chunk_type, embedding)
                VALUES ($1, $2, $3, $4, $5, 'atomic',
                        '{emb}'::halfvec(768))
                """,
                cc_id, cz_id, chunk_idx, f"body {chunk_idx}", chash,
            )
        else:
            await conn.execute(
                f"""
                INSERT INTO content.canonical_chunks
                    (id, canonical_zettel_id, chunk_idx, content,
                     content_hash, chunk_type, embedding,
                     embedding_model_version)
                VALUES ($1, $2, $3, $4, $5, 'atomic',
                        '{emb}'::halfvec(768), $6)
                """,
                cc_id, cz_id, chunk_idx, f"body {chunk_idx}", chash,
                embedding_model_version,
            )
    return cc_id


# ── KF-EMB-A: embedding provenance ──────────────────────────────────────


async def test_canonical_chunks_default_model_version_populated(
    asyncpg_pool: asyncpg.Pool,
) -> None:
    """KF-EMB-A: implicit-DEFAULT path. Inserting a chunk WITHOUT specifying
    ``embedding_model_version`` lands the schema default 'gemini-001-mrl-768'
    — the column is NOT NULL so an empty/null sentinel is impossible.
    """
    cz_id = await _seed_canonical_zettel(asyncpg_pool)
    try:
        cc_id = await _insert_chunk_with_version(
            asyncpg_pool,
            cz_id=cz_id,
            chunk_idx=0,
            seed=0.0,
            embedding_model_version=None,
        )

        async with asyncpg_pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT embedding_model_version "
                "FROM content.canonical_chunks WHERE id = $1",
                cc_id,
            )
        assert row is not None, "chunk did not land"
        assert row["embedding_model_version"] is not None
        assert row["embedding_model_version"].strip() != "", (
            "embedding_model_version must be non-empty"
        )
        # Pin the locked default so a future ALTER COLUMN DEFAULT change trips
        # this test (cross-tenant cosine safety relies on a single default).
        assert row["embedding_model_version"] == "gemini-001-mrl-768"
    finally:
        async with asyncpg_pool.acquire() as conn:
            await conn.execute(
                "DELETE FROM content.canonical_zettels WHERE id = $1", cz_id
            )


async def test_canonical_chunks_explicit_model_version_persisted(
    asyncpg_pool: asyncpg.Pool,
) -> None:
    """KF-EMB-A: explicit-stamp path mirrors the production upsert pipeline
    (``website.features.rag_pipeline.ingest.upsert._EMBED_MODEL_VERSION``)
    which passes the version explicitly into the insert.
    """
    cz_id = await _seed_canonical_zettel(asyncpg_pool)
    explicit_version = "gemini-001-mrl-768"
    try:
        cc_id = await _insert_chunk_with_version(
            asyncpg_pool,
            cz_id=cz_id,
            chunk_idx=0,
            seed=0.0,
            embedding_model_version=explicit_version,
        )
        async with asyncpg_pool.acquire() as conn:
            stored = await conn.fetchval(
                "SELECT embedding_model_version "
                "FROM content.canonical_chunks WHERE id = $1",
                cc_id,
            )
        assert stored == explicit_version
    finally:
        async with asyncpg_pool.acquire() as conn:
            await conn.execute(
                "DELETE FROM content.canonical_zettels WHERE id = $1", cz_id
            )


async def test_canonical_chunks_null_model_version_rejected(
    asyncpg_pool: asyncpg.Pool,
) -> None:
    """KF-EMB-A: explicit NULL must violate the NOT NULL constraint. Pins
    the schema invariant so a future migration cannot weaken the column to
    NULLABLE without tripping CI.
    """
    cz_id = await _seed_canonical_zettel(asyncpg_pool)
    cc_id = uuid.uuid4()
    chash = uuid.uuid4().bytes + uuid.uuid4().bytes
    emb = _embedding_literal(0.0)
    try:
        with pytest.raises(asyncpg.NotNullViolationError):
            async with asyncpg_pool.acquire() as conn:
                await conn.execute(
                    f"""
                    INSERT INTO content.canonical_chunks
                        (id, canonical_zettel_id, chunk_idx, content,
                         content_hash, chunk_type, embedding,
                         embedding_model_version)
                    VALUES ($1, $2, $3, $4, $5, 'atomic',
                            '{emb}'::halfvec(768), NULL)
                    """,
                    cc_id, cz_id, 0, "body", chash,
                )
    finally:
        async with asyncpg_pool.acquire() as conn:
            await conn.execute(
                "DELETE FROM content.canonical_zettels WHERE id = $1", cz_id
            )


async def test_canonical_chunks_unknown_model_version_rejected_by_fk(
    asyncpg_pool: asyncpg.Pool,
) -> None:
    """KF-EMB-A: ``embedding_model_version`` is a FK to
    ``content.embedding_model_versions``. Unknown versions must be rejected
    by the FK constraint — mismatched-version vectors are flagged
    not-comparable at write time, not at query time.
    """
    cz_id = await _seed_canonical_zettel(asyncpg_pool)
    try:
        with pytest.raises(asyncpg.ForeignKeyViolationError):
            await _insert_chunk_with_version(
                asyncpg_pool,
                cz_id=cz_id,
                chunk_idx=0,
                seed=0.0,
                embedding_model_version=f"unknown-model-{uuid.uuid4().hex[:8]}",
            )
    finally:
        async with asyncpg_pool.acquire() as conn:
            await conn.execute(
                "DELETE FROM content.canonical_zettels WHERE id = $1", cz_id
            )


# ── KF-EMB-B: model_version filtering on match_kg_nodes ──────────────────


async def test_match_kg_nodes_rpc_signature_lacks_model_version_filter(
    asyncpg_pool: asyncpg.Pool,
) -> None:
    """KF-EMB-B: documents current state — ``match_kg_nodes`` does NOT take a
    ``model_version`` parameter, so it cannot filter cross-version cosine
    collisions at the storage layer.

    Pinned via ``information_schema.parameters`` so the test flips RED the
    moment a v2 ``match_kg_nodes`` ships with a ``p_model_version`` argument
    (the desired end state per the WAVE-C plan).
    """
    async with asyncpg_pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT parameter_name, data_type
              FROM information_schema.parameters
             WHERE specific_schema = 'public'
               AND specific_name LIKE 'match_kg_nodes%'
             ORDER BY ordinal_position
            """
        )
    param_names = [r["parameter_name"] for r in rows]
    # Current state: 4 params, none of them model_version-related.
    # When the new RPC ships, one of these will be 'p_model_version' or
    # 'model_version' — flip this test to assert it's present at that point.
    assert "p_model_version" not in param_names, (
        f"v2 match_kg_nodes appears to ship model_version filtering; "
        f"update KF-EMB-B test to assert it filters cross-version vectors. "
        f"Current params: {param_names}"
    )
    assert "model_version" not in param_names, (
        f"v2 match_kg_nodes appears to ship model_version filtering; "
        f"update KF-EMB-B test to assert it filters cross-version vectors. "
        f"Current params: {param_names}"
    )


async def test_find_similar_nodes_swallows_legacy_rpc_failure(
    asyncpg_pool: asyncpg.Pool,
    mint_user,
) -> None:
    """KF-EMB-B: ``find_similar_nodes`` wraps the (legacy) RPC call in a
    try/except and returns ``[]`` on failure. After Phase 8 closeout the
    underlying ``public.kg_nodes`` table is dropped, so the RPC raises a
    PostgREST error which the helper must absorb — guaranteeing the helper
    never silently returns cross-version cosine matches today.
    """
    from website.core.supabase_v2.client import get_v2_client
    from website.features.kg_features.embeddings import find_similar_nodes

    user = mint_user(workspace_count=1)
    client = get_v2_client()
    # 768-dim zero-ish vector (any well-formed payload triggers the RPC call).
    query_emb = [0.001 + i * 1e-5 for i in range(768)]

    result = find_similar_nodes(
        supabase_client=client,
        user_id=str(user.auth_user_id),
        embedding=query_emb,
        threshold=0.5,
        limit=10,
    )

    # Contract per embeddings.py: any failure → empty list, never raise.
    # This documents today's accidental-safety; flips when the v2 RPC lands.
    assert isinstance(result, list)
    assert result == [], (
        f"find_similar_nodes returned non-empty {result!r} — either the RPC "
        "was revived or the legacy table re-created. Update KF-EMB-B to "
        "assert the v2 RPC filters by embedding_model_version."
    )
