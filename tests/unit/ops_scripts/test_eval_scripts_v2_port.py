"""DB-v2 purge guard for the rag_eval / corpus-drift / kg-recommendation scripts.

These six scripts used to import the retired ``website.core.supabase_kg``
module (dropped in the DB-v2 Phase 8.0.6 purge). The legacy slug-keyed
query branches that targeted now-dropped tables
(``public.kg_node_chunks/kg_nodes/kg_links/chunks``) were fully purged —
not retained behind PORT-BLOCKED comments or degraded stubs. This suite
asserts the purged contract:

1. Every module imports cleanly via importlib (no retired-supabase_kg
   ImportError).
2. None reference ``website.core.supabase_kg`` in source.
3. No ``PORT-BLOCKED`` / ``port_blocked`` remnant and no stale LEGACY
   header survives anywhere in the six files.
4. The data-access functions whose legacy table was dropped now expose a
   single honest seam: an empty-per-node best-effort return (where the
   original contract was best-effort/empty) or a ``NotImplementedError``
   (where the path genuinely needs a v2 rebuild).
5. Paths that already work without the dropped tables (offline
   ``_build_chunks_map``, ``--current-json`` ``detect_drift``) remain
   fully functional.

No live Supabase is required or constructed by any purged path.
"""

from __future__ import annotations

import asyncio
import importlib
import inspect
from pathlib import Path

import pytest

_MODULES = [
    "ops.scripts.score_rag_eval",
    "ops.scripts.rag_eval_loop",
    "ops.scripts.lib.rag_eval_kasten",
    "ops.scripts.apply_kg_recommendations",
    "ops.scripts.audit_gold_expectations",
    "ops.scripts.check_corpus_drift",
]

_SCRIPT_FILES = [
    "ops/scripts/score_rag_eval.py",
    "ops/scripts/rag_eval_loop.py",
    "ops/scripts/lib/rag_eval_kasten.py",
    "ops/scripts/apply_kg_recommendations.py",
    "ops/scripts/audit_gold_expectations.py",
    "ops/scripts/check_corpus_drift.py",
]

_REPO_ROOT = Path(__file__).resolve().parents[3]


@pytest.mark.parametrize("modname", _MODULES)
def test_module_imports_cleanly(modname):
    """importlib must load the module with no retired-supabase_kg ImportError."""
    mod = importlib.import_module(modname)
    assert mod is not None


@pytest.mark.parametrize("modname", _MODULES)
def test_no_legacy_supabase_kg_reference(modname):
    """Source must not reference the retired website.core.supabase_kg module."""
    mod = importlib.import_module(modname)
    src = Path(inspect.getfile(mod)).read_text(encoding="utf-8")
    assert "website.core.supabase_kg" not in src, (
        f"{modname} still references the retired supabase_kg module"
    )


@pytest.mark.parametrize("modname", _MODULES)
def test_no_stale_legacy_header(modname):
    """The 'LEGACY (broken after 2026-05-11)' header must be removed."""
    mod = importlib.import_module(modname)
    src = Path(inspect.getfile(mod)).read_text(encoding="utf-8")
    assert "LEGACY (broken after 2026-05-11)" not in src, (
        f"{modname} still carries the stale LEGACY header"
    )


@pytest.mark.parametrize("relpath", _SCRIPT_FILES)
def test_no_port_blocked_remnant(relpath):
    """The legacy slug-keyed branches were purged — no PORT-BLOCKED /
    port_blocked marker or commented-out legacy query body may survive."""
    src = (_REPO_ROOT / relpath).read_text(encoding="utf-8")
    lowered = src.lower()
    assert "port-blocked" not in lowered, f"{relpath} still has a PORT-BLOCKED marker"
    assert "port_blocked" not in lowered, f"{relpath} still has a port_blocked marker"


def test_score_rag_eval_fetch_purged_empty_contract():
    """score_rag_eval._fetch_chunks_for_nodes is purged to the honest
    empty-per-node best-effort contract (no v2 client constructed)."""
    sre = importlib.import_module("ops.scripts.score_rag_eval")
    out, embs = asyncio.run(
        sre._fetch_chunks_for_nodes(node_ids=["yt-some-slug"], user_id_hint=None)
    )
    assert out == {"yt-some-slug": []}
    assert embs == {}
    # Empty input still honored.
    out2, embs2 = asyncio.run(
        sre._fetch_chunks_for_nodes(node_ids=[], user_id_hint=None)
    )
    assert out2 == {}
    assert embs2 == {}


def test_audit_fetch_chunks_purged_returns_empty():
    """audit_gold_expectations._fetch_chunks_for_node is purged -> [] (the
    audit's no_chunks_found -> coverage_blind path stays intact)."""
    age = importlib.import_module("ops.scripts.audit_gold_expectations")
    res = asyncio.run(age._fetch_chunks_for_node("yt-some-slug", None))
    assert res == []


def test_check_corpus_drift_supabase_path_purged_raises():
    """_load_supabase_stats raises the honest NotImplementedError seam
    (legacy slug-keyed public.chunks path purged)."""
    ccd = importlib.import_module("ops.scripts.check_corpus_drift")
    with pytest.raises(NotImplementedError, match="rag_eval_v2"):
        ccd._load_supabase_stats()


def test_check_corpus_drift_json_path_still_works(tmp_path):
    """The --current-json detect_drift path is unaffected by the purge."""
    ccd = importlib.import_module("ops.scripts.check_corpus_drift")
    baseline = tmp_path / "b.json"
    baseline.write_text(
        '{"corpus_stats": {"chunk_count": 1000, "source_type_distribution": '
        '{"web": 1.0}, "embedding_centroid": [0,0,0,0,0,0,0,0]}, '
        '"drift_thresholds": {"chunk_count_pct_delta_max": 0.1, '
        '"source_type_proportion_pp_max": 0.05, "centroid_l2_max": 0.05}}',
        encoding="utf-8",
    )
    drifted, reasons = ccd.detect_drift(
        baseline_path=baseline,
        current_stats={
            "chunk_count": 1000,
            "source_type_distribution": {"web": 1.0},
            "embedding_centroid": [0, 0, 0, 0, 0, 0, 0, 0],
        },
    )
    assert drifted is False
    assert reasons == []


def test_apply_recommendations_purged_raises(tmp_path):
    """apply_recommendations is purged to a NotImplementedError seam — no
    fabricated cross-tenant kg_links/kg_nodes writes, no dead skip-loop."""
    akr = importlib.import_module("ops.scripts.apply_kg_recommendations")
    recs = tmp_path / "kg_recommendations.json"
    recs.write_text(
        '[{"type": "add_link", "status": "auto_apply", "payload": '
        '{"from_node": "a", "to_node": "b"}}]',
        encoding="utf-8",
    )
    with pytest.raises(NotImplementedError, match="rag_eval_v2"):
        asyncio.run(
            akr.apply_recommendations(
                recs_path=recs, user_id="u", supabase=None, dry_run=False
            )
        )


def test_rag_eval_kasten_ingest_purged_raises():
    """ingest_kasten raises the honest NotImplementedError seam under v2."""
    rek = importlib.import_module("ops.scripts.lib.rag_eval_kasten")
    with pytest.raises(NotImplementedError, match="rag_eval_v2"):
        asyncio.run(rek.ingest_kasten(zettels=[], user_id="u", runtime=None))


def test_rag_eval_kasten_build_kasten_purged_raises():
    """build_kasten delegates to the purged loader and raises the seam."""
    rek = importlib.import_module("ops.scripts.lib.rag_eval_kasten")
    with pytest.raises(NotImplementedError, match="rag_eval_v2"):
        asyncio.run(
            rek.build_kasten(
                source="youtube",
                iter_num=1,
                user_id="u",
                seed_node_ids=[],
                supabase=None,
                chintan_path=Path("docs/research/Chintan_Testing.md"),
                output_dir=Path("."),
            )
        )


def test_rag_eval_loop_chunks_map_offline_path_unaffected():
    """The offline _build_chunks_map path still stubs by count — the only
    path the importable determinism gate exercises."""
    rel = importlib.import_module("ops.scripts.rag_eval_loop")
    report = {"per_zettel": [{"node_id": "n1", "ok": True, "chunk_count": 3}]}
    out = rel._build_chunks_map(report)
    assert out == {"n1": [{"text": ""}, {"text": ""}, {"text": ""}]}


def test_rag_eval_loop_chunks_map_user_scoped_path_purged_to_stub():
    """The legacy real-fetch branch was purged: a user_id-scoped call now
    returns the same count stubs (no slug-keyed query, no v2 client)."""
    rel = importlib.import_module("ops.scripts.rag_eval_loop")
    report = {"per_zettel": [{"node_id": "n1", "ok": True, "chunk_count": 2}]}
    out = rel._build_chunks_map(report, user_id="some-user")
    assert out == {"n1": [{"text": ""}, {"text": ""}]}
