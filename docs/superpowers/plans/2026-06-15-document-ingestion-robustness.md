# Document Ingestion Robustness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the document-upload path correctly classify, recover, or clearly explain every no-text / encrypted / garbage / corrupt PDF instead of bouncing them all as one generic "Invalid document upload".

**Architecture:** A richer **sync classifier** in `extract_document_upload` raises *specific* `DocumentUploadError` subclasses (Encrypted / NoTextLayer / GarbageText / Corrupt). The **async pipeline** (`run_add_document_pipeline`) catches the two *recoverable* ones (NoTextLayer, GarbageText) and transcribes the PDF with the **already-integrated Gemini multimodal** path (`TieredGeminiClient.generate_multimodal`), then continues the normal summarize/persist flow unchanged. Each subclass maps to a distinct RFC-9457 problem `type`, and the frontend surfaces the actionable `detail`. A POSIX-only `RLIMIT_AS` jail bounds the CPU-bound parse without touching the protected `GUNICORN_TIMEOUT`.

**Tech Stack:** Python 3.12, FastAPI, PyMuPDF (`fitz`), `google.genai` (Gemini), pytest (`asyncio_mode=auto`), vanilla JS frontend.

**Research basis:** `docs/claude_audits/no_text_pdf_recovery_research_2026-06-15.md` (Pass 1) and `docs/claude_audits/ingestion_robustness_research_2026-06-15.md` (Pass 2).

**Guardrails (CLAUDE.md):** Task 7 is infra-adjacent — it adds a per-parse cap and must **NEVER** lower/alter `GUNICORN_TIMEOUT` (180 s), `GUNICORN_WORKERS`, or `--preload`. No purple UI. Commits follow the repo's `feat:`/`fix:`/`test:` convention, 5–10 words, no author/tool names.

---

## File Structure

**Modified:**
- `website/features/summarization_engine/source_ingest/document/ingest.py` — new exception subclasses; classifier in `extract_document_upload`; U+FFFD helper; encrypted/corrupt detection in `_extract_pdf`; optional `RLIMIT` jail.
- `website/api/module_runners/summarization.py` — recovery branch in `run_add_document_pipeline`; Gemini transcription helper.
- `website/api/zettels_routes.py` — map new subclasses to distinct RFC-9457 `type_slug`s in `_problem_for_exception`.
- `website/static/js/add_zettel_api.js` — surface problem `detail` (not just `title`) for document failures.

**Created:**
- `website/features/summarization_engine/source_ingest/document/resource_guard.py` — POSIX `RLIMIT_AS` context manager (Task 7).
- Tests under `tests/unit/website/summarization_engine/document/` (see each task).

**Reference (do not modify):**
- `website/features/summarization_engine/core/gemini_client.py:99` — `generate_multimodal(contents, *, starting_model, label, role) -> GenerateResult` (`.text`).
- `website/features/api_key_switching/key_pool.py:747` — multimodal `gtypes.Content`/`gtypes.Part` precedent.

---

## Task 1: Error taxonomy — specific `DocumentUploadError` subclasses + RFC-9457 types

**Files:**
- Modify: `website/features/summarization_engine/source_ingest/document/ingest.py` (after the `DocumentUploadError` class, ~line 48)
- Modify: `website/api/zettels_routes.py` (`_problem_for_exception`, the `isinstance(exc, DocumentUploadError)` branch ~line 402)
- Test: `tests/unit/website/summarization_engine/document/test_error_taxonomy.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/website/summarization_engine/document/test_error_taxonomy.py
import pytest
from website.features.summarization_engine.source_ingest.document import ingest as doc_ingest
from website.features.summarization_engine.source_ingest.document import (
    DocumentUploadError,
)


def test_subclasses_exist_and_inherit():
    for name in (
        "EncryptedDocumentError",
        "CorruptDocumentError",
        "NoTextLayerError",
        "GarbageTextError",
    ):
        cls = getattr(doc_ingest, name)
        assert issubclass(cls, DocumentUploadError)


def test_recoverable_flag():
    # NoTextLayer / GarbageText are recoverable; Encrypted / Corrupt are not.
    assert doc_ingest.NoTextLayerError(page_count=3).recoverable is True
    assert doc_ingest.GarbageTextError().recoverable is True
    assert doc_ingest.EncryptedDocumentError().recoverable is False
    assert doc_ingest.CorruptDocumentError().recoverable is False


def test_no_text_layer_carries_page_count():
    err = doc_ingest.NoTextLayerError(page_count=11)
    assert err.page_count == 11
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/website/summarization_engine/document/test_error_taxonomy.py -v`
Expected: FAIL — `AttributeError: module ... has no attribute 'EncryptedDocumentError'`

- [ ] **Step 3: Add the subclasses** in `ingest.py` immediately after the existing `DocumentUploadError`:

```python
class DocumentUploadError(ValueError):
    """Raised when an uploaded document cannot be accepted or extracted."""

    # Recoverable means: the bytes are a valid document we simply could not
    # extract as text — a vision pass (OCR/LLM) may still read it. Terminal
    # subclasses (encrypted, corrupt) set this False so the async pipeline
    # does not waste a Gemini call on them.
    recoverable = False


class EncryptedDocumentError(DocumentUploadError):
    """PDF requires a password we don't have."""

    recoverable = False


class CorruptDocumentError(DocumentUploadError):
    """File is structurally broken beyond what the parser can repair."""

    recoverable = False


class NoTextLayerError(DocumentUploadError):
    """Valid document with no extractable text layer (scanned / outlined).

    Carries ``page_count`` so the async recovery layer can enforce a
    page ceiling before sending the file to Gemini vision.
    """

    recoverable = True

    def __init__(self, *args, page_count: int = 0):
        super().__init__(*args or ("This document has no selectable text.",))
        self.page_count = page_count


class GarbageTextError(DocumentUploadError):
    """Text extracted but is mostly replacement chars (CID font w/o ToUnicode)."""

    recoverable = True

    def __init__(self, *args, page_count: int = 0):
        super().__init__(
            *args or ("Extracted text was unreadable (no Unicode mapping).",)
        )
        self.page_count = page_count
```

- [ ] **Step 4: Export them** — extend `website/features/summarization_engine/source_ingest/document/__init__.py`:

```python
from .ingest import (
    DocumentIngestor,
    DocumentUploadError,
    EncryptedDocumentError,
    CorruptDocumentError,
    NoTextLayerError,
    GarbageTextError,
    extract_document_upload,
)

__all__ = [
    "DocumentIngestor",
    "DocumentUploadError",
    "EncryptedDocumentError",
    "CorruptDocumentError",
    "NoTextLayerError",
    "GarbageTextError",
    "extract_document_upload",
]
```

- [ ] **Step 5: Map subclasses to distinct RFC-9457 types** in `zettels_routes.py` `_problem_for_exception`. Add BEFORE the existing generic `isinstance(exc, DocumentUploadError)` branch (subclasses must be checked first):

```python
    from website.features.summarization_engine.source_ingest.document import (
        EncryptedDocumentError,
        CorruptDocumentError,
        NoTextLayerError,
        GarbageTextError,
    )
    if isinstance(exc, EncryptedDocumentError):
        return _problem_dict(
            status_code=422, title="Password-protected document",
            detail="This PDF is password-protected. Remove the password and re-upload.",
            type_slug="document-encrypted", operation_id=operation_id, url=url,
        )
    if isinstance(exc, NoTextLayerError):
        return _problem_dict(
            status_code=422, title="No selectable text",
            detail=("This PDF has no selectable text (it looks scanned or "
                    "printed-to-image). Try pasting the source URL instead."),
            type_slug="document-no-text-layer", operation_id=operation_id, url=url,
        )
    if isinstance(exc, GarbageTextError):
        return _problem_dict(
            status_code=422, title="Unreadable text",
            detail=("We couldn't read this document's text (its fonts have no "
                    "Unicode mapping). Try the source URL or a different export."),
            type_slug="document-garbage-text", operation_id=operation_id, url=url,
        )
    if isinstance(exc, CorruptDocumentError):
        return _problem_dict(
            status_code=422, title="Corrupt document",
            detail="This file appears damaged and could not be read.",
            type_slug="document-corrupt", operation_id=operation_id, url=url,
        )
    # existing generic DocumentUploadError branch stays below, unchanged.
```

- [ ] **Step 6: Run tests** — `pytest tests/unit/website/summarization_engine/document/test_error_taxonomy.py -v` → PASS. Also run existing doc tests: `pytest tests/unit -k document -q`.

- [ ] **Step 7: Commit**

```bash
git add website/features/summarization_engine/source_ingest/document/ingest.py \
        website/features/summarization_engine/source_ingest/document/__init__.py \
        website/api/zettels_routes.py \
        tests/unit/website/summarization_engine/document/test_error_taxonomy.py
git commit -m "feat: per-mode document error taxonomy"
```

---

## Task 2: Encrypted-PDF gate

**Files:**
- Modify: `ingest.py` `_extract_pdf` (~line 71-87)
- Test: `tests/unit/website/summarization_engine/document/test_encrypted_pdf.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/website/summarization_engine/document/test_encrypted_pdf.py
import fitz, pytest
from website.features.summarization_engine.source_ingest.document import (
    extract_document_upload, EncryptedDocumentError,
)


def _encrypted_pdf() -> bytes:
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Secret content that needs a password to read.")
    return doc.tobytes(encryption=fitz.PDF_ENCRYPT_AES_256,
                       owner_pw="owner", user_pw="userpw")


def test_encrypted_pdf_raises_encrypted_error():
    with pytest.raises(EncryptedDocumentError):
        extract_document_upload(filename="locked.pdf", content=_encrypted_pdf())
```

- [ ] **Step 2: Run** → `pytest tests/unit/website/summarization_engine/document/test_encrypted_pdf.py -v` → FAIL (raises generic "Could not extract enough text" instead).

- [ ] **Step 3: Add the gate** inside `_extract_pdf`, immediately after `fitz.open(...)` succeeds and before `page.get_text`:

```python
    try:
        with fitz.open(stream=data, filetype="pdf") as doc:
            if doc.needs_pass:
                # Owner-only-protected PDFs (restrictions but no read password)
                # open with an empty user password; authenticate returns truthy.
                if not doc.authenticate(""):
                    raise EncryptedDocumentError(
                        "PDF is password-protected; cannot read without the password."
                    )
            pages = [page.get_text("text") for page in doc]
            ...
    except EncryptedDocumentError:
        raise
    except Exception as exc:
        raise CorruptDocumentError("Could not extract text from this PDF.") from exc
```

(Note: the existing broad `except` is narrowed in Task 3/this step to raise `CorruptDocumentError` instead of the generic message; keep the `EncryptedDocumentError` re-raise above it.)

- [ ] **Step 4: Run** → PASS. Run `pytest tests/unit -k document -q` (no regressions).

- [ ] **Step 5: Commit**

```bash
git add website/features/summarization_engine/source_ingest/document/ingest.py \
        tests/unit/website/summarization_engine/document/test_encrypted_pdf.py
git commit -m "feat: detect password-protected PDFs"
```

---

## Task 3: No-text-layer structural classifier (replace the blunt `<50` gate)

**Files:**
- Modify: `ingest.py` `_extract_pdf` (return per-page structural stats) + `extract_document_upload` (~line 197-208)
- Test: `tests/unit/website/summarization_engine/document/test_no_text_layer.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/website/summarization_engine/document/test_no_text_layer.py
import io, fitz, pytest
from PIL import Image
from website.features.summarization_engine.source_ingest.document import (
    extract_document_upload, NoTextLayerError, DocumentUploadError,
)


def _image_only_pdf(pages=2) -> bytes:
    doc = fitz.open()
    img = Image.new("RGB", (400, 250), (230, 230, 230))
    buf = io.BytesIO(); img.save(buf, format="PNG")
    for _ in range(pages):
        p = doc.new_page(width=612, height=792)
        p.insert_image(fitz.Rect(56, 56, 456, 306), stream=buf.getvalue())
    return doc.tobytes()


def _text_pdf() -> bytes:
    doc = fitz.open(); p = doc.new_page()
    p.insert_text((72, 100), "Real selectable text well past fifty characters easily here.")
    return doc.tobytes()


def _blank_pdf() -> bytes:
    doc = fitz.open(); doc.new_page(); return doc.tobytes()


def test_image_only_pdf_is_recoverable_no_text_layer():
    with pytest.raises(NoTextLayerError):
        extract_document_upload(filename="scan.pdf", content=_image_only_pdf())


def test_real_text_pdf_accepted():
    res = extract_document_upload(filename="ok.pdf", content=_text_pdf())
    assert "selectable text" in res.raw_text


def test_truly_blank_pdf_is_terminal_not_recoverable():
    # Empty page, no images/vectors → genuinely nothing; NOT a recoverable scan.
    with pytest.raises(DocumentUploadError) as ei:
        extract_document_upload(filename="blank.pdf", content=_blank_pdf())
    assert not getattr(ei.value, "recoverable", False)
```

- [ ] **Step 2: Run** → FAIL (`_image_only_pdf` currently raises generic `DocumentUploadError`, not `NoTextLayerError`).

- [ ] **Step 3: Make `_extract_pdf` return structural stats.** Change its return to include a per-document `structure` dict:

```python
def _extract_pdf(data: bytes) -> tuple[str, dict[str, Any]]:
    try:
        import fitz
    except Exception as exc:
        raise DocumentUploadError("PDF extraction is unavailable in this environment.") from exc
    try:
        with fitz.open(stream=data, filetype="pdf") as doc:
            if doc.needs_pass and not doc.authenticate(""):
                raise EncryptedDocumentError(
                    "PDF is password-protected; cannot read without the password."
                )
            pages, vector_count, image_count = [], 0, 0
            for page in doc:
                pages.append(page.get_text("text"))
                # Character-sized vector drawings = "Text-Looking Vectors"
                # (print-to-PDF outlines). Cheap structural signal.
                vector_count += len(page.get_drawings())
                image_count += len(page.get_images())
            metadata = {
                "page_count": doc.page_count,
                "pdf_title": compact_text(str((doc.metadata or {}).get("title") or "")),
                "pdf_author": compact_text(str((doc.metadata or {}).get("author") or "")),
                "vector_count": vector_count,
                "image_count": image_count,
            }
    except (EncryptedDocumentError, CorruptDocumentError):
        raise
    except Exception as exc:
        raise CorruptDocumentError("Could not extract text from this PDF.") from exc
    return "\n\n".join(pages), {k: v for k, v in metadata.items() if v not in ("", None)}
```

- [ ] **Step 4: Replace the `<50` gate** in `extract_document_upload` (the block at ~line 206-208) so a no-text-but-visual PDF is *recoverable*, while a blank one stays terminal:

```python
    cleaned = compact_text(text, max_chars=MAX_EXTRACTED_CHARS)
    if len(cleaned) < 50:
        if extension == ".pdf":
            # Distinguish "scanned/outlined" (has visual content → recover via
            # vision) from "genuinely empty" (terminal). vector_count counts
            # character-sized outlines; image_count counts raster pages.
            has_visual = (
                metadata.get("vector_count", 0) >= 50
                or metadata.get("image_count", 0) >= 1
            )
            if has_visual:
                raise NoTextLayerError(
                    "This PDF has no selectable text.",
                    page_count=int(metadata.get("page_count", 0)),
                )
        raise DocumentUploadError("Could not extract enough text from this document.")
```

- [ ] **Step 5: Run** → all three tests PASS. Run `pytest tests/unit -k document -q`.

- [ ] **Step 6: Commit**

```bash
git add website/features/summarization_engine/source_ingest/document/ingest.py \
        tests/unit/website/summarization_engine/document/test_no_text_layer.py
git commit -m "feat: classify scanned vs empty PDFs"
```

---

## Task 4: Garbage-text (U+FFFD density) gate

**Files:**
- Modify: `ingest.py` (`_ufffd_density` helper + gate in `extract_document_upload` after `compact_text`)
- Test: `tests/unit/website/summarization_engine/document/test_garbage_text.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/website/summarization_engine/document/test_garbage_text.py
import pytest
from website.features.summarization_engine.source_ingest.document import ingest as di
from website.features.summarization_engine.source_ingest.document import GarbageTextError


def test_ufffd_density():
    assert di._ufffd_density("abc") == 0.0
    assert di._ufffd_density("���abcdefg") == pytest.approx(0.3, abs=0.01)
    assert di._ufffd_density("") == 0.0


def test_garbage_text_routed(monkeypatch):
    # Force _extract_pdf to return mostly-U+FFFD text with enough length.
    garbage = ("�" * 80) + ("x" * 20)
    monkeypatch.setattr(di, "_extract_pdf", lambda data: (garbage, {"page_count": 1, "image_count": 0, "vector_count": 0}))
    with pytest.raises(GarbageTextError):
        di.extract_document_upload(filename="cid.pdf", content=b"%PDF-1.7 fake")
```

(Note: the magic-bytes gate runs before `_extract_pdf`; `b"%PDF-1.7 fake"` passes `filetype.guess`. If it does not in CI, the test monkeypatches `filetype.guess` too — add `monkeypatch.setattr(di.filetype, "guess", lambda c: type("K", (), {"mime": "application/pdf"})())`.)

- [ ] **Step 2: Run** → FAIL (`_ufffd_density` undefined).

- [ ] **Step 3: Add the helper + gate.** Helper near the top of `ingest.py`:

```python
# CID/Identity-H fonts without a ToUnicode CMap extract as U+FFFD replacement
# chars (PyMuPDF Discussion #3801) — visually fine, semantically garbage. A
# density gate stops feeding Gemini confident-wrong text. 10% is a starting
# threshold; tune on real samples (see research open-question #1).
_UFFFD_DENSITY_THRESHOLD = 0.10


def _ufffd_density(text: str) -> float:
    if not text:
        return 0.0
    return text.count("�") / len(text)
```

Gate — in `extract_document_upload`, AFTER `cleaned = compact_text(...)` and AFTER the `<50` block, but BEFORE building sections:

```python
    if _ufffd_density(cleaned) > _UFFFD_DENSITY_THRESHOLD:
        raise GarbageTextError(
            "Extracted text was mostly unreadable.",
            page_count=int(metadata.get("page_count", 0)),
        )
```

- [ ] **Step 4: Run** → PASS. `pytest tests/unit -k document -q`.

- [ ] **Step 5: Commit**

```bash
git add website/features/summarization_engine/source_ingest/document/ingest.py \
        tests/unit/website/summarization_engine/document/test_garbage_text.py
git commit -m "feat: gate garbage CID-font text"
```

---

## Task 5: Gemini-vision recovery in the async pipeline

**Files:**
- Modify: `website/api/module_runners/summarization.py` (`run_add_document_pipeline`, ~line 248)
- Test: `tests/unit/website/summarization_engine/document/test_vision_recovery.py`

**Design:** `extract_document_upload` (sync) raises `NoTextLayerError`/`GarbageTextError`. The async pipeline catches them, and if `page_count <= MAX_VISION_RECOVERY_PAGES`, sends the **PDF bytes inline** to Gemini via the existing `TieredGeminiClient.generate_multimodal`, asking it to transcribe. The transcript becomes `ingest.raw_text` via a normal `extract_document_upload` re-entry on a synthetic text file, preserving all downstream contracts (summarizer, dedup hash, RAG). Over the ceiling or empty transcript → re-raise the original error (→ redirect UX).

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/website/summarization_engine/document/test_vision_recovery.py
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


@pytest.mark.asyncio
async def test_recovers_no_text_pdf_via_gemini(monkeypatch):
    recovered = await sm._recover_document_text_via_vision(
        content=_image_only_pdf(), client=_FakeClient(), page_count=1,
    )
    assert "Recovered transcript" in recovered


@pytest.mark.asyncio
async def test_recovery_refused_over_page_ceiling():
    with pytest.raises(Exception):
        await sm._recover_document_text_via_vision(
            content=b"%PDF", client=_FakeClient(),
            page_count=sm.MAX_VISION_RECOVERY_PAGES + 1,
        )
```

- [ ] **Step 2: Run** → FAIL (`_recover_document_text_via_vision` undefined).

- [ ] **Step 3: Add the recovery helper + ceiling** in `summarization.py`:

```python
# Bound per-document vision cost/latency: ~258 tokens/page (research Pass 1).
# 30 pages ≈ 7.7k vision tokens — safe for the latency budget and quota.
MAX_VISION_RECOVERY_PAGES = 30


async def _recover_document_text_via_vision(*, content, client, page_count):
    from website.features.summarization_engine.source_ingest.document import (
        NoTextLayerError,
    )
    if page_count > MAX_VISION_RECOVERY_PAGES:
        raise NoTextLayerError(
            f"Document has {page_count} pages; too many to read by vision.",
            page_count=page_count,
        )
    from google.genai import types as gtypes

    prompt = (
        "Transcribe ALL readable text from this document verbatim, preserving "
        "reading order and headings. Output only the transcript text — no "
        "commentary. If a page is blank, skip it."
    )
    contents = [
        gtypes.Content(
            role="user",
            parts=[
                gtypes.Part(inline_data=gtypes.Blob(mime_type="application/pdf", data=content)),
                gtypes.Part(text=prompt),
            ],
        )
    ]
    result = await client.generate_multimodal(contents, label="document_vision_recovery")
    return (getattr(result, "text", "") or "").strip()
```

- [ ] **Step 4: Wire it into `run_add_document_pipeline`.** Replace the bare `ingest = extract_document_upload(...)` (line ~248) with a recover-on-failure wrapper:

```python
    from website.features.summarization_engine.source_ingest.document import (
        extract_document_upload, NoTextLayerError, GarbageTextError,
    )
    try:
        ingest = extract_document_upload(
            filename=filename, content=content, content_type=content_type,
        )
    except (NoTextLayerError, GarbageTextError) as exc:
        client = gemini_client_factory()
        recovered = await _recover_document_text_via_vision(
            content=content, client=client, page_count=getattr(exc, "page_count", 0),
        )
        if len(recovered) < 50:
            raise  # vision produced nothing usable → terminal (redirect UX)
        # Re-enter the normal text path with the recovered transcript so dedup
        # hash, summarizer, and RAG chunking all behave identically.
        ingest = extract_document_upload(
            filename=filename, content=recovered.encode("utf-8"),
            content_type="text/plain",
        )
```

(Note: the recovered transcript is fed as a `.txt`-equivalent — but `filename` keeps the `.pdf` suffix, which would re-trigger PDF parsing. Pass a derived text filename: `filename=Path(filename).stem + ".txt"`. Import `Path` from `pathlib` at top if not present.)

- [ ] **Step 5: Run** → both tests PASS. Run `pytest tests/unit -k "document or summarization" -q`.

- [ ] **Step 6: Commit**

```bash
git add website/api/module_runners/summarization.py \
        tests/unit/website/summarization_engine/document/test_vision_recovery.py
git commit -m "feat: Gemini vision recovery for no-text PDFs"
```

---

## Task 6: Surface the problem `detail` in the frontend

**Files:**
- Modify: `website/static/js/add_zettel_api.js` (the failed-envelope normalizer, ~line 22-27)
- Test: `tests/unit/website/test_problem_detail_contract.py` (backend contract — the JS change is verified manually)

- [ ] **Step 1: Write the failing backend contract test** (guarantees the problem body the JS now reads actually carries `detail`):

```python
# tests/unit/website/test_problem_detail_contract.py
from website.api.zettels_routes import _problem_for_exception
from website.features.summarization_engine.source_ingest.document import (
    NoTextLayerError, EncryptedDocumentError,
)


def test_no_text_problem_has_actionable_detail():
    body = _problem_for_exception(NoTextLayerError(page_count=3), operation_id="op1")
    assert body["type"].endswith("document-no-text-layer")
    assert "scanned" in body["detail"].lower()


def test_encrypted_problem_has_actionable_detail():
    body = _problem_for_exception(EncryptedDocumentError(), operation_id="op2")
    assert "password" in body["detail"].lower()
```

(Verify `_problem_for_exception`'s real signature/return-key for the type URI; adjust `type`/`type_slug` key access to match `_problem_dict` output.)

- [ ] **Step 2: Run** → PASS already if Task 1 landed (this guards against regressions). If the key name differs, fix the assertion to match `_problem_dict`'s actual output keys.

- [ ] **Step 3: Update the JS normalizer** so the user sees `title` + the actionable `detail`. In `add_zettel_api.js`, change the message construction (~line 25) from title-only to title + detail:

```javascript
  function normalizeFailedEnvelope(next) {
    var problem = (next && typeof next.error === 'object' && next.error) ? next.error : next;
    var inner = (problem && typeof problem.detail === 'object' && problem.detail) ? problem.detail : null;
    var title = (problem && problem.title) || '';
    var detailStr = (problem && typeof problem.detail === 'string') ? problem.detail : '';
    // Show the actionable detail when present; fall back to title-only.
    var message = detailStr
      ? (title ? (title + ' — ' + detailStr) : detailStr)
      : (title || cleanProblemDetail(problem, 'Summary failed.'));
    return { message: message, detail: inner || problem || next, problem: problem };
  }
```

- [ ] **Step 4: Manual verification** (no JS test harness in repo). Run the app (`ENV=dev python run.py`), upload `docs`-side a no-text PDF via `/home`, confirm the inline error now reads "No selectable text — This PDF has no selectable text (it looks scanned…)". Record result in the PR description.

- [ ] **Step 5: Commit**

```bash
git add website/static/js/add_zettel_api.js tests/unit/website/test_problem_detail_contract.py
git commit -m "feat: surface actionable document error detail"
```

---

## Task 7: Per-parse resource jail (P3 — infra-adjacent, guardrail-bound)

> **GUARDRAIL:** This adds a *new* self-imposed cap on the sync PDF parse only. It MUST NOT read, lower, or alter `GUNICORN_TIMEOUT`, `GUNICORN_WORKERS`, or `--preload`. POSIX-only; a no-op on Windows/dev.

**Files:**
- Create: `website/features/summarization_engine/source_ingest/document/resource_guard.py`
- Modify: `ingest.py` `_extract_pdf` (wrap the `fitz.open(...)` parse)
- Test: `tests/unit/website/summarization_engine/document/test_resource_guard.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/website/summarization_engine/document/test_resource_guard.py
import sys, pytest
from website.features.summarization_engine.source_ingest.document import resource_guard as rg


def test_noop_on_non_posix(monkeypatch):
    monkeypatch.setattr(rg.os, "name", "nt")
    with rg.parse_resource_limit(max_bytes=1):  # must not raise on Windows
        pass


@pytest.mark.skipif(sys.platform.startswith("win"), reason="POSIX rlimits only")
def test_address_space_cap_is_set_and_restored():
    import resource
    soft0, hard0 = resource.getrlimit(resource.RLIMIT_AS)
    with rg.parse_resource_limit(max_bytes=512 * 1024 * 1024):
        soft, _ = resource.getrlimit(resource.RLIMIT_AS)
        assert soft <= 512 * 1024 * 1024
    assert resource.getrlimit(resource.RLIMIT_AS) == (soft0, hard0)
```

- [ ] **Step 2: Run** → FAIL (`resource_guard` missing).

- [ ] **Step 3: Implement the guard:**

```python
# website/features/summarization_engine/source_ingest/document/resource_guard.py
"""POSIX RLIMIT_AS jail for the CPU/RAM-bound sync PDF parse.

Bounds a single parse's address space so a malicious/pathological PDF self-OOMs
(raising MemoryError, caught by the caller) instead of OOM-killing the worker on
the 2 GB droplet. Independent of — and never touches — GUNICORN_TIMEOUT/workers.
No-op on non-POSIX so Windows dev + CI behave normally.
"""
from __future__ import annotations

import contextlib
import os

# 384 MB: comfortably above a legitimate 10 MB PDF's parse working set, well
# below the per-worker headroom that keeps 2 gunicorn workers alive on 2 GB.
_DEFAULT_MAX_BYTES = 384 * 1024 * 1024


@contextlib.contextmanager
def parse_resource_limit(*, max_bytes: int = _DEFAULT_MAX_BYTES):
    if os.name != "posix":
        yield
        return
    import resource

    soft, hard = resource.getrlimit(resource.RLIMIT_AS)
    new_hard = hard
    # Never raise the hard limit; clamp our soft cap under the existing hard.
    cap = max_bytes if hard in (resource.RLIM_INFINITY,) else min(max_bytes, hard)
    try:
        resource.setrlimit(resource.RLIMIT_AS, (cap, new_hard))
        yield
    finally:
        resource.setrlimit(resource.RLIMIT_AS, (soft, hard))
```

- [ ] **Step 4: Apply it** in `_extract_pdf` — wrap only the parse:

```python
    from website.features.summarization_engine.source_ingest.document.resource_guard import (
        parse_resource_limit,
    )
    try:
        with parse_resource_limit(), fitz.open(stream=data, filetype="pdf") as doc:
            ...
    except MemoryError as exc:
        raise CorruptDocumentError("Document is too complex to process safely.") from exc
```

- [ ] **Step 5: Run** → PASS on both platforms (`test_noop_on_non_posix` on Windows; the rlimit test skips on Windows, runs on Linux CI). `pytest tests/unit -k document -q`.

- [ ] **Step 6: Commit**

```bash
git add website/features/summarization_engine/source_ingest/document/resource_guard.py \
        website/features/summarization_engine/source_ingest/document/ingest.py \
        tests/unit/website/summarization_engine/document/test_resource_guard.py
git commit -m "feat: rlimit jail for PDF parse"
```

---

## Final verification (after all tasks)

- [ ] Run the full document suite: `pytest tests/unit -k "document or summarization or zettel" -q` → all PASS.
- [ ] Run ruff once at the end (per repo convention — batch lint): `ruff check website/features/summarization_engine/source_ingest/document website/api/module_runners/summarization.py`.
- [ ] Manually verify the real file: `extract_document_upload` on `C:\Users\LENOVO\Downloads\DC_PDF.pdf` now raises `NoTextLayerError` (recoverable), and a stubbed-client `run_add_document_pipeline` recovers it.
- [ ] PR description: summarize the 7 changes, link both research audits, and note Task 7 is the only infra-adjacent change (guardrail-respecting).

---

## Self-Review (run by the plan author)

**1. Spec coverage:** P1 detection (Task 3) ✓; P1 encrypted gate (Task 2) ✓; P1 taxonomy + UI detail (Tasks 1, 6) ✓; P2 Gemini recovery (Task 5) ✓; P2 garbage-text gate (Task 4) ✓; P3 RLIMIT jail (Task 7) ✓. All six approved items mapped.

**2. Placeholder scan:** No "TBD"/"handle edge cases"/"similar to" — every code step shows real code. Two explicit "verify the real signature" notes (Task 5 filename suffix, Task 6 `_problem_dict` key names) are *verification instructions*, not placeholders; the executing agent confirms against the live file.

**3. Type consistency:** `NoTextLayerError`/`GarbageTextError` carry `page_count` (defined Task 1, used Tasks 3/4/5). `recoverable` flag defined Task 1, used Tasks 3/5. `_recover_document_text_via_vision(*, content, client, page_count)` + `MAX_VISION_RECOVERY_PAGES` defined and used consistently in Task 5. `_ufffd_density` defined+used Task 4. `parse_resource_limit(*, max_bytes)` defined+used Task 7. `generate_multimodal(contents, label=...)` matches the real `gemini_client.py:99` signature.

**Ordering note:** Task 2's broad-`except`→`CorruptDocumentError` change is finalized in Task 3 Step 3 (same function); the executing agent should treat Task 3's `_extract_pdf` body as the authoritative final version.
