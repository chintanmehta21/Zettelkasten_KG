"""kg_features — partial cleanup landed 2026-05-11 (Phase 8.0 H7).

Active modules (kept; pure-compute, no DB):
- `analytics` - graph metrics (igraph); sole prod importer: `website/api/routes.py`
- `embeddings` - Gemini embedding helper; sole prod importer: `website/core/persist.py`
- `scoring`   - D-KG-1 multi-signal connection-strength scorer; pure, NO prod
  importer (only unit/drift-sentinel tests). Retained dormant for the
  upcoming KG-quality rewire — accidental prod import is a guarded failure
  (see tests/unit/test_kg_features_unreachable.py).

Retired modules (deleted; referenced dropped v1 tables / RPCs):
- `retrieval` - v1 hybrid_search + expand_subgraph against dropped kg_nodes/kg_links
- `nl_query` - v1 NL->SQL translator
- `entity_extractor` - v1 entity-canonicalization helper

Per understandlegacycode.com 2024 + LaunchDarkly 2024 + ConfigCat 2024-01-30 +
Hyrum Wright SWE@Google ch.15: hard-delete with git history as the archive.
Future v2 retrieval lives in `website/features/rag_pipeline/retrieval/`.
"""
