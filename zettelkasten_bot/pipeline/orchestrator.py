"""Pipeline orchestrator — sequences the full URL-capture flow.

Entry point: ``process_url``.  Each phase is logged at INFO level so the
bot's behaviour can be traced end-to-end via log inspection.

Phases (S01 stubs; real implementations arrive in S02-S04):
  resolve → normalize → detect_source → dedup → ack → extract →
  summarize → write → mark_seen → done
"""

from __future__ import annotations

import logging
import traceback

from zettelkasten_bot.models.capture import ProcessedNote, SourceType
from zettelkasten_bot.pipeline.duplicate import DuplicateStore
from zettelkasten_bot.sources.base import StubExtractor
from zettelkasten_bot.sources.registry import detect_source_type
from zettelkasten_bot.utils.url_utils import normalize_url, resolve_redirects

logger = logging.getLogger("pipeline.orchestrator")


async def process_url(
    bot,
    chat_id: int,
    url: str,
    source_type: SourceType | None,
    force: bool = False,
    *,
    data_dir: str = "./data",
) -> None:
    """Run the full capture pipeline for *url*.

    Args:
        bot: Telegram bot instance exposing ``send_message(chat_id, text)``.
        chat_id: Telegram chat to send progress/result messages to.
        url: Raw URL submitted by the user.
        source_type: Pre-detected source type, or ``None`` for auto-detect.
        force: When ``True``, reprocess even if the URL was already captured.
        data_dir: Directory used by :class:`DuplicateStore` for persistence.
    """
    try:
        # ── Phase 1: resolve redirects ────────────────────────────────────
        logger.info("Phase resolve — input URL: %s", url)
        resolved = await resolve_redirects(url)
        logger.debug("Resolved URL: %s", resolved)

        # ── Phase 2: normalize ────────────────────────────────────────────
        logger.info("Phase normalize — resolved: %s", resolved)
        normalized = normalize_url(resolved)
        logger.debug("Normalized URL: %s", normalized)

        # ── Phase 3: detect source type ───────────────────────────────────
        if source_type is None:
            logger.info("Phase detect_source — auto-detecting for: %s", normalized)
            source_type = detect_source_type(normalized)
        logger.info("Source type: %s", source_type)

        # ── Phase 4: duplicate check ──────────────────────────────────────
        logger.info("Phase dedup — checking: %s", normalized)
        store = DuplicateStore(data_dir)
        if store.is_duplicate(normalized) and not force:
            logger.info("Duplicate detected, skipping: %s", normalized)
            await bot.send_message(
                chat_id,
                "⚠️ Already captured. Use /force to reprocess.",
            )
            return

        # ── Phase 5: acknowledge ──────────────────────────────────────────
        logger.info("Phase ack — sending processing message")
        await bot.send_message(chat_id, f"⚙️ Processing {normalized}...")

        # ── Phase 6: extract (stub) ───────────────────────────────────────
        logger.info("Phase extract — using StubExtractor (placeholder for S02)")
        extractor = StubExtractor()
        extracted = await extractor.extract(normalized)
        logger.debug("Extracted title: %s", extracted.title)

        # ── Phase 7: summarize (stub) ─────────────────────────────────────
        logger.info("Phase summarize — stub (placeholder for S03)")
        note = ProcessedNote(
            title=extracted.title,
            summary="[Stub summary — S03 will implement real summarization]",
            tags=[],
            source_url=normalized,
            source_type=source_type,
            raw_content=extracted.body,
        )
        logger.debug("Stub note title: %s", note.title)

        # ── Phase 8: write (stub) ─────────────────────────────────────────
        logger.info("Phase write — stub (placeholder for S04): would write note '%s'", note.title)

        # ── Phase 9: mark seen ────────────────────────────────────────────
        logger.info("Phase mark_seen — recording: %s", normalized)
        store.mark_seen(normalized)

        # ── Phase 10: done ────────────────────────────────────────────────
        logger.info("Phase done — URL captured successfully: %s", normalized)
        await bot.send_message(chat_id, f"✅ Note captured: {extracted.title}")

    except Exception as exc:  # noqa: BLE001
        brief = str(exc) or type(exc).__name__
        logger.error(
            "Pipeline error for URL %s: %s\n%s",
            url,
            brief,
            traceback.format_exc(),
        )
        try:
            await bot.send_message(chat_id, f"❌ Error processing URL: {brief}")
        except Exception:  # noqa: BLE001
            logger.error("Failed to send error message to chat %d", chat_id)
