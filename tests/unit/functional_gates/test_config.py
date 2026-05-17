"""Unit tests for functional_gates.config — the operator-editable source of truth."""
from __future__ import annotations

import pytest

from website.features.functional_gates import config as fg_config


def test_pricing1_md_caps_are_seeded_exactly():
    """Caps in config.PLAN_CAPS must match docs/research/pricing1.md verbatim."""
    free = fg_config.PLAN_CAPS["free"]
    basic = fg_config.PLAN_CAPS["basic"]
    mx = fg_config.PLAN_CAPS["max"]

    assert free["zettel"] == {"day": 2, "week": 10, "month": 30, "lifetime": None}
    assert free["kasten"] == {"day": None, "week": None, "month": None, "lifetime": 1}
    assert free["rag_question"] == {"day": None, "week": None, "month": 30, "lifetime": None}

    assert basic["zettel"] == {"day": 5, "week": 30, "month": 50, "lifetime": None}
    assert basic["kasten"]["lifetime"] == 5
    assert basic["rag_question"]["month"] == 100

    assert mx["zettel"] == {"day": 30, "week": 100, "month": 200, "lifetime": None}
    assert mx["kasten"]["week"] == 5
    assert mx["kasten"]["lifetime"] == 50
    assert mx["rag_question"]["month"] == 500


def test_known_plans_are_exactly_free_basic_max():
    assert fg_config.KNOWN_PLANS == frozenset({"free", "basic", "max"})


def test_features_cover_meter_enum_values():
    from website.features.user_pricing.models import Meter

    assert set(fg_config.FEATURES) == {m.value for m in Meter}


def test_wallet_meter_aligns_with_pack_fulfillment():
    """Webhook adds credits with meter='zettel'|'kasten'|'rag_question'.
    Gate must read the SAME meter names.
    """
    assert fg_config.wallet_meter_for("zettel") == "zettel"
    assert fg_config.wallet_meter_for("kasten") == "kasten"
    assert fg_config.wallet_meter_for("rag_question") == "rag_question"


def test_caps_for_known_pair():
    assert fg_config.caps_for("free", "zettel")["day"] == 2
    assert fg_config.caps_for("max", "rag_question")["month"] == 500


def test_caps_for_unknown_plan_falls_back_to_default():
    fallback = fg_config.caps_for("ultra-gold-deluxe", "zettel")
    assert fallback == fg_config.caps_for("free", "zettel")


def test_caps_for_unknown_feature_returns_empty():
    assert fg_config.caps_for("free", "no-such-feature") == {}


def test_normalize_plan_filters_unknown():
    assert fg_config.normalize_plan("max") == "max"
    assert fg_config.normalize_plan("free") == "free"
    assert fg_config.normalize_plan("invented") == "free"
    assert fg_config.normalize_plan(None) == "free"
    assert fg_config.normalize_plan("") == "free"


def test_validate_config_passes_for_shipped_config():
    fg_config.validate_config()  # raises on inconsistency


def test_validate_config_rejects_negative_limit(monkeypatch):
    bad = {
        "free": {
            "zettel":       {"day": -1, "week": None, "month": None, "lifetime": None},
            "kasten":       {"day": None, "week": None, "month": None, "lifetime": 1},
            "rag_question": {"day": None, "week": None, "month": 30,  "lifetime": None},
        }
    }
    monkeypatch.setattr(fg_config, "PLAN_CAPS", bad)
    monkeypatch.setattr(fg_config, "KNOWN_PLANS", frozenset({"free"}))
    with pytest.raises(ValueError, match="non-negative"):
        fg_config.validate_config()


def test_validate_config_rejects_unknown_granularity(monkeypatch):
    bad = {
        "free": {
            "zettel":       {"hourly": 2, "week": None, "month": None, "lifetime": None},
            "kasten":       {"day": None, "week": None, "month": None, "lifetime": 1},
            "rag_question": {"day": None, "week": None, "month": 30,  "lifetime": None},
        }
    }
    monkeypatch.setattr(fg_config, "PLAN_CAPS", bad)
    monkeypatch.setattr(fg_config, "KNOWN_PLANS", frozenset({"free"}))
    with pytest.raises(ValueError, match="unknown granularity"):
        fg_config.validate_config()
