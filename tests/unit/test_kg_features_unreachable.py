"""Phase 8.0 H7 - CI guard: kg_features import surface is locked down.

After the partial cleanup (analytics + embeddings KEPT; retrieval, nl_query,
entity_extractor DELETED), only a small known allow-list of importers may
exist in production paths. Any new import outside the allow-list fails this
test at PR time.

Rationale per Research Q (2024+):
- understandlegacycode.com 2024 - git history is the canonical archive
- LaunchDarkly 2024 - flag retirement is two-stage: remove references, archive flag
- ConfigCat 2024-01-30 - "delete the conditional logic from the codebase"
- Hyrum Wright SWE@Google ch.15 - localize migration expertise in deprecating team
"""
from __future__ import annotations

import subprocess
from pathlib import Path


# Allow-listed importers (verified pure-compute, no v1 DB coupling).
# Paths use forward slashes to match git grep output on every platform.
#
# Phase B (docs/research/phase_b_kg_quality_design.md, decision Q2): the
# KG-population hook is the FIRST and ONLY approved production importer of
# `scoring` (the D-KG-1 connection-strength scorer, wired AS-IS). It also
# imports `embeddings` + `pseudo_tags`. The hook lives at
# website/features/rag_pipeline/ingest/kg_population.py and is the sole
# prod consumer of scoring. `scoring`'s importer set is now asserted to be
# EXACTLY this allow-list by
# `test_kg_features_scoring_has_no_production_importer` — an UNEXPECTED
# importer still fails the guard.
ALLOWED = {
    "website/api/routes.py",        # analytics.compute_graph_metrics
    "website/core/persist.py",      # embeddings.generate_embedding
    # Phase B: D-KG-1 scorer + embeddings + pseudo_tags (population hook).
    "website/features/rag_pipeline/ingest/kg_population.py",
}

# Phase B: the EXACT set of prod modules allowed to import
# `kg_features.scoring`. Locked decision D-KG-1 + Phase B Q2: scoring was
# dormant; the population hook is the single sanctioned importer. Any other
# importer (or its removal) is a real architectural change and must update
# this set in the same PR.
SCORING_ALLOWED = {
    "website/features/rag_pipeline/ingest/kg_population.py",
}


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _git_grep_importers(pattern: str) -> set[str]:
    """File list matching *pattern* across the prod tree.

    Uses ``--untracked`` so a not-yet-committed importer (e.g. the Phase B
    population hook while this PR is in the working tree) is still caught —
    ``git grep`` without it only searches the index, which would let a new
    unauthorized importer pass CI until the commit. ``.gitignore`` is still
    respected so generated/venv files are excluded.
    """
    result = subprocess.run(
        [
            "git", "grep", "-l", "--untracked",
            pattern,
            "--",
            "website/api/", "website/features/", "website/experimental_features/", "website/core/",
            ":!website/features/kg_features/",
        ],
        cwd=str(_repo_root()),
        capture_output=True,
        text=True,
    )
    return {
        line.strip().replace("\\", "/")
        for line in result.stdout.splitlines()
        if line.strip()
    }


def test_kg_features_imports_only_from_allowlist():
    """Any production import of kg_features must be on the allow-list above."""
    matches = _git_grep_importers("from website.features.kg_features")
    unauthorized = matches - ALLOWED
    assert unauthorized == set(), (
        f"unauthorized kg_features importers: {unauthorized}. "
        f"Per Phase 8.0 H7, only {ALLOWED} may import kg_features (analytics/embeddings, "
        "pure-compute). If you need v1 retrieval/NL-query/entity-extraction, port to v2 "
        "in website/core/supabase_v2/repositories/ or website/features/rag_pipeline/."
    )


def test_kg_features_deleted_modules_are_gone():
    """The 3 retired modules must be physically absent."""
    deleted = ("retrieval.py", "nl_query.py", "entity_extractor.py")
    for fn in deleted:
        path = _repo_root() / "website" / "features" / "kg_features" / fn
        assert not path.exists(), (
            f"{fn} should have been hard-deleted in 8.0-H7; found at {path}"
        )


def test_kg_features_scoring_has_no_production_importer():
    """`scoring`'s prod importer set must be EXACTLY ``SCORING_ALLOWED``.

    Phase B (decision Q2) wired the D-KG-1 scorer into the KG-population
    hook — the single sanctioned importer. The guard stays meaningful: it
    no longer asserts "zero importers" but "exactly the approved set", so
    an UNEXPECTED new importer (or the hook silently dropping scoring)
    still fails. If a future change intentionally alters the set, update
    ``SCORING_ALLOWED`` in the SAME PR (do not just silence it).
    """
    importers = _git_grep_importers("kg_features.scoring")
    assert importers == SCORING_ALLOWED, (
        f"scoring.py prod importers {importers} != approved {SCORING_ALLOWED}. "
        "scoring is the D-KG-1 connection-strength scorer; Phase B wired it "
        "ONLY into the KG-population hook. A new importer is a real "
        "architectural change — add it to SCORING_ALLOWED (and ALLOWED) and "
        "update this test in the same PR."
    )


def test_kg_features_kept_modules_are_present():
    """analytics.py, embeddings.py and scoring.py must remain (pure-compute)."""
    kept = ("analytics.py", "embeddings.py", "scoring.py")
    for fn in kept:
        path = _repo_root() / "website" / "features" / "kg_features" / fn
        assert path.exists(), (
            f"{fn} must remain in kg_features (pure-compute; analytics/embeddings "
            f"allow-listed in 8.0-H7, scoring dormant per D-KG-1); missing at {path}"
        )
