# Phase C — Canonical `create_kasten` runner: Design (grounded)

## Grounded contracts (file:line verified 2026-05-18)

- `module_runners/` has only `summarization.py`. Conventions a sibling MUST follow: entitlement gate before work, module `asyncio.Semaphore(2)`, Pydantic `.model_dump(mode="json")` return, lazy heavy imports, `__main__` argparse CLI.
- Reusable per-link: `run_add_zettel_pipeline(*, url, client_action_id, persist, user, effective_user_id)` (`summarization.py:119`) → does summarize→persist→(fire-and-forget) Phase-B KG population automatically when the user sub resolves to a workspace (`persist.py:486-626`).
- Kasten create today: `POST /api/rag/sandboxes` → `create_sandbox` (`sandbox_routes.py:357`) → `RAGRepository.create_kasten` (`rag_repository.py:21`, bare `rag.kastens` INSERT, **no idempotency**; dup-name → 409 via DB UNIQUE). "sandbox" == "kasten".
- Add to Kasten: `RAGRepository.add_zettels_to_kasten(kasten_id, workspace_zettel_ids[])` → `rag.bulk_add_to_kasten` (`_v2/13:86`, `ON CONFLICT DO NOTHING`, join table `rag.kasten_zettels` keyed on `content.workspace_zettels.id`).
- Idempotency to mirror: `zettels_routes` key `(user, client_action_id)` + sha256(body) + 900s cache + `_IN_FLIGHT` shield + 202 polling via `ADD_ZETTEL_IN_MEMORY_ASYNC`.
- Naruto = `f2105544-b73d-4946-8329-096d82f070d3`; runner ingests as user via `user={"sub":uuid}` + `effective_user_id`.
- ⚠️ **Dedup caveat:** `AddZettelPipelineOutput.workspace_zettel_id` is the *canonical* id (not workspace_zettel) when a link dedups (`was_new=False`). Must re-resolve the real `workspace_zettel_id` (canonical+workspace lookup) before `bulk_add_to_kasten`.
- Visibility: `GET /api/rag/sandboxes`, `/members` (`rag.list_kasten_zettels`), `/api/graph?view=my` (cache invalidated post-add).

## Design

New `website/api/module_runners/create_kasten.py` — `run_create_kasten_pipeline(*, name, links, user, effective_user_id, client_action_id, description, icon, color, default_quality, persist=True)` → Pydantic `CreateKastenOutput{status, kasten, ingested[], failed[], operation_id}`. Mirrors `summarization.py` conventions; `__main__` CLI (used by Phase E for Naruto).

Flow: idempotency guard → create-or-get Kasten → per link `run_add_zettel_pipeline(persist=True)` (reuses summarize+persist+KG-pop) under `effective_user_id` → re-resolve workspace_zettel_id (incl. dedup caveat) → `add_zettels_to_kasten(kasten_id, wz_ids)` → invalidate graph cache → structured result with per-link success/fail.

Route consolidation: `POST /api/rag/sandboxes` (`create_sandbox`) becomes a thin caller of `run_create_kasten_pipeline` with `links=[]` (empty → create-only, backward compatible); request model gains optional `links: list[str] = []`.

Tests (mirror tests/integration/v2, `@pytest.mark.live` + unit-mocked): valid create+ingest; invalid (bad URL/empty name/oversize) clean reject; Supabase rows scoped to the caller (Naruto isolation, UUID-leak); summarization + post-transform + KG-pop fired per link; created Kasten + zettels visible via the read endpoints immediately; idempotent re-submit.

## Within-phase decisions (sign-off) — see chat
D1 route consolidation shape · D2 create_kasten idempotency / dup-name behaviour · D3 sync vs async link ingestion.
