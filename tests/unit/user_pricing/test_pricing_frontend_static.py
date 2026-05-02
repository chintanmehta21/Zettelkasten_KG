from __future__ import annotations

from pathlib import Path


def test_pricing_page_uses_shared_header_and_purchase_launcher() -> None:
    html = Path("website/footer/pricing/index.html").read_text(encoding="utf-8")

    assert "<!--ZK_HEADER-->" in html
    assert "/header/css/header.css" in html
    assert "/user-pricing/js/purchase_launcher.js" in html
    assert "Starter" not in html
    assert "Builder" not in html
    assert "Studio" not in html


def test_pricing_js_fetches_catalog_instead_of_embedding_prices() -> None:
    js = Path("website/footer/pricing/js/pricing.js").read_text(encoding="utf-8")

    assert "/api/pricing/catalog" in js
    assert "openPurchase" in js
    assert "14900" not in js
    assert "29900" not in js
    assert "Rs " not in js
    assert 'data-amount="' in js
    assert "expectedAmount" in js
    assert "₹" in js


def test_custom_question_slider_uses_dynamic_pack_scale() -> None:
    js = Path("website/footer/pricing/js/pricing.js").read_text(encoding="utf-8")

    assert "function sliderSettings" in js
    assert "catalog.custom_slider_values && catalog.custom_slider_values[meter]" in js
    assert "[50, 100, 150, 200, 250, 300, 350]" in js
    assert "String(value) + (index === values.length - 1 ? '+' : '')" in js
    assert "snapToPacks" not in js


def test_custom_slider_uses_indexed_stops_for_irregular_quantities() -> None:
    js = Path("website/footer/pricing/js/pricing.js").read_text(encoding="utf-8")

    assert "[1, 5, 10, 20, 30, 40, 50]" in js
    assert 'type="range" min="0"' in js
    assert "sliderIndexForQuantity(customQuantity, slider)" in js
    assert "quantityForSliderIndex" in js
    assert 'max="' + " + slider.inputMax" not in js


def test_custom_slider_labels_are_positioned_on_exact_percentage_ticks() -> None:
    css = Path("website/footer/pricing/css/pricing.css").read_text(encoding="utf-8")
    js = Path("website/footer/pricing/js/pricing.js").read_text(encoding="utf-8")

    assert ".custom-range-labels" in css
    assert "position: absolute" in css
    assert "tickPosition(index, slider)" in js


def test_custom_quantity_input_centers_digits_without_number_spinner() -> None:
    css = Path("website/footer/pricing/css/pricing.css").read_text(encoding="utf-8")

    assert "font-variant-numeric: tabular-nums" in css
    assert "appearance: textfield" in css
    assert "::-webkit-inner-spin-button" in css


def test_pricing_motion_and_strikethrough_visual_tuning() -> None:
    css = Path("website/footer/pricing/css/pricing.css").read_text(encoding="utf-8")

    assert "@keyframes pricing-panel-in" in css
    assert "prefers-reduced-motion: reduce" in css
    assert "border-top: 0.5px solid #fff" in css
    assert "right: -3px" in css
    assert "max-width: none" in css
    assert "min-height: 2.16rem" in css


def test_pricing_toggles_use_sliding_indicator_without_subscription_redraw() -> None:
    css = Path("website/footer/pricing/css/pricing.css").read_text(encoding="utf-8")
    js = Path("website/footer/pricing/js/pricing.js").read_text(encoding="utf-8")

    assert ".pricing-tabs::before" in css
    assert ".period-toggle::before" in css
    assert ".custom-topline::before" in css
    assert "syncSlidingIndicator" in js
    assert "function updateSubscriptionPeriod(periodBtn)" in js
    assert "function updateCustomMeter(meter)" in js
    period_handler = js.split("var periodBtn = event.target.closest('[data-period]')", 1)[1].split("var productBtn", 1)[0]
    assert "renderSubscriptions()" not in period_handler
    card_handler = js.split("var card = event.target.closest('[data-plan-card]')", 1)[1].split("var meterBtn", 1)[0]
    assert "renderSubscriptions()" not in card_handler
    meter_handler = js.split("var meterBtn = event.target.closest('[data-custom-meter]')", 1)[1].split("var stepBtn", 1)[0]
    assert "renderPacks()" not in meter_handler
    step_handler = js.split("var stepBtn = event.target.closest('[data-step-qty]')", 1)[1].split("document.addEventListener('input'", 1)[0]
    assert "renderPacks()" not in step_handler
    range_handler = js.split("event.target.id === 'custom-count-range'", 1)[1].split("event.target.id === 'custom-count-input'", 1)[0]
    assert "renderPacks()" not in range_handler
    input_handler = js.split("event.target.id === 'custom-count-input'", 1)[1].split("window.addEventListener('resize'", 1)[0]
    assert "renderPacks()" not in input_handler


def test_pricing_css_avoids_purple_hues() -> None:
    css = Path("website/footer/pricing/css/pricing.css").read_text(encoding="utf-8").lower()

    forbidden = ["purple", "violet", "lavender", "250,", "260,", "270,", "280,", "290,"]
    for token in forbidden:
        assert token not in css


def test_purchase_launcher_sends_expected_amount_to_backend() -> None:
    js = Path("website/features/user_pricing/js/purchase_launcher.js").read_text(encoding="utf-8")

    assert "expected_amount: expectedAmount" in js
    assert "productInfo.amount" in js
    assert "Displayed price changed" in js
    assert "/^custom_(zettel|kasten|question)_\\d+$/" in js
