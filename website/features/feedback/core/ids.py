"""Feedback ID generator — produces short, copy-safe confirmation IDs (FB-XXXX).

The ID is shown to the user in the success state and embedded in the Slack
message context. It is UI-only — there is no database row keyed on this ID
(operator decision, 2026-05-27). The Slack message timestamp is the canonical
record of each submission.
"""
from __future__ import annotations

import secrets

# Crockford-style base32 minus visually ambiguous chars (0/1/I/O/L) and
# digits 8/9 (kept aligned with the validating regex [A-Z2-7]).
# 23 letters + 6 digits = 29 chars × 4 positions = 707,281 unique tails (~19.4 bits).
_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ234567"
_TAIL_LENGTH = 4


def generate_feedback_id() -> str:
    """Return a fresh confirmation ID like 'FB-7K3Q'."""
    tail = "".join(secrets.choice(_ALPHABET) for _ in range(_TAIL_LENGTH))
    return f"FB-{tail}"
