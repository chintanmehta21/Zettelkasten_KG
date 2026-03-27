"""Offline test suite for zettelkasten_bot.pipeline.orchestrator.process_url.

Covers:
  R016 — error visibility (no partial writes on failure)
  R020 — structured logging phase order (asserted via call ordering)
  R022 — raw-fallback content written to Obsidian with status/Raw tag
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

from zettelkasten_bot.models.capture import ExtractedContent, SourceType
from zettelkasten_bot.pipeline.orchestrator import process_url
from zettelkasten_bot.pipeline.summarizer import SummarizationResult


# ── Factory helpers ──────────────────────────────────────────────────────────


def make_settings(tmp_path: Path) -> MagicMock:
    """Return a MagicMock that looks like a Settings object."""
    s = MagicMock()
    s.gemini_api_key = "test-key"
    s.model_name = "gemini-2.5-flash"
    s.kg_directory = str(tmp_path / "kg")
    s.data_dir = str(tmp_path / "data")
    s.reddit_comment_depth = 10
    return s


def make_extracted(
    source_type: SourceType = SourceType.GENERIC,
    title: str = "Test Title",
) -> ExtractedContent:
    return ExtractedContent(
        url="https://example.com",
        source_type=source_type,
        title=title,
        body="Content body",
        metadata={},
    )


def make_result(is_raw_fallback: bool = False) -> SummarizationResult:
    return SummarizationResult(
        summary="Structured summary",
        tags={
            "domain": ["AI"],
            "type": ["Research"],
            "difficulty": ["Intermediate"],
            "keywords": ["test"],
        },
        one_line_summary="Key takeaway",
        tokens_used=500,
        latency_ms=300,
        is_raw_fallback=is_raw_fallback,
    )


# ── Fixture ──────────────────────────────────────────────────────────────────


@pytest.fixture()
def pipeline_mocks(tmp_path):
    """Patch all 7 orchestrator dependencies at their import sites.

    Yields a SimpleNamespace with attributes:
      settings, resolve_redirects, DuplicateStore, GeminiSummarizer,
      ObsidianWriter, get_extractor, detect_source_type,
      store_instance, summarizer_instance, writer_instance, extractor_instance
    """
    settings = make_settings(tmp_path)

    with (
        patch(
            "zettelkasten_bot.pipeline.orchestrator.get_settings",
            return_value=settings,
        ) as mock_get_settings,
        patch(
            "zettelkasten_bot.pipeline.orchestrator.resolve_redirects",
            new_callable=AsyncMock,
            side_effect=lambda url: url,
        ) as mock_resolve,
        patch(
            "zettelkasten_bot.pipeline.orchestrator.DuplicateStore",
        ) as mock_ds_cls,
        patch(
            "zettelkasten_bot.pipeline.orchestrator.GeminiSummarizer",
        ) as mock_gs_cls,
        patch(
            "zettelkasten_bot.pipeline.orchestrator.ObsidianWriter",
        ) as mock_ow_cls,
        patch(
            "zettelkasten_bot.pipeline.orchestrator.get_extractor",
        ) as mock_get_extractor,
        patch(
            "zettelkasten_bot.pipeline.orchestrator.detect_source_type",
            return_value=SourceType.GENERIC,
        ) as mock_detect,
    ):
        # Wire up instances returned by class constructors
        store_inst = mock_ds_cls.return_value
        store_inst.is_duplicate.return_value = False
        store_inst.mark_seen = MagicMock()

        summarizer_inst = mock_gs_cls.return_value
        summarizer_inst.summarize = AsyncMock(return_value=make_result())

        writer_inst = mock_ow_cls.return_value
        writer_inst.write_note = MagicMock(return_value=Path("kg/note.md"))

        extractor_inst = MagicMock()
        extractor_inst.extract = AsyncMock(return_value=make_extracted())
        mock_get_extractor.return_value = extractor_inst

        from types import SimpleNamespace

        yield SimpleNamespace(
            get_settings=mock_get_settings,
            settings=settings,
            resolve_redirects=mock_resolve,
            DuplicateStore=mock_ds_cls,
            GeminiSummarizer=mock_gs_cls,
            ObsidianWriter=mock_ow_cls,
            get_extractor=mock_get_extractor,
            detect_source_type=mock_detect,
            store=store_inst,
            summarizer=summarizer_inst,
            writer=writer_inst,
            extractor=extractor_inst,
        )


# ── Happy path tests ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_happy_path_generic_full_pipeline(pipeline_mocks):
    """All 11 phases run for a GENERIC URL in default (happy-path) mode."""
    bot = AsyncMock()
    await process_url(bot, chat_id=123, url="https://example.com", source_type=None)

    # Phase 1: resolve redirects
    pipeline_mocks.resolve_redirects.assert_awaited_once()

    # Phase 3: auto-detect (source_type=None)
    pipeline_mocks.detect_source_type.assert_called_once()

    # Phase 4: dedup check
    pipeline_mocks.store.is_duplicate.assert_called_once()

    # Phase 6: extract
    pipeline_mocks.extractor.extract.assert_awaited_once()

    # Phase 7: summarize
    pipeline_mocks.summarizer.summarize.assert_awaited_once()

    # Phase 9: write
    pipeline_mocks.writer.write_note.assert_called_once()

    # Phase 10: mark seen
    pipeline_mocks.store.mark_seen.assert_called_once()

    # Phase 11: done — ✅ in the final message
    messages = [c.args[1] for c in bot.send_message.call_args_list]
    assert any("✅" in m for m in messages), f"No ✅ in messages: {messages}"


@pytest.mark.asyncio
async def test_happy_path_reddit_with_explicit_source_type(pipeline_mocks):
    """When source_type is provided, detect_source_type is skipped."""
    pipeline_mocks.extractor.extract = AsyncMock(
        return_value=make_extracted(source_type=SourceType.REDDIT, title="Reddit Post")
    )
    bot = AsyncMock()
    await process_url(
        bot, chat_id=123, url="https://reddit.com/r/test/comments/abc/", source_type=SourceType.REDDIT
    )

    # detect_source_type must NOT have been called
    pipeline_mocks.detect_source_type.assert_not_called()

    # get_extractor called with REDDIT
    pipeline_mocks.get_extractor.assert_called_once_with(SourceType.REDDIT, pipeline_mocks.settings)


@pytest.mark.asyncio
async def test_happy_path_auto_detect_source_type(pipeline_mocks):
    """When source_type=None, detect_source_type IS called."""
    bot = AsyncMock()
    await process_url(bot, chat_id=123, url="https://example.com", source_type=None)

    pipeline_mocks.detect_source_type.assert_called_once()


# ── R016 error visibility tests ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_extraction_failure_sends_error_and_no_write(pipeline_mocks):
    """R016: extraction RuntimeError → send Telegram error, do NOT write note."""
    pipeline_mocks.extractor.extract.side_effect = RuntimeError("page blocked")
    bot = AsyncMock()

    await process_url(bot, chat_id=123, url="https://example.com", source_type=None)

    # Error message sent
    all_texts = " ".join(c.args[1] for c in bot.send_message.call_args_list)
    assert "❌ Failed to extract" in all_texts, f"Expected error in: {all_texts}"

    # Note must NOT be written
    pipeline_mocks.writer.write_note.assert_not_called()


@pytest.mark.asyncio
async def test_outer_exception_sends_error_message(pipeline_mocks):
    """R016: unhandled exception in resolve → sends '❌ Error processing URL'."""
    pipeline_mocks.resolve_redirects.side_effect = Exception("DNS failure")
    bot = AsyncMock()

    await process_url(bot, chat_id=123, url="https://example.com", source_type=None)

    all_texts = " ".join(c.args[1] for c in bot.send_message.call_args_list)
    assert "❌ Error processing URL" in all_texts, f"Expected outer error in: {all_texts}"

    # Writer must not be called
    pipeline_mocks.writer.write_note.assert_not_called()


@pytest.mark.asyncio
async def test_extraction_failure_does_not_mark_seen(pipeline_mocks):
    """R016: when extraction fails, the URL must NOT be marked as seen."""
    pipeline_mocks.extractor.extract.side_effect = RuntimeError("timeout")
    bot = AsyncMock()

    await process_url(bot, chat_id=123, url="https://example.com", source_type=None)

    pipeline_mocks.store.mark_seen.assert_not_called()


# ── R022 raw-fallback tests ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_raw_fallback_sends_warning_and_writes_note(pipeline_mocks):
    """R022: raw fallback → sends warning AND still writes the note."""
    pipeline_mocks.summarizer.summarize = AsyncMock(return_value=make_result(is_raw_fallback=True))
    bot = AsyncMock()

    await process_url(bot, chat_id=123, url="https://example.com", source_type=None)

    # Warning message sent
    all_texts = " ".join(c.args[1] for c in bot.send_message.call_args_list)
    assert "⚠️ AI summarization failed" in all_texts, f"Expected warning in: {all_texts}"

    # Note IS still written
    pipeline_mocks.writer.write_note.assert_called_once()

    # Tags: contains 'status/Raw', does NOT contain 'status/Processed'
    call_kwargs = pipeline_mocks.writer.write_note.call_args
    tags_passed = call_kwargs.args[2] if len(call_kwargs.args) > 2 else call_kwargs.kwargs.get("tags", [])
    assert "status/Raw" in tags_passed, f"status/Raw missing from tags: {tags_passed}"
    assert not any(t == "status/Processed" for t in tags_passed), \
        f"status/Processed should not appear in raw-fallback tags: {tags_passed}"


@pytest.mark.asyncio
async def test_raw_fallback_tag_override_replaces_status(pipeline_mocks):
    """R022: raw fallback replaces all status/* tags with exactly status/Raw."""
    pipeline_mocks.summarizer.summarize = AsyncMock(return_value=make_result(is_raw_fallback=True))
    bot = AsyncMock()

    await process_url(bot, chat_id=123, url="https://example.com", source_type=None)

    call_kwargs = pipeline_mocks.writer.write_note.call_args
    tags_passed = call_kwargs.args[2] if len(call_kwargs.args) > 2 else call_kwargs.kwargs.get("tags", [])

    status_tags = [t for t in tags_passed if t.startswith("status/")]
    assert status_tags == ["status/Raw"], \
        f"Expected exactly ['status/Raw'], got: {status_tags}"


# ── Duplicate-detection tests ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_duplicate_not_forced_sends_warning_and_returns(pipeline_mocks):
    """Duplicate URL (force=False) → warning sent, extractor and writer not called."""
    pipeline_mocks.store.is_duplicate.return_value = True
    bot = AsyncMock()

    await process_url(bot, chat_id=123, url="https://example.com", source_type=None)

    all_texts = " ".join(c.args[1] for c in bot.send_message.call_args_list)
    assert "⚠️ Already captured" in all_texts, f"Expected dup warning in: {all_texts}"

    pipeline_mocks.extractor.extract.assert_not_awaited()
    pipeline_mocks.writer.write_note.assert_not_called()


@pytest.mark.asyncio
async def test_duplicate_with_force_processes_normally(pipeline_mocks):
    """Duplicate URL with force=True → full pipeline runs anyway."""
    pipeline_mocks.store.is_duplicate.return_value = True
    bot = AsyncMock()

    await process_url(
        bot, chat_id=123, url="https://example.com", source_type=None, force=True
    )

    # Extractor AND writer should be called
    pipeline_mocks.extractor.extract.assert_awaited_once()
    pipeline_mocks.writer.write_note.assert_called_once()

    # Done message sent
    all_texts = " ".join(c.args[1] for c in bot.send_message.call_args_list)
    assert "✅" in all_texts or "📝" in all_texts, f"Expected done emoji in: {all_texts}"


# ── Done-message content tests ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_done_message_includes_title_and_tokens(pipeline_mocks):
    """Final done message must contain the note title and token count."""
    pipeline_mocks.extractor.extract = AsyncMock(
        return_value=make_extracted(title="My Unique Title")
    )
    pipeline_mocks.summarizer.summarize = AsyncMock(
        return_value=SummarizationResult(
            summary="Summary",
            tags={"domain": ["AI"], "type": ["Research"], "difficulty": ["Beginner"], "keywords": ["x"]},
            one_line_summary="Takeaway",
            tokens_used=1234,
            latency_ms=100,
            is_raw_fallback=False,
        )
    )
    bot = AsyncMock()

    await process_url(bot, chat_id=123, url="https://example.com", source_type=None)

    # Last send_message call is the done message
    last_msg = bot.send_message.call_args_list[-1].args[1]
    assert "My Unique Title" in last_msg, f"Title missing from done message: {last_msg}"
    assert "1234" in last_msg, f"Token count missing from done message: {last_msg}"


# ── URL normalization test ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_normalized_url_passed_to_extractor_and_dedup(pipeline_mocks):
    """Tracking params are stripped before dedup check and extractor call."""
    raw_url = "https://example.com/article?utm_source=newsletter&utm_campaign=spring"
    expected_normalized = "https://example.com/article"

    bot = AsyncMock()
    await process_url(bot, chat_id=123, url=raw_url, source_type=None)

    # resolve_redirects is called with raw URL
    pipeline_mocks.resolve_redirects.assert_awaited_once_with(raw_url)

    # dedup check uses normalized URL (without tracking params)
    dedup_url_arg = pipeline_mocks.store.is_duplicate.call_args.args[0]
    assert dedup_url_arg == expected_normalized, \
        f"Dedup called with un-normalized URL: {dedup_url_arg!r}"

    # extractor called with normalized URL
    extractor_url_arg = pipeline_mocks.extractor.extract.call_args.args[0]
    assert extractor_url_arg == expected_normalized, \
        f"Extractor called with un-normalized URL: {extractor_url_arg!r}"


# ── R020 phase-order logging test ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_phase_logging_order(pipeline_mocks, caplog):
    """R020: INFO log entries appear in the correct phase order."""
    import logging

    bot = AsyncMock()
    with caplog.at_level(logging.INFO, logger="pipeline.orchestrator"):
        await process_url(bot, chat_id=123, url="https://example.com", source_type=None)

    phase_messages = [r.message for r in caplog.records if "Phase" in r.message]

    # Verify at least the key phases are logged in order
    expected_phases = ["Phase resolve", "Phase normalize", "Phase dedup", "Phase ack",
                       "Phase extract", "Phase summarize", "Phase tag", "Phase write",
                       "Phase mark_seen", "Phase done"]

    found_indices = []
    for phase in expected_phases:
        for i, msg in enumerate(phase_messages):
            if phase in msg:
                found_indices.append(i)
                break

    assert found_indices == sorted(found_indices), \
        f"Phase logs out of order. Phases found at indices: {found_indices}\nMessages: {phase_messages}"
    assert len(found_indices) >= 8, \
        f"Expected at least 8 phase log entries, found {len(found_indices)}: {phase_messages}"
