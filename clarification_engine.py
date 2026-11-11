"""
Phase 2 — Clarification Engine
================================
Core LLM pipeline that:
  1. Extracts the live schema from the SQLite database.
  2. Builds a system prompt embedding that schema.
  3. Sends the user's question (+ any prior conversation turns) to the LLM.
  4. Parses the response into a validated Pydantic ``LLMResponse``.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from openai import OpenAI

from config import API_KEY, BASE_URL, LLM_MODEL, LLM_PROVIDER
from models import LLMResponse

# ── Lazy client — initialised on first call so importing this
#    module without an API key (e.g. for tests) doesn't crash. ─
_client: OpenAI | None = None


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(api_key=API_KEY, base_url=BASE_URL)
    return _client


# ───────────────────────────────────────────────────────────
#  Schema Extraction
# ───────────────────────────────────────────────────────────

def extract_schema(db_path: str) -> str:
    """Return a human-readable description of every table, column,
    type, constraint, and foreign-key in the SQLite database.

    The output is designed to be pasted straight into a system prompt
    so the LLM understands the data model.
    """
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    # Get all user tables
    cur.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
    )
    tables = [row[0] for row in cur.fetchall()]

    parts: list[str] = []

    for table in tables:
        # Column info
        cur.execute(f"PRAGMA table_info('{table}')")
        columns = cur.fetchall()  # (cid, name, type, notnull, dflt_value, pk)

        # Foreign keys
        cur.execute(f"PRAGMA foreign_key_list('{table}')")
        fks = cur.fetchall()  # (id, seq, table, from, to, ...)

        fk_map: dict[str, str] = {}
        for fk in fks:
            fk_map[fk[3]] = f"→ {fk[2]}.{fk[4]}"

        lines = [f"TABLE: {table}"]
        lines.append("-" * (len(lines[0]) + 2))
        for col in columns:
            _, name, dtype, notnull, default, pk = col
            flags: list[str] = []
            if pk:
                flags.append("PRIMARY KEY")
            if notnull and not pk:
                flags.append("NOT NULL")
            if default is not None:
                flags.append(f"DEFAULT {default}")
            if name in fk_map:
                flags.append(f"FK {fk_map[name]}")
            flag_str = f"  [{', '.join(flags)}]" if flags else ""
            lines.append(f"  {name:<20s} {dtype or 'TEXT':<12s}{flag_str}")

        # Check constraints (show allowed values for status / method cols)
        cur.execute(
            f"SELECT sql FROM sqlite_master WHERE type='table' AND name='{table}'"
        )
        create_sql = cur.fetchone()[0]
        if "CHECK" in create_sql.upper():
            lines.append(f"  -- CHECK constraints present (see DDL)")

        # Row count
        cur.execute(f"SELECT COUNT(*) FROM {table}")
        count = cur.fetchone()[0]
        lines.append(f"  ({count} rows)")

        parts.append("\n".join(lines))

    # Also include the raw CREATE TABLE DDL for precision
    ddl_parts: list[str] = ["-- Raw DDL for reference:"]
    for table in tables:
        cur.execute(
            f"SELECT sql FROM sqlite_master WHERE type='table' AND name='{table}'"
        )
        ddl_parts.append(cur.fetchone()[0] + ";")

    conn.close()

    return "\n\n".join(parts) + "\n\n" + "\n\n".join(ddl_parts)


# ───────────────────────────────────────────────────────────
#  System Prompt
# ───────────────────────────────────────────────────────────

SYSTEM_PROMPT_TEMPLATE = """\
You are an expert SQL analyst working with a SQLite e-commerce database.
Your job is to convert natural language questions into SQL queries — but ONLY
when the question is unambiguous.

═══════════════════════════════════════════════════
DATABASE SCHEMA
═══════════════════════════════════════════════════
{schema}

═══════════════════════════════════════════════════
YOUR TASK
═══════════════════════════════════════════════════
1. Read the user's question carefully.
2. Decide if the question is CLEAR or AMBIGUOUS given the schema above.

A question is **AMBIGUOUS** when:
  • It uses subjective or relative terms without a clear definition
    (e.g. "best", "top", "active", "popular", "big", "recent").
  • It lacks a specific time frame when one would materially change the result.
  • It could plausibly refer to more than one column or metric.
  • The filtering criteria are unclear (e.g. should cancelled/pending orders
    be included or excluded?).
  • It references a concept that does not map directly to a single schema
    element without further context.

A question is **CLEAR** when:
  • The intent maps to specific columns, aggregations, and filters with no
    reasonable alternative interpretation.
  • Time frames, metrics, and sort criteria are explicit or obvious.

3. Respond with **exactly one** JSON object (no markdown fencing, no
   commentary outside the JSON):

If CLEAR:
{{
  "status": "READY",
  "sql_query": "<valid SQLite SELECT query>",
  "clarification_question": null
}}

If AMBIGUOUS:
{{
  "status": "NEEDS_CLARIFICATION",
  "sql_query": null,
  "clarification_question": "<a concise question that resolves the ambiguity>"
}}

═══════════════════════════════════════════════════
RULES
═══════════════════════════════════════════════════
• Generate ONLY SELECT queries — never INSERT, UPDATE, DELETE, DROP, or DDL.
• Use SQLite-compatible syntax (e.g. date functions, string functions).
• When the user answers a clarification question, use their answer together
  with the original question to produce a READY response.
• The clarification question should be specific and give the user concrete
  options to choose from where possible.
• Always return raw JSON — no ```json fencing, no extra text.
"""


def build_system_prompt(db_path: str) -> str:
    """Build the full system prompt with the live schema embedded."""
    schema = extract_schema(db_path)
    return SYSTEM_PROMPT_TEMPLATE.format(schema=schema)


# ───────────────────────────────────────────────────────────
#  LLM Interaction
# ───────────────────────────────────────────────────────────

def call_llm(
    messages: list[dict[str, str]],
    *,
    temperature: float = 0.0,
    max_retries: int = 2,
) -> LLMResponse:
    """Send *messages* to the LLM and return a validated ``LLMResponse``.

    Uses JSON-mode (``response_format={"type": "json_object"}``) which is
    supported by both Gemini and Groq.  The raw JSON string is then parsed
    and validated through the Pydantic model.

    Retries up to *max_retries* times on parse/validation failures (the LLM
    occasionally returns slightly malformed JSON on the first try).
    """
    last_error: Exception | None = None

    for attempt in range(1, max_retries + 1):
        try:
            response = _get_client().chat.completions.create(
                model=LLM_MODEL,
                messages=messages,
                temperature=temperature,
                response_format={"type": "json_object"},
            )

            raw_content: str = response.choices[0].message.content.strip()

            # Parse and validate through Pydantic
            parsed = LLMResponse.model_validate_json(raw_content)
            return parsed

        except Exception as exc:
            last_error = exc
            if attempt < max_retries:
                continue
            raise RuntimeError(
                f"LLM returned invalid output after {max_retries} attempts.\n"
                f"Last error: {last_error}\n"
                f"Provider: {LLM_PROVIDER} | Model: {LLM_MODEL}"
            ) from last_error


# ───────────────────────────────────────────────────────────
#  Convenience: single-turn evaluation
# ───────────────────────────────────────────────────────────

def evaluate_question(
    db_path: str,
    conversation: list[dict[str, str]],
) -> tuple[LLMResponse, list[dict[str, str]]]:
    """Evaluate the current conversation and return the LLM response
    together with the updated message list (including the assistant reply).

    Parameters
    ----------
    db_path:
        Path to the SQLite database file.
    conversation:
        The running list of ``{"role": ..., "content": ...}`` dicts.
        Must contain at least one user message.

    Returns
    -------
    (response, updated_conversation)
    """
    system_msg = {"role": "system", "content": build_system_prompt(db_path)}
    full_messages = [system_msg] + conversation

    result = call_llm(full_messages)

    # Append the raw assistant reply so the next turn has context
    assistant_content = result.model_dump_json()
    conversation.append({"role": "assistant", "content": assistant_content})

    return result, conversation
