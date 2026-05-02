from __future__ import annotations

from pathlib import Path

from website.features.user_pricing.catalog import find_product, get_public_catalog
from website.features.user_pricing.config import PRICING_CONFIG


def test_catalog_reads_subscription_prices_from_config() -> None:
    catalog = get_public_catalog()
    basic = catalog["plans"]["basic"]
    max_plan = catalog["plans"]["max"]

    assert basic["periods"]["monthly"]["launch_amount"] == PRICING_CONFIG["plans"]["basic"]["periods"]["monthly"]["launch_amount"]
    assert basic["periods"]["quarterly"]["launch_amount"] == PRICING_CONFIG["plans"]["basic"]["periods"]["quarterly"]["launch_amount"]
    assert basic["periods"]["yearly"]["launch_amount"] == PRICING_CONFIG["plans"]["basic"]["periods"]["yearly"]["launch_amount"]
    assert max_plan["periods"]["monthly"]["launch_amount"] == PRICING_CONFIG["plans"]["max"]["periods"]["monthly"]["launch_amount"]


def test_catalog_includes_all_pack_groups() -> None:
    catalog = get_public_catalog()

    assert set(catalog["packs"]) == {"zettel", "kasten", "question"}
    assert catalog["packs"]["zettel"][0]["id"] == "zettel_1"
    assert catalog["packs"]["kasten"][0]["quantity"] == 1
    assert catalog["packs"]["question"][-1]["quantity"] == 500


def test_catalog_has_visible_custom_slider_price_points() -> None:
    catalog = get_public_catalog()

    assert [pack["quantity"] for pack in catalog["packs"]["zettel"][:7]] == [1, 5, 10, 20, 30, 40, 50]
    assert [pack["quantity"] for pack in catalog["packs"]["kasten"][:7]] == [1, 5, 10, 20, 30, 40, 50]
    assert [pack["quantity"] for pack in catalog["packs"]["question"][:7]] == [50, 100, 150, 200, 250, 300, 350]
    assert next(pack for pack in catalog["packs"]["kasten"] if pack["quantity"] == 10)["display_amount"] == "₹499"
    assert catalog["custom_slider_values"]["zettel"] == [1, 5, 10, 20, 30, 40, 50]
    assert catalog["custom_slider_values"]["question"] == [50, 100, 150, 200, 250, 300, 350]


def test_generated_custom_pack_products_extend_textbox_quantities() -> None:
    kasten = find_product("custom_kasten_60")
    question = find_product("custom_question_400")

    assert kasten is not None
    assert kasten["kind"] == "pack"
    assert kasten["quantity"] == 60
    assert kasten["amount"] > find_product("kasten_50")["amount"]
    assert question is not None
    assert question["quantity"] == 400
    assert question["id"] == "custom_question_400"


def test_quota_recommendations_are_config_driven() -> None:
    catalog = get_public_catalog()

    assert catalog["recommendations"] == PRICING_CONFIG["recommendations"]
    assert "zettel_10" in catalog["recommendations"]["zettel"]
    assert "kasten_5" in catalog["recommendations"]["kasten"]
    assert "questions_500" in catalog["recommendations"]["rag_question"]


def test_pricing_reference_lives_next_to_config() -> None:
    module_dir = Path("website/features/user_pricing")

    assert (module_dir / "config.py").exists()
    assert (module_dir / "PRICING.md").exists()
