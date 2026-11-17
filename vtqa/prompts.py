"""All prompts live here, so you can read and change them in one place.

The "Question:" line must stay on its own line starting with "Question: ".
(The offline mock model uses it to find the question.)
"""
from __future__ import annotations

SYSTEM_SQL = (
    "You are an expert data analyst who writes SQLite queries. "
    "You only use the tables and columns that appear in the schema."
)
SYSTEM_DIRECT = "You are a careful data analyst. You answer questions about tables."

# Three different ways of asking for SQL. Their answers are compared later (voting).
VARIANTS = ["plain", "plan", "careful"]

_RULES = """Rules:
- Use column names exactly as they appear in the schema.
- Compare numeric columns as numbers and text columns as text.
- "How many" -> COUNT. "Total" -> SUM. "Average" -> AVG.
- "Highest / lowest / first / last / most / least" -> ORDER BY ... LIMIT 1.
- If the question names a person, team, place or product, filter on the matching text column."""


def sql_prompt(variant: str, schema: str, question: str, notes: str = "", attempt: int = 0):
    """Return (system, user) for one SQL-writing attempt."""
    head = f"Database schema (SQLite):\n{schema}\n"
    if notes:
        head += f"\n{notes}\n"
    head += f"\nQuestion: {question}\n\n"
    base = (
        "Write ONE SQLite SELECT query that answers the question. "
        "Select only the column(s) that contain the answer, with no extra columns."
    )
    if variant == "plain":
        tail = base + " Return the query inside a ```sql code block and nothing else."
    elif variant == "plan":
        tail = (
            base + " First write 2-3 short lines saying which tables, columns and filters you need. "
            "Then give the final query inside a ```sql code block."
        )
    elif variant == "careful":
        tail = _RULES + "\n\n" + base + " Return the query inside a ```sql code block and nothing else."
    else:
        raise ValueError(f"unknown variant: {variant}")
    user = head + tail
    if attempt:
        user += f"\n(Attempt {attempt + 1}.)"
    return SYSTEM_SQL, user


def direct_prompt(table_text: str, question: str):
    """The baseline: show the whole table to the model and ask for the answer."""
    user = (
        f"{table_text}\n"
        f"Question: {question}\n\n"
        "Answer using only the table(s). Reply with JSON only, like "
        '{"answer": ["value1", "value2"]}. Use a list even for one value. Write numbers as plain digits.'
    )
    return SYSTEM_DIRECT, user
