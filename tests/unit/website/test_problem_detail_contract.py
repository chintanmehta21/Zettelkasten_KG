"""Contract: document-error RFC 9457 problem bodies carry actionable ``detail``.

Prior tasks mapped document-upload exception subclasses to distinct, actionable
``detail`` strings (e.g. NoTextLayerError -> "...scanned or printed-to-image.
Try pasting the source URL instead."). The frontend now surfaces that ``detail``
to the user, so the backend contract — that the problem body's ``detail`` field
actually carries the actionable guidance — must be guarded.

``_async_failure_error_payload`` funnels through ``_problem_dict``; the returned
body's normative members are ``type``/``title``/``status``/``detail``/``instance``
(RFC 9457 §3.1) plus the canonical ``code`` extension. ``type`` is
``https://zettelkasten.in/problems/errors/{type_slug}``, so it *ends with* the
slug. We assert on ``type`` (ends-with slug) and ``detail`` (substring), which is
exactly what the frontend keys off.
"""

from __future__ import annotations

from website.api.zettels_routes import _async_failure_error_payload
from website.features.summarization_engine.source_ingest.document import (
    EncryptedDocumentError,
    NoTextLayerError,
)


def test_no_text_layer_detail_mentions_scanned():
    """NoTextLayerError -> type ends with ``document-no-text-layer`` and the
    actionable ``detail`` tells the user the PDF looks scanned."""
    body = _async_failure_error_payload(
        NoTextLayerError(page_count=3), operation_id="op1"
    )

    assert body["type"].endswith("document-no-text-layer")
    assert "scanned" in body["detail"].lower()


def test_encrypted_document_detail_mentions_password():
    """EncryptedDocumentError -> type ends with ``document-encrypted`` and the
    actionable ``detail`` tells the user to remove the password."""
    body = _async_failure_error_payload(
        EncryptedDocumentError(), operation_id="op1"
    )

    assert body["type"].endswith("document-encrypted")
    assert "password" in body["detail"].lower()
