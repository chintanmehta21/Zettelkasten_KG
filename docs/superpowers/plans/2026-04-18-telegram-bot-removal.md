# Telegram Bot Removal Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove `telegram_bot` from the website production path by replacing every website dependency with lightweight website-native modules, switching runtime/deploy to a website-only entrypoint, and then deleting the `telegram_bot/` package.

**Architecture:** This is a staged migration, not a big-bang delete. First extract the small subset of reusable logic the website still needs into focused `website` modules, then cut over website imports, then switch the runtime and Docker entrypoint to the website, and only then delete `telegram_bot/` once verification gates are green. Keep the native replacements lightweight and avoid recreating the entire old package structure under `website`.

**Tech Stack:** Python 3.12, FastAPI, Pydantic Settings, httpx, pytest, GitHub Actions, Docker, DigitalOcean droplet blue/green deploy.

---

## File structure map

- Create: `website/core/settings.py`
- Create: `website/core/url_utils.py`
- Create: `website/features/source_registry/__init__.py`
- Create: `website/features/source_registry/base.py`
- Create: `website/features/source_registry/registry.py`
- Create: `website/features/source_registry/extractors/__init__.py`
- Create: `website/features/legacy_summary/__init__.py`
- Create: `website/features/legacy_summary/summarizer.py`
- Create: `website/main.py`
- Modify: `website/core/__init__.py`
- Modify: `website/core/pipeline.py`
- Modify: `website/features/summarization_engine/core/orchestrator.py`
- Modify: `website/features/api_key_switching/__init__.py`
- Modify: `website/experimental_features/nexus/service/bulk_import.py`
- Modify: `website/experimental_features/nexus/service/persist.py`
- Modify: `run.py`
- Modify: `ops/Dockerfile`
- Modify: `.github/workflows/deploy-droplet.yml` only if the new website entrypoint requires workflow-level changes
- Modify: `ops/deploy/*.sh` only if runtime boot assumptions still reference `telegram_bot`
- Delete: `telegram_bot/` at the final task only
- Test: `tests/unit/website/test_settings.py`
- Test: `tests/unit/website/test_url_utils.py`
- Test: `tests/unit/website/test_source_registry.py`
- Test: `tests/unit/website/test_legacy_summary.py`
- Test: existing website and nexus tests that exercise migrated seams

### Task 1: Website-native settings and URL utilities

**Files:**
- Create: `website/core/settings.py`
- Create: `website/core/url_utils.py`
- Modify: `website/core/__init__.py`
- Modify: `website/core/pipeline.py`
- Modify: `website/features/summarization_engine/core/orchestrator.py`
- Modify: `website/features/api_key_switching/__init__.py`
- Modify: `website/experimental_features/nexus/service/persist.py`
- Test: `tests/unit/website/test_settings.py`
- Test: `tests/unit/website/test_url_utils.py`

- [ ] **Step 1: Write the failing tests for website-native settings**

Create `tests/unit/website/test_settings.py` with coverage for:
- `get_settings()` returning a cached singleton
- `newsletter_domains` and `rag_chunks_enabled` being available from the website module
- `github_enabled` property still behaving the same as before

Use a minimal pattern like:

```python
from website.core.settings import Settings


def test_github_enabled_requires_token_and_repo():
    settings = Settings(github_token="t", github_repo="owner/repo")
    assert settings.github_enabled is True
```

- [ ] **Step 2: Run the settings tests to verify they fail**

Run: `pytest tests/unit/website/test_settings.py -v`
Expected: FAIL with import errors because `website.core.settings` does not exist yet.

- [ ] **Step 3: Implement lightweight website-native settings**

Create `website/core/settings.py` by moving only the settings behavior the website still uses from `telegram_bot.config.settings`. Do not import from `telegram_bot`. Keep:
- the `Settings` model
- YAML + env + dotenv source behavior
- `github_enabled`
- `get_settings()`

Do not add Telegram runtime helpers or PTB-specific code.

- [ ] **Step 4: Write the failing tests for website-native URL utilities**

Create `tests/unit/website/test_url_utils.py` with coverage for:
- `validate_url` accepting normal https URLs and rejecting private-IP targets
- `normalize_url` stripping tracking params deterministically
- `resolve_redirects` returning the original URL on timeout/error

- [ ] **Step 5: Run the URL utility tests to verify they fail**

Run: `pytest tests/unit/website/test_url_utils.py -v`
Expected: FAIL with import errors because `website.core.url_utils` does not exist yet.

- [ ] **Step 6: Implement lightweight website-native URL utilities**

Create `website/core/url_utils.py` by moving the SSRF-safe URL helpers from `telegram_bot.utils.url_utils` into `website.core`, preserving behavior and signatures. Do not leave any website import path pointing back to `telegram_bot.utils.url_utils`.

- [ ] **Step 7: Cut over website callers to the native modules**

Update these imports:
- `website/core/pipeline.py`
- `website/features/summarization_engine/core/orchestrator.py`
- `website/features/api_key_switching/__init__.py`
- `website/experimental_features/nexus/service/persist.py`
- `website/core/__init__.py`

Replace `telegram_bot.config.settings` with `website.core.settings` and `telegram_bot.utils.url_utils` with `website.core.url_utils`.

- [ ] **Step 8: Run the focused test suite**

Run:

```bash
pytest tests/unit/website/test_settings.py tests/unit/website/test_url_utils.py -v
```

Expected: PASS.

- [ ] **Step 9: Run migration-relevant website tests**

Run:

```bash
pytest tests/unit/rag tests/unit/nexus tests/unit/website -q
```

Expected: PASS, or a smaller set of failures that point only to the next migration seam.

- [ ] **Step 10: Commit**

```bash
git add website/core/settings.py website/core/url_utils.py website/core/__init__.py website/core/pipeline.py website/features/summarization_engine/core/orchestrator.py website/features/api_key_switching/__init__.py website/experimental_features/nexus/service/persist.py tests/unit/website/test_settings.py tests/unit/website/test_url_utils.py
git commit -m "refactor: move website config and url utils local"
```

### Task 2: Website-native source registry and extractor loading

**Files:**
- Create: `website/features/source_registry/__init__.py`
- Create: `website/features/source_registry/base.py`
- Create: `website/features/source_registry/registry.py`
- Create: `website/features/source_registry/extractors/__init__.py`
- Create: website-native extractor modules for only the extractors the website currently uses
- Modify: `website/experimental_features/nexus/service/bulk_import.py`
- Test: `tests/unit/website/test_source_registry.py`

- [ ] **Step 1: Write failing tests for source detection and extractor lookup**

Cover:
- `detect_source_type(url)` returns the same source types the website currently relies on
- extractor discovery/loading works from the website-native package
- website import paths do not call `telegram_bot.sources`

- [ ] **Step 2: Run the source-registry tests to verify they fail**

Run: `pytest tests/unit/website/test_source_registry.py -v`
Expected: FAIL because the new source registry package does not exist yet.

- [ ] **Step 3: Implement the website-native source registry**

Move only the detection and extractor-loading logic the website actually uses into `website/features/source_registry/`.
Keep the package lightweight:
- do not move command handlers
- do not move Telegram-specific entry logic
- only move extractor base classes and concrete extractor modules required by website flows

- [ ] **Step 4: Cut over Nexus bulk import**

Update `website/experimental_features/nexus/service/bulk_import.py` to use the website-native source registry instead of `telegram_bot.sources` and `telegram_bot.sources.registry`.

- [ ] **Step 5: Run focused tests**

Run:

```bash
pytest tests/unit/website/test_source_registry.py tests/unit/nexus -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add website/features/source_registry website/experimental_features/nexus/service/bulk_import.py tests/unit/website/test_source_registry.py
git commit -m "refactor: move website source registry local"
```

### Task 3: Website-native legacy summary helpers

**Files:**
- Create: `website/features/legacy_summary/__init__.py`
- Create: `website/features/legacy_summary/summarizer.py`
- Modify: `website/experimental_features/nexus/service/bulk_import.py`
- Test: `tests/unit/website/test_legacy_summary.py`

- [ ] **Step 1: Write failing tests for the legacy summary helper**

Cover:
- `build_tag_list` still returns the expected merged tag list shape
- the legacy summarizer entrypoints used by Nexus still produce the same result contracts

- [ ] **Step 2: Run the legacy-summary tests to verify they fail**

Run: `pytest tests/unit/website/test_legacy_summary.py -v`
Expected: FAIL because the new package does not exist yet.

- [ ] **Step 3: Implement the website-native legacy summary module**

Move only the website-needed subset of `GeminiSummarizer` and `build_tag_list` into `website/features/legacy_summary/summarizer.py`.
Do not carry over Telegram-only orchestration.

- [ ] **Step 4: Cut over Nexus bulk import**

Replace imports from `telegram_bot.pipeline.summarizer` with `website.features.legacy_summary.summarizer`.

- [ ] **Step 5: Verify zero website imports from `telegram_bot`**

Run:

```bash
Get-ChildItem website -Recurse -Include *.py | Select-String -Pattern 'from telegram_bot|import telegram_bot'
```

Expected: no matches.

- [ ] **Step 6: Run focused tests**

Run:

```bash
pytest tests/unit/website/test_legacy_summary.py tests/unit/nexus -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add website/features/legacy_summary website/experimental_features/nexus/service/bulk_import.py tests/unit/website/test_legacy_summary.py
git commit -m "refactor: move website legacy summary local"
```

### Task 4: Website-only runtime entrypoint and Docker cutover

**Files:**
- Create: `website/main.py`
- Modify: `run.py`
- Modify: `ops/Dockerfile`
- Modify: runtime or deploy files only if they still point at `telegram_bot.main`
- Test: `tests/unit/website/test_runtime_entrypoint.py`

- [ ] **Step 1: Write the failing runtime-entrypoint tests**

Cover:
- `website.main` can create/run the website app without importing `telegram_bot.main`
- `run.py` delegates to the website-owned entrypoint

- [ ] **Step 2: Run the runtime tests to verify they fail**

Run: `pytest tests/unit/website/test_runtime_entrypoint.py -v`
Expected: FAIL because the website entrypoint does not exist yet.

- [ ] **Step 3: Implement `website/main.py`**

Create a website-owned runtime entrypoint that:
- loads website-native settings
- creates the FastAPI app
- starts uvicorn for the website

It must not initialize PTB, Telegram webhook routes, or bot command menus.

- [ ] **Step 4: Update `run.py`**

Make `run.py` call the website entrypoint so production startup no longer depends on `telegram_bot.main`.

- [ ] **Step 5: Update Docker entrypoint**

Modify `ops/Dockerfile` so the production image boots the website-only runtime path and is structured around the website entrypoint.

- [ ] **Step 6: Run focused tests**

Run:

```bash
pytest tests/unit/website/test_runtime_entrypoint.py -v
```

Expected: PASS.

- [ ] **Step 7: Build the image locally if Docker is available**

Run:

```bash
docker build -f ops/Dockerfile -t zettelkasten-website:runtime-cutover .
```

Expected: PASS. If Docker is unavailable on the workstation, record that explicitly and rely on CI for the first full image verification.

- [ ] **Step 8: Commit**

```bash
git add website/main.py run.py ops/Dockerfile tests/unit/website/test_runtime_entrypoint.py
git commit -m "refactor: boot production from website runtime"
```

### Task 5: Delete `telegram_bot` and prune obsolete dependencies

**Files:**
- Delete: `telegram_bot/`
- Modify: `ops/requirements.txt`
- Modify: any imports or tests still referencing `telegram_bot`
- Test: migration-focused website and nexus suites

- [ ] **Step 1: Verify the website import graph is clean before deletion**

Run:

```bash
Get-ChildItem website -Recurse -Include *.py | Select-String -Pattern 'from telegram_bot|import telegram_bot'
```

Expected: no matches.

- [ ] **Step 2: Delete `telegram_bot/`**

Remove the package only after Task 1 through Task 4 are green.

- [ ] **Step 3: Remove Telegram-only dependencies that are no longer required by the website runtime**

Update `ops/requirements.txt` conservatively:
- remove packages that were only required because of Telegram runtime ownership
- do not remove extractor/runtime dependencies still needed by website-native modules

- [ ] **Step 4: Run migration-focused tests**

Run:

```bash
pytest tests/unit/website tests/unit/nexus tests/unit/rag -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "refactor: remove telegram bot package"
```

### Task 6: Production verification and deploy target

**Files:**
- No required source-file additions unless fixes are needed from verification
- Save screenshots under: `ops/screenshots/`

- [ ] **Step 1: Push the branch and let GitHub Actions build/deploy**

Run:

```bash
git push origin codex/website-native-migration
```

Expected: branch pushed. If a PR workflow is required instead of direct deploy, use the repository’s normal deployment path.

- [ ] **Step 2: Verify GitHub Actions and droplet deploy timing**

Check the deploy workflow and confirm:
- image build succeeds
- SSH deploy succeeds
- total deploy time is under 2 minutes

- [ ] **Step 3: Verify the live website as Naruto**

Use Playwright CLI first. Capture screenshots into `ops/screenshots/`.

Minimum checks:
- home/login flow
- a website-native capture or summarize flow
- a RAG/user flow that exercises the migrated path

- [ ] **Step 4: Verify production Supabase artifacts**

Check the relevant production rows/artifacts for Naruto to confirm the website-native path still writes the expected data.

- [ ] **Step 5: Commit any verification-driven fixes**

```bash
git add -A
git commit -m "fix: stabilize website-native production cutover"
```

## Self-review

- Spec coverage: Task 1 covers settings and URL utilities, Task 2 covers source registry/extractors, Task 3 covers legacy summary helpers, Task 4 covers runtime cutover, Task 5 covers package deletion, and Task 6 covers deploy/live verification and the under-2-minute target.
- Placeholder scan: no TODO/TBD placeholders remain; each task has exact files, commands, and expected results.
- Type consistency: the plan keeps existing behavior/signatures for settings, URL helpers, source detection, extractor loading, and legacy summary helpers, minimizing breakage during cutover.
