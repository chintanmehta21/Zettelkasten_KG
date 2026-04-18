# Website-Native Migration & Lightweight Runtime Design

**Date:** 2026-04-18
**Owner:** Chintan
**Status:** Approved (awaiting implementation plan)
**Supersedes:** None

## Problem

The live product is the website at `https://zettelkasten.in`, but the running codebase and production container still treat `telegram_bot` as the root package for several critical paths:

1. The production runtime still starts through `telegram_bot.main` via `run.py`.
2. Website code still imports configuration, URL utilities, source detection, extractors, and legacy summarization helpers from `telegram_bot`.
3. The presence of two overlapping application surfaces creates architectural confusion and raises the risk of fixing the wrong path.
4. The production image still carries Telegram-oriented runtime structure even though website behavior is now the primary product requirement.
5. Deploy performance is fragile: the end goal is a droplet deploy that completes in under 2 minutes, which requires a lighter and more stable website-first runtime.

The desired end state is that the website becomes the single source of truth for ingestion, summarization, and RAG processing, with `telegram_bot/` removed entirely after the website path is fully self-sufficient.

## Non-Goals

- Preserving Telegram as a first-class runtime path.
- Building a second migration layer that keeps website and Telegram permanently in sync.
- Redesigning the RAG architecture itself.
- Changing user-facing website behavior unless required by the migration.
- Doing droplet cleanup before the website-native cutover is complete.

## Requirements

### Functional requirements

1. Website code must no longer import anything from `telegram_bot`.
2. Production runtime must boot through a website-owned entrypoint, not `telegram_bot.main`.
3. Website-native modules must provide all capabilities currently consumed from `telegram_bot`, including:
   - settings/config access
   - URL validation, normalization, redirect resolution, and shortener detection
   - source type detection and extractor loading
   - legacy summarization/tagging helpers still needed by website import flows
4. The website must remain the canonical path for ingestion, summarization, and RAG persistence.
5. After the cutover is verified, `telegram_bot/` must be deleted from the repo.

### Performance and packaging requirements

1. Native website modules must be as lightweight as possible:
   - only move code the website actually needs
   - avoid dragging Telegram-specific dependencies or abstractions into website-native modules
   - prefer small focused files over re-creating the old package wholesale
2. The production runtime image must be re-shaped around the website-only entrypoint.
3. The final droplet deploy target is:
   - successful website deploy under 2 minutes end to end
   - no SSH deploy timeout
   - stable enough that recent deploys do not oscillate between success and timeout

## Current dependency surface

As of this design, website imports from `telegram_bot` are concentrated in the following areas:

- `website/core/pipeline.py`
- `website/core/__init__.py`
- `website/features/summarization_engine/core/orchestrator.py`
- `website/features/api_key_switching/__init__.py`
- `website/experimental_features/nexus/service/bulk_import.py`
- `website/experimental_features/nexus/service/persist.py`

The imported Telegram-side capabilities fall into five buckets:

1. `telegram_bot.config.settings`
2. `telegram_bot.utils.url_utils`
3. `telegram_bot.sources.registry`
4. `telegram_bot.sources` extractor discovery/loading
5. `telegram_bot.pipeline.summarizer` legacy `GeminiSummarizer` and `build_tag_list`

This concentrated surface makes a staged migration feasible without a full-system rewrite.

## Design

### Phase A — Website-native foundations

Create website-owned equivalents for every Telegram-side capability the website still depends on.

Target structure:

```text
website/core/settings.py
website/core/url_utils.py
website/features/source_registry/
  __init__.py
  registry.py
  base.py
  <extractor modules actually needed by website>
website/features/legacy_summary/
  __init__.py
  summarizer.py
```

Design rules:

- Move only the minimal website-required logic.
- Do not carry over Telegram command handlers, webhook handlers, chat guards, PTB application code, or duplicate bot-only orchestration.
- If a module currently mixes website-usable logic with Telegram-specific behavior, split it and keep only the website-usable slice.
- Keep imports flowing inward toward `website`, never back out to `telegram_bot`.

### Phase B — Website import cutover

Replace every `website -> telegram_bot` import with `website -> website-native` imports.

Specific cutover categories:

1. Website pipeline and summarization engine move to website-native URL utilities.
2. Nexus bulk import moves to website-native settings, extractor registry, source detection, and legacy summarization helpers.
3. API-key switching moves to website-native settings access.
4. Persist paths stop referencing Telegram settings.

At the end of this phase, a repository-wide search must show zero `website` imports from `telegram_bot`.

### Phase C — Website-only runtime entrypoint

Production must stop starting through `run.py -> telegram_bot.main`.

Introduce a website-owned runtime entrypoint at:

```text
website/main.py
```

Responsibilities:

- load website-native settings
- create and run the FastAPI app
- own the production startup path for the live site

The new entrypoint must not initialize PTB, Telegram webhook handlers, or bot command registration.

### Phase D — Docker and deploy alignment

Once the website runtime is independent, re-align production packaging around that reality.

Required outcomes:

1. Docker entrypoint uses the website-owned runtime directly.
2. Image contents reflect only what the website runtime needs.
3. Layer invalidation is minimized so repeated deploys reuse more of the image.
4. Droplet deploy path remains blue/green but is tuned for the website-first runtime shape.

This phase is still migration work, not full droplet cleanup. The focus is on making the website container leaner and faster to deploy before removing extra files on the droplet.

### Phase E — Telegram package deletion

Delete `telegram_bot/` only after all of the following are true:

1. website import graph contains zero `telegram_bot` references
2. tests covering migrated website paths pass
3. production runtime uses website-owned entrypoint
4. production deploy succeeds on the website-only path
5. live website verification passes

Deletion includes:

- removing the package directory
- removing any code references, scripts, or entrypoints that assume it exists
- removing dependencies that were only needed because of Telegram runtime ownership

### Phase F — Droplet cleanup

Only after website-native migration is complete:

1. inspect droplet-side files, containers, volumes, and runtime assets
2. identify what is no longer needed for website execution
3. remove obsolete Telegram-era artifacts and extra runtime baggage
4. confirm the deployed site still boots and behaves correctly

This phase should be conservative: remove only items proven unnecessary for the current website version.

## Verification gates

### Gate 1 — Import independence

Pass criteria:

- repository search shows zero `website` imports from `telegram_bot`
- website tests referencing migrated seams pass

### Gate 2 — Runtime independence

Pass criteria:

- production startup path uses website-owned entrypoint
- no PTB or Telegram runtime initialization is required for website boot

### Gate 3 — Website behavior

Pass criteria:

- live website loads for an end user
- key website routes work
- Naruto-user production verification still succeeds for capture, summarization, and RAG paths

### Gate 4 — Packaging and deploy performance

Pass criteria:

- GitHub Actions build succeeds
- droplet SSH deploy succeeds without timeout
- total production deploy completes in under 2 minutes

### Gate 5 — Package deletion

Pass criteria:

- `telegram_bot/` removed from repo
- codebase remains green on migration-focused tests
- production website still runs correctly after deletion

## Risks and mitigations

### Risk: hidden Telegram dependencies outside the current import list

Mitigation:
- perform repository-wide searches before deletion
- cut over in phases instead of deleting first

### Risk: large copied modules recreate the old architecture under `website`

Mitigation:
- explicitly keep website-native modules lightweight
- extract only the logic the website actually consumes
- split mixed-responsibility code instead of copying it whole

### Risk: runtime/deploy changes succeed locally but not on the droplet

Mitigation:
- keep blue/green deploy path intact while changing only the runtime ownership
- verify with actual GitHub Actions and production health checks

### Risk: deleting `telegram_bot` too early breaks Nexus or summarization flows

Mitigation:
- treat deletion as the final phase, not the first
- require zero-import and production-verification gates before removal

## Success criteria

This migration is complete when all of the following are true:

1. The website owns ingestion, summarization, and RAG processing end to end.
2. No website code imports from `telegram_bot`.
3. Production boots from a website-native runtime entrypoint.
4. `telegram_bot/` has been deleted from the repository.
5. The final droplet deploy completes successfully in under 2 minutes.
