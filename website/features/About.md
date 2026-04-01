# Features

This folder contains all implemented and deployed features for the website.

Each subfolder is a self-contained feature module with its own static assets (HTML, CSS, JS) and content.

## user_auth

User authentication via Supabase Auth with Google OAuth. Provides login/logout UI,
JWT-based API protection, and per-user knowledge graph scoping.

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
