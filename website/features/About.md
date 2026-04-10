# Features

This folder contains all implemented and deployed features for the website.

Each subfolder is a self-contained feature module with its own static assets (HTML, CSS, JS) and content.

Some features are optional and only activate when related configuration is present (for example Supabase).

## user_auth

User authentication via Supabase Auth with Google OAuth. Provides login/logout UI,
JWT-based API protection, and per-user knowledge graph scoping.

Also exposes lightweight user profile APIs (for example `/api/me`) and supports a
user-selectable avatar when Supabase is configured.

## knowledge_graph

Interactive 3D knowledge graph visualizer using ForceGraph3D. Displays all captured
Zettels as nodes with tag-based connections, search/filter by source type, and a
detail panel. Supports multi-user graphs: global view (all users' Zettels combined)
and per-user "My Graph" filtering (toggle visible when logged in).

## kg_features

Intelligence layer for the knowledge graph, adding six capabilities without
external frameworks (zero LangChain, zero Neo4j):

- **M1 Entity Extraction**: Gemini-powered entity/relationship extraction with
  gleaning loops and embedding-based deduplication.
- **M2 Semantic Embeddings**: pgvector-backed 768-dim embeddings via
  `gemini-embedding-001` for similarity-based auto-linking.
- **M3 Graph Analytics**: NetworkX-computed PageRank, Louvain communities,
  betweenness/closeness centrality enriching the graph API response.
- **M4 NL Graph Query**: Natural-language-to-SQL engine with SELECT-only
  safety, guided retry, and user-scoped execution via Supabase RPC.
- **M5 Graph Traversal RPCs**: PostgreSQL recursive CTEs for k-hop neighbors,
  shortest path, top connected nodes, isolated nodes, and tag frequency.
- **M6 Hybrid Retrieval**: Three-stream Reciprocal Rank Fusion search combining
  semantic similarity, full-text search, and graph structure signals.

## api_key_switching

Gemini API key rotation and routing. Supports a multi-key pool (preferred) and
falls back to a single key for backward compatibility.

Key loading priority:
1. `api_env` file (one key per line) in `website/features/api_key_switching/api_env`,
   `<project_root>/api_env`, or `/etc/secrets/api_env`
2. `GEMINI_API_KEYS` environment variable (comma-separated)
3. `GEMINI_API_KEY` (legacy)

## user_home

Signed-in home page for authenticated users. Acts as the post-login starting
point and links into other user-scoped features (graph, zettels, providers).

## user_zettels

Per-user zettels view (when Supabase is configured). Intended for browsing,
filtering, and managing captured notes for the signed-in user.

## browser_cache

A tiny browser-side cache used by the public auth flow to keep redirects and UX
stable without persisting secrets. Stores only non-sensitive flags and paths.
