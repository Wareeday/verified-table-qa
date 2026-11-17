"""Small helpers around SQLite: build a database, describe it to the model, run SQL safely."""
from __future__ import annotations

import re
import sqlite3
import time
from dataclasses import dataclass

from .scoring import normalize

# Column names that clash with SQL words get a suffix.
_SQL_WORDS = {
    "order", "group", "index", "select", "from", "where", "table", "limit", "key", "values",
    "default", "check", "references", "primary", "foreign", "union", "join", "on", "as", "by",
    "desc", "asc", "case", "when", "then", "else", "end", "null", "not", "and", "or", "in",
    "is", "like", "between", "exists", "all", "any", "distinct", "having", "offset", "set",
}


def sanitize_name(name) -> str:
    text = str(name).replace("%", " percent ").replace("#", " number ")
    s = re.sub(r"[^0-9a-zA-Z]+", "_", text.strip().lower()).strip("_")
    if not s:
        s = "col"
    if s[0].isdigit():
        s = "c_" + s
    if s in _SQL_WORDS:
        s = s + "_col"
    return s


def sanitize_columns(cols) -> list:
    """Clean, unique, SQL-friendly column names."""
    used, out = set(), []
    for c in cols:
        base = sanitize_name(c)
        name, i = base, 2
        while name in used:
            name = f"{base}_{i}"
            i += 1
        used.add(name)
        out.append(name)
    return out


def load_tables(tables: dict) -> sqlite3.Connection:
    """Put DataFrames into an in-memory SQLite database and make it read-only."""
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    for name, df in tables.items():
        df.to_sql(name, conn, index=False, if_exists="replace")
    conn.commit()
    conn.execute("PRAGMA query_only = ON")  # from now on nothing can change the data
    return conn


def describe_schema(conn: sqlite3.Connection, n_sample_rows: int = 3) -> str:
    """CREATE TABLE text plus a few example rows (set n_sample_rows=0 for schema-only)."""
    cur = conn.cursor()
    names = [r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
    parts = []
    for t in names:
        ddl = cur.execute("SELECT sql FROM sqlite_master WHERE name=?", (t,)).fetchone()[0]
        parts.append(ddl.strip() + ";")
        if n_sample_rows > 0:
            rows = cur.execute(f'SELECT * FROM "{t}" LIMIT {int(n_sample_rows)}').fetchall()
            if rows:
                cols = [d[0] for d in cur.description]
                parts.append(f"-- example rows from {t} ({' | '.join(cols)}):")
                for r in rows:
                    parts.append("--   " + " | ".join("NULL" if v is None else str(v)[:40] for v in r))
    return "\n".join(parts)


def all_cells(conn: sqlite3.Connection, max_cells: int = 20000) -> list:
    """Every cell value (normalised). Used by the 'is the answer really in the table?' check."""
    cells = []
    names = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")]
    for t in names:
        for row in conn.execute(f'SELECT * FROM "{t}"'):
            for v in row:
                if v is not None:
                    cells.append(normalize(v))
            if len(cells) >= max_cells:
                return cells
    return cells


@dataclass
class ExecResult:
    ok: bool
    rows: list
    error: str = ""


def safe_execute(conn: sqlite3.Connection, sql: str, timeout_s: float = 3.0, max_rows: int = 200) -> ExecResult:
    """Run one read-only query with a time limit. Never raises."""
    text = (sql or "").strip()
    if text.endswith(";"):
        text = text[:-1].rstrip()
    first = re.match(r"\s*(\w+)", text)
    if not first or first.group(1).lower() not in ("select", "with"):
        return ExecResult(False, [], "only SELECT/WITH queries are allowed")
    deadline = time.time() + timeout_s
    conn.set_progress_handler(lambda: 1 if time.time() > deadline else 0, 20000)
    try:
        cur = conn.execute(text)
        rows = cur.fetchmany(max_rows)
        return ExecResult(True, rows, "")
    except (sqlite3.Error, sqlite3.Warning) as e:
        return ExecResult(False, [], str(e))
    finally:
        conn.set_progress_handler(None, 0)
