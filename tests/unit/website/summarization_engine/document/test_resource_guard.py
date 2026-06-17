import sys, pytest
from website.features.summarization_engine.source_ingest.document import resource_guard as rg


def test_noop_on_non_posix(monkeypatch):
    monkeypatch.setattr(rg.os, "name", "nt")
    with rg.parse_resource_limit(max_bytes=1):  # must not raise on Windows
        pass


@pytest.mark.skipif(sys.platform.startswith("win"), reason="POSIX rlimits only")
def test_address_space_cap_is_relative_and_restored():
    import resource
    soft0, hard0 = resource.getrlimit(resource.RLIMIT_AS)
    base = rg._current_address_space()
    assert base > 0  # /proc/self/statm readable on Linux
    HEADROOM = 256 * 1024 * 1024
    with rg.parse_resource_limit(max_bytes=HEADROOM):
        soft, _ = resource.getrlimit(resource.RLIMIT_AS)
        # Cap is RELATIVE: it sits ABOVE current usage (an absolute cap below
        # baseline would insta-OOM every allocation — the prod bug this fixes)
        # and within ~headroom of it.
        assert soft > base
        assert soft <= base + HEADROOM + 64 * 1024 * 1024
    # Original limits restored after the block.
    assert resource.getrlimit(resource.RLIMIT_AS) == (soft0, hard0)
