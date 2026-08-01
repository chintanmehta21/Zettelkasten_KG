"""Iter-03 §8: deploy.sh must fire one canonical RAG probe against the new
color, expect 200 + the expected primary citation, exit 89 on failure.

2026-08-01: the probe was retargeted after an outage. The original gold was
the zk-org/zk fixture in Kasten 227e0fb2, asserted by primary citation
node_id == "gh-zk-org-zk". Both halves had rotted:
  * the Kasten row was deleted (QA cleanup / 30-day canonical shred), so
    create_session hit a chat_sessions FK violation and the probe 500'd; and
  * v2 citations carry canonical_chunk_id UUIDs in node_id, so the v1-era
    node_id assert could never have matched again anyway.
The probe now targets a durable curated Kasten and asserts on the stable
citation TITLE via RAG_SMOKE_EXPECT_TITLE.
"""
from __future__ import annotations

from pathlib import Path

DEPLOY_SH = Path(__file__).resolve().parents[3] / "ops" / "deploy" / "deploy.sh"


def _smoke_block(text: str) -> str:
    start = text.index("[rag-smoke]")
    return text[start : text.index("Flipping Caddy upstream", start)]


def test_deploy_sh_has_rag_smoke_block():
    text = DEPLOY_SH.read_text(encoding="utf-8")
    assert "[rag-smoke]" in text
    assert "/api/rag/adhoc" in text
    assert "exit 89" in text


def test_deploy_sh_rag_smoke_is_contract_shaped():
    """2026-08-01: the gate asserts SHAPE, with identity only as an optional extra.

    Asserting "row X is the top citation" wired mutable business data into the
    deploy's availability path — deleting that row made the gate unpassable and
    aborted the cutover after the point of no return. Fowler's ContractTest:
    "the format of the data matters rather than the actual data".
    """
    block = _smoke_block(DEPLOY_SH.read_text(encoding="utf-8"))
    # Shape checks must exist...
    for marker in (
        "BAD_SHAPE:citations_not_a_list",
        "BAD_SHAPE:citation_missing_title",
        "BAD_SHAPE:empty_answer",
        "NO_CITATIONS",
    ):
        assert marker in block, f"missing shape assertion: {marker}"
    # ...and the pass condition must be the shape-OK sentinel, NOT a raw
    # equality against the expected title.
    assert '"$SMOKE_PRIMARY" == OK:*' in block
    assert '"$SMOKE_PRIMARY" != OK:*' in block
    assert '"$SMOKE_PRIMARY" == "$RAG_SMOKE_EXPECT_TITLE"' not in block, (
        "identity comparison must not gate the deploy directly"
    )


def test_deploy_sh_rag_smoke_identity_check_is_optional():
    """An empty RAG_SMOKE_EXPECT_TITLE must degrade to shape-only, not fail."""
    block = _smoke_block(DEPLOY_SH.read_text(encoding="utf-8"))
    assert "if expect and title != expect:" in block, (
        "the title assertion must be skipped when EXPECT is empty"
    )


def test_deploy_sh_rag_smoke_reads_title_not_node_id():
    """v2 node_ids are canonical_chunk_id UUIDs that change on every re-chunk.

    The original gate asserted ``citations[0].node_id == "gh-zk-org-zk"`` — a
    v1-era identifier that could never match again after the DB v2 migration,
    independently of whether the fixture data existed.
    """
    text = DEPLOY_SH.read_text(encoding="utf-8")
    block = _smoke_block(text)
    assert "RAG_SMOKE_EXPECT_TITLE" in text
    assert "get('title')" in block, "smoke must read the citation title"
    assert "node_id" not in block, (
        "the gate must not assert on node_id — it is a chunk UUID under v2"
    )
    assert "gh-zk-org-zk" not in text, (
        "the retired zk-org/zk v1 gold must not come back — its Kasten and "
        "canonical zettel no longer exist in the database."
    )


def test_deploy_sh_rag_smoke_fixture_ids_are_overridable():
    """Kasten id and expected title must be env-overridable so a future
    fixture rotation does not require editing the script on the droplet."""
    text = DEPLOY_SH.read_text(encoding="utf-8")
    assert 'RAG_SMOKE_KASTEN_ID="${RAG_SMOKE_KASTEN_ID:-' in text
    assert 'RAG_SMOKE_EXPECT_TITLE="${RAG_SMOKE_EXPECT_TITLE:-' in text


def test_deploy_sh_rag_smoke_restores_service_on_abort():
    """2026-08-01 outage guard (supersedes the old no-auto-rollback guard).

    The smoke gate runs AFTER the sequential cutover has already stopped and
    removed the previously-active color, so a bare `exit` left Caddy pointed
    at a dead upstream and the site served raw 502s until an operator
    intervened. Every abort path in the block must hand off to
    restore_previous_color first.

    This is NOT auto-rollback-on-success-masking: the deploy still exits
    non-zero and still logs FATAL, so the failure stays loud.
    """
    text = DEPLOY_SH.read_text(encoding="utf-8")
    block = _smoke_block(text)
    assert "restore_previous_color() {" in text
    assert "rollback.sh" in text[: text.index("[rag-smoke]")], (
        "restore_previous_color must delegate to rollback.sh"
    )
    for exit_code in ("exit 91", "exit 89"):
        assert exit_code in block
    # Every fatal exit inside the smoke block is immediately preceded by the
    # service restore — no abort path may leave the site dark. The helper takes
    # an optional gate-name label (added 2026-08-01 so the fail-safe log says
    # which gate tripped), so allow a quoted argument before the exit.
    for chunk in block.split("restore_previous_color")[1:]:
        rest = chunk.lstrip()
        if rest.startswith('"'):  # optional label argument
            rest = rest[rest.index('"', 1) + 1:].lstrip()
        assert rest.startswith("exit "), (
            "restore_previous_color must be followed directly by the fatal exit"
        )
    assert block.count("restore_previous_color") == block.count("exit 91") + block.count(
        "exit 89"
    ), "every fatal exit in the smoke block must restore the previous color first"


def test_deploy_sh_rag_smoke_never_exits_zero_on_failure():
    """The gate must never turn a failed probe into a successful deploy."""
    block = _smoke_block(DEPLOY_SH.read_text(encoding="utf-8"))
    assert "RAG_SMOKE_REQUIRED" in DEPLOY_SH.read_text(encoding="utf-8")
    assert "exit 0" not in block


def test_deploy_sh_rag_smoke_runs_after_stage2_before_flip():
    text = DEPLOY_SH.read_text(encoding="utf-8")
    stage2_idx = text.index("[stage2-assert] ${IDLE} stage2 session OK")
    smoke_idx = text.index("[rag-smoke]")
    flip_idx = text.index("Flipping Caddy upstream")
    assert stage2_idx < smoke_idx < flip_idx
