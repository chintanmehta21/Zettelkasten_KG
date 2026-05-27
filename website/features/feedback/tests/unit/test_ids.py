"""Tests for the FB-XXXX confirmation ID generator."""
from __future__ import annotations

import re

from website.features.feedback.core.ids import generate_feedback_id


VALID_ID_RE = re.compile(r"^FB-[A-Z2-7]{4}$")


def test_generate_feedback_id_format() -> None:
    fid = generate_feedback_id()
    assert VALID_ID_RE.match(fid), f"unexpected format: {fid}"


def test_generate_feedback_id_excludes_confusing_chars() -> None:
    """The alphabet must exclude 0/1/I/O/L (commonly confused in print/copy)."""
    forbidden = {"0", "1", "I", "O", "L"}
    for _ in range(200):
        fid = generate_feedback_id()
        assert not (forbidden & set(fid[3:])), f"contains forbidden char: {fid}"


def test_generate_feedback_id_collision_resistance_smoke() -> None:
    """20 bits of randomness → ~1M unique tails; 500 samples should have <2 dupes."""
    ids = {generate_feedback_id() for _ in range(500)}
    assert len(ids) >= 498
