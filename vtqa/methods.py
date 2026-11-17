"""The three ways of answering, and the code that runs them for one example."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass

from .db import safe_execute
from .llm import LLMError
from .prompts import VARIANTS, direct_prompt, sql_prompt
from .scoring import normalize, rows_to_answer, same_answer
from .taxonomy import classify
from .verify import decide


@dataclass
class Config:
    k: int = 3                  # how many SQL queries to ask for
    tau: float = 0.66           # accept the answer only if confidence >= tau (0.66 = 2 of 3 agree)
    timeout_s: float = 3.0      # time limit for each SQL query
    max_rows_direct: int = 150  # rows of each table shown to the "direct" baseline
    skip_direct: bool = False
    max_tokens: int = 600
    n_sample_rows: int = 3      # example rows shown in the schema (0 = schema only)


def strip_thinking(text: str) -> str:
    return re.sub(r"<think>.*?</think>", "", text or "", flags=re.S | re.I)


def extract_sql(text: str) -> str:
    text = strip_thinking(text)
    m = re.search(r"```(?:sql|sqlite)?\s*(.*?)```", text, flags=re.S | re.I)
    if m and m.group(1).strip():
        return m.group(1).strip()
    m = re.search(r"\b(select|with)\b.*", text, flags=re.S | re.I)
    if m:
        return m.group(0).split("\n\n")[0].strip()
    return ""


def parse_direct(text: str):
    """Pull the list of answer values out of the model's JSON reply."""
    text = strip_thinking(text)
    m = re.search(r"\{.*\}", text, flags=re.S)
    if m:
        try:
            value = json.loads(m.group(0)).get("answer", [])
            if not isinstance(value, list):
                value = [value]
            return [normalize(v) for v in value]
        except (ValueError, AttributeError):
            pass
    line = text.strip().splitlines()[-1] if text.strip() else ""
    return [normalize(line)] if line else []


def tables_to_text(tables: dict, max_rows: int) -> str:
    parts = []
    for name, df in tables.items():
        parts.append(f"Table {name}:\n" + df.head(max_rows).to_csv(sep="|", index=False))
    return "\n".join(parts)


def make_candidates(llm, ex, conn, schema: str, cfg: Config) -> list:
    """Ask for cfg.k SQL queries (three prompt styles, then repeats at temperature 0.7) and run them."""
    out = []
    for i in range(cfg.k):
        variant = VARIANTS[i % len(VARIANTS)]
        attempt = i // len(VARIANTS)
        temperature = 0.0 if attempt == 0 else 0.7
        system, user = sql_prompt(variant, schema, ex.question, ex.notes, attempt)
        cand = {"variant": variant if attempt == 0 else f"{variant}#{attempt + 1}",
                "sql": "", "ok": False, "error": "", "answer": []}
        try:
            raw = llm.complete(system, user, temperature=temperature, max_tokens=cfg.max_tokens)
        except LLMError as e:
            cand["error"] = f"LLM error: {e}"
            out.append(cand)
            continue
        sql = extract_sql(raw)
        cand["sql"] = sql
        if not sql:
            cand["error"] = "no SQL found in the reply"
        else:
            res = safe_execute(conn, sql, timeout_s=cfg.timeout_s)
            cand["ok"], cand["error"] = res.ok, res.error
            cand["answer"] = rows_to_answer(res.rows) if res.ok else []
        out.append(cand)
    return out


def run_direct(llm, ex, cfg: Config) -> dict:
    """Baseline: give the model the table text and ask for the answer. No SQL, no checking."""
    tables = ex.display_tables or ex.tables
    system, user = direct_prompt(tables_to_text(tables, cfg.max_rows_direct), ex.question)
    try:
        raw = llm.complete(system, user, temperature=0.0, max_tokens=300)
    except LLMError as e:
        return {"answer": [], "correct": False, "error": f"LLM error: {e}"}
    ans = parse_direct(raw)
    return {"answer": ans, "correct": same_answer(ans, ex.gold_answer), "error": ""}


def process_example(llm, ex, conn, schema: str, cells: list, cfg: Config) -> dict:
    cands = make_candidates(llm, ex, conn, schema, cfg)
    first = cands[0]
    verdict = decide(ex.question, cands, cells, cfg.k)
    single_ok = first["ok"] and same_answer(first["answer"], ex.gold_answer)
    vote_ok = bool(verdict.answer) and same_answer(verdict.answer, ex.gold_answer)
    rec = {
        "id": ex.id, "question": ex.question, "difficulty": ex.difficulty,
        "gold": ex.gold_answer, "gold_sql": ex.gold_sql,
        "direct": None if cfg.skip_direct else run_direct(llm, ex, cfg),
        "candidates": cands,
        "single": {"answer": first["answer"], "correct": bool(single_ok),
                   "label": "correct" if single_ok else classify(first, ex.gold_answer)},
        "vote": {"answer": verdict.answer, "correct": bool(vote_ok)},
        "verdict": {"confidence": verdict.confidence, "flags": verdict.flags,
                    "n_valid": verdict.n_valid, "votes": verdict.votes},
    }
    return rec
