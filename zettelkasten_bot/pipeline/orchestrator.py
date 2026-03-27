"""Pipeline orchestrator — sequences the full URL-capture flow.

Entry point: ``process_url``.  Each phase is logged at INFO level so the
bot's behaviour can be traced end-to-end via log inspection.

Phases:
  resolve → normalize → detect_source → dedup → ack → extract →
  summarize → tag → write → mark_seen → done
"""

from __future__ import annotations

import logging
import traceback

from zettelkasten_bot.config.settings import get_settings
from zettelkasten_bot.models.capture import ProcessedNote, SourceType
from zettelkasten_bot.pipeline.duplicate import DuplicateStore
from zettelkasten_bot.pipeline.summarizer import GeminiSummarizer, build_tag_list
from zettelkasten_bot.pipeline.writer import ObsidianWriter
from zettelkasten_bot.sources import get_extractor
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
    settings = get_settings()

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
        source_label = source_type.value.capitalize()
        await bot.send_message(chat_id, f"⚙️ Processing {source_label} link...")

        # ── Phase 6: extract ──────────────────────────────────────────────
        logger.info("Phase extract — using %s extractor", source_type.value)
        try:
            extractor = get_extractor(source_type, settings)
            extracted = await extractor.extract(normalized)
            logger.info("Extracted: '%s' (%d chars)", extracted.title, len(extracted.body))
        except Exception as exc:
            logger.error("Extraction failed for %s: %s", normalized, exc)
            await bot.send_message(
                chat_id,
                f"❌ Failed to extract content from {source_label} link: {exc}",
            )
            return

        # ── Phase 7: summarize via Gemini ─────────────────────────────────
        logger.info("Phase summarize — sending to Gemini")
        summarizer = GeminiSummarizer(
            api_key=settings.gemini_api_key,
            model_name=settings.model_name,
        )
        result = await summarizer.summarize(extracted)

        if result.is_raw_fallback:
            logger.warning(
                "Gemini failed — saving raw content (R022) for %s", normalized
            )
            await bot.send_message(
                chat_id,
                "⚠️ AI summarization failed — saving raw content for manual review.",
            )

        # ── Phase 8: build tags ───────────────────────────────────────────
        logger.info("Phase tag — building multi-dimensional tags")
        tags = build_tag_list(source_type, result.tags)
        if result.is_raw_fallback:
            # Override status tag for raw fallback
            tags = [t for t in tags if not t.startswith("status/")]
            tags.append("status/Raw")
        logger.info("Tags: %s", tags)

        # ── Phase 9: write Obsidian note ──────────────────────────────────
        logger.info("Phase write — writing note to KG directory")
        writer = ObsidianWriter(settings.kg_directory)
        note_path = writer.write_note(extracted, result, tags)
        logger.info("Note written to: %s", note_path)

        # ── Phase 10: mark seen ───────────────────────────────────────────
        logger.info("Phase mark_seen — recording: %s", normalized)
        store.mark_seen(normalized)

        # ── Phase 11: done ────────────────────────────────────────────────
        status_emoji = "✅" if not result.is_raw_fallback else "📝"
        token_info = ""
        if result.tokens_used:
            token_info = f" ({result.tokens_used} tokens, {result.latency_ms}ms)"

        logger.info("Phase done — URL captured successfully: %s", normalized)
        await bot.send_message(
            chat_id,
            f"{status_emoji} **{extracted.title}**\n"
            f"Note saved to KG{token_info}\n"
            f"Tags: {', '.join(t.split('/')[-1] for t in tags[:8])}",
            parse_mode="Markdown",
        )

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
