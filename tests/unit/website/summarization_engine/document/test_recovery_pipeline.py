"""Integration coverage for the no-text PDF vision-recovery WIRING in
``run_add_document_pipeline``.

This drives the *real* runner so the
``extract_document_upload -> NoTextLayerError -> reserve quota ->
_recover_document_text_via_vision -> re-enter extract as .txt -> summarizer``
chain executes end-to-end. Only the two Gemini-touching seams (the recovery
client and the summarizer) plus DTO construction are faked; the catch /
reserve-quota / .txt re-entry code under test runs for real.

Mock seams:
- ``website.features.summarization_engine.summarization.get_summarizer``
  (a *function-local* import in the runner — must be patched at its source
  module, NOT as ``sm.get_summarizer`` which does not exist) -> a fake
  summarizer that captures the IngestResult handed to ``.summarize``.
- ``sm.summary_dto`` / ``sm.quality_dto`` (module-level helpers) -> minimal
  real ``SummaryDTO`` / ``QualityDTO`` so ``AddZettelPipelineOutput`` validates.
- ``gemini_client_factory`` (parameter) -> ``_FakeClient`` whose
  ``generate_multimodal`` returns a >50-char transcript.

Anonymous user (``user=None``) makes ``require_entitlement`` a no-op, and
``persist=False`` skips the Supabase write — so no entitlement/persist mocking.
"""

import io
import uuid

import fitz
import pytest
from PIL import Image

from website.api.module_runners import summarization as sm

# A >50-char transcript so the recovery branch does not re-raise (the runner
# re-raises when len(recovered) < 50).
_TRANSCRIPT = (
    "Recovered transcript: this scanned PDF actually contained these words, "
    "transcribed verbatim by the vision recovery path for the test."
)


def _image_only_pdf(pages: int = 2) -> bytes:
    """An image-only PDF (visual content, zero text layer) — triggers
    NoTextLayerError in extract_document_upload, same recipe as
    test_no_text_layer.py."""
    doc = fitz.open()
    img = Image.new("RGB", (400, 250), (230, 230, 230))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    for _ in range(pages):
        p = doc.new_page(width=612, height=792)
        p.insert_image(fitz.Rect(56, 56, 456, 306), stream=buf.getvalue())
    return doc.tobytes()


class _FakeResult:
    text = _TRANSCRIPT


class _FakeClient:
    """Stands in for the tiered Gemini client. The factory is invoked twice in
    the recovery path (recovery call + summarizer construction); both must be
    tolerated. generate_multimodal feeds the vision recovery."""

    async def generate_multimodal(self, contents, **kw):
        return _FakeResult()


def _make_fake_summarizer(captured: dict):
    class _FakeSummarizer:
        def __init__(self, *args, **kwargs):  # ignore (client, source_config)
            pass

        async def summarize(self, ingest):
            captured["ingest"] = ingest
            return object()  # sentinel; summary_dto is patched, never inspects it

    return _FakeSummarizer


def _fake_summary_dto(bundle):
    # Smallest valid real SummaryDTO so AddZettelPipelineOutput validates.
    return sm.SummaryDTO(
        title="t",
        summary="s",
        brief_summary="b",
        detailed_summary="d",
        tags=[],
        source_type="document",
        source_url="file-upload://scan.txt",
        one_line_summary="o",
        tokens_used=0,
        latency_ms=0,
        metadata={},
    )


def _fake_quality_dto(bundle):
    return sm.QualityDTO(confidence="high")


async def test_no_text_pdf_recovery_wiring_feeds_transcript_to_summarizer(monkeypatch):
    captured: dict = {}

    # get_summarizer is imported function-locally inside run_add_document_pipeline
    # (`from website.features.summarization_engine.summarization import
    # get_summarizer`), so patch it at the source module — patching
    # sm.get_summarizer would have no effect.
    monkeypatch.setattr(
        "website.features.summarization_engine.summarization.get_summarizer",
        lambda source_type: _make_fake_summarizer(captured),
    )
    # summary_dto / quality_dto are module-level names resolved against the
    # runner's globals, so sm.<name> patching is the correct seam.
    monkeypatch.setattr(sm, "summary_dto", _fake_summary_dto)
    monkeypatch.setattr(sm, "quality_dto", _fake_quality_dto)

    result = await sm.run_add_document_pipeline(
        filename="scan.pdf",
        content=_image_only_pdf(),
        content_type="application/pdf",
        client_action_id="t-rec-1",
        persist=False,
        user=None,
        effective_user_id=uuid.uuid4(),
        gemini_client_factory=lambda: _FakeClient(),
    )

    # Load-bearing: the IngestResult handed to the summarizer must carry the
    # vision-recovered transcript. This proves catch -> recover -> .txt re-entry
    # produced the recovered content and threaded it into ingest.raw_text.
    assert "ingest" in captured, "summarizer.summarize was never reached"
    assert "transcribed verbatim by the vision recovery path" in captured["ingest"].raw_text

    # Proves specifically the .txt re-entry branch (recovered bytes were fed
    # back through extract_document_upload with a .txt filename), not the
    # original .pdf path.
    assert captured["ingest"].metadata.get("filename", "").endswith(".txt")

    # The full runner completed and produced its success envelope.
    assert result["status"] == "succeeded"


async def test_short_recovery_reraises_no_text_layer(monkeypatch):
    """Guard the < 50-char re-raise: a too-short vision transcript must NOT be
    silently re-entered; the original NoTextLayerError surfaces. Confirms the
    recovery wiring is gated, not unconditional."""
    from website.features.summarization_engine.source_ingest.document import (
        NoTextLayerError,
    )

    captured: dict = {}
    monkeypatch.setattr(
        "website.features.summarization_engine.summarization.get_summarizer",
        lambda source_type: _make_fake_summarizer(captured),
    )
    monkeypatch.setattr(sm, "summary_dto", _fake_summary_dto)
    monkeypatch.setattr(sm, "quality_dto", _fake_quality_dto)

    class _TinyResult:
        text = "too short"  # < 50 chars

    class _TinyClient:
        async def generate_multimodal(self, contents, **kw):
            return _TinyResult()

    with pytest.raises(NoTextLayerError):
        await sm.run_add_document_pipeline(
            filename="scan.pdf",
            content=_image_only_pdf(),
            content_type="application/pdf",
            client_action_id="t-rec-2",
            persist=False,
            user=None,
            effective_user_id=uuid.uuid4(),
            gemini_client_factory=lambda: _TinyClient(),
        )
    assert "ingest" not in captured, "summarizer must not run when recovery is too short"
