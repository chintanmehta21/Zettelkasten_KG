from pathlib import Path

from website.features.summarization_engine.core.cache import FsContentCache


def test_cache_roundtrip(tmp_path: Path):
    cache = FsContentCache(root=tmp_path, namespace="test_ns")
    key = ("https://a.com/x", "v1")
    assert cache.get(key) is None
    cache.put(key, {"payload": "value", "n": 1})
    stored = cache.get(key)
    assert stored is not None
    assert stored["payload"] == "value"


def test_cache_hash_stable(tmp_path: Path):
    cache = FsContentCache(root=tmp_path, namespace="test_ns")
    key1 = ("a", "b", {"c": 1, "d": 2})
    key2 = ("a", "b", {"d": 2, "c": 1})
    assert cache.key_hash(key1) == cache.key_hash(key2)


def test_cache_disabled_via_env(tmp_path, monkeypatch):
    monkeypatch.setenv("CACHE_DISABLED", "1")
    cache = FsContentCache(root=tmp_path, namespace="test_ns")
    cache.put(("k",), {"v": 1})
    assert cache.get(("k",)) is None
