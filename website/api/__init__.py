"""``website.api`` — HTTP API surface for the Zettelkasten website.

Route modules:

* ``zettels_routes`` — ``POST /api/zettels/add`` + the unified async ops
  polling endpoint ``GET /api/operations/{id}`` and DELETE cancel.
* ``sandbox_routes`` — ``POST /api/rag/sandboxes`` + members + share, plus
  the kasten-scoped async ops polling endpoint.
* ``chat_routes`` — ``POST /api/rag/sessions/{id}/messages`` and ``POST
  /api/rag/adhoc`` (dispatched through ``module_runners.ask_kasten`` per
  the D2 strangler-fig).
* ``routes`` — ``GET /api/graph`` and other catch-all surface (delegates
  to ``module_runners.view_graph``).
* ``module_runners`` — importable runner facades shared by HTTP routes,
  CLI tools, and Phase-E batch scripts.

Shared infrastructure:

* ``_async_ops`` — generic accept / spawn / poll / cancel for any async
  POST family (D3 locked verdict).
* ``_problem`` — sole RFC 9457 problem+json builder.
* ``_concurrency`` — rerank-slot admission gates.

new_apis_1a cleanup (2026-05-23): the legacy ``/api/rag`` router that
previously lived in this file's body was removed — it was never mounted
into the FastAPI app (verified by agent-5 audit), duplicated the v1
sandbox-route classes, and had no external callers. The canonical
implementation is in ``sandbox_routes.py``.
"""
from __future__ import annotations
