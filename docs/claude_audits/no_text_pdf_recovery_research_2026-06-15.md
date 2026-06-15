# No-Text / Scanned / Outlined PDF Ingestion — Deep Research (Pass 1)

**Date:** 2026-06-15
**Status:** Research complete. **Decision deferred** (operator's call after Pass 2: full ingestion robustness).
**Method:** `deep-research` harness — 108 agents, 6 search angles, 25 sources fetched, 121 claims → 25 verified (3-vote adversarial), 18 confirmed / 7 killed, 6 findings after synthesis.

> Do **not** implement from this doc. It is a report. Implementation requires explicit operator approval per CLAUDE.md.

---

## 0. Motivating case (verified from production)

User "Dhruv Chauhan" uploaded `DC_PDF.pdf` (11 pages, "Microsoft Print to PDF" of a Robot Wealth web article). Diagnosed earlier this session:
- Valid PDF (`%PDF-1.7`, passes magic-bytes), not encrypted.
- **0 text chars, 0 embedded fonts, ~9,108 vector drawings, 21 raster images** across all pages — text is baked into vector outlines + images.
- `PyMuPDF.get_text()` → empty → `extract_document_upload` raises at [`ingest.py:208`](website/features/summarization_engine/source_ingest/document/ingest.py:208) (`len(cleaned) < 50`) → `DocumentUploadError: Could not extract enough text from this document.` → UI shows "Invalid document upload".

This is **not a bug** — it's correct rejection of an input the pipeline can't currently recover. This research is about whether/how to recover it.

---

## 1. TL;DR recommendation (research verdict — not yet authorized)

**Two-stage: DETECT locally (near-zero cost) → RECOVER via Gemini vision (zero droplet footprint) → REDIRECT as graceful fallback.**

1. **Detect** no-text/outlined PDFs inline with the `fitz` we already use — chars-per-page **and** character-sized-vector / image-area-coverage checks. Replaces today's naive `<50 chars → reject` gate. The exact Dhruv case is a *named* signal ("Text-Looking Vectors").
2. **Recover** by sending rendered page images to **Gemini** (already integrated, multimodal). It rasterizes pages to pixels, so it reads scanned **and** vector-outlined pages identically. **Zero** new RAM/CPU/disk/dependency on the droplet; ~258 tokens/page (~$0.0013/page; ~$0.014 for Dhruv's 11-page file).
3. **Redirect** (steer user to paste the source URL / upload a text file) only as the **fallback** when Gemini returns empty/low-confidence — not as the primary (pure-redirect is degraded UX).

---

## 2. Recommendation matrix

| Approach | Reads no-text PDFs? | Accuracy on *our* inputs (web/article PDFs, low-qual scans) | Latency / doc | Cost / page | Droplet RAM / infra impact | Privacy / egress | Verdict |
|---|---|---|---|---|---|---|---|
| **(a) Gemini vision** (reuse existing) | ✅ rasterizes every page | High (its strength zone: clean rendered text, charts, low-qual scans) | 1 network API call | ~258 tok ≈ **$0.0013** | **Zero added** — runs in Google cloud | Same trust boundary we already cross for media | **PRIMARY** |
| **(b) Self-hosted OCR** (Tesseract / OCRmyPDF) | ✅ | High on dense text | **~1.8–7.5 s/page** (~20–80 s for 11 pg) on shared 1 vCPU | ~$0 marginal | **Heavy** — Tesseract OS binary + tessdata in image; CPU-bound contends with workers; process-per-page RAM; **OOM / worker-starvation risk** | Zero egress | **AVOID** (infra cost) |
| **(c) Managed doc-AI** (Azure DI / Textract / Mistral OCR) | ✅ | High | 1 network API call (~2–10 s) | $0.0013–0.0015/pg | Zero added | **New vendor + egress review**; Textract *stores inputs by default* (opt-out via Org policy); Azure best residency; Mistral self-host is sales-gated | **FALLBACK only** (redundant w/ Gemini) |
| **(d) Detect + redirect** | ❌ (no recovery) | — | ~20 ms detect | $0 | Zero | Zero egress | **GRACEFUL FALLBACK** |

---

## 3. Findings (survived 3-vote adversarial verification)

### F1 — Detection is solved, local, near-zero-cost, and our exact case is a *named* signal `[high; 3-0 / 2-1]`
Mature tools classify a PDF into `TextBased / Scanned / ImageBased / Mixed` with a 0.0–1.0 confidence score + per-page routing in **~20 ms**, using chars-per-page, image-area coverage, and **character-sized-vector counts**. PyMuPDF4LLM names exactly four OCR-trigger signals: *Text in Images*, *Illegible/Replacement-Unicode Text*, ***Text-Looking Vectors*** (visually readable but vector-drawn = print-to-PDF outlines), *Existing OCR Text of Dubious Quality*. **Dhruv's file = the "Text-Looking Vectors" category by definition.**
→ *Action implication:* upgrade [`ingest.py:208`](website/features/summarization_engine/source_ingest/document/ingest.py:208)'s `<50 chars → reject` to a structural classifier (chars-per-page **AND** char-sized-vector / image-area check) before deciding recover-vs-redirect.
*Sources:* firecrawl/pdf-inspector; PyMuPDF4LLM docs + hybrid-OCR blog (2026-03-31) + ocr-plugins.
*Caveat:* docs confirm the signal exists & is a trigger criterion but don't benchmark recall on that exact file — strong heuristic, not a guarantee.

### F2 — Gemini vision (approach a) is the best fit for our constrained droplet `[high; 3-0 / 2-1]`
Gemini does native vision document understanding by rasterizing every PDF page to pixels (up to 3072×3072), so it reads scanned/image-only **and** vector-outlined pages with zero extractable text — the ~9,000 vector drawings render identically to a scan. **Critically: zero new RAM/CPU/disk/dependency on the droplet** (inference is in Google's cloud — cannot OOM, cannot force drop to 1 worker, no Docker bloat). Cost ~258 tokens/page (~$0.0013/page; ~$0.014 for 11 pages); a no-text PDF pays full vision tokens (no free native-text offset). We already send media to Gemini, so this is a minor extension of a trusted integration.
*Source:* Google Gemini API document-processing docs (primary).
*Caveats:* (1) scanned-PDF fidelity is quality-dependent and lower than born-digital text; **ingest capability is solid, fidelity not guaranteed**; (2) 258/page is a **floor** — large pages tile into multiple 258-token units; (3) egress is real but the same boundary as existing media summarization.

### F3 — Self-hosted OCR (approach b) is viable but a poor fit `[high; 3-0]`
Not pip-only: PyMuPDF OCR is built on **Tesseract**, which needs an OS binary + tessdata in the Docker image. **~1000× slower** than text extraction (text ~1–5 ms/page vs Tesseract ~1.8–7.5 s/page) → ~20–80 s CPU-bound for 11 pages on the shared 1 vCPU, contending with request workers. Parallelism = one single-threaded Tesseract **process per page** (multiplies RAM); on a 1-vCPU box OCRmyPDF clamps threads to 1 (no speedup). Net: competes for the exact RAM/CPU the `--preload` + 2-worker design protects — OOM / worker-starvation risk.
*Sources:* PyMuPDF OCR recipe; OCRmyPDF maintainer (issue #580, verified via GitHub API).
*Caveat:* on a literal 1-vCPU box OCRmyPDF forks ~1 page-worker, which *bounds* RAM multiplication — but the seconds/page CPU cost and OS-binary bloat remain disqualifiers.

### F4 — Managed cloud doc-AI (approach c) is accurate + infra-free but redundant `[high; 3-0 / 2-1]`
Azure DI, AWS Textract, Mistral OCR all ingest scanned docs with predictable per-page pricing and **zero droplet footprint** (like Gemini). Differentiator is privacy + integration cost, not capability: **Azure** = strongest residency (in-region, 24 h retention, Delete API); **Textract** = cheapest but **stores/uses inputs by default** (opt-out only via AWS Org policy) — a real concern for user PDFs; **Mistral** = cheapest at scale + self-host option (zero egress) but sales-gated, undisclosed HW. Adopting any = new SDK + creds + DPA for a capability **Gemini already provides** → not primary. Azure (residency) or self-hosted Mistral (zero-egress) are the fallbacks **if a future rule forbids sending PDFs to Gemini**.
*Sources:* Azure DI privacy docs; AWS Textract FAQ + pricing; Mistral OCR.

### F5 — VLM vs traditional OCR are *complementary*; our inputs sit in Gemini's strength zone `[high; 2-1]`
VLMs (Gemini) win on charts/infographics, handwriting, complex fields, photos, and **low-quality scans** (more predictable). Traditional OCR keeps the edge on **high-density pages** (textbooks, research papers) and structured forms, where **VLMs hallucinate/repeat/drift in dense text**. Dhruv's case (web article via Print-to-PDF — moderate density, clean digital rasterization, no handwriting) = squarely Gemini's strength. We'd only need a traditional-OCR fallback if we later ingest **dense academic PDFs at scale**.
*Source:* getomni.ai OCR benchmark (1,000-doc, Feb 2025) — corroborated by 2024-26 arXiv (CC-OCR, MinerU2.5, "When Semantics Mislead Vision").
*Caveat:* getomni sells a VLM-OCR product (COI), but the cited half *concedes* traditional-OCR wins and is independently corroborated.

### F6 — Detect-and-redirect (approach d) is the right *fallback*, not the primary `[medium; 2-1]`
Detection is cheap + supported (F1). Redirect is the safest zero-cost, zero-egress option and aligns with our URL-centric pipeline (the source article usually has a canonical URL we can ingest as text). **But** industry practice with the same detector (firecrawl/pdf-inspector) routes detected scanned pages to **automated OCR/vision**, not back to the user — pure redirect is degraded UX. Synthesis: **try Gemini-vision first, fall back to redirect only on low-confidence/empty output.**
*Source:* firecrawl/pdf-inspector.
*Caveats:* the "~54% of PDFs don't need OCR" figure is unsourced vendor marketing — illustrative only; pdf-inspector's NO-branch routes to OCR (recovery), not a user-redirect, so it doesn't *directly* validate pure approach (d).

---

## 4. How this maps to our code (for a future, separately-approved implementation)

- **Detection** would slot in [`ingest.py` `extract_document_upload`](website/features/summarization_engine/source_ingest/document/ingest.py:197) right after `_extract_pdf` returns near-empty text — replacing the bare `len(cleaned) < 50` raise with: if PDF **and** (chars-per-page ≈ 0) **and** (high char-sized-vector count **or** high image-area coverage) → route to recovery instead of rejecting. Implementable with **existing `fitz`** (`page.get_drawings()`, `page.get_images()`, `page.get_text("words")`) — **no new dependency** (avoids pulling `pymupdf4llm` + its OpenCV/Tesseract prereqs).
- **Recovery** would reuse the existing Gemini client (`website/features/api_key_switching` + the document summarizer) — render pages with `page.get_pixmap()` and send images, OR send the PDF bytes to Gemini's document API. Gate by **page-count/size ceiling** to bound cost/latency.
- **Fallback/UX** ties into the existing problem path — surface the swallowed `detail` (already flagged this session as a UX gap: frontend shows `title` only, drops `detail`).
- **SSRF:** any "paste source URL" redirect must reuse the existing `validate_url()` guard (`utils/url_utils.py`).

---

## 5. Refuted claims — do NOT repeat these (killed 0-3 / 1-2)

1. **Tj/TJ-vs-Do operator-presence** detection heuristic (0-3) → use numeric **chars-per-page + char-sized-vector / image-area** instead.
2. General "**VLMs match/exceed most traditional OCR**" (0-3) → only **complementary** strengths are verified.
3. **Mistral** handwriting/skew superiority (0-3) → unverified.
4. **IBM** "OCR is *the* standard recovery path" + IBM's PyMuPDF endorsement (0-3 each).
5. PyMuPDF4LLM **auto-OCR without opt-in** (1-2); `get_textpage_ocr` selective-image-OCR sufficiency for the outlined case (1-2).

---

## 6. Open questions → pre-ship eval (before any implementation)

1. **Fidelity**, not just ingest-success, of Gemini vision on Microsoft Print-to-PDF *outlined* text vs clean scans — run a small internal eval on a handful of representative files (incl. Dhruv's actual `DC_PDF.pdf`).
2. Implement detection **inline with existing `fitz`** vs adding `pymupdf4llm` (+ OpenCV/Tesseract prereqs)? — lean inline to avoid dependency bloat.
3. What **page-count / file-size ceiling** before sending to Gemini? (200-page scan ≈ 51k tokens — protect latency budget + quota for normal traffic.)
4. Does uploaded-PDF egress cross a **new data boundary** vs our existing media-URL→Gemini integration (uploads may be more sensitive)? Warrants consent/notice or size-gated routing?

---

## 7. Caveats on the research itself

- **Pricing is time-sensitive** (Gemini 258 tok/page, Mistral $2/1k, Textract $0.0015/page are 2025–26 figures) — re-verify before committing a budget.
- The **OCR-VLM landscape moves fast** (DeepSeek-OCR, PaddleOCR-VL, MinerU2.5 by mid-2026) — narrowing the dense-text gap that currently favors traditional OCR.
- **Not proven:** no source benchmarks recovery accuracy on the *exact* Print-to-PDF file — detection of the category is confirmed; recovery recall/fidelity is inferred.

---

## 8. Sources (25 fetched; primary unless noted)

**Detection / PyMuPDF:** firecrawl/pdf-inspector (primary) · PyMuPDF4LLM docs + hybrid-OCR blog + ocr-plugins (primary) · PyMuPDF OCR recipe (primary) · docs.bswen.com OCR-vs-text (blog) · Quantrium/Medium (blog) · pypi ocr-detection (blog).
**Gemini / VLM:** ai.google.dev document-processing (primary) · getomni.ai benchmark (primary) · reducto.ai LVM-OCR (blog) · aimultiple OCR-accuracy (secondary) · pymupdf.io native-vs-vision-Gemini-3 (blog).
**Self-hosted OCR:** OCRmyPDF issue #580 (primary, GitHub-API-verified) · modal.com open-source-OCR (blog) · ironsoftware Paddle-vs-Tesseract (blog) · OCRmyPDF discussion #1386 (forum).
**Managed cloud:** Azure DI data-privacy (primary) · AWS Textract FAQ + pricing (primary) · Mistral OCR (primary) · aiproductivity cost-comparison (blog).
**Other:** IBM RAG cookbook (primary, but its OCR/PyMuPDF claims were *refuted*) · nutrient.io PyMuPDF (blog) · OCRmyPDF advanced docs (primary) · pdf.oxide.fyi (secondary) · firecrawl best-pdf-parsers (blog).
