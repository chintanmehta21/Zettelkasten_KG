"""Verify nexus persist does NOT eagerly import the embeddings module."""
from __future__ import annotations

import sys


HEAVY = "website.features.kg_features.embeddings"
TARGET = "website.experimental_features.nexus.service.persist"


def test_persist_module_does_not_import_embeddings():
    """Importing the persist module must not pull in kg_features.embeddings."""
    sys.modules.pop(HEAVY, None)
    sys.modules.pop(TARGET, None)
    for key in list(sys.modules.keys()):
        if key.startswith(HEAVY + ".") or key.startswith(TARGET + "."):
            sys.modules.pop(key, None)

    import website.experimental_features.nexus.service.persist  # noqa: F401

    assert HEAVY not in sys.modules


def test_persist_result_function_still_available():
    """The public persist entrypoint remains available after lazy import refactor."""
    import website.experimental_features.nexus.service.persist as persist_module

    assert hasattr(persist_module, "persist_summarized_result")
    assert callable(persist_module.persist_summarized_result)
