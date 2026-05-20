"""Lazy enrichment subsystem for the summarization engine (PR #39 Wave-3).

Moves the expensive, non-user-critical parts of Add Zettel persistence
(chunk segmentation + Gemini batch embedding) OFF the critical HTTP-200
path. The Add Zettel route returns succeeded as soon as the canonical
zettel + workspace zettel row are written; a durable Postgres-backed job
(``core.zettel_enrichment_jobs``) holds the pending enrichment work, and
an in-process async poller drains the queue via ``SELECT FOR UPDATE SKIP
LOCKED`` (Brandur Leach / pg-boss / River pattern).

Public surface:
    * ``repo.enqueue_chunk_embed(...)`` — schedule chunk+embed enrichment.
    * ``worker.run_forever()`` — background coroutine, one per gunicorn
      process; started from the FastAPI lifespan hook in ``website.app``.

The handler implementations live under ``handlers/`` and re-use the
existing ``website.core.persist.build_canonical_chunks`` + chunk-write
RPC so backfill semantics never diverge from the live path.
"""
from website.features.summarization_engine.lazy_enrichment import repo, worker

__all__ = ["repo", "worker"]
