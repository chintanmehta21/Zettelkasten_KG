import sys, pytest
from website.features.summarization_engine.source_ingest.document import resource_guard as rg


def test_noop_on_non_posix(monkeypatch):
    monkeypatch.setattr(rg.os, "name", "nt")
    with rg.parse_resource_limit(max_bytes=1):  # must not raise on Windows
        pass


@pytest.mark.skipif(sys.platform.startswith("win"), reason="POSIX rlimits only")
def test_address_space_cap_is_set_and_restored():
    import resource
    soft0, hard0 = resource.getrlimit(resource.RLIMIT_AS)
    with rg.parse_resource_limit(max_bytes=512 * 1024 * 1024):
        soft, _ = resource.getrlimit(resource.RLIMIT_AS)
        assert soft <= 512 * 1024 * 1024
    assert resource.getrlimit(resource.RLIMIT_AS) == (soft0, hard0)
