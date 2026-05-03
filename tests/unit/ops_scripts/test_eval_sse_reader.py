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
