"""Tests for website.config.page_menus.

PR1 scope: schema valid for the 6 currently-served pages, all entries have
non-empty authed items, no per-page duplicate item keys, all items reference
a key from the canonical registry. Does NOT assert "only pricing has anon" —
that's a PR2 assertion (PR1 leaves anon=None for every entry).
"""
from website.config.page_menus import MenuItem, PageMenu, PAGE_MENUS


EXPECTED_PR1_PAGE_KEYS = {"zettels", "kastens", "rag", "nexus", "profile", "pricing"}
EXPECTED_AUTHED_KEYS_PR1 = ["home", "zettels", "kastens", "nexus", "kg", "profile", "signout"]


def test_page_menus_has_expected_pr1_keys():
    assert set(PAGE_MENUS.keys()) == EXPECTED_PR1_PAGE_KEYS


def test_every_entry_has_non_empty_authed_list():
    for page_key, menu in PAGE_MENUS.items():
        assert menu["authed"], f"{page_key} has empty authed list"


def test_pr1_all_pages_use_same_authed_list():
    """PR1 contract: every page shows the SAME 7-item dropdown today.
    Per-page divergence is introduced in PR2."""
    for page_key, menu in PAGE_MENUS.items():
        item_keys = [item["key"] for item in menu["authed"]]
        assert item_keys == EXPECTED_AUTHED_KEYS_PR1, (
            f"{page_key} diverges from PR1 default list: {item_keys}"
        )


def test_no_duplicate_item_keys_within_a_page():
    for page_key, menu in PAGE_MENUS.items():
        keys = [item["key"] for item in menu["authed"]]
        assert len(keys) == len(set(keys)), f"{page_key} has duplicate item keys"


def test_show_back_button_defaults_true_in_pr1():
    """PR1 doesn't touch /home yet; back-button shows on all 6 pages."""
    for page_key, menu in PAGE_MENUS.items():
        assert menu["show_back_button"] is True


def test_anon_fields_unset_in_pr1():
    """PR1 doesn't populate anon variants. PR2 adds them for pricing."""
    for page_key, menu in PAGE_MENUS.items():
        assert menu["anon"] is None
        assert menu["anon_avatar_action"] is None


def test_every_item_has_required_fields():
    required_keys = {"key", "label", "href", "icon"}
    for page_key, menu in PAGE_MENUS.items():
        for item in menu["authed"]:
            missing = required_keys - set(item.keys())
            assert not missing, f"{page_key}/{item.get('key')} missing fields: {missing}"
