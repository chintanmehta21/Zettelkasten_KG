"""SSE byte-stream parser tests for the iter-09 harness reader.

Tests the JS-side reader logic indirectly by extracting the parser into a
pure-Python equivalent at ops/scripts/_sse_reader.py for unit testing. The
in-page Playwright `fetch().getReader()` consumer mirrors this behaviour.
"""
from ops.scripts._sse_reader import parse_sse_stream


def test_token_then_done_emits_first_and_complete():
    chunks = [
        b"event: token\ndata: \"hello\"\n\n",
        b"event: token\ndata: \" world\"\n\n",
        b"event: done\ndata: {\"turn\":{\"id\":\"t1\"}}\n\n",
    ]
    out = parse_sse_stream(chunks)
    assert out["p_user_first_token_ms"] is not None
    assert out["p_user_last_token_ms"] is not None
    assert out["p_user_complete_ms"] is not None
    assert out["p_user_first_token_ms"] <= out["p_user_last_token_ms"] <= out["p_user_complete_ms"]


def test_done_without_tokens_records_complete_only():
    chunks = [b"event: done\ndata: {\"turn\":{\"id\":\"t1\"}}\n\n"]
    out = parse_sse_stream(chunks)
    assert out["p_user_first_token_ms"] is None
    assert out["p_user_complete_ms"] is not None


def test_error_mid_stream_records_error():
    chunks = [
        b"event: token\ndata: \"hi\"\n\n",
        b"event: error\ndata: {\"code\":\"queue_full\"}\n\n",
    ]
    out = parse_sse_stream(chunks)
    assert out["error"] == {"code": "queue_full"}
    assert out["p_user_complete_ms"] is None


def test_heartbeat_only_then_done_does_not_miscount():
    chunks = [
        b": heartbeat\n\n",
        b": heartbeat\n\n",
        b"event: done\ndata: {\"turn\":{}}\n\n",
    ]
    out = parse_sse_stream(chunks)
    assert out["p_user_first_token_ms"] is None
    assert out["p_user_complete_ms"] is not None


def test_partial_frame_buffer_reassembly():
    chunks = [
        b"event: tok",
        b"en\ndata: \"split\"\n\n",
        b"event: done\ndata: {\"turn\":{}}\n\n",
    ]
    out = parse_sse_stream(chunks)
    assert out["p_user_first_token_ms"] is not None
    assert out["p_user_complete_ms"] is not None


def test_timing_is_relative_to_fetch_start_not_page_load():
    """iter-10 P1: regression for the JS-side harness arithmetic bug — the
    parser MUST return p_user_*_ms relative to per-call fetch t0, not since
    process / page start. Two back-to-back parses must produce independent
    measurements; the second is NOT ~50ms larger than the first just because
    we slept between them.
    """
    import time

    chunks_a = [b"event: token\ndata: \"a\"\n\n", b"event: done\ndata: {}\n\n"]
    chunks_b = [b"event: token\ndata: \"b\"\n\n", b"event: done\ndata: {}\n\n"]
    out_a = parse_sse_stream(chunks_a)
    time.sleep(0.05)
    out_b = parse_sse_stream(chunks_b)
    assert 0 <= out_a["p_user_complete_ms"] < 100
    assert 0 <= out_b["p_user_complete_ms"] < 100
    assert abs(out_b["p_user_complete_ms"] - out_a["p_user_complete_ms"]) < 50
