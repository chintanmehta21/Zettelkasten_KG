"""M4 — Natural-Language Graph Query via Gemini text-to-SQL.

Translates plain-English questions about the knowledge graph into SQL,
executes them against Supabase via RPC, and formats human-readable answers.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time

from pydantic import BaseModel, Field

from website.features.api_key_switching import get_key_pool

logger = logging.getLogger(__name__)


# ── Models ──────────────────────────────────────────────────────────────────

class NLQueryResult(BaseModel):
    """Result returned from a natural-language graph query."""
    question: str
    sql: str
    raw_result: list[dict] = Field(default_factory=list)
    answer: str = ""
    latency_ms: float = 0.0
    retries: int = 0


class NLQueryError(Exception):
    """Raised when a query cannot be fulfilled."""

    def __init__(self, status_code: int, user_message: str) -> None:
        self.status_code = status_code
        self.user_message = user_message
        super().__init__(user_message)


# ── Prompts ─────────────────────────────────────────────────────────────────

_SYSTEM_PROMPT = """\
You are a SQL expert.  Given a natural-language question about a
knowledge graph stored in Supabase (PostgreSQL), generate a single
SELECT query that answers it.

SCHEMA:
  public.kg_nodes (
    id          text PRIMARY KEY,
    user_id     uuid NOT NULL,
    name        text NOT NULL,
    source_type text NOT NULL,   -- enum: 'youtube', 'github', 'reddit', 'substack', 'medium', 'web'
    summary     text,
    tags        text[],          -- PostgreSQL array of tags
    url         text NOT NULL,
    node_date   date,
    metadata    jsonb DEFAULT '{}',
    embedding   vector(768),
    created_at  timestamptz DEFAULT now(),
    updated_at  timestamptz DEFAULT now()
  )

  public.kg_links (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         uuid NOT NULL,
    source_node_id  text NOT NULL REFERENCES public.kg_nodes(id),
    target_node_id  text NOT NULL REFERENCES public.kg_nodes(id),
    relation        text NOT NULL,
    created_at      timestamptz DEFAULT now()
  )

  public.kg_users (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    render_user_id  text UNIQUE NOT NULL,
    display_name    text,
    email           text,
    avatar_url      text,
    is_active       boolean DEFAULT true,
    created_at      timestamptz DEFAULT now(),
    updated_at      timestamptz DEFAULT now()
  )

DOMAIN VOCABULARY:
  source_type values: youtube, github, reddit, substack, medium, web
  Common tag patterns: lowercase, hyphenated (e.g. 'machine-learning')
  relation examples: shared_tag, semantic_similarity

RULES:
  1. ALWAYS filter by user_id = '{user_id}' for data isolation.
  2. ALWAYS prefix tables with public. (e.g. public.kg_nodes).
  3. ALWAYS add LIMIT 50 to prevent unbounded result sets.
  4. Return ONLY the raw SQL — no markdown, no explanation.
  5. Never use INSERT, UPDATE, DELETE, DROP, ALTER, CREATE, or TRUNCATE.
  6. Use unnest(tags) when filtering or grouping by individual tags.
"""

_ANSWER_PROMPT = """\
The user asked: "{question}"

The SQL query returned these results (JSON):
{results}

Write a concise, helpful answer in natural language.  Refer to specific
node names and data points where relevant.  If the result set is empty,
say so clearly.
"""

_COMMON_MISTAKES = """\
COMMON MISTAKES (avoid these):
- Using tags @> ARRAY['x'] instead of unnest(tags) for single tag checks
- Forgetting public. prefix on table names
- Missing WHERE user_id = '{user_id}'
- Using ILIKE on array columns — unnest first

The previous query failed with this error:
{error}

Original question: "{question}"

Generate a corrected SELECT query.  Return ONLY raw SQL.
"""


# ── Helpers ─────────────────────────────────────────────────────────────────

_SQL_FENCE_RE = re.compile(r"```(?:sql)?\s*\n?(.*?)\n?\s*```", re.DOTALL)
_SELECT_ONLY_RE = re.compile(r"^\s*SELECT\b", re.IGNORECASE)


def _strip_sql_artifacts(text: str) -> str:
    """Remove markdown code fences and leading/trailing whitespace."""
    match = _SQL_FENCE_RE.search(text)
    if match:
        return match.group(1).strip()
    return text.strip()


def _safety_check(sql: str) -> None:
    """Raise :class:`NLQueryError` if the SQL is not a pure SELECT statement."""
    stripped = sql.strip().rstrip(";").strip()
    if not _SELECT_ONLY_RE.match(stripped):
        raise NLQueryError(400, "Only SELECT queries are allowed.")
    # Reject multiple statements.
    if ";" in stripped:
        raise NLQueryError(400, "Multiple SQL statements are not allowed.")


# ── Query engine ────────────────────────────────────────────────────────────

class NLGraphQuery:
    """Natural-language query engine over the Supabase knowledge graph."""

    def __init__(self, supabase_client, user_id: str, model: str = "gemini-2.5-flash") -> None:
        self._sb = supabase_client
        self._user_id = user_id
        self._model = model

    async def ask(
        self,
        question: str,
        user_id: str | None = None,
    ) -> NLQueryResult:
        """Translate *question* to SQL, execute, and format an answer.

        Raises :class:`NLQueryError` on safety violations or timeouts.
        """
        start = time.monotonic()
        pool = get_key_pool()
        model = self._model
        retries = 0
        # Backwards-compat: allow user_id override, otherwise use instance value.
        effective_user_id = str(user_id) if user_id is not None else str(self._user_id)

        try:
            # ── 1. Generate SQL ─────────────────────────────────────────
            system = _SYSTEM_PROMPT.replace("{user_id}", effective_user_id)
            sql_response, _, _ = await asyncio.wait_for(
                pool.generate_content(
                    question,
                    config={"system_instruction": system},
                    starting_model=model,
                    label="NL query SQL",
                ),
                timeout=10.0,
            )
            sql_raw = sql_response.text

            sql = _strip_sql_artifacts(sql_raw)
            _safety_check(sql)

            # ── 2. EXPLAIN pre-validation + execute ─────────────────────
            last_error: str | None = None
            raw_result: list[dict] = []

            # Cheap ~1ms sanity check; returns {"ok": true, "plan": ...} or
            # {"ok": false, "error": "..."}.
            explain_err = None
            try:
                explain_resp = self._sb.rpc(
                    "explain_kg_query",
                    {"query_text": sql, "p_user_id": effective_user_id},
                ).execute()
                explain_data = explain_resp.data
                if isinstance(explain_data, dict) and not explain_data.get("ok"):
                    explain_err = explain_data.get("error", "EXPLAIN validation failed")
            except Exception as explain_exc:
                explain_err = str(explain_exc)

            if explain_err:
                last_error = str(explain_err)
                logger.info("EXPLAIN validation failed, will retry: %s", last_error)
            else:
                try:
                    response = self._sb.rpc(
                        "execute_kg_query",
                        {"query_text": sql, "p_user_id": effective_user_id},
                    ).execute()
                    raw_result = response.data or []
                except Exception as db_exc:
                    last_error = str(db_exc)

            if last_error is not None:
                # ── 3. Guided retry (max 1 total) ───────────────────────
                retries = 1
                retry_prompt = _COMMON_MISTAKES.format(
                    error=last_error,
                    question=question,
                    user_id=effective_user_id,
                )
                retry_system = _SYSTEM_PROMPT.replace("{user_id}", effective_user_id)
                sql_response2, _, _ = await asyncio.wait_for(
                    pool.generate_content(
                        retry_prompt,
                        config={"system_instruction": retry_system},
                        starting_model=model,
                        label="NL query retry",
                    ),
                    timeout=10.0,
                )
                sql = _strip_sql_artifacts(sql_response2.text)
                _safety_check(sql)

                # Execute directly (no second EXPLAIN — 1 retry total per spec).
                response = self._sb.rpc(
                    "execute_kg_query",
                    {"query_text": sql, "p_user_id": effective_user_id},
                ).execute()
                raw_result = response.data or []

            # Cap results Python-side.
            raw_result = raw_result[:50]

            # ── 4. Format answer ────────────────────────────────────────
            answer_response, _, _ = await asyncio.wait_for(
                pool.generate_content(
                    _ANSWER_PROMPT.format(
                        question=question,
                        results=json.dumps(raw_result, default=str)[:4000],
                    ),
                    starting_model=model,
                    label="NL query answer",
                ),
                timeout=10.0,
            )
            answer_text = answer_response.text.strip()

            elapsed = (time.monotonic() - start) * 1000
            return NLQueryResult(
                question=question,
                sql=sql,
                raw_result=raw_result,
                answer=answer_text.strip(),
                latency_ms=round(elapsed, 1),
                retries=retries,
            )

        except NLQueryError:
            raise
        except asyncio.TimeoutError:
            raise NLQueryError(504, "Query timed out. Please try a simpler question.")
        except Exception as exc:
            logger.error("NL query execution failed: %s", exc)
            raise NLQueryError(500, "Query execution failed. Please rephrase and try again.") from exc
