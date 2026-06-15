# Document-Ingestion Robustness — Deep Research (Pass 2)

**Date:** 2026-06-15
**Status:** Research complete. **Decision deferred** — no implementation without explicit operator approval.
**Method:** `deep-research` harness — 109 agents, 6 angles, 26 sources fetched, 123 claims → 25 verified (3-vote adversarial), **22 confirmed / 3 killed**.

> ⚠️ **Provenance note:** the harness's final auto-synthesis malfunctioned — it returned a placeholder `summary`/`caveats` ("f3 full evidence probe no-expr") and collapsed to only 3 findings. The underlying **verify layer was healthy** (22/25 claims confirmed with citations). This report is **reconstructed by me** from: (a) the 3 detailed findings that survived synthesis, (b) the full verified-claims log, (c) the 26 cited sources — cross-checked against our actual code. Where a claim was truncated in the harness log, I represent its topic faithfully and mark fidelity. Scope excludes no-text/scanned recovery (that's Pass 1).

---

## 1. TL;DR — where we're already solid, and the 4 cheap wins

Our pipeline is **already above the industry baseline** on several dimensions (magic-bytes gate, defusedxml/XXE, DOCX zip-bomb guard, 10 MB cap, RFC-9457 problems, idempotency keys, durable async status, URL-dedup). The research found **four low/zero-infra hardening wins** that close real gaps:

1. **Encrypted-PDF gate** (High, ~zero cost) — today a password-protected PDF silently becomes the misleading "Could not extract enough text" error.
2. **Garbage-text (U+FFFD) gate** (High, zero cost) — today CID/mojibake text passes the `<50 chars` gate and feeds **Gemini a confident-wrong summary**.
3. **Per-parse resource jail** (High, low cost — **decision-gated, infra-adjacent**) — the sync PDF parse has no per-call memory/CPU ceiling on the 2 GB box.
4. **Error-taxonomy split** (High, zero cost) — one `invalid-document` slug for every failure → users get no actionable signal (compounded by the frontend swallowing `detail`).

---

## 2. Per-dimension matrix

| # | Failure mode | Likelihood | Current coverage in our stack | Recommended hardening | Infra cost | Priority |
|---|---|---|---|---|---|---|
| 1 | Malformed / corrupt / truncated PDF·DOCX | Med | Broad `except` in `_extract_pdf` catches it but is **signal-less**; MuPDF auto-repairs internally | Distinguish *corrupt* from other modes; surface a `CorruptDocumentError`; flag `is_repaired` as **partial-success** (Docling pattern) | None (code) | Med |
| 2 | **Encrypted / password PDF** | Med | **None** — `doc.needs_pass` not checked; surfaces as misleading `<50 chars` error | `if doc.needs_pass:` → `EncryptedDocumentError`; try `authenticate("")` first (owner-only-protected PDFs open with empty pw) | None | **High** |
| 3 | **Decompression bomb / DoS / pathological page count** | Low-Med | DOCX zip-bomb guard ✓, 10 MB cap ✓ — but **PDF parse has no per-call mem/CPU jail** | `RLIMIT_AS` ~256–384 MB self-OOM ceiling + sub-180 s cap on the sync parse (POSIX `resource`/pynisher); + page-count ceiling | Low (stdlib) | **High** *(decision-gated)* |
| 4 | File-type confusion / polyglot / MIME spoof | Med | **magic-bytes** `filetype.guess` ✓ (already beats extension-only) | Acknowledge magic-bytes alone ≠ sufficient vs polyglots (MalDoc-in-PDF); mitigated because we **parse in-process & never serve uploads back** | None | Low-Med |
| 5 | Malicious docs (PDF-JS, DOCX macros, OLE) | Low | We **never execute/render** — text-extract only; defusedxml ✓ (XXE) | Keep not-executing; ClamAV/CDR is **heavy — NOT recommended** for a 2 GB box; risk already bounded | None (no-op) | Low |
| 6 | **Garbage / mojibake / CID-font text** | Med-High | **None** beyond `<50 chars` — a U+FFFD flood passes → Gemini confident-wrong | U+FFFD **density ratio** (~10 % tuned) → `GarbageTextError` or route to OCR (ties to Pass 1) | None | **High** |
| 7 | Format coverage (RTF/ODT/PPTX/img/HTML/ebook) | Low | pdf·txt·md·docx only | Stay narrow on purpose; RTF has CVE history (CVE-2023-21716 = Word-side, not us); images → Pass 1 vision; HTML → URL ingestor | Varies | Low (defer) |
| 8 | **Failure-UX + observability** | High | RFC-9457 ✓, idempotency ✓, durable status ✓ — but **single `invalid-document` slug**, `detail` swallowed by frontend, no partial-success | Split `DocumentUploadError` into per-mode subclasses w/ distinct RFC-9457 `type`s; surface `detail` in UI; add Docling-style `PARTIAL_SUCCESS`; failure-taxonomy telemetry | None (code) | **High** |
| 9 | Concurrency / race / dedup on uploads | Med | idempotency keys ✓, durable ops rows ✓, `UNIQUE(normalized_url)` ✓ | Largely covered; ensure the **document** dedup-hash path mirrors the URL dedup gate | None | Low |

---

## 3. The 3 synthesized findings (full detail, as returned)

### F1 — Split `DocumentUploadError` into per-mode RFC-9457 types; adopt Docling's `PARTIAL_SUCCESS` `[high; 3-0]`
`DocumentUploadError` ([`ingest.py:48`](website/features/summarization_engine/source_ingest/document/ingest.py:48)) maps **every** failure to one slug `invalid-document` (mapping at [`zettels_routes.py:402-410`](website/api/zettels_routes.py:402)); `_problem_dict` already emits RFC-9457 `type_slug`/`title`/`detail`. Subclass into `Encrypted / Corrupt / GarbageText / DecompressionBomb / UnsupportedType`. Industry reference: **Docling** models each conversion error as a structured object and exposes a 6-value `ConversionStatus` enum including `PARTIAL_SUCCESS`. *Sources:* RFC 9457; Docling `base_models.py` / conversion-result docs.

### F2 — Encrypted gate (`needs_pass`) + explicit corrupt catch; flag `is_repaired` `[high; 3-0 / 2-1]`
**Encrypted:** `fitz.open` *succeeds* but `get_text` returns empty → today surfaces as our `<50 chars` error ([`ingest.py:207-208`](website/features/summarization_engine/source_ingest/document/ingest.py:207)). Add `if doc.needs_pass: raise EncryptedDocumentError`, and try `authenticate("")` first (owner-only-protected PDFs). **Corrupt:** `FileDataError` is a `RuntimeError` subclass, but issues **#2674 / #3905** show it can be *bypassed on the stream-bytes path we use* — so the blanket `except` at [`ingest.py:77-86`](website/features/summarization_engine/source_ingest/document/ingest.py:77) is load-bearing but signal-less; flag `is_repaired` as partial-success. *Sources:* PyMuPDF `document.html`; PyMuPDF issue #3905.

### F3 — U+FFFD garbage gate + per-parse `RLIMIT` jail `[high; 3-0]`
**Garbage:** PyMuPDF maintainer (Discussion #3801) confirms — when a glyph has no Unicode back-reference the codepoint is **U+FFFD**, the only recovery is OCR, and there is **no built-in repair**; pdf-inspector's `has_identity_h_no_tounicode` field drives per-page OCR routing. Our gate at `ingest.py:206-208` is **total-length-only**, so a U+FFFD flood passes and feeds **Gemini a confident-wrong summary**. Add a **U+FFFD density ratio** (~10 % threshold) → `GarbageTextError` or route to OCR. **Jail:** an `RLIMIT_CPU` hard limit yields a **kernel SIGKILL even inside a tight C loop** — exactly the PyMuPDF case; `_extract_pdf` is sync in-worker, and the **180 s `GUNICORN_TIMEOUT` is a PROTECTED knob (lowering FORBIDDEN)** — so add a tight **`RLIMIT_AS` ~256–384 MB self-OOM ceiling + a sub-180 s cap** (does *not* touch the protected knob). **Decision-gated, POSIX-only, pynisher 1.x.** *Sources:* automl/pynisher; PyMuPDF Discussion #3801.

---

## 4. Other confirmed claims (survived verify, dropped by the glitched synthesis)

Reconstructed from the verified-claims log (all 3-0 unless noted):

- **Security / file-type (4 claims):** Content-Type/metadata is attacker-spoofable; extension allow/deny lists are insufficient; uploaded docs are an active malware vector (OWASP); polyglot files are real (MalDoc-in-PDF, 2023). → *We already mitigate with magic-bytes + never executing uploads.*
- **DoS (2-1/3-0):** ZIP/decompression bombs are an explicit upload-DoS vector; `pynisher` enforces per-call `RLIMIT`s and SIGKILLs on breach. → *backs F3.*
- **Parser internals (3-0/2-1):** PyMuPDF detects encryption up-front; MuPDF auto-repairs damaged PDFs; `FileDataError` is catchable (2-1); `pdfminer.six` produces *incorrect* Unicode and only handles `ToUnicode` CMaps (so switching parser wouldn't fix CID garbage); maintainer's only garbage recovery = OCR (2-1). → *backs F2/F3.*
- **Failure-UX (3-0):** RFC-9457 separates a stable machine `type` from human `detail`; Docling's structured per-error + `PARTIAL_SUCCESS` taxonomy is the reference. → *backs F1.*

---

## 5. Refuted — do NOT implement these (killed)

1. **`doc.tobytes(garbage=3, deflate=True)` as a corrupt-PDF repair pass** (1-2) — not a reliable in-process repair; don't add it.
2. **Garbage text shows as literal `'<?>'` symbols** (0-3) — **false**; the real signal is **U+FFFD** (use density ratio, per F3).
3. **pdf-inspector decodes ToUnicode CMaps across UTF-16BE/UTF-8/Latin-1 as its meaning-check** (0-3) — unverified mechanism; rely on **U+FFFD density**, not a claimed CMap decoder.

---

## 6. Open questions / before any build

1. Tune the **U+FFFD density threshold** on real samples (10 % is a starting point, not measured for our corpus).
2. The **`RLIMIT` jail is decision-gated & infra-adjacent** (POSIX `resource`, sync-parse isolation) — needs explicit operator sign-off; verify it composes with gunicorn `--preload` + 2-worker without harming the protected 180 s timeout path.
3. Confirm the **document dedup-hash** path mirrors the existing `UNIQUE(normalized_url)` URL-dedup so duplicate uploads coalesce identically.

---

## 7. Sources (26 fetched; primary unless noted)

OWASP File-Upload Cheat Sheet + Unrestricted-Upload + WSTG malicious-files (primary) · RFC 9457 (primary) · Docling conversion-result (primary) · PyMuPDF `document.html` / recipes-common-issues / Discussion #3801 / issue #3905 (primary) · pdfminer.six issue #1072 (primary) · pypdf robustness (primary) · automl/pynisher + sfalkner/pynisher (primary) · Shopify idempotency + brandur idempotency-keys + AWS Postgres duplicate-key (primary/blog) · Google Cloud malware-scanning + DeepInstinct CDR-drawbacks (primary/blog) · thehackernews MalDoc-in-PDF + SentinelOne CVE-2023-21716 (secondary) · Notion import (primary) · Unstructured.io ingestion-challenges + HelloInterview Dropbox (blog) · Quantrium encrypted-PDF + luminousmen resource-limits (blog).

> Source quality strong on PRIMARY vendor/standard docs. The harness's own top-level synthesis was discarded as malformed; per-claim verification (3-vote) is the trusted layer here.
