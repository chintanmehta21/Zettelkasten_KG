"""Smoke test — verifies pytest discovers tests under the feature module."""
from __future__ import annotations


def test_module_importable() -> None:
    import website.features.feedback as feedback
    assert feedback is not None
