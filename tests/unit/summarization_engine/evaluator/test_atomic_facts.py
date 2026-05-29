from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from website.features.summarization_engine.evaluator.atomic_facts import (
    extract_atomic_facts,
)
from website.features.summarization_engine.evaluator.prompts import PROMPT_VERSION


@pytest.mark.asyncio
async def test_extract_atomic_facts_returns_list(tmp_path: Path):
    client = MagicMock()
    fake_result = MagicMock(
        text='[{"claim": "X is Y", "importance": 5}]',
        input_tokens=10,
        output_tokens=5,
    )
    client.generate = AsyncMock(return_value=fake_result)

    facts = await extract_atomic_facts(
        client=client,
        source_text="...",
        cache_root=tmp_path,
        url="https://a.com",
        ingestor_version="1.0.0",
    )

    assert facts == [{"claim": "X is Y", "importance": 5}]


@pytest.mark.asyncio
async def test_extract_atomic_facts_cache_hit(tmp_path: Path):
    client = MagicMock()
    client.generate = AsyncMock()

    from website.features.summarization_engine.core.cache import FsContentCache

    cache = FsContentCache(root=tmp_path, namespace="atomic_facts")

    cache.put(
        ("https://a.com", "1.0.0", PROMPT_VERSION),
        {"facts": [{"claim": "cached", "importance": 3}]},
    )

    facts = await extract_atomic_facts(
        client=client,
        source_text="...",
        cache_root=tmp_path,
        url="https://a.com",
        ingestor_version="1.0.0",
    )

    assert facts == [{"claim": "cached", "importance": 3}]
    client.generate.assert_not_called()


@pytest.mark.asyncio
async def test_fenced_array_response_is_parsed(tmp_path: Path):
    client = MagicMock()
    fake_result = MagicMock(
        text='```json\n[{"claim": "fenced array", "importance": 4}]\n```',
    )
    client.generate = AsyncMock(return_value=fake_result)

    facts = await extract_atomic_facts(
        client=client,
        source_text="src",
        cache_root=tmp_path,
        url="https://a.com",
        ingestor_version="1.0.0",
    )

    assert facts == [{"claim": "fenced array", "importance": 4}]


@pytest.mark.asyncio
async def test_fenced_object_with_facts_is_parsed(tmp_path: Path):
    client = MagicMock()
    fake_result = MagicMock(
        text='```json\n{"facts": [{"claim": "fenced obj", "importance": 2}]}\n```',
    )
    client.generate = AsyncMock(return_value=fake_result)

    facts = await extract_atomic_facts(
        client=client,
        source_text="src",
        cache_root=tmp_path,
        url="https://a.com",
        ingestor_version="1.0.0",
    )

    assert facts == [{"claim": "fenced obj", "importance": 2}]


@pytest.mark.asyncio
async def test_malformed_json_degrades_to_empty_facts(tmp_path: Path):
    client = MagicMock()
    fake_result = MagicMock(text="this is not json at all <<<>>>")
    client.generate = AsyncMock(return_value=fake_result)

    facts = await extract_atomic_facts(
        client=client,
        source_text="src",
        cache_root=tmp_path,
        url="https://a.com",
        ingestor_version="1.0.0",
    )

    assert facts == []
    assert client.generate.await_count == 2


@pytest.mark.asyncio
async def test_empty_result_is_not_cached(tmp_path: Path):
    client = MagicMock()
    # Both calls return an empty array.
    empty_result = MagicMock(text="[]")
    good_result = MagicMock(text='[{"claim": "ok", "importance": 1}]')
    client.generate = AsyncMock(side_effect=[empty_result, good_result])

    facts1 = await extract_atomic_facts(
        client=client,
        source_text="src",
        cache_root=tmp_path,
        url="https://a.com",
        ingestor_version="1.0.0",
    )
    assert facts1 == []

    # Second call must hit the LLM again because the empty result wasn't cached.
    facts2 = await extract_atomic_facts(
        client=client,
        source_text="src",
        cache_root=tmp_path,
        url="https://a.com",
        ingestor_version="1.0.0",
    )
    assert facts2 == [{"claim": "ok", "importance": 1}]
    assert client.generate.await_count == 2


def test_prompt_version_is_v7():
    # Bumped from v6 -> v7 in CF-3 (R3): verbatim-verify-before-flagging clause
    # for invented_number / contradicted_sentence — paired with the deterministic
    # post-judge FP filter in ops.scripts.lib.phases.filter_judge_false_positives.
    assert PROMPT_VERSION == "evaluator.v7"


# --- Truncation repair (iter-001-baseline regression: DMT YouTube zettel) ---


def test_repair_truncated_array_salvages_complete_objects():
    """Regression: max_output_tokens cut JSON array mid-string inside the last
    object (observed iter-001-baseline 2026-05-28 on the DMT YouTube zettel,
    error="Unterminated string starting at: line 119 column 14 (char 4759)").
    Repair must snip at last complete `}` and close the array.
    """
    from website.features.summarization_engine.evaluator.atomic_facts import (
        _repair_truncated_json_array,
    )

    truncated = (
        '[\n'
        '  {"claim": "first complete fact", "importance": 5},\n'
        '  {"claim": "second complete fact", "importance": 4},\n'
        '  {"claim": "third was cut mid-stri'
    )
    out = _repair_truncated_json_array(truncated)
    assert out is not None
    assert len(out) == 2
    assert out[0]["claim"] == "first complete fact"
    assert out[1]["claim"] == "second complete fact"


def test_repair_truncated_array_returns_none_on_non_array():
    from website.features.summarization_engine.evaluator.atomic_facts import (
        _repair_truncated_json_array,
    )
    assert _repair_truncated_json_array('{"key": "value"}') is None
    assert _repair_truncated_json_array("garbage") is None
    assert _repair_truncated_json_array("") is None


def test_repair_truncated_array_returns_none_when_no_complete_object():
    from website.features.summarization_engine.evaluator.atomic_facts import (
        _repair_truncated_json_array,
    )
    # Array opened but first object never closed
    truncated = '[\n  {"claim": "cut before close'
    assert _repair_truncated_json_array(truncated) is None


def test_repair_handles_escaped_quotes_and_braces_in_strings():
    """Brace-depth tracker must respect string boundaries — a `}` inside a JSON
    string literal must NOT decrement depth. Escaped `\\"` must not toggle
    in_string. Both bugs would cause premature truncation."""
    from website.features.summarization_engine.evaluator.atomic_facts import (
        _repair_truncated_json_array,
    )
    truncated = (
        '[\n'
        '  {"claim": "value with \\"escaped quotes\\" and {brace} chars", "importance": 5},\n'
        '  {"claim": "another fact", "importance": 4},\n'
        '  {"claim": "truncat'
    )
    out = _repair_truncated_json_array(truncated)
    assert out is not None
    assert len(out) == 2
    assert "escaped quotes" in out[0]["claim"]
    assert "{brace}" in out[0]["claim"]


def test_parse_facts_uses_repair_on_truncated_array():
    """_parse_facts must transparently recover via repair when stdlib json.loads
    fails on a truncated array — the recovered list propagates to the caller.

    Updated 2026-05-29 (Fix #1): json_repair (mangiucugna/json_repair) is now
    the primary repair layer. It is MORE aggressive than the hand-rolled
    array-snip and can recover the truncated final object too (filling in
    missing trailing braces). Assertion accepts >=2 to support BOTH paths
    cleanly — see ``test_parse_facts_falls_back_to_hand_rolled_when_json_repair_unavailable``
    for the exact hand-rolled assertion."""
    from website.features.summarization_engine.evaluator.atomic_facts import _parse_facts

    truncated = (
        '```json\n[\n'
        '  {"claim": "first", "importance": 5},\n'
        '  {"claim": "second", "importance": 4},\n'
        '  {"claim": "third cut here'
    )
    out = _parse_facts(truncated)
    assert isinstance(out, list)
    # At minimum the two complete objects survive; json_repair recovers a third
    # (filling the truncated string) — both behaviors are valid.
    assert len(out) >= 2
    assert out[0]["claim"] == "first"
    assert out[1]["claim"] == "second"


def test_parse_facts_falls_back_to_hand_rolled_when_json_repair_unavailable(monkeypatch):
    """Regression: if json_repair isn't installed (or import failed), the
    hand-rolled ``_repair_truncated_json_array`` must still salvage the 2
    complete objects. Monkeypatches the module-level _json_repair_loads to None
    to simulate the missing-dep environment."""
    from website.features.summarization_engine.evaluator import atomic_facts as af

    monkeypatch.setattr(af, "_json_repair_loads", None)
    truncated = (
        '```json\n[\n'
        '  {"claim": "first", "importance": 5},\n'
        '  {"claim": "second", "importance": 4},\n'
        '  {"claim": "third cut here'
    )
    out = af._parse_facts(truncated)
    assert isinstance(out, list)
    assert len(out) == 2  # hand-rolled snips at last complete `}`
    assert out[0]["claim"] == "first"
    assert out[1]["claim"] == "second"


def test_parse_facts_raises_on_unrepairable_garbage(monkeypatch):
    """If both repair layers cannot salvage anything, the original
    JSONDecodeError must propagate so the caller's retry-with-brevity path
    can engage. Strip json_repair to force the original error path —
    json_repair is permissive enough to coerce 'not json at all' to a string
    rather than raising, which would mask the retry contract."""
    import json as _json
    import pytest
    from website.features.summarization_engine.evaluator import atomic_facts as af

    monkeypatch.setattr(af, "_json_repair_loads", None)
    with pytest.raises(_json.JSONDecodeError):
        af._parse_facts("not json at all <<<>>>")


# ---------------------------------------------------------------------------
# Fix #1 (2026-05-29) — call-site behavior: max_output_tokens + json_mime on
# attempt 1, finish_reason check, brevity retry.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_extract_atomic_facts_first_attempt_uses_16k_tokens_and_json_mime(
    tmp_path: Path,
):
    """Lane 1 root-cause fix: the FIRST Gemini call must specify both
    ``max_output_tokens=16384`` AND ``response_mime_type='application/json'``.
    Previously json_mime was only on the RETRY attempt — by then the model
    had already truncated mid-string (the DMT failure mode 2026-05-28)."""
    client = MagicMock()
    fake_result = MagicMock(
        text='[{"claim": "ok", "importance": 1}]',
        input_tokens=10, output_tokens=8,
    )
    client.generate = AsyncMock(return_value=fake_result)

    await extract_atomic_facts(
        client=client, source_text="src", cache_root=tmp_path,
        url="https://example.com/a", ingestor_version="1.0.0",
    )

    # The FIRST call's kwargs must contain both knobs simultaneously.
    first_call_kwargs = client.generate.await_args_list[0].kwargs
    assert first_call_kwargs.get("max_output_tokens") == 16384
    assert first_call_kwargs.get("response_mime_type") == "application/json"
    assert first_call_kwargs.get("tier") == "flash"
    assert first_call_kwargs.get("role") == "atomic_facts"


@pytest.mark.asyncio
async def test_extract_atomic_facts_logs_warning_on_max_tokens_finish_reason(
    tmp_path: Path, caplog,
):
    """If the Gemini response carries ``finish_reason='MAX_TOKENS'``, log a
    warning so an operator can spot the truncation pattern in iter telemetry."""
    import logging
    client = MagicMock()
    fake_result = MagicMock(
        text='[{"claim": "partial", "importance": 1}]',
        input_tokens=10, output_tokens=16384,
        finish_reason="MAX_TOKENS",
    )
    client.generate = AsyncMock(return_value=fake_result)

    with caplog.at_level(logging.WARNING,
                          logger="website.features.summarization_engine.evaluator.atomic_facts"):
        await extract_atomic_facts(
            client=client, source_text="src", cache_root=tmp_path,
            url="https://example.com/b", ingestor_version="1.0.0",
        )

    assert any(
        "max_tokens_hit" in rec.message for rec in caplog.records
    ), f"expected max_tokens_hit warning; got: {[r.message for r in caplog.records]}"


@pytest.mark.asyncio
async def test_extract_atomic_facts_retry_uses_brevity_directive(tmp_path: Path):
    """When the first call's output cannot be parsed AND repair fails, the
    retry must send a brevity-directive-augmented prompt (Lane 1 recommendation)
    rather than blindly re-running with the same prompt."""
    from website.features.summarization_engine.evaluator import atomic_facts as af

    # First call → unparseable garbage (after repair layers); second call → ok
    bad_result = MagicMock(text="totally unparseable garbage <<<>>>", finish_reason=None)
    good_result = MagicMock(
        text='[{"claim": "brief", "importance": 2}]',
        input_tokens=12, output_tokens=8, finish_reason=None,
    )
    client = MagicMock()
    client.generate = AsyncMock(side_effect=[bad_result, good_result])

    # Force the hand-rolled repair to fail so the parse error bubbles up
    # and triggers the retry. (json_repair would otherwise coerce the garbage
    # to a string, hiding the retry contract.)
    import unittest.mock as _m
    with _m.patch.object(af, "_json_repair_loads", None):
        out = await extract_atomic_facts(
            client=client, source_text="src", cache_root=tmp_path,
            url="https://example.com/c", ingestor_version="1.0.0",
        )

    assert out == [{"claim": "brief", "importance": 2}]
    assert client.generate.await_count == 2
    # Second call (the retry) must include the brevity-directive suffix.
    # Updated 2026-05-30 (review #2): Instructor-style — explain the retry
    # reason in the reprompt; drop max_output_tokens to 4096 to match the
    # directive (instead of leaving it at 16k which would be a mixed signal).
    second_prompt = client.generate.await_args_list[1].args[0]
    assert "previous response was unparseable" in second_prompt
    assert "at most 15 fact objects" in second_prompt
    second_kwargs = client.generate.await_args_list[1].kwargs
    assert second_kwargs.get("max_output_tokens") == 4096
    assert second_kwargs.get("response_mime_type") == "application/json"


@pytest.mark.asyncio
async def test_dmt_class_failure_max_tokens_plus_truncation_salvaged(tmp_path: Path, caplog):
    """The canonical DMT-class failure mode (2026-05-28 wz=628789b4):
    Gemini returns ``finish_reason=MAX_TOKENS`` AND text truncated mid-string
    in the last array object. The json_repair layer must salvage the complete
    objects, the MAX_TOKENS warning must log, and NO retry should fire
    (we have usable data — retrying would be wasteful API spend)."""
    import logging
    truncated_dmt = (
        '[\n  {"claim": "fact A about DMT", "importance": 5},\n'
        '  {"claim": "fact B about DMT", "importance": 4},\n'
        '  {"claim": "fact C truncated mid-stri'
    )
    fake = MagicMock(
        text=truncated_dmt,
        input_tokens=2000, output_tokens=16384,
        finish_reason="MAX_TOKENS",
    )
    client = MagicMock()
    client.generate = AsyncMock(return_value=fake)

    with caplog.at_level(
        logging.WARNING,
        logger="website.features.summarization_engine.evaluator.atomic_facts",
    ):
        facts = await extract_atomic_facts(
            client=client, source_text="dmt content " * 1000, cache_root=tmp_path,
            url="https://www.youtube.com/watch?v=hhjhU5MXZOo",
            ingestor_version="1.0.0",
        )

    # At minimum the two complete objects survive (json_repair recovers more)
    assert len(facts) >= 2
    assert facts[0]["claim"] == "fact A about DMT"
    assert facts[1]["claim"] == "fact B about DMT"
    # MAX_TOKENS warning fired (the dead-code blocker from review)
    assert any("max_tokens_hit" in r.message for r in caplog.records), (
        f"expected max_tokens_hit warning; got: {[r.message for r in caplog.records]}"
    )
    # Crucially: NO retry. json_repair salvaged enough → don't burn API spend.
    assert client.generate.await_count == 1


def test_generate_result_exposes_finish_reason_field():
    """Blocking #1 from Fix #1 review (2026-05-30): GenerateResult must
    actually expose finish_reason so the atomic_facts warning isn't dead
    code. Verifies the field exists on the dataclass with a None default."""
    from website.features.summarization_engine.core.gemini_client import GenerateResult
    r = GenerateResult(
        text="x", model_used="m", input_tokens=0, output_tokens=0,
    )
    # Default must be None (backward-compat with callers that don't set it)
    assert r.finish_reason is None
    # Explicit value flows through
    r2 = GenerateResult(
        text="x", model_used="m", input_tokens=0, output_tokens=0,
        finish_reason="MAX_TOKENS",
    )
    assert r2.finish_reason == "MAX_TOKENS"


def test_extract_finish_reason_helper_normalizes_sdk_shapes():
    """The helper must accept either the enum-style response (SDK canonical)
    or a missing-attribute response (older / mocked) and produce a string
    or None — never raise."""
    from unittest.mock import MagicMock
    from website.features.summarization_engine.core.gemini_client import _extract_finish_reason

    # SDK canonical: response.candidates[0].finish_reason is an enum-like with .name
    enum_like = MagicMock()
    enum_like.name = "MAX_TOKENS"
    candidate = MagicMock()
    candidate.finish_reason = enum_like
    resp = MagicMock()
    resp.candidates = [candidate]
    assert _extract_finish_reason(resp) == "MAX_TOKENS"

    # Plain-string finish_reason (no enum wrapping): helper must coerce
    # via str() since the str class has no usable .name attribute.
    candidate2 = MagicMock()
    candidate2.finish_reason = "STOP"
    resp2 = MagicMock()
    resp2.candidates = [candidate2]
    assert _extract_finish_reason(resp2) == "STOP"

    # No candidates → None
    resp3 = MagicMock()
    resp3.candidates = []
    assert _extract_finish_reason(resp3) is None

    # No candidates attribute at all → None
    class _Bare:
        pass
    assert _extract_finish_reason(_Bare()) is None


@pytest.mark.asyncio
async def test_extract_atomic_facts_typeerror_fallback_preserves_token_cap(
    tmp_path: Path,
):
    """Backward-compat: if the underlying client mock doesn't accept the new
    response_mime_type kwarg (TypeError), we must still preserve the
    ``max_output_tokens=16384`` cap on the retried call — the perf fix
    should not regress when running against older test mocks."""
    client = MagicMock()
    call_count = {"n": 0}

    async def _generate(*args, **kwargs):
        call_count["n"] += 1
        # First call: include response_mime_type → reject with TypeError
        if "response_mime_type" in kwargs:
            raise TypeError("client does not accept response_mime_type")
        # Second call: should still have max_output_tokens
        return MagicMock(
            text='[{"claim": "ok"}]', input_tokens=1, output_tokens=1,
        )

    client.generate = AsyncMock(side_effect=_generate)

    facts = await extract_atomic_facts(
        client=client, source_text="src", cache_root=tmp_path,
        url="https://example.com/d", ingestor_version="1.0.0",
    )

    assert facts == [{"claim": "ok"}]
    # Two calls total: first failed with TypeError, second succeeded
    assert call_count["n"] == 2
    # The second call (the successful one) must STILL have the 16k cap
    second_kwargs = client.generate.await_args_list[1].kwargs
    assert second_kwargs.get("max_output_tokens") == 16384
