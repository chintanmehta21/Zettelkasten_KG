"""Registered helper exposing the generic-speaker decision for reuse.

The YouTube layout calls _is_placeholder_speaker directly (kept — already
tested); this module re-exports the same conservative predicate under a public
name so other sources can adopt it later without duplicating logic. No new
registry rule is registered here — the layout is the call site.
"""
from __future__ import annotations

from website.features.summarization_engine.summarization.youtube.schema import (
    _is_placeholder_speaker as is_generic_speaker,  # re-export, single source of truth
)

__all__ = ["is_generic_speaker"]
