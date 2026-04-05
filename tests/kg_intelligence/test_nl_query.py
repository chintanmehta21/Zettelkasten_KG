"""M4 — Natural-Language Graph Query tests.

Covers:
- Safety check rejects mutation keywords.
- Safety check rejects multi-statement SQL.
- Artifact stripper removes markdown fences.
- Happy-path: mock Gemini + mock Supabase → NLQueryResult.
- Retry on first DB error.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from website.features.kg_features import nl_query as nl_mod
from website.features.kg_features.nl_query import (
    NLGraphQuery,
    NLQueryError,
    NLQueryResult,
    _safety_check,
    _strip_sql_artifacts,
)


# ── Test 1 ───────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("sql", [
    "DELETE FROM kg_nodes WHERE user_id = 'x'",
    "INSERT INTO kg_nodes VALUES (1)",
    "UPDATE kg_nodes SET name='x'",
    "DROP TABLE kg_nodes",
])
def test_safety_check_blocks_mutation_keywords(sql):
    """All mutation SQL statements must raise NLQueryError(400)."""
    with pytest.raises(NLQueryError) as exc_info:
        _safety_check(sql)
    assert exc_info.value.status_code == 400


# ── Test 2 ───────────────────────────────────────────────────────────────────

def test_safety_check_blocks_multiple_statements():
    """Multi-statement SQL must raise NLQueryError(400)."""
    with pytest.raises(NLQueryError) as exc_info:
        _safety_check("SELECT 1; SELECT 2")
    assert exc_info.value.status_code == 400


# ── Test 3 ───────────────────────────────────────────────────────────────────

def test_strip_sql_artifacts_removes_markdown_fences():
    """Markdown code fences with or without 'sql' lang tag must be stripped."""
    wrapped = "```sql\nSELECT * FROM public.kg_nodes LIMIT 50\n```"
    assert _strip_sql_artifacts(wrapped) == "SELECT * FROM public.kg_nodes LIMIT 50"

    wrapped_no_lang = "```\nSELECT 1\n```"
    assert _strip_sql_artifacts(wrapped_no_lang) == "SELECT 1"

    plain = "SELECT * FROM public.kg_nodes"
    assert _strip_sql_artifacts(plain) == "SELECT * FROM public.kg_nodes"


# ── Test 4 ───────────────────────────────────────────────────────────────────

async def test_nl_query_happy_path(stub_settings, mock_supabase_client):
    """Valid SELECT → SQL executes → result formatted → NLQueryResult returned."""
    # Gemini returns: (1) the SQL, (2) the formatted answer.
    sql_resp = MagicMock()
    sql_resp.text = "SELECT name FROM public.kg_nodes WHERE user_id='u' LIMIT 50"
    answer_resp = MagicMock()
    answer_resp.text = "You have 2 articles: Alpha, Beta."

    fake_client = MagicMock()
    fake_client.models.generate_content.side_effect = [sql_resp, answer_resp]

    # EXPLAIN returns NULL (success), execute returns rows.
    explain_resp = MagicMock()
    explain_resp.data = None
    exec_resp = MagicMock()
    exec_resp.data = [{"name": "Alpha"}, {"name": "Beta"}]
    execute_mock = MagicMock(side_effect=[explain_resp, exec_resp])
    rpc_handle = MagicMock()
    rpc_handle.execute = execute_mock
    mock_supabase_client.rpc.return_value = rpc_handle

    with patch.object(nl_mod, "_get_genai_client", return_value=fake_client), \
         patch.object(nl_mod, "get_settings", return_value=stub_settings):
        engine = NLGraphQuery(mock_supabase_client, user_id="u")
        result = await engine.ask("How many articles do I have?", user_id="u")

    assert isinstance(result, NLQueryResult)
    assert "SELECT" in result.sql.upper()
    assert len(result.raw_result) == 2
    assert result.retries == 0
    assert result.latency_ms >= 0  # timing present (may round to 0 with mocks)
    assert result.answer  # non-empty


# ── Test 5 ───────────────────────────────────────────────────────────────────

async def test_nl_query_retry_on_db_error(stub_settings):
    """First RPC raises, retry succeeds → retries == 1."""
    sql_resp_1 = MagicMock()
    sql_resp_1.text = "SELECT bad_column FROM public.kg_nodes LIMIT 50"
    sql_resp_2 = MagicMock()
    sql_resp_2.text = "SELECT name FROM public.kg_nodes LIMIT 50"
    answer_resp = MagicMock()
    answer_resp.text = "Here are your nodes."

    fake_client = MagicMock()
    fake_client.models.generate_content.side_effect = [
        sql_resp_1, sql_resp_2, answer_resp,
    ]

    # First rpc execute raises; second returns data.
    good_resp = MagicMock()
    good_resp.data = [{"name": "Alpha"}]

    sb = MagicMock()
    # Each .rpc() call creates a new chain call, so we can configure them
    # sequentially via side_effect on execute.
    execute_mock = MagicMock()
    execute_mock.side_effect = [Exception("column bad_column does not exist"), good_resp]
    rpc_handle = MagicMock()
    rpc_handle.execute = execute_mock
    sb.rpc.return_value = rpc_handle

    with patch.object(nl_mod, "_get_genai_client", return_value=fake_client), \
         patch.object(nl_mod, "get_settings", return_value=stub_settings):
        engine = NLGraphQuery(sb, user_id="u")
        result = await engine.ask("list my notes", user_id="u")

    assert result.retries == 1
    assert len(result.raw_result) == 1
