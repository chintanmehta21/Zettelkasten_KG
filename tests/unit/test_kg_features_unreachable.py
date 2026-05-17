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
# `scoring` is deliberately NOT represented here: it is the D-KG-1
# connection-strength scorer, pure but with ZERO production importers as of
# the 2026-05-11 DB-v2 purge (only unit/drift-sentinel tests use it). It is
# retained dormant for the upcoming KG-quality rewire. Its
# zero-prod-importer status is asserted explicitly by
# `test_kg_features_scoring_has_no_production_importer` below, so a future
# accidental prod import of scoring is caught deliberately rather than by
# accident. When the rewire wires it in, add its importer here AND update
# that test in the same PR.
ALLOWED = {
    "website/api/routes.py",        # analytics.compute_graph_metrics
    "website/core/persist.py",      # embeddings.generate_embedding
}


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def test_kg_features_imports_only_from_allowlist():
    """Any production import of kg_features must be on the allow-list above."""
    result = subprocess.run(
        [
            "git", "grep", "-l",
            "from website.features.kg_features",
            "--",
            "website/api/", "website/features/", "website/experimental_features/", "website/core/",
            ":!website/features/kg_features/",
        ],
        cwd=str(_repo_root()),
        capture_output=True,
        text=True,
    )
    matches = {line.strip().replace("\\", "/") for line in result.stdout.splitlines() if line.strip()}
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
    """`scoring` is the dormant D-KG-1 scorer: zero production importers.

    Pure (no DB / network / global state), retained for the upcoming
    KG-quality rewire but deliberately NOT wired into any production path
    yet — hence deliberately absent from ALLOWED. If this fails, scoring
    grew a production importer: that is a real architectural change. Wire
    it into ALLOWED and update this test in the SAME PR (do not just
    silence it).
    """
    result = subprocess.run(
        [
            "git", "grep", "-l",
            "kg_features.scoring",
            "--",
            "website/api/", "website/features/", "website/experimental_features/", "website/core/",
            ":!website/features/kg_features/",
        ],
        cwd=str(_repo_root()),
        capture_output=True,
        text=True,
    )
    importers = {
        line.strip().replace("\\", "/")
        for line in result.stdout.splitlines()
        if line.strip()
    }
    assert importers == set(), (
        f"scoring.py grew unexpected production importer(s): {importers}. "
        "scoring is the dormant D-KG-1 connection-strength scorer with zero "
        "prod importers by design (locked decision D-KG-1). If the KG-quality "
        "rewire intentionally wired it in, add the importer to ALLOWED and "
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
