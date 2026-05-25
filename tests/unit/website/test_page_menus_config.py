"""Tests for website.config.page_menus — PR2 invariants.

PR2 contract: 7 entries (home + zettels + kastens + rag + nexus + profile + pricing).
Each entry has its own per-page items list (current-page hidden). Only `pricing`
has an `anon` variant. Only `home` has `show_back_button=False`. The "Store"
item is present in every entry except `pricing` (which is the Store).
"""
from website.config.page_menus import MenuItem, PageMenu, PAGE_MENUS


EXPECTED_PR2_PAGE_KEYS = {"home", "zettels", "kastens", "rag", "nexus", "profile", "pricing"}


EXPECTED_AUTHED = {
    "home":     ["nexus", "profile", "store", "signout"],
    "zettels":  ["home", "kastens", "kg", "nexus", "profile", "store", "signout"],
    "kastens":  ["home", "zettels", "kg", "nexus", "profile", "store", "signout"],
    "rag":      ["home", "zettels", "kastens", "kg", "nexus", "profile", "store", "signout"],
    "nexus":    ["home", "zettels", "kastens", "kg", "profile", "store", "signout"],
    "profile":  ["home", "zettels", "kastens", "kg", "nexus", "store", "signout"],
    "pricing":  ["home", "zettels", "kastens", "kg", "nexus", "profile", "signout"],
}


def test_page_menus_has_expected_pr2_keys():
    assert set(PAGE_MENUS.keys()) == EXPECTED_PR2_PAGE_KEYS


def test_per_page_authed_lists_match_spec():
    for page_key, expected_keys in EXPECTED_AUTHED.items():
        actual_keys = [item["key"] for item in PAGE_MENUS[page_key]["authed"]]
        assert actual_keys == expected_keys, (
            f"{page_key}: expected {expected_keys}, got {actual_keys}"
        )


def test_no_page_lists_itself_in_dropdown():
    for page_key in ("zettels", "kastens", "rag", "nexus", "profile", "pricing"):
        item_keys = [item["key"] for item in PAGE_MENUS[page_key]["authed"]]
        if page_key == "pricing":
            assert "store" not in item_keys
        else:
            assert page_key not in item_keys


def test_home_omits_zettels_kastens_kg():
    item_keys = [item["key"] for item in PAGE_MENUS["home"]["authed"]]
    assert "zettels" not in item_keys
    assert "kastens" not in item_keys
    assert "kg" not in item_keys
    assert "home" not in item_keys


def test_only_home_hides_back_button():
    for page_key, menu in PAGE_MENUS.items():
        expected_show = page_key != "home"
        assert menu["show_back_button"] is expected_show, (
            f"{page_key}: show_back_button={menu['show_back_button']} "
            f"(expected {expected_show})"
        )


def test_only_pricing_populates_anon():
    for page_key, menu in PAGE_MENUS.items():
        if page_key == "pricing":
            assert menu["anon"] is not None
            assert menu["anon_avatar_action"] == "open-login-modal"
        else:
            assert menu["anon"] is None
            assert menu["anon_avatar_action"] is None


def test_pricing_anon_items_are_home_and_signin():
    anon = PAGE_MENUS["pricing"]["anon"]
    assert anon is not None
    keys = [item["key"] for item in anon]
    assert keys == ["home", "signin"], f"unexpected anon items: {keys}"


def test_dashboard_relabel_to_home():
    for menu in PAGE_MENUS.values():
        for item in menu["authed"]:
            if item["key"] == "home":
                assert item["label"] == "Home", f"label drift: {item['label']!r}"
                assert item["href"] == "/home"


def test_store_item_links_to_pricing():
    for menu in PAGE_MENUS.values():
        for item in menu["authed"]:
            if item["key"] == "store":
                assert item["label"] == "Store"
                assert item["href"] == "/pricing"


def test_every_item_has_required_fields():
    required_keys = {"key", "label", "href", "icon"}
    for page_key, menu in PAGE_MENUS.items():
        for item_list_name in ("authed", "anon"):
            items = menu.get(item_list_name) or []
            for item in items:
                missing = required_keys - set(item.keys())
                assert not missing, (
                    f"{page_key}/{item_list_name}/{item.get('key')} "
                    f"missing fields: {missing}"
                )
