"""M4 — Natural-Language Graph Query via Gemini text-to-SQL.

Translates plain-English questions about the knowledge graph into SQL,
executes them against Supabase via RPC, and formats human-readable answers.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from functools import lru_cache

from google import genai
from pydantic import BaseModel, Field

from telegram_bot.config.settings import get_settings

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


# ── Client ──────────────────────────────────────────────────────────────────

@lru_cache(maxsize=1)
def _get_genai_client() -> genai.Client:
    """Return a cached google-genai Client."""
    settings = get_settings()
    return genai.Client(api_key=settings.gemini_api_key)


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
    source_type text NOT NULL,   -- enum: 'youtube', 'github', 'reddit', 'newsletter', 'generic'
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
  source_type values: youtube, github, reddit, newsletter, generic
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
_UNSAFE_RE = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|TRUNCATE|GRANT|REVOKE)\b",
    re.IGNORECASE,
)


def _strip_sql_artifacts(text: str) -> str:
    """Remove markdown code fences and leading/trailing whitespace."""
    match = _SQL_FENCE_RE.search(text)
    if match:
        return match.group(1).strip()
    return text.strip()


def _safety_check(sql: str) -> None:
    """Raise :class:`NLQueryError` if the SQL is not a pure SELECT.

    Rejects statements containing mutation keywords and multiple
    statements (semicolons).
    """
    if _UNSAFE_RE.search(sql):
        raise NLQueryError(400, "Only SELECT queries are allowed.")
    # Reject multiple statements.
    if ";" in sql.rstrip(";").strip():
        raise NLQueryError(400, "Multiple SQL statements are not allowed.")


# ── Query engine ────────────────────────────────────────────────────────────

class NLGraphQuery:
    """Natural-language query engine over the Supabase knowledge graph."""

    def __init__(self, supabase_client) -> None:
        self._sb = supabase_client

    async def ask(
        self,
        question: str,
        user_id: str,
    ) -> NLQueryResult:
        """Translate *question* to SQL, execute, and format an answer.

        Raises :class:`NLQueryError` on safety violations or timeouts.
        """
        start = time.monotonic()
        client = _get_genai_client()
        model = "gemini-2.5-flash"
        retries = 0

        try:
            # ── 1. Generate SQL ─────────────────────────────────────────
            system = _SYSTEM_PROMPT.replace("{user_id}", user_id)
            sql_raw = await asyncio.wait_for(
                asyncio.to_thread(
                    lambda: client.models.generate_content(
                        model=model,
                        contents=question,
                        config={"system_instruction": system},
                    ).text
                ),
                timeout=10.0,
            )

            sql = _strip_sql_artifacts(sql_raw)
            _safety_check(sql)

            # ── 2. Execute SQL via RPC ──────────────────────────────────
            try:
                response = self._sb.rpc(
                    "execute_kg_query",
                    {"query_text": sql},
                ).execute()
                raw_result = response.data or []
            except Exception as db_exc:
                # ── 3. Guided retry on DB error ─────────────────────────
                retries = 1
                retry_prompt = _COMMON_MISTAKES.format(
                    error=str(db_exc),
                    question=question,
                    user_id=user_id,
                )
                retry_system = _SYSTEM_PROMPT.replace("{user_id}", user_id)
                sql_raw2 = await asyncio.wait_for(
                    asyncio.to_thread(
                        lambda: client.models.generate_content(
                            model=model,
                            contents=retry_prompt,
                            config={"system_instruction": retry_system},
                        ).text
                    ),
                    timeout=10.0,
                )
                sql = _strip_sql_artifacts(sql_raw2)
                _safety_check(sql)

                response = self._sb.rpc(
                    "execute_kg_query",
                    {"query_text": sql},
                ).execute()
                raw_result = response.data or []

            # Cap results Python-side.
            raw_result = raw_result[:50]

            # ── 4. Format answer ────────────────────────────────────────
            import json
            answer_text = await asyncio.wait_for(
                asyncio.to_thread(
                    lambda: client.models.generate_content(
                        model=model,
                        contents=_ANSWER_PROMPT.format(
                            question=question,
                            results=json.dumps(raw_result, default=str)[:4000],
                        ),
                    ).text
                ),
                timeout=10.0,
            )

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
            logger.error("NL query failed: %s", exc)
            raise NLQueryError(500, f"Query failed: {exc}") from exc
