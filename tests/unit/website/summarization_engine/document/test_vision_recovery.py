import io, fitz, pytest
from PIL import Image
from website.api.module_runners import summarization as sm


def _image_only_pdf() -> bytes:
    doc = fitz.open()
    img = Image.new("RGB", (400, 250), (230, 230, 230))
    buf = io.BytesIO(); img.save(buf, format="PNG")
    p = doc.new_page(); p.insert_image(fitz.Rect(56, 56, 456, 306), stream=buf.getvalue())
    return doc.tobytes()


class _FakeResult:
    text = "Recovered transcript: this scanned PDF actually said this sentence clearly."


class _FakeClient:
    async def generate_multimodal(self, contents, **kw):
        return _FakeResult()


async def test_recovers_no_text_pdf_via_gemini():
    recovered = await sm._recover_document_text_via_vision(
        content=_image_only_pdf(), client=_FakeClient(), page_count=1,
    )
    assert "Recovered transcript" in recovered


async def test_recovery_refused_over_page_ceiling():
    with pytest.raises(Exception):
        await sm._recover_document_text_via_vision(
            content=b"%PDF", client=_FakeClient(), page_count=sm.MAX_VISION_RECOVERY_PAGES + 1,
        )
