"""Turning query results and gold answers into comparable strings.

Rules (kept simple on purpose, so you can explain them):
  * text is lower-cased and whitespace is collapsed
  * numbers are compared after removing thousands commas and rounding to 2 decimals
  * an answer is a SET of values: order and duplicates do not matter
"""
from __future__ import annotations

import re

_NUM = re.compile(r"^[-+]?\d+(?:\.\d+)?$")


def _fmt_number(v: float) -> str:
    v = round(v, 2)
    if v == int(v):
        return str(int(v))
    return f"{v:.2f}".rstrip("0").rstrip(".")


def normalize(x) -> str:
    if x is None:
        return "null"
    if isinstance(x, bool):
        return str(x).lower()
    if isinstance(x, (int, float)):
        if x != x:  # NaN
            return "null"
        return _fmt_number(float(x))
    s = re.sub(r"\s+", " ", str(x)).strip().lower().strip("\"'")
    t = s.replace(",", "")
    if _NUM.match(t):
        return _fmt_number(float(t))
    return s


def is_numeric_string(s: str) -> bool:
    return bool(_NUM.match(s))


def rows_to_answer(rows) -> list:
    """Flatten every cell of every row into a list of normalised strings."""
    out = []
    for row in rows:
        for cell in row:
            out.append(normalize(cell))
    return out


def answer_key(ans) -> tuple:
    return tuple(sorted(set(ans)))


def same_answer(a, b) -> bool:
    return answer_key(a) == answer_key(b)
