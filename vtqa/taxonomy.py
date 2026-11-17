"""Automatic first-pass labels for WHY a query was wrong (you refine them by hand later)."""
from __future__ import annotations


def classify(cand: dict, gold: list) -> str:
    if not cand.get("ok"):
        e = (cand.get("error") or "").lower()
        if e.startswith("llm error"):
            return "llm_error"
        if e.startswith("no sql"):
            return "no_sql_found"
        if e.startswith("only select"):
            return "not_a_select_query"
        if "no such column" in e:
            return "unknown_column"
        if "no such table" in e:
            return "unknown_table"
        if "interrupted" in e:
            return "timeout"
        if "syntax error" in e or "incomplete input" in e or "unrecognized token" in e or " near " in e:
            return "syntax_error"
        return "other_execution_error"
    ans = cand.get("answer") or []
    if not ans or all(a == "null" for a in ans):
        return "empty_result"
    if len(set(ans)) != len(set(gold)):
        return "wrong_number_of_values"
    return "wrong_value"
