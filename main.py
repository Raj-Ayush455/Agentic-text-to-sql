"""
Phase 3 — CLI Execution Loop
==============================
Interactive command-line interface that:
  1. Accepts a natural-language question from the user.
  2. Runs it through the Clarification Engine.
  3. If ambiguous → prints a clarification question and loops.
  4. Once READY → executes the SQL against the SQLite database and
     prints the results in a formatted table.
"""

from __future__ import annotations

import os
import sqlite3
import sys
import textwrap

from clarification_engine import evaluate_question
from config import LLM_MODEL, LLM_PROVIDER, require_api_key
from models import LLMResponse, QueryStatus

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ecommerce.db")

# ── ANSI helpers (gracefully degrade on Windows terminals that don't
#    support them) ────────────────────────────────────────────────────
BOLD = "\033[1m"
DIM = "\033[2m"
CYAN = "\033[36m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
RED = "\033[31m"
RESET = "\033[0m"


def _banner() -> None:
    print(
        f"""
{CYAN}╔══════════════════════════════════════════════════════════╗
║        Text-to-SQL  ·  Clarification Engine              ║
╚══════════════════════════════════════════════════════════╝{RESET}
  Provider : {LLM_PROVIDER}
  Model    : {LLM_MODEL}
  Database : {os.path.basename(DB_PATH)}

  Type a natural-language question and press Enter.
  Commands:  {DIM}/new{RESET}  — start a new question
             {DIM}/schema{RESET} — show database tables
             {DIM}/quit{RESET} — exit
"""
    )


def _print_results(cursor: sqlite3.Cursor) -> None:
    """Pretty-print the result set from an executed query."""
    rows = cursor.fetchall()
    if not rows:
        print(f"\n  {DIM}(query returned 0 rows){RESET}\n")
        return

    headers = [desc[0] for desc in cursor.description]
    # Compute column widths
    col_widths = [len(h) for h in headers]
    str_rows = []
    for row in rows:
        str_row = [str(v) if v is not None else "NULL" for v in row]
        str_rows.append(str_row)
        for i, val in enumerate(str_row):
            col_widths[i] = max(col_widths[i], len(val))

    # Header
    header_line = "  ".join(h.ljust(w) for h, w in zip(headers, col_widths))
    separator = "  ".join("─" * w for w in col_widths)
    print(f"\n  {BOLD}{header_line}{RESET}")
    print(f"  {separator}")

    # Rows
    for sr in str_rows:
        line = "  ".join(v.ljust(w) for v, w in zip(sr, col_widths))
        print(f"  {line}")

    print(f"\n  {DIM}({len(rows)} row{'s' if len(rows) != 1 else ''}){RESET}\n")


def _execute_sql(sql: str) -> None:
    """Execute a SELECT query against the database and print results."""
    conn = sqlite3.connect(DB_PATH)
    try:
        cur = conn.cursor()
        cur.execute(sql)
        _print_results(cur)
    except sqlite3.Error as exc:
        print(f"\n  {RED}SQL Error:{RESET} {exc}")
        print(f"  {DIM}Query: {sql}{RESET}\n")
    finally:
        conn.close()


def _show_schema() -> None:
    """Print a compact view of all tables and their columns."""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
    )
    tables = [r[0] for r in cur.fetchall()]

    print(f"\n  {BOLD}Database Tables:{RESET}")
    for table in tables:
        cur.execute(f"PRAGMA table_info('{table}')")
        cols = cur.fetchall()
        col_names = ", ".join(c[1] for c in cols)
        cur.execute(f"SELECT COUNT(*) FROM {table}")
        count = cur.fetchone()[0]
        print(f"    {CYAN}{table}{RESET} ({count} rows)")
        print(f"      ↳ {col_names}")
    print()
    conn.close()


# ───────────────────────────────────────────────────────────
#  Main Loop
# ───────────────────────────────────────────────────────────

def main() -> None:
    require_api_key()

    if not os.path.exists(DB_PATH):
        print(
            f"{RED}Database not found at {DB_PATH}.{RESET}\n"
            "Run  python setup_database.py  first."
        )
        sys.exit(1)

    _banner()

    conversation: list[dict[str, str]] = []
    awaiting_clarification = False

    while True:
        try:
            if awaiting_clarification:
                prompt_text = f"{YELLOW}  ↳ Your answer: {RESET}"
            else:
                prompt_text = f"{GREEN}❯ {RESET}"

            user_input = input(prompt_text).strip()
        except (EOFError, KeyboardInterrupt):
            print(f"\n{DIM}Goodbye!{RESET}")
            break

        if not user_input:
            continue

        # ── Slash commands ──────────────────────────────────
        lower = user_input.lower()
        if lower in ("/quit", "/exit", "/q"):
            print(f"{DIM}Goodbye!{RESET}")
            break
        if lower in ("/new", "/reset"):
            conversation = []
            awaiting_clarification = False
            print(f"{DIM}  ✓ Conversation reset. Ask a new question.{RESET}\n")
            continue
        if lower == "/schema":
            _show_schema()
            continue

        # ── Append user message ─────────────────────────────
        conversation.append({"role": "user", "content": user_input})

        # ── Call the Clarification Engine ───────────────────
        try:
            print(f"{DIM}  ⏳ Thinking...{RESET}")
            result, conversation = evaluate_question(DB_PATH, conversation)
        except Exception as exc:
            print(f"\n  {RED}Engine error:{RESET} {exc}\n")
            # Remove the failed user message so they can retry
            conversation.pop()
            continue

        # ── Handle the response ─────────────────────────────
        if result.status == QueryStatus.NEEDS_CLARIFICATION:
            awaiting_clarification = True
            print(
                f"\n  {YELLOW}🤔 Clarification needed:{RESET}\n"
                f"  {result.clarification_question}\n"
            )

        else:  # READY
            awaiting_clarification = False
            sql = result.sql_query

            print(f"\n  {GREEN}✅ Generated SQL:{RESET}")
            # Indent the SQL for readability
            for line in sql.strip().splitlines():
                print(f"  {DIM}{line}{RESET}")

            print(f"\n  {BOLD}Results:{RESET}")
            _execute_sql(sql)

            # Reset conversation for the next question
            conversation = []
            print(f"  {DIM}(Ready for your next question){RESET}\n")


if __name__ == "__main__":
    main()
