"""Pin the storage-event cross-tab fallback in zk_fetch.js for legacy iOS Safari.

BroadcastChannel only shipped in iOS Safari 15.4 (March 2022). Users on older
iOS would NOT see cross-tab sign-out/expired notifications without this
fallback. Pattern: setItem + immediate removeItem fires the 'storage' event
in OTHER tabs without polluting storage.

See research synthesis 2026-05-26 R1: "storage-event fallback for legacy iOS
Safari (~10 LOC), no server impact."
"""
from __future__ import annotations

import re
from pathlib import Path

ZK_FETCH_JS = (
    Path(__file__).resolve().parents[3]
    / "website"
    / "static"
    / "js"
    / "zk_fetch.js"
)


def _strip_comments(src: str) -> str:
    no_block = re.sub(r"/\*.*?\*/", "", src, flags=re.DOTALL)
    return re.sub(r"//[^\n]*", "", no_block)


def test_zk_fetch_pins_storage_broadcast_key():
    """The shared storage key must be stable across releases so tabs agree."""
    src = _strip_comments(ZK_FETCH_JS.read_text(encoding="utf-8"))
    assert re.search(
        r"""STORAGE_BROADCAST_KEY\s*=\s*['"]zk-auth-broadcast['"]""",
        src,
    ), (
        "STORAGE_BROADCAST_KEY must be 'zk-auth-broadcast' so all tabs (including "
        "older iOS Safari without BroadcastChannel) subscribe to the same key."
    )


def test_zk_fetch_listens_to_storage_event():
    """zk_fetch.js must register a 'storage' window listener for cross-tab fan-out."""
    src = _strip_comments(ZK_FETCH_JS.read_text(encoding="utf-8"))
    assert re.search(r"""addEventListener\(\s*['"]storage['"]""", src), (
        "zk_fetch.js must call window.addEventListener('storage', ...) so iOS "
        "Safari <15.4 tabs receive cross-tab sign-out / session-expired events."
    )


def test_zk_fetch_broadcast_writes_and_immediately_removes():
    """broadcastAndShow must setItem + removeItem to fan out without polluting storage."""
    src = _strip_comments(ZK_FETCH_JS.read_text(encoding="utf-8"))
    assert "broadcastAndShow" in src, "broadcastAndShow function must exist"
    # The write+remove pair is unique to the storage-fallback path; if both are
    # present somewhere in the file, they're in broadcastAndShow (the storage
    # listener only reads, never writes).
    assert "setItem(STORAGE_BROADCAST_KEY" in src, (
        "zk_fetch.js must localStorage.setItem(STORAGE_BROADCAST_KEY, ...) "
        "to trigger the storage event in sibling tabs."
    )
    assert "removeItem(STORAGE_BROADCAST_KEY" in src, (
        "zk_fetch.js must immediately localStorage.removeItem(STORAGE_BROADCAST_KEY) "
        "after the setItem so the key doesn't persist as garbage."
    )
    # And the order must be set→remove (not remove→set), so the storage event
    # fires with a non-null newValue.
    set_idx = src.index("setItem(STORAGE_BROADCAST_KEY")
    remove_idx = src.index("removeItem(STORAGE_BROADCAST_KEY")
    assert set_idx < remove_idx, (
        "setItem(STORAGE_BROADCAST_KEY) must come BEFORE removeItem so the "
        "'storage' event fires with newValue populated (other tabs need to "
        "parse the payload, not just see a deletion)."
    )


def test_zk_fetch_preserves_broadcastchannel_for_modern_browsers():
    """The BroadcastChannel path must remain — storage is fallback, not replacement."""
    src = ZK_FETCH_JS.read_text(encoding="utf-8")
    assert "new BroadcastChannel(" in src, (
        "BroadcastChannel must remain the primary cross-tab transport on modern "
        "browsers; storage event is a fallback for legacy iOS Safari only."
    )
    assert "channel.postMessage" in src, (
        "broadcastAndShow must still postMessage on the BroadcastChannel when "
        "available — belt + braces with the storage-event fallback."
    )


def test_zk_fetch_storage_listener_filters_key():
    """The storage listener must only react to STORAGE_BROADCAST_KEY, not every key."""
    src = ZK_FETCH_JS.read_text(encoding="utf-8")
    # Locate the storage handler and confirm it filters
    # Pattern: `if (e.key !== STORAGE_BROADCAST_KEY || !e.newValue) return;`
    assert re.search(r"e\.key\s*!==?\s*STORAGE_BROADCAST_KEY", src), (
        "Storage event handler must short-circuit when e.key is not our broadcast "
        "key — otherwise unrelated localStorage writes (e.g., kg.view) would "
        "spuriously trigger reauth banners."
    )
