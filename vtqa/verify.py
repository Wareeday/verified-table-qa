"""The verifier: decide whether to trust an answer, or to abstain.

We ask the model for K different SQL queries and run all of them. Then:
  confidence = (number of valid queries that give the majority answer) / K
and it is halved when a sanity check fails. Queries that crash or return nothing count as
"disagreeing" (they stay in the denominator). Ties go to the earliest query (variant "plain").

Sanity checks (all cheap and symbolic, no extra LLM call):
  type_mismatch : a "how many" question must return exactly one number
  ungrounded    : a text answer must appear inside some table cell (it was not made up)
  empty / all_null : the query ran but returned nothing useful (such a query cannot vote)
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field

from .scoring import answer_key, is_numeric_string


@dataclass
class Verdict:
    answer: list
    confidence: float
    flags: list = field(default_factory=list)
    n_valid: int = 0
    votes: dict = field(default_factory=dict)


def question_kind(question: str) -> str:
    q = question.lower().strip()
    if q.startswith("how many") or re.search(r"\bnumber of\b", q):
        return "count"
    return "other"


def is_useful(cand: dict) -> bool:
    ans = cand.get("answer") or []
    return bool(cand.get("ok")) and len(ans) > 0 and not all(a == "null" for a in ans)


def soft_flags(question: str, answer: list, cells: list) -> list:
    flags = []
    if question_kind(question) == "count":
        if not (len(answer) == 1 and is_numeric_string(answer[0])):
            flags.append("type_mismatch")
    else:
        for a in answer:
            if is_numeric_string(a) or a == "null":
                continue  # numbers can be computed, so they need not appear in the table
            if not any(a in c for c in cells):
                flags.append("ungrounded")
                break
    return flags


def decide(question: str, candidates: list, cells: list, k: int) -> Verdict:
    valid = [c for c in candidates if is_useful(c)]
    if not valid:
        return Verdict(answer=[], confidence=0.0, flags=["no_valid_query"], n_valid=0, votes={})
    counts = Counter(answer_key(c["answer"]) for c in valid)
    top_key, top_n = counts.most_common(1)[0]  # ties -> first one seen
    answer = next(c["answer"] for c in valid if answer_key(c["answer"]) == top_key)
    flags = soft_flags(question, answer, cells)
    confidence = top_n / float(k)
    if flags:
        confidence *= 0.5
    votes = {" | ".join(key): n for key, n in counts.items()}
    return Verdict(answer=answer, confidence=round(confidence, 4), flags=flags, n_valid=len(valid), votes=votes)
