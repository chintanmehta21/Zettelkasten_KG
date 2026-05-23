"""B8: metadata fallback must return a list of canonical zettel ids per node."""
from unittest.mock import MagicMock
from uuid import UUID

from website.core.supabase_v2.repositories.kg_repository import KGRepository


def _build_fake_client(data):
    fake = MagicMock()
    chain = fake.schema.return_value.table.return_value.select.return_value.eq.return_value.in_
    chain.return_value.execute.return_value.data = data
    return fake


def test_list_node_canonical_zettel_metadata_returns_list_per_node():
    fake = _build_fake_client([
        {"id": 1, "metadata": {"canonical_zettel_id": "11111111-1111-1111-1111-111111111111"}},
        {"id": 2, "metadata": {"canonical_zettel_id": "22222222-2222-2222-2222-222222222222"}},
    ])
    repo = KGRepository(fake)
    out = repo.list_node_canonical_zettel_metadata(
        UUID("00000000-0000-0000-0000-000000000001"), [1, 2]
    )
    # B8: per-node value is a LIST of zettel ids, not a single str.
    assert out[1] == ["11111111-1111-1111-1111-111111111111"]
    assert out[2] == ["22222222-2222-2222-2222-222222222222"]


def test_metadata_fallback_handles_legacy_multi_zettel_lists():
    """Future-proofing: metadata may carry a list[str] of canonical ids."""
    fake = _build_fake_client([
        {"id": 7, "metadata": {"canonical_zettel_ids": ["a-z-z-z", "b-z-z-z"]}},
    ])
    repo = KGRepository(fake)
    out = repo.list_node_canonical_zettel_metadata(
        UUID("00000000-0000-0000-0000-000000000001"), [7]
    )
    assert out[7] == ["a-z-z-z", "b-z-z-z"]


def test_metadata_plural_and_singular_combined_dedup():
    """Plural + singular together: dedup, plural ids first."""
    fake = _build_fake_client([
        {
            "id": 3,
            "metadata": {
                "canonical_zettel_ids": ["a", "b"],
                "canonical_zettel_id": "a",  # duplicate of plural — dedup
            },
        },
    ])
    repo = KGRepository(fake)
    out = repo.list_node_canonical_zettel_metadata(
        UUID("00000000-0000-0000-0000-000000000001"), [3]
    )
    assert out[3] == ["a", "b"]


def test_empty_node_ids_returns_empty_dict():
    fake = MagicMock()
    repo = KGRepository(fake)
    assert repo.list_node_canonical_zettel_metadata(
        UUID("00000000-0000-0000-0000-000000000001"), []
    ) == {}
